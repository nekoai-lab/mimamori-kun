"""/board の契約と状態遷移。ブラウザの描画確認は別担当で行う。"""
import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

BOARD = Path(__file__).resolve().parents[2] / "static/board.html"
HTML = BOARD.read_text()
SCRIPT = re.search(r'<script>\s*(const \$=[\s\S]*?)</script>', HTML)[1]
NODE = shutil.which("node")

# A/F の製品ファイルを作らず、このファイル内だけで DOM と接続を代替する。
HARNESS = r"""
const vm=require('vm'), assert=require('assert/strict');
const input=JSON.parse(require('fs').readFileSync(0,'utf8'));
const elements=new Map(), calls=[], responses=new Map();
// 必要な DOM だけを模す。削除・disabled でのフォーカス喪失も再現する。
function node(tag='div',attrs={}) {
  const e={tagName:tag.toUpperCase(),attrs,children:[],parentElement:null,value:'',textContent:'',
    hidden:false,options:[],dataset:{},handlers:{},files:[],open:false,_html:'',_disabled:false,
    get id(){return this.attrs.id||'';},
    get isConnected(){return this===doc.body || !!this.parentElement?.isConnected;},
    setAttribute(k,v){this.attrs[k]=v;if(k==='value')this.value=v;if(k.startsWith('data-'))this.dataset[k.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=v;},
    addEventListener(ev,fn){(this.handlers[ev]??=[]).push(fn);},
    get disabled(){return this._disabled;},
    set disabled(v){this._disabled=v;if(v&&doc.activeElement===this)doc.activeElement=doc.body;},
    get innerHTML(){return this._html;},
    set innerHTML(html){
      if(this.children.some(c=>c.contains(doc.activeElement)))doc.activeElement=doc.body;
      this.children.forEach(c=>c.parentElement=null);this.children=[];this._html=html;
      const stack=[this];
      for(const token of html.matchAll(/<\/?[\w-]+\b[^>]*>|[^<]+/g)){
        const t=token[0];if(t.startsWith('</')){if(stack.length>1)stack.pop();continue;}
        if(!t.startsWith('<')){stack[stack.length-1].textContent+=t;continue;}
        const tag=t.match(/^<([\w-]+)/)[1], child=node(tag);
        for(const m of t.slice(tag.length+1,-1).matchAll(/([\w-]+)(?:="([^"]*)")?/g))child.setAttribute(m[1],m[2]??'');
        child._disabled='disabled' in child.attrs;
        child.parentElement=stack[stack.length-1];child.parentElement.children.push(child);
        if(!['input','br','img','hr'].includes(tag))stack.push(child);
      }
    },
    contains(other){return this===other||this.children.some(c=>c.contains(other));},
    matches(sel){
      return sel.split(',').some(part=>{
        let q=part.trim();if(q.includes(' ')) {const i=q.lastIndexOf(' ');return this.matches(q.slice(i+1))&&!!this.parentElement?.closest(q.slice(0,i));}
        if(q.includes(':not(:disabled)')){if(this.disabled)return false;q=q.replace(':not(:disabled)','');}
        if(q.startsWith('#'))return this.id===q.slice(1);
        if(q.startsWith('.'))return (this.attrs.class||'').split(' ').includes(q.slice(1));
        const m=q.match(/^([\w-]+)?(?:\[([\w-]+)(?:="([^"]*)")?\])?$/);
        return !!m&&(!m[1]||this.tagName===m[1].toUpperCase())&&(!m[2]||(m[2] in this.attrs&&(m[3]===undefined||this.attrs[m[2]]===m[3])));
      });
    },
    closest(sel){return this.matches(sel)?this:this.parentElement?.closest(sel)||null;},
    querySelectorAll(sel){return this.children.flatMap(c=>[...(c.matches(sel)?[c]:[]),...c.querySelectorAll(sel)]);},
    querySelector(sel){return this.querySelectorAll(sel)[0]||null;},
    setSelectionRange(start,end,direction='none'){this.selectionStart=start;this.selectionEnd=end;this.selectionDirection=direction;},
    scrollIntoView(options){this.scrollCalls??=[];this.scrollCalls.push(options);},
    focus(options){this.focusOptions=options;if(!this.disabled)doc.activeElement=this;},
    async click(){if(this.disabled)return;for(let p=this;p;p=p.parentElement)for(const fn of p.handlers.click||[])await fn({target:this});},
    getBoundingClientRect(){return {height:100};}
  };
  for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);
  return e;
}
function el(key='') {
  if(elements.has(key))return elements.get(key);
  const e=node('div',key.startsWith('#')?{id:key.slice(1)}:{});
  e.parentElement=doc.body;doc.body.children.push(e);elements.set(key,e);return e;
}
const task=(extra={})=>({id:'t',child:'子A',kind:'deadline',status:'todo',days_left:0,
  date:'2026-09-28',summary:'子A｜提出物',...extra});
const tasks=(items=[])=>({today:'2026-09-28',items,children:['子A','子B'],points:{子A:10,子B:20}});
const notice=(extra={})=>({id:'n',kind:'kid_added',title:'新しい予定',at:'2026-09-28T10:00:00+09:00',
  items:[{id:'t',title:'提出物',date:'2026-09-28'}],...extra});
function reply(body,status=200){return {ok:status<400,json:async()=>body};}
let defaultTasks=tasks(),defaultNotices={items:[]};
function fetch(url,opts){
  calls.push({url,body:opts?.body?JSON.parse(opts.body):null,method:opts?.method||'GET'});
  const queue=responses.get(url);
  if(queue?.length){const r=queue.shift();if(r instanceof Error)return Promise.reject(r);return Promise.resolve(r);}
  return Promise.resolve(reply(url==='/api/tasks'?defaultTasks:url.startsWith('/api/notices?')?defaultNotices:{}));
}
const doc={querySelector:el,querySelectorAll:sel=>doc.body.querySelectorAll(sel),hidden:false,addEventListener(ev,fn){this[ev]=fn;},documentElement:{style:{setProperty(k,v){this[k]=v;}}}};
doc.body=node('body');doc.activeElement=doc.body;
const context=vm.createContext({document:doc,fetch,console,assert,el,calls,responses,reply,task,tasks,notice,
  node,boardHTML:input.html,boardCSS:input.css,
  confirm:()=>true,alert:()=>{},FormData:class{append(){}},
  // 共通ライブラリの固定境界だけを模す。A がなくても同じ処理が動く。
  ...(input.appearance?{Appearance:{setChild(){}},AppearanceStore:{read:async()=>({}),write:async()=>{throw Error('未接続');}}}:{}),
  setDefaults(t,n){defaultTasks=t;defaultNotices=n;},
  tick:()=>new Promise(r=>setImmediate(r))});
context.window=context;
el('#schoolGrade').value='0';el('#kanjiScope').value='previous_grade';el('#rubyMode').value='auto';
vm.runInContext(input.script,context);
(async()=>{await new Promise(r=>setImmediate(r));await vm.runInContext('(async()=>{'+input.test+'})()',context);})()
.catch(e=>{console.error(e);process.exitCode=1;});
"""


