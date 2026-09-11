"""Unit tests for the Model Router — Phase 9 (Plan.md §9, §7.3).

Covers config-driven resolution, the reasoning fallback for unmapped task
types, and the sovereignty guard that rejects any non-localhost endpoint.

``resolve()`` makes no network call, so these tests are fully offline. We build
routers from temporary registry files (via tmp_path) so we never depend on or
mutate the shipped singleton, plus one test that validates the real shipped
``model_registry.yaml``.
"""

from __future__ import annotations

import textwrap

import pytest

from app.agent.model_router import (
    ModelRouter,
    _assert_local_endpoint,
    get_router,
)
from app.agent.task_classifier import TaskType


def _write_registry(tmp_path, body: str):
    path = tmp_path / "model_registry.yaml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Sovereignty guard
# ---------------------------------------------------------------------------

def test_assert_local_endpoint_allows_localhost():
    # Should not raise for any localhost form or the "local" sentinel.
    _assert_local_endpoint("http://localhost:11434", "m")
    _assert_local_endpoint("http://127.0.0.1:11434", "m")
    _assert_local_endpoint("local", "m")


def test_assert_local_endpoint_rejects_external_host():
    with pytest.raises(ValueError, match="Sovereignty violation"):
        _assert_local_endpoint("http://api.openai.com/v1", "m")


def test_assert_local_endpoint_rejects_non_http_scheme():
    with pytest.raises(ValueError, match="Sovereignty violation"):
        _assert_local_endpoint("ftp://localhost/x", "m")


def test_router_load_rejects_external_endpoint_at_resolve(tmp_path):
    path = _write_registry(tmp_path, """
        models:
          reasoning:
            name: evil-model
            endpoint: http://evil.example.com
    """)
    router = ModelRouter(registry_path=path)
    with pytest.raises(ValueError, match="Sovereignty violation"):
        router.resolve(TaskType.REASONING)


# ---------------------------------------------------------------------------
# Resolution + fallback
# ---------------------------------------------------------------------------

def test_resolve_returns_registry_entry(tmp_path):
    path = _write_registry(tmp_path, """
        models:
          reasoning:
            name: model-r
            endpoint: http://localhost:11434
          coding:
            name: model-c
            endpoint: http://localhost:11434
    """)
    router = ModelRouter(registry_path=path)
    decision = router.resolve(TaskType.CODING)
    assert decision.model_name == "model-c"
    assert decision.fallback_used is False
    assert decision.success is True


def test_resolve_falls_back_to_reasoning_for_unmapped_type(tmp_path):
    path = _write_registry(tmp_path, """
        models:
          reasoning:
            name: only-reasoning
            endpoint: http://localhost:11434
    """)
    router = ModelRouter(registry_path=path)
    decision = router.resolve(TaskType.CODING)
    assert decision.fallback_used is True
    assert decision.model_name == "only-reasoning"
    assert "fell back to 'reasoning'" in (decision.fallback_reason or "")


def test_missing_reasoning_entry_raises(tmp_path):
    path = _write_registry(tmp_path, """
        models:
          coding:
            name: only-coding
            endpoint: http://localhost:11434
    """)
    router = ModelRouter(registry_path=path)
    with pytest.raises(RuntimeError, match="no 'reasoning' entry"):
        router.resolve(TaskType.VISION)


def test_missing_required_key_raises(tmp_path):
    path = _write_registry(tmp_path, """
        models:
          reasoning:
            name: no-endpoint
    """)
    with pytest.raises(ValueError, match="missing required key 'endpoint'"):
        ModelRouter(registry_path=path)


def test_missing_registry_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        ModelRouter(registry_path=tmp_path / "does_not_exist.yaml")


def test_empty_models_key_raises(tmp_path):
    path = _write_registry(tmp_path, "models: {}\n")
    with pytest.raises(ValueError, match="no 'models' key"):
        ModelRouter(registry_path=path)


# ---------------------------------------------------------------------------
# Shipped registry sanity — every endpoint must be local
# ---------------------------------------------------------------------------

def test_shipped_registry_is_fully_local():
    router = get_router()
    types = router.available_task_types()
    for required in ("reasoning", "coding", "vision", "embedding"):
        assert required in types, f"shipped registry missing '{required}'"

    # Every resolvable task type must point at a localhost / local endpoint.
    for tt in (TaskType.REASONING, TaskType.CODING, TaskType.VISION, TaskType.EMBEDDING):
        decision = router.resolve(tt)
        endpoint = decision.endpoint
        assert endpoint == "local" or "localhost" in endpoint or "127.0.0.1" in endpoint

def test_call_disables_thinking_for_structured_output(tmp_path, monkeypatch):
    path = _write_registry(tmp_path, """
        models:
          vision:
            name: local-vision
            endpoint: http://localhost:11434
    """)
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": "{}"}

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, json):
            captured.update(json)
            return Response()

    monkeypatch.setattr("app.agent.model_router.httpx.Client", Client)
    router = ModelRouter(registry_path=path)
    decision, response = router.call(TaskType.VISION, prompt="extract JSON")

    assert decision.success is True
    assert response == "{}"
    assert captured["think"] is False
