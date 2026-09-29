"""#61: Gemini に接続せず、読み取りの thinking 設定を確かめる。"""
import logging

import pytest

from mimamori import agent
from mimamori.config import Config


@pytest.mark.parametrize("child", [None, "下の子"])
@pytest.mark.parametrize("raw,expected", [(None, 512), ("0", 0), ("1024", 1024)])
def test_reader_thinking_budget(monkeypatch, caplog, child, raw, expected):
    if raw is None:
        monkeypatch.delenv("MIMAMORI_THINKING_BUDGET", raising=False)
    else:
        monkeypatch.setenv("MIMAMORI_THINKING_BUDGET", raw)
    monkeypatch.setattr(agent, "config", Config())

    reader = agent._generation_config(child)
    assert reader.thinking_config.thinking_budget == expected
    assert not [r for r in caplog.records if r.name == "mimamori.config"]


@pytest.mark.parametrize("child", [None, "下の子"])
@pytest.mark.parametrize("raw", ["", "invalid-private-value", "-1", "1.5"])
def test_invalid_thinking_budget_uses_default(monkeypatch, caplog, child, raw):
    monkeypatch.setenv("MIMAMORI_THINKING_BUDGET", raw)
    with caplog.at_level(logging.WARNING, logger="mimamori.config"):
        monkeypatch.setattr(agent, "config", Config())

    reader = agent._generation_config(child)
    assert reader.thinking_config.thinking_budget == 512
    logs = [r for r in caplog.records if r.name == "mimamori.config"]
    assert len(logs) == 1
    assert logs[0].levelno == logging.WARNING
    assert "MIMAMORI_THINKING_BUDGET" in logs[0].getMessage()
    if raw:
        assert raw not in logs[0].getMessage()
