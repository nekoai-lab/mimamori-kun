"""#62: progressively delivered NDJSON and browser image conversion."""
import pytest
from test_capture import run_js


@pytest.mark.parametrize("audience", ["parent", "child"])
def test_progress_reset_and_registration_only_after_done(audience):
    run_js(r"""
      await start();
      let receive;
      routes.set('/api/extract/stream',()=>({ok:true,body:{getReader:()=>({
        read:()=>new Promise(resolve=>receive=resolve),
        cancel:async()=>{}, releaseLock:()=>{}
      })}}));
      routes.set('/api/register',registerOK);
      const pending = (async()=>{await choose(); if(AUTH==='parent') await readPhoto();})();
      await flush();
      const send=async event=>{
        receive({value:new TextEncoder().encode(JSON.stringify(event)+String.fromCharCode(10)),done:false});
        await flush();
      };
      await send({type:'received'});
      assert.equal($('#note').textContent,AUTH==='child'?'しゃしんを おくったよ':'写真を送りました');
      await send({type:'reading'});
      assert.equal($('#note').textContent,AUTH==='child'?'よんでいるよ':'読んでいます');
      await send({type:'item',item:item({title:'一件目'})});
      assert.equal($('#note').textContent,AUTH==='child'?'もうすぐ':'もうすぐです');
      assert.match($('#result').innerHTML,/一件目/);
      assert.equal(($('#result').innerHTML.match(/<li>/g)||[]).length,1);
      await send({type:'item',item:item({title:'二件目'})});
      assert.equal(($('#result').innerHTML.match(/<li>/g)||[]).length,2);
      await send({type:'question',item:item({title:'非表示の質問'})});
      assert.doesNotMatch($('#result').innerHTML,/非表示の質問/);
      assert.match($('#result').innerHTML,/1件/);
      assert.doesNotMatch($('#result').innerHTML,/<button/);
      await doRegister();
      assert.equal(registrations().length,0);
      await send({type:'reset'});
      assert.equal($('#result').innerHTML,'');
      assert.equal($('#note').textContent,AUTH==='child'?'よんでいるよ':'読んでいます');
      await send({type:'item',item:item({title:'やり直した候補'})});
      await send({type:'done',items:[item({title:'やり直した候補'})]});
      receive({done:true}); await pending;
      assert.equal(registrations().length,AUTH==='child'?1:0);
      if(AUTH==='child') assert.match($('#completion').innerHTML,/やることに 入ったよ/);
      else assert.match($('#result').innerHTML,/登録候補/);
    """, audience)


@pytest.mark.parametrize("failure", ["decode", "canvas", "null", "wrong_type"])
def test_resize_failure_keeps_original(failure):
    run_js(r"""
      const input={name:'photo.heic'}, failure=FAILURE;
      globalThis.Image=class {
        constructor(){this.naturalWidth=4000;this.naturalHeight=3000;}
        set src(value){ if(failure==='decode') this.onerror(); else this.onload(); }
      };
      document.createElement=()=>({
        getContext:()=>{if(failure==='canvas') throw new Error();return {drawImage:()=>{}};},
        toBlob:cb=>cb(failure==='null'?null:{type:'image/png'})
      });
      assert.equal(await shrinkPhoto(input),input);
    """.replace("FAILURE", repr(failure)))


@pytest.mark.parametrize("width,height,expected", [(4000,3000,[1600,1200]), (600,1200,[600,1200]), (2000,4000,[800,1600])])
def test_resize_jpeg_dimensions_quality(width, height, expected):
    run_js(r"""
      let revoked=0, drawn, encoding;
      const output={type:'image/jpeg'};
      URL.revokeObjectURL=()=>revoked++;
      globalThis.Image=class {
        constructor(){this.naturalWidth=WIDTH;this.naturalHeight=HEIGHT;}
        set src(value){this.onload();}
      };
      const canvas={
        getContext:kind=>{assert.equal(kind,'2d');return {drawImage:(...args)=>drawn=args};},
        toBlob:(cb,type,quality)=>{encoding=[type,quality];cb(output);}
      };
      document.createElement=()=>canvas;
      assert.equal(await shrinkPhoto(photo),output);
      assert.deepEqual([canvas.width,canvas.height],EXPECTED);
      assert.deepEqual(drawn.slice(1),[0,0,...EXPECTED]);
      assert.deepEqual(encoding,['image/jpeg',0.85]);
      assert.equal(revoked,1);
    """.replace("WIDTH", str(width)).replace("HEIGHT", str(height)).replace("EXPECTED", str(expected)))


def test_ndjson_byte_boundaries_and_truncated_failure():
    run_js(r"""
      const bytes=new TextEncoder().encode(JSON.stringify({type:'item',item:item({title:'日本語'})})+String.fromCharCode(10)
        +JSON.stringify({type:'done',items:[item()]})+String.fromCharCode(10));
      let n=0, seen=[];
      const res={ok:true,body:{getReader:()=>({
        read:async()=>n<bytes.length?{value:bytes.slice(n,n+++1),done:false}:{done:true},
        cancel:async()=>{},releaseLock:()=>{}
      })}};
      await readEvents(res,e=>seen.push(e));
      assert.equal(seen[0].item.title,'日本語');
      await assert.rejects(()=>readEvents(streamResponse([{type:'reading'}]),()=>{}));
    """)
