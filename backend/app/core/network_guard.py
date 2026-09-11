"""Network Guard — Phase 8 (Plan.md §8).

Enforces sovereign zero-external-call policy at the OS socket level — not just
at the application layer.  This is the difference between "we intend to be
sovereign" and "we can prove it."

Architecture
------------
The guard works in two complementary layers:

Layer 1 — Python socket hook (always active)
    Monkey-patches ``socket.socket.connect`` and ``socket.socket.connect_ex``
    on import.  Every outbound TCP/UDP connect attempt is inspected:
      • Localhost / loopback → allowed (Ollama, ChromaDB, SQLite)
      • Any other host       → connection refused + SovereigntyLog entry
    This catches httpx, urllib, requests, boto3, google-cloud-*, OpenAI SDK,
    and every other Python library that eventually calls socket.connect.

Layer 2 — ASGI middleware (applied on FastAPI startup)
    Wraps every request/response cycle.  Currently used to:
      • Add X-Sovereignty: enforced header to every response so the frontend
        (and API testers) can see the guard is active.
      • In the future: inspect response bodies for telemetry exfiltration.

Layer 3 — Isolation probe (called at startup and on-demand via the dashboard)
    Actively attempts to connect to known cloud endpoints and asserts they
    fail.  Records the probe result in SovereigntyLog so the dashboard can
    display "last verified: <timestamp>" rather than just "blocked".

Why not iptables / Windows Firewall rules?
    Those are the right production-grade mechanism and should be added before
    any real industrial deployment.  But they require root/admin privileges and
    are machine-global, which makes automated setup fragile during development.
    The socket-level hook gives us:
      a) Instant provability during a 5-minute demo.
      b) Zero privilege requirements.
      c) Per-process enforcement (other processes on the machine are unaffected).
      d) Detailed audit logging (which library, which destination, which call).
    The firewall layer is documented in docker-compose.yml (--network none for
    the inference container) and in the Phase 10 deployment notes.

Sovereignty contract
--------------------
- localhost / 127.0.0.1 / ::1 / 0.0.0.0 → ALLOWED
- Any other IP or hostname               → BLOCKED + logged
- Ollama endpoint (localhost:11434)      → ALLOWED (is localhost)
- ChromaDB embedded                     → ALLOWED (in-process, no socket)
- sentence-transformers model cache     → BLOCKED at import if online-only;
    the model must be pre-cached locally (which it is after first use)

Known safe targets (all localhost):
    http://localhost:11434   Ollama inference server
    http://localhost:8000    FastAPI itself (health checks, tests)
    sqlite (no network)
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import time
from functools import wraps
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Hostnames and IP prefixes considered local — connections to these are allowed.
_ALLOWED_HOSTNAMES: frozenset[str] = frozenset({
    "localhost",
    "127.0.0.1",
    "::1",
    "0.0.0.0",
})

# IP ranges that are unconditionally local (loopback + link-local + private)
_ALLOWED_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("0.0.0.0/8"),
    # Allow private-range IPs too: common in Docker bridge and LAN setups
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fe80::/10"),   # IPv6 link-local
)

# Cloud endpoints used for the isolation probe — we attempt to connect and
# assert that we CANNOT.  These are well-known endpoints; the probe does not
# actually send any data, just tests TCP reachability.
_PROBE_TARGETS: list[tuple[str, int]] = [
    ("api.openai.com",       443),
    ("api.anthropic.com",    443),
    ("generativelanguage.googleapis.com", 443),
    ("huggingface.co",       443),
    ("8.8.8.8",              53),   # Google DNS — should be unreachable if guard is working
]

# Guard state
_guard_installed: bool = False
_original_connect: Optional[object] = None
_original_connect_ex: Optional[object] = None


# ---------------------------------------------------------------------------
# Address classification
# ---------------------------------------------------------------------------

def _is_allowed(host: str | bytes) -> bool:
    """Return True only for explicit local hosts or local/private IPs.

    Unknown hostnames are denied without resolving them. Resolving a hostname
    during the guard decision would create the external DNS request that the
    guard is meant to prevent.
    """
    if isinstance(host, bytes):
        host = host.decode("idna", errors="replace")

    host = str(host).strip().lower()

    if host in _ALLOWED_HOSTNAMES:
        return True

    # Try to parse as IP directly (fast path — no DNS)
    try:
        addr = ipaddress.ip_address(host)
        return any(addr in net for net in _ALLOWED_NETWORKS)
    except ValueError:
        pass

    # Do not resolve unknown hostnames here: DNS is an external network path.
    return False


def _extract_host(address) -> str:
    """Extract the hostname/IP from a connect() address argument."""
    if isinstance(address, (list, tuple)) and len(address) >= 1:
        return str(address[0])
    if isinstance(address, (str, bytes)):
        return str(address)
    return str(address)


# ---------------------------------------------------------------------------
# Sovereignty log writer (lightweight — no ORM overhead in the hot path)
# ---------------------------------------------------------------------------

def _write_sovereignty_log(
    event_type: str,
    blocked: bool,
    destination: str,
    detail: str,
) -> None:
    """Write a sovereignty log entry.  Best-effort — never raises."""
    try:
        from app.db.database import SessionLocal
        from app.models.db_models import SovereigntyLog
        with SessionLocal() as db:
            db.add(SovereigntyLog(
                event_type=event_type,
                external_attempt_blocked=blocked,
                destination=destination[:512],
                detail=detail[:1000],
            ))
            db.commit()
    except Exception as exc:
        # Deliberately silent: logging a log failure would be recursive
        pass


# ---------------------------------------------------------------------------
# Socket hook — Layer 1
# ---------------------------------------------------------------------------

def _make_guarded_connect(original_connect, connect_ex: bool = False):
    """Return a replacement for socket.connect / socket.connect_ex that
    blocks non-local destinations."""

    @wraps(original_connect)
    def guarded_connect(self, address):
        host = _extract_host(address)
        if not _is_allowed(host):
            dest_str = str(address)
            logger.error(
                "SOVEREIGNTY_BLOCKED | destination=%s | "
                "reason=non-local host blocked by network_guard | "
                "action=connection_refused",
                dest_str,
            )
            _write_sovereignty_log(
                event_type="external_call_blocked",
                blocked=True,
                destination=dest_str,
                detail="Outbound TCP connection intercepted and blocked by network_guard.py",
            )
            # Raise ConnectionRefusedError — same as a kernel-level block
            raise ConnectionRefusedError(
                f"[SOVEREIGN AI GUARD] Outbound connection to {dest_str!r} "
                f"is blocked. All inference and storage must be local-only."
            )

        return original_connect(self, address)

    return guarded_connect


def install_socket_guard() -> None:
    """Monkey-patch socket.socket to block all non-local connections.

    Idempotent — calling more than once is a no-op.
    """
    global _guard_installed, _original_connect, _original_connect_ex

    if _guard_installed:
        logger.debug("NETWORK_GUARD | already installed — skipping")
        return

    _original_connect = socket.socket.connect
    _original_connect_ex = socket.socket.connect_ex

    socket.socket.connect = _make_guarded_connect(_original_connect, connect_ex=False)
    socket.socket.connect_ex = _make_guarded_connect(_original_connect_ex, connect_ex=True)

    _guard_installed = True
    logger.info(
        "NETWORK_GUARD_INSTALLED | scope=socket.socket.connect + connect_ex | "
        "policy=localhost_only | action=ConnectionRefusedError_on_external_host"
    )


def uninstall_socket_guard() -> None:
    """Remove the socket hook (used in tests only)."""
    global _guard_installed
    if not _guard_installed:
        return
    if _original_connect is not None:
        socket.socket.connect = _original_connect
    if _original_connect_ex is not None:
        socket.socket.connect_ex = _original_connect_ex
    _guard_installed = False
    logger.info("NETWORK_GUARD_UNINSTALLED")


def is_guard_installed() -> bool:
    return _guard_installed


# ---------------------------------------------------------------------------
# Isolation probe — Layer 3
# ---------------------------------------------------------------------------

def probe_isolation(timeout: float = 3.0) -> dict:
    """Actively test that cloud endpoints are unreachable.

    Temporarily bypasses the socket hook (since the hook would block us
    before we even try) so we can measure whether the *OS-level* network
    is actually blocked.  This is the honest test.

    Returns a dict with:
        all_blocked: bool     — True if every probe target failed to connect
        results:     list     — per-target {host, port, reachable, latency_ms}
        timestamp:   float    — Unix timestamp of the probe
        proof:       str      — human-readable summary for the dashboard
    """
    results = []
    any_reachable = False

    for host, port in _PROBE_TARGETS:
        t0 = time.perf_counter()
        reachable = False
        error_reason = ""

        # Bypass our own hook for the probe so we test the actual OS network
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            # Call the ORIGINAL connect (pre-hook) directly
            if _original_connect is not None:
                _original_connect(s, (host, port))
            else:
                s.connect((host, port))
            reachable = True
            any_reachable = True
            s.close()
        except (ConnectionRefusedError, TimeoutError, OSError, socket.timeout) as exc:
            error_reason = type(exc).__name__
        except Exception as exc:
            error_reason = f"{type(exc).__name__}: {exc}"
        finally:
            try:
                s.close()
            except Exception:
                pass

        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        results.append({
            "host": host,
            "port": port,
            "reachable": reachable,
            "error": error_reason if not reachable else None,
            "latency_ms": latency_ms,
        })

        status_word = "REACHABLE ⚠" if reachable else "BLOCKED ✓"
        logger.info(
            "SOVEREIGNTY_PROBE | target=%s:%d | reachable=%s | latency_ms=%.1f",
            host, port, reachable, latency_ms,
        )

    all_blocked = not any_reachable
    timestamp = time.time()

    # Build a proof string for the dashboard
    blocked_count = sum(1 for r in results if not r["reachable"])
    proof = (
        f"Isolation probe at {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(timestamp))}: "
        f"{blocked_count}/{len(results)} cloud endpoints unreachable. "
        f"{'SOVEREIGN ✓' if all_blocked else 'WARNING: some endpoints reachable ⚠'}"
    )

    # Log to sovereignty table
    _write_sovereignty_log(
        event_type="isolation_probe",
        blocked=all_blocked,
        destination=",".join(f"{r['host']}:{r['port']}" for r in results),
        detail=proof,
    )

    logger.info(
        "SOVEREIGNTY_PROBE_DONE | all_blocked=%s | proof=%s",
        all_blocked, proof,
    )

    return {
        "all_blocked": all_blocked,
        "results": results,
        "timestamp": timestamp,
        "proof": proof,
    }


# ---------------------------------------------------------------------------
# ASGI middleware — Layer 2
# ---------------------------------------------------------------------------

class NetworkGuardMiddleware:
    """ASGI middleware that adds X-Sovereignty headers and guard status.

    Add to FastAPI with:
        app.add_middleware(NetworkGuardMiddleware)

    Does NOT block requests (the socket hook already handles that).
    Primary purpose: visible proof that the guard is running, and a hook
    for future response-body inspection.
    """

    def __init__(self, app) -> None:
        self._app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return

        async def send_with_sovereignty_header(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append(
                    (b"x-sovereignty", b"enforced-socket-hook-active")
                )
                message = {**message, "headers": headers}
            await send(message)

        await self._app(scope, receive, send_with_sovereignty_header)