def run_js(test, appearance=False):
    if NODE is None:
        pytest.skip("node が無い")
    proc = subprocess.run([NODE, "-e", HARNESS], input=json.dumps({
        "script": SCRIPT, "test": test, "appearance": appearance,
        "html": HTML, "css": re.search(r"<style>([\s\S]*?)</style>", HTML)[1],
    }),
                          text=True, capture_output=True, timeout=20)
    assert proc.returncode == 0, proc.stderr


class Structure(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.ids = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            assert attrs["id"] not in self.ids
            self.ids[attrs["id"]] = (attrs, self.stack[:])
        if tag not in {"input", "link", "meta", "br", "hr", "img"}:
            self.stack.append((tag, attrs.get("id")))

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()


def test_layout_and_integration_contract():
    tree = Structure()
    tree.feed(HTML.split('<script>')[0])
    for id_ in ["add", "rec", "yp", "logout", "logoutAll", "authMsg", "readingForm", "systemNotices"]:
        assert ("details", "management") in tree.ids[id_][1]
    for id_ in ["kidbtns", "body"]:
        assert ("details", "allPlans") in tree.ids[id_][1]
    for id_ in ["management", "allPlans"]:
        assert "open" not in tree.ids[id_][0]
    assert HTML.index('id="headline"') < HTML.index('id="exceptions"') < HTML.index('id="notice"') < HTML.index('id="allPlans"')
    assert 'data-audience="parent"' in HTML
    for attr in ["data-family-nav", "data-profile-menu", "data-appearance-picker"]:
        assert attr in HTML
    assert HTML.index('/static/theme.js') < HTML.index('/static/appearance.css')
    assert HTML.index('</main>') < HTML.index('/static/appearance.js')
    assert 'id="pts"' not in HTML and "it.points" not in SCRIPT
    assert "抜けはありません" not in HTML and "MIMAMORI_DEMO" not in HTML
    assert "過去14日〜未来14日" in HTML
    assert "/api/child-settings" in HTML and 'id="readingSave"' in HTML
    assert '<script>\n/* ---- ログアウト（#16） ---- */' in HTML


@pytest.mark.parametrize("populated", [False, True])
def test_family_navigation_visible_links(populated):
    run_js(r"""
// 実 HTML を読み、A が描く親用リンクだけをスタブで追加する。
const root=node('main');
root.innerHTML=boardHTML.match(/<main\b[^>]*>([\s\S]*?)<\/main>/)[1];
const nav=root.querySelector('[data-family-nav]');
if(POPULATED)nav.innerHTML='<a data-ap-nav href="/board">一覧</a><a data-ap-nav href="/?mode=parent">撮る</a><a data-ap-nav href="/reward?view=parent">ごほうび</a>';
// 描画エンジンではなく、この退行に関係する CSS の子孫・隣接・空判定を評価。
// 祖先の display:none も確認し、元の「行ごと隠す」ルールの復活を検出する。
function matches(element,selector){
  const parts=selector.trim().split(/\s+/);
  function matchAt(e,i){
    if(!e)return false;
    const q=parts[i],nonempty=q.includes(':not(:empty)');
    if(nonempty&&!e.children.length&&!e.textContent)return false;
    if(!e.matches(q.replace(':not(:empty)','')))return false;
    if(i===0)return true;
    if(parts[i-1]==='+'){
      const siblings=e.parentElement.children;
      return matchAt(siblings[siblings.indexOf(e)-1],i-2);
    }
    for(let p=e.parentElement;p;p=p.parentElement)if(matchAt(p,i-1))return true;
    return false;
  }
  return matchAt(element,parts.length-1);
}
const rules=[...boardCSS.matchAll(/([^{}]+)\{([^{}]*)\}/g)];
function visible(e){
  for(let p=e;p;p=p.parentElement){
    if(p.hidden||'hidden' in p.attrs)return false;
    let display='';
    for(const [,selectors,body] of rules){
      const value=body.match(/(?:^|;)\s*display:\s*([^;!]+)/);
      if(value&&selectors.split(',').some(s=>matches(p,s)))display=value[1].trim();
    }
    if(display==='none')return false;
  }
  return true;
}
const fallback=root.querySelector('.fallback-links');
assert.ok(visible(fallback));
for(const href of ['/schedule','/plan','/kid','/?mode=parent','/reward?view=parent']){
  const links=root.querySelectorAll('a').filter(a=>a.attrs.href===href&&visible(a));
  assert.equal(links.length,1,href+' must have exactly one visible link');
  if(POPULATED&&['/?mode=parent','/reward?view=parent'].includes(href))
    assert.ok('data-ap-nav' in links[0].attrs);
  else assert.ok(fallback.contains(links[0]));
}
if(!POPULATED)assert.equal(fallback.querySelectorAll('a').filter(visible).length,5);
const group=root.querySelector('.board-navigation'), sub=root.querySelector('.board-subnav');
assert.equal(nav.parentElement,group);
// 「暗く」はリンクの行と同じ行（.board-subnav）の右端。ほかの親の画面と同じ置き方（A の結合）
assert.equal(sub.parentElement,group);
assert.equal(fallback.parentElement,sub);
assert.equal(root.querySelector('#theme').parentElement,sub);
""".replace("POPULATED", json.dumps(populated)))


def test_navigation_spacing_and_wrapping_css():
    css = re.search(r"<style>([\s\S]*?)</style>", HTML)[1]
    rules = {selector.strip(): dict(re.findall(r"([\w-]+):\s*([^;]+)", body))
             for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)}
    group = rules[".board-navigation"]
    assert group["display"] == "flex"
    assert group["flex-direction"] == "column"
    assert float(group["gap"].removesuffix("px")) >= 8
    for selector in (".board-navigation [data-family-nav]", ".fallback-links"):
        assert rules[selector]["flex-wrap"] == "wrap"
        assert rules[selector]["max-width"] == "100%"
    assert rules[".fallback-links"]["display"] == "flex"
    assert rules[".board-navigation a"]["max-width"] == "100%"
    assert rules[".board-navigation a"]["overflow-wrap"] == "anywhere"
    sub = rules[".board-subnav"]
    assert sub["display"] == "flex" and sub["flex-wrap"] == "wrap" and float(sub["gap"].removesuffix("px")) >= 8
    assert rules[".board-subnav .theme"]["margin-left"] == "auto"


