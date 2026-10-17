import * as k from '../vendor/iso-kit.mjs';
import * as A from '../vendor/audit.mjs';

// Figure: a bench light-table. Its thumb carriage moves the bright test window.
// 51 physical parts: foot pads/feet, chassis, rim, optical plate, driver covers,
// fasteners, ruler/rail/end stops, carriage, detent buttons, and knob assemblies.
// The screen is a diagnostic image, not an additional physical light source.
export function localModel(x0 = 40, contrast = 4000) {
  const W=128,H=72,ww=40,wh=23,y0=24;
  x0=Math.round(Math.max(0,Math.min(W-ww,x0)));
  const kernel=s=>{const r=Math.ceil(3*s),v=Array.from({length:2*r+1},(_,i)=>Math.exp(-.5*((i-r)/s)**2)),sum=v.reduce((a,b)=>a+b,0);return v.map(x=>x/sum)};
  const spread=(n,a,b,s)=>{const q=kernel(s),r=(q.length-1)/2;return Array.from({length:n},(_,x)=>q.reduce((z,v,i)=>{let j=x+i-r;while(j<0||j>=n)j=j<0?-j:2*n-2-j;return z+v*(j>=a&&j<b?1:0)},0))};
  const xa=Math.floor(x0/8)*8,xb=Math.ceil((x0+ww)/8)*8,ya=Math.floor(y0/6)*6,yb=Math.ceil((y0+wh)/6)*6;
  const cx=spread(W,xa,xb,6),cy=spread(H,ya,yb,4.5),tx=spread(W,xa,xb,16),ty=spread(H,ya,yb,12);
  const field=new Float32Array(W*H),backlight=new Float32Array(W*H);
  for(let y=0;y<H;y++)for(let x=0;x<W;x++){const B=1000*(.92*cx[x]*cy[y]+.08*tx[x]*ty[y]),T=x>=x0&&x<x0+ww&&y>=y0&&y<y0+wh?1000:0;backlight[y*W+x]=B;field[y*W+x]=Math.max(B/contrast,Math.min(T,B));}
  const probe=[x0+ww+2<W?x0+ww+2:x0-3,y0+Math.floor(wh/2)],idx=probe[1]*W+probe[0];
  return {W,H,x0,y0,ww,wh,field,backlight,probe,halo:field[idx],B:backlight[idx],zones:(xb-xa)/8*(yb-ya)/6};
}

