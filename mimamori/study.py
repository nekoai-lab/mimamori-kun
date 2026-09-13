"""学習スケジュール — 課題・枠・見積もり・配分。

ここは**コードだけ**で動く。モデルを呼ばない。
理由（D：LLMと決定的処理の切り分け）:
    配分は毎日呼ばれ、押した瞬間に結果が返らないと使われない。
    そして「同じ入力なら必ず同じ結果」でないと、親も子も計画を信用しない。
    モデルに任せるのは入口（範囲の読み取り）と出口（言い方）だけ。

置き場所:
    新しいDBは増やさない。台帳（ledger）の settings に置く。
    ローカルでは .data/ledger.json、GCP を繋げば Firestore に載る。

用語:
    課題（assignment）  「数学ワーク p.42-78」のような、範囲のあるまとまり
    単位（unit）        ページ／問／周。数えられるもの
    枠（capacity）      その日に勉強にあてられる分数。曜日ごとに決める
    見積もり（estimate）1単位あたりの分数。教科ごと。既定から始めて実績で寄せる
"""
from __future__ import annotations

import datetime as dt
import re
import uuid
from typing import Any, Dict, List, Optional

from . import ledger

JST = dt.timezone(dt.timedelta(hours=9))
WD = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WD_JP = "月火水木金土日"

K_ASSIGN = "assignments"
K_CAP = "capacity_week"
K_EST = "estimates"

# 既定の枠（分）。塾のある日は親が下げる前提で、まずは平日90・休日120。
DEFAULT_CAPACITY = {"mon": 90, "tue": 90, "wed": 90, "thu": 90, "fri": 90, "sat": 120, "sun": 120}

# 1単位あたりの既定の分。実測ではなく目安（D-56）。実績で寄せるのは B-7。
DEFAULT_ESTIMATE = {"page": 6, "question": 2, "round": 30, "unit": 5}

# 締切の直前に終わらせない。予備日を必ず残す（体調・行事・読み違いのため）。
BUFFER_DAYS = 2

# 1日に並べる教科の数。多すぎると切り替えばかりになり、少なすぎると1教科に偏る。
MIX_PER_DAY = 3


def today() -> dt.date:
    return dt.datetime.now(JST).date()


# ---------------------------------------------------------------- 枠

def capacity() -> Dict[str, Any]:
    """曜日ごとの枠と、日ごとの上書き。"""
    saved = ledger.get_setting(K_CAP) or {}
    week = dict(DEFAULT_CAPACITY)
    for k, v in (saved.get("week") or {}).items():
        if k in week:
            try:
                week[k] = max(0, int(v))
            except (TypeError, ValueError):
                pass
    days = {k: int(v) for k, v in (saved.get("days") or {}).items() if str(v).lstrip("-").isdigit()}
    return {"week": week, "days": days}