@pytest.mark.parametrize("appearance", [False, True])
def test_four_conclusions_and_family_scope(appearance):
    run_js(r"""
assert.equal(el('#headline').textContent,'いま確認することはありません');
setDefaults(tasks([task({child:'子B'})]),{items:[]}); await load();
filter='kid:子A';render();
assert.equal(el('#headline').textContent,'確認すること 1件');
assert.match(el('#exceptions').innerHTML,/子B/);
assert.doesNotMatch(el('#body').innerHTML,/提出物/);
setDefaults(tasks([task({kind:'homework'})]),{items:[notice()]}); await load();
assert.equal(el('#headline').textContent,'新しい知らせがあります');
assert.match(el('#reason').textContent,/承認は不要/);
responses.set('/api/tasks',[reply({},500)]);await load();
assert.equal(el('#headline').textContent,'確認できていない情報があります');
assert.match(el('#reason').textContent,/予定/);
assert.match(el('#notice').innerHTML,/新しい予定/);
""", appearance)


def test_exception_rules_priority_sorting_and_server_days():
    run_js(r"""
const items=[];
for(const status of ['pending','todo','doing','done','rejected'])
for(const kind of ['event','homework','deadline','bring','other'])
for(const days_left of [-3,0,1]) {
  const it=task({status,kind,days_left});
  const expected=status==='pending'||(['todo','doing'].includes(status)&&
    ((days_left<0&&['homework','deadline','bring'].includes(kind))||
     (days_left===0&&['deadline','bring'].includes(kind))));
  assert.equal(Boolean(exceptionReason(it)),expected,JSON.stringify(it));
}
assert.deepEqual(exceptions([task({id:'today'}),task({id:'old',days_left:-5}),
  task({id:'pending',status:'pending',days_left:-8}),task({id:'recent',days_left:-1})]).map(i=>i.id),
  ['pending','old','recent','today']);
assert.equal(exceptions([task({kind:'homework',date:'1900-01-01',days_left:1})]).length,0);
""")


