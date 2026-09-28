"""A の結合（2）：相棒の着替え・子の / のナビを下に・「もう一度確かめる」の余白・/login の色と書体。

ブラウザでの見た目（320px・文字200%・375px・PC・明暗・テーマ3種）は PR に記録する。ここではそれを支える作りを守る。
"""
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "static"
KID = (STATIC / "kid.html").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
LOGIN = (STATIC / "login.html").read_text(encoding="utf-8")
CSS = (STATIC / "appearance.css").read_text(encoding="utf-8")


def rule(html_or_css, selector):
    m = re.search(re.escape(selector) + r"\{([^}]*)\}", html_or_css)
    assert m, selector
    return m.group(1)


# ---------------------------------------------------------------- ① 相棒の着替え

@pytest.mark.parametrize("theme", ["rocket-lab", "monochrome", "snow-bird"])
def test_companion_changes_with_each_theme(theme):
    assert f'class="companion-art{" ap-art-mono" if theme == "monochrome" else ""}" data-art="{theme}" aria-hidden="true"' in KID
    body = rule(KID, f':root[data-kid-theme="{theme}"] .companion-art[data-art="{theme}"]')
    assert "display:block" in body
    if theme == "monochrome":
        assert "background-color:var(--kid-text)" in body          # 線画は文字の色で塗る（暗い画面でも見える）
        assert "monochrome.svg" in KID
    else:
        assert f"/static/assets/appearance/{theme}.svg" in body
    assert (STATIC / "assets" / "appearance" / f"{theme}.svg").exists()


def test_companion_keeps_its_spoken_name_and_neutral_picture():
    assert "display:none" in rule(KID, ".companion-art")            # テーマがなければ元の絵のまま
    hidden = rule(KID, ":root[data-kid-theme] .companion-picture")
    assert "display:none" not in hidden and "clip-path:inset(50%)" in hidden   # 見えなくしても読み上げの名前は残す
    assert 'role="img" aria-label="相棒のまる" id="companion-picture"' in KID
    assert '$("#companion-picture").setAttribute("aria-label","相棒の"+companionName)' in KID


# ---------------------------------------------------------------- ② 子の / のナビを下に

def test_kid_capture_nav_is_at_the_bottom_like_kid_page():
    nav = rule(INDEX, 'body[data-audience="kid"] [data-family-nav]')
    assert "position:fixed" in nav and "bottom:0" in nav and "env(safe-area-inset-bottom)" in nav
    link = rule(INDEX, 'body[data-audience="kid"] [data-family-nav] a')
    assert "min-height:48px" in link
    assert "var(--kid-nav-h" in rule(INDEX, 'body[data-audience="kid"]')     # 本文の下にナビの高さぶん空ける
    # ナビが高くなりすぎたら固定をやめる
    assert "position:static" in rule(INDEX, 'body[data-audience="kid"].nav-in-flow [data-family-nav]')
    assert 'classList.toggle("nav-in-flow", h>vh*0.3)' in INDEX


def test_theme_button_stays_in_parent_nav_and_moves_up_for_kids():
    # 親：リンクの行の右端（元の場所）。子：ナビが下に行くので、見出しの行に置く
    assert re.search(r'<button class="theme" id="theme" type="button">☾ 暗く</button>\s*</nav>', INDEX)
    assert "if(kid && theme.parentElement!==hdr) hdr.appendChild(theme);" in INDEX
    assert "if(!kid && theme.parentElement!==nav) nav.appendChild(theme);" in INDEX
    assert 'observe(document.body,{attributes:true,attributeFilter:["data-audience"]})' in INDEX


# ---------------------------------------------------------------- ③ 「もう一度確かめる」の余白

def test_identity_retry_has_space_below():
    m = re.search(r"#identity-retry\{margin:(\d+)px 0 (\d+)px\}", INDEX)
    assert m and int(m.group(2)) >= 16


# ---------------------------------------------------------------- ④ /login の色と書体

def test_login_uses_the_quiet_entry_palette_and_font():
    assert '<html lang="ja" data-audience="entry">' in LOGIN
    assert LOGIN.index("/static/theme.js") < LOGIN.index("/static/appearance.css")
    assert "Zen Maru Gothic" not in LOGIN and "Zen+Maru+Gothic" not in LOGIN
    entry = rule(LOGIN, ':root[data-audience="entry"]')
    for token in ("--me:var(--parent-accent)", "--error:var(--parent-warning)", "--shadow:none"):
        assert token in entry
    assert "border-radius:16px" in rule(LOGIN, ".card")


def test_entry_shares_parent_tokens_and_font_in_appearance():
    assert '[data-audience="parent"], [data-audience="entry"] {' in CSS
    assert '[data-theme="dark"][data-audience="entry"]' in CSS
    assert 'html:root[data-audience="entry"] body { font-family: var(--parent-font); }' in CSS \
        or 'html:root[data-audience="parent"] body, html:root[data-audience="entry"] body { font-family: var(--parent-font); }' in CSS
    assert 'html:root[data-audience="entry"] :is(h1, h2, h3, h4)' in CSS
