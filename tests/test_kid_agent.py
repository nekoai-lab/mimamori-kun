"""#8：/kid の相棒は、話している子のやることだけを読めて、その子のものだけを変えられる。"""
import inspect

import pytest

from mimamori import calendar_tools, kid_agent

OLDER, YOUNGER = "上の子", "下の子"


@pytest.fixture(autouse=True)
def fresh_demo():
    """テストごとにデモの台帳を作り直す（状態を持ち越さない）。"""
    calendar_tools._demo_store = None
    calendar_tools._demo_day = None
    yield


def tools_for(child):
    return {f.__name__: f for f in kid_agent.build_tools(child)}


def status_of(event_id):
    items = calendar_tools.list_tasks(days=14)["items"]
    return next(i["status"] for i in items if i["id"] == event_id)


def a_task_of(child):
    items = calendar_tools.list_tasks(days=14)["items"]
    return next(i["id"] for i in items if i["child"] == child and i["status"] == "todo")


def test_model_cannot_choose_the_child():
    for f in kid_agent.build_tools(YOUNGER):
        assert "child" not in inspect.signature(f).parameters


def test_get_my_tasks_returns_only_that_childs_tasks():
    tasks = tools_for(YOUNGER)["get_my_tasks"]()
    assert tasks
    ids = {t["id"] for t in tasks}
    items = calendar_tools.list_tasks(days=14)["items"]
    assert all(i["child"] == YOUNGER for i in items if i["id"] in ids)


@pytest.mark.parametrize("tool", ["finish_task", "start_task"])
def test_other_childs_task_is_refused(tool):
    other = a_task_of(OLDER)
    result = tools_for(YOUNGER)[tool](other)
    assert result["status"] == "error"
    assert status_of(other) == "todo"      # 変わっていない


@pytest.mark.parametrize("tool,expected", [("finish_task", "done"), ("start_task", "doing")])
def test_own_task_is_updated(tool, expected):
    mine = a_task_of(YOUNGER)
    result = tools_for(YOUNGER)[tool](mine)
    assert result["status"] == expected
    assert status_of(mine) == expected


def test_unknown_id_is_refused():
    assert tools_for(YOUNGER)["finish_task"]("no-such-id")["status"] == "error"


def test_agent_uses_the_child_scoped_tools():
    agent = kid_agent.build_agent(YOUNGER)
    names = sorted(getattr(t, "__name__", getattr(t, "name", "")) for t in agent.tools)
    assert names == ["finish_task", "get_my_tasks", "start_task"]
    for t in agent.tools:
        assert "child" not in inspect.signature(t).parameters
