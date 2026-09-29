"""#59: 既存の DOM/fetch ハーネスで親の確定フローと撮る画面を検証する。"""
import pytest

from test_board import run_js as board
from test_capture import run_js as capture

SETUP = r'''
const q={id:'q',state:'waiting',title:'運動会',child:'上の子',date_text:'再来週の土曜日'};
setDefaults({...tasks([task()]),today:'2026-09-29',date_questions:[q]}, {items:[]});
await load(); calls.length=0;
const area=el('#dateQuestions');
const press=async(action,attr='')=>{const b=area.querySelector('[data-date-action="'+action+'"]'+attr);assert.ok(b,action);await b.click();};
const month=async n=>{const b=area.querySelectorAll('[data-date-action="month"]').find(b=>b.dataset.month===String(n));assert.ok(b);await b.click();};
const day=async n=>{const b=area.querySelectorAll('[data-date-action="day"]').find(b=>b.dataset.day===String(n));assert.ok(b);await b.click();};
'''


def test_choose_reselect_summary_correct_then_register():
    board(SETUP + r'''
assert.match(el('#headline').textContent,/確認すること 2件/);
assert.match(area.innerHTML,/プリントには「再来週の土曜日」とあるよ。何月何日？/);
await month(10);await day(3);
assert.match(area.innerHTML,/10月3日（土）で いい？/);
await press('reselect');await month(10);await day(3);await press('ok');
assert.match(area.innerHTML,/これで とうろくする？/);
assert.equal(calls.length,0);
await press('reset');await month(10);await day(4);await press('ok');
assert.match(area.innerHTML,/10月4日（日）/);assert.equal(calls.length,0);
responses.set('/api/date_questions/q/register',[reply({state:'registered',results:[{status:'ok',id:'new'}]})]);
await press('register');
assert.equal(calls.length,1);assert.equal(calls[0].body.date,'2026-10-04');
assert.equal(calls[0].url,'/api/date_questions/q/register');
assert.equal(area.innerHTML,'');
''')


def test_month_order_invalid_days_and_layout_contract():
    board(SETUP + r'''
const months=area.querySelectorAll('[data-date-action="month"]');
assert.equal(months.length,12);
assert.equal(months[0].dataset.month,'9');assert.equal(months[11].dataset.month,'8');
assert.equal(months[11].dataset.year,'2027');
await month(2);
assert.equal(area.querySelectorAll('[data-date-action="day"]').length,31);
for(const n of [29,30,31])assert.ok(area.querySelectorAll('[data-date-action="day"]').find(b=>b.dataset.day===String(n)).disabled);
await day(30);assert.equal(dateDrafts.get('q').step,'day');
await press('reselect');await month(4);
assert.ok(area.querySelectorAll('[data-date-action="day"]').find(b=>b.dataset.day==='31').disabled);
assert.match(boardCSS,/grid-template-columns:repeat\(7,minmax\(44px,1fr\)\)/);
assert.match(boardCSS,/min-height:44px/);
assert.match(boardCSS,/max-width:360px/);
assert.ok(boardHTML.indexOf('id="dateQuestions"')<boardHTML.indexOf('id="exceptions"'));
assert.equal(calls.length,0);
''')


def test_range_asks_start_end_and_blocks_reverse():
    board(SETUP + r'''
q.date_is_range=true;renderDateQuestions();
assert.match(area.innerHTML,/いつから/);
await month(10);await day(3);await press('ok');
assert.match(area.innerHTML,/いつまで/);
await month(10);await day(2);await press('ok');
assert.match(area.innerHTML,/以降の日付/);assert.equal(calls.length,0);
await month(10);await day(5);await press('ok');
assert.match(area.innerHTML,/10月3日（土） 〜 10月5日（月）/);
responses.set('/api/date_questions/q/register',[reply({state:'registered'})]);
await press('register');assert.equal(calls[0].body.end_date,'2026-10-05');
''')


def test_later_reload_and_dismiss():
    board(SETUP + r'''
responses.set('/api/date_questions/q/later',[reply({state:'waiting'})]);
await press('later');assert.match(area.innerHTML,/あとで確認できる/);
await load();assert.match(area.innerHTML,/運動会/);
assert.equal(data.date_questions.length,1);
responses.set('/api/date_questions/q/dismiss',[reply({state:'dismissed'})]);
await press('dismiss');assert.equal(area.innerHTML,'');
assert.equal(calls.filter(c=>c.url.endsWith('/register')).length,0);
''')


