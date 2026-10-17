// Run directly with Node: no npm package metadata or build step is required.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';

const moduleSource = await readFile(new URL('../mapping.js', import.meta.url), 'utf8');
const {halfToFloat, decodeFrame, extendedSRGB, linear709ToP3, mappingGain, rgba, toLinear709} =
  await import(`data:text/javascript;base64,${Buffer.from(moduleSource).toString('base64')}`);

const near = (actual, expected, tolerance = 1e-10) =>
  assert.ok(Math.abs(actual - expected) <= tolerance, `${actual} differs from ${expected}`);

test('binary16 decoding retains small absolute nits, large HDR nits, sign and IEEE special values', () => {
  const examples = [
    [0x0000, 0], [0x0001, 0.000000059604644775390625],
    [0x03ff, 0.000060975551605224609375], [0x0400, 0.00006103515625],
    [0x3555, 0.333251953125], [0x3c00, 1], [0x5640, 100],
    [0x67d0, 2000], [0x7bff, 65504], [0xbc00, -1],
  ];
  for (const [bits, expected] of examples) assert.equal(halfToFloat(bits), expected);
  assert.ok(Object.is(halfToFloat(0x8000), -0));
  assert.equal(halfToFloat(0x7c00), Infinity);
  assert.equal(halfToFloat(0xfc00), -Infinity);
  assert.ok(Number.isNaN(halfToFloat(0x7c01)));
  assert.ok(Number.isNaN(halfToFloat(0xffff)));
});

test('frame decoding uses little endian bytes, declared frame stride, top-to-bottom rows and interleaved RGB', () => {
  // Two 2×2 frames separated by four bytes of padding. Each row has distinct
  // channel values, so a channel/row swap or contiguous-frame assumption fails.
  const bytes = new Uint8Array([
    0x00,0x3c, 0x00,0x40, 0x00,0x42, 0x00,0x44, 0x00,0x45, 0x00,0x46,
    0x00,0x47, 0x00,0x48, 0x80,0x48, 0x00,0x49, 0x80,0x49, 0x00,0x4a,
    0x00,0x7c, 0x00,0x7c,
    0x00,0x4c, 0x00,0x4d, 0x00,0x4e, 0x00,0x4f, 0x00,0x50, 0x80,0x50,
    0x00,0x51, 0x80,0x51, 0x00,0x52, 0x80,0x52, 0x00,0x53, 0x80,0x53,
  ]);
  assert.deepEqual(Array.from(decodeFrame(bytes.buffer, 2, 2, 0, 28)),
    [1,2,3, 4,5,6, 7,8,9, 10,11,12]);
  assert.deepEqual(Array.from(decodeFrame(bytes.buffer, 2, 2, 1, 28)),
    [16,20,24, 28,32,36, 40,44,48, 52,56,60]);
  assert.throws(() => decodeFrame(bytes.buffer, 2, 2, 2, 28), RangeError);
});

test('asset decoder rejects NaN and infinity instead of displaying an invalid HDR signal', () => {
  for (const bits of [0x7c00, 0xfc00, 0x7c01]) {
    const buffer = new ArrayBuffer(6), view = new DataView(buffer);
    view.setUint16(2, bits, true);
    assert.throws(() => decodeFrame(buffer, 1, 1), /nonfinite float16/);
  }
});

test('sRGB output transfer preserves reference white, the toe and extended values above one', () => {
  near(extendedSRGB(0), 0);
  near(extendedSRGB(0.001), 0.01292);
  near(extendedSRGB(0.0031308), 0.040449936);
  near(extendedSRGB(0.18), 0.46135612950044164);
  near(extendedSRGB(1), 1);
  near(extendedSRGB(2), 1.3532560461493863);
  assert.ok(extendedSRGB(4) > extendedSRGB(2));
  near(extendedSRGB(-0.18), -0.46135612950044164);
  near(extendedSRGB(-2), -1.3532560461493863);
});

