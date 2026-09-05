"""Google Calendar への読み書き。カレンダーそのものを台帳として使う。

新しいDBは作らない。予定の extendedProperties.private に
「誰の・種別・状態・ポイント」を持たせ、ダッシュボードはそれを読むだけ。
カレンダー側で人が手で直しても整合が壊れない。

認証は Application Default Credentials。
Cloud Run では実行サービスアカウントがそのまま使われるので鍵ファイルは不要。
対象カレンダーの「特定のユーザーとの共有」に、そのサービスアカウントの
メールアドレスを『予定の変更権限』で追加しておくこと。
"""
from __future__ import annotations

import datetime as dt
import os
import uuid
from typing import Any, Dict, List, Optional

from .config import config

SCOPES = ["https://www.googleapis.com/auth/calendar"]
MARK = "mimamorikun"           # このアプリが作った予定の目印
_service = None

DEMO = os.getenv("MIMAMORI_DEMO", "").lower() in ("1", "true", "yes")

# デモモードのときだけ使う、プロセス内の仮の台帳。
# 「終わった」が会話のあいだ残らないと伴走にならないので、状態を持たせる。
_demo_store: List[Dict[str, Any]] = []
_demo_day: str = ""


def _svc():
    global _service
    if _service is None:
        import google.auth
        from googleapiclient.discovery import build

        creds, _ = google.auth.default(scopes=SCOPES)
        _service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    return _service


def service_account_email() -> str:
    """共有設定に貼るためのアドレス。UI に出して案内する。"""
    if DEMO:
        return "(デモモード)"
    try:
        import google.auth

        creds, _ = google.auth.default(scopes=SCOPES)
        return getattr(creds, "service_account_email", "") or "(ADC: ユーザー資格情報)"
    except Exception as e:  # noqa: BLE001
        return f"(取得できず: {e})"


# ---------------------------------------------------------------- 読み

def list_events(start_date: str, end_date: str) -> List[Dict[str, Any]]:
    """指定期間の既存予定を返す。重複登録を避けるために、書く前に必ず読む。

    Args:
        start_date: 期間の開始日 YYYY-MM-DD
        end_date: 期間の終了日 YYYY-MM-DD（この日を含む）

    Returns:
        件名・日付だけに絞った予定のリスト。
        id は返さない。重複を伝えるときは件名で言うこと（id では人が読めない）。
    """
    if DEMO:
        today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
        return [
            {"summary": e["summary"], "date": e["date"]}
            for e in _demo_state(today)
            if start_date <= e["date"] <= end_date
        ]
    return [{"summary": e["summary"], "date": e["date"]} for e in _raw(start_date, end_date)]


def _raw(start_date: str, end_date: str) -> List[Dict[str, Any]]:
    tmin = f"{start_date}T00:00:00+09:00"
    tmax = (dt.date.fromisoformat(end_date) + dt.timedelta(days=1)).isoformat() + "T00:00:00+09:00"
    res = (
        _svc()
        .events()
        .list(
            calendarId=config.calendar_id,
            timeMin=tmin,
            timeMax=tmax,
            singleEvents=True,
            orderBy="startTime",
            maxResults=250,
        )
        .execute()
    )
    out = []
    for ev in res.get("items", []):
        st = ev.get("start", {})
        priv = (ev.get("extendedProperties") or {}).get("private") or {}
        out.append(
            {
                "id": ev.get("id", ""),
                "summary": ev.get("summary", ""),
                "date": st.get("date") or st.get("dateTime", "")[:10],
                "time": (st.get("dateTime", "")[11:16] or None),
                "description": ev.get("description", ""),
                "link": ev.get("htmlLink", ""),
                "mine": priv.get("app") == MARK,
                "child": priv.get("child", ""),
                "kind": priv.get("kind", ""),
                "status": priv.get("status", "todo"),
                "points": int(priv.get("points", 0) or 0),
                "bring": priv.get("bring", ""),
            }
        )
    return out


# 同じ日のものをどの順で見せるか。取り返しがつかないものを上に置く。
# 提出物はその日を過ぎたら終わり。持ち物はその日の朝まで。
# 宿題は遅れても出せる。行事は行くだけで、やることがない。
_KIND_ORDER = {"deadline": 0, "bring": 1, "homework": 2, "event": 3}


