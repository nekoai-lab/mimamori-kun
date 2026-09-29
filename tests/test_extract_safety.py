"""#62 follow-up: synthetic model data, clocks and transport failures only."""
import asyncio
import json
import logging

import httpx
import pytest
from google.genai import errors

import main
from mimamori import agent, auth
from test_extract_retry import fake_runner
from test_extract_stream import api, post, item


@pytest.mark.parametrize('waiting', [False, True])
def test_normalized_stream_event_and_done(fake_runner, monkeypatch, waiting):
    monkeypatch.setattr(agent, '_review', lambda items, child: dict(items=items, skipped=0, skipped_titles=[]))
    raw = {**item(), 'child':'elementary'}
    if waiting:
        raw['date_text'] = '明後日'
    fake_runner.replies = [json.dumps(dict(summary='', items=[raw]))]
    async def consume():
        return [e async for e in agent.stream_otayori(b'fake', 'image/png')]
    events = asyncio.run(consume())
    assert events[1]['type'] == ('question' if waiting else 'item')
    assert events[1]['item']['child'] == '下の子'
    assert events[-1]['date_questions' if waiting else 'items'] == [events[1]['item']]


def test_sdk_limits(fake_runner):
    fake_runner.replies = [json.dumps(dict(summary='', items=[]))]
    asyncio.run(agent.read_otayori(b'fake', 'image/png'))
    cfg = fake_runner.calls[0]['config']
    assert cfg.http_options.timeout == 20000
    assert cfg.http_options.retry_options.attempts == 1


def test_extraction_prompt_and_schema_without_date_enumeration(fake_runner):
    fake_runner.replies = [json.dumps(dict(summary='', items=[]))]
    asyncio.run(agent.read_otayori(b'fake', 'image/png'))
    call = fake_runner.calls[0]
    cfg = call['config']
    prompt = cfg.system_instruction + call['contents'].parts[1].text
    assert 'date_mentions' not in prompt
    assert '列挙' not in prompt
    assert 'date_mentions' not in cfg.response_schema.model_json_schema()['properties']
    assert agent.AMBIGUOUS_PROMPT in prompt


@pytest.mark.parametrize('kind', ['429', '503', 'timeout', 'httpx'])
@pytest.mark.parametrize('child', [False, True])
@pytest.mark.parametrize('streaming', [False, True])
def test_temporary_api_failure(api, fake_runner, monkeypatch, caplog, kind, child, streaming):
    exc = (errors.ClientError(429, {'error': {'message':'PRIVATE'}}) if kind == '429' else
           errors.ServerError(503, {'error': {'message':'PRIVATE'}}) if kind == '503' else
           httpx.ReadTimeout('PRIVATE') if kind == 'httpx' else TimeoutError('PRIVATE'))
    fake_runner.replies = [exc]
    monkeypatch.setattr(main, '_user', lambda r: '下の子' if child else auth.PARENT)
    with caplog.at_level(logging.WARNING):
        if streaming:
            result = post(api)[-1]
            assert result['type'] == 'error'
        else:
            response = api.post('/api/extract', files={'image':('x.png', b'fake', 'image/png')})
            assert response.status_code == 503
            result = response.json()
    assert result['temporary'] is True
    assert result['detail'] == ('いまは よめないよ。すこし まってから もういちど ためしてね' if child else
                                'いまは読み取りが混み合っています。少し待ってからもう一度お試しください')
    failures = [r for r in caplog.records if r.name == 'main']
    status = int(kind) if kind.isdigit() else None
    assert [r.getMessage() for r in failures] == [f'extract failure: type={type(exc).__name__} status={status}']
    assert all(r.exc_info is None for r in failures)
    assert 'PRIVATE' not in caplog.text
    assert len(fake_runner.calls) == 1


@pytest.mark.parametrize('text', ['', '{broken'])
@pytest.mark.parametrize('child', [False, True])
def test_invalid_content_keeps_original_failure(api, fake_runner, monkeypatch, caplog, text, child):
    fake_runner.replies = [text, text]
    monkeypatch.setattr(main, '_user', lambda r: '下の子' if child else auth.PARENT)
    event = post(api)[-1]
    assert event == dict(type='error', detail='読み取りに失敗しました。もう一度試してください。', temporary=False)
    failures = [r for r in caplog.records if r.name == 'main']
    assert [r.getMessage() for r in failures] == ['extract failure: type=JSONDecodeError status=None']
    assert all(r.exc_info is None for r in failures)


def test_deadline_shared_by_retry_with_fake_clock(fake_runner, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(agent.time, 'monotonic', lambda: clock[0])
    fake_runner.replies = ['', json.dumps(dict(summary='', items=[]))]
    async def consume():
        stream = agent.stream_otayori(b'fake', 'image/png')
        assert (await anext(stream))['type'] == 'reading'
        clock[0] = 24
        assert (await anext(stream))['type'] == 'reset'
        clock[0] = 25.01
        with pytest.raises(TimeoutError):
            await anext(stream)
    asyncio.run(consume())
    assert len(fake_runner.calls) == 1 and fake_runner.closed == 1


def test_hanging_call_cancelled_with_fake_wait(monkeypatch):
    waits, closed = [], []
    async def stuck(*args):
        try:
            yield {'type':'reading'}
            await asyncio.Event().wait()
        finally:
            closed.append(True)
    actual_wait = asyncio.wait_for
    async def fake_wait(awaitable, timeout):
        waits.append(timeout)
        if len(waits) == 1:
            return await awaitable
        # 模した時間切れでも wait_for 本体のキャンセルと generator の close を通す。
        return await actual_wait(awaitable, timeout=0)
    monkeypatch.setattr(agent, '_stream_otayori', stuck)
    monkeypatch.setattr(agent.asyncio, 'wait_for', fake_wait)
    async def consume():
        with pytest.raises(TimeoutError):
            async for _ in agent.stream_otayori(b'fake', 'image/png'):
                pass
    asyncio.run(consume())
    assert len(waits) == 2 and all(0 < n <= 25 for n in waits)
    assert closed == [True]