def test_failure_keeps_question_and_escape_print():
    board(SETUP + r'''
q.date_text='<img src=x onerror=alert(1)>';renderDateQuestions();
assert.match(area.innerHTML,/&lt;img/);
await month(10);await day(3);await press('ok');
responses.set('/api/date_questions/q/register',[reply({},502)]);
responses.set('/api/date_questions',[reply({items:[q]})]);
await press('register');assert.match(area.innerHTML,/保存結果を確認できません/);
assert.equal(data.date_questions.length,1);
q.state='registering';await load();assert.equal(area.querySelectorAll('button').length,2);
assert.match(area.innerHTML,/二重登録/);
''')


def test_parent_capture_has_only_clear_candidates():
    capture(r'''
await start();
routes.set('/api/extract',()=>response({items:[item()],date_questions_count:2}));
await choose();await readPhoto();
assert.match(nodes.get('result').innerHTML,/日付が はっきりしないもの 2件/);
assert.equal(extraction.items.length,1);assert.equal(registrations().length,0);
''', auth='parent')


def test_kid_capture_handoff_with_and_without_candidates():
    capture(r'''
await start();
routes.set('/api/register',registerOK);
routes.set('/api/extract',()=>response({items:[item()],date_questions_count:1}));
await choose();await readPhoto();
assert.equal(registrations().length,1);assert.equal(registrations()[0].items.length,1);
assert.match(nodes.get('result').innerHTML,/日付が わからないものは おうちの人に きいてもらうね/);
routes.set('/api/extract',()=>response({items:[],date_questions_count:1}));
await choose();await readPhoto();assert.equal(registrations().length,1);
assert.match(nodes.get('result').innerHTML,/日付が わからないものは おうちの人に きいてもらうね/);
''')


def test_display_title_keeps_saved_title_and_child_once():
    board(SETUP + r'''
q.title='上の子｜運動会';renderDateQuestions();
assert.match(area.innerHTML,/<h3>運動会<\/h3>/);
assert.ok(!area.innerHTML.includes('上の子｜'));
await month(10);await day(17);await press('ok');
assert.match(area.innerHTML,/<p[^>]*>運動会 10月17日（土） 上の子　これで とうろくする？<\/p>/);
assert.equal(q.title,'上の子｜運動会');
q.title='運動会｜集合';renderDateQuestions();
assert.match(area.innerHTML,/<h3>運動会｜集合<\/h3>/);
''')


def test_year_labels_follow_today_for_month_day_confirmation_and_summary():
    board(SETUP + r'''
const labels=()=>area.querySelectorAll('[data-date-action="month"]').map(b=>b.textContent);
assert.ok(labels().includes('10月'));assert.ok(!labels().includes('2026年 10月'));
assert.ok(labels().includes('2027年 1月'));
await month(10);assert.match(area.innerHTML,/<p[^>]*>運動会 上の子 何月何日？ 10月<\/p>/);
await day(17);assert.match(area.innerHTML,/<p[^>]*>運動会 上の子 10月17日（土）で いい？<\/p>/);
await press('reselect');await month(1);
assert.match(area.innerHTML,/<p[^>]*>運動会 上の子 何月何日？ 2027年 1月<\/p>/);
await day(3);assert.match(area.innerHTML,/<p[^>]*>運動会 上の子 2027年1月3日（日）で いい？<\/p>/);
await press('ok');assert.match(area.innerHTML,/<p[^>]*>運動会 2027年1月3日（日） 上の子　これで とうろくする？<\/p>/);
data.today='2027-01-01';await press('reset');
assert.ok(labels().includes('1月'));assert.ok(!labels().includes('2027年 1月'));
await month(1);await day(3);assert.match(area.innerHTML,/<p[^>]*>運動会 上の子 1月3日（日）で いい？<\/p>/);
''')


def test_range_summary_across_years():
    board(SETUP + r'''
q.date_is_range=true;renderDateQuestions();
await month(12);await day(30);await press('ok');
await month(1);await day(3);await press('ok');
assert.match(area.innerHTML,/<p[^>]*>運動会 12月30日（水） 〜 2027年1月3日（日） 上の子　これで とうろくする？<\/p>/);
''')


