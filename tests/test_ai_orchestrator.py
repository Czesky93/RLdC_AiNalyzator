"""
Testy routingu local AI w ai_orchestrator.py

Scenariusze:
- check_local_ai_health() gdy Ollama jest dostępna → reachable=True
- check_local_ai_health() gdy Ollama niedostępna → reachable=False, brak wyjątku
- generate_ai_chat_response() gdy local provider usable=True → używa _call_ollama_chat
- generate_ai_chat_response() gdy local provider usable=False → fallback do groq/heuristic
- generate_ai_chat_response() gdy _call_ollama_chat timeout → fallback, bez wyjątku
- generate_ai_chat_response() gdy wszyscy providerzy nie dzialaą → heuristic fallback
- get_ai_orchestrator_status() zwraca pola local_ai_*
"""

from __future__ import annotations

import os
import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from backend.database import RuntimeSetting, SessionLocal

# ─── Pomocnicze stałe ────────────────────────────────────────────────────────
_FAKE_OLLAMA_TAGS_RESPONSE = {
    "models": [
        {"name": "qwen2.5:0.5b"},
        {"name": "qwen2.5:1.5b"},
    ]
}

_FAKE_OLLAMA_CHAT_RESPONSE = {
    "message": {"role": "assistant", "content": "Odpowiedź testowa od Ollama."}
}


# ─── check_local_ai_health ───────────────────────────────────────────────────


class TestCheckLocalAiHealth:
    """Testy sprawdzające diagnostykę local AI."""

    def test_ollama_reachable_returns_full_dict(self):
        """Gdy Ollama odpowiada → reachable=True, latency_ms, model_available."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _FAKE_OLLAMA_TAGS_RESPONSE
        mock_resp.raise_for_status.return_value = None

        with patch("requests.get", return_value=mock_resp):
            from backend.ai_orchestrator import check_local_ai_health

            result = check_local_ai_health()

        assert result["reachable"] is True
        assert isinstance(result["latency_ms"], int)
        assert result["latency_ms"] >= 0
        assert result["model_available"] is True
        assert isinstance(result["installed_models"], list)
        assert len(result["installed_models"]) >= 1

    def test_ollama_unreachable_returns_error_no_exception(self):
        """Gdy Ollama nie odpowiada → reachable=False, brak wyjątku."""
        with patch("requests.get", side_effect=requests.ConnectionError("refused")):
            with patch("backend.ai_orchestrator._try_start_ollama", return_value=False):
                from backend.ai_orchestrator import check_local_ai_health

                result = check_local_ai_health()

        assert result["reachable"] is False
        assert "last_error" in result

    def test_ollama_unreachable_model_available_false(self):
        """Gdy Ollama nie odpowiada → model_available=False."""
        with patch("requests.get", side_effect=requests.Timeout("timeout")):
            with patch("backend.ai_orchestrator._try_start_ollama", return_value=False):
                from backend.ai_orchestrator import check_local_ai_health

                result = check_local_ai_health()

        assert result["model_available"] is False

    def test_model_not_in_list_returns_model_available_false(self):
        """Gdy model nie jest na liście zainstalowanych → model_available=False."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"models": [{"name": "llama3:8b"}]}
        mock_resp.raise_for_status.return_value = None

        with patch("requests.get", return_value=mock_resp):
            with patch.dict(os.environ, {"OLLAMA_MODEL": "qwen2.5:0.5b"}):
                from backend.ai_orchestrator import check_local_ai_health

                result = check_local_ai_health()

        assert result["reachable"] is True
        assert result["model_available"] is False

    def test_result_has_required_keys(self):
        """check_local_ai_health() zawsze zwraca wymagane klucze."""
        with patch("requests.get", side_effect=Exception("error")):
            with patch("backend.ai_orchestrator._try_start_ollama", return_value=False):
                from backend.ai_orchestrator import check_local_ai_health

                result = check_local_ai_health()

        for key in (
            "reachable",
            "model_available",
            "latency_ms",
            "installed_models",
            "last_error",
        ):
            assert key in result, f"Brak klucza: {key}"


