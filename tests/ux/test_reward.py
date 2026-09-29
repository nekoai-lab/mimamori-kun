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
  constructor(tag='div'){this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.attrs={};this.listeners={};this.style={setProperty(k,v){this[k]=v;}};this.value='';this.hidden=false;this.disabled=false;this._text='';this.className='';this.parent=null;
    this.classList={add:(...xs)=>{this.className=[...new Set(this.className.split(' ').filter(Boolean).concat(xs))].join(' ')},remove:(...xs)=>{this.className=this.className.split(' ').filter(x=>!xs.includes(x)).join(' ')},toggle:(x,on)=>{if(on??!this.classList.contains(x))this.classList.add(x);else this.classList.remove(x)},contains:x=>this.className.split(' ').includes(x)};}
  set textContent(x){this._text=String(x);this.children=[];}
  get textContent(){return this._text+this.children.map(x=>x.textContent).join('');}
  set innerHTML(x){this._html=x;this.children=[];}
  get innerHTML(){return this._html||'';}
  append(...xs){for(const x of xs){this.children.push(x);x.parent=this;}}
  appendChild(x){this.append(x);return x;}
  replaceChildren(...xs){if(this.all.includes(document.activeElement))document.activeElement=document.body;this.children=[];this._text='';this.append(...xs);}
  remove(){if(this.parent)this.parent.children=this.parent.children.filter(x=>x!==this);}
  setAttribute(k,v){this.attrs[k]=String(v);}
  getAttribute(k){return this.attrs[k]??null;}
  addEventListener(k,fn){(this.listeners[k]??=[]).push(fn);}
  async click(){for(const fn of this.listeners.click||[])await fn({target:this});}
  focus(){document.activeElement=this;}
  scrollIntoView(options){this.scrolled=options;}
  getBoundingClientRect(){return {height:this.height??60};}
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
const store=new Map();
const localStorage={getItem:k=>store.get(k)??null,setItem:(k,v)=>store.set(k,String(v))};
let search='';
const location={pathname:'/reward',hash:'#main',get search(){return search;}};
let replies=[],calls=[],routes=null;
async function fetch(url,options){calls.push({url,options});if(!replies.length&&!routes?.[url]?.length)throw Error('unexpected fetch '+url);const r=routes?.[url]?.length?routes[url].shift():replies.shift();if(typeof r==='function')return r(url,options);if(r instanceof Error)throw r;return {ok:r.ok??true,status:r.status??200,json:async()=>{if(r.bad)throw Error('bad json');return r.body??r;}};}
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
assert.equal(card(G.label).querySelector('[data-go]'),null);
assert.equal(card(W.label).querySelectorAll('[data-ask]').length,0);  // 100pt はまだ ためている
await go.click();   // 古いボタンから連打しても
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
replies.push(new Error('offline'),new Error('offline'));   // 残高と申込の取り直しも失敗
await card(G.label).querySelector('[data-go]').click();
assert.match(text('#send-note'),/^おくれたか まだ わからないよ/);
assert.equal(document.querySelector('#recheck').hidden,false);
assert.equal(card(G.label).querySelectorAll('[data-ask]').concat(card(G.label).querySelectorAll('[data-go]')).every(b=>b.disabled),true);
await askFor(G);                      // 送り直させない
assert.equal(posts().length,1);
// もういちど たしかめる：申込がない → 送れていなかった
reload({bal:34});
await document.querySelector('#recheck').click();
// 見つからなくても、まだ処理中かもしれない：送れていないとは決めない（コードレビュー #41）
assert.equal(text('#send-note'),'まだ みつからないよ。すこし まってから「もういちど たしかめる」を おしてね。');
assert.ok(uncertain);
assert.equal(card(G.label).querySelector('[data-ask]'),null);
await askFor(G);
assert.equal(posts().length,1);
// 再読込しても（端末に覚えている）止まったまま
assert.ok(JSON.parse(localStorage.getItem('mimamori-reward-pending'))['kid:下の子']);
// サーバーの処理が終わるはずの時間をこえても見つからなければ、送れていない
lastSent.at-=SETTLE_MS;
reload({bal:34});
await document.querySelector('#recheck').click();
assert.match(text('#send-note'),/^おくれなかったよ/);
assert.equal(JSON.parse(localStorage.getItem('mimamori-reward-pending'))['kid:下の子'],undefined);
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
    (None, "?view=parent", False),
    (None, "", False),
    # 認証が無効な環境の実際の返事（role:"parent"・auth:false）
    ("noauth", "?view=parent", True),
    ("noauth", "", False),
])
def test_parent_area_only_for_parent(role, view, parent):
    me = ("{ok:false,status:401}" if role is None else
          "{role:'parent',auth:false,name:'',user:''}" if role == "noauth" else
          "{role:'%s',auth:true,name:'x'}" % role)
    run_js(r'''
search=VIEW;
routes={'/api/auth/me':[ME],'/api/config':[{children:[{name:'下の子'}]}]};
await boot();
assert.equal(parentView,PARENT);
assert.equal(document.querySelector('#parent-view').hidden,!PARENT);
assert.equal(document.querySelector('#kid-view').hidden,UNAUTH||PARENT);
assert.equal(document.documentElement.dataset.audience,PARENT?'parent':'kid');
'''.replace("VIEW", repr(view)).replace("ME", me).replace("UNAUTH", "true" if role is None else "false").replace("PARENT", "true" if parent else "false"))


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


