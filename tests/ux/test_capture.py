"""Issue #23: HTML契約と、ブラウザ不要のJS状態遷移テスト。

DOM・fetch・Appearanceのスタブはこのファイルだけに置く。
外部API、モデル、GCPには接続しない。見た目と実機の操作は別担当の検証対象。
"""
import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

HTML = (Path(__file__).resolve().parents[2] / "static/index.html").read_text()
SCRIPT = re.search(r"<script>\s*(.*?)</script>", HTML, re.S).group(1)


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.feed(HTML)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def test_shared_contracts_and_accessible_fallback():
    tags = Elements().tags
    scripts = [a["src"] for t, a in tags if t == "script" and "src" in a]
    assert scripts == ["/static/theme.js", "/static/who.js", "/static/appearance.js"]
    assert HTML.index('/static/theme.js') < HTML.index('/static/appearance.css')
    assert HTML.index('id="completion"') < HTML.index('/static/appearance.js')
    for slot in ("data-family-nav", "data-profile-menu", "data-appearance-picker"):
        assert any(slot in a for _, a in tags)
    ids = [a["id"] for _, a in tags if "id" in a]
    assert len(ids) == len(set(ids))
    by_id = {a["id"]: (t, a) for t, a in tags if "id" in a}
    assert by_id["child"][0] == "select"
    assert by_id["note"][1]["role"] == "status"
    assert by_id["file"][1]["capture"] == "environment"
    assert "capture" not in by_id["album"][1]
    assert by_id["photo-dialog"][0] == "dialog"
    assert 'prefers-reduced-motion:reduce' in HTML
    assert 'max-width:100%' in HTML


def test_normal_screen_has_no_english_tagline():
    assert "SCHOOL NOTICE" not in HTML


def test_login_and_who_are_the_only_identity_inputs():
    assert 'fetch("/api/auth/me")' in SCRIPT
    assert 'me.role === "child"' in SCRIPT
    for forbidden in ("URLSearchParams", "localStorage", "?mode=", "data-c=", 'id="who-back"'):
        assert forbidden not in SCRIPT
    for event in ('"who:ready"', '"change"'):
        assert f'$("#child").addEventListener({event}, selectedChild)' in SCRIPT
    assert 'source: isKid() ? "kid" : "parent"' in SCRIPT
    assert 'source: "parent"' not in SCRIPT
    assert '確度 ' not in SCRIPT
    assert 'd.trace' not in SCRIPT
    assert '20秒' not in SCRIPT