# ─── generate_ai_chat_response ───────────────────────────────────────────────


class TestGenerateAiChatResponse:
    """Testy routingu łańcucha local → groq → gemini → openai → heuristic."""

    def _make_local_usable_status(self) -> dict:
        """Status z local AI jako usable=True i primary=local."""
        return {
            "primary": "local",
            "providers": {
                "local": {"usable": True, "status": "ok"},
                "groq": {"usable": False, "status": "no_key"},
                "gemini": {"usable": False, "status": "no_key"},
                "openai": {"usable": False, "status": "no_key"},
            },
        }

    def _make_local_unusable_status(self) -> dict:
        """Status z local AI jako usable=False."""
        return {
            "primary": "groq",
            "providers": {
                "local": {"usable": False, "status": "unreachable"},
                "groq": {"usable": True, "status": "ok"},
                "gemini": {"usable": False, "status": "no_key"},
                "openai": {"usable": False, "status": "no_key"},
            },
        }

    def _make_all_unusable_status(self) -> dict:
        """Status z wszystkimi providerami usable=False → heuristic."""
        return {
            "primary": "heuristic",
            "providers": {
                "local": {"usable": False, "status": "unreachable"},
                "groq": {"usable": False, "status": "no_key"},
                "gemini": {"usable": False, "status": "no_key"},
                "openai": {"usable": False, "status": "no_key"},
            },
        }

    def test_local_usable_uses_ollama(self):
        """Gdy local usable=True → generate_ai_chat_response używa _call_ollama_chat."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _FAKE_OLLAMA_CHAT_RESPONSE
        mock_resp.raise_for_status.return_value = None

        with patch(
            "backend.ai_orchestrator.get_ai_orchestrator_status",
            return_value=self._make_local_usable_status(),
        ):
            with patch("backend.ai_orchestrator._circuit_open", return_value=False):
                with patch("requests.post", return_value=mock_resp):
                    from backend.ai_orchestrator import generate_ai_chat_response

                    response, provider = generate_ai_chat_response(
                        "Cześć", max_tokens=50
                    )

        assert provider == "local"
        assert len(response) > 0

    def test_local_unusable_falls_back_to_groq(self):
        """Gdy local usable=False → fallback do groq (jeśli groq usable)."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Groq odpowiada."}}]
        }
        mock_resp.raise_for_status.return_value = None

        with patch(
            "backend.ai_orchestrator.get_ai_orchestrator_status",
            return_value=self._make_local_unusable_status(),
        ):
            with patch("backend.ai_orchestrator._circuit_open", return_value=False):
                with patch("requests.post", return_value=mock_resp):
                    from backend.ai_orchestrator import generate_ai_chat_response

                    response, provider = generate_ai_chat_response(
                        "Cześć", max_tokens=50
                    )

        assert provider == "groq"
        assert len(response) > 0

    def test_local_timeout_triggers_fallback(self):
        """Gdy _call_ollama_chat timeout → fallback do groq/heuristic, brak wyjątku."""
        groq_resp = MagicMock()
        groq_resp.status_code = 200
        groq_resp.json.return_value = {
            "choices": [{"message": {"content": "Groq po timeout local."}}]
        }
        groq_resp.raise_for_status.return_value = None

        def _mock_post(*args, **kwargs):
            url = args[0] if args else kwargs.get("url", "")
            if "11434" in str(url):
                raise requests.Timeout("local timeout")
            return groq_resp

        with patch(
            "backend.ai_orchestrator.get_ai_orchestrator_status",
            return_value=self._make_local_usable_status(),
        ):
            with patch("backend.ai_orchestrator._circuit_open", return_value=False):
                with patch("requests.post", side_effect=_mock_post):
                    from backend.ai_orchestrator import generate_ai_chat_response

                    response, provider = generate_ai_chat_response(
                        "Cześć", max_tokens=50
                    )

        # Local timeout → fallback. Groq usable=False w tym statusie → heuristic
        assert isinstance(response, str)
        assert len(response) > 0
        assert provider in ("local", "groq", "gemini", "openai", "heuristic")

    def test_all_providers_unusable_returns_heuristic(self):
        """Gdy wszyscy providerzy usable=False → heuristic fallback bez wyjątku."""
        with patch(
            "backend.ai_orchestrator.get_ai_orchestrator_status",
            return_value=self._make_all_unusable_status(),
        ):
            from backend.ai_orchestrator import generate_ai_chat_response

            response, provider = generate_ai_chat_response("test", max_tokens=50)

        assert isinstance(response, str)
        assert len(response) > 0
        assert provider == "heuristic"

    def test_returns_tuple_str_str(self):
        """generate_ai_chat_response zawsze zwraca (str, str)."""
        with patch(
            "backend.ai_orchestrator.get_ai_orchestrator_status",
            return_value=self._make_all_unusable_status(),
        ):
            from backend.ai_orchestrator import generate_ai_chat_response

            result = generate_ai_chat_response("test")

        assert isinstance(result, tuple)