test('linear BT.709 to P3 preserves D65 neutrals and XYZ colorimetry before the output transfer', () => {
  // Independently specified RGB→XYZ matrices derived from the D65 primaries.
  // Checking XYZ tests chromaticity, rather than repeating the P3 conversion.
  const srgbXYZ = [
    [0.4123907992659595, 0.3575843393838780, 0.1804807884018343],
    [0.2126390058715104, 0.7151686787677560, 0.0721923153607337],
    [0.0193308187155918, 0.1191947797946260, 0.9505321522496607],
  ];
  const p3XYZ = [
    [0.4865709486482162, 0.2656676931690931, 0.1982172852343625],
    [0.2289745640697488, 0.6917385218365064, 0.0792869140937450],
    [0, 0.0451133818589026, 1.0439443689009760],
  ];
  const xyz = (matrix, rgb) => matrix.map(row => row.reduce((sum, a, i) => sum + a * rgb[i], 0));
  for (const level of [0, 0.001, 0.18, 1, 4]) {
    for (const value of linear709ToP3(level, level, level)) near(value, level, 1e-9);
  }
  for (const rgb of [[1,0,0], [0,1,0], [0,0,1], [0.7,0.2,3.5]]) {
    const expected = xyz(srgbXYZ, rgb), converted = xyz(p3XYZ, linear709ToP3(...rgb));
    converted.forEach((value, i) => near(value, expected[i], 5e-10));
  }
});

test('relative scaling uses one declared scene ceiling across TVs and all motion frames', () => {
  const gain = mappingGain('scaled', 100, 2000, 4, 0);
  near(2000 * gain, 4);
  near(500 * gain, 1);
  near(100 * gain, 0.2);
  // A meter reading changes the white-based request, not a relative preview.
  assert.equal(mappingGain('scaled', 600, 2000, 4, 0), gain);
  const tvA = [0, 100, 1000, 1500], tvB = [0, 100, 250, 500];
  const a = tvA.map(nits => nits * gain), b = tvB.map(nits => nits * gain);
  near(a[1], b[1]);
  near(a[3] / b[3], 3); // no per-TV peak normalization
  near(mappingGain('scaled', 100, 2000, 4, 1), 2 * gain);
  near(mappingGain('scaled', 100, 2000, 4, -2), gain / 4);
});

test('white-based requests preserve the measured nit ratio and expose the explicit clipping point', () => {
  const gain = mappingGain('clipped', 100, 2000, 4, 0);
  near(100 * gain, 1);
  near(400 * gain, 4);
  assert.deepEqual([0,10,100,500,2000].map(nits => Math.min(4, nits * gain)), [0,0.1,1,4,4]);
  assert.equal(mappingGain('clipped', 100, 500, 4, 0), gain);
  near(mappingGain('clipped', 200, 2000, 4, 0), gain / 2);
  near(mappingGain('clipped', 100, 2000, 4, 1), 2 * gain);
  // SDR fallback reduces the available component ceiling; reference white
  // remains component one and is not silently reduced to make peaks fit.
  assert.equal(mappingGain('clipped', 100, 2000, 1, 0), gain);
  near(mappingGain('scaled', 100, 2000, 1, 0), 1 / 2000);
});

test('GPU upload expands interleaved RGB to opaque RGBA without clipping HDR values', () => {
  const input = new Float32Array([0.25, 0.5, 2, 100, 2000, 4]);
  assert.deepEqual(Array.from(rgba(input)), [0.25,0.5,2,1, 100,2000,4,1]);
  assert.deepEqual(Array.from(input), [0.25,0.5,2, 100,2000,4]);
});

test('M15 declared linear matrices preserve signed gamut coordinates and legacy bytes', () => {
  const legacy = new Float32Array([100, 200, 300]);
  assert.equal(toLinear709(legacy, {color_space:'linear-srgb'}), legacy);
  // BT.2020→BT.709 D65 from normalized primary matrices, no transfer or clip.
  const matrix = [[1.6604910021,-0.5876411388,-0.0728498633],
    [-0.1245504745,1.1328998971,-0.0083494226],[-0.0181507634,-0.1005788980,1.1187296614]];
  const red = toLinear709(new Float32Array([100,0,0]), {color_space:'linear-bt2020',to_linear_srgb:matrix});
  near(red[0],166.04910021,1e-5);near(red[1],-12.45504745,1e-6);assert.ok(red[2]<0);
  const white = toLinear709(legacy.fill(100), {color_space:'linear-bt2020',to_linear_srgb:matrix});
  for(const component of white) near(component,100,1e-5);
  assert.throws(()=>toLinear709(legacy,{color_space:'linear-xyz'}),/Missing linear/);
  assert.throws(()=>toLinear709(legacy,{color_space:'linear-xyz',to_linear_srgb:[[NaN]]}),/Invalid linear/);
});