# 小さなDOM代替。描画の正しさはHTML検査、業務の分岐は実際のページJSで検査する。
HARNESS = r'''
const assert = require('node:assert/strict');
const nodes = new Map(), calls = [], routes = new Map(), timers = new Map();
let timerId = 0, authValue = AUTH, configStatus = 200;
const navigations = [];
class Element {
  constructor(id='') {
    this.id=id; this.dataset={}; this.style={}; this.value=''; this.textContent='';
    this.hidden=false; this.disabled=false; this.isConnected=true;
    this.listeners={}; this.children=[]; this.buttons=[]; this.attrs={}; this._html='';
  }
  set innerHTML(value) {
    this._html=value; this.children=[];
    for(const m of value.matchAll(/\bid="([^"]+)"/g)) nodes.set(m[1], new Element(m[1]));
    this.buttons = [...value.matchAll(/<button\b/g)].map(() => new Element());
  }
  get innerHTML() { return this._html; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  async emit(type, event={target:this}) { for(const fn of this.listeners[type] || []) await fn(event); }
  querySelectorAll(selector) { return selector === 'button' ? this.buttons : []; }
  setAttribute(key,value) { this.attrs[key]=value; }
  removeAttribute(key) { delete this.attrs[key]; }
  appendChild(el) { this.children.push(el); return el; }
  insertAdjacentHTML(where, value) {
    const oldChildren = this.children; this.innerHTML = where === 'afterbegin' ? value + this._html : this._html + value; this.children=oldChildren;
  }
  remove() { this.isConnected=false; if(this.id) nodes.delete(this.id); }
  focus() { this.focused=true; document.activeElement=this; }
  scrollIntoView(options) { navigations.push({id:this.id,options}); }
  click() { return this.emit('click'); }
  showModal() { this.open=true; }
}
for(const id of STATIC_IDS) nodes.set(id, new Element(id));
const document = {
  documentElement:new Element(), body:new Element(),
  querySelector:s => s.startsWith('#') ? nodes.get(s.slice(1)) || null : null,
  querySelectorAll:s => [], getElementById:id => nodes.get(id) || null,
  createElement:() => new Element(),
};
document.activeElement = document.body;
globalThis.window = globalThis;
const navigator = {onLine:true};
const location = {search:'?mode=parent'};
const URL = {createObjectURL:() => 'blob:test-photo', revokeObjectURL:() => {}};
class FormData { constructor(){this.values={};} append(k,v){this.values[k]=v;} }
const setTimeout = (fn, ms) => { timers.set(++timerId,{fn,ms}); return timerId; };
const clearTimeout = id => timers.delete(id);
const setInterval = setTimeout, clearInterval = clearTimeout;
const response = (data, status=200) => ({ok:status>=200 && status<300, status, json:async()=>data});
const streamResponse = events => {
  const chunks=events.map(e=>new TextEncoder().encode(JSON.stringify(e)+'\n'));
  return {ok:true, body:{getReader:()=>({
    read:async()=>chunks.length ? {value:chunks.shift(),done:false} : {done:true},
    cancel:async()=>{}, releaseLock:()=>{}
  })}};
};
const children = [{name:'下の子',school_level:'elementary'}, {name:'上の子',school_level:'junior_high'}];
const fetch = async (url, opts={}) => {
  calls.push({url,opts});
  if(url==='/api/auth/me') {
    if(authValue==='network') throw new Error('offline');
    if(routes.has(url)) return await routes.get(url)(opts);
    return response({role:authValue}, typeof authValue==='number' ? authValue : 200);
  }
  if(url==='/api/config') return response({children},configStatus);
  if(url==='/api/extract/stream' && !routes.has(url)){
    const res = await routes.get('/api/extract')(opts);
    if(!res.ok) return res;
    const data = await res.json();
    return streamResponse([{type:'received'}, {type:'reading'}, {type:'done',...data}]);
  }
  if(!routes.has(url)) throw new Error('Unexpected fetch: '+url);
  return await routes.get(url)(opts);
};
const flush = async () => { for(let i=0;i<20;i++) await Promise.resolve(); };
const registrations = () => calls.filter(c => c.url==='/api/register').map(c=>JSON.parse(c.opts.body));
const photo = {type:'image/png', name:'synthetic.png'};
const item = (overrides={}) => ({id:'candidate',title:'下の子｜こくご',child:'下の子',date:'2026-09-28',kind:'homework',selected:true,branch:'new',...overrides});
const registerOK = opts => response({results:JSON.parse(opts.body).items.map((i,n)=>({status:'ok',id:'event'+n,title:i.title})),notice:{id:'notice'}});
const start = async () => {
  await flush();
  nodes.get('child').value='下の子';
  await nodes.get('child').emit('who:ready');
};
const choose = () => choosePhoto({target:{files:[photo]}});
'''


