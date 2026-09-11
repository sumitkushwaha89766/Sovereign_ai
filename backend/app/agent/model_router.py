"""Model Router — Phase 7.3 (Plan.md §7.3).

Maps a TaskType to the correct local model endpoint by reading
``backend/app/agent/model_registry.yaml`` at startup.

Architecture rule (§4.4): the router is CONFIG-DRIVEN.
No model name or endpoint may be hardcoded in this file or anywhere else in
the codebase.  To change a model, edit model_registry.yaml only.

Every routing decision is structured-logged with:
    - task_type         — what was requested
    - selected_model    — name resolved from the registry
    - endpoint          — Ollama (or local) URL
    - reason            — which registry entry matched and why
    - fallback_used     — True if primary choice failed and we fell back
    - latency_ms        — wall-clock time for the Ollama call (0 for dry-runs)
    - success           — True / False

Sovereignty: the only allowed outbound targets are localhost endpoints listed
in model_registry.yaml.  Any other host is a hard error.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
import yaml

from app.agent.task_classifier import TaskType
from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Locate the registry file relative to this source file so it works regardless
# of the working directory the server is started from.
# ---------------------------------------------------------------------------

_REGISTRY_PATH = Path(__file__).parent / "model_registry.yaml"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ModelConfig:
    """One entry from the registry (one task type)."""
    task_type: str
    name: str
    endpoint: str
    note: str = ""
    fallback: Optional[dict[str, str]] = None


@dataclass
class RoutingDecision:
    """Everything the caller and the logs need to know about a routing choice."""
    task_type: TaskType
    model_name: str
    endpoint: str
    reason: str
    fallback_used: bool = False
    fallback_reason: Optional[str] = None
    latency_ms: float = 0.0
    success: bool = True
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Registry loader
# ---------------------------------------------------------------------------

def _load_registry(path: Path = _REGISTRY_PATH) -> dict[str, ModelConfig]:
    """Parse model_registry.yaml and return a task-type → ModelConfig map.

    Called once at import time; call reload_registry() to hot-reload during
    development without restarting the server.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"model_registry.yaml not found at {path}. "
            "Create it before starting the backend."
        )
    with path.open("r", encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh)

    models_raw: dict[str, Any] = raw.get("models", {})
    if not models_raw:
        raise ValueError("model_registry.yaml has no 'models' key or it is empty.")

    registry: dict[str, ModelConfig] = {}
    for task_type, cfg in models_raw.items():
        if not isinstance(cfg, dict):
            raise ValueError(f"Registry entry for '{task_type}' must be a mapping.")
        for required in ("name", "endpoint"):
            if required not in cfg:
                raise ValueError(
                    f"Registry entry '{task_type}' is missing required key '{required}'."
                )
        registry[task_type] = ModelConfig(
            task_type=task_type,
            name=cfg["name"],
            endpoint=cfg["endpoint"],
            note=cfg.get("note", ""),
            fallback=cfg.get("fallback"),
        )

    logger.info(
        "MODEL_REGISTRY_LOADED | path=%s | task_types=%s",
        path,
        list(registry.keys()),
    )
    return registry


# ---------------------------------------------------------------------------
# Sovereignty guard
# ---------------------------------------------------------------------------

_ALLOWED_SCHEMES = {"http", "https", "local"}


def _assert_local_endpoint(endpoint: str, model_name: str) -> None:
    """Raise if endpoint is not localhost or the special 'local' sentinel.

    This is a defence-in-depth check so a misconfigured registry can never
    cause an outbound external call.
    """
    if endpoint == "local":
        return   # in-process model, no network
    parsed = urlparse(endpoint)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(
            f"Sovereignty violation: model '{model_name}' has a non-HTTP endpoint '{endpoint}'."
        )
    host = parsed.hostname or ""
    if host not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError(
            f"Sovereignty violation: model '{model_name}' endpoint '{endpoint}' "
            f"resolves to non-localhost host '{host}'. "
            "Only localhost endpoints are permitted."
        )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

