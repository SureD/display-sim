// Preview transform only. TV processing remains in the exported CPU frames.
export function halfToFloat(bits) {
  const sign = bits & 0x8000 ? -1 : 1;
  const exp = (bits >> 10) & 31, fraction = bits & 1023;
  if (exp === 31) return fraction ? NaN : sign * Infinity;
  return sign * (exp ? 2 ** (exp - 15) * (1 + fraction / 1024) : 2 ** -14 * fraction / 1024);
}

export function decodeFrame(buffer, width, height, index = 0, stride = width * height * 6) {
  const count = width * height * 3;
  const view = new DataView(buffer, index * stride, count * 2);
  const rgb = new Float32Array(count);
  for (let i = 0; i < count; i++) {
    const value = halfToFloat(view.getUint16(i * 2, true));
    if (!Number.isFinite(value)) throw new Error('Export contains nonfinite float16 values');
    rgb[i] = value;
  }
  return rgb;
}

export function extendedSRGB(linear) {
  const a = Math.abs(linear);
  return Math.sign(linear) * (a <= 0.0031308 ? 12.92 * a : 1.055 * a ** (1 / 2.4) - 0.055);
}

export function linear709ToP3(r, g, b) {
  return [0.8224619687 * r + 0.1775380313 * g,
    0.0331941989 * r + 0.9668058011 * g,
    0.0170826307 * r + 0.0723974407 * g + 0.9105199286 * b];
}

export function mappingGain(mode, whiteNits, scenePeak, ceiling, exposure) {
  return 2 ** exposure * (mode === 'scaled' ? ceiling / scenePeak : 1 / whiteNits);
}

export function rgba(rgb) {
  const out = new Float32Array(rgb.length / 3 * 4);
  for (let i = 0, j = 0; i < rgb.length; i += 3, j += 4) {
    out[j] = rgb[i]; out[j + 1] = rgb[i + 1]; out[j + 2] = rgb[i + 2]; out[j + 3] = 1;
  }
  return out;
}
