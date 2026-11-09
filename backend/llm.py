"""Thin Gemini REST client.

Deliberately not using the SDK: the installed google-genai is old, and the raw
REST surface lets us pin exactly what we send. Two call shapes are used by the
pipeline -- free text and schema-constrained JSON.

Grounding note: `tools:[{google_search:{}}]` returns 429 on a free-tier key, so
this app never asks the model to search. Retrieval is done by backend/sources.py
and the model only ever reasons over evidence we fetched ourselves. That is the
reason a citation in this system cannot be hallucinated.
"""
from __future__ import annotations

import json
import time
from typing import Any, Optional

import requests

from . import config


class LLMError(RuntimeError):
    pass


# Transient / "try the next model" conditions seen in practice.
_FALLTHROUGH = {404, 429, 500, 502, 503, 504}

_last_model_used: Optional[str] = None
_calls = 0


def stats() -> dict[str, Any]:
    return {"calls": _calls, "last_model": _last_model_used, "chain": config.GEMINI_MODELS}


def _post(model: str, body: dict[str, Any]) -> requests.Response:
    url = f"{config.GEMINI_BASE}/models/{model}:generateContent"
    return requests.post(
        url,
        headers={"x-goog-api-key": config.GEMINI_API_KEY, "Content-Type": "application/json"},
        json=body,
        timeout=90,
    )


def _extract_text(payload: dict[str, Any]) -> str:
    cands = payload.get("candidates") or []
    if not cands:
        fb = payload.get("promptFeedback", {})
        raise LLMError(f"no candidates (promptFeedback={fb})")
    cand = cands[0]
    parts = (cand.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    if not text.strip():
        raise LLMError(f"empty completion (finishReason={cand.get('finishReason')})")
    return text


def generate(
    prompt: str,
    *,
    system: str = "",
    schema: Optional[dict[str, Any]] = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    retries_per_model: int = 2,
) -> str:
    """Return raw completion text. Walks the model chain on transient failure."""
    global _last_model_used, _calls

    if not config.GEMINI_API_KEY:
        raise LLMError("GEMINI_API_KEY is not set (see .env)")

    gen_cfg: dict[str, Any] = {"temperature": temperature, "maxOutputTokens": max_tokens}
    if schema is not None:
        gen_cfg["responseMimeType"] = "application/json"
        gen_cfg["responseSchema"] = schema

    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": gen_cfg,
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}

    problems: list[str] = []
    for model in config.GEMINI_MODELS:
        for attempt in range(retries_per_model):
            try:
                resp = _post(model, body)
            except requests.RequestException as exc:
                problems.append(f"{model}: {type(exc).__name__}")
                time.sleep(1.0 + attempt)
                continue

            if resp.status_code == 200:
                _calls += 1
                _last_model_used = model
                return _extract_text(resp.json())

            msg = ""
            try:
                msg = (resp.json().get("error") or {}).get("message", "")[:160]
            except Exception:
                msg = resp.text[:160]
            problems.append(f"{model}: {resp.status_code} {msg}")

            if resp.status_code in _FALLTHROUGH:
                time.sleep(0.8 + attempt)
                continue
            break  # 400-class: body is wrong, next model will not help

    raise LLMError("all models failed -> " + " | ".join(problems[-4:]))


def generate_json(
    prompt: str,
    schema: dict[str, Any],
    *,
    system: str = "",
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> Any:
    """Schema-constrained call. Returns parsed JSON."""
    raw = generate(
        prompt, system=system, schema=schema, temperature=temperature, max_tokens=max_tokens
    )
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = min((i for i in (raw.find("{"), raw.find("[")) if i != -1), default=-1)
        end = max(raw.rfind("}"), raw.rfind("]"))
        if start != -1 and end > start:
            return json.loads(raw[start : end + 1])
        raise LLMError(f"model did not return JSON: {raw[:200]!r}")


def health() -> dict[str, Any]:
    """Cheap liveness probe used by the UI status rail."""
    if not config.GEMINI_API_KEY:
        return {"ok": False, "detail": "no api key"}
    try:
        out = generate("Reply with the single word: ok", max_tokens=256, temperature=0.0)
        return {"ok": True, "model": _last_model_used, "detail": out.strip()[:40]}
    except Exception as exc:
        return {"ok": False, "detail": str(exc)[:200]}
