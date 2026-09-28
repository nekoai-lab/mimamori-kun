"""Issue #20: HTML contracts and browser-free JS behavior, no external services.

The DOM and A/F adapters below are test-only. Node is optional for environments
that only run the HTML/JS structural checks; the default pytest invocation finds
all tests. Browser rendering and real microphone permissions are separate QA.
"""
import json
from html.parser import HTMLParser
from pathlib import Path
import re
import shutil
import subprocess

import pytest

HTML = (Path(__file__).resolve().parents[2] / "static/kid.html").read_text()
JS = HTML.split("<script>")[-1].split("</script>")[0]


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


DOC = Elements()
DOC.feed(HTML)


def test_connection_slots_and_load_order():
    for slot in ("data-appearance-picker", "data-family-nav", "data-profile-menu"):
        assert any(slot in attrs for _, attrs in DOC.tags)
    assert HTML.index('/static/theme.js') < HTML.index('/static/appearance.css')
    assert HTML.index('<dialog') < HTML.index('/static/appearance.js')
    assert 'window.Appearance?.setChild(child)' in JS
    assert 'window.Reading?.render(text,readingPolicy,{contentRole})' in JS
    assert 'getJSON("/api/auth/me").catch(()=>null)' in JS
    assert 'me?.role==="child"||me?.role==="parent"' in JS
    assert 'sel.addEventListener("change",showChild)' in JS
    assert 'sel.addEventListener("who:ready",showChild)' in JS


def test_accessible_initial_actions_and_safe_fallback_navigation():
    ids = {attrs['id']: (tag, attrs) for tag, attrs in DOC.tags if 'id' in attrs}
    for key in ('talk', 'voice', 'bubble', 'close-chat', 'mic', 'send'):
        assert ids[key][0] == 'button'
    assert ids['chat'][0] == 'dialog'
    assert ids['child'][0] == 'select' and 'hidden' in ids['child'][1]
    assert ids['companion-picture'][1]['role'] == 'img'
    assert ids['thread'][1]['role'] == 'log'
    nav = HTML.split('<nav data-family-nav')[1].split('</nav>')[0]
    assert re.findall(r'href="([^"]+)"', nav) == ['/kid', '/?mode=kid', '/reward']
    assert 'aria-current="page"' in nav
    assert 'href="/login?switch=parent"' in HTML
    assert 'やりとりは おうちの人も見られます' in HTML
    assert '#today{display:flex;flex-direction:column' in HTML
    assert 'min-height:48px' in HTML
    assert 'body.large-controls #companion{position:static}' in HTML
    assert 'prefers-reduced-motion:reduce' in HTML
    assert 'data-kid-theme="monochrome"' in HTML


def test_no_optimistic_points_or_settings_http_contract():
    assert 'queueDone' not in JS
    assert 'points+" pt"' in JS
    assert 'companion_name:name' in JS
    assert '/api/appearance' not in JS and '/api/companion' not in JS
    assert 'JSON.stringify({child:s.child,history:requestHistory})' in JS
    assert 'recording=false' in JS and 'rec.abort()' in JS
    assert '明日に送る' in JS and 'renderFrame()' in JS


