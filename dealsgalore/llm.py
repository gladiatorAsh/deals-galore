"""OpenAI-compatible chat client that falls through a list of free providers.

Defaults: Groq's free tier first, Gemini's OpenAI-compatible endpoint as the
fallback. Any OpenAI-compatible provider can be added in config.yaml.

Calls go straight over HTTP (no SDK) so that any unexpected response is
reported with its status and content type instead of failing obscurely.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import requests

from .config import LLMProvider

log = logging.getLogger(__name__)
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


class LLMUnavailable(RuntimeError):
    pass


class LLMError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _parse_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_RE.search(text)
        if not m:
            raise
        return json.loads(m.group(0))


def chat_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    return base if base.endswith("/chat/completions") else f"{base}/chat/completions"


class LLMClient:
    def __init__(self, providers: list[LLMProvider], session: Any = None):
        self.providers = [p for p in providers if p.api_key]
        self.exhausted: set[str] = set()
        self.working: dict[str, str] = {}
        self.waited = 0.0  # seconds spent waiting out rate limits this run
        self.sleep = time.sleep
        self.calls = 0
        self.session = session or requests
        if not self.providers:
            log.info("No LLM API keys found; using heuristic scoring only")

    @property
    def available(self) -> bool:
        return any(p.name not in self.exhausted for p in self.providers)

    def _post(self, p: LLMProvider, body: dict[str, Any]) -> dict[str, Any]:
        r = self.session.post(
            chat_url(p.base_url),
            json=body,
            headers={
                "Authorization": f"Bearer {p.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=90,
        )
        ctype = r.headers.get("Content-Type", "")
        if r.status_code >= 400:
            detail = r.text[:300].replace("\n", " ")
            raise LLMError(f"HTTP {r.status_code}: {detail}", r.status_code)
        try:
            data = r.json()
        except ValueError:
            raise LLMError(
                f"non-JSON response (HTTP {r.status_code}, {ctype or 'no content-type'}): "
                f"{r.text[:200]!r}", r.status_code
            ) from None
        if not isinstance(data, dict) or not data.get("choices"):
            raise LLMError(f"unexpected response shape: {str(data)[:200]}", r.status_code)
        return data

    def _list_models(self, p: LLMProvider) -> list[str]:
        """Ask an OpenAI-compatible provider which models this key can use."""
        url = chat_url(p.base_url).rsplit("/chat/completions", 1)[0] + "/models"
        try:
            r = self.session.get(url, headers={"Authorization": f"Bearer {p.api_key}"}, timeout=30)
            if r.status_code >= 400:
                return []
            ids = [m.get("id", "") for m in (r.json().get("data") or [])]
        except Exception:
            return []
        skip = ("whisper", "tts", "guard", "embed", "vision", "audio", "speech", "image", "compound")
        ids = [i.removeprefix("models/") for i in ids if i and not any(k in i.lower() for k in skip)]
        return sorted(ids)

    def _try_model(self, p: LLMProvider, model: str, messages: list) -> dict[str, Any]:
        body = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        try:
            return self._post(p, body)
        except LLMError as exc:
            if exc.status in (400, 422) and not _is_model_error(exc):
                # Some models reject response_format; retry without it.
                body.pop("response_format")
                return self._post(p, body)
            raise

    def complete_json(self, system: str, user: str) -> tuple[dict[str, Any], str]:
        last_error: Exception | None = None
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        for p in self.providers:
            if p.name in self.exhausted:
                continue
            # Prefer the model that worked earlier this run, then the configured list.
            candidates = [m for m in [self.working.get(p.name), *p.models] if m]
            tried: set[str] = set()
            retried: set[str] = set()
            discovered = rate_limited = False
            while True:
                model = next((m for m in candidates if m not in tried), None)
                if model is None:
                    if discovered or rate_limited:
                        break
                    discovered = True
                    found = self._list_models(p)
                    if found:
                        log.warning("Configured models unavailable on %s; trying discovered: %s",
                                    p.name, ", ".join(found[:5]))
                    candidates = found
                    continue
                tried.add(model)
                try:
                    data = self._try_model(p, model, messages)
                    self.calls += 1
                    if self.working.get(p.name) != model:
                        if model != p.models[0]:
                            log.warning("Using %s model %s (update config.yaml to silence this)",
                                        p.name, model)
                        self.working[p.name] = model
                    content = data["choices"][0].get("message", {}).get("content") or ""
                    return _parse_json(content), f"{p.name}:{model}"
                except LLMError as exc:
                    last_error = exc
                    if _is_model_error(exc):
                        log.info("%s model %s unavailable: %s", p.name, model, exc)
                        continue  # try the next model
                    if exc.status == 429:
                        # Free tiers limit tokens per minute PER MODEL: wait out a short
                        # limit once, otherwise move on to the next model.
                        wait = _retry_after(str(exc))
                        if (wait is not None and wait <= MAX_WAIT and model not in retried
                                and self.waited + wait <= MAX_TOTAL_WAIT):
                            retried.add(model)
                            tried.discard(model)
                            self.waited += wait
                            log.info("%s model %s rate-limited; waiting %.0fs", p.name, model, wait)
                            self.sleep(wait + 1)
                            continue
                        log.info("%s model %s rate-limited; trying the next model", p.name, model)
                        rate_limited = True
                        continue
                    log.warning("LLM provider %s failed: %s", p.name, exc)
                    if exc.status in (401, 403, 429) or "rate" in str(exc).lower():
                        self.exhausted.add(p.name)
                    break
                except Exception as exc:  # unparseable content etc.
                    log.warning("LLM provider %s failed: %s", p.name, exc)
                    last_error = exc
                    break
            if p.name not in self.working or rate_limited:
                if rate_limited:
                    log.warning("LLM provider %s: all models rate-limited for now", p.name)
                self.exhausted.add(p.name)
        raise LLMUnavailable(str(last_error) if last_error else "no providers")


MAX_WAIT = 30  # seconds: longest single rate-limit wait worth taking
MAX_TOTAL_WAIT = 120  # seconds of waiting per run, across all calls


def _retry_after(text: str) -> float | None:
    """Parse Groq/OpenAI style 'try again in 18.9s' or '1m23.4s'."""
    m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", text)
    if not m:
        return None
    return int(m.group(1) or 0) * 60 + float(m.group(2))


def _is_model_error(exc: LLMError) -> bool:
    text = str(exc).lower()
    return exc.status in (400, 403, 404) and (
        "model_not_found" in text or "does not exist" in text or "no longer available" in text
        or "model_decommissioned" in text or "decommissioned" in text
        or ("model" in text and "not found" in text) or "no access to model" in text
    )