def list_tasks(days: int = 14) -> Dict[str, Any]:
    """ダッシュボード用。今日から days 日ぶんを、子ども別・状態別に整えて返す。"""
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
    end = today + dt.timedelta(days=days)

    if DEMO:
        items = _demo_state(today)
    else:
        items = [e for e in _raw(today.isoformat(), end.isoformat()) if e["mine"]]

    for e in items:
        d = dt.date.fromisoformat(e["date"])
        e["days_left"] = (d - today).days
        e["overdue"] = e["days_left"] < 0 and e["status"] != "done"

    points: Dict[str, int] = {}
    for c in config.children:
        points[c["name"]] = 0
    for e in items:
        if e["status"] == "done":
            points[e["child"]] = points.get(e["child"], 0) + e["points"]

    return {
        "today": today.isoformat(),
        "children": [c["name"] for c in config.children],
        "items": sorted(
            items,
            key=lambda x: (x["status"] == "done", x["date"], _KIND_ORDER.get(x["kind"], 9), x["summary"]),
        ),
        "points": points,
    }


def _demo_state(today: dt.date) -> List[Dict[str, Any]]:
    """デモ用の台帳。日付が変わったときだけ作り直す。"""
    global _demo_store, _demo_day
    if _demo_day != today.isoformat() or not _demo_store:
        _demo_store = _demo_items(today)
        _demo_day = today.isoformat()
    return _demo_store


def _demo_names() -> tuple:
    """ダミーの持ち主を、MIMAMORI_CHILDREN で設定した呼び名に合わせる。

    呼び名を変えたときにダミーが誰のものでもなくなると、/kid のやることが
    0件になって会話が始まらない。学齢で対応付け、無ければ並び順で埋める。
    """
    names = [c["name"] for c in config.children] or ["上の子", "下の子"]
    by_level = {c["school_level"]: c["name"] for c in config.children}
    older = by_level.get("junior_high") or names[0]
    younger = by_level.get("elementary") or (names[1] if len(names) > 1 else names[0])
    return older, younger


def _demo_items(today: dt.date) -> List[Dict[str, Any]]:
    """GCP を繋がずに画面を確認するためのダミー。MIMAMORI_DEMO=1 で有効。"""
    def d(n):
        return (today + dt.timedelta(days=n)).isoformat()
    older, younger = _demo_names()
    base = dict(mine=True, link="", description="", time=None)
    return [
        dict(base, id="d1", summary=f"{younger}｜図工 ペットボトル2本 持参", date=d(0),
             child=younger, kind="bring", status="todo", points=2, bring="500mlペットボトル2本、油性ペン"),
        dict(base, id="d2", summary=f"{younger}｜漢字ドリル p.42", date=d(0),
             child=younger, kind="homework", status="doing", points=3, bring=""),
        dict(base, id="d3", summary=f"{older}｜三者面談 希望調査票 提出", date=d(1),
             child=older, kind="deadline", status="todo", points=3, bring=""),
        dict(base, id="d4", summary=f"✓ {older}｜塾 計算プリント", date=d(0),
             child=older, kind="homework", status="done", points=3, bring=""),
        dict(base, id="d5", summary=f"{younger}｜社会科見学（清掃工場）", date=d(6), time="08:15",
             child=younger, kind="event", status="todo", points=0, bring="お弁当、水筒、しおり"),
        dict(base, id="d6", summary=f"{older}｜体育祭 係希望票 提出", date=d(-1),
             child=older, kind="deadline", status="todo", points=3, bring=""),
        dict(base, id="d7", summary=f"{younger}｜社会科見学 参加同意書 提出", date=d(3),
             child=younger, kind="deadline", status="todo", points=3, bring=""),
        dict(base, id="d8", summary=f"{older}｜中間テスト 直し 5問", date=d(2),
             child=older, kind="homework", status="todo", points=5, bring=""),
    ]


# ---------------------------------------------------------------- 書き

