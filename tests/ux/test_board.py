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
function el(key='') {
  if(elements.has(key)) return elements.get(key);
  const e={id:key.slice(1),value:'',textContent:'',innerHTML:'',hidden:false,disabled:false,
    options:[],dataset:{},handlers:{},attrs:{},files:[],
    addEventListener(ev,fn){this.handlers[ev]=fn;},setAttribute(k,v){this.attrs[k]=v;},
    focus(){},click(){return this.handlers.click?.({target:this});},
    closest(sel){return this.matches===sel?this:null;}};
  elements.set(key,e);return e;
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
const doc={querySelector:el,querySelectorAll:()=>[],hidden:false,addEventListener(ev,fn){this[ev]=fn;}};
const context=vm.createContext({document:doc,fetch,console,assert,el,calls,responses,reply,task,tasks,notice,
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
    proc = subprocess.run([NODE, "-e", HARNESS], input=json.dumps({"script": SCRIPT, "test": test, "appearance": appearance}),
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
    assert "保存はまだ利用できません" in HTML
    assert '<script>\n/* ---- ログアウト（#16） ---- */' in HTML


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
const btn=el('button');btn.dataset={id:'t',n:'n',title:'提出物',status:'done'};
btn.matches=action==='seen'?'.seen':'.cancel-task';
const invoke=()=>action==='done'?onStatus({currentTarget:btn}):onNotice({target:btn});
const url=action==='seen'?'/api/notices/seen':'/api/status';
let release;responses.set(url,[new Promise(r=>release=r)]);
const request=invoke();await tick();await invoke();
assert.equal(calls.filter(c=>c.method==='POST').length,1);
assert.match(el('#notice').innerHTML,/新しい予定/);
assert.match(el('#exceptions').innerHTML,/提出物/);
release(reply({},500));await request;
assert.equal(btn.disabled,false);assert.match(el('#actionMsg').textContent,/確認できません/);
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
const btn=el('cancel');btn.matches='.cancel-task';btn.dataset={id:'t',title:'提出物'};
let prompt;window.confirm=text=>{prompt=text;return false;};
await onNotice({target:btn});assert.match(prompt,/提出物/);assert.equal(calls.length,0);
window.confirm=()=>true;responses.set('/api/status',[reply({status:'error'})]);
await onNotice({target:btn});assert.match(el('#notice').innerHTML,/提出物/);
assert.equal(btn.disabled,false);
""")


def test_settings_preview_never_writes_or_leaks_child_draft():
    run_js(r"""
calls.length=0;
el('#schoolGrade').value='3';el('#kanjiScope').value='previous_grade';previewReading();
assert.doesNotMatch(el('#readingPreview').innerHTML,/<ruby>/);
el('#rubyMode').value='all';previewReading();assert.match(el('#readingPreview').innerHTML,/<ruby>/);
el('#readingForm').handlers.change({target:{id:'readingChild'}});
assert.equal(el('#schoolGrade').value,'0');assert.equal(el('#rubyMode').value,'auto');
let prevented=false;el('#readingForm').handlers.submit({preventDefault(){prevented=true;}});
assert.equal(prevented,true);assert.equal(calls.length,0);
""")


def test_existing_manual_recurring_and_year_plan_requests():
    run_js(r"""
el('#addtitle').value='音読';el('#addchild').value='子A';el('#addkind').value='homework';el('#adddate').value='2026-09-28';
responses.set('/api/register',[reply({results:[{status:'ok'}]})]);
await el('#add').handlers.submit({preventDefault(){}});
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
