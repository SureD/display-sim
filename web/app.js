import {decodeFrame, mappingGain, toLinear709} from './mapping.js';
import {createRenderers} from './renderers.js';

const $ = id => document.getElementById(id);
const canvasIds = ['canvas-left','canvas-right','reference-patch','wedge'];
const media = {hdr:matchMedia('(dynamic-range: high)'),p3:matchMedia('(color-gamut: p3)'),rec2020:matchMedia('(color-gamut: rec2020)')};
const state = {
  scene:'bright_window', leftProfile:'generic_va_fald_miniled', rightProfile:'generic_woled',
  mode:'scaled', whiteNits:100, scenePeak:2000, requestedCeiling:1, exposure:0,
  zoom:1, centerX:.5, centerY:.5, playing:false, frame:0, measured:false, renderCount:0,
};
// Read-only use in the dependency-free browser smoke script; no TV simulation here.
window.__tvPreview = {state};
let manifest, rendererSet, assets, loadEpoch=0, drawPending=false, animation=0, playbackStart=0, reloadPending=false;
const buffers=new Map(), decoded=new Map();
let uploadedKeys=['',''];
const fmt = (v,d=1) => Number(v).toLocaleString('en-US',{maximumFractionDigits:d});
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const scene=()=>manifest.scenes.find(s=>s.id===state.scene);
const profiles=()=>[state.leftProfile,state.rightProfile].map(id=>manifest.profiles.find(p=>p.id===id));
const hdrActive=()=>rendererSet?.extended && media.hdr.matches;
const ceiling=()=>hdrActive()?state.requestedCeiling:1;
function status(message,error=false) { $('status').textContent=message; $('status').classList.toggle('error',error); }
function fail(error) {stopPlayback(); status(error.message || String(error),true); console.error(error);}
function envKey() {return `${media.hdr.matches}/${media.p3.matches}/${media.rec2020.matches}/${rendererSet.kind}`;}
function clearStored() {try{sessionStorage.removeItem('tv-lab-white-v1');}catch{/* Storage may be disabled. */}}
function restoreCalibration() {
  try {
    const saved=JSON.parse(sessionStorage.getItem('tv-lab-white-v1'));
    if(saved?.environment===envKey() && saved.white>=1 && saved.white<=10000) {
      state.whiteNits=saved.white; state.measured=true; $('white-nits').value=saved.white;
    }
  }catch{/* Calibration remains explicitly assumed. */}
}

