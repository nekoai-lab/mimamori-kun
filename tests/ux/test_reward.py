"""Issue #21（UX 塊 C）：/reward の状態・文言・申込の送信ロック。外部サービスなし。

DOM とサーバーはテスト用の偽物。ブラウザでの見た目と実サーバーとの通しは PR の確認（スクリーンショット）で行う。
"""
from pathlib import Path
import re
import shutil
import subprocess

import pytest

HTML = (Path(__file__).resolve().parents[2] / "static/reward.html").read_text()
JS = HTML.split("<script>")[-1].split("</script>")[0]
KID_VIEW = HTML.split('<div id="kid-view">')[1].split('<div id="parent-view"')[0]


def test_load_order_and_slots():
    assert HTML.index("/static/theme.js") < HTML.index("/static/appearance.css") < HTML.index("/static/who.js")
    assert HTML.index("data-family-nav") < HTML.index("/static/appearance.js") < HTML.index("<script>\n")
    for slot in ("data-appearance-picker", "data-profile-menu", "data-family-nav"):
        assert slot in HTML
    assert 'id="child"' in HTML  # who.js が子を決める select
    assert "window.Appearance?.setChild(child)" in JS


def test_parent_entry_and_no_pace_or_companion_on_kid_screen():
    assert 'href="/login?switch=parent&amp;next=%2Freward%3Fview%3Dparent"' in KID_VIEW
    # 「今のペースだと 約◯日」は子の画面から外す（親の領域だけ）
    assert "ペース" not in KID_VIEW and "約" not in KID_VIEW
    assert 'id="pace"' in HTML.split('<div id="parent-view"')[1]
    # 相棒は置かない（残りを言わせない）
    assert "companion" not in HTML and "相棒" not in KID_VIEW
    # カードを薄くしない
    assert "opacity" not in HTML.split("/* ごほうびのカード")[1].split("/* 折りたたみ")[0]
    assert "交換できるもの" not in HTML


HARNESS = r'''
const assert = require('node:assert/strict');
class Element {
  constructor(tag='div'){this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.attrs={};this.listeners={};this.style={};this.value='';this.hidden=false;this.disabled=false;this._text='';this.className='';this.parent=null;
    this.classList={add:(...xs)=>{this.className=[...new Set(this.className.split(' ').filter(Boolean).concat(xs))].join(' ')},remove:(...xs)=>{this.className=this.className.split(' ').filter(x=>!xs.includes(x)).join(' ')},toggle:(x,on)=>{if(on??!this.classList.contains(x))this.classList.add(x);else this.classList.remove(x)},contains:x=>this.className.split(' ').includes(x)};}
  set textContent(x){this._text=String(x);this.children=[];}
  get textContent(){return this._text+this.children.map(x=>x.textContent).join('');}
  set innerHTML(x){this._html=x;this.children=[];}
  get innerHTML(){return this._html||'';}
  append(...xs){for(const x of xs){this.children.push(x);x.parent=this;}}
  appendChild(x){this.append(x);return x;}
  replaceChildren(...xs){this.children=[];this._text='';this.append(...xs);}
  remove(){if(this.parent)this.parent.children=this.parent.children.filter(x=>x!==this);}
  setAttribute(k,v){this.attrs[k]=String(v);}
  getAttribute(k){return this.attrs[k]??null;}
  addEventListener(k,fn){(this.listeners[k]??=[]).push(fn);}
  async click(){for(const fn of this.listeners.click||[])await fn({target:this});}
  focus(){document.activeElement=this;}
  getBoundingClientRect(){return {height:60};}
  get all(){return this.children.flatMap(x=>[x,...x.all]);}
  matches(s){if(s==='[data-ask]')return this.dataset.ask==='1';if(s==='[data-go]')return this.dataset.go==='1';if(s.startsWith('.'))return this.classList.contains(s.slice(1));return this.tagName===s.toUpperCase();}
  querySelectorAll(s){return this.all.filter(x=>x.matches(s));}
  querySelector(s){return this.querySelectorAll(s)[0]||null;}
  get buttons(){return this.querySelectorAll('button');}
}
const elements=new Map();
const document={documentElement:new Element('html'),body:new Element('body'),activeElement:null,
  querySelector:s=>{if(!elements.has(s))elements.set(s,new Element());return elements.get(s);},
  querySelectorAll:s=>s==='#rewards .card'?document.querySelector('#rewards').children:[],
  createElement:tag=>new Element(tag)};
const window={innerHeight:667,addEventListener(){}};
let search='';
const location={get search(){return search;}};
let replies=[],calls=[];
async function fetch(url,options){calls.push({url,options});if(!replies.length)throw Error('unexpected fetch '+url);const r=replies.shift();if(typeof r==='function')return r(url,options);if(r instanceof Error)throw r;return {ok:r.ok??true,status:r.status??200,json:async()=>{if(r.bad)throw Error('bad json');return r.body??r;}};}
function deferred(){let resolve;const promise=new Promise(x=>resolve=x);return {promise,resolve};}
const posts=()=>calls.filter(c=>c.options?.method==='POST');
const G={label:'ゲームの時間を30分のばす',points:30}, W={label:'週末に行きたいところを1つ決められる',points:100};
const text=sel=>document.querySelector(sel).textContent;
const cards=()=>document.querySelector('#rewards').children;
const card=label=>cards().find(c=>c.dataset.label===label);
function load({bal=34,hist=[{title:'こくご',date:'2026-09-28',kind:'adjust',points:34}],items=[],rem={cap:{yen:0,count:0},yen_left:null,count_left:null},list=[G,W]}={}){
  child='下の子';rewards=list;balance=bal;history=hist;reqs=items;remaining=rem;rules={homework:3};paintAll();
}
function reload(state){ // loadChild の3本（points・rewards は持っている・redeem）
  replies.push({child:'下の子',balance:state.bal,history:state.hist||[],rules:{homework:3}});
  replies.push({items:state.items||[],remaining:state.rem||{cap:{yen:0,count:0},yen_left:null,count_left:null}});
}
'''


