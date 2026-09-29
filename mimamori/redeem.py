"""引き換え（ごほうび）— 申請 → 親が承認 → 手渡し。

決まっていること:
    - **カード番号も決済も、アプリは一切扱わない**（コンビニで買って手渡す）
    - 3つの状態が履歴に残る: もうしこみ / OK / わたした
    - ポイントは**申請した時点で引く**。断られたら戻す。
      承認時に引くと、同じポイントで2つ申し込めてしまう
    - ズルの歯止めはここ（D-44）。日々の加点では止めない

月の上限:
    使いすぎを止めるためではなく、**親が家の予算を決められるようにする**ため。
    0 は「上限なし」。円で持つ（ポイントではなく、実際に出ていくお金で考えるため）。
"""
from __future__ import annotations

import datetime as dt
import uuid
import re
from typing import Any, Dict, List, Optional

from . import ledger, points

K_REQ = "redemptions"
K_CAP = "redeem_cap"
JST = dt.timezone(dt.timedelta(hours=9))

REQUESTED, APPROVED, HANDED, REJECTED = "requested", "approved", "handed", "rejected"
LABEL = {REQUESTED: "もうしこみ", APPROVED: "OK", HANDED: "わたした", REJECTED: "なし"}


def _now() -> str:
    return dt.datetime.now(JST).isoformat(timespec="seconds")


def _month(iso: str = "") -> str:
    return (iso or _now())[:7]


def cap() -> Dict[str, int]:
    """月の上限。0 は上限なし。"""
    saved = ledger.get_setting(K_CAP) or {}
    out = {"yen": 0, "count": 0}
    for k in out:
        try:
            out[k] = max(0, int(saved.get(k, 0)))
        except (TypeError, ValueError):
            pass
    return out


def set_cap(yen: Optional[int] = None, count: Optional[int] = None) -> Dict[str, int]:
    cur = cap()
    if yen is not None:
        cur["yen"] = max(0, int(yen))
    if count is not None:
        cur["count"] = max(0, int(count))
    ledger.set_setting(K_CAP, cur)
    return cur


def requests(child: str = "", month: str = "", status: str = "") -> List[Dict[str, Any]]:
    rows = [r for r in (ledger.get_setting(K_REQ) or []) if isinstance(r, dict)]
    if child:
        rows = [r for r in rows if r.get("child") == child]
    if month:
        rows = [r for r in rows if _month(r.get("at", "")) == month]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    return sorted(rows, key=lambda r: r.get("at", ""), reverse=True)


def used_this_month(child: str = "") -> Dict[str, int]:
    """今月すでに使ったぶん。**断られたものは数えない。**"""
    rows = [r for r in requests(child=child, month=_month())
            if r.get("status") in (REQUESTED, APPROVED, HANDED)]
    return {"yen": sum(int(r.get("yen") or 0) for r in rows), "count": len(rows)}


def remaining(child: str = "") -> Dict[str, Any]:
    c, used = cap(), used_this_month(child)
    return {
        "cap": c,
        "used": used,
        "yen_left": (c["yen"] - used["yen"]) if c["yen"] else None,
        "count_left": (c["count"] - used["count"]) if c["count"] else None,
    }


