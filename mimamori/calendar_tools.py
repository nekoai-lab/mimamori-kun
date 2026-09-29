"""Google Calendar への読み書き。カレンダーそのものを台帳として使う。

新しいDBは作らない。予定の extendedProperties.private に
「誰の・種別・状態・ポイント」を持たせ、ダッシュボードはそれを読むだけ。
ポイントの加点・取消は set_status を通して行う。

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


def list_raw(start_date: str, end_date: str) -> List[Dict[str, Any]]:
    """id を含めて既存予定を返す。**アプリ内部用**（エージェントのツールではない）。

    list_events は件名と日付しか返さない（id を出すとモデルが人に読めない文字列を喋るため）。
    日付を直す・差し替えるには id が要るので、内部からはこちらを使う。
    """
    if DEMO:
        today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
        rows = [e for e in _demo_state(today) if start_date <= e["date"] <= end_date]
    else:
        rows = [e for e in _raw(start_date, end_date) if e["mine"]]
    for e in rows:
        e.setdefault("minutes", minutes_for(e))
    return rows


def event_meta(event_id: str) -> Optional[Dict[str, Any]]:
    """その予定がだれのもので、だれが・いつ入れたか（#16）。みまもりくんの予定でなければ None。

    子どもが id を指定して状態を変えたり取り消したりするときに、サーバー側の記録で確かめる。
    status は今の状態、created は UNIX 秒（カレンダーが付ける作成時刻。デモは足したとき）。
    """
    if not event_id:
        return None
    if DEMO:
        today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
        row = next((e for e in _demo_state(today) if e["id"] == event_id), None)
        if not row:
            return None
        return {"child": row.get("child", ""), "source": row.get("source", "parent"),
                "status": row.get("status", "todo"), "created": float(row.get("created") or 0)}
    try:
        ev = _svc().events().get(calendarId=config.calendar_id, eventId=event_id).execute()
    except Exception:  # noqa: BLE001
        return None
    priv = (ev.get("extendedProperties") or {}).get("private") or {}
    if priv.get("app") != MARK:
        return None
    try:
        created = dt.datetime.fromisoformat((ev.get("created") or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        created = 0.0
    return {"child": priv.get("child", ""), "source": priv.get("source", "parent"),
            "status": priv.get("status", "todo"), "created": created}


def event_owner(event_id: str) -> Optional[str]:
    """その予定がだれのものか（#16）。見つからなければ None。"""
    meta = event_meta(event_id)
    return meta["child"] if meta else None


def _raw(start_date: str, end_date: str, completed_on: str = "") -> List[Dict[str, Any]]:
    tmin = f"{start_date}T00:00:00+09:00"
    tmax = (dt.date.fromisoformat(end_date) + dt.timedelta(days=1)).isoformat() + "T00:00:00+09:00"
    params = dict(calendarId=config.calendar_id, singleEvents=True, maxResults=250)
    if completed_on:
        # 予定日とは独立に検索する。遠い過去・未来の完了も今日の実績に含む。
        params["privateExtendedProperty"] = f"done_date={completed_on}"
    else:
        params.update(timeMin=tmin, timeMax=tmax, orderBy="startTime")
    events = []
    while True:
        res = _svc().events().list(**params).execute()
        events.extend(res.get("items", []))
        if not res.get("nextPageToken"):
            break
        params["pageToken"] = res["nextPageToken"]
    out = []
    for ev in events:
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
                "done_at": priv.get("done_at") or "",
                "batch": priv.get("batch", ""),
                "source": priv.get("source", "parent"),
                "minutes": int(priv.get("minutes") or 0) or _MINUTES.get(priv.get("kind", ""), 10),
                "points": int(priv.get("points", 0) or 0),
                "bring": priv.get("bring", ""),
            }
        )
    return out


# 何日前まで遡って「遅れている」を拾うか。前向きの窓（今日+14日）と対称にする。
# ここが 0 だと、昨日期限の提出物がそもそも取れず、遅れている欄が必ず空になる。
OVERDUE_DAYS = 14

# 同じ日のものをどの順で見せるか。取り返しがつかないものを上に置く。
# 提出物はその日を過ぎたら終わり。持ち物はその日の朝まで。
# 宿題は遅れても出せる。行事は行くだけで、やることがない。
_KIND_ORDER = {"deadline": 0, "bring": 1, "homework": 2, "event": 3}


def _done_today(item: Dict[str, Any], today: dt.date) -> bool:
    if item.get("status") != "done" or not item.get("done_at"):
        return False
    return dt.datetime.fromisoformat(item["done_at"]).astimezone(
        dt.timezone(dt.timedelta(hours=9))).date() == today