@pytest.mark.parametrize("status", ["approved", "handed", "rejected"])
def test_unknown_reply_matches_request_already_decided_by_parent(status):
    # QA #41：たしかめるまでに親が決めていても「送れた」。「おくれなかったよ」で再申込させない
    run_js(r'''
load({bal:100});
await card(G.label).querySelector('[data-ask]').click();
replies.push(new Error('offline'));
reload({bal:70,items:[{id:'new',label:G.label,cost:30,status:STATUS,at:new Date().toISOString()}]});
await card(G.label).querySelector('[data-go]').click();
assert.equal(text('#send-note'),KID_ST[STATUS]);
assert.equal(posts().length,1);
'''.replace("STATUS", repr(status)))


def test_match_sent_ignores_known_and_other_rewards():
    run_js(r'''
const sent={label:G.label,cost:30};
assert.equal(matchSent(['a'],[{id:'a',label:G.label,cost:30,status:'requested'}],sent),0);
assert.equal(matchSent([],[{id:'b',label:W.label,cost:100,status:'requested'}],sent),0);
assert.equal(matchSent([],[{id:'c',label:G.label,cost:20,status:'requested'}],sent),0);
assert.equal(matchSent([],[{id:'d',label:G.label,cost:30,status:'approved'}],sent),1);
''')


def test_refund_is_not_claimed_from_an_earlier_rejection():
    run_js(r'''
const day='2026-09-29';
const now={id:'n',label:G.label,cost:30,status:'rejected',note:'今週は なし',decided_at:day+'T10:00:00+09:00'};
const old={id:'o',label:G.label,cost:30,status:'rejected',note:'先月は なし',decided_at:'2026-08-01T10:00:00+09:00'};
const refund=(note,date)=>({kind:'adjust',points:30,title:'「'+G.label+'」の交換を取りやめ：'+note,date});
// 前の見送りの記録だけ → 今回は言わない
assert.equal(refunded(now,[refund('先月は なし','2026-08-01')],[now,old]),false);
assert.equal(refunded(now,[refund('今週は なし',day)],[now,old]),true);
// 見送りの日より前の記録は数えない
assert.equal(refunded(now,[refund('今週は なし','2026-09-01')],[now]),false);
// 同じ報酬・同じ理由の見送りが2件で、記録が1件 → 言わない
const twin={...now,id:'t'};
assert.equal(refunded(now,[refund('今週は なし',day)],[now,twin]),false);
assert.equal(refunded(now,[refund('今週は なし',day),refund('今週は なし',day)],[now,twin]),true);
''')


