#!/usr/bin/env node
// Dependency-free Chrome smoke check. Run the static server first, then:
// node web/tests/smoke.cjs [http://127.0.0.1:8000/web/]
// Screenshots and results are written outside the source tree.
'use strict';

const {spawn} = require('node:child_process');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const zlib = require('node:zlib');
const assert = require('node:assert/strict');

const url = process.argv[2] || 'http://127.0.0.1:8000/web/';
const out = process.env.TV_SMOKE_OUTPUT || '/tmp/tv-web-smoke';
const executable = process.env.CHROME_BIN || '/usr/bin/google-chrome';
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

class CDP {
  constructor(child) {
    this.child = child;
    this.nextId = 1;
    this.pending = new Map();
    this.listeners = [];
    this.buffer = Buffer.alloc(0);
    child.stdio[4].on('data', (chunk) => {
      this.buffer = Buffer.concat([this.buffer, chunk]);
      let end;
      while ((end = this.buffer.indexOf(0)) >= 0) {
        const raw = this.buffer.subarray(0, end).toString('utf8');
        this.buffer = this.buffer.subarray(end + 1);
        if (!raw) continue;
        const message = JSON.parse(raw);
        if (message.id) {
          const pending = this.pending.get(message.id);
          if (!pending) continue;
          this.pending.delete(message.id);
          clearTimeout(pending.timer);
          if (message.error) pending.reject(new Error(JSON.stringify(message.error)));
          else pending.resolve(message.result);
        } else {
          for (const listener of this.listeners) listener(message);
        }
      }
    });
    child.on('exit', (code) => {
      for (const pending of this.pending.values()) {
        clearTimeout(pending.timer);
        pending.reject(new Error(`Chrome exited (${code})`));
      }
      this.pending.clear();
    });
  }

  send(method, params = {}, sessionId) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`CDP timeout: ${method}`));
      }, 30000);
      this.pending.set(id, {resolve, reject, timer});
      const message = {id, method, params};
      if (sessionId) message.sessionId = sessionId;
      this.child.stdio[3].write(`${JSON.stringify(message)}\0`);
    });
  }
}

// Chrome screenshots use noninterlaced, eight-bit RGB/RGBA PNGs. Decode enough
// of the standard format to measure rendered pixels without an image package.
function pixelsFromPNG(base64) {
  const buffer = Buffer.from(base64, 'base64');
  assert.equal(buffer.subarray(1, 4).toString(), 'PNG', 'Chrome must return PNG');
  let width, height, channels;
  const compressed = [];
  for (let offset = 8; offset < buffer.length;) {
    const size = buffer.readUInt32BE(offset);
    const type = buffer.subarray(offset + 4, offset + 8).toString();
    const data = buffer.subarray(offset + 8, offset + 8 + size);
    if (type === 'IHDR') {
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      assert.equal(data[8], 8, 'Expected eight-bit screenshot');
      assert.ok(data[9] === 2 || data[9] === 6, 'Expected RGB or RGBA screenshot');
      channels = data[9] === 6 ? 4 : 3;
      assert.equal(data[12], 0, 'Expected noninterlaced screenshot');
    }
    if (type === 'IDAT') compressed.push(data);
    offset += size + 12;
  }
  const filtered = zlib.inflateSync(Buffer.concat(compressed));
  const rowBytes = width * channels;
  const pixels = Buffer.alloc(width * height * channels);
  let input = 0;
  function paeth(a, b, c) {
    const p = a + b - c, pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
    return pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
  }
  for (let y = 0; y < height; y++) {
    const filter = filtered[input++];
    for (let x = 0; x < rowBytes; x++) {
      const offset = y * rowBytes + x;
      const left = x >= channels ? pixels[offset - channels] : 0;
      const up = y ? pixels[offset - rowBytes] : 0;
      const upperLeft = y && x >= channels ? pixels[offset - rowBytes - channels] : 0;
      const predictors = [0, left, up, Math.floor((left + up) / 2), paeth(left, up, upperLeft)];
      assert.ok(filter <= 4, `PNG filter ${filter}`);
      pixels[offset] = (filtered[input++] + predictors[filter]) & 255;
    }
  }
  return {width, height, channels, pixels};
}

