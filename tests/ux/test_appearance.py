"""UX 塊 A：見た目の共通基盤（design/UX_SPEC.md §3.1〜§3.4・§4.2）。

- appearance.css：3テーマ×明暗の6組と親の色が仕様の表どおりで、文字 4.5:1・操作 3:1 を満たす
- appearance.js：子の切替で前の子の応答が混ざらない。保存に失敗したら保存できたふりをしない。
  知らない ID は中立。テーマの保存は名前・学年を送らない（部分更新）。差込先がない画面では何もしない。
  親の画面には子のテーマを付けない。ナビは子・親で決まった順に並ぶ
node の vm で、小さな作り物の DOM と fetch で動かす（node が無い環境では飛ばす）。
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "static"
CSS = (STATIC / "appearance.css").read_text(encoding="utf-8")

# §3.2 の色の表（bg, text, accent, card, done, on-accent, muted）
KID = {
    ("rocket-lab", "light"): "#F3F7FF #152744 #2454B8 #FFFFFF #17664D #FFFFFF #4C5F7A",
    ("rocket-lab", "dark"): "#101A2D #F2F6FF #9DBDFF #1D2B45 #83D9B6 #101A2D #B6C6E0",
    ("monochrome", "light"): "#F5F5F5 #202124 #292929 #FFFFFF #414141 #FFFFFF #606166",
    ("monochrome", "dark"): "#151515 #F2F2F2 #E8E8E8 #242424 #D4D4D4 #151515 #BDBDBD",
    ("snow-bird", "light"): "#F1F7FA #243541 #326474 #FFFFFF #386653 #FFFFFF #526675",
    ("snow-bird", "dark"): "#17232C #F1F7FB #A4CFDF #253540 #A1D4BC #17232C #BDCFDC",
}
KID_VARS = ["--kid-bg", "--kid-text", "--kid-accent", "--kid-card", "--kid-done", "--kid-on-accent", "--kid-muted"]
# §3.1（bg, text, muted, card, accent, warning, line）
PARENT = {
    "light": "#F5F5F7 #1D1D1F #5C5C63 #FFFFFF #005FCC #984A13 #D7D7DC",
    "dark": "#111113 #F5F5F7 #B8B8C0 #202024 #88B8FF #FFBD8A #45454C",
}
PARENT_VARS = ["--parent-bg", "--parent-text", "--parent-muted", "--parent-card", "--parent-accent", "--parent-warning", "--parent-line"]


def block(selector_start):
    """selector_start で始まる規則の宣言を dict で返す。"""
    m = re.search(r"(?m)^" + re.escape(selector_start) + r"[^{]*\{([^}]*)\}", CSS)
    assert m, selector_start
    return dict((k.strip(), v.strip()) for k, v in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", m.group(1)))


def lum(hexcolor):
    c = [int(hexcolor[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a, b):
    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


# ---------------------------------------------------------------- 色

@pytest.mark.parametrize("theme,mode", list(KID))
def test_kid_theme_colors_match_spec_and_contrast(theme, mode):
    sel = f'[data-kid-theme="{theme}"]' if mode == "light" else f'[data-theme="dark"][data-kid-theme="{theme}"]'
    got = block(sel)
    want = dict(zip(KID_VARS, KID[(theme, mode)].split()))
    for k, v in want.items():
        assert got[k].upper() == v, (theme, mode, k)
    bg, text, accent, card, done, on, muted = KID[(theme, mode)].split()
    for fg, back in [(text, bg), (text, card), (muted, bg), (muted, card), (on, accent)]:
        assert contrast(fg, back) >= 4.5, (theme, mode, fg, back)      # 文字
    for fg, back in [(accent, bg), (accent, card), (done, bg), (done, card)]:
        assert contrast(fg, back) >= 3, (theme, mode, fg, back)        # 操作・意味のある印


def test_dark_rules_also_apply_inside_the_preview():
    """シートのプレビュー（子要素の data-kid-theme）も暗い画面で暗い色になる。"""
    for theme, _ in KID:
        assert f'[data-theme="dark"] [data-kid-theme="{theme}"]' in CSS


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_parent_colors_match_spec_and_contrast(mode):
    got = block('[data-audience="parent"]') if mode == "light" else block('[data-theme="dark"][data-audience="parent"]')
    want = dict(zip(PARENT_VARS, PARENT[mode].split()))
    for k, v in want.items():
        assert got[k].upper() == v, (mode, k)
    bg, text, muted, card, accent, warn, _ = PARENT[mode].split()
    for fg in (text, muted, accent, warn):
        assert contrast(fg, bg) >= 4.5 and contrast(fg, card) >= 4.5, (mode, fg)


def test_kid_colors_only_replace_page_vars_when_kid_and_themed():
    """子の色を :root の既存の色へ無条件に上書きしない（§3.3）。テーマ未設定の子は元の色のまま。"""
    assert re.search(r'html:root\[data-audience="kid"\]\[data-kid-theme\][^{]*\{[^}]*--paper:\s*var\(--kid-bg\)', CSS)
    assert not re.search(r'(^|\n):root\s*\{', CSS)


def test_pages_outside_the_units_do_not_load_appearance():
    """/plan・/schedule は theme.js だけで明暗が動く（A を読まない）。"""
    for page in ("plan.html", "schedule.html"):
        html = (STATIC / page).read_text(encoding="utf-8")
        assert "/static/theme.js" in html and "appearance" not in html
    theme = (STATIC / "theme.js").read_text(encoding="utf-8")
    assert "kid-theme" not in theme and "mimamori-theme" in theme


def test_assets_exist_and_are_ours():
    for name in ("rocket-lab", "monochrome", "snow-bird"):
        for f in (f"{name}.svg", f"stamp-{name}.svg"):
            svg = (STATIC / "assets" / "appearance" / f).read_text(encoding="utf-8")
            assert svg.lstrip().startswith("<svg") and "<script" not in svg and "href=" not in svg


# ---------------------------------------------------------------- appearance.js

node = shutil.which("node")
needs_node = pytest.mark.skipif(node is None, reason="node が無い")

DOM = r"""
const vm = require('vm');
function matches(e, sel){
  const m = sel.match(/^([a-z]+)?((?:\.[\w-]+)*)((?:\[[\w-]+\])*)$/);
  if (!m) throw new Error('selector ' + sel);
  if (m[1] && e.tag !== m[1]) return false;
  for (const c of (m[2] || '').split('.').filter(Boolean)) if (!e.classList.contains(c)) return false;
  for (const a of (m[3] || '').match(/[\w-]+/g) || []) if (!(a in e.attrs)) return false;
  return true;
}
function el(tag){
  const e = { tag, kids:[], attrs:{}, handlers:{}, dataset:{}, style:{ props:{}, setProperty(k,v){ this.props[k]=v; } }, parent:null,
    textContent:'', hidden:false, type:'', isConnected:true,
    classList:{ set:new Set(), add(c){ this.set.add(c); }, contains(c){ return this.set.has(c); }, remove(c){ this.set.delete(c); } },
    get className(){ return [...this.classList.set].join(' '); }, set className(v){ this.classList.set = new Set(String(v).split(/\s+/).filter(Boolean)); },
    get id(){ return this.attrs.id || ''; }, set id(v){ this.attrs.id = v; },
    get href(){ return this.attrs.href || ''; }, set href(v){ this.attrs.href = v; },
    get src(){ return this.attrs.src || ''; }, set src(v){ this.attrs.src = v; },
    get tagName(){ return this.tag.toUpperCase(); }, get firstChild(){ return this.kids[0] || null; }, get children(){ return this.kids.slice(); },
    setAttribute(k,v){ this.attrs[k]=String(v); }, getAttribute(k){ return k in this.attrs ? this.attrs[k] : null; },
    hasAttribute(k){ return k in this.attrs; }, removeAttribute(k){ delete this.attrs[k]; },
    appendChild(c){ if (c.parent) c.remove(); this.kids.push(c); c.parent=this; return c; },
    insertBefore(c, ref){ if (c.parent) c.remove(); const i = ref ? this.kids.indexOf(ref) : -1; if (i<0) this.kids.push(c); else this.kids.splice(i,0,c); c.parent=this; return c; },
    replaceChildren(...cs){ this.kids.forEach(k=>k.parent=null); this.kids=[]; cs.forEach(c=>this.appendChild(c)); },
    remove(){ if (this.parent){ const p=this.parent; p.kids.splice(p.kids.indexOf(this),1); this.parent=null; } },
    addEventListener(ev,fn){ (this.handlers[ev]=this.handlers[ev]||[]).push(fn); },
    click(){ (this.handlers.click||[]).forEach(f=>f()); },
    focus(){ doc.activeElement = this; },
    all(){ return this.kids.flatMap(k => [k, ...(k.all ? k.all() : [])]); },
    querySelectorAll(sel){ const parts = sel.split(',').map(s=>s.trim()); return this.all().filter(x => x.tag && parts.some(p=>matches(x,p))); },
    querySelector(sel){ return this.querySelectorAll(sel)[0] || null; },
  };
  return e;
}
let doc;
function makeEnv(opts){
  const calls = [], pending = [];
  const html = el('html'), body = el('body');
  html.appendChild(body);
  doc = { documentElement: html, body, readyState:'complete', activeElement:null,
    createElement: el, createTextNode: t => ({ tag:null, textContent:t, kids:[] }),
    querySelectorAll: s => html.querySelectorAll(s), querySelector: s => html.querySelector(s),
    addEventListener(ev, fn){ (doc.h = doc.h || {})[ev] = fn; } };
  for (const [k,v] of Object.entries(opts.htmlAttrs || {})) html.setAttribute(k, v);
  for (const slot of opts.slots || []) { const s = el(slot.tag || 'span'); s.setAttribute(slot.attr, ''); for (const k of slot.kids || []) { const c = el(k.tag); if (k.href) c.href = k.href; if (k.id) c.id = k.id; c.textContent = k.text || ''; s.appendChild(c); } body.appendChild(s); }
  const store = {};
  // fetch：opts.api(url, body) が {status, body} か 'hold'（あとで解決）を返す
  const fetch = (url, o) => {
    const payload = o && o.body ? JSON.parse(o.body) : null;
    calls.push({ url: String(url), method: (o && o.method) || 'GET', payload });
    const r = opts.api(String(url), payload);
    const respond = x => ({ ok: x.status < 400, status: x.status, json: () => x.body === 'BAD' ? Promise.reject(new Error('bad')) : Promise.resolve(x.body) });
    if (r === 'hold') return new Promise((res, rej) => pending.push({ url: String(url), payload, res: x => res(respond(x)), rej }));
    if (r === 'network') return Promise.reject(new TypeError('network'));
    return Promise.resolve(respond(r));
  };
  const win = { fetch, document: doc, location: { href: 'http://x' + (opts.path || '/kid'), pathname: opts.path || '/kid' },
    URL, JSON, Promise, localStorage: { getItem: k => k in store ? store[k] : null, setItem: (k,v) => { store[k] = String(v); }, removeItem: k => { delete store[k]; } } };
  win.window = win;
  return { win, doc, html, body, calls, pending, store };
}
const settle = async () => { for (let i = 0; i < 20; i++) await new Promise(r => setTimeout(r, 0)); };
"""

RUN = DOM + r"""
(async () => {
  const src = require('fs').readFileSync(process.argv[1], 'utf8');
  const scenario = require('fs').readFileSync(0, 'utf8');
  const out = await eval('(async () => {' + scenario + '})()');
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""


def run(scenario):
    p = subprocess.run([node, "-e", RUN, str(STATIC / "appearance.js")], input=scenario, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


LOAD = "const env = makeEnv(OPTS); vm.runInNewContext(src, env.win); const A = env.win.Appearance; await settle();\n"


def scenario(opts, body):
    return "const OPTS = " + opts + ";\n" + LOAD + body


@needs_node
def test_no_slots_no_audience_does_nothing():
    out = run(scenario("{ api: () => ({status: 500, body: {}}) }",
                       "return { theme: env.html.getAttribute('data-kid-theme'), calls: env.calls.length, kids: env.body.kids.length };"))
    assert out == {"theme": None, "calls": 0, "kids": 0}


@needs_node
def test_switching_child_ignores_the_previous_childs_late_answer():
    out = run(scenario(
        "{ htmlAttrs: {'data-audience': 'kid'}, api: (url) => url.includes('child=%E5%85%84') ? 'hold' : {status: 200, body: {settings: {theme_id: 'snow-bird'}}} }",
        """
        A.setChild('兄');                    // 兄の設定は遅れて返る
        await settle();
        await A.setChild('弟');             // 弟は snow-bird
        const mid = env.html.getAttribute('data-kid-theme');
        env.pending[0].res({status: 200, body: {settings: {theme_id: 'monochrome'}}});
        await settle();
        return { mid, after: env.html.getAttribute('data-kid-theme'), cur: A.current() };
        """))
    assert out["mid"] == "snow-bird" and out["after"] == "snow-bird" and out["cur"]["child"] == "弟"


@needs_node
def test_unknown_theme_id_is_neutral_and_not_rewritten():
    out = run(scenario(
        "{ htmlAttrs: {'data-audience': 'kid'}, api: () => ({status: 200, body: {settings: {theme_id: 'dino-2030', companion_name: 'ぴよ'}}}) }",
        "await A.setChild('弟'); return { theme: env.html.getAttribute('data-kid-theme'), writes: env.calls.filter(c => c.method === 'POST').length };"))
    assert out == {"theme": None, "writes": 0}


@needs_node
def test_write_failure_does_not_pretend_it_was_saved_and_can_retry():
    out = run(scenario(
        "{ htmlAttrs: {'data-audience': 'kid'}, slots: [{attr: 'data-appearance-picker'}], "
        "api: (url, p) => p ? (globalThis.fail = (globalThis.fail || 0) + 1) <= 1 ? {status: 500, body: {}} : {status: 200, body: {settings: {theme_id: p.theme_id}}} "
        ": {status: 200, body: {settings: {theme_id: 'rocket-lab'}}} }",
        """
        await A.setChild('弟');
        const ok1 = await A._commit('monochrome');
        const slot = env.body.querySelector('[data-appearance-picker]');
        const status = slot.querySelector('.ap-status');
        const text1 = status.kids.map(k => k.textContent).join('');
        const shown = env.html.getAttribute('data-kid-theme'), saved1 = A.current().saved, cache1 = env.store['mimamori-appearance:弟'];
        status.querySelector('button').click();              // もういちど
        await settle();
        return { ok1, text1, shown, saved1, cache1, saved2: A.current().saved, status2: A.current().status,
                 cache2: env.store['mimamori-appearance:弟'] };
        """))
    assert out["ok1"] is False and "まだ覚えられていない" in out["text1"]
    assert out["shown"] == "monochrome"                      # この画面では変わる
    assert out["saved1"] == "rocket-lab" and out["cache1"] == "rocket-lab"   # 覚えたことにしない
    assert out["saved2"] == "monochrome" and out["status2"] == "saved" and out["cache2"] == "monochrome"


@needs_node
def test_unconnected_store_is_not_saved():
    """設定の口（塊 F）がまだない（404）ときは、保存できたと言わない。"""
    out = run(scenario(
        "{ htmlAttrs: {'data-audience': 'kid'}, slots: [{attr: 'data-appearance-picker'}], api: () => ({status: 404, body: {}}) }",
        "await A.setChild('弟'); const ok = await A._commit('snow-bird'); return { ok, cur: A.current(), cache: env.store['mimamori-appearance:弟'] || null };"))
    assert out["ok"] is False and out["cur"]["status"] == "failed" and out["cur"]["saved"] is None and out["cache"] is None


@needs_node
def test_theme_write_sends_only_theme_fields_and_name_write_only_name():
    out = run(scenario(
        "{ htmlAttrs: {'data-audience': 'kid'}, api: (url, p) => ({status: 200, body: {settings: Object.assign({theme_id: 'rocket-lab'}, p || {})}}) }",
        """
        await A.setChild('弟');
        await A._commit('snow-bird');
        await env.win.CompanionStore.write('弟', {companion_name: 'ぴよ', theme_id: 'monochrome', school_grade: 3});
        return env.calls.filter(c => c.method === 'POST').map(c => Object.keys(c.payload).sort());
        """))
    assert out == [["child", "theme_id", "theme_schema_version"], ["child", "companion_name"]]


@needs_node
def test_parent_pages_do_not_take_the_kid_theme():
    out = run(scenario(
        "{ htmlAttrs: {'data-audience': 'parent'}, slots: [{attr: 'data-appearance-picker'}], api: () => ({status: 200, body: {settings: {theme_id: 'snow-bird'}}}) }",
        "await A.setChild('弟'); return { theme: env.html.getAttribute('data-kid-theme'), hidden: env.body.querySelector('[data-appearance-picker]').hidden };"))
    assert out == {"theme": None, "hidden": True}


@needs_node
def test_cached_theme_is_used_only_until_the_setting_answers():
    out = run(scenario(
        "{ htmlAttrs: {'data-audience': 'kid'}, api: () => 'hold' }",
        """
        env.store['mimamori-appearance:弟'] = 'monochrome';
        A.setChild('弟'); await settle();
        const during = env.html.getAttribute('data-kid-theme');
        env.pending[0].res({status: 200, body: {settings: {}}}); await settle();
        return { during, after: env.html.getAttribute('data-kid-theme'), cache: env.store['mimamori-appearance:弟'] || null };
        """))
    assert out == {"during": "monochrome", "after": None, "cache": None}


@needs_node
@pytest.mark.parametrize("who,path,labels,current", [
    ("kid", "/kid", ["きょう", "とる", "ごほうび"], "きょう"),
    ("kid", "/", ["きょう", "とる", "ごほうび"], "とる"),
    ("parent", "/", ["一覧", "撮る", "ごほうび", "予定表"], "撮る"),
])
def test_family_nav_order_and_current(who, path, labels, current):
    out = run(scenario(
        "{ path: '" + path + "', htmlAttrs: {'data-audience': '" + who + "'}, api: () => ({status: 404, body: {}}), "
        "slots: [{tag: 'nav', attr: 'data-family-nav', kids: [{tag: 'a', href: '/', text: '撮る'}, {tag: 'a', href: '/schedule', text: '予定表'}, "
        "{tag: 'a', href: '/kid', text: 'きょう'}, {tag: 'button', id: 'theme', text: '暗く'}]}] }",
        """
        const nav = env.body.querySelector('[data-family-nav]');
        return { shown: nav.kids.filter(k => k.tag === 'a' && !k.hidden).map(k => k.textContent),
                 current: nav.kids.filter(k => k.getAttribute('aria-current') === 'page' && !k.hidden).map(k => k.textContent),
                 button: !!nav.querySelector('button') };
        """))
    assert out["shown"] == labels and out["current"] == [current] and out["button"] is True


@needs_node
def test_profile_menu_shows_own_name_and_parent_entry():
    out = run(scenario(
        "{ htmlAttrs: {'data-audience': 'kid'}, api: () => ({status: 404, body: {}}), "
        "slots: [{tag: 'details', attr: 'data-profile-menu', kids: [{tag: 'summary', id: 'child-name', text: '下の子'}, {tag: 'div'}]}] }",
        """
        env.win.mimamoriMe = {role: 'child', name: '下の子', auth: true, switched: false};
        A.refresh();
        const d = env.body.querySelector('[data-profile-menu]');
        return { summary: d.querySelector('summary').textContent, id: d.querySelector('summary').id,
                 links: d.querySelectorAll('a').map(a => [a.textContent, a.href]), selects: d.querySelectorAll('select').length };
        """))
    assert out["summary"] == "下の子" and out["id"] == "child-name" and out["selects"] == 0
    assert out["links"] == [["おうちの人に かわる", "/login?switch=parent&next=%2Fboard"]]


# ---------------------------------------------------------------- who.js（A が変えた本物のファイル）
#
# 以前直した穴を、本物の who.js で確かめ直す（kid.html・index.html のテストは who.js の代わりを使っている）
#   - 子が決まる前に読み込みを始めない：select が埋まるまで who:ready を出さず、決まってから1回だけ出す
#   - 通信に失敗しても親のままにしない：/api/auth/me が取れなければ親子（data-audience）を付けない

WHO_RUN = DOM + r"""
(async () => {
  const src = require('fs').readFileSync(process.argv[1], 'utf8');
  const c = JSON.parse(require('fs').readFileSync(0, 'utf8'));
  const env = makeEnv({ htmlAttrs: c.htmlAttrs || {}, slots: c.slots || [],
    api: url => url === '/api/auth/me' ? c.me : ({status: 404, body: {}}) });
  const head = el('head'); env.html.appendChild(head); env.doc.head = head;
  const select = el('select'); select.id = 'child'; select.options = []; select.value = '';
  const events = [];
  select.dispatchEvent = e => { events.push([e.type, select.value]); (select.handlers[e.type] || []).forEach(f => f(e)); };
  if (c.select) env.body.appendChild(select);
  env.doc.getElementById = id => id === 'child' && c.select ? select : null;
  env.doc.dispatchEvent = () => {};
  let observer = null;
  if (c.saved) env.store['mimamori-child'] = c.saved;
  Object.assign(env.win, {
    Event: function (t) { this.type = t; }, CustomEvent: function (t, o) { this.type = t; this.detail = o && o.detail; },
    MutationObserver: function (cb) { observer = this; this.cb = cb; this.observe = () => {}; this.disconnect = () => { this.off = true; }; },
    setTimeout, setInterval: () => 0, addEventListener() {}, matchMedia: () => ({ matches: false, addEventListener() {} }),
  });
  if (c.appearance) env.win.Appearance = {};
  vm.runInNewContext(src, env.win);
  await settle();
  env.doc.h.DOMContentLoaded();                 // 画面の読み込みが終わった（select はまだ空）
  await settle();
  const before = events.slice();
  for (const name of c.fill || []) { const o = el('option'); o.value = name; o.textContent = name; select.options.push(o); }
  if (observer && !observer.off) observer.cb();  // 画面が /api/config のあとで select を埋めた
  await settle();
  console.log(JSON.stringify({ before, events, ready: select.dataset ? select.dataset.whoReady || null : null,
    audience: env.html.getAttribute('data-audience'), role: env.html.dataset ? env.html.dataset.role || null : null,
    parentEntry: !!env.body.kids.find(k => k.id === 'who-parent'), bar: !!env.body.kids.find(k => k.id === 'who-switched') }));
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""


def run_who(case):
    p = subprocess.run([node, "-e", WHO_RUN, str(STATIC / "who.js")], input=json.dumps(case, ensure_ascii=False),
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


CHILD_ME = {"status": 200, "body": {"role": "child", "name": "下の子", "auth": True, "switched": False}}


@needs_node
def test_who_waits_for_the_child_list_before_ready():
    """子が決まる前に読み込みを始めない（#9 の穴）。覚えている子を入れてから who:ready を1回だけ出す。"""
    out = run_who({"me": CHILD_ME, "select": True, "fill": ["上の子", "下の子"], "saved": "下の子"})
    assert out["before"] == []
    assert out["events"] == [["change", "下の子"], ["who:ready", "下の子"]]


@needs_node
@pytest.mark.parametrize("me", [{"status": 500, "body": {}}, "network", {"status": 401, "body": {}}])
def test_who_does_not_decide_parent_when_me_fails(me):
    """/api/auth/me が取れないときは、親子を付けない（親のまま使える状態にしない）。親への入口も帯も出さない。"""
    out = run_who({"me": me})
    assert out["audience"] is None and out["role"] is None and not out["parentEntry"] and not out["bar"]


@needs_node
@pytest.mark.parametrize("given,appearance,profile,entry", [
    (None, False, False, True),       # A がない画面：下に「おうちの人に かわる」
    (None, True, True, False),        # プロフィールのある画面：入口はプロフィールの中（appearance.js）
    ("parent", False, False, True),   # 画面が決めた親子はそのまま
])
def test_who_sets_audience_from_login_and_places_parent_entry(given, appearance, profile, entry):
    case = {"me": CHILD_ME, "appearance": appearance,
            "htmlAttrs": {"data-audience": given} if given else {},
            "slots": [{"attr": "data-profile-menu"}] if profile else []}
    out = run_who(case)
    assert out["audience"] == (given or "kid") and out["role"] == "child" and out["parentEntry"] is entry


# ---------------------------------------------------------------- PR-34 のレビューで直したもの

@needs_node
@pytest.mark.parametrize("post", ["ok", "fail"])
def test_late_setting_never_undoes_the_theme_the_child_just_chose(post):
    """A3：設定の取得が遅れているあいだに選んだら、あとで届いた古い設定で戻さない（最後に選んだものが勝つ）。"""
    out = run(scenario(
        "{ htmlAttrs: {'data-audience': 'kid'}, slots: [{attr: 'data-appearance-picker'}], "
        "api: (url, p) => p ? " + ("{status: 200, body: {settings: {theme_id: p.theme_id}}}" if post == "ok" else "{status: 500, body: {}}") + " : 'hold' }",
        """
        A.setChild('弟'); await settle();                 // 取得は保留
        await A._commit('monochrome');                    // 本人が選んで「これにする」
        env.pending[0].res({status: 200, body: {settings: {theme_id: 'rocket-lab'}}});   // 古い設定が遅れて届く
        await settle();
        const status = env.body.querySelector('.ap-status-text').textContent;
        return { theme: env.html.getAttribute('data-kid-theme'), cur: A.current(), cache: env.store['mimamori-appearance:弟'] || null, status };
        """))
    assert out["theme"] == "monochrome" and out["cur"]["theme"] == "monochrome"
    if post == "ok":
        assert out["cur"]["saved"] == "monochrome" and out["cache"] == "monochrome" and out["status"] == "このみためを おぼえたよ"
    else:   # この画面では変えた、を古い設定で取り消さない。覚えたことにもしない
        assert out["cur"]["status"] == "failed" and out["cur"]["saved"] is None and out["cache"] is None
        assert "まだ覚えられていない" in out["status"]


@needs_node
def test_switching_child_still_drops_the_old_childs_answer_after_a_choice():
    out = run(scenario(
        "{ htmlAttrs: {'data-audience': 'kid'}, api: (url, p) => p ? {status: 200, body: {settings: {theme_id: p.theme_id}}} : url.includes('%E5%85%84') ? 'hold' : {status: 200, body: {settings: {theme_id: 'snow-bird'}}} }",
        """
        A.setChild('兄'); await settle(); await A._commit('monochrome');
        await A.setChild('弟');
        env.pending[0].res({status: 200, body: {settings: {theme_id: 'rocket-lab'}}}); await settle();
        return { theme: env.html.getAttribute('data-kid-theme'), child: A.current().child };
        """))
    assert out == {"theme": "snow-bird", "child": "弟"}


RETRY = """
        await A.setChild('弟');
        await A._commit('snow-bird');                                   // 1回目は失敗
        const slot = env.body.querySelector('[data-appearance-picker]');
        const again = slot.querySelector('.ap-retry'), msg = slot.querySelector('.ap-status-text');
        again.focus(); again.click(); await settle();
        const waiting = env.doc.activeElement === msg && again.hidden;
        MOVE
        env.pending[env.pending.length - 1].res(RESULT); await settle();
        const a = env.doc.activeElement;
        return { waiting, focus: a === again ? 'retry' : a === msg ? 'message' : a && a.textContent, retryShown: !again.hidden, text: msg.textContent };
"""


def retry_case(result, move=""):
    api = "{ htmlAttrs: {'data-audience': 'kid'}, slots: [{attr: 'data-appearance-picker'}], api: (url, p) => p ? ((globalThis.n = (globalThis.n || 0) + 1) === 1 ? {status: 500, body: {}} : 'hold') : {status: 200, body: {settings: {}}} }"
    return run(scenario(api, RETRY.replace("MOVE", move).replace("RESULT", result)))


@needs_node
def test_retry_keeps_focus_on_the_message_then_on_the_next_retry_when_it_fails_again():
    """A2：「もういちど」を押しても、フォーカスが外れない。再失敗なら新しい「もういちど」へ。"""
    out = retry_case("{status: 500, body: {}}")
    assert out["waiting"] is True and out["focus"] == "retry" and out["retryShown"] is True
    assert "まだ覚えられていない" in out["text"]


@needs_node
def test_retry_success_leaves_focus_on_the_result_message():
    out = retry_case("{status: 200, body: {settings: {theme_id: 'snow-bird'}}}")
    assert out["waiting"] is True and out["focus"] == "message" and out["text"] == "このみためを おぼえたよ" and out["retryShown"] is False


@needs_node
def test_retry_does_not_take_focus_back_after_the_child_moved_on():
    out = retry_case("{status: 500, body: {}}", move="const other = el('button'); other.textContent = 'べつの操作'; env.body.appendChild(other); other.focus();")
    assert out["focus"] == "べつの操作"


def test_theme_cards_wrap_instead_of_overflowing():
    """A1：絵と説明を横に固定しない。狭い幅・文字拡大では上下に並ぶ（ブラウザの 320px・文字200% でも確かめる）。"""
    card = re.search(r"\.ap-choice \{([^}]*)\}", CSS).group(1)
    assert "flex-wrap: wrap" in card and "min-width: 0" in card and "grid-template-columns: 96px" not in CSS
    assert re.search(r"\.ap-choice > \.ap-info \{[^}]*min-width: 0", CSS)
    assert re.search(r"\.ap-mini \{[^}]*flex-wrap: wrap", CSS)


def test_preview_sample_card_wraps_instead_of_squeezing_the_task_name():
    """A1追補：「試す」の見本カードも、320px・文字200% で横にはみ出さず、タスク名が1文字ずつ縦に並ばない。

    ブラウザでの実測（320×568・375×667・390×844 の文字200%、3テーマ適用済み、PC）は PR #34 に記録。
    ここでは、その結果を支える作りを守る：カードは折り返す・親より広がらない、タスク名は最低幅を持つ。
    """
    card = re.search(r"\.ap-preview \.ap-card \{([^}]*)\}", CSS).group(1)
    assert "flex-wrap: wrap" in card and "min-width: 0" in card and "max-width: 100%" in card
    name = re.search(r"\.ap-preview \.ap-card \.ap-card-name \{([^}]*)\}", CSS).group(1)
    assert "min-width: min(5em, 100%)" in name and "word-break: keep-all" in name and "overflow-wrap: anywhere" in name
    js = (STATIC / "appearance.js").read_text(encoding="utf-8")
    assert 'text("span", "ap-card-name", "きょうの ドリル")' in js
