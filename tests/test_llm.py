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

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, None))
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
    assert data == {"results": []} and prov == "gh:openai/gpt-4.1-mini"
    assert s.calls[0][1]["response_format"] == {"type": "json_object"}


def test_non_json_falls_back_to_next_provider(monkeypatch):
    s = _S(_R(200, None, text="<html>oops</html>", ctype="text/html"), ok('{"results": [1]}'))
    c = LLMClient(_providers(monkeypatch), session=s)
    data, prov = c.complete_json("sys", "u")
    assert prov == "gem:g" and data == {"results": [1]}


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


def _model_gone(name):
    return _R(404, text='{"error":{"message":"The model `%s` does not exist or you do not have '
                        'access to it.","code":"model_not_found"}}' % name)


def test_falls_through_model_preference_list(monkeypatch):
    monkeypatch.setenv("K1", "a")
    p = LLMProvider("groq", "https://api.groq.com/openai/v1", ["big", "small"], "K1")
    s = _S(_model_gone("big"), ok('{"results": []}'), ok('{"results": [2]}'))
    c = LLMClient([p], session=s)
    assert c.complete_json("s", "u")[1] == "groq:small"
    # Second call goes straight to the model that worked.
    assert c.complete_json("s", "u") == ({"results": [2]}, "groq:small")
    assert [b["model"] for _, b in s.calls] == ["big", "small", "small"]


def test_discovers_models_when_all_configured_are_gone(monkeypatch):
    monkeypatch.setenv("K1", "a")
    p = LLMProvider("groq", "https://api.groq.com/openai/v1", "retired", "K1")
    listing = _R(200, {"data": [{"id": "whisper-large-v3"}, {"id": "new-chat-model"}]})
    s = _S(_model_gone("retired"), listing, ok('{"results": []}'))
    data, prov = LLMClient([p], session=s).complete_json("s", "u")
    assert prov == "groq:new-chat-model"
    assert s.calls[1][0] == "https://api.groq.com/openai/v1/models"


def test_all_models_gone_marks_provider_exhausted(monkeypatch):
    monkeypatch.setenv("K1", "a")
    p = LLMProvider("groq", "https://x/v1", "retired", "K1")
    s = _S(_model_gone("retired"), _R(200, {"data": []}))
    c = LLMClient([p], session=s)
    with pytest.raises(LLMUnavailable):
        c.complete_json("s", "u")
    assert not c.available