# Minimal DOM; deliberately no production stubs and no browser/network use.
HARNESS = r'''
const assert = require('node:assert/strict');
class Element {
  constructor(tag='div') { this.tagName=tag; this.children=[]; this.dataset={}; this.attrs={}; this.listeners={}; this.style={}; this.value=''; this.hidden=false; this.disabled=false; this.open=false; this._text=''; this._html=''; this.className='';
    this.classList={add:(...xs)=>{this.className=[...new Set(this.className.split(' ').concat(xs))].join(' ')},remove:(...xs)=>{this.className=this.className.split(' ').filter(x=>!xs.includes(x)).join(' ')},toggle:(x,on)=>{if(on??!this.className.split(' ').includes(x))this.classList.add(x);else this.classList.remove(x)},contains:x=>this.className.split(' ').includes(x)};
  }
  set textContent(x){this._text=String(x);this.children=[];}
  get textContent(){return this._text+this.children.map(x=>x.textContent).join('');}
  set innerHTML(x){this._html=x;this.children=[];}
  get innerHTML(){return this._html;}
  append(...xs){for(const x of xs){this.children.push(x);x.parent=this;}}
  appendChild(x){this.append(x);}
  replaceChildren(...xs){this.children=[];this._text='';this.append(...xs);}
  remove(){if(this.parent)this.parent.children=this.parent.children.filter(x=>x!==this);}
  setAttribute(k,v){this.attrs[k]=String(v);}
  addEventListener(k,fn){(this.listeners[k]??=[]).push(fn);}
  async fire(k){for(const fn of this.listeners[k]||[])await fn({preventDefault(){},target:this});}
  focus(){document.activeElement=this;}
  showModal(){this.open=true;}
  close(){this.open=false;this.fire('close');}
  get lastElementChild(){return this.children.at(-1);}
  get options(){return [...this._html.matchAll(/<option>(.*?)<\/option>/g)].map(x=>({value:x[1]}));}
  matches(s){return s.startsWith('.')?this.className.split(' ').includes(s.slice(1)):this.tagName===s;}
  querySelectorAll(s){return this.children.flatMap(x=>[...(x.matches(s)?[x]:[]),...x.querySelectorAll(s)]);}
  querySelector(s){return this.querySelectorAll(s)[0]||null;}
  closest(s){return this.matches(s)?this:this.parent?.closest(s);}
}
const elements=new Map();
const document={documentElement:new Element('html'),body:new Element('body'),activeElement:null,
 querySelector:s=>{if(!elements.has(s))elements.set(s,new Element());return elements.get(s);},
 querySelectorAll:s=>s==='[data-companion-name]'?[document.querySelector('#name-label')]:[],
 createElement:tag=>new Element(tag)};
const storage=new Map();
const localStorage={getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)};
const window={addEventListener(){}};
const navigator={onLine:true};
const matchMedia=()=>({matches:false});
const setInterval=()=>0, clearInterval=()=>{};
const timers=new Map();let timerID=0;
const setTimeout=fn=>{timers.set(++timerID,fn);return timerID;},clearTimeout=id=>timers.delete(id);
const location={reload(){}};
class DocumentFragment extends Element {}
let replies=[],calls=[];
async function fetch(url,options){calls.push({url,options});if(!replies.length)throw Error('unexpected fetch '+url);const reply=replies.shift();if(typeof reply==='function')return reply(url,options);if(reply instanceof Error)throw reply;return {ok:reply.ok??true,json:async()=>reply.body??reply};}
function deferred(){let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};}
function task(id='one',status='doing'){return {id,status,child:'下の子',summary:'こくご ドリル',date:'2026-09-28',days_left:0,kind:'homework',points:3,minutes:20};}
function setup(){child='下の子';epoch=1;snapshot={items:[task()],points:0,today:'2026-09-28',at:1};stale=false;document.querySelector('#pt').textContent='0 pt';}
function taskReply(items=[],points=3){return {items,points:{'下の子':points},today:'2026-09-28'};}
function weekReply(done=1,start='2026-09-27'){return {child:'下の子',start,done,goal:5};}
'''