def list_tasks(days: int = 14) -> Dict[str, Any]:
    """ダッシュボード用。今日から days 日ぶんを、子ども別・状態別に整えて返す。"""
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
    end = today + dt.timedelta(days=days)
    start = today - dt.timedelta(days=OVERDUE_DAYS)

    if DEMO:
        items = _demo_state(today)
    else:
        items = [e for e in _raw(start.isoformat(), end.isoformat()) if e["mine"]]
        completed = _raw(start.isoformat(), end.isoformat(), completed_on=today.isoformat())
        items = list({e["id"]: e for e in items + completed if e["mine"]}.values())

    items = [e for e in items if e["date"] >= today.isoformat()
             or e["status"] != "done" or _done_today(e, today)]

    # 親が「けす」を押したものは、記録としてカレンダーには残すが画面には出さない。
    items = [e for e in items if e["status"] != "rejected"]

    for e in items:
        e.setdefault("minutes", minutes_for(e))
        d = dt.date.fromisoformat(e["date"])
        e["days_left"] = (d - today).days
        e["overdue"] = e["days_left"] < 0 and e["status"] != "done"

    points: Dict[str, int] = {}
    for c in config.children:
        points[c["name"]] = 0
    for e in items:
        if _done_today(e, today):
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
    """デモ用の台帳。日をまたいでも完了状態を保持する。"""
    global _demo_store, _demo_day
    if not _demo_day or not _demo_store:
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
    # 分はダミーでも入れておく。上の子の枠バーが空になると、確かめようがない。
    return [
        dict(base, id="d1", summary=f"{younger}｜図工 ペットボトル2本 持参", date=d(0),
             child=younger, kind="bring", status="todo", points=2, bring="500mlペットボトル2本、油性ペン"),
        dict(base, id="d2", summary=f"{younger}｜漢字ドリル p.42", date=d(0),
             child=younger, kind="homework", status="doing", points=3, bring=""),
        dict(base, id="d3", summary=f"{older}｜三者面談 希望調査票 提出", date=d(1),
             child=older, kind="deadline", status="todo", points=3, bring=""),
        dict(base, id="d4", summary=f"{older}｜塾 計算プリント", date=d(0),
             child=older, kind="homework", status="todo", points=3, bring=""),
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

def _body(item: Dict[str, Any], status: str = "todo") -> Dict[str, Any]:
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
                "status": status,
                "points": str(_points_for(item)),
                "bring": ("、".join(item["bring"]) if isinstance(item.get("bring"), list) else (item.get("bring") or "")),
                # どの取り込みで入ったか（版）。改訂版との差分を出すときに使う。
                "batch": item.get("batch", ""),
                "minutes": str(minutes_for(item)),
                # だれが入れたか。子が入れたものは親に知らせ、あとから消せるようにする。
                "source": item.get("source", "parent"),
            }
        },
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": m}
                for m in (config.reminders_timed if t0 else config.reminders_allday)
            ],
        },
    }


# 1件あたりの目安時間（分）。**画面には「量」で出し、内部では時間で数える。**
# 実測ではなく目安。上の子の枠バーが「だいたい入るか」を言えればいい。
_MINUTES = {"homework": 30, "deadline": 5, "bring": 5, "event": 0}


def minutes_for(item: Dict[str, Any]) -> int:
    try:
        m = int(item.get("minutes") or 0)
    except (TypeError, ValueError):
        m = 0
    return m if m > 0 else _MINUTES.get(item.get("kind", ""), 10)


def _points_for(item: Dict[str, Any]) -> int:
    """ポイントは『行動』に付ける。結果（点数）には付けない。"""
    return {"homework": 3, "deadline": 3, "bring": 2, "event": 0}.get(item.get("kind", ""), 1)


def _demo_add(item: Dict[str, Any], status: str = "todo") -> str:
    """デモ台帳に足す。

    ここで足さないと、撮ったおたよりが一覧にも会話にも出てこない。
    画面には「追加しました」と出るのに、みまもりくんは元のダミーの話を続ける。
    """
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
    _demo_state(today)          # 台帳がまだ無ければ作らせる
    bring = item.get("bring")
    new_id = "x" + uuid.uuid4().hex[:7]
    _demo_store.append(
        {
            "id": new_id,
            "summary": item["title"],
            "date": item["date"],
            "child": item.get("child", ""),
            "kind": item.get("kind", ""),
            "status": status,
            "points": _points_for(item),
            "bring": "、".join(bring) if isinstance(bring, list) else (bring or ""),
            "batch": item.get("batch", ""),
            "minutes": minutes_for(item),
            "source": item.get("source", "parent"),
            "created": dt.datetime.now(dt.timezone.utc).timestamp(),   # 取り消せる時間を確かめるため（#16）
            "mine": True,
            "link": "",
            "description": item.get("note", "") or "",
            "time": item.get("time_start"),
        }
    )
    return new_id