def run_js(body):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node がない環境：HTML の契約テストだけ動かす")
    program = HARNESS + JS.removesuffix("\n").rsplit("boot();", 1)[0]
    program += "\n(async()=>{\n" + body + "\n})().catch(e=>{console.error(e);process.exitCode=1});"
    result = subprocess.run([node, "-e", program], text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_meter_is_clamped_and_never_negative():
    run_js(r'''
assert.deepEqual(meter(14,30),{pct:47,left:16});
assert.deepEqual(meter(45,30),{pct:100,left:0});
assert.deepEqual(meter(-5,30),{pct:0,left:35});
assert.deepEqual(meter(null,30),{pct:0,left:null});
''')


def test_card_states_for_every_condition():
    run_js(r'''
const rem={cap:{yen:0,count:0},yen_left:null,count_left:null};
const ctx=(o={})=>({balance:34,reqs:[],remaining:rem,sending:false,uncertain:null,...o});
assert.equal(cardState(G,ctx()).kind,'ready');
assert.equal(cardState(G,ctx()).can,true);
assert.equal(cardState(G,ctx({balance:0})).text,'ポイントを ためているよ');
assert.equal(cardState(G,ctx({balance:29})).kind,'saving');
// 分からないものがあれば申込を止める（0 に置き換えない）
for(const k of ['balance','reqs','remaining']) assert.equal(cardState(G,ctx({[k]:null})).kind,'unknown');
// 月上限は残高不足と区別する
assert.equal(cardState(G,ctx({remaining:{...rem,count_left:0}})).text,'こんげつの もうしこみは おやすみ。おうちの人と はなしてね');
assert.equal(cardState(G,ctx({balance:0,remaining:{...rem,count_left:0}})).kind,'capped');
assert.equal(cardState({label:'本',points:30,yen:800},ctx({remaining:{...rem,yen_left:500}})).kind,'capped');
assert.equal(cardState({label:'本',points:30,yen:400},ctx({remaining:{...rem,yen_left:500}})).kind,'ready');
assert.equal(cardState(G,ctx({remaining:{...rem,yen_left:0}})).kind,'ready');  // 円のない報酬はお金の上限にかからない
// 送信中・送れたか分からないあいだは押せない
assert.equal(cardState(G,ctx({sending:true})).can,false);
assert.equal(cardState(G,ctx({uncertain:{label:'x'}})).can,false);
''')


def test_cards_normal_order_badge_and_numbers_only_on_screen():
    run_js(r'''
load({bal:14,hist:[{title:'こくご',date:'2026-09-28',points:14}]});
assert.deepEqual(cards().map(c=>c.dataset.label),[G.label,W.label]);  // 親の並びのまま
assert.match(card(G.label).textContent,/14 \/ 30 pt/);
assert.match(card(G.label).textContent,/あと16pt/);
assert.match(card(G.label).textContent,/ポイントを ためているよ/);
assert.doesNotMatch(card(G.label).textContent,/もうしこめる/);
assert.equal(card(G.label).querySelectorAll('[data-ask]').length,0);
assert.equal(document.querySelector('#start').hidden,true);
load({bal:34});
assert.match(card(G.label).textContent,/もうしこめる/);
assert.doesNotMatch(card(G.label).textContent,/あと/);  // 差は 0 未満にしない・0 は出さない
assert.match(card(W.label).textContent,/34 \/ 100 pt/);
''')


def test_zero_empty_and_unknown_balance():
    run_js(r'''
load({bal:0,hist:[]});
assert.equal(document.querySelector('#start').hidden,false);
assert.equal(cards().length,2);
load({bal:0,hist:[],list:[]});
assert.equal(text('#rewards'),'ごほうびは おうちの人と きめよう');
load({bal:null,hist:null});
assert.equal(text('#balance'),'—');
assert.match(card(G.label).textContent,/— \/ 30 pt/);
assert.equal(card(G.label).querySelectorAll('button').length,0);
assert.equal(document.querySelector('#start').hidden,true);
''')


def test_request_statuses_and_refund_only_when_confirmed():
    run_js(r'''
const now=new Date().toISOString();
const items=[
 {id:'a',label:G.label,cost:30,status:'requested',at:now},
 {id:'b',label:W.label,cost:100,status:'approved',at:now},
 {id:'c',label:G.label,cost:30,status:'rejected',at:now,decided_at:now,note:'来週 また'},
 {id:'d',label:G.label,cost:30,status:'handed',at:now,handed_at:now},
 {id:'e',label:G.label,cost:30,status:'rejected',at:'2020-01-01',decided_at:'2020-01-02',note:'むかし'},
];
load({bal:4,hist:[],items});
const top=text('#reqs');
assert.match(top,/おうちの人に おくったよ/);
assert.match(top,/おうちの人が OKしたよ/);
assert.match(top,/てわたしを まっているよ/);
assert.match(top,/今回は みおくり/);
assert.match(top,/来週 また/);
assert.doesNotMatch(top,/ポイントは もどったよ/);     // 戻した記録がまだない
assert.doesNotMatch(top,/むかし/);                     // 古い みおくり は上に出さない
assert.doesNotMatch(top,/うけとった/);
assert.equal(document.querySelector('#handed-box').hidden,false);
assert.match(text('#handed'),/ゲームの時間/);
// 戻した記録があれば「もどったよ」
load({bal:34,hist:[{title:'「'+G.label+'」の交換を取りやめ：来週 また',kind:'adjust',points:30,date:now.slice(0,10)}],items});
assert.match(text('#reqs'),/ポイントは もどったよ/);
// 取り消された記録や額の違う記録では言わない
assert.equal(refunded(items[2],[{title:'「'+G.label+'」の交換を取りやめ：x',kind:'adjust',points:30,revoked:true}]),false);
assert.equal(refunded(items[2],[{title:'「'+G.label+'」の交換を取りやめ：x',kind:'adjust',points:10}]),false);
load({bal:34,items:[]});
assert.equal(document.querySelector('#reqs-section').hidden,true);   // 申込がなければ大きな空の欄は作らない
''')


def test_two_tap_request_locks_and_sends_once():
    run_js(r'''
load({bal:34});
await card(G.label).querySelector('[data-ask]').click();
assert.equal(posts().length,0);                          // 1タップ目は広げるだけ
assert.match(card(G.label).textContent,/30ptを つかって もうしこむ/);
assert.match(card(G.label).textContent,/30pt へるよ/);
assert.equal(document.activeElement.dataset.go,'1');
const slow=deferred();
replies.push(()=>slow.promise);
const go=card(G.label).querySelector('[data-go]');
const first=go.click();
assert.equal(sending,true);
assert.equal(card(G.label).querySelector('[data-go]').disabled,true);
assert.equal(card(W.label).querySelectorAll('[data-ask]').length,0);  // 100pt はまだ ためている
await card(G.label).querySelector('[data-go]').click();   // 連打しても
await askFor(G);
assert.equal(posts().length,1);
assert.deepEqual(JSON.parse(posts()[0].options.body),{child:'下の子',label:G.label,cost:30,yen:0});
reload({bal:4,items:[{id:'n',label:G.label,cost:30,status:'requested',at:new Date().toISOString()}]});
slow.resolve({ok:true,status:200,json:async()=>({request:{id:'n'},balance:4})});
await first;
assert.equal(sending,false);
assert.equal(text('#send-note'),'おうちの人に おくったよ');
assert.equal(text('#balance'),'4');
assert.match(text('#reqs'),/おうちの人に おくったよ/);
assert.equal(posts().length,1);
''')


def test_cancel_closes_without_sending():
    run_js(r'''
load({bal:34});
await card(G.label).querySelector('[data-ask]').click();
await card(G.label).buttons.find(b=>b.textContent==='やめる').click();
assert.equal(posts().length,0);
assert.equal(card(G.label).querySelectorAll('[data-go]').length,0);
assert.equal(document.activeElement.dataset.ask,'1');
''')


def test_refused_request_shows_reason_and_reloads():
    run_js(r'''
load({bal:34});
await card(G.label).querySelector('[data-ask]').click();
replies.push({ok:false,status:400,body:{detail:'今月の交換は1回までです。'}});
reload({bal:34,rem:{cap:{yen:0,count:1},yen_left:null,count_left:0}});
await card(G.label).querySelector('[data-go]').click();
assert.equal(text('#send-note'),'もうしこめなかったよ：今月の交換は1回までです。');
assert.match(card(G.label).textContent,/こんげつの もうしこみは おやすみ/);
assert.equal(posts().length,1);
''')


@pytest.mark.parametrize("reply", ["network", "server5xx", "badjson"])
def test_unknown_reply_is_checked_not_resent(reply):
    run_js(r'''
load({bal:34,items:[{id:'old',label:G.label,cost:30,status:'handed',at:'2026-09-01'}]});
await card(G.label).querySelector('[data-ask]').click();
replies.push(REPLY);
// たしかめる：前になかった申込が1件 → 送れた
replies.push({items:[{id:'old',label:G.label,cost:30,status:'handed'},{id:'new',label:G.label,cost:30,status:'requested',at:new Date().toISOString()}]});
reload({bal:4,items:[{id:'new',label:G.label,cost:30,status:'requested',at:new Date().toISOString()}]});
await card(G.label).querySelector('[data-go]').click();
assert.equal(posts().length,1);
assert.equal(text('#send-note'),'おうちの人に おくったよ');
assert.equal(uncertain,null);
'''.replace("REPLY", {"network": "new Error('offline')",
                      "server5xx": "{ok:false,status:502,bad:true}",
                      "badjson": "{ok:true,status:200,bad:true}"}[reply]))


def test_unknown_reply_not_found_and_check_failure():
    run_js(r'''
load({bal:34});
await card(G.label).querySelector('[data-ask]').click();
replies.push(new Error('offline'));
replies.push(new Error('offline'));   // 取り直しも失敗
await card(G.label).querySelector('[data-go]').click();
assert.match(text('#send-note'),/^おくれたか まだ わからないよ/);
assert.equal(document.querySelector('#recheck').hidden,false);
assert.equal(card(G.label).querySelectorAll('[data-ask]').concat(card(G.label).querySelectorAll('[data-go]')).every(b=>b.disabled),true);
await askFor(G);                      // 送り直させない
assert.equal(posts().length,1);
// もういちど たしかめる：申込がない → 送れていなかった
replies.push({items:[]});
reload({bal:34});
await document.querySelector('#recheck').click();
assert.match(text('#send-note'),/^おくれなかったよ/);
assert.equal(uncertain,null);
assert.equal(document.querySelector('#recheck').hidden,true);
assert.equal(card(G.label).querySelector('[data-ask]').disabled,false);
assert.equal(posts().length,1);
''')


def test_late_reply_after_child_switch_is_ignored():
    run_js(r'''
load({bal:34});
await card(G.label).querySelector('[data-ask]').click();
const slow=deferred();
replies.push(()=>slow.promise);
const first=card(G.label).querySelector('[data-go]').click();
// 親が子を切り替えた
document.querySelector('#child').value='上の子';
replies.push({child:'上の子',balance:50,history:[],rules:{}});
replies.push({items:[],remaining:{cap:{yen:0,count:0},yen_left:null,count_left:null}});
showChild();
await new Promise(r=>setImmediate(r));
slow.resolve({ok:true,status:200,json:async()=>({})});
await first;
await new Promise(r=>setImmediate(r));
assert.equal(child,'上の子');
assert.equal(text('#send-note'),'');
assert.equal(text('#balance'),'50');
assert.equal(sending,false);
''')


@pytest.mark.parametrize("role,view,parent", [
    ("child", "?view=parent", False),
    ("child", "", False),
    ("parent", "?view=parent", True),
    ("parent", "", True),
    (None, "?view=parent", True),
    (None, "", False),
])
def test_parent_area_only_for_parent(role, view, parent):
    me = "{ok:false,status:401}" if role is None else "{role:'%s',auth:true,name:'x'}" % role
    run_js(r'''
search=VIEW;
replies.push({children:[{name:'下の子'}]});
replies.push(ME);
await boot();
assert.equal(parentView,PARENT);
assert.equal(document.querySelector('#parent-view').hidden,!PARENT);
assert.equal(document.querySelector('#kid-view').hidden,PARENT);
assert.equal(document.documentElement.dataset.audience,PARENT?'parent':'kid');
'''.replace("VIEW", repr(view)).replace("ME", me).replace("PARENT", "true" if parent else "false"))


def test_parent_reject_needs_reason_and_decisions_reload():
    run_js(r'''
setAudience(true);
load({bal:4,items:[{id:'a',label:G.label,cost:30,status:'requested',at:new Date().toISOString()}]});
const row=document.querySelector('#p-reqs').children[0];
assert.deepEqual(row.buttons.map(b=>b.textContent),['OK','わたした','みおくる']);
await row.buttons.find(b=>b.textContent==='みおくる').click();
const go=row.buttons.find(b=>b.textContent==='みおくる（ポイントを戻す）');
await go.click();
assert.equal(text('#p-note'),'みおくる理由を書いてください');
assert.equal(posts().length,0);
row.querySelector('textarea').value='  来週 また  ';
replies.push({request:{id:'a',status:'rejected'},balance:34});
reload({bal:34,items:[{id:'a',label:G.label,cost:30,status:'rejected',note:'来週 また'}]});
replies.push({days:0});   // loadPace
replies.push({days:null});
await go.click();
assert.deepEqual(JSON.parse(posts()[0].options.body),{id:'a',note:'来週 また'});
assert.equal(posts()[0].url,'/api/redeem/reject');
assert.equal(text('#p-note'),'みおくりにして、ポイントを戻しました');
assert.equal(text('#balance'),'34');
''')