def _reset_ai_runtime_state():
    db = SessionLocal()
    try:
        db.query(RuntimeSetting).filter(
            RuntimeSetting.key.in_(
                ["ai_provider_budget_state", "ai_response_cache_state"]
            )
        ).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_external_ai_daily_limit_falls_back_to_local(monkeypatch):
    _reset_ai_runtime_state()
    monkeypatch.setenv("EXTERNAL_AI_DAILY_LIMIT", "3")
    monkeypatch.setenv("USE_GROQ", "true")
    monkeypatch.setenv("LOCAL_MODEL_ENABLED", "true")

    groq_calls = {"count": 0}

    def _fake_status(force: bool = False):
        return {
            "primary": "groq",
            "providers": {
                "local": {"usable": True, "status": "ready"},
                "groq": {"usable": True, "status": "ready"},
                "gemini": {"usable": False, "status": "disabled"},
                "openai": {"usable": False, "status": "disabled"},
            },
            "queue_pressure": {"local_only": False},
        }

    def _fake_groq(messages, max_tokens=400):
        groq_calls["count"] += 1
        return "groq"

    with patch("backend.ai_orchestrator.get_ai_orchestrator_status", side_effect=_fake_status):
        with patch("backend.ai_orchestrator._call_groq_chat", side_effect=_fake_groq):
            with patch("backend.ai_orchestrator._call_ollama_chat", return_value="local"):
                results = [
                    __import__("backend.ai_orchestrator", fromlist=["generate_ai_chat_response"]).generate_ai_chat_response(
                        f"analysis-{idx}",
                        task="decision_support",
                        priority="high",
                    )[1]
                    for idx in range(4)
                ]

    assert results[:3] == ["groq", "groq", "groq"]
    assert results[3] == "local"
    assert groq_calls["count"] == 3


def test_ai_cache_prevents_duplicate_external_call(monkeypatch):
    _reset_ai_runtime_state()
    monkeypatch.setenv("EXTERNAL_AI_DAILY_LIMIT", "3")

    calls = {"count": 0}

    def _fake_status(force: bool = False):
        return {
            "primary": "groq",
            "providers": {
                "local": {"usable": True, "status": "ready"},
                "groq": {"usable": True, "status": "ready"},
                "gemini": {"usable": False, "status": "disabled"},
                "openai": {"usable": False, "status": "disabled"},
            },
            "queue_pressure": {"local_only": False},
        }

    def _fake_groq(messages, max_tokens=400):
        calls["count"] += 1
        return "cached-groq"

    with patch("backend.ai_orchestrator.get_ai_orchestrator_status", side_effect=_fake_status):
        with patch("backend.ai_orchestrator._call_groq_chat", side_effect=_fake_groq):
            with patch("backend.ai_orchestrator._call_ollama_chat", return_value="local"):
                from backend.ai_orchestrator import generate_ai_chat_response

                first = generate_ai_chat_response(
                    "same payload", task="decision_support", priority="high", symbols=["BTCUSDC"]
                )
                second = generate_ai_chat_response(
                    "same payload", task="decision_support", priority="high", symbols=["BTCUSDC"]
                )

    assert first[0] == second[0]
    assert calls["count"] == 1