def create_events(items: List[Dict[str, Any]], status: str = "todo") -> List[Dict[str, str]]:
    """項目をカレンダーに登録する。

    status に "pending" を渡すと、親が承認するまで子のやることには出ない。
    子の画面から撮ったものは、外から来た画像を読ませた結果がそのまま
    書き込みになるので、必ず承認を挟む。
    """
    results = []
    for item in items:
        if DEMO:
            try:
                new_id = _demo_add(item, status)
                results.append({"title": item["title"], "status": "ok", "link": "", "id": new_id})
            except Exception as e:  # noqa: BLE001
                results.append({"title": item.get("title", "?"), "status": "error", "error": str(e)})
            continue
        try:
            ev = _svc().events().insert(calendarId=config.calendar_id, body=_body(item, status)).execute()
            results.append({"title": item["title"], "status": "ok",
                            "link": ev.get("htmlLink", ""), "id": ev.get("id", "")})
        except Exception as e:  # noqa: BLE001
            results.append({"title": item.get("title", "?"), "status": "error", "error": str(e)})
    return results


def set_status(event_id: str, status: str) -> Dict[str, Any]:
    """状態を変える。pending / todo / doing / done / rejected。

    完了しても予定は消さない。件名に ✓ を付けて記録として残し、
    ダッシュボードの未完了リストからは外れる。
    """
    from . import points

    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec="seconds")
    if DEMO:
        for it in _demo_state(dt.date.fromisoformat(now[:10])):
            if it["id"] == event_id:
                done_at = points.record_status(it, status, now)
                it["status"] = status
                if done_at:
                    it["done_at"] = done_at
                else:
                    it.pop("done_at", None)
                title = it["summary"].lstrip("✓ ").strip()
                it["summary"] = ("✓ " + title) if status == "done" else title
                return {"id": event_id, "status": status, "summary": it["summary"]}
        return {"id": event_id, "status": "error", "note": "その id のやることが見つかりませんでした"}
    ev = _svc().events().get(calendarId=config.calendar_id, eventId=event_id).execute()
    priv = (ev.get("extendedProperties") or {}).get("private") or {}
    if priv.get("app") != MARK:
        raise ValueError("みまもりくんの予定ではありません")
    done_at = (priv.get("done_at") or now) if status == "done" else ""
    priv.update(status=status, done_at=done_at or None, done_date=done_at[:10] or None)
    summary = ev.get("summary", "").lstrip("✓ ").strip()
    if status == "done":
        summary = "✓ " + summary
    body = {"summary": summary, "extendedProperties": {"private": priv}}
    # Calendar と台帳を跨ぐ原子的な保存はできない。Calendar 成功後に台帳へ記録し、
    # 台帳側が失敗した場合はエラーを返す。同じ操作の再送で重複せず回復できる。
    _svc().events().patch(calendarId=config.calendar_id, eventId=event_id, body=body).execute()
    canonical = points.record_status({**priv, "id": event_id, "summary": summary}, status, done_at)
    if canonical != done_at:
        # 同時に完了した場合も最初のトランザクションの時刻に揃える。
        _svc().events().patch(calendarId=config.calendar_id, eventId=event_id, body={
            "extendedProperties": {"private": {"done_at": canonical or None,
                                                 "done_date": canonical[:10] or None}}
        }).execute()
    return {"id": event_id, "status": status, "summary": summary}


def move_event(event_id: str, new_date: str) -> Dict[str, Any]:
    """予定の日にちを直す。**消して作り直さない。**

    作り直すと id が変わり、ポイント台帳の ref_id が迷子になる。
    改訂版の予定表で日程がずれたときは、この道を通る。
    """
    dt.date.fromisoformat(new_date)          # 形が違えばここで落とす
    if DEMO:
        for it in _demo_store:
            if it["id"] == event_id:
                it["date"] = new_date
                return {"id": event_id, "date": new_date, "summary": it["summary"]}
        return {"id": event_id, "status": "error", "note": "その id の予定が見つかりませんでした"}
    ev = _svc().events().get(calendarId=config.calendar_id, eventId=event_id).execute()
    st = ev.get("start", {})
    if st.get("dateTime"):
        t0 = st["dateTime"][11:]
        t1 = (ev.get("end", {}).get("dateTime") or st["dateTime"])[11:]
        body = {
            "start": {"dateTime": f"{new_date}T{t0}", "timeZone": config.timezone},
            "end": {"dateTime": f"{new_date}T{t1}", "timeZone": config.timezone},
        }
    else:
        end = (dt.date.fromisoformat(new_date) + dt.timedelta(days=1)).isoformat()
        body = {"start": {"date": new_date}, "end": {"date": end}}
    ev = _svc().events().patch(calendarId=config.calendar_id, eventId=event_id, body=body).execute()
    return {"id": event_id, "date": new_date, "summary": ev.get("summary", "")}
