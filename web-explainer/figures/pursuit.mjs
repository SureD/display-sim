import * as k from '../vendor/iso-kit.mjs';
import * as A from '../vendor/audit.mjs';
import * as G from '../vendor/lathe.mjs';

/* Figure, 67 purposeful solids. Object: a motorised pursuit camera on two
   supported rails, a real panel on a stand, and its exposure inspection tray.
   The teaching speed is a parameter; support width is the research equation,
   never a claimed measured MPRT. No television calibration is implied. */
export function persistenceOf(refresh = 60, duty = 1, speed = 480) {
  const visibleMs = 1000 * duty / refresh;
  return { visibleMs, supportPx: speed * visibleMs / 1000, meanRatio: duty };
}

const W = 680, H = 380;
const BASE = { x: -145, y: -72, w: 290, d: 169, r: 8 };
const P = k.fitProjection([...k.boxCorners(BASE, -13, 0), [-125,-55,108], [125,-55,108]], W, H, { pad: 34, azimuth: 32, elevation: 29 });
const at = (p) => k.iso(p, P);
const S = k.solidSvg, L = k.lineSvg;
const quad = (points) => k.pathOf(points.map(at), true);
const face = (x0,x1,z0,z1) => quad([[x0,-48.42,z0],[x1,-48.42,z0],[x1,-48.42,z1],[x0,-48.42,z1]]);
const exposure = (width) => k.onTop([[59-width/2,75],[59+width/2,75],[59+width/2,84],[59-width/2,84]], 1.9, P, true);

