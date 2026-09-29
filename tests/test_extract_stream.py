"""#62: synthetic chunks only; no live model calls."""
import asyncio
import json
import logging

import pytest
from fastapi.testclient import TestClient

import main
from mimamori import agent, auth, ledger
from mimamori.schema import Extraction
from test_extract_retry import fake_runner


def item(**patch):
    return dict(kind="event", title="架空行事", child="下の子",
                date="2026-12-05", date_text="2026年12月5日（土）", **patch)


@pytest.mark.parametrize("size", [1, 2, 7, 31, 1000])
def test_closed_items_all_boundaries(size):
    rows = [item(note='日本語 { } " \\ 改行\n', bring=['[ ]', '末尾\\']),
            item(note='別の "items": [{}]')]
    text = json.dumps({"summary": '偽の "items": [{}]', "nested": {"items": [{}]},
                       "items": rows}, ensure_ascii=False)
    previous = []
    for end in range(size, len(text) + size, size):
        current = agent.closed_items(text[:end])
        assert current[:len(previous)] == previous
        assert current == rows[:len(current)]
        previous = current
    assert previous == rows


def test_one_generation_schema_prompt_and_environment_client(fake_runner):
    fake_runner.replies = [json.dumps({"summary": "", "items": []})]
    asyncio.run(agent.read_otayori(b"synthetic", "image/jpeg"))
    assert len(fake_runner.calls) == 1 and fake_runner.closed == 1
    call = fake_runner.calls[0]
    assert call["model"] == agent.config.model
    assert call["config"].response_schema is Extraction
    assert call["config"].response_mime_type == "application/json"
    assert call["config"].thinking_config.thinking_budget == 512
    assert agent.AMBIGUOUS_PROMPT in call["contents"].parts[1].text
    assert "list_events" not in call["config"].system_instruction
    assert not call["config"].tools


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr(ledger, "_store", ledger._LocalStore(tmp_path / "ledger.json"))
    monkeypatch.setattr(main.images_mod, "normalize", lambda data, mime: (data, mime))
    monkeypatch.setattr(auth, "enabled", lambda: False)
    return TestClient(main.app)


def post(api):
    response = api.post("/api/extract/stream",
                        files={"image": ("test.png", b"synthetic", "image/png")})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    return [json.loads(line) for line in response.text.splitlines()]


@pytest.mark.parametrize("child", [None, "下の子"])
def test_stream_order_review_questions_and_scope(api, fake_runner, monkeypatch, child):
    monkeypatch.setattr(main, "_user", lambda request: child or auth.PARENT)
    monkeypatch.setattr(agent, "list_raw", lambda *args: [
        {"id": "same", "summary": "架空行事", "date": "2026-12-05", "child": child or "下の子"},
        {"id": "sibling", "summary": "習字", "date": "2026-12-05", "child": "上の子"},
    ])
    rows = [item(), {**item(), "title": "習字"},
            {**item(), "title": "提出", "date": None, "date_text": "明後日"}]
    text = json.dumps({"summary": "架空", "items": rows}, ensure_ascii=False)
    fake_runner.replies = [[text[i:i+13] for i in range(0, len(text), 13)]]
    events = post(api)
    expected = ["received", "reading"] + (["item"] if child else []) + ["question", "done"]
    assert [e["type"] for e in events] == expected
    done = events[-1]
    assert done["skipped"] == (1 if child else 2)
    assert done["date_questions_count"] == 1 and "date_questions" not in done
    if child:
        assert events[2]["item"] == done["items"][0]
        assert all(e["item"]["child"] == child for e in events if "item" in e)
        assert "sibling" not in json.dumps(events)


@pytest.mark.parametrize("recover", [False, True])
def test_partial_failure_reset_and_no_question_persistence(api, fake_runner, monkeypatch, recover):
    monkeypatch.setattr(agent, "_review", lambda items, child: dict(items=items, skipped=0, skipped_titles=[]))
    partial = '{"items":[' + json.dumps({**item(), "date_text": "明後日"}) + '],'
    good = json.dumps({"summary": "", "items": [item()]})
    fake_runner.replies = [partial, good if recover else partial]
    events = post(api)
    assert [e["type"] for e in events] == (
        ["received", "reading", "question", "reset", "reading"]
        + (["item", "done"] if recover else ["question", "error"]))
    assert len(fake_runner.calls) == 2
    assert not main.ambiguous_dates.pending()
    if not recover:
        assert events[-1]["detail"] == "読み取りに失敗しました。もう一度試してください。"