function reportedHeadroom() {
  // No permission request. Most Chrome versions expose neither property here.
  // ScreenDetailed.hdrHeadroom is stops; the obsolete property is a ratio.
  const stops=window.screen.hdrHeadroom;
  const legacy=window.screen.highDynamicRangeHeadroom;
  if(typeof stops==='number' && Number.isFinite(stops) && stops>=0 && Number.isFinite(2**stops))
    return `${fmt(2**stops,2)}× (${fmt(stops,2)} stops; experimental)`;
  if(typeof legacy==='number' && Number.isFinite(legacy) && legacy>=1)
    return `${fmt(legacy,2)}× (legacy experimental API)`;
  return 'Not exposed by browser';
}
function capabilityLabels() {
  $('hdr-status').textContent=media.hdr.matches?'High dynamic range reported':'Standard dynamic range reported';
  $('gamut-status').textContent=media.rec2020.matches?'Rec.2020 query matches':media.p3.matches?'Display P3 query matches':'sRGB query only';
  $('headroom-status').textContent=reportedHeadroom();
  $('renderer-status').textContent=rendererSet.label;
  $('backend-badge').textContent=hdrActive()?'Extended HDR request · unverified output':`${rendererSet.kind==='webgpu'?'Extended surface':'SDR fallback'} · SDR output`;
  $('headroom-limit').disabled=!hdrActive();
  if(!hdrActive()) {state.requestedCeiling=1;$('headroom-limit').value=1;}
  $('ceiling-note').textContent=hdrActive()
    ? 'Component ceiling is a manual assumption, not reported hardware headroom. The host may map or clip it again.'
    : 'Output is limited to SDR component 1. HDR capability or an extended surface alone does not prove HDR light output.';
  document.documentElement.dataset.backend=rendererSet.kind;
  $('render-notes').textContent=`${rendererSet.label}. ${rendererSet.failures.length?`Fallback probes: ${rendererSet.failures.join(' · ')}. `:''}Exported float16 is decoded without an SDR intermediate. The host preview applies one shared exposure and component clamp. No TV tone map or ABL is recomputed in the browser.`;
}
function mappingLabels() {
  const c=ceiling(), gain=mappingGain(state.mode,state.whiteNits,state.scenePeak,c,state.exposure);
  const white=`${state.measured?'measured':'assumed'} ${fmt(state.whiteNits)}-nit white`;
  $('mapping-status').textContent=state.mode==='scaled'
    ? `Relative preview: ${fmt(state.scenePeak)} simulated nits → component ${fmt(c,2)} before exposure. Shared across both TVs and every frame. Reference: ${white}; this mode does not request an absolute nit match.`
    : `White-based request: nits ÷ ${fmt(state.whiteNits)} (${white}), limited at component ${fmt(c,2)}. Values above ${fmt(state.whiteNits*c)} nits clip at 0 EV. Actual output needs meter verification.`;
  $('calibration-status').textContent=`${state.measured?'MEASURED':'UNMEASURED · assumed'} ${fmt(state.whiteNits)} nits`;
  $('calibration-status').style.color=state.measured?'#b5e5d7':'';
  $('exposure-value').textContent=`${state.exposure>=0?'+':''}${fmt(state.exposure,2)} EV`;
  $('zoom-value').textContent=`${fmt(state.zoom,2)}×`;
  $('scale-peak').disabled=state.mode!=='scaled';
  return {gain,ceiling:c,zoom:state.zoom,centerX:state.centerX,centerY:state.centerY};
}
function patches() {
  rendererSet.instances[2].upload(new Float32Array(160*100*3).fill(1),160,100);
  const w=640,h=56,levels=[0,10,50,100,200,400,1000,2000],rgb=new Float32Array(w*h*3);
  for(let y=0;y<h;y++) for(let x=0;x<w;x++) {
    const level=levels[Math.floor(x/(w/8))],index=(y*w+x)*3;
    rgb[index]=level; rgb[index+1]=level; rgb[index+2]=level;
  }
  rendererSet.instances[3].upload(rgb,w,h);
}
function draw() {
  drawPending=false;
  const settings=mappingLabels();
  if(assets) {
    assets.forEach((asset,i)=>{
      const key=`${asset.file}/${state.frame}`;
      if(uploadedKeys[i]!==key) {
        let frame=decoded.get(key);
        if(!frame) {
          frame=toLinear709(decodeFrame(asset.buffer,asset.width,asset.height,state.frame,asset.frame_stride_bytes),manifest.format);
          decoded.set(key,frame);
          if(decoded.size>48) decoded.delete(decoded.keys().next().value);
        }
        rendererSet.instances[i].upload(frame,asset.width,asset.height);uploadedKeys[i]=key;
      }
      rendererSet.instances[i].draw(settings);
    });
  }
  rendererSet.instances[2].draw({gain:1,ceiling:1});
  rendererSet.instances[3].draw({...settings,zoom:1,centerX:.5,centerY:.5});
  const current=scene();
  $('timeline').value=state.frame;
  $('frame-label').textContent=current.kind==='motion'?`${String(state.frame+1).padStart(2,'0')} / ${current.frame_count} · ${fmt(state.frame/current.fps,3)}s`:'STILL FRAME';
  document.documentElement.dataset.frame=String(state.frame);
  document.documentElement.dataset.scene=state.scene;
  document.documentElement.dataset.leftProfile=state.leftProfile;
  document.documentElement.dataset.rightProfile=state.rightProfile;
  state.renderCount++;
}
function requestDraw() {if(!drawPending){drawPending=true;requestAnimationFrame(()=>{try{draw();}catch(error){fail(error);}});}}
async function fetchAsset(asset) {
  if(!buffers.has(asset.file)) {
    const promise=(async()=>{
      const response=await fetch(new URL(asset.file,new URL('data/manifest.json',location.href)));
      if(!response.ok)throw new Error(`Asset request failed (${response.status}): ${asset.file}`);
      const buffer=await response.arrayBuffer();
      if(buffer.byteLength!==asset.byte_length)throw new Error(`Asset length mismatch: ${asset.file}`);
      if(crypto.subtle) {
        const digest=await crypto.subtle.digest('SHA-256',buffer);
        const hash=Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,'0')).join('');
        if(hash!==asset.sha256)throw new Error(`Asset checksum mismatch: ${asset.file}`);
      }
      return buffer;
    })();
    buffers.set(asset.file,promise);
    promise.catch(()=>buffers.delete(asset.file));
  }
  return {...asset,buffer:await buffers.get(asset.file)};
}
async function loadComparison() {
  const epoch=++loadEpoch;
  stopPlayback(); assets=null; uploadedKeys=['',''];
  $('play').disabled=true; $('timeline').disabled=true;
  document.documentElement.dataset.loading='true';
  status('Loading and verifying linear-nit assets…');
  const current=scene(),selected=profiles();
  let next;
  try {next=await Promise.all(selected.map(p=>fetchAsset(current.assets[p.id])));}
  catch(error) {if(epoch===loadEpoch) {document.documentElement.dataset.loading='false';throw error;}return;}
  if(epoch!==loadEpoch)return;
  assets=next;
  state.frame=clamp(state.frame,0,current.frame_count-1);
  $('scene-description').textContent=current.description;
  for(const [i,side] of ['left','right'].entries()) {
    const p=selected[i],s=next[i].statistics;
    $('tech-'+side).textContent=p.technology.replaceAll('_',' ').toUpperCase();
    $('layout-'+side).textContent=p.settings.panel.subpixel.toUpperCase();
    $('stats-'+side).textContent=current.kind==='macro'
      ? `Illustrative aperture peak ${fmt(s.peak_channel_nits)} · unmeasured geometry`
      : `Asset peak ${fmt(s.peak_channel_nits)} nits · mean Y ${fmt(s.mean_luminance_nits,3)} nits`;
  }
  const p=$('profile-notes');p.replaceChildren();
  for(const profile of selected) {
    const text=document.createTextNode(`${profile.label}: YAML ${profile.yaml_sha256.slice(0,12)} · `);
    const link=document.createElement('a'); link.href='data/'+profile.snapshots.provenance.file;link.textContent='M/D/P/NR evidence snapshot ↗';
    p.append(text,link,document.createTextNode(' '));
  }
  const motion=current.kind==='motion';
  $('play').disabled=!motion; $('timeline').disabled=!motion; $('timeline').max=current.frame_count-1;
  $('playback-note').textContent=motion?`${fmt(current.fps,3)} fps target · saved pursuit frames · loop has a history cut`:'Exported CPU reference · no live TV processing';
  draw();
  document.documentElement.dataset.loading='false';
  document.documentElement.dataset.ready='true';
  status(`${manifest.profiles.length} placeholder profiles · ${manifest.scenes.length} scenes · float16 assets verified${crypto.subtle?' (SHA-256)':' (byte length)'} · ambient 0 lux`);
}
function stopPlayback() {
  state.playing=false;cancelAnimationFrame(animation);$('play').textContent='▶ Play';$('play').setAttribute('aria-label','Play motion sequence');
}
function tick(now) {
  if(!state.playing)return;
  // A queued rAF timestamp can precede the click's performance.now() slightly.
  const current=scene(),frame=Math.floor(Math.max(0,now-playbackStart)/1000*current.fps)%current.frame_count;
  if(frame!==state.frame) {state.frame=frame;requestDraw();}
  animation=requestAnimationFrame(tick);
}
function resetView() {state.zoom=1;state.centerX=.5;state.centerY=.5;$('zoom').value=1;}
function configureViewEvents() {
  for(const id of ['canvas-left','canvas-right']) {
    const canvas=$(id);
    let drag=null;
    canvas.addEventListener('pointerdown',event=>{
      if(event.button!==0)return;
      drag={x:event.clientX,y:event.clientY,cx:state.centerX,cy:state.centerY};canvas.setPointerCapture(event.pointerId);
    });
    canvas.addEventListener('pointermove',event=>{
      if(!drag)return;
      const box=canvas.getBoundingClientRect();
      state.centerX=clamp(drag.cx-(event.clientX-drag.x)/box.width/state.zoom,0,1);
      state.centerY=clamp(drag.cy-(event.clientY-drag.y)/box.height/state.zoom,0,1);requestDraw();
    });
    for(const type of ['pointerup','pointercancel','lostpointercapture'])canvas.addEventListener(type,()=>{drag=null;});
    canvas.addEventListener('wheel',event=>{
      event.preventDefault();state.zoom=clamp(state.zoom*Math.exp(-event.deltaY*.002),1,8);$('zoom').value=state.zoom;requestDraw();
    },{passive:false});
  }
}
function bindControls() {
  $('scene').addEventListener('change',()=>{state.scene=$('scene').value;state.frame=0;resetView();loadComparison().catch(fail);});
  for(const side of ['left','right'])$('tv-'+side).addEventListener('change',()=>{state[side+'Profile']=$('tv-'+side).value;state.frame=0;loadComparison().catch(fail);});
  $('mode').addEventListener('change',()=>{state.mode=$('mode').value;requestDraw();});
  for(const [id,key,min,max] of [['white-nits','whiteNits',1,10000],['scale-peak','scenePeak',1,65504],['headroom-limit','requestedCeiling',1,64]]) {
    $(id).addEventListener('input',()=>{
      const value=Number($(id).value);
      if(!$(id).value || !Number.isFinite(value) || value<min || value>max) {status(`Enter ${min}–${max} for ${$(id).parentElement.textContent.trim()}.`,true);return;}
      state[key]=value;
      if(key==='whiteNits') {state.measured=false;clearStored();}
      requestDraw();
    });
  }
  $('exposure').addEventListener('input',()=>{state.exposure=Number($('exposure').value);requestDraw();});
  $('zoom').addEventListener('input',()=>{state.zoom=Number($('zoom').value);requestDraw();});
  $('reset-view').addEventListener('click',()=>{resetView();requestDraw();});
  $('macro').addEventListener('click',()=>{state.scene='macro_apertures';$('scene').value=state.scene;state.frame=0;resetView();loadComparison().catch(fail);});
  $('calibrate').addEventListener('click',()=>{
    const measured=Number($('measured-nits').value);
    if(!Number.isFinite(measured) || measured<1 || measured>10000) {status('Enter a measured white luminance between 1 and 10,000 cd/m².',true);$('measured-nits').focus();return;}
    state.whiteNits=measured;state.measured=true;$('white-nits').value=measured;
    try{sessionStorage.setItem('tv-lab-white-v1',JSON.stringify({white:measured,environment:envKey(),timestamp:new Date().toISOString()}));}catch{/* This tab still uses the reading. */}
    status(`Reference white recorded: ${fmt(measured)} nits. Verify the wedge; remeasure after display or brightness changes.`);requestDraw();
  });
  $('reset-calibration').addEventListener('click',()=>{
    state.whiteNits=100;state.measured=false;$('white-nits').value=100;$('measured-nits').value='';clearStored();status('Calibration cleared. Using an explicitly assumed 100-nit white.');requestDraw();
  });
  $('play').addEventListener('click',()=>{
    if(state.playing){stopPlayback();return;}
    if(scene().kind!=='motion' || !assets)return;
    state.playing=true;playbackStart=performance.now()-state.frame/scene().fps*1000;
    $('play').textContent='Ⅱ Pause';$('play').setAttribute('aria-label','Pause motion sequence');animation=requestAnimationFrame(tick);
  });
  $('timeline').addEventListener('input',()=>{if(!assets || scene().kind!=='motion')return;stopPlayback();state.frame=clamp(Number($('timeline').value),0,scene().frame_count-1);requestDraw();});
  configureViewEvents();
  for(const query of Object.values(media))query.addEventListener('change',()=>{
    state.measured=false;state.whiteNits=100;$('white-nits').value=100;clearStored();capabilityLabels();requestDraw();
    status('Display capability changed. Calibration cleared; remeasure reference white.');
  });
  document.addEventListener('visibilitychange',()=>{if(document.hidden)stopPlayback();});
  window.addEventListener('tv-renderer-lost',async event=>{
    if(reloadPending)return;reloadPending=true;stopPlayback();
    try {
      const forced=rendererSet.kind==='webgpu'?'gl2':'2d';
      const previousFailures=[...rendererSet.failures,event.detail || `${rendererSet.label} context lost`];
      for(const id of canvasIds){const old=$(id),fresh=old.cloneNode(false);old.replaceWith(fresh);}
      rendererSet=await createRenderers(canvasIds,forced);rendererSet.failures.unshift(...previousFailures);state.measured=false;state.whiteNits=100;$('white-nits').value=100;clearStored();capabilityLabels();patches();uploadedKeys=['',''];configureViewEvents();draw();
      status(`Graphics context lost. Switched to ${rendererSet.label}; remeasure reference white.`);
    }catch(error){fail(error);}finally{reloadPending=false;}
  });
}
function checkManifest(data) {
  const f=data.format;
  if(data.schema_version!==1 || f?.dtype!=='float16' || f.byte_order!=='little' || f.channels!==3 || !['linear-srgb','linear-display-p3','linear-bt2020','linear-xyz'].includes(f.color_space) || f.layout!==(f.color_space==='linear-xyz'?'frame-major HWC XYZ':'frame-major HWC RGB') || f.units!=='linear-nit')throw new Error('Unsupported export format. Regenerate with python3 -m sim export-web.');
  toLinear709(new Float32Array(3),f); // Validate the declared conversion before loading assets.
  for(const s of data.scenes) for(const p of data.profiles) {
    const a=s.assets[p.id];
    if(!a || a.width!==s.width || a.height!==s.height || a.frame_count!==s.frame_count || a.frame_stride_bytes!==a.width*a.height*6 || a.byte_length!==a.frame_stride_bytes*a.frame_count)throw new Error('Invalid scene dimensions or frame stride in export manifest.');
  }
}
async function main() {
  const response=await fetch('data/manifest.json');
  if(!response.ok)throw new Error('Missing web data. Run python3 -m sim export-web, then serve the repository with python3 -m http.server.');
  manifest=await response.json();checkManifest(manifest);
  for(const s of manifest.scenes){const option=new Option(s.title,s.id);$('scene').append(option);}
  $('scene').options[0].remove();$('scene').value=state.scene;
  for(const side of ['left','right']) {
    for(const p of manifest.profiles)$('tv-'+side).append(new Option(p.label,p.id));
    $('tv-'+side).value=state[side+'Profile'];
  }
  rendererSet=await createRenderers(canvasIds);
  state.requestedCeiling=hdrActive()?4:1;$('headroom-limit').value=state.requestedCeiling;
  restoreCalibration();capabilityLabels();patches();bindControls();await loadComparison();
}
main().catch(fail);
