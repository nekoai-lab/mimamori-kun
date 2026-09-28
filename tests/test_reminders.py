"""#31: 終日・時刻つきの通知設定。外部サービスには接続しない。"""
import os
from pathlib import Path
import subprocess

import pytest

from mimamori import calendar_tools
from mimamori.config import Config


@pytest.fixture(autouse=True)
def clear_reminders(monkeypatch):
    for name in ("MIMAMORI_REMINDERS", "MIMAMORI_REMINDERS_TIMED", "MIMAMORI_REMINDERS_ALLDAY"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize(
    "values, timed, allday",
    [
        ({}, [1200, 60], [360]),
        ({"MIMAMORI_REMINDERS": "90,30"}, [90, 30], [360]),
        ({"MIMAMORI_REMINDERS": "bad"}, [1200, 60], [360]),
        ({"MIMAMORI_REMINDERS": " 90, bad,30 "}, [90, 30], [360]),
        ({"MIMAMORI_REMINDERS_TIMED": "1080,60", "MIMAMORI_REMINDERS": "90"}, [1080, 60], [360]),
        ({"MIMAMORI_REMINDERS_ALLDAY": "720,360"}, [1200, 60], [720, 360]),
    ],
)
def test_config_defaults_and_precedence(monkeypatch, values, timed, allday):
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    config = Config()
    assert config.reminders_timed == timed
    assert config.reminders_allday == allday


@pytest.mark.parametrize("kind, default", [("TIMED", [1200, 60]), ("ALLDAY", [360])])
@pytest.mark.parametrize("raw, expected", [(" 90, bad, , -1, 1.5, 0,30 ", [90, 0, 30]), ("bad,-1", None), ("", None)])
def test_config_filters_invalid_values(monkeypatch, kind, default, raw, expected):
    monkeypatch.setenv("MIMAMORI_REMINDERS", "15")
    monkeypatch.setenv(f"MIMAMORI_REMINDERS_{kind}", raw)
    assert getattr(Config(), f"reminders_{kind.lower()}") == (default if expected is None else expected)


@pytest.mark.parametrize("time_fields", [{}, {"time_start": None}, {"time_start": ""}, {"time_start": "08:15"}, {"time_start": "00:00"}])
def test_body_uses_reminders_for_event_type(monkeypatch, time_fields):
    monkeypatch.setenv("MIMAMORI_REMINDERS_ALLDAY", "360")
    monkeypatch.setenv("MIMAMORI_REMINDERS_TIMED", "1080,60")
    monkeypatch.setattr(calendar_tools, "config", Config())
    body = calendar_tools._body({"title": "テスト予定", "date": "2026-10-01", **time_fields})
    minutes = [1080, 60] if time_fields.get("time_start") else [360]
    assert body["reminders"] == {
        "useDefault": False,
        "overrides": [{"method": "popup", "minutes": value} for value in minutes],
    }


@pytest.mark.parametrize(
    "values, timed, allday",
    [
        ({}, "1200,60", "360"),
        ({"MIMAMORI_REMINDERS": "90,30"}, "90,30", "360"),
        ({"MIMAMORI_REMINDERS_TIMED": "1080,60", "MIMAMORI_REMINDERS_ALLDAY": "720,360", "MIMAMORI_REMINDERS": "90"}, "1080,60", "720,360"),
    ],
)
def test_deploy_env_argument(monkeypatch, values, timed, allday):
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    script = (Path(__file__).resolve().parents[1] / "deploy.sh").read_text()
    argument = next(line.strip().removeprefix("--set-env-vars ") for line in script.splitlines() if line.strip().startswith("--set-env-vars "))
    # 引数の展開だけを検証する。deploy.sh・gcloud・実際の .env は実行・読込しない。
    env = {**os.environ, "PROJECT": "test", "REGION": "test", "MIMAMORI_MODEL": "test",
           "MIMAMORI_CALENDAR_ID": "test", "MIMAMORI_CHILDREN": "子A:elementary,子B:junior_high"}
    result = subprocess.run(["bash", "-uc", 'printf "%s" ' + argument], env=env, check=True, capture_output=True, text=True)
    prefix, delimiter, payload = result.stdout.split("^", 2)
    assert prefix == ""
    fields = dict(part.split("=", 1) for part in payload.split(delimiter))
    assert fields["MIMAMORI_REMINDERS_ALLDAY"] == allday
    assert fields["MIMAMORI_REMINDERS_TIMED"] == timed
    assert fields["MIMAMORI_CHILDREN"] == env["MIMAMORI_CHILDREN"]
    assert "MIMAMORI_REMINDERS" not in fields
