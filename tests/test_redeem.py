"""#42: 再送・競合・保存失敗でも申込とポイントを一体に保つ。"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, current_thread

import pytest

from mimamori import ledger, points, redeem


@pytest.fixture(autouse=True)
def fresh(monkeypatch, tmp_path):
    monkeypatch.setattr(ledger, "_store", ledger._LocalStore(tmp_path / "ledger.json"))
    monkeypatch.setattr(points, "sync_from_calendar", lambda child: 0)
    ledger.add("子", 100, "adjust")


def test_same_key_survives_status_cap_and_balance_changes():
    key = "test-request-key-01"
    row = redeem.request("子", "ごほうび", 100, request_key=key)
    redeem.set_cap(count=1)
    approved = redeem.approve(row["id"])
    again = redeem.request("子", "変更後の名前", 200, request_key=key, allowed_rewards=[])
    assert again == approved
    assert len(redeem.requests()) == 1
    assert ledger.balance("子") == 0
    assert len(ledger.history("子")) == 2


def test_keys_are_scoped_to_child_and_not_pruned():
    key = "test-request-key-01"
    original = redeem.request("子", "ごほうび", 1, request_key=key)
    ledger.add("別の子", 300, "adjust")
    other = redeem.request("別の子", "ごほうび", 1, request_key=key)
    for _ in range(201):
        redeem.request("別の子", "ごほうび", 1)
    assert other["id"] != original["id"]
    assert redeem.request("子", "ごほうび", 1, request_key=key) == original
    assert ledger.balance("子") == 99


def race(monkeypatch, *actions):
    start = Barrier(len(actions))
    old_read = Barrier(len(actions))
    get = ledger.get_setting

    def intercepted(key, *args):
        value = get(key, *args)
        # 修正前の「状態を読んでから別々に保存」の競合を確実に起こす。
        if key == redeem.K_REQ and current_thread().name.startswith("redeem-race"):
            old_read.wait(timeout=5)
        return value

    monkeypatch.setattr(ledger, "get_setting", intercepted)

    def run(fn):
        start.wait(timeout=5)
        try:
            return fn()
        except ValueError:
            return None

    with ThreadPoolExecutor(len(actions), thread_name_prefix="redeem-race") as pool:
        return list(pool.map(run, actions))


@pytest.mark.parametrize("action", ["reject", "approve", "hand"])
def test_duplicate_decision_race(monkeypatch, action):
    row = redeem.request("子", "ごほうび", 30)
    fn = lambda: getattr(redeem, action)(row["id"], "また今度") if action != "hand" else redeem.hand(row["id"])
    results = race(monkeypatch, fn, fn)
    assert sum(r is not None for r in results) == 1
    refunds = [e for e in ledger.history("子") if e.get("redeem_id") == row["id"] and e["delta"] > 0]
    assert len(refunds) == (1 if action == "reject" else 0)
    assert ledger.balance("子") == (100 if action == "reject" else 70)


@pytest.mark.parametrize("first", ["approve", "hand"])
def test_decision_against_reject(monkeypatch, first):
    row = redeem.request("子", "ごほうび", 30)
    results = race(monkeypatch, lambda: getattr(redeem, first)(row["id"]),
                   lambda: redeem.reject(row["id"], "また今度"))
    saved = redeem.requests()[0]
    refunds = [e for e in ledger.history("子") if e["delta"] == 30]
    if first == "approve":
        # requested -> approved -> rejected は既存仕様で許される。
        assert saved["status"] == "rejected"
        assert results[1] is not None
        assert len(refunds) == 1
    else:
        assert sum(r is not None for r in results) == 1
        assert saved["status"] in ("handed", "rejected")
    assert len(refunds) == (1 if saved["status"] == "rejected" else 0)
    assert all(e.get("redeem_id") == row["id"] for e in refunds)
    assert ledger.balance("子") == (100 if refunds else 70)


@pytest.mark.parametrize("same_key", [True, False])
def test_parallel_requests_cannot_overspend(monkeypatch, same_key):
    keys = ["test-request-key-01", "test-request-key-01" if same_key else "test-request-key-02"]
    results = race(monkeypatch, *(lambda key=key: redeem.request("子", "ごほうび", 100, request_key=key) for key in keys))
    assert len(redeem.requests()) == 1
    assert ledger.balance("子") == 0
    assert sum(r is not None for r in results) == (2 if same_key else 1)
    if same_key:
        assert results[0] == results[1]


def test_parallel_requests_obey_cap(monkeypatch):
    redeem.set_cap(count=1)
    results = race(monkeypatch, *(lambda: redeem.request("子", "ごほうび", 30) for _ in range(2)))
    assert sum(r is not None for r in results) == 1
    assert len(redeem.requests()) == 1
    assert ledger.balance("子") == 70


@pytest.mark.parametrize("action", ["request", "reject"])
def test_failed_save_leaves_no_partial_charge_or_refund(monkeypatch, action):
    row = redeem.request("子", "ごほうび", 30)
    before = ledger.store().path.read_bytes()

    def fail(_data):
        raise OSError("test write failure")

    monkeypatch.setattr(ledger.store(), "_write", fail)
    with pytest.raises(OSError):
        if action == "request":
            redeem.request("子", "ごほうび", 30)
        else:
            redeem.reject(row["id"], "また今度")
    assert ledger.store().path.read_bytes() == before


@pytest.mark.parametrize("fail_commit", [False, True])
def test_firestore_retry_and_commit_keep_entries_with_request(monkeypatch, fail_commit):
    """実 RPC を使わず、読み→一括保存と再実行を検証する。"""
    from copy import deepcopy
    from types import SimpleNamespace
    from unittest.mock import Mock
    from google.cloud import firestore

    data = {("points_ledger", "seed"): ledger.make_entry("子", 100, "adjust")}

    class Ref:
        def __init__(self, path):
            self.path = path

        def get(self, transaction=None):
            if transaction:
                assert not transaction.set.called, "書き込み後の読み取りは禁止"
            value = deepcopy(data.get(self.path))
            return SimpleNamespace(exists=value is not None, to_dict=lambda: value)

        def set(self, value):
            pytest.fail("トランザクションの外で保存してはいけない")

    class Collection:
        def __init__(self, name, child=None):
            self.name, self.child = name, child

        def document(self, name):
            return Ref((self.name, name))

        def where(self, field, op, child):
            assert (field, op) == ("child", "==")
            return Collection(self.name, child)

        def stream(self, transaction=None):
            if transaction:
                assert not transaction.set.called
            return [SimpleNamespace(to_dict=lambda v=deepcopy(v): v) for (col, _), v in data.items()
                    if col == self.name and (not self.child or v["child"] == self.child)]

    attempts = []

    def transactional(fn):
        def run(_tx):
            # 最初の試行は競合で破棄。設定と台帳行をまとめて保存した2回目だけが残る。
            for _ in range(2):
                tx = Mock()
                result = fn(tx)
                attempts.append(tx)
            if fail_commit:
                raise OSError("test commit failure")
            for call in tx.set.call_args_list:
                ref, value = call.args
                data[ref.path] = deepcopy(value)
            return result
        return run

    store = ledger._FirestoreStore.__new__(ledger._FirestoreStore)
    store._family = SimpleNamespace(collection=Collection)
    store._db = Mock()
    monkeypatch.setattr(ledger, "_store", store)
    monkeypatch.setattr(firestore, "transactional", transactional)
    if fail_commit:
        with pytest.raises(OSError):
            redeem.request("子", "ごほうび", 30, request_key="test-request-key-01")
        assert redeem.requests() == []
        assert ledger.balance("子") == 100
    else:
        row = redeem.request("子", "ごほうび", 30, request_key="test-request-key-01")
        assert redeem.request("子", "ごほうび", 30, request_key="test-request-key-01") == row
        assert ledger.balance("子") == 70
        assert len(ledger.history("子")) == 2
        assert any(e["id"] == row["ledger_id"] for e in ledger.history("子"))
        redeem.reject(row["id"], "また今度")
        assert ledger.balance("子") == 100
        refunds = [e for e in ledger.history("子") if e["delta"] == 30]
        assert len(refunds) == 1 and refunds[0]["redeem_id"] == row["id"]
        assert redeem.requests()[0]["status"] == "rejected"
    assert len(attempts) >= 2


def test_local_replace_failure_preserves_ledger(monkeypatch):
    from pathlib import Path

    row = redeem.request("子", "ごほうび", 30)
    store = ledger.store()
    before = store.path.read_bytes()

    def fail(*args):
        raise OSError("test replace failure")

    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError):
        redeem.reject(row["id"], "また今度")
    assert store.path.read_bytes() == before
    assert list(store.path.parent.iterdir()) == [store.path]