@pytest.mark.parametrize("resource", ["tasks", "notices"])
@pytest.mark.parametrize("failure", ["reply({},500)", "new Error('offline')", "{ok:true,json:async()=>{throw Error('json')}}", "reply({})", "reply({items:[null],children:[],today:'2026-09-28'})"])
def test_failure_never_claims_all_clear(resource, failure):
    url = "/api/tasks" if resource == "tasks" else "/api/notices?unseen=true"
    run_js(f"""
responses.set({json.dumps(url)},[{failure}]);await load();
assert.equal(el('#headline').textContent,'確認できていない情報があります');
assert.match(el('#freshness').textContent,/最新を確認できません/);
await el('#reload').click();
assert.equal(el('#headline').textContent,'いま確認することはありません');
""")


def test_loading_partial_success_stale_and_out_of_order():
    run_js(r"""
let release;
responses.set('/api/notices?unseen=true',[new Promise(r=>release=r)]);
const pending=load();await tick();
assert.equal(el('#headline').textContent,'確認しています');
release(reply({items:[]}));await pending;
setDefaults(tasks([task()]),{items:[notice()]});await load();
responses.set('/api/tasks',[reply({},500)]);
responses.set('/api/notices?unseen=true',[reply({},500)]);await load();
assert.equal(el('#headline').textContent,'最新の状態を確認できません');
assert.match(el('#exceptions').innerHTML,/提出物/);
let old;
responses.set('/api/tasks',[new Promise(r=>old=r)]);
const first=load(); await tick();
setDefaults(tasks(),{items:[]});await load();
old(reply(tasks([task()])));await first;
assert.equal(el('#headline').textContent,'いま確認することはありません');
""")


def test_multiple_notices_operational_notices_and_xss():
    run_js(r"""
const unsafe='<img src=x onerror="bad()">';
setDefaults(tasks([task({summary:unsafe,child:unsafe,bring:unsafe,id:unsafe})]),
 {items:[notice({title:unsafe,items:[{id:unsafe,title:unsafe}]}),notice({id:'r',kind:'redeem'}),notice({id:'o',kind:'test',title:'運用テスト'})]});await load();
assert.match(el('#notice').innerHTML,/新しい知らせ 2件/);
assert.match(el('#notice').innerHTML,/\/reward\?view=parent/);
assert.doesNotMatch(el('#notice').innerHTML,/運用テスト/);
assert.match(el('#systemNotices').innerHTML,/運用テスト/);
for(const selector of ['#exceptions','#body','#notice']) {
 assert.doesNotMatch(el(selector).innerHTML,/<img/);
 assert.match(el(selector).innerHTML,/&lt;img/);
}
assert.ok(el('#notice').innerHTML.indexOf('内容を確認')<el('#notice').innerHTML.indexOf('この予定を取り消す'));
setDefaults(tasks(),{items:[notice({kind:'test'})]});await load();
assert.equal(el('#headline').textContent,'いま確認することはありません');
""")


@pytest.mark.parametrize("action", ["seen", "done", "cancel"])
def test_actions_wait_for_server_failure_retry_and_separation(action):
    run_js(r"""
setDefaults(tasks([task()]),{items:[notice()]});await load();calls.length=0;
const action=ACTION;
const btn=el(action==='done'?'#exceptions':'#notice').querySelector(action==='done'?'[data-status]':action==='seen'?'.seen':'.cancel-task');
const invoke=()=>action==='done'?onStatus({currentTarget:btn}):onNotice({target:btn});
const url=action==='seen'?'/api/notices/seen':'/api/status';
let release;responses.set(url,[new Promise(r=>release=r)]);
const request=invoke();await tick();await invoke();
assert.equal(calls.filter(c=>c.method==='POST').length,1);
assert.match(el('#notice').innerHTML,/新しい予定/);
assert.match(el('#exceptions').innerHTML,/提出物/);
release(reply({},500));await request;
assert.equal(btn.disabled,false);assert.match(el(action==='done'?'#exceptions':'#notice').innerHTML,/確認できません/);
assert.equal(data.items[0].status,'todo');assert.equal(notices.length,1);
responses.set(url,[reply(action==='seen'?{seen:1}:{status:action==='done'?'done':'rejected'})]);
setDefaults(tasks(action==='seen'?[task()]:[]),{items:action==='seen'?[]:[notice()]});
await invoke();
const posts=calls.filter(c=>c.method==='POST');
assert.equal(posts.length,2);
assert.deepEqual(JSON.parse(JSON.stringify(posts[1].body)),action==='seen'?{id:'n'}:{event_id:'t',status:action==='done'?'done':'rejected'});
assert.equal(posts[1].url,url);
if(action==='seen')assert.match(el('#exceptions').innerHTML,/提出物/);
else assert.equal(notices.length,1);
""".replace("ACTION", json.dumps(action)))


def test_cancel_confirmation_and_application_failure():
    run_js(r"""
setDefaults(tasks([task()]),{items:[notice()]});await load();calls.length=0;
const btn=el('#notice').querySelector('.cancel-task');
let prompt;window.confirm=text=>{prompt=text;return false;};
await onNotice({target:btn});assert.match(prompt,/提出物/);assert.equal(calls.length,0);
window.confirm=()=>true;responses.set('/api/status',[reply({status:'error'})]);
await onNotice({target:btn});assert.match(el('#notice').innerHTML,/提出物/);
assert.equal(btn.disabled,false);
""")