def test_local_only_task_never_uses_external(monkeypatch):
    _reset_ai_runtime_state()

    def _fake_status(force: bool = False):
        return {
            "primary": "groq",
            "providers": {
                "local": {"usable": True, "status": "ready"},
                "groq": {"usable": True, "status": "ready"},
                "gemini": {"usable": False, "status": "disabled"},
                "openai": {"usable": False, "status": "disabled"},
            },
            "queue_pressure": {"local_only": False},
        }

    with patch("backend.ai_orchestrator.get_ai_orchestrator_status", side_effect=_fake_status):
        with patch("backend.ai_orchestrator._call_groq_chat", side_effect=AssertionError("external should not be used")):
            with patch("backend.ai_orchestrator._call_ollama_chat", return_value="local-status"):
                from backend.ai_orchestrator import generate_ai_chat_response

                response, provider = generate_ai_chat_response(
                    "show logs", task="logs", priority="high"
                )

    assert response == "local-status"
    assert provider == "local"
        assert len(result) == 2
        assert isinstance(result[0], str)
        assert isinstance(result[1], str)


# ─── get_ai_orchestrator_status — pola local_ai_* ────────────────────────────


class TestGetAiOrchestratorStatusLocalFields:
    """Weryfikacja że status zawiera pola local_ai_*."""

    _LOCAL_AI_FIELDS = [
        "local_ai_model",
        "local_ai_endpoint",
        "local_ai_reachable",
        "local_ai_selected",
        "local_ai_model_installed",
        "local_ai_last_status",
    ]

    def test_status_contains_local_ai_fields(self):
        """get_ai_orchestrator_status() zawiera wszystkie pola local_ai_*."""
        mock_tags = MagicMock()
        mock_tags.status_code = 200
        mock_tags.json.return_value = _FAKE_OLLAMA_TAGS_RESPONSE
        mock_tags.raise_for_status.return_value = None

        with patch("requests.get", return_value=mock_tags):
            from backend.ai_orchestrator import get_ai_orchestrator_status

            status = get_ai_orchestrator_status(force=True)

        for field in self._LOCAL_AI_FIELDS:
            assert field in status, f"Brak pola: {field}"

    def test_local_ai_latency_ms_present(self):
        """Status zawiera local_ai_latency_ms (może być None gdy nieosiągalny)."""
        mock_tags = MagicMock()
        mock_tags.status_code = 200
        mock_tags.json.return_value = _FAKE_OLLAMA_TAGS_RESPONSE
        mock_tags.raise_for_status.return_value = None

        with patch("requests.get", return_value=mock_tags):
            from backend.ai_orchestrator import get_ai_orchestrator_status

            status = get_ai_orchestrator_status(force=True)

        assert "local_ai_latency_ms" in status

    def test_local_ai_model_is_string(self):
        """local_ai_model jest stringiem (nazwa modelu)."""
        mock_tags = MagicMock()
        mock_tags.status_code = 200
        mock_tags.json.return_value = _FAKE_OLLAMA_TAGS_RESPONSE
        mock_tags.raise_for_status.return_value = None

        with patch("requests.get", return_value=mock_tags):
            from backend.ai_orchestrator import get_ai_orchestrator_status

            status = get_ai_orchestrator_status(force=True)

        assert isinstance(status["local_ai_model"], str)
        assert len(status["local_ai_model"]) > 0

    def test_local_provider_in_providers_dict(self):
        """Klucz 'local' jest w status['providers']."""
        mock_tags = MagicMock()
        mock_tags.status_code = 200
        mock_tags.json.return_value = _FAKE_OLLAMA_TAGS_RESPONSE
        mock_tags.raise_for_status.return_value = None

        with patch("requests.get", return_value=mock_tags):
            from backend.ai_orchestrator import get_ai_orchestrator_status

            status = get_ai_orchestrator_status(force=True)

        providers = status.get("providers", {})
        assert "local" in providers, "Brak klucza 'local' w providers"


