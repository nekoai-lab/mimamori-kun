"""#16・UX_REVIEW R1・R2：「子どもに戻す」とログアウトは、サーバーが成功を返したときだけ画面を進める。

失敗（500）・通信断では画面に残り、もう一度押せる。who.js と board.html の処理を node の vm で、
小さな作り物の DOM と fetch で動かして確かめる（node が無い環境では飛ばす。GitHub の Ubuntu には入っている）。
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
node = shutil.which("node")
pytestmark = pytest.mark.skipif(node is None, reason="node が無い")

FAKE_DOM = r"""
const vm = require('vm');
function el(tag){
  const e = { tag, id:'', className:'', textContent:'', type:'', disabled:false, hidden:false, kids:[], attrs:{}, handlers:{}, dataset:{},
    setAttribute(k,v){ this.attrs[k]=v; if(k==='id') this.id=v; },
    style:{ setProperty(){} }, getAttribute(k){ return k in this.attrs ? this.attrs[k] : null; }, hasAttribute(k){ return k in this.attrs; },
    appendChild(c){ this.kids.push(c); c.parent=this; return c; }, insertBefore(c){ this.kids.unshift(c); c.parent=this; return c; },
    removeAttribute(k){ delete this.attrs[k]; },
    addEventListener(ev,fn){ (this.handlers[ev]=this.handlers[ev]||[]).push(fn); },
    querySelector(){ return null; }, querySelectorAll(){ return []; }, focus(){},
    remove(){ if (this.parent) { const i = this.parent.kids.indexOf(this); if (i >= 0) this.parent.kids.splice(i, 1); this.parent = null; } },
    get children(){ return this.kids.slice(); } };
  return e;
}
function makeEnv(responses){
  const calls = [];
  const byId = {};
  const doc = {
    head: el('head'), body: el('body'), readyState: 'complete',
    createElement: el, createTextNode: t => ({ tag:'#text', textContent:t }),
    getElementById: id => byId[id] || null, addEventListener(){}, dispatchEvent(){}, querySelector(){ return null; },
    documentElement: el('html'),
  };
  const loc = { href: '/board', pathname: '/board', reload(){ loc.reloaded = true; } };
  const fetch = (url, opts) => {
    calls.push(String(url));
    const r = responses[String(url)];
    const next = Array.isArray(r) ? r.shift() : r;
    if (!next || next === 'network') return Promise.reject(new Error('network'));
    return Promise.resolve({ ok: next.status < 400, status: next.status, headers: { get: () => null },
                             json: () => next.body === 'BAD' ? Promise.reject(new SyntaxError('bad json'))
                                                             : Promise.resolve(next.body === undefined ? {} : next.body) });
  };
  const win = { fetch, location: loc, document: doc, addEventListener(){}, confirm: () => true,
                setInterval: () => 0, clearInterval(){}, CustomEvent: function(n,o){ this.type=n; this.detail=o&&o.detail; },
                localStorage: { getItem: () => null, setItem(){} }, MutationObserver: function(){ this.observe=()=>{}; this.disconnect=()=>{}; } };
  win.window = win;
  return { win, doc, loc, calls, byId };
}
const tick = () => new Promise(r => setTimeout(r, 0));
async function settle(){ for (let i = 0; i < 10; i++) await tick(); }
"""

WHO = FAKE_DOM + r"""
(async () => {
  const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));
  const src = require('fs').readFileSync(process.argv[1], 'utf8');
  const out = [];
  for (const c of cases) {
    const env = makeEnv({ '/api/auth/me': [{ status: 200, body: { role: 'parent', switched: true, back_to: '下の子', auth: true } },
                                          ...(c.me_after || [])],
                          '/api/auth/back': c.back });
    vm.runInNewContext(src, Object.assign(env.win, { Promise, Date, JSON, setTimeout }));
    await settle();
    const bar = env.doc.body.kids.find(k => k.id === 'who-switched');
    const btn = bar.kids.find(k => k.tag === 'button');
    const err = bar.kids.find(k => k.className === 'who-err');
    const unknownBox = () => env.doc.body.kids.find(k => k.id === 'who-unknown');
    const texts = e => (e.textContent || '') + (e.kids || []).map(texts).join('');
    const clicks = [];
    const press = c.press || Array(c.clicks).fill('bar');
    for (const which of press) {
      if (which === 'bar') btn.handlers.click[0]();
      else { const u = unknownBox(); const b = u.kids[0].kids.find(k => k.tag === 'button'); b.handlers.click[0](); }
      await settle();
      const u = unknownBox();
      clicks.push({ href: env.loc.href, disabled: btn.disabled, label: btn.textContent, err: err.textContent,
                    unknown: u ? texts(u) : null,
                    unknown_button: u ? u.kids[0].kids.find(k => k.tag === 'button').disabled : null,
                    covered: env.doc.body.kids.filter(k => k.id !== 'who-unknown').every(k => k.inert === true && k.attrs['aria-hidden'] === 'true') });
    }
    out.push({ clicks, calls: env.calls });
  }
  console.log(JSON.stringify(out));
})();
"""

BOARD = FAKE_DOM + r"""
(async () => {
  const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));
  const html = require('fs').readFileSync(process.argv[1], 'utf8');
  const script = html.match(/<script>\s*\/\* ---- ログアウト（#16） ---- \*\/([\s\S]*?)<\/script>/)[1];
  const out = [];
  for (const c of cases) {
    const env = makeEnv({ '/api/auth/logout': c.logout, '/api/auth/logout_all': c.logout_all });
    for (const id of ['logout', 'logoutAll', 'authMsg']) env.byId[id] = el(id);
    env.win.confirm = () => c.confirm !== false;
    vm.runInNewContext(script, Object.assign(env.win, { Promise, JSON }));
    const steps = [];
    for (const which of c.press) { env.byId[which].handlers.click[0](); await settle();
      steps.push({ href: env.loc.href, msg: env.byId.authMsg.textContent, disabled: env.byId.logout.disabled || env.byId.logoutAll.disabled }); }
    out.push({ steps, calls: env.calls });
  }
  console.log(JSON.stringify(out));
})();
"""


def run(script, target, cases):
    p = subprocess.run([node, "-e", script, str(target)], input=json.dumps(cases, ensure_ascii=False),
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


OK = {"status": 200, "body": {}}
ERR = {"status": 500, "body": {}}


# ---------------------------------------------------------------- R1 子どもに戻す

@pytest.mark.parametrize("failure", [ERR, "network"])
def test_back_to_child_stays_on_failure_and_can_retry(failure):
    out = run(WHO, ROOT / "static" / "who.js", [{"back": [failure, OK], "clicks": 2,
                                                  "me_after": [{"status": 200, "body": {"role": "parent", "switched": True}}]}])[0]
    first, second = out["clicks"]
    assert first["href"] == "/board"                                  # 進まない
    assert "まだ子どもの画面に戻せていません" in first["err"]
    assert first["disabled"] is False and first["label"] == "子どもに戻す"   # もう一度押せる
    assert second["href"] == "/kid"                                   # 成功したら進む
    assert out["calls"].count("/api/auth/back") == 2


def test_back_to_child_goes_on_when_the_server_already_went_back():
    """401 などでも、今の状態が子どもなら子どもの画面へ（サーバー側で先に戻っていた場合）。"""
    out = run(WHO, ROOT / "static" / "who.js", [{"back": [{"status": 401, "body": {}}], "clicks": 1,
                                                  "me_after": [{"status": 200, "body": {"role": "child", "switched": False}}]}])[0]
    assert out["clicks"][0]["href"] == "/kid"


# R1 追補：戻す操作も、今の状態の確認（/api/auth/me）も失敗したとき
PARENT = {"status": 200, "body": {"role": "parent", "switched": True, "back_to": "下の子"}}
CHILD = {"status": 200, "body": {"role": "child", "switched": False}}


@pytest.mark.parametrize("back_failure", [ERR, "network", {"status": 401, "body": {}}])
@pytest.mark.parametrize("me_failure", [ERR, "network", {"status": 200, "body": "BAD"}, {"status": 200, "body": None},
                                        {"status": 200, "body": {"ok": True}}])
def test_back_and_me_both_fail_closes_parent_screen_and_can_recheck(back_failure, me_failure):
    """戻れたか分からないときは、親のまま使える状態にしない。画面全体をおおい、もう一度たしかめられる。"""
    out = run(WHO, ROOT / "static" / "who.js", [{"back": [back_failure, "network"], "press": ["bar", "unknown"],
                                                  "me_after": [me_failure, CHILD]}])[0]
    first, second = out["clicks"]
    assert first["href"] == "/board"                                  # ログイン画面にも子どもの画面にも進まない
    assert "確認できませんでした" in first["unknown"]
    assert first["covered"] is True                                   # 後ろの親の画面は操作できない
    assert first["unknown_button"] is False                           # もう一度たしかめられる
    assert second["href"] == "/kid"                                   # 確かめて子どもなら子どもの画面へ
    assert out["calls"].count("/api/auth/me") == 3


def test_recheck_that_still_fails_keeps_the_screen_closed():
    out = run(WHO, ROOT / "static" / "who.js", [{"back": ["network", "network"], "press": ["bar", "unknown"],
                                                  "me_after": [ERR, "network"]}])[0]
    for step in out["clicks"]:
        assert step["href"] == "/board" and step["covered"] is True and "確認できませんでした" in step["unknown"]


def test_recheck_that_finds_parent_opens_the_bar_again():
    """確かめて、まだ親のままと分かったら、幕を外して親の帯でやり直せるようにする。"""
    out = run(WHO, ROOT / "static" / "who.js", [{"back": ["network", "network"], "press": ["bar", "unknown"],
                                                  "me_after": [ERR, PARENT]}])[0]
    second = out["clicks"][1]
    assert second["unknown"] is None and second["covered"] is False
    assert "まだ子どもの画面に戻せていません" in second["err"] and second["disabled"] is False


@pytest.mark.parametrize("back_failure", [ERR, "network", {"status": 401, "body": {}}])
def test_back_fails_and_me_401_goes_to_login(back_failure):
    """ログインが切れていると確かめられたときだけ、ログイン画面へ。"""
    out = run(WHO, ROOT / "static" / "who.js", [{"back": [back_failure], "clicks": 1,
                                                  "me_after": [{"status": 401, "body": {}}]}])[0]
    assert out["clicks"][0]["href"] == "/login"


def test_switched_bar_is_built_without_html():
    src = (ROOT / "static" / "who.js").read_text(encoding="utf-8")
    body = src[src.index("function showSwitched"):src.index("function showParentEntry")]
    assert "innerHTML" not in body


# ---------------------------------------------------------------- R2 ログアウト

@pytest.mark.parametrize("which,path,scope", [("logout", "logout", "この端末"), ("logoutAll", "logout_all", "すべての端末")])
@pytest.mark.parametrize("failure", [ERR, "network"])
def test_logout_stays_on_failure_and_can_retry(which, path, scope, failure):
    out = run(BOARD, ROOT / "static" / "board.html", [{path: [failure, OK], "press": [which, which]}])[0]
    first, second = out["steps"]
    assert first["href"] == "/board" and scope in first["msg"] and first["disabled"] is False
    assert second["href"] == f"/login?done={path}"


def test_logout_all_cancelled_sends_nothing():
    out = run(BOARD, ROOT / "static" / "board.html", [{"logout_all": [OK], "press": ["logoutAll"], "confirm": False}])[0]
    assert out["calls"] == [] and out["steps"][0]["href"] == "/board"