def test_reading_settings_load_for_the_child_and_save_only_on_submit():
    """学年・ふりがな（塊 F）：子を選ぶとその子の保存済みの値を読む。表示例を変えても保存しない。保存は「保存する」だけ。"""
    run_js(r"""
const A='/api/child-settings?child='+encodeURIComponent('子A');
responses.set(A,[reply({settings:{school_grade:'e3',kanji_scope:'current_grade',ruby_mode:'all'}})]);
el('#readingChild').value='子A'; await loadReading();
assert.equal(el('#schoolGrade').value,'3');assert.equal(el('#kanjiScope').value,'current_grade');assert.equal(el('#rubyMode').value,'all');
assert.equal(el('#readingSave').disabled,false);
calls.length=0;
el('#schoolGrade').value='4'; el('#readingForm').handlers.change[0]({target:{id:'schoolGrade'}});
assert.equal(calls.filter(c=>c.method==='POST').length,0);           // 表示例を変えただけでは送らない
let prevented=false; await el('#readingForm').handlers.submit[0]({preventDefault(){prevented=true;}});
assert.equal(prevented,true);
const post=calls.find(c=>c.method==='POST');
assert.equal(post.url,'/api/child-settings');
assert.equal(JSON.stringify(post.body),JSON.stringify({child:'子A',school_grade:'e4',kanji_scope:'current_grade',ruby_mode:'all'}));
assert.match(el('#readingStatus').textContent,/保存しました/);
// 保存したあとに値を変えたら、成功の文を残さない（UX_REVIEW PR-39 F1）。元に戻したら消える
el('#rubyMode').value='auto'; el('#readingForm').handlers.change[0]({target:{id:'rubyMode'}});
assert.equal(el('#readingStatus').textContent,'まだ保存していません。「保存する」で確定します。');
el('#rubyMode').value='all'; el('#readingForm').handlers.change[0]({target:{id:'rubyMode'}});
assert.equal(el('#readingStatus').textContent,'');
assert.equal(calls.filter(c=>c.method==='POST').length,1);             // 変えただけでは送らない
// 保存に失敗したら、保存できたと言わない。もう一度押せる
responses.set('/api/child-settings',[reply({detail:'x'},500)]);
await el('#readingForm').handlers.submit[0]({preventDefault(){}});
assert.match(el('#readingStatus').textContent,/保存できませんでした/);
assert.equal(el('#readingSave').disabled,false);
""")


def test_reading_settings_do_not_carry_a_draft_to_another_child_or_save_unread_values():
    run_js(r"""
const A='/api/child-settings?child='+encodeURIComponent('子A'), B='/api/child-settings?child='+encodeURIComponent('子B');
responses.set(A,[reply({settings:{school_grade:'e2'}})]);
el('#readingChild').value='子A'; await loadReading();
el('#schoolGrade').value='6';                                        // 子A の打ちかけ
responses.set(B,[reply({settings:{}})]);
el('#readingChild').value='子B'; await loadReading();
assert.equal(el('#schoolGrade').value,'0');                           // 子B は保存済みの値（未設定）
// 読み込めない子は、知らない値を上書きしないよう保存させない
responses.set(A,[new Error('offline')]);
el('#readingChild').value='子A'; await loadReading();
assert.equal(el('#readingSave').disabled,true);
assert.match(el('#readingStatus').textContent,/読み込めませんでした/);
calls.length=0; await el('#readingForm').handlers.submit[0]({preventDefault(){}});
assert.equal(calls.filter(c=>c.method==='POST').length,0);
// 遅れて届いた前の子の値で、今の子の表示を上書きしない
let slow; responses.set(A,[new Promise(r=>slow=r)]); responses.set(B,[reply({settings:{school_grade:'j1'}})]);
el('#readingChild').value='子A'; const first=loadReading();
el('#readingChild').value='子B'; await loadReading();
slow(reply({settings:{school_grade:'e1'}})); await first;
assert.equal(el('#schoolGrade').value,'7');
""")


def test_existing_manual_recurring_and_year_plan_requests():
    run_js(r"""
el('#addtitle').value='音読';el('#addchild').value='子A';el('#addkind').value='homework';el('#adddate').value='2026-09-28';
responses.set('/api/register',[reply({results:[{status:'ok'}]})]);
await el('#add').handlers.submit[0]({preventDefault(){}});
assert.deepEqual(JSON.parse(JSON.stringify(calls.find(c=>c.url==='/api/register').body.items)),[{kind:'homework',title:'子A｜音読',child:'子A',date:'2026-09-28'}]);
responses.set('/api/recurring',[reply({templates:[{id:'r',title:'音読',child:'子A',days:'daily',enabled:true}]})]);await loadRec();
responses.set('/api/recurring',[reply({today:{created:[]}})]);await el('#recsave').click();
assert.equal(calls.find(c=>c.url==='/api/recurring'&&c.method==='POST').body.templates[0].id,'r');
el('#yptext').value='4月';el('#ypchild').value='子A';el('#yplevel').value='family';
responses.set('/api/year_plan/check',[reply({check:{ok:true,notes:[],examples:[],dated:1},will_add:1,counts:{family:1,school:0,holiday:0},preview:[]})]);
await el('#ypcheck').click();assert.equal(el('#ypgo').disabled,false);
responses.set('/api/year_plan/register',[reply({created:1})]);await el('#ypgo').click();
assert.equal(calls.find(c=>c.url==='/api/year_plan/register').body.confirm,true);
assert.equal(calls.find(c=>c.url==='/api/year_plan/check').body.confirm,false);
""")


