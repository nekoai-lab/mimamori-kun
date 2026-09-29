"""PR #67 S62-1 / S62-2: retry the retained photo and report each outcome."""
import pytest

from test_capture import HTML, run_js


@pytest.mark.parametrize('audience', ['child', 'parent'])
@pytest.mark.parametrize('failure', ['timeout', '429', '503'])
def test_temporary_failure_retries_same_resized_photo_once(audience, failure):
    run_js(r'''
      await start();
      let resizeCount=0, fileDialogs=0;
      const resized={type:'image/jpeg',bytes:'resized synthetic photo'};
      shrinkPhoto=async input=>{assert.equal(input,photo);resizeCount++;return resized;};
      $('#file').addEventListener('click',()=>fileDialogs++);
      $('#album').addEventListener('click',()=>fileDialogs++);
      const fail=()=>FAILURE==='timeout'
        ? streamResponse([{type:'reading'},{type:'error',temporary:true}])
        : response({},Number(FAILURE));
      routes.set('/api/extract/stream',fail);
      await choose(); if(AUTH==='parent') await readPhoto();
      const assertRetry=()=>{
        const html=$('#result').innerHTML;
        assert.ok(html.includes(AUTH==='child'?'もういちど よむ':'もう一度読み取る'));
        assert.ok(html.includes(AUTH==='child'?'写真は そのままで いいよ':'写真を撮り直す必要はありません'));
        assert.match(html,/class="btn primary" id="retry-read"/);
        assert.match(html,/class="row retry-secondary"/);
        assert.ok(html.indexOf('id="retry-read"')<html.indexOf('id="retake"'));
        assert.equal($('#retry-read').disabled,false);
      };
      assertRetry();
      let finish;
      routes.set('/api/extract/stream',()=>new Promise(resolve=>finish=resolve));
      const retry=$('#retry-read'), pending=retry.click();
      await flush();
      assert.equal(retry.disabled,true);
      // Call the handler even on the detached/disabled button: the busy guard must hold.
      await retry.click(); await retry.click(); await $('#go').click();
      const requests=()=>calls.filter(c=>c.url==='/api/extract/stream');
      assert.equal(requests().length,2);
      assert.equal(fileDialogs,0);
      assert.equal(resizeCount,1);
      assert.ok(requests().every(c=>c.opts.method==='POST' && c.opts.body.values.image===resized));
      finish(fail()); await pending;
      assertRetry();
      routes.set('/api/extract/stream',()=>streamResponse([{type:'done',items:[]}]));
      await $('#retry-read').click();
      assert.equal(requests().length,3);
      assert.equal(resizeCount,1);
      assert.doesNotMatch($('#result').innerHTML,/id="retry-read"/);
      assert.equal(registrations().length,0);
    '''.replace('FAILURE', repr(failure)), audience)


@pytest.mark.parametrize('audience', ['child', 'parent'])
@pytest.mark.parametrize('failure', ['empty', 'json'])
def test_unreadable_photo_keeps_retake(audience, failure):
    run_js(r'''
      await start();
      routes.set('/api/extract/stream',()=>FAILURE==='empty' ? streamResponse([]) : {
        ok:true,body:{getReader:()=>({read:async()=>({value:new TextEncoder().encode('{broken}\n'),done:false}),
          cancel:async()=>{},releaseLock:()=>{}})}});
      await choose(); if(AUTH==='parent') await readPhoto();
      assert.match($('#result').innerHTML,/うまく読めなかったよ。文字がはっきり写っているか見てね。/);
      assert.match($('#result').innerHTML,/id="retake">とりなおす/);
      assert.doesNotMatch($('#result').innerHTML,/retry-read|写真は そのまま|撮り直す必要/);
      let opened=0; $('#file').addEventListener('click',()=>opened++);
      await $('#retake').click(); assert.equal(opened,1);
      assert.equal(registrations().length,0);
    '''.replace('FAILURE', repr(failure)), audience)


@pytest.mark.parametrize('audience', ['child', 'parent'])
@pytest.mark.parametrize('skipped,questions,new', [(2,0,False),(0,1,False),(2,1,False),(2,1,True)])
def test_duplicate_question_and_new_outcomes(audience, skipped, questions, new):
    run_js(r'''
      await start();
      routes.set('/api/extract/stream',()=>streamResponse([{type:'done',items:NEW?[item()]:[],
        skipped:SKIPPED,date_questions_count:QUESTIONS}]));
      routes.set('/api/register',registerOK);
      await choose(); if(AUTH==='parent') await readPhoto();
      const html=$('#result').innerHTML, completion=$('#completion').innerHTML;
      const duplicate=AUTH==='child'?'やることは もう 入っていたよ（2件）':'すでに入っているもの 2件は、そのままにしました';
      const question=AUTH==='child'?'日付が わからないものは おうちの人に きいてもらうね（1件）':'日付が はっきりしないもの 1件は「確認すること」で聞きます';
      assert.equal(html.includes(duplicate),SKIPPED>0);
      assert.equal(html.includes(question),QUESTIONS>0);
      assert.equal(completion.includes('やることに 入ったよ'),AUTH==='child' && NEW);
      assert.doesNotMatch(html,/やることに 入ったよ|やることは見つからなかったよ/);
      if(AUTH==='child') assert.match(html+completion,/きょうを みる/);
      else assert.match(html,NEW?/登録する/:/登録候補はありません/);
      assert.equal(registrations().length,AUTH==='child' && NEW?1:0);
    '''.replace('SKIPPED', str(skipped)).replace('QUESTIONS', str(questions))
       .replace('NEW', str(new).lower()), audience)


def test_retry_layout_wraps_and_preserves_touch_targets():
    # Browser geometry/screenshots are checked separately; retain the responsive CSS contract.
    assert '.btn{min-height:44px;max-width:100%;overflow-wrap:anywhere;' in HTML
    assert '.retry-secondary .btn{font-size:12.5px;padding:8px 12px}' in HTML
    assert 'flex-wrap:wrap' in HTML
    assert '#result{overflow-wrap:anywhere}' in HTML


@pytest.mark.parametrize('change', ['photo', 'child'])
def test_resized_retry_photo_is_discarded_when_input_changes(change):
    run_js(r'''
      await start();
      const inputs=[];
      shrinkPhoto=async input=>{inputs.push(input);return {type:'image/jpeg',original:input};};
      routes.set('/api/extract/stream',()=>response({},429));
      await choose(); await readPhoto();
      assert.equal(inputs.length,1);
      const nextPhoto={type:'image/png',name:'next.png'};
      if(CHANGE==='child'){
        $('#child').value='上の子'; await $('#child').emit('change');
        await readPhoto();
        assert.equal(inputs.length,1);
      }
      await choosePhoto({target:{files:[nextPhoto]}}); await readPhoto();
      assert.deepEqual(inputs,[photo,nextPhoto]);
      const sent=calls.filter(c=>c.url==='/api/extract/stream').at(-1).opts.body.values.image;
      assert.equal(sent.original,nextPhoto);
    '''.replace('CHANGE', repr(change)), 'parent')
