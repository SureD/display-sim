import * as k from '../vendor/iso-kit.mjs';
import * as A from '../vendor/audit.mjs';

// Figure: a two-meter photometric instrument. All mechanical dimensions below
// are illustration geometry; no physical dimensions of a television are claimed.
// 57 real, individually recorded parts: feet, shell, panel, fasteners, two
// stepped meter cases, two moving pointers, a PQ knob, profile selector,
// ten-cell APL indicator, connector bosses and a screwed-on calibration plate.
export const HDR_PROFILES = {
  woled: { name: 'WOLED', peak: 850, full: 170, gamma: 2.4, knee: 0.85 },
  qdoled: { name: 'QD-OLED', peak: 1100, full: 199, gamma: 1, knee: 0.85 },
  va: { name: 'VA mini-LED', peak: 2000, full: 620, gamma: 1, knee: 0.70 },
};

export const HDR_NOTES = {
  title: '亮度预算仪 / Luminance budget meter',
  hint: '调节 PQ 信号与归一化 APL；左表读输出，右表读容量占比。',
  caption: '独立的中性像素 soft_clip 演示，手动指定归一化负载 a。左表量程 0–2000 nits，右表量程 0–100% P₀，十格指示条显示 a。装置比例仅为插画。三组容量、拐点与 ABL 形状均为 P 级占位参数，并非实测电视。原始 profile 默认 abl_source=emitted；demand 模式改由上游请求图像提供 APL。此处手动覆盖负载以单独展示函数。',
  sources: ['sim/color.py', 'sim/load.py', 'sim/stages/tonemap.py', 'sim/profiles/generic_woled.yaml', 'sim/profiles/generic_qdoled.yaml', 'sim/profiles/generic_va_fald_miniled.yaml', 'research/03-color-hdr.md', 'research/m3-hdr-abl-params.md'],
};

// Same scalar equations as sim/color.py, sim/load.py and stages/tonemap.py.
// APL is explicitly independent here, rather than inferred from a PQ code.
export function hdrModel(code, a, profile = 'woled') {
  const p = HDR_PROFILES[profile] || HDR_PROFILES.woled;
  const clamp = (n, low, high) => Math.min(high, Math.max(low, n));
  const v = clamp(code, 0, 1) ** (32 / 2523);
  const input = Math.fround(10000 * (Math.max(v - 3424 / 4096, 0) / Math.max(2413 / 128 - 2392 / 128 * v, 1e-12)) ** (16384 / 2610));
  const load = clamp(a, 0, 1);
  const capacity = p.full + (p.peak - p.full) * (1 - load) ** p.gamma;
  // The Python stage stores and operates on float32 luminance.
  const f = Math.fround;
  const peak = f(capacity), knee = f(peak * f(p.knee)), span = f(peak - knee);
  const excess = f(Math.max(f(input - knee), 0));
  const attenuation = f(Math.exp(-Math.min(f(excess / span), 40)));
  const shoulder = f(knee + f(span * f(1 - attenuation)));
  const output = input <= knee ? input : Math.min(shoulder, peak);
  return { input, capacity, output, load, p };
}

const W = 680, H = 380;
const BASE = { x: -138, y: -71, w: 276, d: 142, r: 11 };
const PANEL = { x: -133, y: -66, w: 266, d: 132, r: 8 };
const MAIN = { x: -51, y: -14, r: 43, z: 31.2 };
const CAP = { x: 66, y: -15, r: 28, z: 27.2 };
const KNOB = { x: -92, y: 46, r: 10.5, z: 25 };
const SELECTOR = { x: 96, y: 44, r: 8, z: 23 };
const START = -Math.PI * 0.75, SPAN = Math.PI * 1.5;
const P = k.fitProjection([...k.boxCorners(BASE, -9, 14), [-94, -55, 33], [94, 28, 31]], W, H, { pad: 35, azimuth: 48, elevation: 38 });