def request(child: str, label: str, cost: int, yen: int = 0,
            request_key: Optional[str] = None, allowed_rewards=None) -> Dict[str, Any]:
    """同じ子・キーは最初の申込を返す。キーなしは毎回新しい申込。"""
    if request_key is not None and (not isinstance(request_key, str) or
            not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", request_key)):
        raise ValueError("申込のキーが正しくありません。")
    points.sync_from_calendar(child)

    def change(saved, bal, settings):
        rows = saved or []
        if request_key is not None:
            for row in rows:
                if row.get("child") == child and row.get("request_key") == request_key:
                    return rows, [], row
        if not child or not label:
            raise ValueError("だれが・なにと交換するかが要ります。")
        if int(cost) <= 0:
            raise ValueError("交換に必要なポイントが正しくありません。")
        if allowed_rewards is not None and not any(
            r.get("label") == label and
            int(r.get("points") or r.get("cost") or 0) == int(cost) and
            int(r.get("yen") or 0) == int(yen or 0) for r in allowed_rewards
        ):
            raise ValueError("交換できるものの中から選んでください。")
        c = {"yen": 0, "count": 0}
        for k in c:
            try:
                c[k] = max(0, int((settings[K_CAP] or {}).get(k, 0)))
            except (TypeError, ValueError):
                pass
        used = [r for r in rows if r.get("child") == child and
                _month(r.get("at", "")) == _month() and
                r.get("status") in (REQUESTED, APPROVED, HANDED)]
        if c["count"] and len(used) + 1 > c["count"]:
            raise ValueError(f"今月の交換は{c['count']}回までです。来月になったらまた申し込めます。")
        if c["yen"] and int(yen) and sum(int(r.get("yen") or 0) for r in used) + int(yen) > c["yen"]:
            raise ValueError(f"今月の上限（{c['yen']}円）をこえます。おうちの人と相談してください。")
        if bal < int(cost):
            raise ValueError("ポイントが足りません")
        request_id = uuid.uuid4().hex
        entry = ledger.make_entry(child, -int(cost), "redeem", created_by="parent",
                                  title=label, redeem_id=request_id)
        row = {
            "id": request_id, "child": child, "label": label, "cost": int(cost),
            "yen": int(yen or 0), "status": REQUESTED, "at": _now(),
            "ledger_id": entry["id"], "decided_at": "", "handed_at": "", "note": "",
        }
        if request_key is not None:
            row["request_key"] = request_key
        # キーを忘れると古い再送で再び引かれるので、200件で切り捨てない。
        return rows + [row], [entry], row

    return ledger.transact_setting_entries(K_REQ, child, change, (K_CAP,))


def _find(rows: List[Dict[str, Any]], request_id: str) -> Dict[str, Any]:
    for r in rows:
        if r.get("id") == request_id:
            return r
    raise ValueError("その申し込みが見つかりませんでした。")


def _decide(request_id: str, status: str, note: str = "") -> Dict[str, Any]:
    def change(saved, _bal, _settings):
        rows = saved or []
        r = _find(rows, request_id)
        allowed = (REQUESTED,) if status == APPROVED else (REQUESTED, APPROVED)
        if r["status"] not in allowed:
            raise ValueError(f"いまの状態は「{LABEL.get(r['status'], r['status'])}」です。")
        if status == REJECTED and not note.strip():
            raise ValueError("断るときは、理由を書いてください（子どもに伝わります）。")
        r["status"] = status
        added = []
        if status == HANDED:
            r["handed_at"] = _now()
            if not r.get("decided_at"):
                r["decided_at"] = r["handed_at"]
        else:
            r["decided_at"] = _now()
            r["note"] = note.strip() if status == REJECTED else note
        if status == REJECTED:
            added.append(ledger.make_entry(
                r["child"], r["cost"], "adjust", created_by="parent",
                title=f"「{r['label']}」の交換を取りやめ：{note.strip()}", redeem_id=r["id"]))
        return rows, added, r

    return ledger.transact_setting_entries(K_REQ, "", change)


def approve(request_id: str, note: str = "") -> Dict[str, Any]:
    return _decide(request_id, APPROVED, note)


def reject(request_id: str, note: str = "") -> Dict[str, Any]:
    """状態を変えるのと同時に、一度だけポイントを戻す。"""
    return _decide(request_id, REJECTED, note)


def hand(request_id: str) -> Dict[str, Any]:
    return _decide(request_id, HANDED)


# ---------------------------------------------------------------- あと何日

def pace(child: str, days: int = 14) -> float:
    """直近の1日あたり獲得ポイント。**引き換えのマイナスは数えない。**"""
    since = (dt.datetime.now(JST).date() - dt.timedelta(days=days)).isoformat()
    got = 0
    for e in ledger.history(child, limit=300):
        if e.get("revoked"):
            continue
        if (e.get("created_at") or "")[:10] < since:
            continue
        d = int(e.get("delta") or 0)
        if d > 0:
            got += d
    return got / days if days else 0.0


def days_to(child: str, cost: int) -> Optional[int]:
    """「今のペースだと約◯日」。ペースが分からなければ None（言わない）。"""
    left = int(cost) - points.balance(child)
    if left <= 0:
        return 0
    p = pace(child)
    if p <= 0:
        return None
    return max(1, round(left / p))
