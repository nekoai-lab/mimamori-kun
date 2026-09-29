"""ポイントの台帳。

残高は「数値を持って書き換える」のではなく、**加減算の記録を合算して出す**。
こうしておくと、いつ・なぜ増えたか（減ったか）が必ず残り、あとで揉めない。

保存先は環境によって差し替わる:
    - Cloud Run（K_SERVICE がある）では Firestore 必須。接続失敗は起動エラー
    - ローカルは MIMAMORI_LEDGER=firestore を明示したときだけ Firestore。接続失敗は起動エラー
    - MIMAMORI_LEDGER=json または未指定のローカル開発では JSON ファイル
    - MIMAMORI_LEDGER の未知の値は、環境によらずエラー

**呼ぶ側は保存先を知らない。** 先に台帳の形を決めておき、
GCP が用意できた日に繋ぎ変えるだけで動くようにするための構造。

台帳に入るもの:
    delta       増減。引き換えはマイナスで入る
    reason      何で増えたか（"homework" / "test_fix" / "redeem" など）
    ref_id      予定のID や 引き換えID。あとで辿るため
    created_by  "agent" か "parent"
    revoked     親が取り消したら True。**行は消さない**
"""
from __future__ import annotations

import json
import os
import threading
import tempfile
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

JST = timezone(timedelta(hours=9))
_LOCAL_PATH = Path(os.getenv("MIMAMORI_LEDGER_PATH", ".data/ledger.json"))


def _now() -> str:
    return datetime.now(JST).isoformat(timespec="seconds")


# ------------------------------------------------------------------ 保存先

# JSON ファイル1本を丸ごと読み書きするので、同時に書くと片方が消える。1つの鍵でまとめて守る（#16）
_LOCAL_LOCK = threading.RLock()