# ─── /health endpoint — local_ai blok ────────────────────────────────────────


class TestHealthEndpointLocalAiBlock:
    """Weryfikacja że /health zawiera blok local_ai."""

    def test_health_contains_local_ai(self):
        """GET /health → body zawiera klucz 'local_ai'."""
        import os

        from fastapi.testclient import TestClient

        os.environ.setdefault("DISABLE_COLLECTOR", "true")

        mock_tags = MagicMock()
        mock_tags.status_code = 200
        mock_tags.json.return_value = _FAKE_OLLAMA_TAGS_RESPONSE
        mock_tags.raise_for_status.return_value = None

        with patch("requests.get", return_value=mock_tags):
            from backend.app import app

            client = TestClient(app)
            resp = client.get("/health")

        assert resp.status_code == 200
        data = resp.json()
        assert "local_ai" in data, "Brak klucza 'local_ai' w /health"

    def test_health_local_ai_has_required_keys(self):
        """GET /health → local_ai zawiera: enabled, configured, reachable, model."""
        import os

        from fastapi.testclient import TestClient

        os.environ.setdefault("DISABLE_COLLECTOR", "true")

        mock_tags = MagicMock()
        mock_tags.status_code = 200
        mock_tags.json.return_value = _FAKE_OLLAMA_TAGS_RESPONSE
        mock_tags.raise_for_status.return_value = None

        with patch("requests.get", return_value=mock_tags):
            from backend.app import app

            client = TestClient(app)
            resp = client.get("/health")

        data = resp.json()
        local_ai = data.get("local_ai", {})
        for key in ("enabled", "configured", "reachable", "model"):
            assert key in local_ai, f"Brak klucza '{key}' w local_ai"


class TestAiProviderHardening:
    """Regresje dla twardego fallbacku providerów."""

    def test_openai_invalid_key_sets_auth_failed(self):
        """Invalid OpenAI key powinien być jawnie oznaczony jako auth_failed."""
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "{}"
        mock_resp.json.return_value = {
            "error": {
                "code": "invalid_api_key",
                "message": "Incorrect API key provided",
            }
        }

        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "sk-invalid",
                "AI_PROVIDER": "openai",
            },
            clear=False,
        ):
            with patch("requests.post", return_value=mock_resp):
                from backend.ai_orchestrator import get_ai_orchestrator_status

                status = get_ai_orchestrator_status(force=True)

        openai = (status.get("providers") or {}).get("openai") or {}
        assert openai.get("usable") is False
        assert openai.get("status") == "auth_failed"

    def test_multi_parallel_skips_unusable_provider(self):
        """run_multi_ai_parallel pomija providery oznaczone usable=False."""
        with patch(
            "backend.ai_orchestrator.get_ai_orchestrator_status",
            return_value={
                "providers": {
                    "local": {"usable": False, "status": "auth_failed", "reason": "invalid key"},
                    "groq": {"usable": True, "status": "ok"},
                }
            },
        ):
            with patch(
                "backend.ai_orchestrator._call_groq_chat",
                return_value="Groq OK",
            ):
                with patch(
                    "backend.ai_orchestrator._call_ollama_chat",
                    side_effect=AssertionError("local provider should be skipped"),
                ):
                    from backend.ai_orchestrator import run_multi_ai_parallel

                    with patch.dict(
                        os.environ,
                        {"AI_PROVIDERS": "ollama,groq", "AI_PROVIDER_TIMEOUT_SECONDS": "2"},
                        clear=False,
                    ):
                        out = run_multi_ai_parallel(
                            [{"role": "user", "content": "test"}],
                            max_tokens=32,
                        )

        assert "local" in out
        assert out["local"][0] is None
        assert str(out["local"][1]).startswith("unavailable:")
        assert out.get("groq", (None, None))[0] == "Groq OK"
