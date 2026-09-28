"""#26：学年に合わせた漢字・ふりがな（static/reading.js）。node で動かして確かめる。

node が無い環境では飛ばす（GitHub の Ubuntu には入っている）。
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "static" / "data" / "reading"

HARNESS = r"""
const R = require(process.argv[1]);
const fs = require('fs');
const dir = process.argv[2];
const load = n => JSON.parse(fs.readFileSync(dir + '/' + n, 'utf8'));
const cases = JSON.parse(fs.readFileSync(0, 'utf8'));
const out = [];
// とても小さな document（DOM の組み立てを確かめるだけ）
function el(tag){ return { tag, attrs:{}, kids:[], setAttribute(k,v){this.attrs[k]=v}, appendChild(c){this.kids.push(c); return c} }; }
const doc = { createDocumentFragment(){ return el('#frag') }, createElement: el, createTextNode(t){ return { tag:'#text', text:t } } };
function html(n){ if(n.tag==='#text') return n.text.replace(/</g,'&lt;'); const inner=n.kids.map(html).join(''); return n.tag==='#frag'? inner : '<'+n.tag+'>'+inner+'</'+n.tag+'>'; }
for (const c of cases) {
  if (c.nodata) R.setData(null, null, null);
  else if (c.nodict) R.setData(null, null, load('labels.json'));
  else R.setData(load('kanji-grades.json'), load('words.json'), load('labels.json'));
  if (c.label) { out.push(R.label(c.label, c.policy)); continue; }
  const r = R.render(c.text, c.policy, c.opts || {}, doc);
  out.push({ html: html(r.node), speech: r.speech, unresolved: r.unresolved });
}
console.log(JSON.stringify(out));
"""

node = shutil.which("node")
pytestmark = pytest.mark.skipif(node is None, reason="node が無い")


def run(cases):
    p = subprocess.run([node, "-e", HARNESS, str(ROOT / "static" / "reading.js"), str(DATA)],
                       input=json.dumps(cases, ensure_ascii=False), capture_output=True, text=True, check=True)
    return json.loads(p.stdout)


def one(text, policy=None, **opts):
    return run([{"text": text, "policy": policy or {}, "opts": opts}])[0]


# ---------------------------------------------------------------- 字表

def test_kanji_table_matches_the_official_counts():
    t = json.loads((DATA / "kanji-grades.json").read_text(encoding="utf-8"))
    counts = {g: len(s) for g, s in t["grades"].items()}
    assert counts == {"1": 80, "2": 160, "3": 200, "4": 202, "5": 193, "6": 191}
    allc = "".join(t["grades"].values())
    assert len(allc) == len(set(allc)) == 1026
    assert "文部科学省" in t["source"]


def test_dictionary_readings_are_kana_and_every_word_has_kanji():
    w = json.loads((DATA / "words.json").read_text(encoding="utf-8"))["words"]
    import re
    for word, info in w.items():
        assert re.search(r"[一-鿿]", word), word
        assert re.fullmatch(r"[ぁ-ゟー ]+", info["r"]), (word, info["r"])


# ---------------------------------------------------------------- 学年の境目

def test_grade1_default_puts_readings_on_grade1_words():
    r = one("学校で 音読を する", {"school_grade": "e1"})
    assert "<ruby>学校<rp>（</rp><rt>がっこう</rt><rp>）</rp></ruby>" in r["html"]
    assert "<rt>おんどく</rt>" in r["html"]


def test_grade2_previous_scope_knows_grade1_but_not_grade2():
    r = one("学校で 音読を する", {"school_grade": "e2"})
    assert "<rt>がっこう</rt>" not in r["html"] and "学校" in r["html"]     # 学・校は1年
    assert "<rt>おんどく</rt>" in r["html"]                                 # 読は2年


def test_current_grade_scope_uses_this_years_kanji_plainly():
    r = one("学校で 音読を する", {"school_grade": "e2", "kanji_scope": "current_grade"})
    assert "<rt>" not in r["html"]
    assert r["html"] == "学校で 音読を する"


@pytest.mark.parametrize("grade", ["e1", "e2", "e3", "e4", "e5", "e6"])
def test_irregular_words_keep_readings_through_elementary(grade):
    r = one("今日の 宿題", {"school_grade": grade, "kanji_scope": "current_grade"})
    assert "<rt>きょう</rt>" in r["html"]


def test_junior_high_uses_elementary_kanji_plainly_including_irregular():
    r = one("今日の 宿題と 社会科見学", {"school_grade": "j1"})
    assert "<rt>" not in r["html"]


def test_unset_grade_adds_readings_to_basic_words():
    r = one("学校の 宿題", {})
    assert "<rt>がっこう</rt>" in r["html"] and "<rt>しゅくだい</rt>" in r["html"]


def test_okurigana_only_the_kanji_get_the_reading():
    r = one("見た目を 選ぶ", {"school_grade": "e1"})
    assert "<ruby>見<rp>（</rp><rt>み</rt>" in r["html"]
    assert "<ruby>目<rp>（</rp><rt>め</rt>" in r["html"]
    assert "<ruby>選<rp>（</rp><rt>えら</rt><rp>）</rp></ruby>ぶ" in r["html"]


# ---------------------------------------------------------------- 設定

def test_known_kanji_override_and_word_override():
    r = one("音読", {"school_grade": "e2", "known_kanji_overrides": ["読"]})
    assert "<rt>" not in r["html"]
    r = one("学校", {"school_grade": "e3", "ruby_word_overrides": ["学校"]})
    assert "<rt>がっこう</rt>" in r["html"]


def test_readings_on_for_everything_but_not_for_questions():
    assert "<rt>がっこう</rt>" in one("学校", {"school_grade": "e6"}, readingsOn=True)["html"]
    assert "<rt>" not in one("学校", {"school_grade": "e1"}, readingsOn=True, contentRole="question")["html"]


def test_question_text_never_gets_readings():
    r = one("次の 漢字の 読み方を 書きなさい。音読", {"school_grade": "e1"}, contentRole="question")
    assert "<rt>" not in r["html"] and r["html"].startswith("次の 漢字")


# ---------------------------------------------------------------- 分からないとき・安全

def test_unknown_words_keep_the_original_and_are_reported():
    r = one("鑑賞会", {"school_grade": "e2"})
    assert r["html"] == "鑑賞会" and r["unresolved"] == ["鑑賞会"]


def test_missing_dictionary_keeps_the_original_without_guessing():
    r = run([{"text": "学校の 宿題", "policy": {"school_grade": "e1"}, "nodata": True}])[0]
    assert "<rt>" not in r["html"] and r["html"] == "学校の 宿題"
    assert r["unresolved"] == ["学校", "宿題"]


def test_html_in_text_is_never_executed():
    r = one('<img src=x onerror="alert(1)">学校', {"school_grade": "e1"})
    assert "<img" not in r["html"] and "&lt;img" in r["html"]


def test_speech_is_the_original_text_once():
    r = one("学校で 音読を する", {"school_grade": "e1"})
    assert r["speech"] == "学校で 音読を する"
    assert '"aria-hidden"' not in r["speech"]


def test_reading_js_builds_dom_without_innerhtml():
    src = (ROOT / "static" / "reading.js").read_text(encoding="utf-8")
    assert "innerHTML" not in src and "insertAdjacentHTML" not in src


# ---------------------------------------------------------------- 固定ラベル

def test_labels_switch_between_kana_and_kanji_by_grade():
    out = run([
        {"label": "today", "policy": {"school_grade": "e1"}},
        {"label": "today", "policy": {"school_grade": "j1"}},
        {"label": "shoot", "policy": {"school_grade": "e1"}},
        {"label": "shoot", "policy": {"school_grade": "j2"}},
        {"label": "reward", "policy": {}},
        {"label": "today", "policy": {"school_grade": "j1"}, "nodict": True},   # 辞書が取れない：推測せず、かな
        {"label": "today", "policy": {}, "nodata": True},                       # ラベルも取れない：画面のもとの文字を使う
    ])
    assert out == ["きょう", "今日", "とる", "とる", "ごほうび", "きょう", None]