def run_js(scenario, auth="child"):
    node = shutil.which("node")
    if not node:
        pytest.skip("Nodeなし: HTML・JSの静的契約テストのみ実行")
    ids = [a["id"] for _, a in Elements().tags if "id" in a]
    program = (
        f"const STATIC_IDS={json.dumps(ids)}, AUTH={json.dumps(auth)};\n"
        + HARNESS + "\n" + SCRIPT
        + "\n(async()=>{\n" + scenario + "\n})().catch(e=>{console.error(e);process.exitCode=1;});"
    )
    result = subprocess.run([node, "-"], input=program, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_parent_waits_for_confirmation():
    run_js(r'''
      await start();
      routes.set('/api/extract',()=>response({items:[item()]}));
      routes.set('/api/register',registerOK);
      await choose();
      assert.equal(audience,'parent');
      assert.equal(calls.filter(c=>c.url==='/api/extract').length,0);
      await readPhoto();
      assert.equal(registrations().length,0);
      assert.match($('#result').innerHTML,/登録候補/);
      // ユーザーが確認フォームで編集してから押した状態。
      const fields = {selected:{checked:true},child:{textContent:'上の子'},
        title:{value:'直した内容'},date:{value:'2026-10-01'},time_start:{value:''},note:{value:'追加'} };
      document.querySelectorAll = s => s === '.item' ? [{dataset:{id:'candidate'},
        querySelector:sel=>fields[sel.match(/data-f="([^"]+)"/)[1]]}] : [];
      await doRegister();
      assert.equal(registrations().length,1);
      assert.equal(registrations()[0].source,'parent');
      assert.equal(registrations()[0].items[0].title,'直した内容');
      assert.equal(registrations()[0].items[0].child,'上の子');
      await doRegister(); await readPhoto();
      assert.equal(registrations().length,1);
    ''', 'parent')


def test_child_auto_registration_keeps_branch_metadata_and_no_notification_claim_on_failure():
    run_js(r'''
      await start();
      const moved=item({branch:'moved',selected:false,matched_id:'previous',matched_date:'2026-09-27'});
      routes.set('/api/extract',()=>response({items:[item(),moved,item({branch:'same'})],skipped:1}));
      routes.set('/api/register',opts=>response({results:JSON.parse(opts.body).items.map(i=>({status:'ok',title:i.title,id:'event'})),notice:null}));
      await choose();
      assert.equal(audience,'kid');
      assert.equal(document.body.dataset.audience,'kid');
      assert.equal(registrations().length,1);
      assert.equal(registrations()[0].source,'kid');
      assert.equal(registrations()[0].items.length,2);
      assert.equal(registrations()[0].items[1].matched_id,'previous');
      assert.match($('#completion').innerHTML,/やることに 入ったよ/);
      assert.match($('#completion').innerHTML,/href="\/kid"/);
      assert.doesNotMatch($('#completion').innerHTML,/知らせ/);
      await readPhoto();
      assert.equal(registrations().length,1);
    ''')


@pytest.mark.parametrize("auth", ["child", "parent"])
def test_completion_titles_strip_child_prefix_only_for_child_display(auth):
    run_js(r'''
      await start();
      const titles = ['下の子｜図工 色紙', '音読', '下の子｜図工｜色紙',
        '下の子｜<img src=x onerror=alert(1)>'];
      const items = titles.map((title,n)=>item({id:'item'+n,title}));
      const data = {results:titles.map((title,n)=>({status:'ok',id:'event'+n,title}))};
      const original = JSON.stringify({items,data});
      routes.set('/api/register',()=>response(data));
      await registerItems(items,generation);
      const html = $('#completion').innerHTML;
      const prefix = AUTH === 'child' ? '' : '下の子｜';
      assert.ok(html.includes('<li>'+prefix+'図工 色紙</li>'));
      assert.ok(html.includes('<li>音読</li>'));
      assert.ok(html.includes('<li>'+prefix+'図工｜色紙</li>'));
      assert.ok(html.includes('<li>'+prefix+'&lt;img src=x onerror=alert(1)&gt;</li>'));
      assert.doesNotMatch(html,/<img src=x/);
      if(AUTH === 'child') assert.doesNotMatch(html,/下の子｜/);
      assert.deepEqual(registrations()[0].items.map(i=>i.title),titles);
      assert.equal(JSON.stringify({items,data}),original);
    ''', auth)


def test_only_ambiguous_ownership_requires_confirmation():
    run_js(r'''
      await start();
      routes.set('/api/extract',()=>response({items:[item(),item({id:'unknown',child:''}),item({id:'other',child:'上の子'})]}));
      routes.set('/api/register',registerOK);
      await choose();
      assert.equal(registrations()[0].items.length,1);
      assert.equal($('#result').children.length,2);
      assert.match($('#result').innerHTML,/だれの ぶん/);
      const row=$('#result').children[0];
      await row.buttons[0].click();
      assert.equal(registrations().length,2);
      assert.equal(registrations()[1].items[0].child,'下の子');
      assert.equal(registrations()[1].items[0].id,'unknown');
      await $('#result').children[1].buttons[1].click();
      assert.equal(registrations().length,2);
    ''')


@pytest.mark.parametrize("skipped,message", [(0,"やることは見つからなかったよ"),(2,"もう入っていたよ")])
def test_empty_and_duplicate_have_exit_without_registering(skipped,message):
    run_js(f'''
      await start();
      routes.set('/api/extract',()=>response({{items:[],skipped:{skipped}}}));
      await choose();
      assert.equal(registrations().length,0);
      assert.ok($('#result').innerHTML.includes({json.dumps(message)}));
      assert.match($('#result').innerHTML,/別の写真/);
      assert.match($('#result').innerHTML,/href="\\/kid"/);
    ''')


def test_partial_results_and_undo_use_successful_ids_only():
    run_js(r'''
      await start();
      routes.set('/api/extract',()=>response({items:[item(),item({id:'b'}),item({id:'c'})]}));
      routes.set('/api/register',()=>response({results:[{status:'ok',id:'saved',title:'成功'},{status:'error',title:'失敗'}]}));
      routes.set('/api/register/undo',opts=>{
        assert.deepEqual(JSON.parse(opts.body).ids,['saved']);
        return response({undone:0,failed:['saved']});
      });
      await choose();
      assert.match($('#completion').innerHTML,/成功/);
      assert.match($('#completion').innerHTML,/未確認 2件/);
      assert.ok([...timers.values()].some(t=>t.ms===1000));
      await $('#undo').click();
      assert.match($('#undonote').textContent,/1件は取り消せません/);
      await readPhoto(); assert.equal(registrations().length,1);
    ''')


@pytest.mark.parametrize("failure", ["network", "http", "json"])
def test_uncertain_registration_cannot_be_resubmitted(failure):
    run_js(r'''
      await start();
      routes.set('/api/extract',()=>response({items:[item()]}));
      routes.set('/api/register',()=>{
        if(FAILURE==='network') throw new Error();
        if(FAILURE==='http') return response({},500);
        return {ok:true,json:async()=>{throw new Error('bad json');}};
      });
      await choose();
      assert.match($('#completion').innerHTML,/入ったか たしかめられなかったよ/);
      assert.doesNotMatch($('#completion').innerHTML,/やることに 入ったよ/);
      await readPhoto(); await doRegister();
      assert.equal(registrations().length,1);
    '''.replace("FAILURE", json.dumps(failure)))


def test_offline_retains_photo_and_failed_read_has_retake_and_manual_exit():
    run_js(r'''
      await start(); navigator.onLine=false;
      await choose();
      assert.equal(picked,photo);
      assert.equal(calls.filter(c=>c.url==='/api/extract').length,0);
      assert.match($('#note').textContent,/閉じると失われます/);
      navigator.onLine=true;
      routes.set('/api/extract',()=>response({},415));
      await readPhoto();
      assert.match($('#result').innerHTML,/文字がはっきり/);
      assert.ok($('#retake')); await $('#qfall').click();
      assert.equal($('#qbox').hidden,false);
      assert.equal($('#qtitle').focused,true);
      await $('#file').emit('cancel');
      assert.match($('#note').textContent,/写真を選ぶか/);
    ''')


def test_slow_read_and_child_switch_drop_old_response():
    run_js(r'''
      await start();
      const themed=[]; window.Appearance={setChild:child=>themed.push(child)};
      let resolve;
      routes.set('/api/extract',()=>new Promise(r=>resolve=r));
      const pending=choose(); await flush();
      [...timers.values()].find(t=>t.ms===15000).fn();
      assert.equal($('#note').textContent,'もう少しかかっているよ');
      $('#child').value='上の子'; await $('#child').emit('change');
      assert.deepEqual(themed,['上の子']);
      resolve(response({items:[item()]})); await pending;
      assert.equal(registrations().length,0);
      assert.equal($('#result').innerHTML,'');
      assert.equal($('#completion').innerHTML,'');
      assert.equal(picked,null);
      assert.equal(qChild,'上の子');
    ''')


def test_late_registration_response_never_appears_for_other_child():
    run_js(r'''
      await start(); let resolve;
      routes.set('/api/extract',()=>response({items:[item()]}));
      routes.set('/api/register',()=>new Promise(r=>resolve=r));
      const pending=choose(); await flush();
      assert.equal(registrations().length,1);
      $('#child').value='上の子'; await $('#child').emit('change');
      resolve(response({results:[{status:'ok',title:'前の子',id:'old'}]}));
      await pending;
      assert.equal($('#completion').innerHTML,'');
      assert.equal(busy,false);
    ''')


@pytest.mark.parametrize("auth,source",[("child","kid"),("parent","parent")])
def test_manual_add_shares_success_and_blocks_double_click(auth,source):
    run_js(r'''
      await start(); let resolve;
      routes.set('/api/register',()=>new Promise(r=>resolve=r));
      const pending=$('#qadd').click(); await flush();
      await $('#qadd').click(); await $('#qsame').click();
      assert.equal(registrations().length,1);
      assert.equal(registrations()[0].source,SOURCE);
      assert.equal(registrations()[0].items[0].child,'下の子');
      resolve(response({results:[{status:'ok',id:'manual',title:'こくご'}]})); await pending;
      assert.match($('#completion').innerHTML,/こくご/);
      await $('#qadd').click(); assert.equal(registrations().length,1);
      await $('#qnext').click(); assert.equal($('#qadd').disabled,false);
    '''.replace("SOURCE",json.dumps(source)),auth)


def test_yesterday_handles_month_boundary_duplicates_and_kid_source():
    run_js(r'''
      await start();
      const OriginalDate=Date;
      globalThis.Date=class extends OriginalDate {
        constructor(...args){super(...(args.length ? args : ['2026-10-01T12:00:00+09:00']));}
      };
      routes.set('/api/schedule?ym=2026-09&child='+encodeURIComponent('下の子'),()=>response({items:[
        {summary:'✓ 下の子｜音読',date:'2026-09-30',child:'下の子',kind:'homework'},
        {summary:'下の子｜もちもの',date:'2026-09-30',child:'下の子',kind:'bring'},
        {summary:'下の子｜もちもの',date:'2026-09-30',child:'下の子',kind:'bring'},
        {summary:'上の子｜えいご',date:'2026-09-30',child:'上の子',kind:'homework'},
        {summary:'行事',date:'2026-09-30',child:'下の子',kind:'event'}
      ]}));
      routes.set('/api/schedule?ym=2026-10&child='+encodeURIComponent('下の子'),()=>response({items:[
        {summary:'下の子｜音読',date:'2026-10-01',child:'下の子',kind:'homework'}
      ]}));
      routes.set('/api/register',registerOK);
      await $('#qsame').click();
      assert.equal(registrations().length,1);
      assert.equal(registrations()[0].source,'kid');
      assert.equal(registrations()[0].items.length,1);
      assert.equal(registrations()[0].items[0].date,'2026-10-01');
      assert.equal(registrations()[0].items[0].kind,'bring');
    ''')


def test_parent_render_escapes_extracted_text_and_keeps_differences():
    run_js(r'''
      await start(); picked=photo; previewURL='blob:photo';
      render({items:[item({title:'<img src=x onerror=alert(1)>',branch:'moved',
        matched_date:'2026-09-27',changes:['<追記>'],source_text:'<原文>',confidence:0.8})],trace:['secret']});
      const html=$('#result').innerHTML;
      assert.match(html,/&lt;img src=x/);
      assert.doesNotMatch(html,/<img src=x/);
      assert.match(html,/2026-09-27/); assert.match(html,/→/);
      assert.match(html,/&lt;追記&gt;/);
      assert.doesNotMatch(html,/secret|確度/);
      await $('#shot').click(); assert.equal($('#photo-dialog').open,true);
    ''','parent')


def test_undo_expires_after_ten_minutes():
    run_js(r'''
      await start();
      showRegistered({results:[{status:'ok',id:'one',title:'宿題'}]},1);
      const before=Date.now();
      assert.ok(undoUntil-before<=10*60*1000);
      assert.ok(undoUntil-before>9*60*1000);
      const tick=[...timers.values()].find(t=>t.ms===1000).fn;
      Date.now=()=>before+10*60*1000+1;
      await $('#undo').click();
      assert.equal(calls.filter(c=>c.url==='/api/register/undo').length,0);
      tick(); assert.equal($('#undo'),null);
    ''')


def test_appearance_failure_does_not_break_child_selection_or_manual_entry():
    run_js(r'''
      await start();
      window.Appearance={setChild:()=>Promise.reject(new Error('not connected'))};
      $('#child').value='上の子'; await $('#child').emit('change');
      await flush();
      assert.equal($('#qadd').disabled,false);
      assert.equal(qChild,'上の子');
      window.Appearance={setChild:()=>{throw new Error('unavailable');}};
      $('#child').value='下の子'; await $('#child').emit('change');
      assert.equal($('#qadd').disabled,false);
    ''')


def test_repeat_read_failure_never_registers_or_claims_success():
    run_js(r'''
      await start();
      await $('#qsame').click(); // 予定取得のスタブなし → fetch が失敗
      assert.equal(registrations().length,0);
      assert.match($('#qnote').textContent,/読み込めませんでした/);
      assert.equal($('#completion').innerHTML,'');
      assert.equal($('#qadd').disabled,false);
    ''')


def test_manual_entry_does_not_consume_unsubmitted_parent_photo():
    run_js(r'''
      await start(); await choose();
      routes.set('/api/register',registerOK);
      await $('#qadd').click();
      assert.equal(photoConsumed,false);
      assert.equal($('#go').disabled,false);
    ''','parent')


@pytest.mark.parametrize("auth", [401, 404, 500, "network", "unknown", None])
@pytest.mark.parametrize("recovered", ["child", "parent"])
def test_identity_failure_blocks_every_entry_and_retry_recovers(auth, recovered):
    run_js(r"""
      await start();
      assert.equal(audience,'unknown');
      assert.match($('#capture-title').textContent,/確認できませんでした/);
      assert.match($('#identity-note').textContent,/だれかを確かめられなかった/);
      assert.equal($('#identity-retry').hidden,false);
      for(const id of ['file','album','go','qadd','qsame']) assert.equal(nodes.get(id).disabled,true);
      await choose(); await readPhoto(); await doRegister();
      await $('#qadd').click(); await $('#qsame').click();
      await registerItems([item()],generation);
      await assert.rejects(()=>qPost([item()]));
      assert.equal(calls.filter(c=>['/api/extract','/api/register'].includes(c.url)).length,0);
      authValue=RECOVERED;
      await $('#identity-retry').click();
      assert.equal(audience,RECOVERED==='child' ? 'kid' : 'parent');
      assert.equal($('#file').disabled,false);
      routes.set('/api/extract',()=>response({items:[item()]}));
      routes.set('/api/register',registerOK);
      await choose();
      if(RECOVERED==='child') assert.equal(registrations()[0].source,'kid');
      else {
        assert.equal(registrations().length,0);
        await readPhoto();
        assert.match($('#result').innerHTML,/登録候補/);
      }
    """.replace("RECOVERED", json.dumps(recovered)), auth)


@pytest.mark.parametrize("auth", ["child", "parent"])
def test_config_failure_stays_blocked_until_retry(auth):
    run_js(r"""
      configStatus=500;
      await start();
      assert.equal(configReady,false);
      assert.match($('#identity-note').textContent,/設定を読み込めません/);
      await choose(); await $('#qadd').click(); await $('#qsame').click();
      assert.equal(registrations().length,0);
      assert.equal($('#file').disabled,true);
      configStatus=200;
      await $('#identity-retry').click();
      assert.equal(configReady,true);
      assert.equal($('#file').disabled,false);
    """, auth)


def test_pending_identity_blocks_operations_and_duplicate_retry():
    run_js(r"""
      await start();
      let resolve;
      routes.set('/api/auth/me',()=>new Promise(r=>resolve=r));
      const pending=confirmIdentity(); await flush();
      const count=calls.length;
      await confirmIdentity();
      assert.equal(calls.length,count);
      assert.equal(audience,'pending');
      await choose(); await $('#qadd').click(); await doRegister();
      assert.equal(registrations().length,0);
      assert.equal($('#file').disabled,true);
      resolve(response({role:'child'})); await pending;
      assert.equal($('#file').disabled,false);
    """)


@pytest.mark.parametrize("case", ["success", "empty", "same", "failure", "owner", "mixed", "partial", "uncertain", "parent"])
def test_read_result_navigation_happens_once(case):
    run_js(r"""
      await start();
      routes.set('/api/extract',()=>CASE==='failure' ? response({},500) : response({
        items: ['empty','same'].includes(CASE) ? [] :
          CASE==='owner' ? [item({child:''})] :
          CASE==='mixed' ? [item(),item({child:''})] : [item()],
        skipped: CASE==='same' ? 1 : 0
      }));
      routes.set('/api/register',opts=>{
        if(CASE==='uncertain') throw new Error();
        if(CASE==='partial') return response({results:[{status:'error',title:'未確認'}]});
        return registerOK(opts);
      });
      await choose();
      if(CASE==='parent') await readPhoto();
      assert.equal(navigations.length,1);
      const expected=['success','partial','uncertain'].includes(CASE) ? 'completion' : 'result';
      assert.equal(navigations[0].id,expected);
      assert.equal(document.activeElement,nodes.get(expected));
      assert.deepEqual(navigations[0].options,{block:'start',behavior:'instant'});
      if(CASE==='parent'){
        await registerItems([item()],generation);
        assert.equal(navigations.length,2);
        assert.equal(navigations[1].id,'completion');
      }
    """.replace("CASE", json.dumps(case)), "parent" if case == "parent" else "child")


def test_late_result_does_not_take_focus_from_another_control():
    run_js(r"""
      await start(); let resolve;
      routes.set('/api/extract',()=>new Promise(r=>resolve=r));
      const pending=choose(); await flush();
      $('#qtitle').focus();
      resolve(response({items:[]})); await pending;
      assert.equal(navigations.length,0);
      assert.equal(document.activeElement,$('#qtitle'));
    """)


def test_result_regions_and_manual_title_have_persistent_names():
    tags = Elements().tags
    by_id = {a["id"]: a for _, a in tags if "id" in a}
    for id_ in ("result", "completion"):
        assert by_id[id_]["tabindex"] == "-1"
        assert by_id[id_]["aria-label"]
    assert any(t == "label" and a.get("for") == "qtitle" for t, a in tags)
    for id_ in ("file", "album", "go", "qadd", "qsame"):
        assert "disabled" in by_id[id_]


def test_parent_candidates_have_unique_labels_and_named_groups():
    run_js(r"""
      await start();
      render({items:[item({title:'図工 <色紙>'}),item({id:'other',title:'音読'})]});
      const html=$('#result').innerHTML;
      const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]);
      assert.equal(ids.length,new Set(ids).size);
      for(let i=0;i<2;i++){
        for(const field of ['title','date','time_start','note']){
          const id='candidate-'+i+'-'+field;
          assert.ok(html.includes('<label for="'+id+'">'));
          assert.ok(html.includes('<input id="'+id+'"'));
        }
      }
      assert.equal((html.match(/<fieldset /g)||[]).length,2);
      assert.equal((html.match(/<\/fieldset>/g)||[]).length,2);
      assert.ok(html.includes('<legend>候補 1：図工 &lt;色紙&gt;</legend>'));
      assert.ok(html.includes('aria-label="図工 &lt;色紙&gt;を登録する"'));
      assert.ok(html.includes('aria-label="音読を登録する"'));
    """, "parent")


def test_retry_after_shared_selector_watch_expires_allows_explicit_child_selection():
    run_js(r"""
      await flush();
      assert.equal(audience,'unknown');
      const now=Date.now();
      Date.now=()=>now+16000;
      authValue='child';
      await $('#identity-retry').click();
      assert.equal($('#child').hidden,false);
      assert.equal($('#file').disabled,true);
      $('#child').value='下の子';
      await $('#child').emit('change');
      assert.equal($('#file').disabled,false);
      assert.equal(audience,'kid');
    """, 500)