function scene(cameraX = 0) {
  const R = A.recorder(P);
  let count = 0;
  const put = (name, shape, svg, centre, moving=false, extra='') => {
    shape.name = name;
    shape.owner = moving ? 'pursuit.camera' : name.startsWith('stand.') ? 'stand.frame' : 'pursuit.panel';
    R.solid(shape);
    const transform = moving ? ` data-pursuit-moving transform="${k.translateAlong(P,[cameraX,0,0])}"` : '';
    const item = R.put({ name, at: centre, shapes:[shape], svg:`<g${transform}${extra}>${svg}</g>` });
    if (moving && cameraX) { item.shapes = [A.moved(shape,[cameraX,0,0])]; Object.assign(shape, item.shapes[0]); }
    count++;
    return item;
  };
  const slab = (name,plan,z,h,tone='mid',moving=false,detail='',lit=false) => put(name,A.slab(plan,z,h),S(k.slabOf(plan,z,h,P,6,Math.min(.65,h/5)),{tone,lit})+detail,[plan.x+plan.w/2,plan.y+plan.d/2,z+h/2],moving);
  const cyl = (name,x,y,r,z,h,tone='mid',moving=false,slot=false) => {
    const detail = slot ? L(k.lineOnTop([x-r,y],[x+r,y],z+h,P),{tone:'lo'}) : '';
    return put(name,A.cylinder(x,y,r,z,h),S(k.cylinder(x,y,r,z,h,P,32,.25),{tone})+detail,[x,y,z+h/2],moving);
  };
  // Heavy optical bench: four isolation pads, four feet, a bevelled deck.
  for (const [i,[x,y]] of k.corners(BASE,19).entries()) {
    slab(`stand.pad${i}`,{x:x-7,y:y-7,w:14,d:14,r:3},-13,2,'lo');
    slab(`stand.foot${i}`,{x:x-5,y:y-5,w:10,d:10,r:2},-11,5,'mid');
  }
  slab('stand.deck',BASE,-6,6,'lo',false,L(k.planOutline(k.insetPlan(BASE,4),0,P),{tone:'faint'}));
  for (const [i,[x,y]] of k.corners(BASE,10).entries()) cyl(`stand.deck-bolt${i}`,x,y,2.1,0,.8,'mid',false,true);

  // Two panel mounting shoes, uprights and top pads support the housing.
  for (const [i,x] of [-91,91].entries()) {
    slab(`stand.panel-shoe${i}`,{x:x-16,y:-66,w:32,d:25,r:3},0,3);
    for (const [j,dx] of [-11,11].entries()) cyl(`stand.panel-bolt${i}-${j}`,x+dx,-54,1.5,3,.7,'mid',false,true);
    slab(`stand.panel-post${i}`,{x:x-5,y:-58,w:10,d:9,r:1.2},3,20,'mid');
    slab(`stand.panel-seat${i}`,{x:x-12,y:-59,w:24,d:13,r:2},23,3,'mid');
  }
  slab('panel.housing',{x:-124,y:-55,w:248,d:6,r:3},26,79,'mid');
  // One panel plane contains its emitted test target. It is deliberately dark
  // except for a single lit bar; the bar's width isn't pixel-response time.
  const screenPlan={x:-116,y:-49,w:232,d:.5,r:0};
  const screenArt = S(k.slabOf(screenPlan,34,64,P,1),{tone:'lo',crease:'none'})+
    `<g data-pursuit-target><path d="${face(-3,3,45,87)}" fill="var(--anatomy-lit)" opacity=".94"/><path d="${face(-.6,.6,45,87)}" fill="var(--anatomy-hi)" opacity=".92"/></g>`;
  put('panel.screen',A.slab(screenPlan,34,64),screenArt,[0,-48.75,66]);
  slab('panel.lower-rim',{x:-119,y:-49,w:238,d:1.3,r:0},27,5,'hi');
  slab('panel.upper-rim',{x:-119,y:-49,w:238,d:1.3,r:0},100,3,'mid');
  for(const [i,x] of [-121,119].entries()) slab(`panel.side-rim${i}`,{x,y:-49,w:2,d:1.3,r:0},29,72,'mid');
  for(const [i,x] of [-110,110].entries()) cyl(`panel.top-bolt${i}`,x,-52,1.2,105,.6,'mid',false,true);

  // Rails remain fixed; camera and saddle travel together along x. Bushings
  // sit above rails and the saddle sits on the four bushings, with no overlap.
  for(const [j,y] of [39,64].entries()) {
    for(const [i,x] of [-126,126].entries()) {
      slab(`stand.rail-shoe${j}-${i}`,{x:x-8,y:y-8,w:16,d:16,r:2},0,3,'mid');
      slab(`stand.rail-leg${j}-${i}`,{x:x-4,y:y-4,w:8,d:8,r:1},3,4,'mid');
    }
    slab(`stand.rail${j}`,{x:-130,y:y-2.5,w:260,d:5,r:1.2},7,6,'hi');
    for(const [i,x] of [-130,125].entries()) slab(`stand.rail-stop${j}-${i}`,{x,y:y-4,w:5,d:8,r:1},13,5,'mid');
  }
  for(const [j,y] of [39,64].entries()) for(const [i,x] of [-20,20].entries())
    slab(`camera.shoe${j}-${i}`,{x:x-6,y:y-3.5,w:12,d:7,r:1.2},13,4,'mid',true);
  slab('camera.saddle',{x:-29,y:31,w:58,d:41,r:3},17,4,'mid',true);
  for(const [i,[x,y]] of [[-23,35],[23,35],[-23,68],[23,68]].entries()) cyl(`camera.saddle-bolt${i}`,x,y,1.4,21,.8,'mid',true,true);
  slab('camera.riser',{x:-14,y:43,w:28,d:15,r:2},21,4,'mid',true);
  const bodyPlan={x:-21,y:37,w:42,d:28,r:3};
  slab('camera.body',bodyPlan,25,29,'hi',true,L(k.planOutline(k.insetPlan(bodyPlan,2),54,P),{tone:'faint'}));
  slab('camera.cap',{x:-18,y:39,w:36,d:23,r:2},54,2,'mid',true);
  slab('camera.hot-shoe',{x:-6,y:44,w:12,d:8,r:1},56,2,'mid',true);
  cyl('camera.shutter',13,47,2.7,56,2,'hi',true,true);
  cyl('camera.mode-dial',-12,53,4,56,2.5,'mid',true,true);
  slab('camera.grip',{x:21,y:42,w:5,d:18,r:2},29,21,'mid',true);
  // The barrel points towards the physical panel, not towards the viewer.
  const F=G.frameAlong([0,37,40],[0,-1,0]);
  const lens=[['mount',0,2,10,'mid'],['focus',2,8,8,'hi'],['rim',8,10,9,'mid'],['glass',10,10.45,7.2,'lo']];
  for(const [name,s0,s1,r,tone] of lens) {
    const profile=[[s0,r],[s1,r]];
    put(`camera.lens-${name}`,A.solid(F,profile),S(G.solidOf(profile,F,P,{steps:48}),{tone,crease:'lo'}),[0,37-(s0+s1)/2,40],true);
  }
  // A held exposure laid on an inspection tray: fixed aspect, variable width.
  const tray={x:8,y:72,w:102,d:17,r:2};
  const trayDetail=L(k.planOutline(k.insetPlan(tray,2),1.5,P),{tone:'faint'})+
    `<path data-pursuit-exposure d="${exposure(24)}" fill="url(#pursuit-exposure-ink)"/>`;
  slab('stand.exposure-tray',tray,0,1.5,'lo',false,trayDetail);
  const rule={x:-116,y:81,w:106,d:9,r:1};
  const y=rule.y+2,z=.7;
  let ruleArt=L(k.lineOnTop([rule.x+3,y],[rule.x+rule.w-3,y],z,P),{tone:'faint'});
  const ticks=[];
  for(let x=rule.x+3;x<=rule.x+rule.w-3;x+=5)ticks.push(k.lineOnTop([x,y],[x,rule.y+rule.d],z,P));
  ruleArt+=L(ticks.join(''),{tone:'lo'});
  slab('stand.travel-ruler',rule,0,.7,'mid',false,ruleArt);

  A.settle(R,P,{step:1});
  const items=[...R.items].sort((a,b)=>a.key-b.key);
  return {R,count,markup:items.map(p=>p.svg).join('')};
}

