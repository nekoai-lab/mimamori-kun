"""#57: モデル・カレンダーへ通信せず、ADK のイベントで再試行を確かめる。"""
import asyncio
import json
import logging
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from google.adk.events import Event
from google.adk.models.llm_response import LlmResponse
from google.genai import types

import main
from mimamori import agent

PRIVATE = "架空のおたより本文・氏名"
GOOD = json.dumps({"summary": PRIVATE, "items": []}, ensure_ascii=False)


def response(text):
    # ADK 1.3 の実際の変換を通す（空なら STOP は error_code に入る）。
    raw = types.GenerateContentResponse(
        candidates=[types.Candidate(
            content=types.Content(role="model", parts=[] if text is None else [types.Part(text=text)]),
            finish_reason=types.FinishReason.STOP,
        )],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=1648, thoughts_token_count=809,
        ),
    )
    return Event(author="mimamori_reader", **LlmResponse.create(raw).model_dump())


@pytest.fixture
def fake_runner(monkeypatch):
    state = SimpleNamespace(replies=[], calls=[], sessions=[], agents=[])

    class Runner:
        def __init__(self, agent, app_name):
            state.agents.append(agent)
            self.session_service = self

        async def create_session(self, **kwargs):
            session = SimpleNamespace(id=str(len(state.sessions)))
            state.sessions.append(session)
            return session

        async def run_async(self, **kwargs):
            state.calls.append(kwargs)
            reply = state.replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            yield response(reply)

    monkeypatch.setattr(agent, "InMemoryRunner", Runner)
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
def test_retry_recovers_with_fresh_session(fake_runner, caplog, first, kind, child):
    caplog.set_level(logging.WARNING, logger="mimamori.agent")
    fake_runner.replies = [first, GOOD]
    out = read(child)
    assert out["summary"] == PRIVATE
    assert len(fake_runner.calls) == 2
    assert len(fake_runner.sessions) == 2
    a, b = fake_runner.calls
    assert a["session_id"] != b["session_id"]
    assert a["new_message"] == b["new_message"]
    assert a["new_message"].parts[0].inline_data.data == b"dummy image"
    if child:
        assert f"child は必ず {child}" in fake_runner.agents[0].instruction
        assert fake_runner.agents[0].tools[0] is not agent.list_events
    logs = retry_logs(caplog)
    assert len(logs) == 1
    message = logs[0].getMessage()
    assert f"first_failure={kind}" in message
    assert f"finish_reason={'STOP' if first is None else 'unknown'}" in message
    assert "prompt_token_count=1648 thoughts_token_count=809 candidates_token_count=None" in message
    assert "retry_result=success" in message
    assert PRIVATE not in caplog.text
    assert "dummy image" not in caplog.text


def test_two_empty_responses_raise_original_error(fake_runner, caplog):
    fake_runner.replies = [None, None]
    with pytest.raises(ValueError, match="^JSON が見つかりません: $"):
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
    assert result.json() == {"detail": "読み取りに失敗しました: JSON が見つかりません: "}
    assert len(fake_runner.calls) == 2
