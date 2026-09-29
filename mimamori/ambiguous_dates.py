"""日付を推測せず、原文と確認待ちを保持する。Calendar は確定操作だけで触る。"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
import uuid

from . import ledger, notify
from .config import config

KEY = "date_questions"
JST = dt.timezone(dt.timedelta(hours=9))
ISSUES = ("relative", "no_month", "year_cross", "weekday_mismatch", "vague",
          "undecided", "multiple", "recurring", "low_confidence")


def now():
    return dt.datetime.now(JST)


def check(item, today=None, *, require_text=False):
    """モデルの理由に原文から検出した理由を足す。値は推測・補正しない。"""
    item = dict(item)
    today = today or now().date()
    original = item.get("date_text") or item.get("source_text") or ""
    text = unicodedata.normalize("NFKC", original)
    # 予備日は本来の日付とは別候補にしない。原文・メモには残す。
    parts = re.split(r"(?:雨天(?:時|の場合)?[は、:]?|予備日)", text, maxsplit=1)
    primary = parts[0]
    if len(parts) > 1:
        reserve = re.search(r"雨天|予備日", original)
        reserve = original[reserve.start():] if reserve else text[len(primary):]
        if reserve not in item.get("note", ""):
            item["note"] = (item.get("note", "") + "\n" + reserve).strip()
    issues = set(item.get("date_issues") or [])
    if require_text and not text:
        issues.add("low_confidence")
    patterns = {
        "relative": r"来週|再来週|先週|今週|明日|明後日|あさって|翌日|翌週|翌月|翌年|本日|今日|昨日|一昨日|今月|来月|再来月|来年|再来年|\d+(?:日|週間?|か月|ヶ月)後",
        "no_month": r"\d+日",
        "vague": r"\d+月中|上旬|中旬|下旬|月末|月初|頃|ころ",
        "undecided": r"未定|後日決定|調整中",
        "multiple": r"または|又は|いずれか|学年(?:ごと|別)|[・、]\s*\d+日",
        "recurring": r"毎週|隔週|毎月|毎日",
    }
    date_pattern = r"(?:(\d{4})[-/年])?(\d{1,2})[月/.-](\d{1,2})(?:日)?"
    written_dates = list(re.finditer(date_pattern, primary))
    month_day = written_dates[0] if written_dates else None
    for issue, pattern in patterns.items():
        if re.search(pattern, primary) and (issue != "no_month" or not month_day):
            issues.add(issue)
    is_range = bool(item.get("date_is_range") or item.get("end_date") or
                    re.search(r"から|[〜～~]|上旬|中旬|下旬|\d+月中", primary))
    if not is_range and (len(written_dates) > 1 or len(re.findall(r"\d{1,2}日", primary)) > 1):
        issues.add("multiple")
    if item.get("confidence", 1) < 0.5:
        issues.add("low_confidence")
    try:
        date = dt.date.fromisoformat(item.get("date") or "")
        end = dt.date.fromisoformat(item["end_date"]) if item.get("end_date") else date
        if end < date:
            issues.add("vague")
    except ValueError:
        date = None
        if not issues:
            issues.add("vague")
    if month_day:
        year, month, day = month_day.groups()
        # 年のない範囲の終点も検査する（12月30日〜1月3日など）。
        if (not year and (abs(int(month) - today.month) >= 6 or (date and date.year != today.year)) or
                any(not m.group(1) and int(m.group(2)) < int(month) for m in written_dates[1:])):
            issues.add("year_cross")
        if date and (date.month != int(month) or date.day != int(day) or (year and date.year != int(year))):
            issues.add("low_confidence")
        # 各端点の曜日を照合する。曜日だけを全体から拾うと「毎週金曜」等と混線する。
        for m in re.finditer(r"(?:(\d{4})[-/年])?(?:(\d{1,2})[月/.-])?(\d{1,2})(?:日)?\s*(?:[（(]([月火水木金土日])(?:曜日?)?[)）]|([月火水木金土日])曜日?)", primary):
            if date:
                y, mo, d, paren, bare = m.groups()
                weekday = paren or bare
                try:
                    actual = dt.date(int(y or date.year), int(mo or date.month), int(d))
                    if "月火水木金土日"[actual.weekday()] != weekday:
                        issues.add("weekday_mismatch")
                except ValueError:
                    issues.add("low_confidence")
    elif text and not issues:
        issues.add("no_month")
    item["date_text"] = item.get("date_text") or original
    item["date_issues"] = [i for i in ISSUES if i in issues]
    item["date_is_range"] = is_range
    if item["date_issues"]:
        item.update(date=None, end_date=None, needs_review=True)
    return item


def enqueue(items):
    stamp = now().isoformat()
    rows = [dict(i, id=uuid.uuid4().hex, created_at=stamp, state="waiting", reminded_at=None)
            for i in items]
    if rows:
        ledger.transact_setting(KEY, lambda old: (old or []) + rows)
    return len(rows)


def pending():
    return sorted([r for r in (ledger.get_setting(KEY) or []) if r["state"] in ("waiting", "registering")],
                  key=lambda r: r["created_at"])


def change(id_, action, date=None, end_date=None, child=None, *, validate=None, times=None):
    """トランザクション内では副作用を起こさず、登録の権利だけ確保する。"""
    def update(old):
        rows = old or []
        row = next((r for r in rows if r["id"] == id_), None)
        if row is None:
            raise KeyError(id_)
        if row["state"] == "registered" and action == "register":
            return rows
        if row["state"] == "registering" and action in ("dismiss", "confirmed", "retry"):
            row["state"] = {"dismiss": "dismissed", "confirmed": "registered", "retry": "waiting"}[action]
            if action == "confirmed":
                row["result"] = {"state": "registered", "results": [], "confirmed": True}
            return rows
        if row["state"] != "waiting" or action == "confirmed":
            raise ValueError("この項目は処理済みか、登録結果の確認が必要です。")
        if action == "dismiss":
            row["state"] = "dismissed"
        elif action == "register":
            if row.get("date_is_range") and not end_date:
                raise ValueError("いつまでの日付も選んでください。")
            chosen_child = child if child is not None else row.get("child")
            if chosen_child not in [c["name"] for c in config.children]:
                raise ValueError("だれの予定か選んでください。")
            candidate = dict(row, child=chosen_child, chosen_date=date, chosen_end_date=end_date, **(times or {}))
            if validate:
                validate(candidate)
            row.update(candidate, state="registering")
        return rows
    rows = ledger.transact_setting(KEY, update)
    return next(r for r in rows if r["id"] == id_)


def finish(id_, result):
    def update(old):
        for row in old or []:
            if row["id"] == id_ and row["state"] == "registering":
                row.update(state="registered", result=result)
        return old
    ledger.transact_setting(KEY, update)


def remind():
    stamp = now()
    token = uuid.uuid4().hex
    def claim(old):
        for row in old or []:
            if (row["state"] == "waiting" and not row.get("reminded_at") and
                    stamp - dt.datetime.fromisoformat(row["created_at"]) >= dt.timedelta(days=3)):
                row.update(reminded_at=stamp.isoformat(), reminder_token=token)
        return old or []
    rows = ledger.transact_setting(KEY, claim)
    due = [r for r in rows if r.get("reminder_token") == token]
    if due:
        first = due[0]
        # 保存・Calendar 用の件名はそのまま、表示時だけ子の接頭辞を外す。
        title = first["title"].removeprefix(first["child"] + "｜")
        prefix = f"日付の確認待ちが{len(due)}件あります。" if len(due) > 1 else ""
        notify.add("date_question", "日付の確認が 3日 のこっています",
                   prefix + f"『{title}』（{first['child']}、プリントの表記：『{first['date_text']}』）の日付が決まっていません。"
                   "みまもりくんの『確認すること』から日付を選んでください。")
