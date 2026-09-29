"""#59: 既存の DOM/fetch ハーネスで親の確定フローと撮る画面を検証する。"""
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
await press('register');assert.match(area.innerHTML,/保存結果を確認できません/);
assert.equal(data.date_questions.length,1);
q.state='registering';await load();assert.equal(area.querySelectorAll('button').length,0);
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
assert.match(nodes.get('result').innerHTML,/日付は おうちの人に きいてもらうね/);
routes.set('/api/extract',()=>response({items:[],date_questions_count:1}));
await choose();await readPhoto();assert.equal(registrations().length,1);
assert.match(nodes.get('result').innerHTML,/日付は おうちの人に きいてもらうね/);
''')


def test_display_title_keeps_saved_title_and_child_once():
    board(SETUP + r'''
q.title='上の子｜運動会';renderDateQuestions();
assert.match(area.innerHTML,/<h3>運動会<\/h3>/);
assert.ok(!area.innerHTML.includes('上の子｜'));
await month(10);await day(17);await press('ok');
assert.match(area.innerHTML,/<p>運動会 10月17日（土） 上の子　これで とうろくする？<\/p>/);
assert.equal(q.title,'上の子｜運動会');
q.title='運動会｜集合';renderDateQuestions();
assert.match(area.innerHTML,/<h3>運動会｜集合<\/h3>/);
''')


def test_year_labels_follow_today_for_month_day_confirmation_and_summary():
    board(SETUP + r'''
const labels=()=>area.querySelectorAll('[data-date-action="month"]').map(b=>b.textContent);
assert.ok(labels().includes('10月'));assert.ok(!labels().includes('2026年 10月'));
assert.ok(labels().includes('2027年 1月'));
await month(10);assert.match(area.innerHTML,/<p>10月<\/p>/);
await day(17);assert.match(area.innerHTML,/<p>10月17日（土）で いい？<\/p>/);
await press('reselect');await month(1);
assert.match(area.innerHTML,/<p>2027年 1月<\/p>/);
await day(3);assert.match(area.innerHTML,/<p>2027年1月3日（日）で いい？<\/p>/);
await press('ok');assert.match(area.innerHTML,/<p>運動会 2027年1月3日（日） 上の子　これで とうろくする？<\/p>/);
data.today='2027-01-01';await press('reset');
assert.ok(labels().includes('1月'));assert.ok(!labels().includes('2027年 1月'));
await month(1);await day(3);assert.match(area.innerHTML,/<p>1月3日（日）で いい？<\/p>/);
''')


def test_range_summary_across_years():
    board(SETUP + r'''
q.date_is_range=true;renderDateQuestions();
await month(12);await day(30);await press('ok');
await month(1);await day(3);await press('ok');
assert.match(area.innerHTML,/<p>運動会 12月30日（水） 〜 2027年1月3日（日） 上の子　これで とうろくする？<\/p>/);
''')