function imageStats(base64) {
  const {width, height, channels, pixels} = pixelsFromPNG(base64);
  let nonblack = 0, sum = 0, squares = 0, checksum = 2166136261;
  for (let i = 0; i < pixels.length; i += channels) {
    const value = (pixels[i] + pixels[i + 1] + pixels[i + 2]) / 3;
    if (value > 8) nonblack++;
    sum += value;
    squares += value * value;
    for (let channel = 0; channel < 3; channel++) checksum = Math.imul(checksum ^ pixels[i + channel], 16777619) >>> 0;
  }
  const count = width * height, mean = sum / count;
  const center = (Math.floor(height/2)*width+Math.floor(width/2))*channels;
  return {width, height, mean, nonblackFraction: nonblack / count, deviation: Math.sqrt(squares / count - mean * mean), checksum, centerPixel:Array.from(pixels.subarray(center,center+3))};
}

async function main() {
  await fs.mkdir(out, {recursive: true});
  const profile = await fs.mkdtemp(path.join(os.tmpdir(), 'tv-web-chrome-'));
  const extraFlags=JSON.parse(process.env.TV_SMOKE_CHROME_FLAGS || '[]');
  assert.ok(Array.isArray(extraFlags) && extraFlags.every(flag=>typeof flag === 'string' && flag.startsWith('--')), 'TV_SMOKE_CHROME_FLAGS must be a JSON array of Chrome flags');
  const child = spawn(executable, [
    '--headless=new', '--no-sandbox', '--disable-dev-shm-usage',
    '--use-angle=swiftshader', '--enable-unsafe-swiftshader',
    ...(process.env.TV_SMOKE_WEBGPU === '1' ? ['--enable-unsafe-webgpu','--use-webgpu-adapter=swiftshader'] : []),
    '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
    '--disable-backgrounding-occluded-windows',
    '--remote-debugging-pipe', '--hide-scrollbars', '--no-first-run',
    '--no-default-browser-check', ...extraFlags, `--user-data-dir=${profile}`, 'about:blank',
  ], {stdio: ['ignore', 'pipe', 'pipe', 'pipe', 'pipe']});
  let stderr = '';
  child.stderr.on('data', (chunk) => { stderr = (stderr + chunk.toString()).slice(-20000); });
  const cdp = new CDP(child);
  const errors = [];
  const results = {url, checks: [], screenshots: [], errors};
  let session;
  try {
    results.browser = (await cdp.send('Browser.getVersion')).product;
    const {targetId} = await cdp.send('Target.createTarget', {url: 'about:blank'});
    session = (await cdp.send('Target.attachToTarget', {targetId, flatten: true})).sessionId;
    await cdp.send('Target.activateTarget', {targetId});
    const send = (method, params = {}) => cdp.send(method, params, session);
    cdp.listeners.push((message) => {
      if (message.sessionId !== session) return;
      if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails.exception?.description || message.params.exceptionDetails.text);
      if (message.method === 'Runtime.consoleAPICalled' && message.params.type === 'error') errors.push(message.params.args.map((arg) => arg.value || arg.description).join(' '));
      if (message.method === 'Log.entryAdded' && message.params.entry.level === 'error') errors.push(message.params.entry.text);
    });
    await Promise.all([send('Page.enable'), send('Runtime.enable'), send('Log.enable')]);
    await send('Emulation.setDeviceMetricsOverride', {width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false});
    await send('Page.addScriptToEvaluateOnNewDocument', {source:`window.__tvSmokeBackends=[];new MutationObserver(records=>{for(const r of records)if(r.target===document.documentElement)window.__tvSmokeBackends.push({backend:r.target.dataset.backend,at:performance.now()});}).observe(document,{subtree:true,attributes:true,attributeFilter:['data-backend']});`});
    await send('Page.navigate', {url});
    async function evaluate(expression) {
      const result = await send('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
      if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
      return result.result.value;
    }
    async function until(expression, label, timeout = 30000) {
      const start = Date.now();
      while (Date.now() - start < timeout) {
        if (await evaluate(expression)) return;
        await sleep(100);
      }
      const debug = await evaluate(`({state:window.__tvPreview?.state,hidden:document.hidden,status:document.querySelector('#status')?.textContent,loading:document.documentElement?.dataset.loading})`).catch(()=>null);
      throw new Error(`Timed out: ${label}; ${JSON.stringify(debug)}`);
    }
    async function screenshot(name, selector) {
      const params = {format: 'png', captureBeyondViewport: true};
      if (selector) {
        const rect = await evaluate(`(() => { const r = document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect(); return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1}; })()`);
        assert.ok(rect.width > 0 && rect.height > 0, `${selector} has dimensions`);
        params.clip = rect;
      }
      const {data} = await send('Page.captureScreenshot', params);
      await fs.writeFile(path.join(out, `${name}.png`), Buffer.from(data, 'base64'));
      results.screenshots.push(`${name}.png`);
      const stats = imageStats(data);
      if (selector === '#wedge') {
        const {width,height,channels,pixels} = pixelsFromPNG(data);
        stats.centerSamples = Array.from({length:8},(_,i)=>{
          const offset=(Math.floor(height/2)*width+Math.floor((i+.5)*width/8))*channels;
          return Array.from(pixels.subarray(offset,offset+3));
        });
      }
      return stats;
    }
    async function setValue(selector, value, event = 'change') {
      await evaluate(`(() => { const e = document.querySelector(${JSON.stringify(selector)}); if (!e) throw new Error('Missing control: ' + ${JSON.stringify(selector)}); e.value = ${JSON.stringify(String(value))}; e.dispatchEvent(new Event(${JSON.stringify(event)}, {bubbles:true})); })()`);
      if (['#scene','#tv-left','#tv-right'].includes(selector)) {
        await until(`document.documentElement.dataset.loading === 'false' && !document.querySelector('#status').classList.contains('error')`, `${selector} asset load`);
      }
      await sleep(250);
    }
    function check(label, value) { assert.ok(value, label); results.checks.push(label); }

    await until(`document.documentElement?.dataset.ready === 'true'`, 'viewer ready', 60000);
    await sleep(300);
    check('Viewer marks itself ready', true);
    const canvases = await evaluate(`Array.from(document.querySelectorAll('#canvas-left, #canvas-right')).map(c => ({id:c.id, selector:'#'+c.id, width:c.width, height:c.height}))`);
    check('At least two comparison canvases exist', canvases.length >= 2);
    results.canvases = [];
    for (let i = 0; i < Math.min(canvases.length, 2); i++) {
      const stats = await screenshot(`canvas-${i + 1}`, canvases[i].selector);
      check(`Canvas ${i + 1} renders nonblack pixels`, stats.nonblackFraction > 0.01 && stats.deviation > 1);
      results.canvases.push({...canvases[i], ...stats});
    }
    await screenshot('desktop');

    const defaultScene = await evaluate(`document.querySelector('#scene').value`);
    await setValue('#scene', 'gradients');
    results.transferProbe = await screenshot('neutral-wedge', '#wedge');
    await screenshot('neutral-gradient', '#canvas-left');
    const nitSteps = [0,10,50,100,200,400,1000,2000];
    results.transferProbe.expectedSDR = nitSteps.map((n)=>{
      const v=n/2000;
      return Math.round(255*(v<=.0031308?12.92*v:1.055*v**(1/2.4)-.055));
    });
    check('Neutral step wedge follows one sRGB transfer', results.transferProbe.centerSamples.every((rgb,i)=>rgb.every(c=>Math.abs(c-results.transferProbe.expectedSDR[i])<=2)));
    await setValue('#scene', defaultScene);

    const sceneOptions = await evaluate(`Array.from(document.querySelector('#scene').options).map(o => o.value)`);
    const profileOptions = await evaluate(`Array.from(document.querySelector('#tv-left').options).map(o => o.value)`);
    check('All four TV profiles are selectable', profileOptions.length === 4);
    check('Gallery scenes and macro apertures are selectable', sceneOptions.length >= 5 && sceneOptions.includes('macro_apertures'));
    check('Capability and mapping reports are visible', await evaluate(`['#mapping-status','#renderer-status','#headroom-status'].every(s => document.querySelector(s)?.textContent.trim().length > 0)`));
    results.capabilities = await evaluate(`({backend:document.documentElement.dataset.backend,renderer:document.querySelector('#renderer-status').textContent,headroom:document.querySelector('#headroom-status').textContent,mapping:document.querySelector('#mapping-status').textContent,notes:document.querySelector('#render-notes').textContent})`);

    // Scene/profile changes load real exported buffers; compare the resulting
    // canvas screenshots rather than merely checking selected option values.
    const originalScene = await evaluate(`document.querySelector('#scene').value`);
    const nextScene = sceneOptions.find((value) => value !== originalScene && value !== 'macro_apertures');
    const beforeScene = await screenshot('before-scene', '#canvas-left');
    await setValue('#scene', nextScene);
    await sleep(750);
    const afterScene = await screenshot('after-scene', '#canvas-left');
    check('Scene selection changes displayed pixels', beforeScene.checksum !== afterScene.checksum);

    const originalProfile = await evaluate(`document.querySelector('#tv-left').value`);
    const nextProfile = profileOptions.find((value) => value !== originalProfile);
    await setValue('#tv-left', nextProfile);
    await sleep(750);
    const afterProfile = await screenshot('after-profile', '#canvas-left');
    check('TV selection changes displayed pixels', afterScene.checksum !== afterProfile.checksum);
    await setValue('#tv-right', originalProfile);
    check('Side-by-side TV selectors work independently', await evaluate(`document.querySelector('#tv-left').value !== document.querySelector('#tv-right').value`));

    await setValue('#mode', 'scaled');
    const scaled = await screenshot('scaled', '#canvas-left');
    await setValue('#mode', 'clipped');
    const clipped = await screenshot('clipped', '#canvas-left');
    check('Scaled and clipped mappings produce different pixels', scaled.checksum !== clipped.checksum);
    check('Mapping report identifies clipped mode', await evaluate(`/clip/i.test(document.querySelector('#mapping-status').textContent)`));
    await setValue('#mode', 'scaled');

    const calibrationBefore = await evaluate(`document.querySelector('#mapping-status').textContent`);
    await setValue('#measured-nits', 173);
    await evaluate(`document.querySelector('#calibrate').click()`);
    await sleep(200);
    const calibrationAfter = await evaluate(`document.querySelector('#mapping-status').textContent`);
    check('Measured luminance updates calibration report', calibrationAfter !== calibrationBefore && /173/.test(calibrationAfter));
    await evaluate(`document.querySelector('#reset-calibration').click()`);
    await sleep(200);
    check('Calibration can be reset', await evaluate(`document.querySelector('#mapping-status').textContent`) !== calibrationAfter);
    const reference = await screenshot('reference-patch', '#reference-patch');
    check('Calibration reference patch is visible', reference.nonblackFraction > 0.05);
    check('Calibration reference patch remains neutral component-one white', reference.centerPixel.every(c=>c === 255));

    await evaluate(`document.querySelector('#macro').click()`);
    await sleep(750);
    check('Macro control selects the exported aperture scene', await evaluate(`document.querySelector('#scene').value === 'macro_apertures'`));
    await screenshot('macro');
    await setValue('#tv-left', 'generic_woled');
    await setValue('#tv-right', 'generic_qdoled');
    await screenshot('macro-oled');
    const beforeZoom = await screenshot('before-zoom', '#canvas-left');
    await setValue('#zoom', 4, 'input');
    const afterZoom = await screenshot('after-zoom', '#canvas-left');
    check('Macro zoom changes displayed pixels', beforeZoom.checksum !== afterZoom.checksum);

    const canvasBounds = await evaluate(`(() => { const r = document.querySelector('#canvas-left').getBoundingClientRect(); return {x:r.x,y:r.y,width:r.width,height:r.height}; })()`);
    const x = canvasBounds.x + canvasBounds.width * 0.5, y = canvasBounds.y + canvasBounds.height * 0.5;
    await send('Input.dispatchMouseEvent', {type:'mouseMoved',x,y});
    await send('Input.dispatchMouseEvent', {type:'mousePressed',x,y,button:'left',clickCount:1});
    await send('Input.dispatchMouseEvent', {type:'mouseMoved',x:x+67,y:y+31,button:'left',buttons:1});
    await send('Input.dispatchMouseEvent', {type:'mouseReleased',x:x+67,y:y+31,button:'left',clickCount:1});
    await sleep(200);
    const afterPan = await screenshot('after-pan', '#canvas-left');
    check('Dragging pans the zoomed image', afterPan.checksum !== afterZoom.checksum);
    const zoomBeforeWheel = await evaluate(`Number(document.querySelector('#zoom').value)`);
    await send('Input.dispatchMouseEvent', {type:'mouseWheel',x,y,deltaX:0,deltaY:-120});
    await sleep(200);
    check('Mouse wheel changes zoom', await evaluate(`Number(document.querySelector('#zoom').value)`) !== zoomBeforeWheel);

    if (sceneOptions.includes('motion_pan')) await setValue('#scene', 'motion_pan');
    await setValue('#zoom', 1, 'input');
    await sleep(750);
    const playbackBefore = await screenshot('before-playback', '#canvas-left');
    await until(`!document.querySelector('#play').disabled`, 'motion sequence loaded');
    const firstFrame = await evaluate(`document.documentElement.dataset.frame`);
    await evaluate(`document.querySelector('#play').click()`);
    await until(`(() => { if(document.documentElement.dataset.frame === ${JSON.stringify(firstFrame)}) return false; document.querySelector('#play').click(); return true; })()`, 'playback advances exported frames');
    const playbackAfter = await screenshot('after-playback', '#canvas-left');
    check('Motion playback advances frames and changes pixels', playbackBefore.checksum !== playbackAfter.checksum);
    await setValue('#timeline', 0, 'input');
    check('Timeline can seek back to the first frame', await evaluate(`Number(document.querySelector('#timeline').value) === 0`));
    await screenshot('desktop-interactive');

    // Keep this final group after interaction assertions so it also catches
    // errors emitted by later loads and playback, not just startup failures.
    await send('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
    await sleep(400);
    check('Mobile document fits its viewport', await evaluate('document.documentElement.scrollWidth <= innerWidth + 1'));
    await screenshot('mobile');
    results.backendTransitions = await evaluate('window.__tvSmokeBackends');
    await sleep(100);
    assert.deepEqual(errors, [], 'No browser console/page/resource errors');
    results.checks.push('No browser console/page/resource errors');
    await fs.writeFile(path.join(out, 'results.json'), JSON.stringify(results, null, 2) + '\n');
    console.log(JSON.stringify(results, null, 2));
  } catch (error) {
    results.failure = error.stack;
    results.chromeStderr = stderr;
    await fs.writeFile(path.join(out, 'results.json'), JSON.stringify(results, null, 2) + '\n');
    console.error(error.stack);
    process.exitCode = 1;
  } finally {
    await fs.writeFile(path.join(out, 'chrome-stderr.log'), stderr).catch(()=>{});
    await cdp.send('Browser.close').catch(() => {});
    child.kill('SIGTERM');
    await fs.rm(profile, {recursive: true, force: true}).catch(() => {});
  }
}

main().catch((error) => { console.error(error.stack); process.exitCode = 1; });