class _LocalStore:
    """開発用。JSON ファイル1本。Cloud Run はステートレスなので本番では使わない。"""

    kind = "local"

    def __init__(self, path: Path = _LOCAL_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"entries": [], "settings": {}}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"entries": [], "settings": {}}

    def _write(self, data: Dict[str, Any]) -> None:
        # 同じファイルシステム上で置き換える。書き込み失敗で元の台帳を壊さない。
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                             dir=self.path.parent, delete=False) as f:
                temporary = Path(f.name)
                json.dump(data, f, ensure_ascii=False, indent=2)
            temporary.replace(self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def append(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        with _LOCAL_LOCK:
            data = self._read()
            data["entries"].append(entry)
            self._write(data)
        return entry

    def entries(self, child: Optional[str] = None) -> List[Dict[str, Any]]:
        with _LOCAL_LOCK:
            rows = self._read()["entries"]
        return [r for r in rows if child is None or r.get("child") == child]

    def update(self, entry_id: str, patch: Dict[str, Any]) -> bool:
        with _LOCAL_LOCK:
            data = self._read()
            for r in data["entries"]:
                if r.get("id") == entry_id:
                    r.update(patch)
                    self._write(data)
                    return True
        return False

    def get_setting(self, key: str) -> Any:
        with _LOCAL_LOCK:
            return self._read().get("settings", {}).get(key)

    def set_setting(self, key: str, value: Any) -> None:
        with _LOCAL_LOCK:
            data = self._read()
            data.setdefault("settings", {})[key] = value
            self._write(data)

    def transact_setting(self, key: str, fn: Callable[[Any], Any]) -> Any:
        with _LOCAL_LOCK:
            data = self._read()
            new = fn(data.setdefault("settings", {}).get(key))
            data["settings"][key] = new
            self._write(data)
            return new


    def transact_setting_entries(self, key, child, fn, read_keys=()):
        with _LOCAL_LOCK:
            data = self._read()
            settings = data.setdefault("settings", {})
            bal = sum(e["delta"] for e in data["entries"]
                      if e.get("child") == child and not e.get("revoked"))
            new, added, result = fn(settings.get(key), bal,
                                    {k: settings.get(k) for k in read_keys})
            settings[key] = new
            by_id = {e["id"]: e for e in data["entries"]}
            by_id.update({e["id"]: e for e in added})
            data["entries"] = list(by_id.values())
            self._write(data)
            return result


class _FirestoreStore:
    """本番用。families/{family}/points_ledger と settings。"""

    kind = "firestore"

    def __init__(self, project: str, family: str = "default"):
        from google.cloud import firestore  # 遅延 import（ローカルでは不要）

        self._db = firestore.Client(project=project)
        self._family = self._db.collection("families").document(family)

    def check_connection(self) -> None:
        # Client の生成だけでは RPC が発生しない。文書が未作成でも読み取りは成功する。
        self._family.get(retry=None, timeout=10)

    def append(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        self._family.collection("points_ledger").document(entry["id"]).set(entry)
        return entry

    def entries(self, child: Optional[str] = None) -> List[Dict[str, Any]]:
        col = self._family.collection("points_ledger")
        q = col.where("child", "==", child) if child else col
        return [d.to_dict() for d in q.stream()]

    def update(self, entry_id: str, patch: Dict[str, Any]) -> bool:
        self._family.collection("points_ledger").document(entry_id).update(patch)
        return True

    def get_setting(self, key: str) -> Any:
        snap = self._family.collection("settings").document(key).get()
        return snap.to_dict().get("value") if snap.exists else None

    def set_setting(self, key: str, value: Any) -> None:
        self._family.collection("settings").document(key).set({"value": value})

    def transact_setting(self, key: str, fn: Callable[[Any], Any]) -> Any:
        """読んで・変えて・書くを1つのトランザクションで。ぶつかったら Firestore がやり直す（fn は何度か呼ばれうる）。"""
        from google.cloud import firestore

        ref = self._family.collection("settings").document(key)

        @firestore.transactional
        def run(tx):
            snap = ref.get(transaction=tx)
            new = fn(snap.to_dict().get("value") if snap.exists else None)
            tx.set(ref, {"value": new})
            return new

        return run(self._db.transaction())


    def transact_setting_entries(self, key, child, fn, read_keys=()):
        from google.cloud import firestore

        settings = self._family.collection("settings")
        entries = self._family.collection("points_ledger")
        ref = settings.document(key)

        @firestore.transactional
        def run(tx):
            snap = ref.get(transaction=tx)
            extra = {}
            for k in read_keys:
                other = settings.document(k).get(transaction=tx)
                extra[k] = other.to_dict().get("value") if other.exists else None
            # 読み取りはすべて書き込みより前。残高確認も同じスナップショットで行う。
            rows = (entries.where("child", "==", child).stream(transaction=tx)
                    if child else [])
            bal = sum(e.get("delta", 0) for e in (r.to_dict() for r in rows)
                      if not e.get("revoked"))
            new, added, result = fn(snap.to_dict().get("value") if snap.exists else None,
                                    bal, extra)
            tx.set(ref, {"value": new})
            for entry in added:
                tx.set(entries.document(entry["id"]), entry)
            return result

        return run(self._db.transaction())


_store = None


def store():
    """保存先を1つだけ作って使い回す。"""
    global _store
    if _store is not None:
        return _store
    backend = os.getenv("MIMAMORI_LEDGER", "json")
    if backend not in {"json", "firestore"}:
        raise RuntimeError("MIMAMORI_LEDGER は firestore または json を指定してください")
    on_cloud_run = "K_SERVICE" in os.environ
    if on_cloud_run or backend == "firestore":
        project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
        if not project:
            raise RuntimeError("Firestore の台帳には GOOGLE_CLOUD_PROJECT が必要です")
        try:
            candidate = _FirestoreStore(project)
            candidate.check_connection()
            _store = candidate
            return _store
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("台帳: Firestore に接続できません") from exc
    _store = _LocalStore()
    return _store


# ------------------------------------------------------------------ 台帳の操作

def make_entry(
    child: str,
    delta: int,
    reason: str,
    ref_id: Optional[str] = None,
    created_by: str = "agent",
    title: str = "",
    redeem_id: Optional[str] = None,
) -> Dict[str, Any]:
    """保存前の台帳行を作る。トランザクション内でも外部への書き込みはしない。"""
    entry = {
        "id": uuid.uuid4().hex,
        "child": child,
        "delta": int(delta),
        "reason": reason,
        "ref_id": ref_id,
        "title": title,
        "created_by": created_by,
        "created_at": _now(),
        "revoked": False,
    }
    if redeem_id is not None:
        entry["redeem_id"] = redeem_id
    return entry


def add(child: str, delta: int, reason: str, ref_id: Optional[str] = None,
        created_by: str = "agent", title: str = "") -> Dict[str, Any]:
    """台帳に1行足す。既存の行は書き換えない。"""
    return store().append(make_entry(child, delta, reason, ref_id, created_by, title))


def revoke(entry_id: str) -> bool:
    """親が取り消す。行は消さず、印を付けるだけ。"""
    return store().update(entry_id, {"revoked": True, "revoked_at": _now()})


def balance(child: str) -> int:
    """残高 = 取り消されていない行の合算。"""
    return sum(e["delta"] for e in store().entries(child) if not e.get("revoked"))


def history(child: str, limit: int = 30) -> List[Dict[str, Any]]:
    """新しい順。取り消した行も残す（理由が分かるように）。"""
    rows = sorted(
        store().entries(child), key=lambda e: e.get("created_at", ""), reverse=True
    )
    return rows[:limit]


def has_ref(child: str, ref_id: str) -> bool:
    """同じ予定で二重に加点していないか。"""
    return any(
        e.get("ref_id") == ref_id and not e.get("revoked")
        for e in store().entries(child)
    )


# ------------------------------------------------------------------ 設定

def get_setting(key: str, default: Any = None) -> Any:
    v = store().get_setting(key)
    return default if v is None else v


def set_setting(key: str, value: Any) -> Dict[str, Any]:
    store().set_setting(key, value)
    return {"ok": True, "key": key, "stored_in": store().kind}


def transact_setting(key: str, fn: Callable[[Any], Any]) -> Any:
    """設定を1つ、ほかの書き込みとぶつからないように書き換える。fn(今の値) -> 新しい値。

    fn はやり直しで何度か呼ばれることがあるので、外の状態を変えないこと（結果は返り値で受け取る）。
    """
    return store().transact_setting(key, fn)


def transact_setting_entries(key, child, fn, read_keys=()):
    """設定・残高の確認と設定・台帳行の保存をまとめる。

    fn(設定, 残高, 追加で読む設定) -> (新設定, 保存する台帳行, 結果)。
    Firestore は競合時に fn を再実行するため、外部への副作用を起こさないこと。
    台帳行は id で upsert する（取消も設定と一体で保存できる）。
    child が空なら残高は使わない。既存の transact_setting の契約は変えない。
    """
    return store().transact_setting_entries(key, child, fn, read_keys)