function needleAt(dial, share, tail = 4) {
  const angle = START + SPAN * Math.min(1, Math.max(0, share));
  return k.lineOnTop([dial.x - Math.sin(angle) * tail, dial.y + Math.cos(angle) * tail], [dial.x + Math.sin(angle) * (dial.r - 9), dial.y - Math.cos(angle) * (dial.r - 9)], dial.z + 0.15, P);
}

function buildInstrument() {
  const R = A.recorder(P);
  const put = (name, at, paths, shape, style = {}, extra = '') => {
    const svg = k.solidSvg(paths, style) + extra;
    return R.put({ name: `hdr.${name}`, at, svg, shapes: [R.solid(shape)] });
  };
  const slab = (name, plan, z, h, tone = 'mid', inner = '') => put(name, [plan.x + plan.w / 2, plan.y + plan.d / 2, z + h / 2], k.slabOf(plan, z, h, P, 8, h > 1 ? 0.6 : 0), A.slab(plan, z, h, { name: `hdr.${name}` }), { tone, inner });
  const cyl = (name, x, y, r, z, h, tone = 'mid', inner = '', extra = '', meta = {}) => put(name, [x, y, z + h / 2], k.cylinder(x, y, r, z, h, P, r > 25 ? 72 : 32, h > 1 ? 0.45 : 0), A.cylinder(x, y, r, z, h, { name: `hdr.${name}`, ...meta }), { tone, inner }, extra);
  const line = (path, tone = 'lo', opts = {}) => k.lineSvg(path, { tone, ...opts });
  const dot = (x, y, z, tone = 'mid', size = 0.5) => k.dotsSvg([k.iso([x, y, z], P)], { tone, size });
  const screw = (name, x, y, z, r = 1.6) => cyl(name, x, y, r, z, 0.65, 'mid', line(k.ring(x, y, r * 0.7, z + 0.65, P, 24), 'faint') + dot(x, y, z + 0.65));

  for (const [i, [x, y]] of k.corners(BASE, 21).entries()) {
    cyl(`foot-${i}-sole`, x, y, 8, -9, 2, 'lo', '', '', { ground: true });
    cyl(`foot-${i}-body`, x, y, 6.2, -7, 7, 'lo');
  }
  slab('shell', BASE, 0, 12, 'lo', line(k.sideSeam(BASE, 5, P, 8), 'faint'));
  slab('top-panel', PANEL, 12, 2, 'mid', line(k.planOutline(k.insetPlan(PANEL, 3), 14, P, 8), 'faint'));
  for (const [i, [x, y]] of k.corners(PANEL, 8).entries()) screw(`panel-screw-${i}`, x, y, 14, 1.85);

  function meter(name, d, lowerZ) {
    cyl(`${name}-seat`, d.x, d.y, d.r + 3, 14, 2.5, 'mid');
    cyl(`${name}-case`, d.x, d.y, d.r, 16.5, lowerZ - 16.5, 'mid', line(k.sideArc(d.x, d.y, d.r, 19, P, 72), 'faint'));
    cyl(`${name}-bezel`, d.x, d.y, d.r + 0.8, lowerZ, d.z - 0.7 - lowerZ, 'hi', line(k.knurl(d.x, d.y, d.r + 0.8, lowerZ, d.z - 0.7, 96, P, 0), 'lo'));
    const face = cyl(`${name}-face`, d.x, d.y, d.r - 3, d.z - 0.7, 0.7, 'hi');
    const radius = d.r - 5.8;
    const t = k.radialTicks(d.x, d.y, radius, 40, 5, d.z, [2.2, 3.6], P, START, SPAN);
    face.svg += line(k.ring(d.x, d.y, radius, d.z, P, 96), 'lo') + line(t.minor, 'lo') + line(t.major, 'mid');
    // Two pointers are ordinary light-weight meter needles, above the face.
    // They are drawn as open pointer strokes, whose tips may end on a face.
    const m = hdrModel(0.75, 0.1);
    face.svg += `<path id="hdr-${name}-needle" class="iso-line" data-tone="${name === 'main' ? 'lit' : 'hi'}" data-free="" d="${needleAt(d, name === 'main' ? m.output / 2000 : m.capacity / m.p.peak)}" style="stroke-width:${name === 'main' ? 1.45 : 1.1}"/>`;
    for (const [i, angle] of [0.25, 0.75, 1.25, 1.75].entries()) {
      const a = angle * Math.PI;
      screw(`${name}-bezel-screw-${i}`, d.x + Math.sin(a) * (d.r - 1.3), d.y + Math.cos(a) * (d.r - 1.3), d.z - 0.7, 1.05);
    }
    cyl(`${name}-hub`, d.x, d.y, 2.25, d.z, 1.0, 'mid', line(k.ring(d.x, d.y, 1.05, d.z + 1, P, 24), 'lo'));
  }
  meter('main', MAIN, 27);
  meter('cap', CAP, 23);

  // Three tangible controls: a large input potentiometer, a load bar window,
  // and a three-detent profile selector. All stand on the top panel.
  cyl('pq-seat', KNOB.x, KNOB.y, KNOB.r + 3, 14, 2, 'lo');
  const knob = cyl('pq-knob', KNOB.x, KNOB.y, KNOB.r, 16, KNOB.z - 16, 'mid', line(k.knurl(KNOB.x, KNOB.y, KNOB.r, 16, KNOB.z, 40, P, 0), 'lo'));
  knob.svg += `<path id="hdr-pq-pointer" class="iso-line" data-tone="hi" data-free="" d="${needleAt({ ...KNOB, r: 16 }, 0.75, 0)}" style="stroke-width:1.1"/>` + dot(KNOB.x, KNOB.y, KNOB.z, 'hi', 0.6);
  const kt = k.radialTicks(KNOB.x, KNOB.y, KNOB.r + 2, 20, 5, 16, [1.1, 2], P, START, SPAN);
  knob.svg += line(k.ring(KNOB.x, KNOB.y, KNOB.r + 2, 16, P, 72), 'faint') + line(kt.minor, 'lo') + line(kt.major, 'mid');

  const window = { x: -49, y: 36, w: 104, d: 22, r: 3 };
  slab('load-window-seat', window, 14, 1.7, 'lo');
  const bezel = slab('load-window-bezel', k.insetPlan(window, 1), 15.7, 1.5, 'mid', line(k.planOutline(k.insetPlan(window, 2.8), 17.2, P, 8), 'lo'));
  for (let i = 0; i < 10; i++) {
    const cell = { x: -41 + i * 8.6, y: 40.6, w: 6.8, d: 12.8, r: 0.8 };
    const item = slab(`load-cell-${i}`, cell, 17.2, 0.6, 'lo');
    item.svg += `<path id="hdr-load-${i}" d="${k.planOutline(k.insetPlan(cell, 0.9), 17.8, P, 6)}" fill="var(--anatomy-hi)" opacity="${i === 0 ? 0.95 : 0.10}"/>`;
  }
  screw('load-window-left-screw', -45.5, 47, 17.2, 1.05);
  screw('load-window-right-screw', 51.5, 47, 17.2, 1.05);

  cyl('selector-seat', SELECTOR.x, SELECTOR.y, 11, 14, 2, 'lo');
  const detent = cyl('selector-knob', SELECTOR.x, SELECTOR.y, SELECTOR.r, 16, SELECTOR.z - 16, 'mid', line(k.knurl(SELECTOR.x, SELECTOR.y, SELECTOR.r, 16, SELECTOR.z, 32, P, 0), 'lo'));
  detent.svg += `<path id="hdr-profile-pointer" class="iso-line" data-tone="hi" data-free="" d="${needleAt({ ...SELECTOR, r: 14 }, 0.1, 0)}"/>` + dot(SELECTOR.x, SELECTOR.y, SELECTOR.z, 'hi');
  for (let i = 0; i < 3; i++) {
    const a = START + SPAN * (0.1 + i * 0.4);
    const [x, y] = [SELECTOR.x + Math.sin(a) * 9.5, SELECTOR.y - Math.cos(a) * 9.5];
    detent.svg += dot(x, y, 16, i === 0 ? 'hi' : 'lo', 0.5);
  }

  const nameplate = { x: -125, y: -59, w: 32, d: 12, r: 1.5 };
  const np = slab('calibration-plate', nameplate, 14, 0.8, 'lo', line(k.planOutline(k.insetPlan(nameplate, 1.5), 14.8, P, 6), 'faint'));
  np.svg += k.faceTextSvg(k.topMatrix([-109, -52.1], 14.8, P), 'NITS', { size: 4, tone: 'mid', anchor: 'middle' });
  screw('calibration-plate-left', -121.5, -53, 14.8, 0.75);
  screw('calibration-plate-right', -96.5, -53, 14.8, 0.75);

  // Two recessed connector bosses with closed socket rims at the rear.
  for (const [i, x] of [27, 47].entries()) {
    cyl(`connector-${i}-boss`, x, -52, 5.2, 14, 2.0, 'mid');
    cyl(`connector-${i}-socket`, x, -52, 3.5, 16, 1.5, 'lo', line(k.ring(x, -52, 2.1, 17.5, P, 32), 'faint'));
  }

  A.settle(R, P);
  R.items.sort((a, b) => a.key - b.key);
  const halo = `<path class="iso-halo" d="${k.haloOf(BASE, -9, 9, P)}"/>`;
  return { R, body: halo + R.items.map(item => item.svg).join('') };
}

