"""A の結合：塊 A（見た目の共通基盤）が入った画面の見出しの書体と、/board のログアウトの2つの強弱。

- 見出しに明朝体・等幅英字を混ぜない（UX_SPEC §3.1）。A が入った画面（/・/board・/kid）の見出しは本文と同じ書体
- ログアウトは「この端末」をふつうの強さ、「すべての端末」を一段弱くし、範囲（子どもの端末も含む）を文で補う（PR-17 A4）
ブラウザでの見た目（320px・文字200%・375px・PC・明暗）は PR に記録する。ここではそれを支える作りを守る。
"""
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "static"
A_PAGES = ["index.html", "board.html", "kid.html"]


def css_rules(html):
    css = "\n".join(re.findall(r"<style>([\s\S]*?)</style>", html))
    return [(sel.strip(), body) for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)]


@pytest.mark.parametrize("page", A_PAGES)
def test_headings_do_not_use_mincho_or_monospace(page):
    html = (STATIC / page).read_text(encoding="utf-8")
    assert "/static/appearance.css" in html
    for sel, body in css_rules(html):
        heading = re.search(r"(^|[\s,>])h[1-4]\b", sel)
        if heading and "font-family" in body:
            assert not re.search(r"Mincho|serif\b|Mono|monospace", body), (page, sel, body)
    assert "Zen+Old+Mincho" not in html            # 使わない書体は読み込まない


def test_appearance_sets_heading_font_for_parent_and_kid():
    css = (STATIC / "appearance.css").read_text(encoding="utf-8")
    assert re.search(r'html:root\[data-audience="parent"\] :is\(h1, h2, h3, h4\)[^{]*\{[^}]*font-family:\s*var\(--parent-font\)', css)
    assert re.search(r'html:root\[data-audience="kid"\] :is\(h1, h2, h3, h4\)[^{]*\{[^}]*font-family:\s*var\(--kid-font, inherit\)', css)
    assert re.search(r'--parent-font:\s*system-ui, -apple-system, "Hiragino Kaku Gothic ProN", "Noto Sans JP", sans-serif', css)


def test_logout_all_is_weaker_and_explains_its_reach():
    html = (STATIC / "board.html").read_text(encoding="utf-8")
    # ボタンの id と文言は変えない（tests/test_auth_ui.py と #17 の動きがこれに頼る）
    assert '<button type="button" id="logout">この端末をログアウト</button>' in html
    m = re.search(r'<button type="button" id="logoutAll" aria-describedby="(\w+)">すべての端末をログアウト</button>', html)
    assert m, "すべての端末のボタンに範囲の説明をつなぐ"
    note = re.search(r'id="' + m.group(1) + r'">([^<]+)<', html).group(1)
    assert "子どもの端末" in note and "すべての端末" in note
    rules = dict(css_rules(html))
    this_device = rules["footer .auth #logout"]
    all_devices = rules["footer .auth #logoutAll"]
    assert "font-weight:700" in this_device and "color:var(--ink)" in this_device
    assert "border-style:dashed" in all_devices and "font-weight:400" in all_devices
    # 全端末は、この端末と並べず、区切ったところに置く
    assert html.index('id="logout"') < html.index('class="auth-all"') < html.index('id="logoutAll"')
    assert "confirm(" in html                       # 全端末の確かめはそのまま