export function renderPursuit() {
  const {markup}=scene();
  const svg=k.figureSvg({width:W,height:H,label:'追踪相机在双导轨上跟随屏幕目标。发光保持时间越长，相机的积分影像越宽。',body:`<defs><linearGradient id="pursuit-exposure-ink"><stop offset="0" stop-color="var(--anatomy-lit)" stop-opacity=".08"/><stop offset=".16" stop-color="var(--anatomy-lit)" stop-opacity=".8"/><stop offset=".84" stop-color="var(--anatomy-lit)" stop-opacity=".8"/><stop offset="1" stop-color="var(--anatomy-lit)" stop-opacity=".08"/></linearGradient></defs><path class="iso-halo" d="${k.haloOf(BASE,-13,12,P)}"/>${markup}`}).replace('<svg','<svg id="pursuit-figure"');
  const live=`(function(){
  const persistenceOf=${persistenceOf.toString()};
  const root=document.getElementById('pursuit-figure');if(!root)return;
  const P=${JSON.stringify(P)},moving=[...root.querySelectorAll('[data-pursuit-moving]')],target=root.querySelector('[data-pursuit-target]'),ink=root.querySelector('[data-pursuit-exposure]');
  const refresh=document.getElementById('pursuit-refresh'),duty=document.getElementById('pursuit-duty'),speed=document.getElementById('pursuit-speed'),readout=document.getElementById('pursuit-readout');
  const still=matchMedia('(prefers-reduced-motion: reduce)');
  const iso=(p)=>ISO.iso(p,P),path=(pts)=>'M'+pts.map(p=>iso(p).map(v=>v.toFixed(2)).join(',')).join('L')+'Z';
  let frame=0,last=0,clock=0,visible=false,hidden=document.hidden;
  function values(){return {f:Number(refresh?.value)||60,d:Math.max(.25,Math.min(1,Number(duty?.value)||1)),v:Number(speed?.value)||480};}
  function draw(){const {f,d,v}=values(),{visibleMs:t,supportPx:b}=persistenceOf(f,d,v);
    const travel=140,progress=clock*.12*v*.16,cycle=progress%(travel*2),x=-70+(cycle<travel?cycle:travel*2-cycle);
    const sampleTime=Math.floor(clock*.12*f)/f,sp=sampleTime*v*.16,sc=sp%(travel*2),sx=-70+(sc<travel?sc:travel*2-sc);
    moving.forEach(p=>p.setAttribute('transform',ISO.translateAlong(P,[x,0,0])));target.setAttribute('transform',ISO.translateAlong(P,[sx,0,0]));
    const width=b*3;ink.setAttribute('d',path([[59-width/2,75,1.9],[59+width/2,75,1.9],[59+width/2,84,1.9],[59-width/2,84,1.9]]));
    const text=t.toFixed(2)+' ms · '+b.toFixed(2)+' px';if(readout&&readout.textContent!==text)readout.textContent=text;
    if(duty)duty.setAttribute('aria-valuetext',Math.round(d*100)+'% 发光占空比；保持 '+t.toFixed(2)+' 毫秒');
    root.setAttribute('aria-label','追踪相机实验：'+f+' Hz，发光 '+Math.round(d*100)+'%，理论保持宽度 '+b.toFixed(2)+' 像素。图中运动以 0.12 倍慢放。');
  }
  function tick(now){frame=0;if(!visible||hidden||still.matches)return;const dt=last?Math.min((now-last)/1000,1/30):0;last=now;clock+=dt;draw();frame=requestAnimationFrame(tick);}
  function run(){if(!frame&&visible&&!hidden&&!still.matches){last=0;frame=requestAnimationFrame(tick);}}
  function halt(){if(frame)cancelAnimationFrame(frame);frame=0;last=0;}
  for(const input of [refresh,duty,speed])input?.addEventListener('input',()=>{draw();run();});
  new IntersectionObserver(e=>{visible=e[e.length-1].isIntersecting;if(visible)run();else halt();},{rootMargin:'80px'}).observe(root);
  document.addEventListener('visibilitychange',()=>{hidden=document.hidden;if(hidden)halt();else run();});
  still.addEventListener('change',()=>{if(still.matches){halt();draw();}else run();});
  draw();
})();`;
  return {svg,live};
}

export function auditPursuit() {
  let failures=0;
  const home=scene().R;
  const keys=new Map(home.items.map(item=>[item.name,item.key]));
  for(const x of [-70,0,70]) {
    const {R,count}=scene(x);
    R.items.forEach(item=>{item.key=keys.get(item.name);});
    const result=A.audit(R,P);
    console.log('Pursuit Figure · camera x='+x+' · '+count+' solids');
    console.log(A.report(result));
    failures+=A.failures(result);
  }
  console.log(failures?'pursuit audit failed: '+failures:'pursuit audit passed');
  if(failures)process.exitCode=1;
  return failures;
}