def test_initial_failure_retains_successful_half_without_all_clear():
    run_js(r"""
data=null;notices=[];sources.tasks.at=null;sources.notices.at=null;
responses.set('/api/tasks',[new Error('offline')]);
setDefaults(tasks(),{items:[notice()]});await load();
assert.equal(el('#headline').textContent,'確認できていない情報があります');
assert.match(el('#notice').innerHTML,/新しい予定/);
assert.match(el('#freshness').textContent,/予定: 未取得/);
""")


@pytest.mark.parametrize('action', ['done', 'undo', 'seen', 'cancel'])
@pytest.mark.parametrize('failure', ['reply({},500)', "new Error('offline')", 'reply({})'])
def test_card_local_uncertain_result_and_recheck(action, failure):
    run_js(r'''
const action=ACTION;
showDone=true;
const ts=Array.from({length:7},(_,i)=>task({id:'t'+i,summary:'対象'+i,status:action==='undo'?'done':'todo'}));
const ns=Array.from({length:7},(_,i)=>notice({id:'n'+i,title:'知らせ'+i,items:[{id:'t'+i,title:'対象'+i}]}));
setDefaults(tasks(ts),{items:ns});await load();
const root=el(action==='undo'?'#body':action==='done'?'#exceptions':'#notice');
const card=()=>root.querySelectorAll('[data-card]').find(c=>c.dataset.card===(['done','undo'].includes(action)?'t6':'n6'));
if(action==='cancel')card().querySelector('details').open=true;
const button=card().querySelector(action==='seen'?'.seen':action==='cancel'?'.cancel-task':'[data-status]');
button.focus();
let release;const url=action==='seen'?'/api/notices/seen':'/api/status';
responses.set(url,[new Promise(r=>release=r)]);
const pending=action==='done'||action==='undo'?onStatus({currentTarget:button}):onNotice({target:button});
await tick();
assert.notEqual(document.activeElement,document.body);
assert.equal(document.activeElement.closest('[data-card]'),card());
assert.equal(document.activeElement.attrs.tabindex,'-1');assert.equal(button.disabled,true);
release(FAILURE);await pending;
assert.ok(card());assert.match(card().innerHTML||root.innerHTML,/確認できませんでした/);
let retry=card().querySelector('[data-recheck]');assert.ok(retry);
assert.equal(document.activeElement,retry);
assert.match(retry.closest('[data-action]').querySelector('[role="status"]').textContent,action==='seen'?/知らせ6/:/対象6/);
if(action==='cancel')assert.equal(card().querySelector('details').open,true);
responses.set(action==='seen'?'/api/notices?unseen=true':'/api/tasks',[reply({},500)]);
await retry.click();
assert.ok(card());retry=card().querySelector('[data-recheck]');assert.ok(retry);
assert.equal(document.activeElement,retry);
assert.match(el('#headline').textContent,/確認でき/);
// 同じ場所から再取得のみを行い、サーバーの現状へ戻す。
const posts=calls.filter(c=>c.method==='POST').length;
responses.set('/api/status?event_id=t6',[reply({id:'t6',status:action==='undo'?'done':'todo'})]);
await retry.click();
assert.equal(calls.filter(c=>c.method==='POST').length,posts);
assert.equal(card().querySelector('[data-recheck]'),null);
assert.notEqual(document.activeElement,document.body);
assert.equal(document.activeElement.closest('[data-card]'),card());
'''.replace('ACTION', json.dumps(action)).replace('FAILURE', failure))


@pytest.mark.parametrize('action', ['done', 'undo', 'seen', 'cancel'])
@pytest.mark.parametrize('outcome', ['remain', 'remove', 'last', 'moved', 'moved_failure'])
def test_action_focus_handoff(action, outcome):
    run_js(r'''
const action=ACTION,outcome=OUTCOME;
showDone=true;
const old=task({id:'t0',status:action==='undo'?'done':'todo'}),other=task({id:'t1'});
const n0=notice({id:'n0',items:[{id:'t0',title:'対象0'}]}),n1=notice({id:'n1'});
setDefaults(tasks(outcome==='last'?[old]:[old,other]),{items:outcome==='last'?[n0]:[n0,n1]});await load();
const root=el(action==='undo'?'#body':action==='done'?'#exceptions':'#notice');
const getCard=id=>root.querySelectorAll('[data-card]').find(c=>c.dataset.card===id);
const id=['done','undo'].includes(action)?'t0':'n0';
let card=getCard(id);
if(action==='cancel')card.querySelector('details').open=true;
const btn=card.querySelector(action==='seen'?'.seen':action==='cancel'?'.cancel-task':'[data-status]');btn.focus();
let release;responses.set(action==='seen'?'/api/notices/seen':'/api/status',[new Promise(r=>release=r)]);
const pending=['done','undo'].includes(action)?onStatus({currentTarget:btn}):onNotice({target:btn});await tick();
if(outcome.startsWith('moved'))el('#reload').focus();
const remaining=outcome==='remain'||outcome.startsWith('moved');
setDefaults(tasks(remaining?[{...old,status:action==='undo'?'todo':'done'},other]:outcome==='last'?[]:[other]),
 {items:remaining?[{...n0,items:[]},n1]:outcome==='last'?[]:[n1]});
release(outcome==='moved_failure'?reply({},500):reply(action==='seen'?{seen:1}:{status:action==='cancel'?'rejected':action==='undo'?'todo':'done'}));await pending;
assert.notEqual(document.activeElement,document.body);
if(outcome.startsWith('moved'))assert.equal(document.activeElement,el('#reload'));
else if(outcome==='last')assert.equal(document.activeElement,el('#headline'));
else {
 // 対応済みは例外から消えるので、次の例外へ進む。
 const expected=remaining&&action!=='done'?id:['done','undo'].includes(action)?'t1':'n1';
 assert.equal(document.activeElement.closest('[data-card]').dataset.card,expected);
 assert.ok(['BUTTON','SUMMARY','A'].includes(document.activeElement.tagName));
}
'''.replace('ACTION', json.dumps(action)).replace('OUTCOME', json.dumps(outcome)))


