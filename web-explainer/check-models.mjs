// Scientific verification of the browser figures against the existing CPU model.
// Run from any working directory: node web-explainer/check-models.mjs
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { localModel } from './figures/local-dimming.mjs';
import { hdrModel } from './figures/hdr.mjs';
import { persistenceOf } from './figures/pursuit.mjs';
const python=String.raw`
import json
import numpy as np
from dataclasses import replace
from sim.frame import Frame
from sim.profile import load_profile
from sim.stages.backlight import simulate_backlight
from sim.stages.panel import lcd_transmit
from sim.color import pq_eotf
from sim.load import abl_capacity
from sim.stages.tonemap import soft_shoulder
from pathlib import Path
base=Path('sim/profiles')
p=load_profile('generic_va_fald_miniled')
ld=[]
for x in [0,17,40,85,88]:
 for c in [4000,1200]:
  rgb=np.zeros((72,128,3),np.float32);rgb[24:47,x:x+40]=1000
  b=simulate_backlight(Frame(rgb),p.backlight).backlight
  out=lcd_transmit(rgb,b,c)
  probe=x+42 if x+42<128 else x-3
  ld.append(dict(x=x,c=c,field=out[:,:,0].flatten().tolist(),backlight=b.flatten().tolist(),halo=float(out[35,probe,0])))
hdr=[]
for key,name in [('va','generic_va_fald_miniled'),('woled','generic_woled'),('qdoled','generic_qdoled')]:
 hp=load_profile(name).hdr
 for code in [0,.508078,.75,1]:
  for a in [0,.1,.5,1]:
   y=float(pq_eotf(np.array(code)))
   capacity=abl_capacity(a*hp.panel_peak_nits,hp)
   output=float(soft_shoulder(np.array(y),capacity,hp.knee_ratio))
   hdr.append(dict(profile=key,code=code,a=a,input=y,capacity=capacity,output=output))
print(json.dumps(dict(ld=ld,hdr=hdr)))
`;
const proc=spawnSync('python3',['-c',python],{cwd:fileURLToPath(new URL('..',import.meta.url)),encoding:'utf8',maxBuffer:12*1024*1024});
if(proc.status!==0)throw Error(proc.stderr);
const reference=JSON.parse(proc.stdout);let maxError=0;
for(const r of reference.ld){const m=localModel(r.x,r.c);assert(!(m.probe[0]>=m.x0&&m.probe[0]<m.x0+m.ww),'halo probe must stay outside the window');for(const key of ['field','backlight'])for(let i=0;i<m[key].length;i++){const error=Math.abs(m[key][i]-r[key][i]);maxError=Math.max(maxError,error);assert(error<.001,`${key} differs at ${r.x}/${r.c}/${i}: ${error}`);}assert(Math.abs(m.halo-r.halo)<1e-6);}
for(const r of reference.hdr){const m=hdrModel(r.code,r.a,r.profile);for(const key of ['input','capacity','output'])assert(Math.abs(m[key]-r[key])<.001,`${key}: ${m[key]} != ${r[key]}`);}
for(const [f,d,v,time,width] of [[60,1,480,1000/60,8],[120,1,480,1000/120,4],[60,.5,480,1000/120,4],[120,.25,960,1000/480,2]]){const m=persistenceOf(f,d,v);assert(Math.abs(m.visibleMs-time)<1e-10);assert(Math.abs(m.supportPx-width)<1e-10);}
console.log(`PASS: 10 full local-dimming rasters vs Python (max error ${maxError.toExponential(2)} nit); 48 PQ/ABL/shoulder cases; 4 pursuit cases; all halo probes outside window.`);