def test_parent_decision_lock_holds_until_reload_and_unknown_blocks_that_request():
    run_js(r'''
setAudience(true);
const item={id:'a',label:G.label,cost:30,status:'requested',at:new Date().toISOString()};
const other={id:'b',label:W.label,cost:100,status:'requested',at:new Date().toISOString()};
load({bal:4,items:[item,other]});
const btn=(i,label)=>document.querySelector('#p-reqs').children[i].buttons.find(b=>b.textContent===label);
replies.push(new Error('offline'));                  // OK の返事が消えた
const slow=deferred();
replies.push(()=>slow.promise);                      // 読み直しの points が遅い
replies.push({items:[item,other],remaining:{cap:{yen:0,count:0},yen_left:null,count_left:null}});
replies.push({days:null}); replies.push({days:null});   // loadPace
const first=btn(0,'OK').click();
await new Promise(r=>setImmediate(r));
// 読み直しが終わるまで、どの申込のボタンも押せない・押しても送らない
assert.equal(deciding,true);
assert.equal(btn(1,'OK').disabled,true);
await decide('approve','a');
await decide('approve','b');
assert.equal(posts().length,1);
slow.resolve({ok:true,status:200,json:async()=>({child:'下の子',balance:4,history:[],rules:{}})});
await first;
for(let i=0;i<5;i++) await new Promise(r=>setImmediate(r));   // めやす（loadPace）の取得を終わらせる
assert.equal(deciding,false);
// 状態が変わっていない（requested のまま）ので、この申込は操作させない。ほかの申込は操作できる
const row0=document.querySelector('#p-reqs').children[0];
assert.equal(row0.buttons.map(b=>b.textContent).join(','),'読み直す');
assert.match(row0.textContent,/送れたか確かめています/);
assert.equal(btn(1,'OK').disabled,false);
assert.match(text('#p-note'),/送れたか分かりません/);
// 読み直して状態が変わっていたら、ロックを外す
reload({bal:4,items:[{...item,status:'approved'},other]});
replies.push({days:null}); replies.push({days:null});
await row0.buttons[0].click();
for(let i=0;i<5;i++) await new Promise(r=>setImmediate(r));
assert.deepEqual(document.querySelector('#p-reqs').children[0].buttons.map(b=>b.textContent),['わたした','みおくる']);
''')


def test_over_cap_is_not_shown_as_negative():
    run_js(r'''
setAudience(true);
load({bal:4,items:[],rem:{cap:{yen:1000,count:2},yen_left:-500,count_left:-1}});
assert.equal(text('#left'),'今月の上限を 500円 こえています／今月の回数を 1回 こえています');
load({bal:4,items:[],rem:{cap:{yen:1000,count:2},yen_left:300,count_left:1}});
assert.equal(text('#left'),'今月あと 300円／あと 1回');
''')


@pytest.mark.parametrize("reply", [
    "{ok:false,status:401}", "{ok:false,status:500}", "new Error('offline')",
    "{bad:true}", "{}", "{auth:true,role:'unexpected'}", "{role:'parent'}",
])
def test_auth_failure_hides_parent_actions_and_retry_restores_role(reply):
    run_js(r'''
search='?view=parent';
routes={'/api/auth/me':[REPLY],'/api/config':[{children:[{name:'下の子'}]}]};
await boot();
assert.equal(document.querySelector('#parent-view').hidden,true);
assert.equal(parentView,false);
assert.notEqual(document.querySelector('#to-parent').href,'/reward?view=parent');
assert.equal(calls.length,1);  // 未確認のまま設定や残高を読まない
if(REPLY401){
  assert.equal(location.href,'/login?next='+encodeURIComponent('/reward?view=parent#main'));
}else{
  assert.equal(text('#error'),'だれが つかっているか たしかめられないよ');
  assert.equal(document.querySelector('#auth-retry').hidden,false);
  for(const role of ['parent','child']){
    routes={'/api/auth/me':[{auth:true,role,name:'下の子'}],'/api/config':[{children:[{name:'下の子'}]}]};
    rewards=[G,W];
    reload({bal:100});
    if(role==='parent') replies.push({days:0},{days:0});
    await document.querySelector('#auth-retry').click();
    for(let i=0;i<5;i++) await new Promise(r=>setImmediate(r));
    assert.equal(parentView,role==='parent');
    assert.equal(document.querySelector('#parent-view').hidden,role!=='parent');
    assert.equal(document.querySelector('#kid-view').hidden,role==='parent');
    assert.equal(document.querySelector('#auth-retry').hidden,true);
  }
}
'''.replace("REPLY401", "true" if "401" in reply else "false").replace("REPLY", reply))


