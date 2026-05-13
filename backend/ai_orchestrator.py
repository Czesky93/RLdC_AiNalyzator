"""
AI orchestrator for multi-provider diagnostics and routing.

Local/free-first policy:
1) local (ollama)
2) free providers (groq, gemini)
3) paid providers (openai)
4) heuristic fallback

MULTI-AI MODE:
When AI_MULTI_ENABLED=true, all enabled providers run in parallel.
Responses are collected and passed to expert_audit_engine for consensus.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import logging
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

from backend.database import RuntimeSetting, SessionLocal, utc_now_naive

logger = logging.getLogger(__name__)

# ─── TTL cache dla get_ai_orchestrator_status ────────────────────────────────
_STATUS_CACHE_LOCK: threading.Lock = threading.Lock()
_STATUS_CACHE: Optional[Dict[str, Any]] = None
_STATUS_CACHE_AT: float = 0.0
_STATUS_CACHE_TTL: float = float(os.getenv("AI_STATUS_CACHE_TTL", "60"))

# ─── Circuit breaker per-provider ────────────────────────────────────────────
# Klucz: nazwa providera, wartość: {fail_count, open, retry_at}
_PROVIDER_CIRCUIT: Dict[str, Dict[str, Any]] = {}
_CIRCUIT_BREAKER_THRESHOLD: int = 3  # ile konsekutywnych błędów otwiera circuit
_CIRCUIT_BREAKER_TIMEOUT: float = 300.0  # sekundy do następnej próby (5 min)
_AI_STATE_LOCK: threading.RLock = threading.RLock()
_AI_INFLIGHT_LOCK: threading.Lock = threading.Lock()
_AI_INFLIGHT: Dict[str, threading.Event] = {}
_AI_INFLIGHT_RESULTS: Dict[str, Tuple[str, str]] = {}
_AI_STATE_KEY = "ai_provider_budget_state"
_AI_CACHE_STATE_KEY = "ai_response_cache_state"


def _circuit_open(provider_name: str) -> bool:
    """Zwraca True jeśli circuit jest otwarty (provider chwilowo wyłączony)."""
    c = _PROVIDER_CIRCUIT.get(provider_name)
    if not c:
        return False
    if c.get("open") and time.monotonic() < c.get("retry_at", 0.0):
        return True
    # Okno retry minęło — resetuj circuit
    if c.get("open") and time.monotonic() >= c.get("retry_at", 0.0):
        c["open"] = False
        c["fail_count"] = 0
        logger.info(f"[ai_circuit] {provider_name}: circuit reset, ponawiam próby")
    return False


def _record_provider_failure(provider_name: str, exc_text: str) -> None:
    """Rejestruje niepowodzenie providera. Pierwsze — WARNING, kolejne — DEBUG.
    Po _CIRCUIT_BREAKER_THRESHOLD porażkach otwiera circuit breaker."""
    c = _PROVIDER_CIRCUIT.setdefault(
        provider_name, {"fail_count": 0, "open": False, "retry_at": 0.0}
    )
    c["fail_count"] = c.get("fail_count", 0) + 1
    if c["fail_count"] == 1:
        logger.warning(f"[ai_chat] {provider_name} failed: {exc_text}")
    else:
        logger.debug(
            f"[ai_chat] {provider_name} failed (próba {c['fail_count']}): {exc_text}"
        )
    if c["fail_count"] >= _CIRCUIT_BREAKER_THRESHOLD and not c.get("open"):
        c["open"] = True
        c["retry_at"] = time.monotonic() + _CIRCUIT_BREAKER_TIMEOUT
        logger.warning(
            f"[ai_circuit] {provider_name}: circuit OTWARTY po {c['fail_count']} błędach. "
            f"Kolejna próba za {_CIRCUIT_BREAKER_TIMEOUT:.0f}s."
        )


def _record_provider_success(provider_name: str) -> None:
    """Resetuje circuit breaker po sukcesie."""
    c = _PROVIDER_CIRCUIT.get(provider_name)
    if c and (c.get("fail_count", 0) > 0 or c.get("open")):
        c["fail_count"] = 0
        c["open"] = False
        logger.debug(f"[ai_circuit] {provider_name}: reset (sukces)")


def _bool_env(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name, "") or "").strip().lower()
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _runtime_value(key: str, env_name: str, default: Any) -> Any:
    try:
        db = SessionLocal()
        try:
            row = db.query(RuntimeSetting).filter(RuntimeSetting.key == key).first()
            if row is not None and row.value is not None:
                return row.value
        finally:
            db.close()
    except Exception:
        pass
    return os.getenv(env_name, default)


def _load_runtime_json(setting_key: str, default: Dict[str, Any]) -> Dict[str, Any]:
    db = SessionLocal()
    try:
        row = db.query(RuntimeSetting).filter(RuntimeSetting.key == setting_key).first()
        if row and row.value:
            try:
                payload = json.loads(row.value)
                if isinstance(payload, dict):
                    return payload
            except Exception:
                return dict(default)
        return dict(default)
    finally:
        db.close()


def _save_runtime_json(setting_key: str, payload: Dict[str, Any]) -> None:
    db = SessionLocal()
    try:
        row = db.query(RuntimeSetting).filter(RuntimeSetting.key == setting_key).first()
        value = json.dumps(payload, ensure_ascii=False)
        if row is None:
            row = RuntimeSetting(key=setting_key, value=value)
            db.add(row)
        else:
            row.value = value
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _utc_date_key() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _external_daily_limit() -> int:
    raw = _runtime_value("external_ai_daily_limit", "EXTERNAL_AI_DAILY_LIMIT", "3")
    try:
        return max(1, int(raw))
    except Exception:
        return 3


def _provider_state() -> Dict[str, Any]:
    with _AI_STATE_LOCK:
        state = _load_runtime_json(
            _AI_STATE_KEY,
            {"date": _utc_date_key(), "providers": {}},
        )
        today = _utc_date_key()
        if state.get("date") != today:
            state = {"date": today, "providers": {}}
            _save_runtime_json(_AI_STATE_KEY, state)
        return state


def _provider_used_today(provider_name: str) -> int:
    state = _provider_state()
    return int(
        ((state.get("providers") or {}).get(provider_name) or {}).get("used_today") or 0
    )


def _increment_provider_usage(provider_name: str) -> int:
    with _AI_STATE_LOCK:
        state = _provider_state()
        providers = state.setdefault("providers", {})
        current = providers.setdefault(
            provider_name,
            {
                "used_today": 0,
                "daily_limit": _external_daily_limit(),
                "fallback_active": False,
            },
        )
        current["daily_limit"] = _external_daily_limit()
        current["used_today"] = int(current.get("used_today") or 0) + 1
        current["fallback_active"] = int(current.get("used_today") or 0) >= int(
            current.get("daily_limit") or _external_daily_limit()
        )
        _save_runtime_json(_AI_STATE_KEY, state)
        return int(current["used_today"])


def _mark_provider_fallback(provider_name: str, active: bool) -> None:
    with _AI_STATE_LOCK:
        state = _provider_state()
        providers = state.setdefault("providers", {})
        current = providers.setdefault(
            provider_name,
            {
                "used_today": 0,
                "daily_limit": _external_daily_limit(),
                "fallback_active": False,
            },
        )
        current["daily_limit"] = _external_daily_limit()
        current["fallback_active"] = bool(active)
        _save_runtime_json(_AI_STATE_KEY, state)


def get_ai_budget_status() -> Dict[str, Any]:
    state = _provider_state()
    providers = state.get("providers") or {}
    limit = _external_daily_limit()
    payload = {}
    for provider_name in ("openai", "groq", "gemini"):
        current = providers.get(provider_name) or {}
        used_today = int(current.get("used_today") or 0)
        payload[provider_name] = {
            "provider": provider_name,
            "used_today": used_today,
            "daily_limit": int(current.get("daily_limit") or limit),
            "fallback_active": bool(
                current.get("fallback_active") or used_today >= limit
            ),
        }
    return {"date": state.get("date") or _utc_date_key(), "providers": payload}


def _allow_external_provider(provider_name: str) -> Tuple[bool, Optional[str]]:
    if provider_name not in {"openai", "groq", "gemini"}:
        return True, None
    limit = _external_daily_limit()
    used_today = _provider_used_today(provider_name)
    if used_today >= limit:
        _mark_provider_fallback(provider_name, True)
        return False, "daily_limit_reached"
    return True, None


def _cache_ttl_seconds() -> int:
    try:
        return max(
            1,
            int(
                _runtime_value("ai_cache_ttl_seconds", "AI_CACHE_TTL_SECONDS", "21600")
            ),
        )
    except Exception:
        return 21600


def _symbol_cooldown_seconds() -> int:
    try:
        return max(
            1,
            int(
                _runtime_value(
                    "ai_symbol_cooldown_seconds", "AI_SYMBOL_COOLDOWN_SECONDS", "1800"
                )
            ),
        )
    except Exception:
        return 1800


def _cache_enabled() -> bool:
    raw = _runtime_value("enable_ai_cache", "ENABLE_AI_CACHE", "true")
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_symbols(symbols: Optional[List[str]]) -> List[str]:
    seen: List[str] = []
    for symbol in symbols or []:
        norm = (
            str(symbol or "")
            .strip()
            .replace(" ", "")
            .replace("/", "")
            .replace("-", "")
            .upper()
        )
        if norm and norm not in seen:
            seen.append(norm)
    return seen


def _cache_key(
    task: str, user_text: str, context_summary: str, symbols: List[str]
) -> str:
    bucket = int(time.time() // max(1, _cache_ttl_seconds()))
    prompt_hash = hashlib.sha256(
        f"{task}|{user_text}|{context_summary}|{','.join(symbols)}".encode("utf-8")
    ).hexdigest()[:24]
    return f"{task}:{','.join(symbols)}:{bucket}:{prompt_hash}"


def _load_cache_state() -> Dict[str, Any]:
    return _load_runtime_json(
        _AI_CACHE_STATE_KEY, {"entries": {}, "symbol_last_task": {}}
    )


def _save_cache_state(payload: Dict[str, Any]) -> None:
    _save_runtime_json(_AI_CACHE_STATE_KEY, payload)


def _cache_lookup(
    task: str, symbols: List[str], cache_key: str
) -> Optional[Tuple[str, str]]:
    if not _cache_enabled():
        return None
    state = _load_cache_state()
    entries = state.get("entries") or {}
    entry = entries.get(cache_key) or {}
    if not entry:
        return None
    if (time.time() - float(entry.get("stored_at") or 0.0)) > _cache_ttl_seconds():
        return None
    return str(entry.get("response") or ""), str(entry.get("provider") or "cache")


def _cache_store(
    task: str,
    symbols: List[str],
    cache_key: str,
    response: str,
    provider: str,
) -> None:
    if not _cache_enabled():
        return
    state = _load_cache_state()
    entries = state.setdefault("entries", {})
    symbol_last_task = state.setdefault("symbol_last_task", {})
    entries[cache_key] = {
        "task": task,
        "symbols": symbols,
        "response": response,
        "provider": provider,
        "stored_at": time.time(),
    }
    for symbol in symbols:
        symbol_last_task[f"{task}:{symbol}"] = time.time()
    _save_cache_state(state)


def _symbol_cooldown_active(
    task: str, symbols: List[str]
) -> Tuple[bool, Optional[str]]:
    if not symbols:
        return False, None
    state = _load_cache_state()
    symbol_last_task = state.get("symbol_last_task") or {}
    cooldown = _symbol_cooldown_seconds()
    now = time.time()
    for symbol in symbols:
        key = f"{task}:{symbol}"
        last_ts = float(symbol_last_task.get(key) or 0.0)
        if last_ts and (now - last_ts) < cooldown:
            return True, symbol
    return False, None


def _task_local_only(task: str) -> bool:
    return task in {
        "deterministic",
        "command_parsing",
        "status",
        "query",
        "queue_status",
        "logs",
        "help",
        "execution_status",
        "reconcile_status",
        "universe_status",
        "quote_status",
        "chat",
    }


def _mask_secret(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _safe_text(value: Any, max_len: int = 220) -> str:
    txt = str(value or "")
    txt = txt.replace("\n", " ").replace("\r", " ").strip()
    # Redact potential API secrets from provider error payloads.
    txt = re.sub(r"sk-[A-Za-z0-9_-]{6,}", "sk-[REDACTED]", txt)
    txt = re.sub(
        r"(?i)(api[_\s-]?key\s*(provided|is)?\s*[:=]?\s*)([A-Za-z0-9_-]{8,})",
        r"\1[REDACTED]",
        txt,
    )
    return txt[:max_len]


def _detect_openai_unpaid(error_text: str, error_code: str) -> bool:
    payload = f"{error_code} {error_text}".lower()
    needles = [
        "insufficient_quota",
        "billing",
        "payment",
        "quota",
        "exceeded your current quota",
        "you exceeded your current quota",
    ]
    return any(n in payload for n in needles)


def _provider_enabled(name: str) -> bool:
    mapping = {
        "openai": [
            ("use_openai", "USE_OPENAI", False),
            ("openai_enabled", "OPENAI_ENABLED", False),
        ],
        "groq": [("use_groq", "USE_GROQ", True)],
        "gemini": [("use_gemini", "USE_GEMINI", True)],
        "local": [("local_model_enabled", "LOCAL_MODEL_ENABLED", True)],
    }
    checks = mapping.get(name, [])
    if not checks:
        return True
    for runtime_key, env_name, default in checks:
        raw = str(_runtime_value(runtime_key, env_name, str(default))).strip().lower()
        if raw in {"1", "true", "yes", "on"}:
            return True
    return False


def _openai_status() -> Dict[str, Any]:
    if not _provider_enabled("openai"):
        return {
            "name": "openai",
            "configured": False,
            "usable": False,
            "status": "disabled",
            "reason": "provider disabled by runtime flags",
            "key_masked": "",
            "model": (os.getenv("OPENAI_MODEL", "gpt-5-mini") or "gpt-5-mini").strip(),
        }
    key = (os.getenv("OPENAI_API_KEY", "") or "").strip()
    model = (os.getenv("OPENAI_MODEL", "gpt-5-mini") or "gpt-5-mini").strip()
    endpoint = (
        os.getenv("OPENAI_ENDPOINT", "https://api.openai.com/v1/models")
        or "https://api.openai.com/v1/models"
    ).strip()
    timeout_s = float(os.getenv("AI_PROVIDER_TIMEOUT_SECONDS", "4") or 4)

    if not key:
        return {
            "name": "openai",
            "configured": False,
            "usable": False,
            "status": "missing_key",
            "reason": "OPENAI_API_KEY not set",
            "key_masked": "",
            "model": model,
        }

    if _bool_env("OPENAI_UNPAID", False) or not _bool_env(
        "OPENAI_BILLING_AVAILABLE", True
    ):
        return {
            "name": "openai",
            "configured": True,
            "usable": False,
            "status": "unpaid_or_disabled",
            "reason": "OpenAI configured but billing unavailable/disabled by env",
            "key_masked": _mask_secret(key),
            "model": model,
        }

    try:
        resp = requests.get(
            endpoint,
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout_s,
        )
        if resp.status_code == 200:
            return {
                "name": "openai",
                "configured": True,
                "usable": True,
                "status": "ready",
                "reason": "provider reachable",
                "key_masked": _mask_secret(key),
                "model": model,
                "endpoint": endpoint,
            }

        code = "http_error"
        message = _safe_text(resp.text)
        try:
            payload = resp.json() if resp.text else {}
            err = (payload or {}).get("error") or {}
            code = str(err.get("code") or err.get("type") or code)
            message = _safe_text(err.get("message") or message)
        except Exception:
            pass

        unpaid = _detect_openai_unpaid(message, code)
        auth_failed = (
            "incorrect api key" in message.lower()
            or "invalid_api_key" in code.lower()
            or "invalid api key" in message.lower()
            or "authentication" in code.lower()
        )
        if auth_failed:
            message = "OpenAI auth failed (invalid API key)"
        return {
            "name": "openai",
            "configured": True,
            "usable": False,
            "status": (
                "auth_failed" if auth_failed else ("unpaid" if unpaid else "error")
            ),
            "reason": message,
            "error_code": code,
            "key_masked": _mask_secret(key),
            "model": model,
            "endpoint": endpoint,
        }
    except Exception as exc:
        return {
            "name": "openai",
            "configured": True,
            "usable": False,
            "status": "error",
            "reason": _safe_text(exc),
            "key_masked": _mask_secret(key),
            "model": model,
            "endpoint": endpoint,
        }


def _ollama_base_url() -> str:
    return (
        (
            os.getenv(
                "OLLAMA_BASE_URL", os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
            )
            or "http://127.0.0.1:11434"
        )
        .strip()
        .rstrip("/")
    )


def _ollama_model() -> str:
    return (os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b") or "qwen2.5:1.5b").strip()


def _try_start_ollama() -> bool:
    """Próbuje uruchomić `ollama serve` jeśli Ollama nie odpowiada.
    Zwraca True jeśli serwis jest dostępny po próbie startu."""
    base_url = _ollama_base_url()
    timeout_s = float(os.getenv("AI_PROVIDER_TIMEOUT_SECONDS", "4") or 4)
    try:
        # Sprawdź czy już działa
        resp = requests.get(f"{base_url}/api/tags", timeout=timeout_s)
        if resp.status_code == 200:
            return True
    except Exception:
        pass

    # Sprawdź czy ollama jest w PATH
    try:
        result = subprocess.run(
            ["which", "ollama"], capture_output=True, text=True, timeout=3
        )
        if result.returncode != 0:
            logger.info("[local_ai_unreachable] ollama nie jest zainstalowany w PATH")
            return False
    except Exception:
        logger.info("[local_ai_unreachable] nie można sprawdzić ollama w PATH")
        return False

    # Spróbuj uruchomić
    logger.info("[local_ai_started] próba uruchomienia: ollama serve")
    try:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:
        logger.warning(f"[local_ai_unreachable] ollama serve nie uruchomiony: {exc}")
        return False

    # Czekaj na gotowość (max 8s, co 2s)
    for i in range(4):
        time.sleep(2)
        try:
            resp = requests.get(f"{base_url}/api/tags", timeout=timeout_s)
            if resp.status_code == 200:
                logger.info(f"[local_ai_started] ollama dostępny po {(i+1)*2}s")
                return True
        except Exception:
            pass

    logger.warning("[local_ai_unreachable] ollama nie odpowiedział po próbie startu")
    return False


def check_local_ai_health() -> Dict[str, Any]:
    """Pełna diagnostyka local AI (Ollama).
    Zwraca: reachable, latency_ms, model_available, model, endpoint, last_error."""
    base_url = _ollama_base_url()
    model = _ollama_model()
    timeout_s = float(os.getenv("AI_PROVIDER_TIMEOUT_SECONDS", "4") or 4)
    auto_start = _bool_env("LOCAL_AI_AUTO_START", True)
    retries = int(os.getenv("LOCAL_AI_RETRIES", "2") or 2)

    logger.debug("[local_ai_healthcheck_started] url=%s model=%s", base_url, model)

    last_error: Optional[str] = None
    latency_ms: Optional[int] = None

    for attempt in range(1, retries + 2):
        try:
            t0 = time.monotonic()
            resp = requests.get(f"{base_url}/api/tags", timeout=timeout_s)
            latency_ms = int((time.monotonic() - t0) * 1000)

            if resp.status_code != 200:
                last_error = f"HTTP {resp.status_code}"
                logger.debug(
                    "[local_ai_unreachable] attempt=%d error=%s", attempt, last_error
                )
            else:
                payload = resp.json() if resp.text else {}
                models = payload.get("models") or []
                model_names = {
                    str(m.get("name", "")) for m in models if isinstance(m, dict)
                }
                has_model = model in model_names
                if not has_model:
                    logger.info(
                        "[local_ai_unreachable] ollama dostępny, ale brak modelu '%s'. "
                        "Dostępne: %s",
                        model,
                        list(model_names)[:5],
                    )
                else:
                    logger.debug(
                        "[local_ai_healthcheck_started] OK: model=%s latency=%dms",
                        model,
                        latency_ms,
                    )
                return {
                    "reachable": True,
                    "latency_ms": latency_ms,
                    "model_available": has_model,
                    "model": model,
                    "endpoint": base_url,
                    "last_error": None if has_model else f"model_not_found:{model}",
                    "installed_models": list(model_names),
                }
        except Exception as exc:
            last_error = _safe_text(exc)
            logger.debug(
                "[local_ai_unreachable] attempt=%d error=%s", attempt, last_error
            )

        # Przed ostatnią próbą spróbuj auto-start
        if attempt == 1 and auto_start:
            if _try_start_ollama():
                continue  # idź do następnej iteracji
        elif attempt <= retries:
            time.sleep(1)

    logger.info("[local_ai_unreachable] last_error=%s", last_error)
    return {
        "reachable": False,
        "latency_ms": latency_ms,
        "model_available": False,
        "model": model,
        "endpoint": base_url,
        "last_error": last_error,
        "installed_models": [],
    }


def _ollama_status() -> Dict[str, Any]:
    if not _provider_enabled("local"):
        return {
            "name": "local",
            "configured": False,
            "usable": False,
            "status": "disabled",
            "reason": "local model disabled by runtime flags",
            "model": _ollama_model(),
            "endpoint": _ollama_base_url(),
            "latency_ms": None,
        }
    base_url = _ollama_base_url()
    model = _ollama_model()
    # Używamy krótkiego timeout dla healthchecku /api/tags (lista modeli)
    timeout_s = float(os.getenv("AI_PROVIDER_TIMEOUT_SECONDS", "4") or 4)
    t0 = time.monotonic()
    try:
        resp = requests.get(f"{base_url}/api/tags", timeout=timeout_s)
        latency_ms = int((time.monotonic() - t0) * 1000)
        if resp.status_code != 200:
            return {
                "name": "local",
                "configured": bool(base_url),
                "usable": False,
                "status": "error",
                "reason": f"Ollama HTTP {resp.status_code}",
                "model": model,
                "endpoint": base_url,
                "latency_ms": latency_ms,
            }
        payload = resp.json() if resp.text else {}
        models = payload.get("models") or []
        model_names = {str(m.get("name", "")) for m in models if isinstance(m, dict)}
        has_model = model in model_names if model else False
        return {
            "name": "local",
            "configured": bool(base_url),
            "usable": True,
            "status": "ready" if has_model else "ready_model_missing",
            "reason": "local model endpoint reachable",
            "model": model,
            "model_installed": has_model,
            "endpoint": base_url,
            "latency_ms": latency_ms,
        }
    except Exception as exc:
        latency_ms = int((time.monotonic() - t0) * 1000)
        return {
            "name": "local",
            "configured": bool(base_url),
            "usable": False,
            "status": "unreachable",
            "reason": _safe_text(exc),
            "model": model,
            "endpoint": base_url,
            "latency_ms": latency_ms,
        }


def _key_based_provider(
    name: str,
    key_env: str,
    model_env: str,
    default_model: str,
    endpoint_env: str,
    default_endpoint: str,
) -> Dict[str, Any]:
    if not _provider_enabled(name):
        return {
            "name": name,
            "configured": False,
            "usable": False,
            "status": "disabled",
            "reason": "provider disabled by runtime flags",
            "key_masked": "",
            "model": (os.getenv(model_env, default_model) or default_model).strip(),
            "endpoint": (
                os.getenv(endpoint_env, default_endpoint) or default_endpoint
            ).strip(),
        }
    key = (os.getenv(key_env, "") or "").strip()
    model = (os.getenv(model_env, default_model) or default_model).strip()
    endpoint = (os.getenv(endpoint_env, default_endpoint) or default_endpoint).strip()
    configured = bool(key)
    return {
        "name": name,
        "configured": configured,
        "usable": configured,
        "status": "ready" if configured else "missing_key",
        "reason": "configured" if configured else f"{key_env} not set",
        "key_masked": _mask_secret(key),
        "model": model,
        "endpoint": endpoint,
    }


def _pick_primary(
    preferred: str, providers: Dict[str, Dict[str, Any]]
) -> Tuple[str, List[str], bool]:
    local_first_chain = ["local", "groq", "gemini", "openai", "heuristic"]

    preferred = (preferred or "").strip().lower()
    if preferred in {"ollama", "local"}:
        pref = "local"
    elif preferred in {"auto", ""}:
        pref = "auto"
    else:
        pref = preferred

    if pref != "auto" and pref in providers and providers[pref].get("usable"):
        chain = [pref] + [x for x in local_first_chain if x != pref]
        return pref, chain[1:], False

    chosen = "heuristic"
    for candidate in local_first_chain:
        if candidate == "heuristic":
            chosen = "heuristic"
            break
        if providers.get(candidate, {}).get("usable"):
            chosen = candidate
            break

    fallback_chain = [x for x in local_first_chain if x != chosen]
    fallback_active = pref not in {"auto", chosen}
    return chosen, fallback_chain, fallback_active


def get_ai_orchestrator_status(force: bool = False) -> Dict[str, Any]:
    """
    Resolve provider diagnostics and routing state.

    Wynik jest cachowany przez AI_STATUS_CACHE_TTL sekund (domyślnie 60s).
    Unika wielokrotnych sond HTTP providerów w ramach jednej sesji.
    Użyj force=True aby wymusić odświeżenie (np. z endpointu diagnostycznego).
    """
    global _STATUS_CACHE, _STATUS_CACHE_AT

    now_mono = time.monotonic()
    with _STATUS_CACHE_LOCK:
        if (
            not force
            and _STATUS_CACHE is not None
            and (now_mono - _STATUS_CACHE_AT) < _STATUS_CACHE_TTL
        ):
            return _STATUS_CACHE

    provider_setting = (os.getenv("AI_PROVIDER", "auto") or "auto").strip().lower()
    primary_setting = (
        (os.getenv("PRIMARY_AI", provider_setting) or provider_setting).strip().lower()
    )
    fallback_setting = (os.getenv("FALLBACK_AI", "auto") or "auto").strip().lower()
    hybrid_enabled = _bool_env("AI_HYBRID_MODE", True)

    providers: Dict[str, Dict[str, Any]] = {
        "local": _ollama_status(),
        "gemini": _key_based_provider(
            name="gemini",
            key_env="GEMINI_API_KEY",
            model_env="GEMINI_MODEL",
            default_model="gemini-2.0-flash",
            endpoint_env="GEMINI_ENDPOINT",
            default_endpoint="https://generativelanguage.googleapis.com",
        ),
        "groq": _key_based_provider(
            name="groq",
            key_env="GROQ_API_KEY",
            model_env="GROQ_MODEL",
            default_model="llama-3.3-70b-versatile",
            endpoint_env="GROQ_ENDPOINT",
            default_endpoint="https://api.groq.com/openai/v1/chat/completions",
        ),
        "openai": _openai_status(),
        "heuristic": {
            "name": "heuristic",
            "configured": True,
            "usable": True,
            "status": "ready",
            "reason": "always available rules fallback",
            "model": "atr_bollinger_rules",
        },
    }

    preferred = (
        primary_setting
        if primary_setting and primary_setting != "auto"
        else provider_setting
    )
    primary, fallback_chain, fallback_active = _pick_primary(preferred, providers)

    if fallback_setting not in {"", "auto"} and fallback_setting in providers:
        fallback_chain = [fallback_setting] + [
            x for x in fallback_chain if x != fallback_setting
        ]

    queue_pressure = {
        "pressure": 0,
        "level": "normal",
        "local_only": False,
        "limit_external_ai": False,
        "drop_non_critical": False,
    }
    try:
        from backend.queue_guard import get_queue_pressure_state

        db = SessionLocal()
        try:
            queue_pressure = get_queue_pressure_state(db)
        finally:
            db.close()
    except Exception:
        pass

    def _task_provider(task: str) -> str:
        if _task_local_only(task) or queue_pressure.get("local_only"):
            return "local" if providers.get("local", {}).get("usable") else "heuristic"
        env_name = f"AI_TASK_{task.upper()}"
        val = (os.getenv(env_name, "") or "").strip().lower()
        if val in providers and providers[val].get("usable"):
            return val
        return primary

    task_routing = {
        "analysis": _task_provider("analysis"),
        "prediction": _task_provider("prediction"),
        "text": _task_provider("text"),
        "decision_assist": _task_provider("decision_assist"),
        "command_parsing": _task_provider("command_parsing"),
        "chat": _task_provider("chat"),
    }

    now = utc_now_naive().isoformat()
    # Dołącz informacje o circuit breaker per provider
    circuit_state = {
        name: {
            "fail_count": c.get("fail_count", 0),
            "circuit_open": bool(
                c.get("open") and time.monotonic() < c.get("retry_at", 0.0)
            ),
        }
        for name, c in _PROVIDER_CIRCUIT.items()
    }
    local_provider = providers.get("local") or {}
    local_ai_enabled = _bool_env("LOCAL_AI_ENABLED", True)
    local_ai_configured = bool(local_provider.get("configured"))
    local_ai_reachable = bool(local_provider.get("usable"))
    local_ai_selected = primary == "local"
    local_ai_last_error = (
        None if local_ai_reachable else _safe_text(local_provider.get("reason") or "")
    )
    local_ai_model = local_provider.get("model") or _ollama_model()
    local_ai_endpoint = local_provider.get("endpoint") or _ollama_base_url()
    local_ai_latency_ms = local_provider.get("latency_ms")
    local_ai_model_installed = local_provider.get("model_installed")
    ai_budget = get_ai_budget_status()

    result = {
        "checked_at": now,
        "cache_ttl_s": int(_STATUS_CACHE_TTL),
        "ai_provider_setting": provider_setting,
        "primary_setting": primary_setting,
        "fallback_setting": fallback_setting,
        "hybrid_mode": hybrid_enabled,
        "primary": primary,
        "fallback_chain": fallback_chain,
        "fallback_active": fallback_active,
        "local_only_mode": bool(queue_pressure.get("local_only")),
        "providers": providers,
        "task_routing": task_routing,
        "ai_budget": ai_budget,
        "queue_pressure": queue_pressure,
        "circuit_breakers": circuit_state,
        "local_ai_enabled": local_ai_enabled,
        "local_ai_configured": local_ai_configured,
        "local_ai_reachable": local_ai_reachable,
        "local_ai_selected": local_ai_selected,
        "local_ai_model": local_ai_model,
        "local_ai_endpoint": local_ai_endpoint,
        "local_ai_latency_ms": local_ai_latency_ms,
        "local_ai_model_installed": local_ai_model_installed,
        "local_ai_last_error": local_ai_last_error,
        "local_ai_last_healthcheck": now,
        "local_ai_last_status": local_provider.get("status"),
        "active_providers": [
            name for name, pdata in providers.items() if bool(pdata.get("usable"))
        ],
        "unavailable_providers": {
            name: {
                "status": pdata.get("status"),
                "reason": pdata.get("reason"),
            }
            for name, pdata in providers.items()
            if not bool(pdata.get("usable"))
        },
        "summary": {
            "primary_label": f"AI Primary: {primary}",
            "fallback_label": (
                "Fallback: active" if fallback_active else "Fallback: standby"
            ),
            "local_only_label": (
                "Local-only: active"
                if queue_pressure.get("local_only")
                else "Local-only: standby"
            ),
            "openai_label": providers["openai"].get("status"),
            "local_label": providers["local"].get("status"),
            "local_latency_ms": local_ai_latency_ms,
            "free_provider_ready": bool(
                providers["groq"].get("usable") or providers["gemini"].get("usable")
            ),
        },
    }

    with _STATUS_CACHE_LOCK:
        _STATUS_CACHE = result
        _STATUS_CACHE_AT = now_mono

    return result


def summarize_ai_status_for_text(status: Dict[str, Any]) -> str:
    providers = status.get("providers") or {}
    openai = providers.get("openai") or {}
    local = providers.get("local") or {}
    groq = providers.get("groq") or {}
    gemini = providers.get("gemini") or {}

    lines = [
        f"AI Primary: {status.get('primary', 'unknown')}",
        f"Fallback: {'active' if status.get('fallback_active') else 'standby'}",
        f"Hybrid mode: {'enabled' if status.get('hybrid_mode') else 'disabled'}",
        f"OpenAI: {openai.get('status', 'unknown')} ({openai.get('reason', '-')})",
        f"Local: {local.get('status', 'unknown')} ({local.get('reason', '-')})",
        f"Groq: {groq.get('status', 'unknown')}",
        f"Gemini: {gemini.get('status', 'unknown')}",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# AI CHAT — generowanie odpowiedzi konwersacyjnych
# Łańcuch: groq → gemini → openai → heuristic fallback
# ─────────────────────────────────────────────────────────────────────────────

_CHAT_SYSTEM_PROMPT = (
    "Jesteś asystentem trading bota RLdC AiNalyzer. "
    "Odpowiadasz zwięźle, po polsku, konkretnie — maksymalnie 3–4 zdania. "
    "Nie wymyślaj danych rynkowych. "
    "Jeśli pytanie wymaga aktualnych danych rynkowych, których nie masz, powiedz to wprost. "
    "Jeśli pytanie jest ambigalne, daj krótką odpowiedź i zaproponuj doprecyzowanie."
)

_CHAT_COMMANDS_HELP = """Komendy dostępne przez Telegram:
• status — pełny status systemu
• saldo / portfolio — stan portfela
• pozycje — otwarte pozycje
• kup [symbol] — złóż zlecenie kupna, np. kup btc
• sprzedaj [symbol] — złóż zlecenie sprzedaży
• analiza [symbol] — analiza sygnałów, np. analiza eth
• pomoc / help — lista komend
• /start — menu startowe
"""


def _call_ollama_chat(messages: List[Dict], max_tokens: int = 400) -> str:
    """Wywołaj lokalny model Ollama dla rozmowy (OpenAI-compatible /api/chat)."""
    base_url = _ollama_base_url()
    model = _ollama_model()
    timeout_s = float(
        os.getenv("OLLAMA_TIMEOUT_SECONDS")
        or os.getenv("AI_LOCAL_TIMEOUT_SECONDS")
        or os.getenv("AI_PROVIDER_TIMEOUT_SECONDS", "90")
        or "90"
    )

    # Konwertuj do formatu Ollama (messages są już w formacie OpenAI — kompatybilne)
    t0 = time.monotonic()
    logger.debug("[local_ai_request_sent] model=%s tokens=%d", model, max_tokens)
    resp = requests.post(
        f"{base_url}/api/chat",
        json={
            "model": model,
            "messages": messages,
            "stream": False,
            "keep_alive": "10m",
            "options": {"num_predict": max_tokens, "temperature": 0.7},
        },
        timeout=timeout_s,
    )
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    resp.raise_for_status()
    data = resp.json()
    content = (data.get("message") or {}).get("content") or ""
    if not content:
        raise ValueError("Ollama zwrócił pustą odpowiedź")
    logger.info(
        "[local_ai_response_received] model=%s elapsed=%dms len=%d",
        model,
        elapsed_ms,
        len(content),
    )
    return content.strip()


def _call_groq_chat(messages: List[Dict], max_tokens: int = 400) -> str:
    """Wywołaj Groq (OpenAI-compatible endpoint) dla rozmowy."""
    key = (os.getenv("GROQ_API_KEY", "") or "").strip()
    if not key:
        raise ValueError("GROQ_API_KEY not configured")
    model = (
        os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile") or "llama-3.3-70b-versatile"
    ).strip()
    endpoint = (
        os.getenv("GROQ_ENDPOINT", "https://api.groq.com/openai/v1/chat/completions")
        or "https://api.groq.com/openai/v1/chat/completions"
    ).strip()
    timeout_s = float(os.getenv("AI_PROVIDER_TIMEOUT_SECONDS", "12") or 12)

    resp = requests.post(
        endpoint,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.7,
        },
        timeout=timeout_s,
    )
    resp.raise_for_status()
    data = resp.json()
    content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
    return (content or "").strip()


def _call_gemini_chat(messages: List[Dict], max_tokens: int = 400) -> str:
    """Wywołaj Gemini dla rozmowy (Google REST API format)."""
    key = (os.getenv("GEMINI_API_KEY", "") or "").strip()
    if not key:
        raise ValueError("GEMINI_API_KEY not configured")
    model = (
        os.getenv("GEMINI_MODEL", "gemini-2.0-flash") or "gemini-2.0-flash"
    ).strip()
    endpoint_base = (
        (
            os.getenv("GEMINI_ENDPOINT", "https://generativelanguage.googleapis.com")
            or "https://generativelanguage.googleapis.com"
        )
        .strip()
        .rstrip("/")
    )
    endpoint = f"{endpoint_base}/v1beta/models/{model}:generateContent?key={key}"
    timeout_s = float(os.getenv("AI_PROVIDER_TIMEOUT_SECONDS", "12") or 12)

    # Konwersja messages → Gemini format
    system_text = ""
    contents = []
    for msg in messages:
        role = msg.get("role", "")
        text = msg.get("content", "")
        if role == "system":
            system_text = text
        elif role == "user":
            combined = (
                f"{system_text}\n\n{text}" if system_text and not contents else text
            )
            system_text = ""
            contents.append({"role": "user", "parts": [{"text": combined}]})
        elif role == "assistant":
            contents.append({"role": "model", "parts": [{"text": text}]})

    resp = requests.post(
        endpoint,
        headers={"Content-Type": "application/json"},
        json={
            "contents": contents,
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.7},
        },
        timeout=timeout_s,
    )
    resp.raise_for_status()
    data = resp.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise ValueError("Gemini returned no candidates")
    content = (candidates[0].get("content") or {}).get("parts") or []
    return (content[0].get("text") or "").strip() if content else ""


def _call_openai_chat(messages: List[Dict], max_tokens: int = 400) -> str:
    """Wywołaj OpenAI dla rozmowy."""
    key = (os.getenv("OPENAI_API_KEY", "") or "").strip()
    if not key:
        raise ValueError("OPENAI_API_KEY not configured")
    model = (os.getenv("OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini").strip()
    timeout_s = float(os.getenv("AI_PROVIDER_TIMEOUT_SECONDS", "12") or 12)

    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.7,
        },
        timeout=timeout_s,
    )
    resp.raise_for_status()
    data = resp.json()
    content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
    return (content or "").strip()


def _heuristic_chat_response(user_text: str) -> str:
    """Reguły lokalne — fallback gdy żaden provider AI nie działa."""
    low = user_text.lower().strip()

    if any(w in low for w in ["pomoc", "help", "komendy", "co możesz", "co umiesz"]):
        return _CHAT_COMMANDS_HELP

    if any(w in low for w in ["status", "jak dziala", "jak działa", "działa"]):
        return (
            "System RLdC Trading Bot działa autonomicznie — zbiera dane co 60s, "
            "analizuje sygnały i wykonuje zlecenia gdy warunki są spełnione. "
            "Szczegóły: /status"
        )

    if any(w in low for w in ["cześć", "hej", "siema", "dzień dobry", "witam"]):
        return (
            "Cześć! Jestem botem tradingowym RLdC. "
            "Wpisz /status by zobaczyć stan systemu lub 'pomoc' by poznać komendy."
        )

    if any(w in low for w in ["btc", "bitcoin", "eth", "ethereum", "sol", "solana"]):
        return (
            "Aktualnych danych rynkowych nie mam bezpośrednio w tej chwili. "
            "Sprawdź analizę: 'analiza btc' lub 'analiza eth'."
        )

    if any(w in low for w in ["zysk", "zarobił", "strata", "pnl", "wynik"]):
        return "Status portfela: /portfolio lub 'saldo'."

    return (
        "Nie rozpoznałem tego polecenia. "
        "Wpisz 'pomoc' by zobaczyć listę dostępnych komend lub /start."
    )


def run_multi_ai_parallel(
    messages: List[Dict],
    max_tokens: int = 400,
) -> Dict[str, Tuple[Optional[str], Optional[str]]]:
    """
    Uruchom WSZYSTKIE AI providery RÓWNOLEGLE i zwróć wszystkie odpowiedzi.

    Returns:
        Dict[provider_name] = (response_text, error_or_none)

    Każdy provider jest uruchamiany w osobnym threadzie z timeout.
    """
    responses: Dict[str, Tuple[Optional[str], Optional[str]]] = {}

    provider_fns = {
        "local": _call_ollama_chat,
        "groq": _call_groq_chat,
        "gemini": _call_gemini_chat,
        "openai": _call_openai_chat,
    }

    enabled_providers = (os.getenv("AI_PROVIDERS", "ollama,gemini,groq") or "").split(
        ","
    )
    enabled_providers = [p.strip().lower() for p in enabled_providers if p.strip()]

    # Map: nazwa env (ollama) → klucz w dicts (local)
    provider_mapping = {
        "ollama": "local",
        "local": "local",
        "gemini": "gemini",
        "groq": "groq",
        "openai": "openai",
    }

    timeout_s = float(os.getenv("AI_PROVIDER_TIMEOUT_SECONDS", "30") or 30)
    provider_status = get_ai_orchestrator_status(force=False).get("providers", {})

    logger.debug(
        "[multi_ai_parallel] enabled=%s timeout=%.1f max_tokens=%d",
        enabled_providers,
        timeout_s,
        max_tokens,
    )

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {}

        for env_name in enabled_providers:
            provider_key = provider_mapping.get(env_name)
            if not provider_key or provider_key not in provider_fns:
                continue

            p_meta = provider_status.get(provider_key) or {}
            if not bool(p_meta.get("usable")):
                reason = _safe_text(
                    p_meta.get("reason") or p_meta.get("status") or "unavailable"
                )
                responses[provider_key] = (None, f"unavailable:{reason}")
                logger.info(
                    "[multi_ai_skip] provider=%s status=%s reason=%s",
                    provider_key,
                    p_meta.get("status"),
                    reason,
                )
                continue

            fn = provider_fns[provider_key]
            futures[provider_key] = executor.submit(fn, messages, max_tokens)

        for provider_key, future in futures.items():
            try:
                result = future.result(timeout=timeout_s)
                responses[provider_key] = (result, None)
                logger.info(
                    "[multi_ai_response] provider=%s success len=%d",
                    provider_key,
                    len(result or ""),
                )
            except concurrent.futures.TimeoutError:
                responses[provider_key] = (None, "timeout")
                logger.warning("[multi_ai_response] provider=%s timeout", provider_key)
                _record_provider_failure(provider_key, "timeout")
            except Exception as exc:
                responses[provider_key] = (None, str(exc)[:100])
                logger.warning(
                    "[multi_ai_response] provider=%s error=%s",
                    provider_key,
                    str(exc)[:100],
                )
                _record_provider_failure(provider_key, str(exc)[:100])

    logger.debug(
        "[multi_ai_parallel_done] received=%d/%d responses",
        sum(1 for r, e in responses.values() if r is not None),
        len(responses),
    )

    return responses


def generate_ai_chat_response(
    user_text: str,
    context_summary: str = "",
    max_tokens: int = 400,
    *,
    task: str = "chat",
    symbols: Optional[List[str]] = None,
    priority: str = "normal",
    allow_external: Optional[bool] = None,
) -> Tuple[str, str]:
    """
    Generuje odpowiedź konwersacyjną AI.
    Łańcuch (local-first): local → groq → gemini → openai → heuristic.

    Returns:
        (response_text, provider_used)
    """
    status = get_ai_orchestrator_status()
    providers = status.get("providers", {})
    primary = status.get("primary", "heuristic")
    normalized_symbols = _normalize_symbols(symbols)
    task_name = str(task or "chat").strip().lower()
    priority_name = str(priority or "normal").strip().lower()
    cache_key = _cache_key(task_name, user_text, context_summary, normalized_symbols)
    queue_pressure = status.get("queue_pressure") or {}

    cached = _cache_lookup(task_name, normalized_symbols, cache_key)
    if cached:
        logger.info(
            "[ai_routing] task=%s provider_selected=%s cache_hit=true symbols=%s",
            task_name,
            cached[1],
            normalized_symbols,
        )
        return cached

    cooldown_active, cooldown_symbol = _symbol_cooldown_active(
        task_name, normalized_symbols
    )
    local_only_reasons: List[str] = []
    if allow_external is None:
        allow_external = priority_name == "high" and not _task_local_only(task_name)
    if _task_local_only(task_name):
        allow_external = False
        local_only_reasons.append("task_local_only")
    if priority_name != "high":
        allow_external = False
        local_only_reasons.append("priority_below_high")
    if queue_pressure.get("local_only"):
        allow_external = False
        local_only_reasons.append("queue_pressure_local_only")
    if cooldown_active:
        allow_external = False
        local_only_reasons.append(f"symbol_cooldown:{cooldown_symbol}")

    system_prompt = _CHAT_SYSTEM_PROMPT
    if context_summary:
        system_prompt += f"\n\nAktualny kontekst systemu: {context_summary}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text},
    ]

    _full_chain = [
        ("local", _call_ollama_chat),
        ("groq", _call_groq_chat),
        ("gemini", _call_gemini_chat),
        ("openai", _call_openai_chat),
    ]

    if allow_external and primary not in ("local", "heuristic", "auto"):
        _full_chain = [
            (primary, dict(_full_chain).get(primary))
        ] + [  # type: ignore[arg-type]
            (n, f)
            for n, f in _full_chain
            if n != primary and dict(_full_chain).get(n) is not None
        ]
        _full_chain = [(n, f) for n, f in _full_chain if f is not None]

    wait_event: Optional[threading.Event] = None
    with _AI_INFLIGHT_LOCK:
        inflight = _AI_INFLIGHT.get(cache_key)
        if inflight is not None:
            wait_event = inflight
        else:
            inflight = threading.Event()
            _AI_INFLIGHT[cache_key] = inflight
    if wait_event is not None:
        wait_event.wait(timeout=10)
        return _AI_INFLIGHT_RESULTS.get(
            cache_key, (_heuristic_chat_response(user_text), "heuristic")
        )

    try:
        for provider_name, call_fn in _full_chain:
            if provider_name in {"openai", "groq", "gemini"} and not allow_external:
                continue
            p = providers.get(provider_name, {})
            if not p.get("usable"):
                continue
            if _circuit_open(provider_name):
                continue
            external_ok, external_reason = _allow_external_provider(provider_name)
            if not external_ok:
                logger.info(
                    "[ai_routing] task=%s provider_selected=local provider_fallback_reason=%s",
                    task_name,
                    external_reason,
                )
                continue
            try:
                t0 = time.monotonic()
                response = call_fn(messages, max_tokens)
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                if response:
                    _record_provider_success(provider_name)
                    if provider_name in {"openai", "groq", "gemini"}:
                        _increment_provider_usage(provider_name)
                    _cache_store(
                        task_name,
                        normalized_symbols,
                        cache_key,
                        response,
                        provider_name,
                    )
                    logger.info(
                        "[ai_routing] task=%s provider_selected=%s elapsed_ms=%d cache_hit=false fallback_reason=%s local_only_mode_reason=%s symbols=%s",
                        task_name,
                        provider_name,
                        elapsed_ms,
                        external_reason or "",
                        ",".join(local_only_reasons),
                        normalized_symbols,
                    )
                    result = (response, provider_name)
                    _AI_INFLIGHT_RESULTS[cache_key] = result
                    return result
            except requests.Timeout:
                _record_provider_failure(provider_name, "timeout")
            except Exception as exc:
                _record_provider_failure(provider_name, _safe_text(exc))

        provider_used = "heuristic"
        if providers.get("local", {}).get("usable"):
            try:
                response = _call_ollama_chat(messages, max_tokens)
                if response:
                    _cache_store(
                        task_name,
                        normalized_symbols,
                        cache_key,
                        response,
                        "local",
                    )
                    logger.info(
                        "[ai_routing] task=%s provider_selected=local provider_fallback_reason=%s local_only_mode_reason=%s",
                        task_name,
                        "fallback_chain_exhausted",
                        ",".join(local_only_reasons),
                    )
                    result = (response, "local")
                    _AI_INFLIGHT_RESULTS[cache_key] = result
                    return result
            except Exception:
                pass

        response = _heuristic_chat_response(user_text)
        logger.info(
            "[ai_routing] task=%s provider_selected=heuristic provider_fallback_reason=%s local_only_mode_reason=%s",
            task_name,
            "all_providers_unavailable",
            ",".join(local_only_reasons),
        )
        result = (response, provider_used)
        _AI_INFLIGHT_RESULTS[cache_key] = result
        return result
    finally:
        with _AI_INFLIGHT_LOCK:
            event = _AI_INFLIGHT.pop(cache_key, None)
            if event is not None:
                event.set()