def test_automatic_refresh_preserves_open_notice_and_current_control():
    run_js(r'''
setDefaults(tasks([task()]),{items:[notice()]});await load();
const details=el('#notice').querySelector('details');details.open=true;
details.querySelector('summary').focus();
await document.visibilitychange();await tick();
assert.equal(el('#notice').querySelector('details').open,true);
assert.equal(document.activeElement,el('#notice').querySelector('summary'));
assert.notEqual(document.activeElement,document.body);
''')
    assert 'scroll-margin-top:' in HTML
    assert 'id="headline" tabindex="-1"' in HTML


@pytest.mark.parametrize('failed_source', ['tasks', 'notices'])
def test_cancel_recheck_retains_card_until_both_sources_confirm(failed_source):
    run_js(r'''
setDefaults(tasks([task()]),{items:[notice()]});await load();
el('#notice').querySelector('details').open=true;
let btn=el('#notice').querySelector('.cancel-task');btn.focus();
responses.set('/api/status',[reply({})]);await onNotice({target:btn});
setDefaults(tasks(),{items:[]});
responses.set(SOURCE==='tasks'?'/api/tasks':'/api/notices?unseen=true',[reply({},500)]);
await el('#notice').querySelector('[data-recheck]').click();
assert.ok(el('#notice').querySelector('[data-card]'));
assert.equal(el('#notice').querySelector('details').open,true);
assert.equal(document.activeElement,el('#notice').querySelector('[data-recheck]'));
responses.set('/api/status?event_id=t',[reply({id:'t',status:'rejected'})]);
await document.activeElement.click();
assert.ok(el('#notice').querySelector('[data-card]'));
assert.match(el('#notice').innerHTML,/取り消しました/);
assert.equal(el('#notice').querySelector('.cancel-task'),null);
assert.notEqual(document.activeElement,document.body);
'''.replace('SOURCE', json.dumps(failed_source)))


def test_waiting_user_moves_to_another_card_and_refresh_keeps_that_action():
    run_js(r'''
setDefaults(tasks([task({id:'t0'}),task({id:'t1'})]),{items:[]});await load();
let release;responses.set('/api/status',[new Promise(r=>release=r)]);
const first=el('#exceptions').querySelector('[data-status]');first.focus();
const pending=onStatus({currentTarget:first});await tick();
el('#exceptions').querySelectorAll('[data-status]')[1].focus();
setDefaults(tasks([task({id:'t1'})]),{items:[]});
release(reply({status:'done'}));await pending;
assert.equal(document.activeElement,el('#exceptions').querySelector('[data-status]'));
assert.equal(document.activeElement.dataset.id,'t1');
''')