@pytest.mark.parametrize("outcome", ["requested", "approved", "handed", "rejected", "multiple", "missing", "failed"])
def test_uncertain_card_reconciliation_and_actual_status(outcome):
    run_js(r'''
load({bal:200});
uncertain={label:W.label,cost:100};
lastSent={sent:uncertain,before:['old'],at:Date.now()};
pendingSet('kid:'+child,lastSent);
paintCards();
for(const c of cards()){
  assert.doesNotMatch(c.textContent,/もうしこめる|もうしこむ/);
  assert.match(c.textContent,/おくれたか たしかめているよ/);
  assert.ok(c.querySelector('h3'));
  assert.ok(c.querySelector('.meter'));
}
const outcome=OUTCOME;
const item={id:'new',label:W.label,cost:100,status:outcome,at:new Date().toISOString()};
const unresolved=['multiple','missing','failed'].includes(outcome);
const items=outcome==='multiple'?[{...item,status:'requested'},{...item,id:'other',status:'approved'}]:outcome==='missing'?[]:[item];
if(outcome==='multiple') lastSent.at-=SETTLE_MS;  // 時間が過ぎても複数候補なら解除しない
if(outcome==='failed') replies.push(new Error('offline'),new Error('offline'));
else reload({bal:100,items});
await recheck();
assert.equal(posts().length,0);
assert.equal(!!uncertain,unresolved);
assert.equal(document.querySelector('#recheck').hidden,!unresolved);
assert.equal(!!pendingGet('kid:'+child),unresolved);
if(unresolved){
  assert.doesNotMatch(text('#rewards'),/もうしこめる|もうしこむ/);
  await askFor(W);
  assert.equal(posts().length,0);
}else assert.equal(text('#send-note'),KID_ST[outcome]);
'''.replace("OUTCOME", repr(outcome)))


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("outcome", ["success", "refused", "unknown", "recheck_failed", "reload_failed"])
def test_request_result_keeps_focus_and_scrolls_from_each_card(index, outcome):
    run_js(r'''
load({bal:200});
const reward=[G,W][INDEX];
await card(reward.label).querySelector('[data-ask]').click();
const go=card(reward.label).querySelector('[data-go]');
go.focus();
const outcome=OUTCOME;
if(outcome==='unknown'||outcome==='recheck_failed'){
  replies.push(new Error('offline'));
  if(outcome==='unknown') reload({bal:200});
  else replies.push(new Error('offline'),new Error('offline'));
}else{
  replies.push(outcome==='refused'?{ok:false,status:400,body:{detail:'上限'}}:{request:{id:'a'}});
  if(outcome==='reload_failed') replies.push(new Error('offline'),new Error('offline'));
  else reload({bal:100});
}
await go.click();
assert.equal(document.activeElement,document.querySelector('#send-note'));
assert.notEqual(document.activeElement,document.body);
assert.ok(text('#send-note'));
assert.equal(document.activeElement.scrolled.block,'start');
assert.match(HTML_STYLE,/scroll-margin-block:16px calc\(var\(--nav-space,88px\) \+ 16px\)/);
'''.replace("INDEX", str(index)).replace("OUTCOME", repr(outcome)).replace("HTML_STYLE", repr(HTML.split('</style>')[0])))


@pytest.mark.parametrize("action", ["approve", "hand", "reject"])
@pytest.mark.parametrize("outcome", ["success", "refused", "unknown", "reload_failed"])
def test_parent_decision_result_keeps_focus(action, outcome):
    run_js(r'''
setAudience(true);
load({bal:100,items:[{id:'a',label:G.label,cost:30,status:'requested'}]});
const row=document.querySelector('#p-reqs').children[0];
const action=ACTION, outcome=OUTCOME;
let go=row.buttons.find(b=>b.textContent===({approve:'OK',hand:'わたした',reject:'みおくる'}[action]));
if(action==='reject'){
  await go.click();
  row.querySelector('textarea').value='また今度';
  go=row.buttons.find(b=>b.textContent==='みおくる（ポイントを戻す）');
}
go.focus();
replies.push(outcome==='unknown'?new Error('offline'):outcome==='refused'?{ok:false,status:400,body:{detail:'できませんでした'}}:{request:{id:'a'}});
if(outcome==='reload_failed') replies.push(new Error('offline'),new Error('offline'));
else reload({bal:100});
replies.push({days:0},{days:0});
await go.click();
assert.equal(document.activeElement,document.querySelector('#p-note'));
assert.ok(text('#p-note'));
assert.equal(document.activeElement.scrolled.block,'start');
'''.replace("ACTION", repr(action)).replace("OUTCOME", repr(outcome)))