def set_capacity(week: Optional[Dict[str, Any]] = None, days: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cur = capacity()
    if week:
        for k, v in week.items():
            if k not in cur["week"]:
                raise ValueError(f"曜日の名前が違います: {k}")
            v = int(v)
            if not (0 <= v <= 480):
                raise ValueError("枠は0分から480分のあいだで決めてください。")
            cur["week"][k] = v
    if days:
        for k, v in days.items():
            dt.date.fromisoformat(k)          # 形が違えばここで落とす
            v = int(v)
            if not (0 <= v <= 480):
                raise ValueError("枠は0分から480分のあいだで決めてください。")
            cur["days"][k] = v
    ledger.set_setting(K_CAP, cur)
    return cur


def minutes_on(date: dt.date, cap: Optional[Dict[str, Any]] = None) -> int:
    """その日に使える分。**当日の上書きが曜日より強い。**"""
    cap = cap or capacity()
    iso = date.isoformat()
    if iso in cap["days"]:
        return max(0, int(cap["days"][iso]))
    return max(0, int(cap["week"][WD[date.weekday()]]))


# ---------------------------------------------------------------- 見積もり

def estimates() -> Dict[str, int]:
    saved = ledger.get_setting(K_EST) or {}
    out = dict(DEFAULT_ESTIMATE)
    for k, v in saved.items():
        try:
            out[k] = max(1, int(v))
        except (TypeError, ValueError):
            pass
    return out


def set_estimates(values: Dict[str, Any]) -> Dict[str, int]:
    cur = {k: int(v) for k, v in values.items() if str(v).isdigit() and int(v) > 0}
    ledger.set_setting(K_EST, cur)
    return estimates()


def minutes_per_unit(unit: str, est: Optional[Dict[str, int]] = None) -> int:
    est = est or estimates()
    return est.get(unit) or est.get("unit") or 5


# ---------------------------------------------------------------- 課題

def assignments(child: Optional[str] = None, include_done: bool = False) -> List[Dict[str, Any]]:
    rows = ledger.get_setting(K_ASSIGN) or []
    out = [r for r in rows if isinstance(r, dict)]
    if child:
        out = [r for r in out if r.get("child") == child]
    if not include_done:
        out = [r for r in out if int(r.get("done") or 0) < int(r.get("total") or 0)]
    return sorted(out, key=lambda r: (r.get("due") or "9999-12-31", -int(r.get("priority") or 0)))


def add_assignment(child: str, subject: str, title: str, total: int, unit: str,
                   due: str, priority: int = 0) -> Dict[str, Any]:
    """課題を1つ足す。**範囲は数に直してから入れる**（読み取りは parse_range）。"""
    if not child or not subject or not title:
        raise ValueError("だれの・なんの教科・なにか、の3つが要ります。")
    total = int(total)
    if total <= 0:
        raise ValueError("量が0では配れません。")
    dt.date.fromisoformat(due)
    row = {
        "id": uuid.uuid4().hex[:8],
        "child": child,
        "subject": subject,
        "title": title,
        "total": total,
        "done": 0,
        "unit": unit if unit in DEFAULT_ESTIMATE else "unit",
        "due": due,
        "priority": int(priority),
        "created": today().isoformat(),
    }
    rows = ledger.get_setting(K_ASSIGN) or []
    rows.append(row)
    ledger.set_setting(K_ASSIGN, rows)
    return row


def update_assignment(assignment_id: str, done: Optional[int] = None,
                      priority: Optional[int] = None, due: Optional[str] = None) -> Dict[str, Any]:
    rows = ledger.get_setting(K_ASSIGN) or []
    for r in rows:
        if r.get("id") != assignment_id:
            continue
        if done is not None:
            r["done"] = max(0, min(int(done), int(r["total"])))
        if priority is not None:
            r["priority"] = int(priority)
        if due is not None:
            dt.date.fromisoformat(due)
            r["due"] = due
        ledger.set_setting(K_ASSIGN, rows)
        return r
    raise ValueError("その課題が見つかりませんでした。")


def remove_assignment(assignment_id: str) -> bool:
    rows = ledger.get_setting(K_ASSIGN) or []
    rest = [r for r in rows if r.get("id") != assignment_id]
    if len(rest) == len(rows):
        return False
    ledger.set_setting(K_ASSIGN, rest)
    return True


# ---------------------------------------------------------------- 範囲の読み取り（B-3）

_NUM = r"(\d{1,4})"
_SEP = r"(?:\s*(?:から|まで|[-~〜ー–—－]|to)\s*)"          # 「から」は2文字。文字クラスでは拾えない
_P = r"(?:p\.?|ｐ|ページ|頁)"

# 数え方ごとの読み取り。**上から順に当てる。**
_PATTERNS = [
    # p.42-78 / P30〜55 / p.42から78ページ
    (re.compile(_P + r"\s*" + _NUM + _SEP + _P + r"?\s*" + _NUM, re.I), "page", "range"),
    # 42-78ページ / 42ページから78ページ
    (re.compile(_NUM + r"\s*" + _P + r"?" + _SEP + _NUM + r"\s*" + _P, re.I), "page", "range"),
    # 問1-50 / 1〜50問
    (re.compile(r"問\s*" + _NUM + _SEP + _NUM), "question", "range"),
    (re.compile(_NUM + _SEP + _NUM + r"\s*問"), "question", "range"),
    (re.compile(_NUM + r"\s*問"), "question", "count"),
    # 12ページ / p.12
    (re.compile(_NUM + r"\s*(?:ページ|頁)"), "page", "count"),
    (re.compile(_P + r"\s*" + _NUM, re.I), "page", "count"),
]

# 周回は別に数える。「ワークを3周 p.10-19」は 10ページ×3周＝30ページ。
_ROUND = re.compile(_NUM + r"\s*(?:周|回まわ|回やる|回とく)")


def parse_range(text: str) -> Optional[Dict[str, Any]]:
    """「ワーク p.42-78」→ {"unit":"page","total":37}。**まず計算で解く。**

    読めたら dict、読めなければ None（そのときだけモデルに回す）。
    範囲は**両端を含む**。42〜78 は 37ページ（78-42+1）。
    ここを 36 にすると、最後の1ページが毎回どこにも配られない。
    """
    if not text:
        return None
    s = text.replace("，", ",").replace("　", " ")

    rounds = 0
    mr = _ROUND.search(s)
    if mr:
        rounds = int(mr.group(1))
        s_wo = s[: mr.start()] + " " + s[mr.end():]     # 周回の数字を量と取り違えない
    else:
        s_wo = s

    base = None
    for pat, unit, kind in _PATTERNS:
        m = pat.search(s_wo)
        if not m:
            continue
        if kind == "range":
            a, b = int(m.group(1)), int(m.group(2))
            if b < a:
                a, b = b, a
            base = {"unit": unit, "total": b - a + 1, "from": a, "to": b}
        else:
            base = {"unit": unit, "total": int(m.group(1))}
        break

    if base is None:
        if rounds:
            return {"unit": "round", "total": rounds, "how": "計算"}   # 「3周」だけ
        return None

    if rounds:
        base = {"unit": base["unit"], "total": base["total"] * rounds, "rounds": rounds,
                "per_round": base["total"]}
    base["how"] = "計算"
    if base["total"] <= 0 or base["total"] > 5000:
        return None
    return base


# ---------------------------------------------------------------- 配分（B-4）

def _deadline(row: Dict[str, Any], buffer_days: int) -> dt.date:
    """実際に終わらせたい日。**締切そのものではなく、予備日を引いた日。**"""
    due = dt.date.fromisoformat(row["due"])
    return due - dt.timedelta(days=buffer_days)


def plan(child: str, start: Optional[dt.date] = None, horizon: int = 45,
         buffer_days: int = BUFFER_DAYS) -> Dict[str, Any]:
    """今日から先の配分を出す。**同じ入力なら必ず同じ結果**（乱数もモデルも使わない）。

    決まりごと:
      1. 予備日を先に取る。締切の2〜3日前までに終わらせる
      2. 前倒し。今日から詰める。後ろに寄せない
      3. 枠は超えない。超えるくらいなら**入らないと言う**
      4. 1単位も入らない日には、無理に割らない（10分でページ半分、は意味がない）
    """
    start = start or today()
    cap, est = capacity(), estimates()
    rows = assignments(child)
    if not rows:
        return {"child": child, "from": start.isoformat(), "days": [], "shortfall": [],
                "warnings": [], "total_minutes": 0}

    # 残りの単位数と、1単位あたりの分
    left = {}
    for r in rows:
        rest = max(0, int(r["total"]) - int(r.get("done") or 0))
        if rest:
            left[r["id"]] = {"row": r, "units": rest, "mpu": minutes_per_unit(r["unit"], est)}

    days: List[Dict[str, Any]] = []
    used_buffer: List[str] = []
    for i in range(horizon):
        d = start + dt.timedelta(days=i)
        room = minutes_on(d, cap)
        day = {"date": d.isoformat(), "weekday": WD_JP[d.weekday()],
               "capacity": room, "used": 0, "items": []}
        # 締切が近い順、同じなら優先度の高い順に詰める
        order = sorted(
            left.values(),
            key=lambda x: (x["row"]["due"], -int(x["row"].get("priority") or 0), x["row"]["title"]),
        )
        # その日に触れる課題（締切前で、まだ残っているもの）
        live = [j for j in order if j["units"] > 0 and d <= dt.date.fromisoformat(j["row"]["due"])]
        if not live:
            if all(j["units"] <= 0 for j in left.values()):
                break
            continue

        # **1日1教科にしない。** 同じ締切のものを1教科ずつ潰すと、
        # 初日が漢字120分になって続かないし、子の画面も1件しか並ばない（A-8 は3〜5件）。
        # まず上位 MIX_PER_DAY 件に枠を分け、余った分だけ締切の近い順に足す。
        share = room // min(len(live), MIX_PER_DAY) if room else 0

        def give(job, cap_minutes):
            r = job["row"]
            room_left = min(cap_minutes, room - day["used"])
            n = min(job["units"], room_left // job["mpu"])
            if n <= 0:
                return
            limit = _deadline(r, buffer_days)
            if d > limit and r["id"] not in used_buffer:
                used_buffer.append(r["id"])   # 予備日に食い込んだ。あとで伝える
            hit = next((it for it in day["items"] if it["assignment_id"] == r["id"]), None)
            if hit:
                hit["units"] += int(n)
                hit["minutes"] += int(n * job["mpu"])
            else:
                day["items"].append({
                    "assignment_id": r["id"], "title": r["title"], "subject": r["subject"],
                    "unit": r["unit"], "units": int(n), "minutes": int(n * job["mpu"]),
                    "due": r["due"],
                })
            day["used"] += int(n * job["mpu"])
            job["units"] -= int(n)

        for job in live[:MIX_PER_DAY]:
            give(job, share)
        for job in live:                       # 余った枠は、締切の近い順に埋める
            give(job, room)
        if day["items"]:
            days.append(day)
        if all(j["units"] <= 0 for j in left.values()):
            break

    shortfall = []
    for job in left.values():
        if job["units"] > 0:
            r = job["row"]
            shortfall.append({
                "assignment_id": r["id"], "title": r["title"], "subject": r["subject"],
                "due": r["due"], "units_left": int(job["units"]), "unit": r["unit"],
                "minutes_left": int(job["units"] * job["mpu"]),
            })

    warnings = []
    if shortfall:
        m = sum(s["minutes_left"] for s in shortfall)
        warnings.append(
            "このままだと締切までに **" + str(m) + "分ぶん**（"
            + "、".join(f"{s['title']} {s['units_left']}{_unit_jp(s['unit'])}" for s in shortfall[:3])
            + "）が残ります。枠を増やすか、締切の近いものから優先度を上げてください。"
        )
    if used_buffer:
        names = [left[i]["row"]["title"] for i in used_buffer if i in left]
        warnings.append("予備日まで使う見込みです: " + "、".join(names[:3]))

    return {
        "child": child,
        "from": start.isoformat(),
        "buffer_days": buffer_days,
        "days": days,
        "shortfall": shortfall,
        "warnings": warnings,
        "total_minutes": sum(d["used"] for d in days),
    }


def _unit_jp(unit: str) -> str:
    return {"page": "ページ", "question": "問", "round": "周"}.get(unit, "")


def today_plan(child: str) -> Dict[str, Any]:
    """今日のぶんだけ。/kid と枠バーはこれを見る。"""
    p = plan(child)
    first = p["days"][0] if p["days"] and p["days"][0]["date"] == today().isoformat() else None
    return {
        "child": child,
        "date": today().isoformat(),
        "items": (first or {}).get("items", []),
        "minutes": (first or {}).get("used", 0),
        "capacity": minutes_on(today()),
        "warnings": p["warnings"],
    }
