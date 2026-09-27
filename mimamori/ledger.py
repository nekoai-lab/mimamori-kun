"""ポイントの台帳。

残高は「数値を持って書き換える」のではなく、**加減算の記録を合算して出す**。
こうしておくと、いつ・なぜ増えたか（減ったか）が必ず残り、あとで揉めない。

保存先は環境によって差し替わる:
    - Cloud Run（K_SERVICE がある）では Firestore 必須。接続失敗は起動エラー
    - ローカルでは GOOGLE_CLOUD_PROJECT があれば Firestore を試し、失敗時は JSON
    - プロジェクト未指定のローカル開発では JSON ファイル

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
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

JST = timezone(timedelta(hours=9))
_LOCAL_PATH = Path(os.getenv("MIMAMORI_LEDGER_PATH", ".data/ledger.json"))


def _now() -> str:
    return datetime.now(JST).isoformat(timespec="seconds")


# ------------------------------------------------------------------ 保存先

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
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def append(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        data = self._read()
        data["entries"].append(entry)
        self._write(data)
        return entry

    def entries(self, child: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = self._read()["entries"]
        return [r for r in rows if child is None or r.get("child") == child]

    def update(self, entry_id: str, patch: Dict[str, Any]) -> bool:
        data = self._read()
        for r in data["entries"]:
            if r.get("id") == entry_id:
                r.update(patch)
                self._write(data)
                return True
        return False

    def get_setting(self, key: str) -> Any:
        return self._read().get("settings", {}).get(key)

    def set_setting(self, key: str, value: Any) -> None:
        data = self._read()
        data.setdefault("settings", {})[key] = value
        self._write(data)


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


_store = None


def store():
    """保存先を1つだけ作って使い回す。"""
    global _store
    if _store is not None:
        return _store
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
    on_cloud_run = "K_SERVICE" in os.environ
    if on_cloud_run and not project:
        raise RuntimeError("Cloud Run の台帳には GOOGLE_CLOUD_PROJECT が必要です")
    if project:
        try:
            candidate = _FirestoreStore(project)
            if on_cloud_run:
                candidate.check_connection()
            _store = candidate
            return _store
        except Exception as exc:  # noqa: BLE001
            if on_cloud_run:
                raise RuntimeError("Cloud Run の台帳: Firestore に接続できません") from exc
            # ローカル開発だけは従来どおり JSON に切り替える。
    _store = _LocalStore()
    return _store


# ------------------------------------------------------------------ 台帳の操作

def add(
    child: str,
    delta: int,
    reason: str,
    ref_id: Optional[str] = None,
    created_by: str = "agent",
    title: str = "",
) -> Dict[str, Any]:
    """台帳に1行足す。**既存の行は書き換えない。**"""
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
    return store().append(entry)


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