@pytest.mark.parametrize("parent", [False, True])
@pytest.mark.parametrize("unknown", [False, True])
def test_slow_response_does_not_take_focus_from_another_control(parent, unknown):
    run_js(r'''
setAudience(PARENT);
load({bal:200,items:[{id:'a',label:G.label,cost:30,status:'requested'}]});
const slow=deferred();
replies.push(()=>slow.promise);
let work;
if(PARENT) work=decide('approve','a');
else{
  await card(W.label).querySelector('[data-ask]').click();
  work=card(W.label).querySelector('[data-go]').click();
}
const elsewhere=document.querySelector('#theme');
elsewhere.focus();
reload({bal:100});
if(PARENT) replies.push({days:0},{days:0});
slow.resolve({ok:!UNKNOWN,status:UNKNOWN?500:200,json:async()=>({})});
await work;
assert.equal(document.activeElement,elsewhere);
assert.equal(elsewhere.scrolled,undefined);
'''.replace("PARENT", str(parent).lower()).replace("UNKNOWN", str(unknown).lower()))


@pytest.mark.parametrize("height,viewport", [(145, 568), (80, 667), (180, 375), (60, 900)])
def test_nav_padding_tracks_measured_height_and_flow_policy(height, viewport):
    run_js(r'''
const nav=document.querySelector('#nav');
nav.height=HEIGHT; window.innerHeight=VIEWPORT;
placeNav();
const space=parseFloat(document.documentElement.style['--nav-space']);
if(HEIGHT>VIEWPORT*.3){
  assert.equal(document.body.classList.contains('nav-in-flow'),true);
  assert.equal(space,0);
}else{
  assert.equal(document.body.classList.contains('nav-in-flow'),false);
  assert.ok(space>=HEIGHT+6); // 最後のリンクのフォーカス枠もナビより上へ
}
nav.height=70; window.innerHeight=667;
placeNav();
assert.equal(document.body.classList.contains('nav-in-flow'),false);
assert.ok(parseFloat(document.documentElement.style['--nav-space'])>=70);
'''.replace("HEIGHT", str(height)).replace("VIEWPORT", str(viewport)))


def test_recheck_cannot_overlap_or_resend_while_waiting():
    run_js(r'''
load({bal:200});
uncertain={label:W.label,cost:100};
lastSent={sent:uncertain,before:[],at:Date.now()};
const slow=deferred();
replies.push(()=>slow.promise,{items:[],remaining:{}});
const first=recheck();
assert.equal(document.querySelector('#recheck').disabled,true);
await recheck();
await askFor(W);
assert.equal(calls.length,2);  // 残高と申込を各1回だけ取得
assert.equal(posts().length,0);
slow.resolve({ok:true,json:async()=>({balance:200,history:[]})});
await first;
assert.equal(document.querySelector('#recheck').disabled,false);
assert.ok(uncertain);
assert.doesNotMatch(text('#rewards'),/もうしこめる|もうしこむ/);
''')


@pytest.mark.parametrize("reverse_ready", [False, True])
def test_cap_saves_are_serial_and_keep_latest_value(reverse_ready):
    run_js(r'''
setAudience(true);
load({list:[]});
const firstReply=deferred(), secondReply=deferred();
let server={yen:0,count:5}, active=0, peak=0;
const received=[];
const response=()=>({ok:true,status:200,json:async()=>({})});
const save=gate=>async(url,options)=>{
  active++; peak=Math.max(peak,active);
  const cap=JSON.parse(options.body); received.push(cap);
  await gate.promise;
  server=cap; active--;
  return response();
};
// 2本目が先に応答できる状態でも、1本目が終わるまで送信しない。
routes={
  '/api/redeem/cap':[save(firstReply),save(secondReply)],
};
routes['/api/points?child='+encodeURIComponent(child)]=[{balance:34},{balance:34}];
const read=async()=>({ok:true,json:async()=>({items:[],remaining:{cap:{...server}}})});
routes['/api/redeem?child='+encodeURIComponent(child)]=[read,read];
document.querySelector('#capcount').value='0';
const first=saveCap();
document.querySelector('#capcount').value='2';
const second=saveCap();
assert.equal(document.querySelector('#capcount').disabled,false);
assert.equal(document.querySelector('#capyen').disabled,false);
assert.equal(posts().length,1);
assert.equal(text('#capnote'),'保存しています');
if(REVERSE) secondReply.resolve();
firstReply.resolve();
await new Promise(r=>setImmediate(r));
assert.equal(posts().length,2);
assert.equal(Number(document.querySelector('#capcount').value),2);
if(!REVERSE){
  assert.equal(text('#capnote'),'保存しています');
  secondReply.resolve();
}
await first;
await second;
assert.equal(peak,1);
assert.deepEqual(received,[{yen:0,count:0},{yen:0,count:2}]);
assert.deepEqual(server,{yen:0,count:2});
assert.deepEqual(remaining.cap,server);
assert.equal(Number(document.querySelector('#capcount').value),server.count);
assert.equal(text('#capnote'),'保存しました');
'''.replace("REVERSE", str(reverse_ready).lower()))