let cached;
function instrument() { return cached ||= buildInstrument(); }

export function auditHDR() {
  const { R } = instrument();
  A.auditOrExit(R, P, { argv: ['--audit'] });
  return R;
}

export function renderHDR() {
  const { body, R } = instrument();
  const svg = k.figureSvg({ width: W, height: H, className: 'hdr-art', label: '两个指针表组成的亮度预算仪：左表为映射输出 nits，右表为 APL 允许峰值与 P₀ 的比值。下方旋钮对应 PQ 信号，十格窗口对应手动 APL。', body }).replace('<svg ', `<svg id="hdr-svg" data-parts="${R.solids.length}" `);
  const live = `
;(() => {
  const profiles = ${JSON.stringify(HDR_PROFILES)};
  const HDR_PROFILES = profiles;
  const model = ${hdrModel.toString()};
  const P = ${JSON.stringify(P)}, MAIN = ${JSON.stringify(MAIN)}, CAP = ${JSON.stringify(CAP)}, KNOB = ${JSON.stringify(KNOB)}, SELECTOR = ${JSON.stringify(SELECTOR)};
  const START = ${START}, SPAN = ${SPAN};
  const svg = document.getElementById('hdr-svg');
  const codeEl = document.getElementById('hdr-code'), aplEl = document.getElementById('hdr-apl'), profileEl = document.getElementById('hdr-profile');
  const readout = document.getElementById('hdr-readout');
  if (!svg || !codeEl || !aplEl || !profileEl) return;
  const mainNeedle = document.getElementById('hdr-main-needle'), capNeedle = document.getElementById('hdr-cap-needle');
  const pqPointer = document.getElementById('hdr-pq-pointer'), selectorPointer = document.getElementById('hdr-profile-pointer');
  const cells = Array.from({length: 10}, (_, i) => document.getElementById('hdr-load-' + i));
  const still = matchMedia('(prefers-reduced-motion: reduce)');
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const needle = (d, share, tail = 4) => {
    const a = START + SPAN * clamp(share, 0, 1);
    return lineOnTop([d.x - Math.sin(a) * tail, d.y + Math.cos(a) * tail], [d.x + Math.sin(a) * (d.r - 9), d.y - Math.cos(a) * (d.r - 9)], d.z + 0.15, P);
  };
  let code = Number(codeEl.value), load = Number(aplEl.value), shownCode = code, shownLoad = load;
  let visible = false, frame = 0, last = 0, tourTime = 0, idleTimer = 0, lastInteraction = performance.now(), touring = !still.matches;
  let profile = profileEl.value;
  const tour = [0.10, 0.40, 0.75, 1.00, 0.10];
  function draw() {
    const m = model(shownCode, shownLoad, profile);
    mainNeedle.setAttribute('d', needle(MAIN, m.output / 2000));
    capNeedle.setAttribute('d', needle(CAP, m.capacity / m.p.peak));
    pqPointer.setAttribute('d', needle({...KNOB, r: 16}, shownCode, 0));
    const selection = {woled: 0.1, qdoled: 0.5, va: 0.9}[profile] ?? 0.1;
    selectorPointer.setAttribute('d', needle({...SELECTOR, r: 14}, selection, 0));
    cells.forEach((cell, i) => cell.setAttribute('opacity', String(0.1 + 0.85 * clamp(shownLoad * 10 - i, 0, 1))));
    const format = n => n >= 100 ? n.toFixed(0) : n.toFixed(1);
    const text = 'PQ ' + shownCode.toFixed(3) + ' → ' + format(m.input) + ' nits · 容量 ' + format(m.capacity) + ' → 输出 ' + format(m.output) + ' nits · a=' + (shownLoad * 100).toFixed(0) + '%';
    if (readout && readout.textContent !== text) readout.textContent = text;
    svg.dataset.inputNits = String(m.input); svg.dataset.capacityNits = String(m.capacity); svg.dataset.outputNits = String(m.output); svg.dataset.apl = String(shownLoad); svg.dataset.profile = profile;
    const cv = document.getElementById('hdr-code-value'), av = document.getElementById('hdr-apl-value');
    if (cv) cv.textContent = shownCode.toFixed(3);
    if (av) av.textContent = (shownLoad * 100).toFixed(0) + '%';
  }
  function tick(now) {
    frame = 0;
    const dt = last ? Math.min((now - last) / 1000, 1 / 25) : 1 / 60; last = now;
    if (!visible) return;
    if (touring && !still.matches && now - lastInteraction > 6500 && !svg.closest('figure')?.contains(document.activeElement)) {
      tourTime += dt; load = tour[Math.floor(tourTime / 3) % tour.length]; aplEl.value = load;
    }
    const gain = still.matches ? 1 : 1 - Math.exp(-dt / 0.32);
    shownCode += (code - shownCode) * gain; shownLoad += (load - shownLoad) * gain;
    if (Math.abs(code - shownCode) < 0.00001) shownCode = code;
    if (Math.abs(load - shownLoad) < 0.00001) shownLoad = load;
    draw();
    if (visible && !still.matches && (touring || shownCode !== code || shownLoad !== load)) frame = requestAnimationFrame(tick);
  }
  function run() { if (visible && !frame) { last = 0; frame = requestAnimationFrame(tick); } }
  function quiet() {
    lastInteraction = performance.now(); tourTime = 0; touring = false;
    clearTimeout(idleTimer);
    if (!still.matches) idleTimer = setTimeout(() => { touring = true; lastInteraction = performance.now() - 6501; run(); }, 6500);
  }
  function steer() {
    code = Number(codeEl.value); load = Number(aplEl.value); profile = profileEl.value;
    quiet();
    if (still.matches) { shownCode = code; shownLoad = load; draw(); }
    run();
  }
  for (const control of [codeEl, aplEl, profileEl]) { control.addEventListener('input', steer); control.addEventListener('change', steer); }
  svg.addEventListener('pointerdown', quiet);
  new IntersectionObserver(entries => {
    visible = entries[entries.length - 1].isIntersecting;
    if (visible) run(); else if (frame) { cancelAnimationFrame(frame); frame = 0; }
  }, {rootMargin: '0px'}).observe(svg);
  still.addEventListener('change', () => { touring = !still.matches; if (still.matches) { shownCode = code; shownLoad = load; draw(); } else run(); });
  draw();
})();
`;
  return { svg, live, notes: HDR_NOTES, parts: R.solids.length };
}