def test_stream_auth_required(api, fake_runner, monkeypatch):
    monkeypatch.setattr(auth, "enabled", lambda: True)
    r = api.post("/api/extract/stream", files={"image": ("x", b"x", "image/png")})
    assert r.status_code == 401
    assert not fake_runner.calls


def test_timing_logs_contain_only_metrics(api, fake_runner, caplog):
    fake_runner.replies = [json.dumps({"summary": "PRIVATE", "items": []})]
    with caplog.at_level(logging.INFO):
        post(api)
    assert "received_bytes=9 conversion_seconds=" in caplog.text
    assert "first_item_seconds=" in caplog.text and "total_seconds=" in caplog.text
    assert "retried=False" in caplog.text and "prompt_token_count=1648" in caplog.text
    assert "PRIVATE" not in caplog.text and "synthetic" not in caplog.text


def test_item_is_delivered_before_model_finishes(fake_runner, monkeypatch):
    monkeypatch.setattr(agent, "_review", lambda items, child: dict(items=items, skipped=0, skipped_titles=[]))
    first = '{"summary":"架空","items":[' + json.dumps(item())
    fake_runner.replies = [[first, "]}"]]

    async def consume():
        stream = agent.stream_otayori(b"synthetic", "image/png")
        assert (await anext(stream))["type"] == "reading"
        event = await anext(stream)
        assert event["type"] == "item"
        assert event["item"]["title"] == "架空行事"
        assert (await anext(stream))["type"] == "done"
        await stream.aclose()

    asyncio.run(consume())
    assert fake_runner.closed == 1


@pytest.mark.parametrize("child", [None, "下の子"])
@pytest.mark.parametrize("reset", [False, True])
def test_disconnect_after_question_still_persists_final_once(api, fake_runner, monkeypatch, child, reset):
    """Use ASGI http.disconnect while the real extractor is paused mid-stream."""
    from io import BytesIO
    from starlette.datastructures import UploadFile, Headers
    from starlette.requests import Request

    monkeypatch.setattr(main, "_user", lambda request: child or auth.PARENT)
    monkeypatch.setattr(agent, "list_raw", lambda *args: [])
    question = {**item(), "title": "最終の質問", "date": None, "date_text": "明後日"}
    good = json.dumps({"summary": "", "items": [question]})
    partial = '{"items":[' + json.dumps(dict(question, title="破棄する質問")) + '],'
    fake_runner.replies = [partial, good] if reset else [good]
    enqueue = main.ambiguous_dates.enqueue
    saved = []

    def save(items):
        saved.append([dict(i) for i in items])
        return enqueue(items)

    monkeypatch.setattr(main.ambiguous_dates, "enqueue", save)

    async def scenario():
        disconnected = asyncio.Event()
        resume = asyncio.Event()
        finished = asyncio.Event()
        seen = []
        original = main.stream_otayori

        async def paused(*args, **kwargs):
            try:
                async for event in original(*args, **kwargs):
                    yield event
                    if event["type"] == "question":
                        await resume.wait()
            finally:
                finished.set()

        monkeypatch.setattr(main, "stream_otayori", paused)
        scope = {"type": "http", "asgi": {"spec_version": "2.0"}}
        response = await main.extract_stream(
            Request(scope), UploadFile(BytesIO(b"synthetic"),
                                       headers=Headers({"content-type": "image/png"})), "")

        async def send(message):
            if message["type"] == "http.response.body" and message.get("body"):
                event = json.loads(message["body"])
                seen.append(event["type"])
                if event["type"] == "question":
                    disconnected.set()

        async def receive():
            await disconnected.wait()
            return {"type": "http.disconnect"}

        await asyncio.wait_for(response(scope, receive, send), 2)
        assert seen[-1] == "question" and "done" not in seen
        assert not saved and not main.ambiguous_dates.pending()
        resume.set()
        await asyncio.wait_for(finished.wait(), 2)
        assert len(saved) == 1
        assert [i["title"] for i in saved[0]] == ["最終の質問"]
        pending = main.ambiguous_dates.pending()
        assert len(pending) == 1
        assert pending[0]["child"] == "下の子"
        assert len(fake_runner.calls) == (2 if reset else 1)
        assert seen[-1] == "question"  # No relay resumes after disconnect.

    asyncio.run(scenario())
