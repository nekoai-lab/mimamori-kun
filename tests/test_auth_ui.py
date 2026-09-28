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
  const e = { tag, id:'', className:'', textContent:'', type:'', disabled:false, hidden:false, kids:[], attrs:{}, handlers:{}, dataset:{}, style:{},
    setAttribute(k,v){ this.attrs[k]=v; if(k==='id') this.id=v; }, getAttribute(k){ return this.attrs[k]; },
    appendChild(c){ this.kids.push(c); return c; }, insertBefore(c){ this.kids.unshift(c); return c; },
    addEventListener(ev,fn){ (this.handlers[ev]=this.handlers[ev]||[]).push(fn); },
    querySelector(){ return null; }, querySelectorAll(){ return []; }, focus(){}, remove(){} };
  return e;
}
function makeEnv(responses){
  const calls = [];
  const byId = {};
  const doc = {
    head: el('head'), body: el('body'), readyState: 'complete',
    createElement: el, createTextNode: t => ({ tag:'#text', textContent:t }),
    getElementById: id => byId[id] || null, addEventListener(){}, dispatchEvent(){}, querySelector(){ return null; },
    documentElement: { dataset:{} },
  };
  const loc = { href: '/board', pathname: '/board', reload(){ loc.reloaded = true; } };
  const fetch = (url, opts) => {
    calls.push(String(url));
    const r = responses[String(url)];
    const next = Array.isArray(r) ? r.shift() : r;
    if (!next || next === 'network') return Promise.reject(new Error('network'));
    return Promise.resolve({ ok: next.status < 400, status: next.status, headers: { get: () => null },
                             json: () => Promise.resolve(next.body || {}) });
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
    const clicks = [];
    for (let i = 0; i < c.clicks; i++) { btn.handlers.click[0](); await settle();
      clicks.push({ href: env.loc.href, disabled: btn.disabled, label: btn.textContent, err: err.textContent }); }
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