@pytest.mark.parametrize("phase", ["post", "reload"])
def test_cap_changes_while_saving_send_only_latest(phase):
    run_js(r'''
setAudience(true);
load({list:[]});
const slow=deferred();
const ok={ok:true,json:async()=>({})};
if(PHASE==='post') replies.push(()=>slow.promise);
else replies.push({});
if(PHASE==='reload') replies.push(()=>slow.promise);
else replies.push({balance:34});
replies.push({items:[],remaining:{cap:{yen:0,count:0}}});
replies.push({});
reload({bal:34,rem:{cap:{yen:500,count:2}}});
document.querySelector('#capcount').value='0';
const work=saveCap();
await new Promise(r=>setImmediate(r));
document.querySelector('#capcount').value='1'; await saveCap();
document.querySelector('#capcount').value='2'; await saveCap();
document.querySelector('#capyen').value='500'; await saveCap();
assert.equal(posts().length,1);
slow.resolve(PHASE==='post'?ok:{ok:true,json:async()=>({balance:34})});
await work;
assert.deepEqual(posts().map(c=>JSON.parse(c.options.body)),[{yen:0,count:0},{yen:500,count:2}]);
assert.equal(Number(document.querySelector('#capyen').value),500);
assert.equal(Number(document.querySelector('#capcount').value),2);
assert.deepEqual(remaining.cap,{yen:500,count:2});
assert.equal(text('#capnote'),'保存しました');
'''.replace("PHASE", repr(phase)))


@pytest.mark.parametrize("outcome", ["count_mismatch", "yen_mismatch", "missing", "read_failed", "editing"])
def test_cap_success_requires_readback_matching_inputs(outcome):
    run_js(r'''
setAudience(true);
load({list:[]});
const slow=deferred();
replies.push(()=>slow.promise);
document.querySelector('#capyen').value='500';
document.querySelector('#capcount').value='2';
const work=saveCap();
const outcome=OUTCOME;
if(outcome==='read_failed') replies.push({balance:34},new Error('offline'));
else reload({bal:34,rem:outcome==='missing'?{}:{cap:{yen:outcome==='yen_mismatch'?0:500,count:outcome==='count_mismatch'?0:2}}});
// change（blur）前の入力も、読み直しで消さず画面の値と照合する。
if(outcome==='editing') document.querySelector('#capcount').value='3';
slow.resolve({ok:true,json:async()=>({})});
await work;
assert.match(text('#capnote'),/^保存できたか分かりません/);
assert.equal(Number(document.querySelector('#capyen').value),500);
assert.equal(Number(document.querySelector('#capcount').value),outcome==='editing'?3:2);
'''.replace("OUTCOME", repr(outcome)))


@pytest.mark.parametrize("status", [400, 403, 422])
def test_cap_rejected_save_reports_failure_and_allows_next_save(status):
    run_js(r'''
setAudience(true);
load({list:[]});
document.querySelector('#capcount').value='2';
replies.push({ok:false,status:STATUS,body:{detail:'上限を保存できません'}});
await saveCap();
assert.match(text('#capnote'),/^保存できませんでした/);
replies.push({});
reload({bal:34,rem:{cap:{yen:0,count:2}}});
await saveCap();
assert.equal(posts().length,2);
assert.equal(text('#capnote'),'保存しました');
'''.replace("STATUS", str(status)))
