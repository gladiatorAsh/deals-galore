"""OpenAI-compatible chat client that falls through a list of free providers.

GitHub Models works inside GitHub Actions with the built-in GITHUB_TOKEN (the
workflow grants `models: read`), so the default setup needs no API keys at all.
Gemini's OpenAI-compatible endpoint is the fallback when GitHub's daily quota
runs out.

Calls go straight over HTTP (no SDK) so that any unexpected response is
reported with its status and content type instead of failing obscurely.
"""
from __future__ import annotations

import json
import logging
import re
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

    def complete_json(self, system: str, user: str) -> tuple[dict[str, Any], str]:
        last_error: Exception | None = None
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        for p in self.providers:
            if p.name in self.exhausted:
                continue
            body = {
                "model": p.model,
                "messages": messages,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
            }
            try:
                try:
                    data = self._post(p, body)
                except LLMError as exc:
                    if exc.status in (400, 422):
                        # Some models reject response_format; retry without it.
                        body.pop("response_format")
                        data = self._post(p, body)
                    else:
                        raise
                self.calls += 1
                content = data["choices"][0].get("message", {}).get("content") or ""
                return _parse_json(content), p.name
            except Exception as exc:
                status = getattr(exc, "status", None)
                log.warning("LLM provider %s failed: %s", p.name, exc)
                # Auth, quota and rate-limit problems won't fix themselves this run.
                if status in (401, 403, 404, 429) or "rate" in str(exc).lower():
                    self.exhausted.add(p.name)
                last_error = exc
        raise LLMUnavailable(str(last_error) if last_error else "no providers")
