import { writeFileSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { ISO_CSS } from './vendor/iso-kit.mjs';
import { kitScript } from './vendor/inline-kit.mjs';
import { renderLocalDimming, auditLocalDimming } from './figures/local-dimming.mjs';
import { renderHDR } from './figures/hdr.mjs';
import { renderPursuit } from './figures/pursuit.mjs';
import { page } from './page.mjs';
const here=dirname(fileURLToPath(import.meta.url));
const ld=renderLocalDimming(), hdr=renderHDR(), pursuit=renderPursuit();
const runtime=kitScript()+'\nconst ISO={iso,translateAlong,lineOnTop};\n'+readFileSync(join(here,'app.js'),'utf8')+'\n'+ld.live+'\n'+hdr.live+'\n'+pursuit.live;
for(const theme of ['dark','light']){const name=theme==='dark'?'index.html':'index-light.html';writeFileSync(join(here,name),page({ld,hdr,pursuit,runtime,theme,isoCSS:ISO_CSS}));console.log('Built '+name);}
if(process.argv.includes('--audit')){
  auditLocalDimming();
  const hm=await import('./figures/hdr.mjs');if(hm.auditHDR)hm.auditHDR();
  const pm=await import('./figures/pursuit.mjs');if(pm.auditPursuit)pm.auditPursuit();
}