def _body(item: Dict[str, Any]) -> Dict[str, Any]:
    date = item["date"]
    end_date = item.get("end_date") or date
    t0, t1 = item.get("time_start"), item.get("time_end")

    if t0:
        start = {"dateTime": f"{date}T{t0}:00", "timeZone": config.timezone}
        end = {"dateTime": f"{end_date}T{(t1 or t0)}:00", "timeZone": config.timezone}
    else:
        # 終日予定。Calendar API の end.date は排他なので +1 日する。
        start = {"date": date}
        end = {"date": (dt.date.fromisoformat(end_date) + dt.timedelta(days=1)).isoformat()}

    lines = []
    if item.get("bring"):
        lines.append("持ち物: " + ("、".join(item["bring"]) if isinstance(item["bring"], list) else item["bring"]))
    if item.get("note"):
        lines.append(item["note"])
    if item.get("source_text"):
        lines += ["", "--- おたより原文 ---", item["source_text"]]
    lines += ["", "（みまもりくんが自動登録）"]

    return {
        "summary": item["title"],
        "description": "\n".join(lines),
        "start": start,
        "end": end,
        "extendedProperties": {
            "private": {
                "app": MARK,
                "child": item.get("child", ""),
                "kind": item.get("kind", ""),
                "status": "todo",
                "points": str(_points_for(item)),
                "bring": ("、".join(item["bring"]) if isinstance(item.get("bring"), list) else (item.get("bring") or "")),
            }
        },
        "reminders": {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": m} for m in config.reminders],
        },
    }


def _points_for(item: Dict[str, Any]) -> int:
    """ポイントは『行動』に付ける。結果（点数）には付けない。"""
    return {"homework": 3, "deadline": 3, "bring": 2, "event": 0}.get(item.get("kind", ""), 1)


def _demo_add(item: Dict[str, Any]) -> None:
    """デモ台帳に足す。

    ここで足さないと、撮ったおたよりが一覧にも会話にも出てこない。
    画面には「追加しました」と出るのに、みまもりくんは元のダミーの話を続ける。
    """
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
    _demo_state(today)          # 台帳がまだ無ければ作らせる
    bring = item.get("bring")
    _demo_store.append(
        {
            "id": "x" + uuid.uuid4().hex[:7],
            "summary": item["title"],
            "date": item["date"],
            "child": item.get("child", ""),
            "kind": item.get("kind", ""),
            "status": "todo",
            "points": _points_for(item),
            "bring": "、".join(bring) if isinstance(bring, list) else (bring or ""),
            "mine": True,
            "link": "",
            "description": item.get("note", "") or "",
            "time": item.get("time_start"),
        }
    )


def create_events(items: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """確定した項目をカレンダーに登録する。ユーザーの承認後にだけ呼ぶ。"""
    results = []
    for item in items:
        if DEMO:
            try:
                _demo_add(item)
                results.append({"title": item["title"], "status": "ok", "link": ""})
            except Exception as e:  # noqa: BLE001
                results.append({"title": item.get("title", "?"), "status": "error", "error": str(e)})
            continue
        try:
            ev = _svc().events().insert(calendarId=config.calendar_id, body=_body(item)).execute()
            results.append({"title": item["title"], "status": "ok", "link": ev.get("htmlLink", "")})
        except Exception as e:  # noqa: BLE001
            results.append({"title": item.get("title", "?"), "status": "error", "error": str(e)})
    return results


def set_status(event_id: str, status: str) -> Dict[str, Any]:
    """状態を変える。todo / doing / done。

    完了しても予定は消さない。件名に ✓ を付けて記録として残し、
    ダッシュボードの未完了リストからは外れる。
    """
    if DEMO:
        for it in _demo_store:
            if it["id"] == event_id:
                it["status"] = status
                title = it["summary"].lstrip("✓ ").strip()
                it["summary"] = ("✓ " + title) if status == "done" else title
                return {"id": event_id, "status": status, "summary": it["summary"]}
        # 記録できていないのに done を返すと、子には「終わったね」と伝わり
        # 親の一覧には残り続ける。できなかったことは、できなかったと返す。
        return {"id": event_id, "status": "error", "note": "その id のやることが見つかりませんでした"}
    ev = _svc().events().get(calendarId=config.calendar_id, eventId=event_id).execute()
    priv = (ev.get("extendedProperties") or {}).get("private") or {}
    priv["status"] = status
    summary = ev.get("summary", "")
    summary = summary.lstrip("✓ ").strip()
    if status == "done":
        summary = "✓ " + summary
    body = {"summary": summary, "extendedProperties": {"private": priv}}
    ev = _svc().events().patch(calendarId=config.calendar_id, eventId=event_id, body=body).execute()
    return {"id": event_id, "status": status, "summary": ev.get("summary", "")}