def test_unknown_child_selected_before_summary_and_sent_to_server():
    board(SETUP + r'''
q.child='不明';data.children=['上の子','下の子'];renderDateQuestions();
await month(10);await day(17);await press('ok');
assert.match(area.innerHTML,/だれの予定？/);
assert.ok(!area.innerHTML.includes('これで とうろくする？'));
assert.equal(area.querySelector('[data-date-action="register"]'),null);
const choices=area.querySelectorAll('[data-date-action="child"]');
assert.equal(choices.map(b=>b.textContent).join(','),'上の子,下の子');
assert.match(boardCSS,/\.date-question button\{[^}]*min-width:44px;min-height:44px/);
assert.equal(calls.length,0);
await choices[1].click();
assert.match(area.innerHTML,/運動会 10月17日（土） 下の子　これで とうろくする？/);
assert.equal(q.child,'不明');
await press('reset');await month(10);await day(17);await press('ok');
assert.match(area.innerHTML,/だれの予定？/);
await area.querySelectorAll('[data-date-action="child"]').find(b=>b.dataset.child==='下の子').click();
responses.set('/api/date_questions/q/register',[reply({state:'registered'})]);
await press('register');
assert.equal(calls.length,1);
assert.equal(calls[0].body.child,'下の子');
assert.equal(calls[0].body.date,'2026-10-17');
''')


@pytest.mark.parametrize("action,state", [("dismiss", "dismissed"), ("confirmed", "registered")])
def test_unknown_result_shows_resolution_actions_and_removes_card(action, state):
    board(SETUP + r'''
await month(10);await day(3);await press('ok');
responses.set('/api/date_questions/q/register',[reply({detail:'カレンダーを確認してください。'},502)]);
responses.set('/api/date_questions',[reply({items:[{...q,state:'registering'}]})]);
await press('register');
assert.match(area.innerHTML,/カレンダーを確認してください/);
assert.equal(area.querySelector('[data-date-action="register"]'),null);
assert.match(area.innerHTML,/カレンダーを確認した：入っていた/);
assert.match(area.innerHTML,/とうろくしない/);
assert.match(boardCSS,/\.date-question button\{[^}]*min-width:44px;min-height:44px/);
''' + f"""
responses.set('/api/date_questions/q/{action}',[reply({{state:'{state}'}})]);
await press('{action}');
assert.equal(area.innerHTML,'');
assert.equal(calls.filter(c=>c.url.endsWith('/register')).length,1);
""")


def test_validation_reason_and_time_correction_retry():
    board(SETUP + r'''
q.time_start='9時';q.time_end='10時';
await month(10);await day(3);await press('ok');
responses.set('/api/date_questions/q/register',[reply({detail:'時刻は HH:MM の形で入れてください。'},400),reply({state:'registered'})]);
responses.set('/api/date_questions',[reply({items:[q]})]);
await press('register');
assert.match(area.innerHTML,/時刻は HH:MM の形で入れてください/);
assert.equal(area.querySelector('[data-date-time="time_start"]').value,'9時');
area.querySelector('[data-date-time="time_start"]').value='09:00';
area.querySelector('[data-date-time="time_end"]').value='10:00';
await press('register');
const writes=calls.filter(c=>c.url.endsWith('/register'));
assert.equal(writes.length,2);
assert.equal(writes[1].body.time_start,'09:00');
assert.equal(writes[1].body.time_end,'10:00');
assert.equal(area.innerHTML,'');
''')


@pytest.mark.parametrize('last', [False, True])
def test_date_context_focus_scroll_and_summary_order(last):
    board(SETUP + r'''
if(LAST){data.date_questions.unshift(...Array.from({length:6},(_,i)=>({...q,id:'other'+i})));}
q.title='長い予定名の運動会と親子で参加する学校の集まり';renderDateQuestions();
// 文字拡大・折り返し後の実測値を毎回読み直す。
let height=156;
el('header').getBoundingClientRect=()=>({height});
const card=()=>area.querySelector('[data-date-id="q"]');
const click=async(action,value)=>{
 const buttons=card().querySelectorAll('[data-date-action="'+action+'"]');
 const b=buttons.find(b=>!value||b.dataset[action]===String(value));b.focus();await b.click();
};
function check(words){
 const target=card().querySelector('.date-context');
 assert.equal(document.activeElement,target);
 assert.equal(target.attrs.tabindex,'-1');
 assert.ok(target.textContent.includes(q.title));
 for(const word of words)assert.ok(target.textContent.includes(word),target.textContent);
 assert.equal(target.focusOptions.preventScroll,true);
 assert.equal(target.scrollCalls.at(-1).block,'start');
 assert.equal(document.documentElement.style['--board-header-height'],height+'px');
 assert.match(boardCSS,/\.date-context[^{}]*\{scroll-margin-top:calc\(var\(--board-header-height, 100px\) \+ 16px\)/);
}
await click('month',10);check(['10月']);height=212;
await click('day',17);check(['10月17日（土）','で いい？']);
await click('reselect');check(['何月何日？']);
await click('month',10);check(['10月']);
await click('day',17);check(['10月17日（土）']);
await click('ok');check(['10月17日（土）','これで とうろくする？']);
const register=card().querySelector('[data-date-action="register"]');
assert.equal(register.attrs['aria-label'],q.title+'を 10月17日（土）で とうろくする');
const order=card().querySelectorAll('p, input, button');
const summary=order.indexOf(document.activeElement);
assert.equal(order[summary+1].dataset.dateTime,'time_start');
assert.equal(order[summary+2].dataset.dateTime,'time_end');
assert.equal(order[summary+3],register);
assert.equal(order[summary+4].dataset.dateAction,'reset');
await click('reset');check(['何月何日？']);
q.date_is_range=true;
await click('month',12);await click('day',30);await click('ok');check(['12月30日（水）','いつまで']);
await click('month',1);check(['12月30日（水）','2027年 1月']);
await click('day',3);check(['2027年1月3日（日）']);
await click('ok');check(['12月30日（水） 〜 2027年1月3日（日）']);
'''.replace('LAST', 'true' if last else 'false'))