def run_js(body):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node unavailable: static contract tests still run')
    # Initialization is exercised explicitly in boot tests.
    program = HARNESS + JS.removesuffix('\n').rsplit('boot();', 1)[0]
    program += '\n(async()=>{\n' + body + '\n})().catch(e=>{console.error(e);process.exitCode=1});'
    result = subprocess.run([node, '-e', program], text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('auth', [401, 404, 'child', 'parent'])
def test_boot_waits_for_who_and_auth_is_optional(auth):
    run_js('''
      replies=[{children:[{name:'下の子',school_level:'elementary'}]}, AUTH, {minutes:90}];
      await boot();
      assert.equal(child,'');
      assert.deepEqual(calls.map(x=>x.url),['/api/config','/api/auth/me','/api/capacity']);
      assert.ok($('#child').listeners['who:ready']);
      assert.ok($('#child').listeners.change);
      if(typeof ROLE==='string')assert.equal(document.body.dataset.audience,ROLE==='parent'?'parent':'kid');
    '''.replace('AUTH', json.dumps({'ok': False} if isinstance(auth, int) else {'role': auth}))
           .replace('ROLE', json.dumps(auth)))


def test_explicit_completion_and_old_child_layout():
    run_js('''
      setup();levels[child]='junior_high';renderCards();
      const row=$('#today').children[0];
      assert.equal(row.tagName,'article');
      assert.equal(row.listeners.click,undefined);
      assert.equal(row.querySelector('.finish').textContent,'おわった');
      assert.equal(row.querySelector('.later').textContent,'明日に送る');
      assert.equal($('#frame').hidden,false);
      assert.ok(row.querySelector('summary').textContent.includes('こくご ドリル'));
    ''')


@pytest.mark.parametrize('response,state', [('{ok:false}', 'error'),
                                          ("{status:'error'}", 'error'),
                                          ("new TypeError('offline')", 'waiting')])
def test_failed_completion_never_claims_done_or_points(response, state):
    run_js('''
      setup();replies=[RESPONSE];finishCard(task());await new Promise(setImmediate);
      assert.equal(jobs.get(jobKey(child,'one')).state,STATE);
      assert.equal($('#pt').textContent,'0 pt');
      assert.equal($('#records-list').children.length,0);
      assert.ok($('#today').textContent.includes('もういちど'));
      assert.equal(calls.length,1);
      assert.equal(thread.children.length,0);
    '''.replace('RESPONSE', response).replace('STATE', json.dumps(state)))


def test_double_tap_and_undo_during_send_restore_doing_in_order():
    run_js('''
      setup();const pending=deferred();replies=[()=>pending.promise];
      finishCard(task());finishCard(task());undoItem(task());
      assert.equal(calls.length,1);
      assert.equal(jobs.get(jobKey(child,'one')).undoRequested,true);
      replies.push({status:'doing'},taskReply([task()],0),weekReply(0));
      pending.resolve({ok:true,json:async()=>({status:'done'})});
      await new Promise(setImmediate);
      const writes=calls.filter(x=>x.options?.method==='POST').map(x=>JSON.parse(x.options.body).status);
      assert.deepEqual(writes,['done','doing']);
      assert.equal(jobs.get(jobKey(child,'one')).state,'restored');
      assert.equal($('#records-list').children.length,0);
      assert.ok($('#today').querySelector('.finish'));
      assert.equal($('#pt').textContent,'0 pt');
    ''')


def test_never_sent_offline_job_can_be_cancelled_locally():
    run_js('''
      setup();navigator.onLine=false;finishCard(task());
      assert.equal(calls.length,0);
      assert.ok($('#today').textContent.includes('おくるのを まっているよ'));
      undoItem(task());assert.equal(jobs.size,0);
      assert.deepEqual(lsGet(OUT_KEY,[]),[]);
      assert.ok($('#today').querySelector('.finish'));
    ''')


def test_retry_serialized_and_success_is_reversible_without_timeout():
    run_js('''
      setup();navigator.onLine=false;finishCard(task());navigator.onLine=true;
      replies=[{status:'done'},taskReply([task('one','done')]),weekReply()];
      await Promise.all([flushOutbox(),flushOutbox()]);
      assert.equal(calls.filter(x=>x.options?.method==='POST').length,1);
      assert.equal($('#pt').textContent,'3 pt');
      assert.ok($('#today').textContent.includes('きょうのぶん おわったね'));
      assert.ok($('#records-list').textContent.includes('もどす'));
      assert.equal($('#records').open,true);
      assert.deepEqual(lsGet(OUT_KEY,[]),[]);
    ''')


def test_undo_failure_keeps_confirmed_done():
    run_js('''
      setup();snapshot.items=[task('one','done')];replies=[{ok:false}];
      undoItem(snapshot.items[0]);await new Promise(setImmediate);
      assert.ok($('#records-list').textContent.includes('まだ もどせていないよ'));
      assert.equal($('#today').querySelector('.finish'),null);
    ''')


def test_child_switch_discards_late_reads_even_when_switching_back():
    run_js('''
      setup();const pending=deferred();replies=[()=>pending.promise];
      const load=loadCards();epoch+=2;
      $('#pt').textContent='— pt';
      pending.resolve({ok:true,json:async()=>taskReply([task()],999)});await load;
      assert.equal($('#pt').textContent,'— pt');
      assert.equal(storage.has(CACHE_KEY+':'+child),false);
    ''')


def test_empty_error_and_cache_are_distinct_and_child_scoped():
    run_js('''
      setup();replies=[taskReply([],0)];await loadCards();
      assert.ok($('#today').textContent.includes('きょうは やることないよ'));
      replies=[{ok:false}];await loadCards();
      assert.ok($('#load-note').textContent.includes('前にひらいたとき'));
      assert.equal($('#pt').textContent,'— pt');
      assert.ok(!$('#today').textContent.includes('おわったね'));
      child='上の子';epoch++;replies=[{ok:false}];await loadCards();
      assert.ok($('#load-note').textContent.includes('よみこめなかったよ'));
      assert.equal($('#today').children.length,0);
    ''')


def test_week_completion_once_per_child_and_week_and_not_on_revisit():
    run_js('''
      setup();let celebrations=0;confetti=()=>celebrations++;
      for(const n of [4,5,5,4,5]){replies=[weekReply(n)];await loadBoard();}
      assert.equal(celebrations,1);
      replies=[weekReply(5,'2026-10-04')];await loadBoard();
      assert.equal(celebrations,1);
      weekStates.clear();replies=[weekReply(5)];await loadBoard();
      assert.equal(celebrations,1);
      replies=[{ok:false}];await loadBoard();
      assert.ok($('#board').textContent.includes('だいしを よみこめなかったよ'));
    ''')


def test_name_adapter_is_child_scoped_patch_and_unconnected_is_unsaved():
    run_js('''
      setup();$('#companion-input').value='まる';await $('#name-form').fire('submit');
      assert.ok($('#name-status').textContent.includes('まだ覚えられていない'));
      const writes=[];
      window.CompanionStore={read:async key=>({companion_name:'まる'}),write:async(key,patch)=>writes.push({key,patch})};
      await loadName();await $('#name-form').fire('submit');
      assert.deepEqual(writes,[{key:'下の子',patch:{companion_name:'まる'}}]);
      assert.ok($('#name-status').textContent.includes('おぼえたよ'));
      const wait=deferred();window.CompanionStore.read=()=>wait.promise;
      const load=loadName();epoch++;child='上の子';companionName='まる';
      wait.resolve({companion_name:'古い応答'});await load;
      assert.equal(companionName,'まる');
    ''')


def test_chat_open_does_not_record_and_voice_fallback_is_visible():
    run_js('''
      setup();openChat($('#talk'));assert.equal(recording,false);
      assert.equal($('#chat').open,true);assert.equal(calls.length,0);
      startRecognition();assert.ok($('#mic-status').textContent.includes('文字で書いてね'));
      $('#chat').close();assert.equal(document.activeElement,$('#talk'));
      assert.equal(recording,false);
    ''')


def test_chat_failure_retry_does_not_duplicate_history():
    run_js('''
      setup();replies=[{ok:false}];await send('こんにちは');
      assert.deepEqual(history,[]);assert.equal($('#retry-chat').hidden,false);
      replies=[{text:'きたね！',tools:[]}];await send('こんにちは',true);
      assert.equal(history.length,2);
      assert.deepEqual(JSON.parse(calls[1].options.body),{child:'下の子',history:[{role:'user',text:'こんにちは'}]});
    ''')


def test_appearance_stub_runs_once_after_child_ready_without_changing_chat():
    run_js('''
      const selected=[];window.Appearance={setChild:key=>selected.push(key)};
      window.CompanionStore={read:async()=>({companion_name:'まる'})};
      $('#child').value='下の子';
      replies=[taskReply([task()],0),weekReply(0)];
      showChild();showChild();await new Promise(setImmediate);
      assert.deepEqual(selected,['下の子']);
      assert.equal(calls.filter(x=>x.url==='/api/tasks').length,1);
      assert.equal(calls.filter(x=>x.url==='/api/kid/chat').length,0);
      assert.equal($('#child-name').textContent,'下の子');
      assert.equal($('#pt').textContent,'0 pt');
    ''')


def test_postpone_reload_does_not_allow_duplicate_or_completion():
    run_js('''
      setup();levels[child]='junior_high';renderCards();
      const pending=deferred();replies=[()=>pending.promise];
      const operation=postpone(task(),$('#today').querySelector('.later'));
      renderCards();
      const later=$('#today').querySelector('.later');
      assert.equal(later.disabled,true);
      await postpone(task(),later);finishCard(task());
      assert.equal(calls.length,1);
      replies=[taskReply([],0)];
      pending.resolve({ok:true,json:async()=>({id:'one',date:'2026-09-29'})});
      await operation;
      assert.equal(moving.size,0);
      assert.equal($('#today').querySelector('.finish'),null);
    ''')


def test_speech_starts_on_voice_click_and_stops_on_close():
    # A recognition stub is installed before page initialization so the same
    # SR feature detection as production selects it.
    global HARNESS
    base = HARNESS
    try:
        HARNESS += r'''
        let starts=0,aborts=0;
        window.SpeechRecognition=class {
          start(){starts++;this.onstart?.();}
          abort(){aborts++;}
        };
        '''
        run_js('''
          setup();await $('#talk').fire('click');assert.equal(starts,0);
          $('#chat').close();await $('#voice').fire('click');
          assert.equal(starts,1);assert.equal(recording,true);
          assert.ok($('#mic-status').textContent.includes('きいているよ'));
          $('#chat').close();assert.equal(recording,false);assert.ok(aborts>0);
          assert.equal($('#mic').attrs['aria-pressed'],'false');
        ''')
    finally:
        HARNESS = base


def test_record_undo_after_reload_preserves_previous_doing():
    run_js('''
      setup();replies=[{status:'done'},taskReply([task('one','done')]),weekReply()];
      finishCard(task());await new Promise(setImmediate);
      jobs.clear(); // reload: server record remains, transient job is gone
      replies=[{status:'doing'},taskReply([task()],0),weekReply(0)];
      undoItem(task('one','done'));await new Promise(setImmediate);
      const statuses=calls.filter(x=>x.options?.method==='POST').map(x=>JSON.parse(x.options.body).status);
      assert.deepEqual(statuses,['done','doing']);
    ''')
