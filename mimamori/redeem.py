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


def _save(rows: List[Dict[str, Any]]) -> None:
    ledger.set_setting(K_REQ, rows[-200:])


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


def request(child: str, label: str, cost: int, yen: int = 0) -> Dict[str, Any]:
    """子が申し込む。**ここでポイントを引く**（断られたら戻す）。"""
    if not child or not label:
        raise ValueError("だれが・なにと交換するかが要ります。")
    cost = int(cost)
    if cost <= 0:
        raise ValueError("交換に必要なポイントが正しくありません。")

    c, used = cap(), used_this_month(child)
    if c["count"] and used["count"] + 1 > c["count"]:
        raise ValueError(f"今月の交換は{c['count']}回までです。来月になったらまた申し込めます。")
    if c["yen"] and int(yen) and used["yen"] + int(yen) > c["yen"]:
        raise ValueError(f"今月の上限（{c['yen']}円）をこえます。おうちの人と相談してください。")

    entry = points.redeem(child, cost, label)          # 残高が足りなければここで落ちる
    row = {
        "id": uuid.uuid4().hex[:8],
        "child": child,
        "label": label,
        "cost": cost,
        "yen": int(yen or 0),
        "status": REQUESTED,
        "at": _now(),
        "ledger_id": entry.get("id", ""),
        "decided_at": "",
        "handed_at": "",
        "note": "",
    }
    rows = (ledger.get_setting(K_REQ) or []) + [row]
    _save(rows)
    return row


def _find(rows: List[Dict[str, Any]], request_id: str) -> Dict[str, Any]:
    for r in rows:
        if r.get("id") == request_id:
            return r
    raise ValueError("その申し込みが見つかりませんでした。")


def approve(request_id: str, note: str = "") -> Dict[str, Any]:
    rows = ledger.get_setting(K_REQ) or []
    r = _find(rows, request_id)
    if r["status"] != REQUESTED:
        raise ValueError(f"いまの状態は「{LABEL.get(r['status'], r['status'])}」です。")
    r["status"] = APPROVED
    r["decided_at"] = _now()
    r["note"] = note
    _save(rows)
    return r


def reject(request_id: str, note: str = "") -> Dict[str, Any]:
    """断る。**引いたポイントは戻す。**理由は必ず残す。"""
    rows = ledger.get_setting(K_REQ) or []
    r = _find(rows, request_id)
    if r["status"] not in (REQUESTED, APPROVED):
        raise ValueError(f"いまの状態は「{LABEL.get(r['status'], r['status'])}」です。")
    if not note.strip():
        raise ValueError("断るときは、理由を書いてください（子どもに伝わります）。")
    r["status"] = REJECTED
    r["decided_at"] = _now()
    r["note"] = note.strip()
    _save(rows)
    points.adjust(r["child"], r["cost"], f"「{r['label']}」の交換を取りやめ：{note.strip()}")
    return r


def hand(request_id: str) -> Dict[str, Any]:
    """手渡した。ここで初めて「終わり」。買って渡すのは人がやる。"""
    rows = ledger.get_setting(K_REQ) or []
    r = _find(rows, request_id)
    if r["status"] not in (APPROVED, REQUESTED):
        raise ValueError(f"いまの状態は「{LABEL.get(r['status'], r['status'])}」です。")
    r["status"] = HANDED
    r["handed_at"] = _now()
    if not r.get("decided_at"):
        r["decided_at"] = r["handed_at"]
    _save(rows)
    return r


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