@pytest.mark.parametrize('action', ['later', 'register', 'dismiss'])
@pytest.mark.parametrize('failure', [False, True])
@pytest.mark.parametrize('destination', ['stay', 'reload', 'other_button', 'other_input'])
def test_date_pending_result_preserves_user_position(action, failure, destination):
    board(SETUP + r'''
const action=ACTION, failure=FAILURE, destination=DESTINATION;
data.date_questions.push({...q,id:'other',title:'別の予定'});
dateDrafts.set('other',{step:'summary',part:'start',start:'2026-10-18'});
renderDateQuestions();
await month(10);await day(17);await press('ok');
const getCard=id=>area.querySelector('[data-date-id="'+id+'"]');
const original=getCard('q');
const button=original.querySelector('[data-date-action="'+action+'"]');button.focus();
const status=original.querySelector('.date-feedback');
let release;responses.set('/api/date_questions/q/'+action,[new Promise(r=>release=r)]);
responses.set('/api/date_questions',[reply({items:[q,{...q,id:'other',title:'別の予定'}]})]);
const pending=button.click();await tick();
assert.equal(getCard('q'),original,'送信開始でカードを消さない');
assert.equal(document.activeElement,status);
assert.match(status.textContent,/運動会.*保存しています/);
assert.equal(button.disabled,true);
let destinationNode;
if(destination==='reload')destinationNode=el('#reload');
if(destination==='other_button')destinationNode=getCard('other').querySelector('[data-date-action="reset"]');
if(destination==='other_input'){
 destinationNode=getCard('other').querySelector('[data-date-time="time_start"]');destinationNode.value='12:34';destinationNode.setSelectionRange(1,3);
}
if(destinationNode)destinationNode.focus();
release(failure?reply({},502):reply({state:action==='dismiss'?'dismissed':action==='register'?'registered':'waiting'}));
await pending;
assert.notEqual(document.activeElement,document.body);
assert.equal(document.activeElement.isConnected,true);
if(destination==='stay'){
 const expected=failure||action==='later'?getCard('q').querySelector('.date-feedback'):el('#actionMsg');
 assert.equal(document.activeElement,expected);
 assert.match(expected.textContent,failure?/確認できません/:action==='later'?/あとで確認/:action==='register'?/登録しました/:/確認待ちから外しました/);
 assert.equal(expected.scrollCalls.at(-1).block,'start');
}else if(destination==='reload')assert.equal(document.activeElement,destinationNode);
else {
 assert.equal(document.activeElement.closest('[data-date-id]').dataset.dateId,'other');
 if(destination==='other_input'){
  assert.equal(document.activeElement.dataset.dateTime,'time_start');assert.equal(document.activeElement.value,'12:34');
  assert.equal(document.activeElement.selectionStart,1);assert.equal(document.activeElement.selectionEnd,3);
 }else assert.equal(document.activeElement.dataset.dateAction,'reset');
 assert.equal(document.activeElement.scrollCalls,undefined,'別の操作へスクロールを強制しない');
}
'''.replace('ACTION', repr(action)).replace('FAILURE', 'true' if failure else 'false').replace('DESTINATION', repr(destination)))
