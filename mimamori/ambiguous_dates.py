"""日付を推測せず、原文と確認待ちを保持する。Calendar は確定操作だけで触る。"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
import uuid

from . import calendar_tools, dedupe, ledger, notify
from .config import config

KEY = "date_questions"
JST = dt.timezone(dt.timedelta(hours=9))
ISSUES = ("relative", "no_month", "year_cross", "weekday_mismatch", "vague",
          "undecided", "multiple", "recurring", "low_confidence")

# 「まで／までに」の揺れを拾い、原文の日付表現が大きく違う候補は分ける。
QUESTION_DATE_RATIO = 0.82


def _title_parts(text):
    """言い換え用の本文と補足を分ける。完全一致のキーには使わない。"""
    text = unicodedata.normalize("NFKC", text or "")
    pairs = {"(": ")", "[": "]", "{": "}", "【": "】", "「": "」",
             "『": "』", "〈": "〉", "《": "》", "〔": "〕"}
    stack, spans = [], []
    for index, char in enumerate(text):
        if char in pairs:
            stack.append((index, pairs[char]))
        elif stack and char == stack[-1][1]:
            start, _ = stack.pop()
            spans.append((start, index + 1))
    # 閉じていないかっこ以降の本文まで消さない。
    removed = {index for start, end in spans for index in range(start, end)}
    title = dedupe.norm("".join(char for index, char in enumerate(text) if index not in removed))
    supplements = tuple(dedupe.norm(text[start + 1:end - 1])
                        for start, end in sorted(spans))
    return title, supplements


_TITLE_VERBS = sorted(("準備", "持参", "用意", "持ってくる", "持っていく",
                       "持ってくること", "持ってくるもの"), key=len, reverse=True)
_TITLE_DATE_SUFFIXES = sorted(("期限", "締切", "締め切り", "〆切", "しめきり"),
                              key=len, reverse=True)


def _title_paraphrase(a, b):
    a, a_supplements = _title_parts(a)
    b, b_supplements = _title_parts(b)
    if a_supplements and b_supplements and a_supplements != b_supplements:
        return False

    def strip_date_suffix(title):
        # 日付の種類だけを表す末尾語を1つ除く。保存値・完全一致キーは変えない。
        for suffix in _TITLE_DATE_SUFFIXES:
            if title.endswith(suffix):
                remaining = title[:-len(suffix)]
                return remaining if len(remaining) >= 2 else title
        return title

    a, b = strip_date_suffix(a), strip_date_suffix(b)
    short, long = sorted((a, b), key=len)
    if len(short) >= 2 and long.endswith(short):
        return True

    def stem(title):
        for verb in _TITLE_VERBS:
            if title.endswith(verb):
                return title[:-len(verb)]
        return None

    a_stem, b_stem = stem(a), stem(b)
    return a_stem is not None and len(a_stem) >= 2 and a_stem == b_stem


def _question_key(item):
    return (item.get("child"), dedupe.norm(item.get("title")),
            unicodedata.normalize("NFKC", item.get("date_text") or ""))



# 長い語を先に取り、再来週を来週、翌々日を翌日として扱わない。
_DATE_WORDS = (
    "今日", "本日", "明日", "明後日", "あさって", "昨日", "一昨日",
    "今週", "来週", "再来週", "翌週", "前週", "先週",
    "今月", "来月", "再来月", "翌月", "前月", "先月",
    "今年", "来年", "再来年", "翌年", "前年", "昨年",
    "前日", "翌日", "翌々日", "当日", "前々日",
    "上旬", "中旬", "下旬", "初旬", "末", "月末", "月初",
)
_DATE_ANCHORS = re.compile(
    r"(?P<number>[0-9]+)|(?P<word>"
    + "|".join(sorted(_DATE_WORDS, key=len, reverse=True))
    + r")|(?P<weekday>[月火水木金土日])曜日?|\(\s*(?P<paren>[月火水木金土日])(?:曜日?)?\s*\)"
)


def _date_anchors(text):
    """補足を消す前の原文から日付の決め手を順に保持する。時刻の数字も含む。"""
    text = unicodedata.normalize("NFKC", text or "")
    anchors = []
    for match in _DATE_ANCHORS.finditer(text):
        number, word, weekday, paren = match.groups()
        anchors.append(("number", number) if number is not None else
                       ("word", word) if word is not None else
                       ("weekday", weekday or paren))
    return tuple(anchors)


def _question_matches(candidates, rows):
    """完全一致を優先し、未回答だけに言い換えを1対1で割り当てる。"""
    keys = [_question_key(r) for r in rows]
    anchors = [_date_anchors(r.get("date_text")) for r in rows]
    edges = []
    for i, item in enumerate(candidates):
        key = _question_key(item)
        item_anchors = _date_anchors(item.get("date_text"))
        for j, row in enumerate(rows):
            if (row.get("child") != item.get("child") or
                    row["state"] not in ("waiting", "registering", "answered", "registered")):
                continue
            if key == keys[j]:
                edges.append((True, 1.0, i, j))
                continue
            if row["state"] not in ("waiting", "registering") or item_anchors != anchors[j]:
                continue
            date_score = dedupe.similarity(key[2], keys[j][2])
            if (date_score >= QUESTION_DATE_RATIO and
                    _title_paraphrase(item.get("title"), row.get("title"))):
                edges.append((False, date_score, i, j))
    matches, used = {}, set()
    for _, _, i, j in sorted(edges, key=lambda e: (-e[0], -e[1], e[2], e[3])):
        if i not in matches and j not in used:
            matches[i] = rows[j]
            used.add(j)
    return matches


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
    """同じ質問の照合と追加を同一トランザクションで行う。"""
    if not items:
        return {"count": 0, "skipped_titles": []}
    today = now().date()
    try:
        # 日付を推測できないので、前後1年の既存予定を照合する。
        existing = calendar_tools.list_raw(
            (today - dt.timedelta(days=365)).isoformat(),
            (today + dt.timedelta(days=365)).isoformat())
    except Exception:  # 読めなければ質問を残す。台帳との照合は続ける。
        existing = []
    stamp = now().isoformat()
    candidates = [dict(i, id=uuid.uuid4().hex, created_at=stamp, state="waiting", reminded_at=None)
                  for i in items]
    # 同じ読み取り内では正規化後の完全一致だけをまとめる。
    unique = {}
    for item in candidates:
        key = _question_key(item)
        unique.setdefault(key, item)
    candidates = list(unique.values())
    outcome = {}

    def add(old):
        rows = list(old or [])
        matches = _question_matches(candidates, rows)
        question_ids, skipped = set(), []
        for index, item in enumerate(candidates):
            title = dedupe.norm(item.get("title", ""))
            child = item.get("child")
            text = unicodedata.normalize("NFKC", item.get("date_text") or "")
            related = [r for r in rows if r.get("child") == child
                       and dedupe.norm(r.get("title", "")) == title]
            same = matches.get(index)
            if same and same["state"] in ("answered", "registered"):
                skipped.append(item.get("title", ""))
                continue
            if same:
                # 再読込でも未回答の確認を案内する。同一バッチの重複は1件と数える。
                question_ids.add(same["id"])
                continue
            # 原文が違うと分かる登録済み予定を、件名だけの照合で拾い直さない。
            other_rows = [r for r in related
                          if r["state"] in ("answered", "registered", "registering")
                          and unicodedata.normalize("NFKC", r.get("date_text") or "") != text]
            other_ids = {result["id"] for r in other_rows
                         for result in (r.get("result") or {}).get("results", [])
                         if result.get("id")}
            # 通信結果不明→親の確認済みでは Calendar id が残らない。
            other_dates = {r["chosen_date"] for r in other_rows if r.get("chosen_date")
                           and not any(v.get("id") for v in (r.get("result") or {}).get("results", []))}
            if title and child in [c["name"] for c in config.children] and any(
                    ev.get("child") == child and dedupe.norm(ev.get("summary", "")) == title
                    and ev.get("id") not in other_ids and ev.get("date") not in other_dates
                    for ev in existing):
                skipped.append(item.get("title", ""))
                continue
            rows.append(item)
            question_ids.add(item["id"])
        # Firestore の再試行ごとに結果を置き換える（加算しない）。
        outcome.update(count=len(question_ids), skipped_titles=skipped)
        return rows

    ledger.transact_setting(KEY, add)
    return outcome


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
