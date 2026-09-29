"""#57: モデル・カレンダーへ通信せず、google-genai のチャンクで再試行を確かめる。"""
import asyncio
import json
import logging
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from google.genai import types
from google import genai

import main
from mimamori import agent

PRIVATE = "架空のおたより本文・氏名"
GOOD = json.dumps({"summary": PRIVATE, "items": []}, ensure_ascii=False)


def response(text):
    return types.GenerateContentResponse(
        candidates=[types.Candidate(
            content=types.Content(role="model", parts=[] if text is None else [types.Part(text=text)]),
            finish_reason=types.FinishReason.STOP,
        )],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=1648, thoughts_token_count=809,
        ),
    )


@pytest.fixture
def fake_runner(monkeypatch):
    state = SimpleNamespace(replies=[], calls=[], closed=0)

    class Client:
        def __init__(self):
            self.aio = self
            self.models = self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            state.closed += 1

        async def generate_content_stream(self, **kwargs):
            state.calls.append(kwargs)
            reply = state.replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            async def chunks():
                for part in reply if isinstance(reply, list) else [reply]:
                    yield response(part)
            return chunks()

    monkeypatch.setattr(genai, "Client", Client)
    return state


def read(child=None):
    return asyncio.run(agent.read_otayori(b"dummy image", "image/png", PRIVATE, child))


def retry_logs(caplog):
    return [r for r in caplog.records if r.name == "mimamori.agent"]


@pytest.mark.parametrize("child", [None, "下の子"])
@pytest.mark.parametrize("first,kind", [
    (None, "empty_response"), ("   ", "empty_response"),
    (PRIVATE, "missing_json"), ('{"summary": "' + PRIVATE + '",}', "invalid_json"),
])
def test_retry_recovers_with_same_input(fake_runner, caplog, first, kind, child):
    caplog.set_level(logging.WARNING, logger="mimamori.agent")
    fake_runner.replies = [first, GOOD]
    out = read(child)
    assert out["summary"] == PRIVATE
    assert len(fake_runner.calls) == 2
    assert fake_runner.closed == 1
    a, b = fake_runner.calls
    assert a["contents"] == b["contents"]
    assert a["contents"].parts[0].inline_data.data == b"dummy image"
    if child:
        assert f"child は必ず {child}" in fake_runner.calls[0]["config"].system_instruction
        assert not fake_runner.calls[0]["config"].tools
    logs = retry_logs(caplog)
    assert len(logs) == 1
    message = logs[0].getMessage()
    assert f"first_failure={kind}" in message
    assert "finish_reason=STOP" in message
    assert "prompt_token_count=1648 thoughts_token_count=809 candidates_token_count=None" in message
    assert "retry_result=success" in message
    assert PRIVATE not in caplog.text
    assert "dummy image" not in caplog.text


def test_two_empty_responses_raise_original_error(fake_runner, caplog):
    fake_runner.replies = [None, None]
    with pytest.raises(ValueError):
        read()
    assert len(fake_runner.calls) == 2
    assert len(retry_logs(caplog)) == 1
    assert "retry_result=failure" in caplog.text


def test_success_does_not_retry(fake_runner, caplog):
    fake_runner.replies = [GOOD]
    assert read()["summary"] == PRIVATE
    assert len(fake_runner.calls) == 1
    assert not retry_logs(caplog)


def test_retry_runner_failure_is_logged_without_exception_text(fake_runner, caplog):
    fake_runner.replies = [None, RuntimeError(PRIVATE)]
    with pytest.raises(RuntimeError):
        read()
    assert len(fake_runner.calls) == 2
    assert "retry_result=failure" in caplog.text
    assert PRIVATE not in caplog.text


def test_initial_runner_failure_is_not_retried(fake_runner, caplog):
    fake_runner.replies = [RuntimeError(PRIVATE)]
    with pytest.raises(RuntimeError):
        read()
    assert len(fake_runner.calls) == 1
    assert not retry_logs(caplog)


def test_extract_two_empty_responses_returns_existing_500(fake_runner, monkeypatch):
    fake_runner.replies = [None, None]
    monkeypatch.setattr(main.auth, "enabled", lambda: False)
    monkeypatch.setattr(main, "_user", lambda request: "parent")
    monkeypatch.setattr(main.images_mod, "normalize", lambda data, mime: (data, mime))
    with TestClient(main.app) as client:
        result = client.post("/api/extract", files={"image": ("test.png", b"dummy image", "image/png")})
    assert result.status_code == 500
    assert result.json() == {"detail": "読み取りに失敗しました。もう一度試してください。"}
    assert len(fake_runner.calls) == 2
