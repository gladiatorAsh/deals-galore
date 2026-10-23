from __future__ import annotations

import pytest

from dealsgalore.config import LLMProvider
from dealsgalore.llm import LLMClient, LLMUnavailable, chat_url


class _R:
    def __init__(self, status, payload=None, text="", ctype="application/json"):
        self.status_code, self._payload, self.text = status, payload, text
        self.headers = {"Content-Type": ctype}

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _S:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append((url, json))
        return self.responses.pop(0)


def _providers(monkeypatch):
    monkeypatch.setenv("K1", "a")
    monkeypatch.setenv("K2", "b")
    return [LLMProvider("gh", "https://models.github.ai/inference", "openai/gpt-4.1-mini", "K1"),
            LLMProvider("gem", "https://x/v1beta/openai/", "g", "K2")]


def ok(content):
    return _R(200, {"choices": [{"message": {"content": content}}]})


def test_chat_url():
    assert chat_url("https://models.github.ai/inference") == "https://models.github.ai/inference/chat/completions"
    assert chat_url("https://x/v1beta/openai/") == "https://x/v1beta/openai/chat/completions"
    assert chat_url("https://a/chat/completions") == "https://a/chat/completions"


def test_success_and_fenced_json(monkeypatch):
    s = _S(ok('```json\n{"results": []}\n```'))
    data, prov = LLMClient(_providers(monkeypatch), session=s).complete_json("sys", "u")
    assert data == {"results": []} and prov == "gh"
    assert s.calls[0][1]["response_format"] == {"type": "json_object"}


def test_non_json_falls_back_to_next_provider(monkeypatch):
    s = _S(_R(200, None, text="<html>oops</html>", ctype="text/html"), ok('{"results": [1]}'))
    c = LLMClient(_providers(monkeypatch), session=s)
    data, prov = c.complete_json("sys", "u")
    assert prov == "gem" and data == {"results": [1]}


def test_400_retries_without_response_format(monkeypatch):
    s = _S(_R(400, text="response_format unsupported"), ok('{"results": []}'))
    LLMClient(_providers(monkeypatch), session=s).complete_json("sys", "u")
    assert "response_format" not in s.calls[1][1]


def test_rate_limit_exhausts_provider(monkeypatch):
    s = _S(_R(429, text="rate limited"), _R(429, text="rate limited"))
    c = LLMClient(_providers(monkeypatch), session=s)
    with pytest.raises(LLMUnavailable):
        c.complete_json("sys", "u")
    assert c.exhausted == {"gh", "gem"} and not c.available