class ModelRouter:
    """Config-driven model router.

    All model names and endpoints come from model_registry.yaml — never
    hardcoded here.

    Usage (synchronous)::

        router = ModelRouter()

        # Resolve only (no network call) — for planning / logging
        decision = router.resolve(TaskType.REASONING)

        # Resolve + call Ollama
        decision, response_text = router.call(TaskType.REASONING, prompt="...")
    """

    def __init__(self, registry_path: Path = _REGISTRY_PATH) -> None:
        self._registry: dict[str, ModelConfig] = _load_registry(registry_path)

    def reload_registry(self) -> None:
        """Hot-reload the registry without restarting the server."""
        self._registry = _load_registry(_REGISTRY_PATH)
        logger.info("MODEL_REGISTRY_RELOADED")

    # ------------------------------------------------------------------
    # Core routing
    # ------------------------------------------------------------------

    def resolve(self, task_type: TaskType) -> RoutingDecision:
        """Return a RoutingDecision for *task_type* without making a network call.

        Falls back to the 'reasoning' entry if the specific task type has no
        dedicated registry entry (e.g. 'embedding' redirected to 'reasoning'
        during hardware-constrained operation).
        """
        t0 = time.perf_counter()
        key = str(task_type)
        cfg: Optional[ModelConfig] = self._registry.get(key)
        fallback_used = False
        fallback_reason: Optional[str] = None

        if cfg is None:
            # Fallback: use the reasoning model (always present)
            fallback_key = str(TaskType.REASONING)
            cfg = self._registry.get(fallback_key)
            if cfg is None:
                raise RuntimeError(
                    "model_registry.yaml has no 'reasoning' entry — cannot route."
                )
            fallback_used = True
            fallback_reason = (
                f"No registry entry for task_type='{key}'; "
                f"fell back to 'reasoning' entry ({cfg.name})"
            )

        _assert_local_endpoint(cfg.endpoint, cfg.name)

        reason = (
            f"registry['{cfg.task_type}'].name={cfg.name!r} | "
            f"endpoint={cfg.endpoint!r}"
        )
        if cfg.note:
            reason += f" | note={cfg.note!r}"

        latency_ms = round((time.perf_counter() - t0) * 1000, 2)

        decision = RoutingDecision(
            task_type=task_type,
            model_name=cfg.name,
            endpoint=cfg.endpoint,
            reason=reason,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            latency_ms=latency_ms,
            success=True,
        )

        self._log(decision)
        return decision

    # ------------------------------------------------------------------
    # Ollama call
    # ------------------------------------------------------------------

    def call(
        self,
        task_type: TaskType,
        prompt: str,
        *,
        system: Optional[str] = None,
        images: Optional[list[str]] = None,   # base64-encoded for vision tasks
        timeout: Optional[float] = None,
    ) -> tuple[RoutingDecision, str]:
        """Resolve the model for *task_type* and call Ollama's /api/generate.

        Returns (RoutingDecision, response_text).

        Raises on network errors after logging them; the planner should catch
        and surface appropriate user-facing messages.

        Note: this is a synchronous blocking call.  The FastAPI route that
        invokes the agent should run it in a thread pool (``asyncio.to_thread``
        or ``BackgroundTasks``) to avoid blocking the event loop.
        """
        decision = self.resolve(task_type)
        t_call = time.perf_counter()

        if decision.endpoint == "local":
            # In-process model (e.g. sentence-transformers for embedding).
            # The actual call is handled by the embedding layer; return empty.
            decision.latency_ms = round((time.perf_counter() - t_call) * 1000, 2)
            logger.info(
                "MODEL_CALL_LOCAL | model=%s | task_type=%s",
                decision.model_name,
                decision.task_type,
            )
            return decision, ""

        payload: dict[str, Any] = {
            "model": decision.model_name,
            "prompt": prompt,
            "stream": False,
            # gemma4:e2b can place its entire bounded generation in a thinking
            # channel, leaving Ollama's `response` empty. The planner requires
            # the visible response for JSON/labelled-section parsing.
            "think": False,
            "options": {
                "num_predict": settings.model_max_output_tokens,
                "temperature": 0.1,
            },
        }
        if system:
            payload["system"] = system
        if images:
            payload["images"] = images

        url = decision.endpoint.rstrip("/") + "/api/generate"
        request_timeout = timeout if timeout is not None else settings.model_call_timeout_seconds
        cfg = self._registry.get(str(task_type))
        attempts = [(decision.model_name, decision.endpoint)]
        if cfg and cfg.fallback:
            fallback_name = cfg.fallback.get("name")
            fallback_endpoint = cfg.fallback.get("endpoint")
            if not fallback_name or not fallback_endpoint:
                raise ValueError(
                    f"Invalid fallback configuration for task_type='{task_type}'"
                )
            _assert_local_endpoint(fallback_endpoint, fallback_name)
            attempts.append((fallback_name, fallback_endpoint))

        last_error: Exception | None = None
        response_text = ""
        for attempt_index, (model_name, endpoint) in enumerate(attempts):
            payload["model"] = model_name
            attempt_url = endpoint.rstrip("/") + "/api/generate"
            for retry_index in range(2):
                try:
                    with httpx.Client(timeout=request_timeout) as client:
                        resp = client.post(attempt_url, json=payload)
                    resp.raise_for_status()
                    response_text = resp.json().get("response", "")
                    decision.success = True
                    if attempt_index:
                        decision.fallback_used = True
                        decision.fallback_reason = str(last_error)
                        decision.model_name = model_name
                        decision.endpoint = endpoint
                        logger.warning(
                            "MODEL_FALLBACK_USED | task_type=%s | model=%s | error=%s",
                            decision.task_type, model_name, last_error,
                        )
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    decision.success = False
                    if retry_index == 0:
                        logger.warning(
                            "MODEL_CALL_RETRY | model=%s | task_type=%s | error=%s",
                            model_name, decision.task_type, exc,
                        )
            if decision.success:
                break

        if not decision.success:
            decision.error = str(last_error)
            decision.latency_ms = round((time.perf_counter() - t_call) * 1000, 2)
            logger.error(
                "MODEL_CALL_FAILED | model=%s | task_type=%s | endpoint=%s "
                "| latency_ms=%.2f | error=%s",
                decision.model_name, decision.task_type, decision.endpoint,
                decision.latency_ms, last_error,
            )
            raise last_error  # type: ignore[misc]

        decision.latency_ms = round((time.perf_counter() - t_call) * 1000, 2)
        logger.info(
            "MODEL_CALL_SUCCESS | model=%s | task_type=%s | endpoint=%s "
            "| latency_ms=%.2f | response_len=%d",
            decision.model_name,
            decision.task_type,
            decision.endpoint,
            decision.latency_ms,
            len(response_text),
        )
        return decision, response_text

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _log(self, d: RoutingDecision) -> None:
        """Emit the structured routing-decision log entry required by the SKILL."""
        logger.info(
            "MODEL_ROUTED | task_type=%s | model=%s | endpoint=%s | reason=%s "
            "| fallback=%s | fallback_reason=%s | latency_ms=%.2f | success=%s",
            d.task_type,
            d.model_name,
            d.endpoint,
            d.reason,
            d.fallback_used,
            d.fallback_reason,
            d.latency_ms,
            d.success,
        )

    def available_task_types(self) -> list[str]:
        """Return the task types currently registered."""
        return list(self._registry.keys())

    def registry_summary(self) -> dict[str, dict[str, str]]:
        """Return a safe summary (no secrets) of the loaded registry."""
        return {
            k: {"name": v.name, "endpoint": v.endpoint}
            for k, v in self._registry.items()
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_router = ModelRouter()


def get_router() -> ModelRouter:
    """Return the shared ModelRouter singleton.

    Use this instead of constructing new instances so the registry is only
    loaded from disk once per process.
    """
    return _router
