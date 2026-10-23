"""OpenAI-compatible chat client that falls through a list of free providers.

GitHub Models works inside GitHub Actions with the built-in GITHUB_TOKEN (the
workflow grants `models: read`), so the default setup needs no API keys at all.
Gemini's OpenAI-compatible endpoint is the fallback when GitHub's daily quota
runs out.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from .config import LLMProvider

log = logging.getLogger(__name__)
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


class LLMUnavailable(RuntimeError):
    pass


def _parse_json(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_RE.search(text or "")
        if not m:
            raise
        return json.loads(m.group(0))


class LLMClient:
    def __init__(self, providers: list[LLMProvider]):
        self.providers = [p for p in providers if p.api_key]
        self.exhausted: set[str] = set()
        self.calls = 0
        if not self.providers:
            log.info("No LLM API keys found; using heuristic scoring only")

    @property
    def available(self) -> bool:
        return any(p.name not in self.exhausted for p in self.providers)

    def complete_json(self, system: str, user: str) -> tuple[dict[str, Any], str]:
        from openai import OpenAI  # imported lazily so tests don't need it

        last_error: Exception | None = None
        for p in self.providers:
            if p.name in self.exhausted:
                continue
            client = OpenAI(base_url=p.base_url, api_key=p.api_key, timeout=60, max_retries=1)
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
            try:
                try:
                    resp = client.chat.completions.create(
                        model=p.model,
                        messages=messages,
                        temperature=0.2,
                        response_format={"type": "json_object"},
                    )
                except Exception as exc:
                    if getattr(exc, "status_code", None) == 400:
                        # Some models reject response_format; retry without it.
                        resp = client.chat.completions.create(
                            model=p.model, messages=messages, temperature=0.2
                        )
                    else:
                        raise
                self.calls += 1
                return _parse_json(resp.choices[0].message.content or ""), p.name
            except Exception as exc:
                status = getattr(exc, "status_code", None)
                log.warning("LLM provider %s failed (%s): %s", p.name, status, exc)
                # Rate limits and auth problems won't fix themselves this run.
                if status in (401, 403, 429) or "rate" in str(exc).lower():
                    self.exhausted.add(p.name)
                last_error = exc
        raise LLMUnavailable(str(last_error) if last_error else "no providers")