@pytest.mark.parametrize('action', ['cancel', 'seen', 'done'])
@pytest.mark.parametrize('outcome', ['confirmed', 'unchanged', 'error', 'missing'])
@pytest.mark.parametrize('moved', [False, True])
def test_recheck_names_actual_result_and_keeps_it_in_card(action, outcome, moved):
    run_js(r'''
const action=ACTION,outcome=OUTCOME,moved=MOVED;
setDefaults(tasks([task()]),{items:[notice()]});await load();
const root=el(action==='done'?'#exceptions':'#notice');
if(action==='cancel')root.querySelector('details').open=true;
const btn=root.querySelector(action==='done'?'[data-status]':action==='seen'?'.seen':'.cancel-task');btn.focus();
responses.set(action==='seen'?'/api/notices/seen':'/api/status',[new Error('response lost')]);
await (action==='done'?onStatus({currentTarget:btn}):onNotice({target:btn}));
// 実契約：取消済みは tasks にない。知らせは登録時の項目を保持したまま。
setDefaults(tasks(outcome==='confirmed'?(action==='cancel'?[]:action==='done'?[task({status:'done'})]:[task()]):[task()]),
 {items:outcome==='confirmed'&&action==='seen'?[]:[notice()]});
const url=action==='seen'?'/api/notices?unseen=true':'/api/status?event_id=t';
let release;responses.set(url,[new Promise(r=>release=r)]);
const retry=root.querySelector('[data-recheck]');retry.focus();
const posts=calls.filter(c=>c.method==='POST').length;
const pending=retry.click();await tick();
assert.notEqual(document.activeElement,document.body);
if(moved)el('#reload').focus();
release(outcome==='error'?reply({},500):outcome==='missing'?reply({},404):
 reply(action==='seen'?{items:outcome==='confirmed'?[]:[notice()]}:{id:'t',status:outcome==='confirmed'?(action==='cancel'?'rejected':'done'):'todo'}));
await pending;
assert.equal(calls.filter(c=>c.method==='POST').length,posts);
assert.ok(root.querySelector('[data-card]'));
assert.notEqual(document.activeElement,document.body);
if(moved)assert.equal(document.activeElement,el('#reload'));
else assert.equal(document.activeElement.closest('[data-card]'),root.querySelector('[data-card]'));
const feedback=root.querySelector('[data-action="'+(action==='done'?'status:t':action==='seen'?'seen:n':'cancel:t')+'"] .action-feedback');
assert.ok(feedback);
assert.equal(feedback.matches('.is-warning'),outcome!=='confirmed');
if(action==='done'&&outcome==='confirmed'){
 const card=feedback.closest('.row');
 assert.ok(card.matches('.is-done'));
 const content=card.querySelector('.row-content');
 assert.ok(content);assert.ok(content.querySelector('.ttl'));
 assert.equal(content.contains(feedback),false);
 assert.equal(content.contains(feedback.closest('[data-action]')),false);
 assert.equal(feedback.closest('[data-action]').parentElement,card);
}
const failed=['error','missing'].includes(outcome);
if(failed){
 assert.match(root.innerHTML,/確認できませんでした/);
 assert.ok(root.querySelector('[data-recheck]'));
 if(action==='cancel')assert.match(root.innerHTML,/Google カレンダーで確かめる/);
}else{
 const expected=action==='cancel'?(outcome==='confirmed'?'「提出物」を取り消しました':'「提出物」は取り消せていませんでした'):
 action==='seen'?(outcome==='confirmed'?'既読にしました':'既読にできていませんでした'):
 outcome==='confirmed'?'対応済みにしました':'対応済みにできていませんでした';
 assert.ok(root.innerHTML.includes(expected),root.innerHTML);
 assert.equal(root.querySelector('[data-recheck]'),null);
 assert.equal(!!root.querySelector(action==='done'?'[data-status]':action==='seen'?'.seen':'.cancel-task'),outcome==='unchanged');
 if(outcome==='confirmed'&&action==='cancel')assert.match(root.innerHTML,/取り消し済み/);
 if(!moved)assert.equal(document.activeElement.attrs.tabindex,'-1');
 render();assert.ok(root.innerHTML.includes(expected));
 if(outcome==='confirmed'&&action!=='cancel'){
   await load();assert.equal(root.querySelector('[data-card]'),null);
   assert.notEqual(document.activeElement,document.body);
 }
}
'''.replace('ACTION', json.dumps(action)).replace('OUTCOME', json.dumps(outcome)).replace('MOVED', json.dumps(moved)))


def test_feedback_colors_and_done_opacity_scope():
    css = re.search(r"<style>([\s\S]*?)</style>", HTML)[1]
    rules = dict(re.findall(r"([^{}]+)\{([^{}]*)\}", css))
    rules = {selector.strip(): body for selector, body in rules.items()}
    assert re.search(r"color:\s*var\(--ink\)", rules[".action-feedback"])
    assert re.search(r"color:\s*var\(--late-ink\)", rules[".action-feedback.is-warning"])
    # カード祖先への opacity 復活や、操作・結果文への追加を検出する。
    dimmed = {selector for selector, body in rules.items()
              if re.search(r"(?:^|;)\s*opacity:\s*(?:0?\.\d+|0)\s*(?:;|$)", body)}
    assert ".row.is-done .row-content" in dimmed
    assert dimmed <= {
        ".row.is-done .row-content", ".ypfile button:disabled",
        ".acts button:disabled", "footer .auth button:disabled",
        ".add .prim:disabled", ".recfoot .prim:disabled", ".ypbar .prim:disabled",
        ".ypout .mv:disabled", ".recrow.off .t,.recrow.off .who,.recrow.off .wd",
    }
    # 結果文が載る背景で、明暗どちらも通常文字のコントラストを保つ。
    def rgb(value):
        if len(value) == 4:
            value = "#" + "".join(c * 2 for c in value[1:])
        return [int(value[i:i + 2], 16) / 255 for i in (1, 3, 5)]

    def luminance(color):
        return sum(w * (c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4)
                   for w, c in zip((.2126, .7152, .0722), color))

    for selector in (":root", ':root[data-theme="dark"]'):
        palette = dict(re.findall(r"(--[\w-]+):\s*(#[0-9A-Fa-f]+)", rules[selector]))
        paper = rgb(palette["--paper"])
        late = palette["--late"]
        alpha = int(late[7:9], 16) / 255
        backgrounds = [rgb(palette[k]) for k in ("--surface", "--accent-soft", "--paper")]
        backgrounds.append([a * alpha + b * (1 - alpha) for a, b in zip(rgb(late), paper)])
        for background in backgrounds:
            levels = sorted((luminance(rgb(palette["--ink"])), luminance(background)))
            assert (levels[1] + .05) / (levels[0] + .05) >= 4.5
