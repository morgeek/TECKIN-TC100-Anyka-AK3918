from pathlib import Path
import json, sys
root=Path(__file__).resolve().parents[2]
out=Path(sys.argv[1]).resolve(); out.mkdir(parents=True, exist_ok=True)
config={'video':{'main':{'width':1280,'height':720,'codec':0,'fps':20,'bitrate':1200,'gop':40,'format':'1','minqp':20,'maxqp':45,'smartmode':1},'sub':{'width':352,'height':200,'codec':0,'fps':8,'bitrate':200,'gop':16,'format':'1','minqp':20,'maxqp':45,'smartmode':1}},'audio':{'samplerate':8000,'volume':10,'codec_main':4}}
fake='''
localStorage.clear();
window.__config=CONFIG; window.__posts=[]; window.__mode='success';
window.fetch=async function(url, opts={}) {
 const cmd=new URL(url,location.href).searchParams.get('cmd');
 if (opts.method==='POST') {
   window.__posts.push({url,body:opts.body,headers:Object.fromEntries(opts.headers)});
   if(window.__hold) await new Promise(resolve=>window.__release=resolve);
   if(window.__mode==='error') return new Response(JSON.stringify({ok:false,error:'SD card is read-only'}));
   const p=new URLSearchParams(opts.body);
   if(cmd==='set_video_params' && window.__mode!=='mismatch') {
     const i=p.get('stream'), v=window.__config.video[i==='1'?'sub':'main'];
     const size=p.get('video_size'+i).split('x');v.width=+size[0];v.height=+size[1];
     for(const [k,f] of Object.entries({video_codec:'codec',fps:'fps',brbitrate:'bitrate',goplen:'gop',video_format:'format',minqp:'minqp',maxqp:'maxqp',smartmode:'smartmode'}))v[f]=+p.get(k+i);
   }
   return new Response(JSON.stringify({ok:true,message:'Saved'}));
 }
 if(cmd==='fullconfig') { if(window.__loadFail) throw new Error('offline'); return new Response(JSON.stringify(window.__config)); }
 if(cmd==='statusline') return new Response(JSON.stringify({cpu:12,ram_percent:43,csrf_token:'aabbcc',wifi_qual:70}));
 if(cmd==='hostname') return new Response('TC100');
 if(cmd==='list_presets') return new Response(JSON.stringify({presets:[]}));
 return new Response(JSON.stringify({ok:true}));
};
'''.replace('CONFIG',json.dumps(config))
html='<!doctype html><html data-theme="light"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
for f in ['bulma.1.0.2.min.css','ui-modern.min.css']:html+='<link rel="stylesheet" href="'+(root/'www/css'/f).as_uri()+'">'
html+='<script>'+fake+'</script><script src="'+(root/'www/scripts/index.bundle.min.js').as_uri()+'"></script></head><body><section class="section"><div id="content" class="container">'
html+=(root/'www/settings.html').read_text()
html+='</div></section><script>document.querySelector(\'[data-tab="tab-video"]\').click();</script></body></html>'
(out/'fixture.html').write_text(html)