export function renderLocalDimming() {
  const W=680,H=390,BASE={x:-168,y:-110,w:336,d:220,r:9};
  const screen={x:-138,y:-87,w:264,d:148.5,r:2};
  const P=k.fitProjection(k.boxCorners(BASE,-8,37),W,H,{pad:45,azimuth:38,elevation:42});
  const R=A.recorder(P),at=p=>k.iso(p,P);
  const slab=(name,plan,z,h,tone='mid',extra='',move=[0,0,0])=>{
    const shape=R.solid(A.slab(plan,z,h,{name,ground:name.startsWith('stand.')}));
    const svg=k.solidSvg(k.slabOf(plan,z,h,P,5,.5),{tone,inner:extra});
    R.put({name,at:[plan.x+plan.w/2,plan.y+plan.d/2,z+h/2],piece:name,move,shapes:[shape],svg:move[0]?`<g id="ld-carriage" transform="${k.translateAlong(P,[0,0,0])}">${svg}</g>`:svg});return shape;
  };
  const cyl=(name,x,y,r,z,h,tone='mid',extra='')=>{
    R.put({name,at:[x,y,z+h/2],piece:name,shapes:[R.solid(A.cylinder(x,y,r,z,h,{name}))],svg:k.solidSvg(k.cylinder(x,y,r,z,h,P,32,.25),{tone,inner:extra})});
  };
  for(const [i,[x,y]] of k.corners(BASE,23).entries()){
    slab('stand.pad'+i,{x:x-9,y:y-9,w:18,d:18,r:4},-8,3,'lo');
    slab('foot'+i,{x:x-7,y:y-7,w:14,d:14,r:3},-5,5,'mid');
  }
  slab('chassis',BASE,0,10,'mid',k.lineSvg(k.sideSeam(BASE,4,P,5),{tone:'faint'}));
  const rim=[{x:-148,y:-97,w:284,d:10,r:2},{x:-148,y:61.5,w:284,d:10,r:2},{x:-148,y:-87,w:10,d:148.5,r:1},{x:126,y:-87,w:10,d:148.5,r:1}];
  rim.forEach((p,i)=>slab('rim'+i,p,10,9,'mid'));
  slab('optical-bed',screen,10,8,'lo');
  const texture=`<image id="ld-texture" width="${screen.w}" height="${screen.d}" transform="${k.topMatrix([screen.x,screen.y],19,P)}" preserveAspectRatio="none"/>`;
  let grid='';
  for(let x=1;x<16;x++)grid+=k.lineOnTop([screen.x+x*screen.w/16,screen.y],[screen.x+x*screen.w/16,screen.y+screen.d],19,P);
  for(let y=1;y<12;y++)grid+=k.lineOnTop([screen.x,screen.y+y*screen.d/12],[screen.x+screen.w,screen.y+y*screen.d/12],19,P);
  slab('lcd-glass',screen,18,1,'hi',texture+k.lineSvg(grid,{tone:'faint'})+`<path id="ld-window" class="ld-window"/><path id="ld-probe" class="ld-probe"/>`);
  for(const [i,[x,y]] of k.corners({x:-143,y:-92,w:274,d:158.5,r:0},0).entries())cyl('rim-bolt'+i,x,y,1.8,19,1,'mid');
  // Side driver covers rest on the chassis, outside the optical assembly.
  for(let i=0;i<4;i++){
    const q={x:142,y:-86+i*37,w:16,d:31,r:2};
    let vents='';for(let j=0;j<4;j++)vents+=k.planOutline({x:146,y:q.y+7+j*5,w:8,d:1.5,r:.6},15,P,3);
    slab('driver'+i,q,10,5,'lo',k.lineSvg(vents,{tone:'faint'}));
    cyl('driver-bolt'+i,150,q.y+3,1.1,15,.8,'mid');
  }
  const rail={x:-138,y:77,w:264,d:7,r:1};
  slab('slide-rail',rail,10,4,'mid');
  const strip={x:-138,y:86,w:264,d:7,r:1};
  const ticks=k.topTicks(-134,122,4,4,86,11,[2,4.5],P);
  slab('ruler',strip,10,1,'lo',k.lineSvg(ticks.minor,{tone:'lo'})+k.lineSvg(ticks.major,{tone:'mid'}));
  for(const [i,x] of [-143,126].entries())slab('rail-stop'+i,{x,y:76,w:5,d:9,r:1},10,7,'mid');
  const carriagePlan={x:-10,y:77,w:20,d:7,r:1};
  slab('thumb-carriage',carriagePlan,14,6,'hi',k.lineSvg(k.planOutline(k.insetPlan(carriagePlan,2),20,P),{tone:'lo'}),[100,0,0]);
  const cp={x:-130,y:97,w:83,d:8,r:1};
  slab('nameplate',cp,10,1,'lo',k.lineSvg(k.planOutline(k.insetPlan(cp,1.5),11,P),{tone:'faint'})+k.faceTextSvg(k.topMatrix([-89,101],11,P),'LIGHT / 192',{size:3,tone:'mid',anchor:'middle'}));
  for(let i=0;i<6;i++){
    const x=-29+i*15;cyl('switch-base'+i,x,101,4.2,10,1.5,'lo');cyl('switch-cap'+i,x,101,2.9,11.5,2,'mid');
  }
  cyl('knob-seat',91,100,6,10,2,'lo');
  const kr=5,kz=12,kh=8;
  cyl('knob',91,100,kr,kz,kh,'mid',k.lineSvg(k.knurl(91,100,kr,kz,kz+kh,36,P,0),{tone:'lo'}));
  for(let i=0;i<4;i++)cyl('chassis-bolt'+i,...k.corners(BASE,10)[i],1.7,10,.8,'mid');
  // Carriage travel changes no overlap relationships: all other pieces are clear.
  A.settle(R,P,{states:[-.84,0,.5,1.008]});
  const svg=k.figureSvg({width:W,height:H,label:'192 分区局部调光光台。移动滑块改变亮窗位置，屏幕上的光晕与测点读数由同一个双高斯和 LCD 漏光模型计算。',body:[`<path class="iso-halo" d="${k.haloOf(BASE,-8,8,P)}"/>`,...R.items.sort((a,b)=>a.key-b.key).map(x=>x.svg)]});
  const live=`(()=>{
    const P=${JSON.stringify(P)},screen=${JSON.stringify(screen)},model=${localModel.toString()};
    const q=id=>document.getElementById(id),root=q('fig-ld'),slider=q('ld-position'),con=q('ld-contrast'),shadow=q('ld-shadow'),stage=q('ld-stage');
    const canvas=document.createElement('canvas');canvas.width=128;canvas.height=72;const ctx=canvas.getContext('2d'),texture=q('ld-texture');
    const still=matchMedia('(prefers-reduced-motion: reduce)');let x=40,target=40,visible=false,raf=0,last=0,idle=performance.now(),clock=0,drawn=-1,lastC=0,lastS=null;
    const path=(pts,closed=true)=>onTop(pts,19.1,P,closed);
    function draw(){const m=model(x,+con.value);if(drawn===m.x0&&lastC===+con.value&&lastS===shadow.checked)return;drawn=m.x0;lastC=+con.value;lastS=shadow.checked;
      const data=ctx.createImageData(128,72),reference=shadow.checked?5:1000;
      for(let i=0;i<m.field.length;i++){const l=Math.min(1,m.field[i]/reference),s=l<=.0031308?12.92*l:1.055*l**(1/2.4)-.055;data.data[4*i]=data.data[4*i+1]=data.data[4*i+2]=Math.round(s*255);data.data[4*i+3]=255}ctx.putImageData(data,0,0);texture.setAttribute('href',canvas.toDataURL());
      const ax=screen.x+m.x0/128*screen.w,ay=screen.y+m.y0/72*screen.d,bx=ax+m.ww/128*screen.w,by=ay+m.wh/72*screen.d;
      q('ld-window').setAttribute('d',path([[ax,ay],[bx,ay],[bx,by],[ax,by]]));const px=screen.x+(m.probe[0]+.5)/128*screen.w,py=screen.y+(m.probe[1]+.5)/72*screen.d;q('ld-probe').setAttribute('d',ring(px,py,1.8,19.2,P,20));
      q('ld-carriage').setAttribute('transform',translateAlong(P,[(m.x0-40)*2.1,0,0]));
      q('ld-readout').textContent='测点 '+m.halo.toFixed(4)+' nit · B='+m.B.toFixed(1)+' / C='+con.value;
      q('ld-zone-count').textContent=m.zones+' / 192';q('ld-exposure').textContent=shadow.checked?'光晕诊断 ×200':'共同曝光 ×1';q('ld-position-value').textContent=m.x0+' px';
      root.dataset.halo=m.halo;root.dataset.position=m.x0;root.dataset.backlight=m.B;
    }
    function tick(now){const dt=last?Math.min((now-last)/1000,1/30):1/60;last=now;if(now-idle>6000&&!still.matches&&!root.matches(':hover')&&!root.contains(document.activeElement)){clock+=dt;target=40+26*Math.sin(clock*.35);slider.value=target}x=still.matches?target:x+(target-x)*(1-Math.exp(-dt/.18));if(Math.abs(x-target)<.02)x=target;draw();raf=visible&&!still.matches?requestAnimationFrame(tick):0}
    const run=()=>{if(!raf&&visible){last=0;raf=requestAnimationFrame(tick)}};
    function input(){idle=performance.now();target=+slider.value;stage.setAttribute('aria-valuenow',Math.round(target));stage.setAttribute('aria-valuetext','亮窗位置 '+Math.round(target)+' / 88 像素');if(still.matches){x=target;draw()}else run()}
    [slider,con,shadow].forEach(el=>el.addEventListener('input',()=>{input();draw()}));root.addEventListener('pointerdown',()=>idle=performance.now());
    stage.addEventListener('pointermove',e=>{if(e.pointerType==='touch'&&e.buttons===0)return;const r=stage.getBoundingClientRect();target=Math.max(0,Math.min(88,(e.clientX-r.left)/r.width*110-11));slider.value=target;idle=performance.now();if(still.matches){x=target;draw()}else run()});
    stage.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();slider.value=e.key==='Home'?0:e.key==='End'?88:Math.max(0,Math.min(88,+slider.value+(e.key==='ArrowRight'?1:-1)));input();stage.setAttribute('aria-valuenow',slider.value)});
    new IntersectionObserver(es=>{visible=es.at(-1).isIntersecting;if(visible)run()}).observe(stage);still.addEventListener('change',()=>{if(still.matches){x=target;draw()}else run()});draw();
  })();`;
  return {svg,live,R,P,parts:R.solids.length};
}

export function auditLocalDimming(){const {R,P}=renderLocalDimming();return A.auditOrExit(R,P,{frames:[-.84,0,.5,1.008]});}
