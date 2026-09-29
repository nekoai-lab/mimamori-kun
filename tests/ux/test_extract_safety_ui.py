"""Exercise the actual capture-page JS with synthetic streams/DOM."""
import pytest
from test_capture import run_js


@pytest.mark.parametrize('audience', ['parent', 'child'])
@pytest.mark.parametrize('temporary', [False, True])
def test_error_stream_shows_role_specific_message(audience, temporary):
    run_js(r'''
      await start();
      if(!TEMPORARY){
        routes.set('/api/extract/stream',()=>streamResponse([{type:'error',temporary:true}]));
        await choose(); if(AUTH==='parent') await readPhoto();
        assert.match($('#result').innerHTML,AUTH==='parent'?/混み合っています/:/いまは 読めないよ/);
      }
      routes.set('/api/extract/stream',()=>streamResponse([{type:'error',temporary:TEMPORARY}]));
      await choose(); if(AUTH==='parent') await readPhoto();
      const text=$('#result').innerHTML;
      if(TEMPORARY){
        assert.match(text,AUTH==='parent' ? /いまは読み取りが混み合っています。少し待ってからもう一度お試しください/ : /いまは 読めないよ。すこし まってから もういちど/);
        assert.doesNotMatch(text,/文字がはっきり/);
      }else assert.match(text,/うまく読めなかったよ。文字がはっきり写っているか見てね。/);
      assert.equal(registrations().length,0);
    '''.replace('TEMPORARY', str(temporary).lower()), audience)


@pytest.mark.parametrize('empty', [False, True])
def test_parent_add_uses_existing_form_preserves_edits_and_stays_candidate(empty):
    run_js(r'''
      await start();
      globalThis.crypto={randomUUID:()=> 'manual-added'};
      routes.set('/api/extract',()=>response({items:EMPTY?[]:[item({child:'上の子',title:'上の子｜宿題'})]}));
      await choose(); await readPhoto();
      assert.match($('#result').innerHTML,/ほかにも ある？/);
      assert.match($('#result').innerHTML,/id="shot"/);
      await $('#shot').click(); assert.equal($('#photo-dialog').open,true);
      assert.equal($('#photo-large').src,previewURL);
      const fields={selected:{checked:false},title:{value:'編集した件名'},date:{value:'2026-12-25'},
        time_start:{value:'09:00'},note:{value:'水筒'},child:{textContent:'上の子'}};
      const row={dataset:{id:'candidate'},querySelector:s=>fields[s.match(/data-f="(.*?)"/)[1]]};
      document.querySelectorAll=s=>s==='.item' && !EMPTY ? [row] : [];
      await $('#add-candidate').click();
      assert.equal(qChild,EMPTY?'下の子':'上の子');
      if(!EMPTY){
        fields.child.textContent='下の子';
        await $('#add-candidate').click();
        assert.equal(qChild,'下の子');
      }
      assert.equal($('#qbox').hidden,false);
      $('#qtitle').value='はちまき'; qKind='bring'; qDate='2026-12-26';
      await $('#qadd').click();
      assert.equal(registrations().length,0);
      assert.equal(extraction.items.length,EMPTY?1:2);
      const added=extraction.items.at(-1);
      assert.match(added.title,/はちまき/);
      assert.equal(added.child,'下の子');
      assert.equal(added.date,'2026-12-26'); assert.equal(added.kind,'bring');
      assert.equal(added.selected,true);
      assert.match($('#result').innerHTML,/はちまき/);
      if(!EMPTY){
        assert.equal(extraction.items[0].selected,false);
        assert.equal(extraction.items[0].title,'編集した件名');
        assert.equal(extraction.items[0].date,'2026-12-25');
        assert.equal(extraction.items[0].note,'水筒');
      }
    '''.replace('EMPTY', str(empty).lower()), 'parent')
