// 外滩漫游 - first-person walkthrough of the Shanghai Bund.
// Geometry: GLB files exported from the Blender model (blender/export_web.py).
// Data: assets/world.json (footprints, trees, lamps, ferry route...), Blender axes:
//   x = east, y = north, z = up  ->  three.js: (x, z, -y)
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { Sky } from 'three/addons/objects/Sky.js';
import { computeBoundsTree, disposeBoundsTree, acceleratedRaycast } from 'three-mesh-bvh';

THREE.BufferGeometry.prototype.computeBoundsTree = computeBoundsTree;
THREE.BufferGeometry.prototype.disposeBoundsTree = disposeBoundsTree;
THREE.Mesh.prototype.raycast = acceleratedRaycast;

const ASSETS = ['ground', 'bridges', 'landmarks', 'buildings_core', 'buildings_back', 'lujiazui', 'context'];
const WALKABLE = new Set(['ground', 'bridges']);
const SUN = { elevation: 19, azimuth: 114 };      // golden early-morning light, as in the Blender renders
const EYE = 1.65, RADIUS = 0.32, STEP = 0.6, WALK = 1.6, RUN = 4.2, FLY = 30;

const $ = (id) => document.getElementById(id);
const B = (x, y, z = 0) => new THREE.Vector3(x, z, -y);       // Blender -> three

// ---------------------------------------------------------------------------
// procedural textures (tileable value noise painted on canvases)
// ---------------------------------------------------------------------------
function hash(x, y, s) {
  let h = (x * 374761393 + y * 668265263 + s * 982451653) | 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967295;
}
function vnoise(x, y, s, p) {
  const xi = Math.floor(x), yi = Math.floor(y), xf = x - xi, yf = y - yi;
  const u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf);
  const m = (a) => ((a % p) + p) % p;
  const a = hash(m(xi), m(yi), s), b = hash(m(xi + 1), m(yi), s);
  const c = hash(m(xi), m(yi + 1), s), d = hash(m(xi + 1), m(yi + 1), s);
  return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v;
}
function fbm(x, y, s, p, oct = 4) {
  let f = 0, amp = 0.5, fr = 1, sum = 0;
  for (let i = 0; i < oct; i++) { f += amp * vnoise(x * fr, y * fr, s + i * 17, p * fr); sum += amp; amp *= 0.5; fr *= 2; }
  return f / sum;
}
const hex = (h) => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
const mixc = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];

let MAX_ANISO = 4;
function paint(w, h, fn, srgb = true) {
  const c = document.createElement('canvas'); c.width = w; c.height = h;
  const ctx = c.getContext('2d'); const img = ctx.createImageData(w, h); const d = img.data;
  const H = new Float32Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const out = fn(x / w, 1 - (y + 1) / h, x, y);
    const i = (y * w + x) * 4;
    d[i] = out[0]; d[i + 1] = out[1]; d[i + 2] = out[2]; d[i + 3] = out[3] ?? 255;
    H[y * w + x] = out[4] ?? 0.5;
  }
  ctx.putImageData(img, 0, 0);
  const tex = new THREE.CanvasTexture(c);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.anisotropy = MAX_ANISO;
  if (srgb) tex.colorSpace = THREE.SRGBColorSpace;
  tex.userData.height = H; tex.userData.w = w; tex.userData.h = h;
  return tex;
}
function normalFrom(tex, strength = 2) {
  const { height: H, w, h } = tex.userData;
  const c = document.createElement('canvas'); c.width = w; c.height = h;
  const ctx = c.getContext('2d'); const img = ctx.createImageData(w, h); const d = img.data;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const hl = H[y * w + (x + w - 1) % w], hr = H[y * w + (x + 1) % w];
    const hu = H[((y + h - 1) % h) * w + x], hd = H[((y + 1) % h) * w + x];
    let nx = (hl - hr) * strength, ny = (hd - hu) * strength, nz = 1;
    const l = Math.hypot(nx, ny, nz); nx /= l; ny /= l; nz /= l;
    const i = (y * w + x) * 4;
    d[i] = (nx * 0.5 + 0.5) * 255; d[i + 1] = (ny * 0.5 + 0.5) * 255; d[i + 2] = (nz * 0.5 + 0.5) * 255; d[i + 3] = 255;
  }
  ctx.putImageData(img, 0, 0);
  const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.anisotropy = MAX_ANISO;
  return t;
}

// stone ashlar: blocks of bw x bh metres on a texture covering `size` metres
function texStone(base, { size = 2.4, bw = 1.1, bh = 0.48, joint = 0.012, rustic = false, seed = 1 } = {}) {
  const c0 = hex(base); const N = 512;
  return paint(N, N, (u, v, px, py) => {
    const X = u * size, Y = v * size;
    const row = Math.floor(Y / bh); const off = (row % 2) * bw * 0.5;
    const bx = ((X + off) % bw + bw) % bw, by = ((Y % bh) + bh) % bh;
    const j = rustic ? 0.035 : joint;
    const jm = (bx < j || by < j) ? 1 : 0;
    const n = fbm(u * 6, v * 6, seed, 6), n2 = fbm(u * 24, v * 24, seed + 9, 24, 2);
    const blockTone = (hash(Math.floor((X + off) / bw), row, seed) - 0.5) * 0.12;
    let c = mixc(c0, [30, 30, 30], 0.18 * n + 0.1 * n2 - blockTone);
    if (hash(px, py, seed + 3) > 0.985) c = mixc(c, [20, 20, 20], 0.5);
    // rain streaks (vertical)
    const st = fbm(u * 18, v * 1.5, seed + 4, 18, 3); c = mixc(c, [40, 38, 34], Math.pow(Math.max(0, st - 0.45), 2) * 1.6);
    if (jm) c = mixc(c, [50, 48, 44], rustic ? 0.65 : 0.35);
    return [c[0], c[1], c[2], 255, jm ? 0 : 0.6 + n2 * 0.2];
  });
}
function texBrick(c1, c2, mortar, { band = null, bandColor = '#ddd5c4', size = 2.5, seed = 2 } = {}) {
  const a = hex(c1), b = hex(c2), m = hex(mortar), bc = hex(bandColor); const N = 512;
  const bw = 0.25, bh = 0.0625;
  return paint(N, N, (u, v, px, py) => {
    const X = u * size, Y = v * size;
    if (band) {
      const f = ((Y % band[0]) + band[0]) % band[0];
      if (f < band[1]) { const n = fbm(u * 8, v * 8, seed + 5, 8); const c = mixc(bc, [60, 60, 60], 0.15 * n); return [c[0], c[1], c[2], 255, 0.7]; }
    }
    const row = Math.floor(Y / bh); const off = (row % 2) * bw * 0.5;
    const bx = ((X + off) % bw + bw) % bw, by = ((Y % bh) + bh) % bh;
    const jm = bx < 0.012 || by < 0.011;
    const t = hash(Math.floor((X + off) / bw), row, seed);
    let c = jm ? m : mixc(a, b, t);
    const n = fbm(u * 5, v * 5, seed, 5); c = mixc(c, [25, 22, 20], 0.25 * n);
    const st = fbm(u * 16, v * 1.4, seed + 4, 16, 3); c = mixc(c, [30, 28, 26], Math.pow(Math.max(0, st - 0.45), 2) * 1.4);
    return [c[0], c[1], c[2], 255, jm ? 0 : 0.7];
  });
}
function texNoise(base, { size = 4, varr = 0.25, seed = 3, fine = 0.1, dark = [20, 20, 20], speck = 0 } = {}) {
  const c0 = hex(base); const N = 512;
  return paint(N, N, (u, v, px, py) => {
    const n = fbm(u * 4, v * 4, seed, 4, 5), n2 = hash(px, py, seed);
    let c = mixc(c0, dark, varr * n + fine * n2);
    if (speck && n2 > 1 - speck) c = mixc(c, [230, 230, 225], 0.35);
    return [c[0], c[1], c[2], 255, 0.5 + 0.3 * n];
  });
}
function texTiles(base, alt, { size = 2.4, tw = 0.6, th = 0.3, seed = 4 } = {}) {
  const a = hex(base), b = hex(alt); const N = 512;
  return paint(N, N, (u, v, px, py) => {
    const X = u * size, Y = v * size;
    const row = Math.floor(Y / th); const off = (row % 2) * tw * 0.5;
    const bx = ((X + off) % tw + tw) % tw, by = ((Y % th) + th) % th;
    const jm = bx < 0.008 || by < 0.008;
    let c = mixc(a, b, hash(Math.floor((X + off) / tw), row, seed));
    const n = fbm(u * 5, v * 5, seed, 5); c = mixc(c, [40, 40, 38], 0.18 * n);
    if (hash(px, py, seed + 1) > 0.98) c = mixc(c, [30, 30, 30], 0.4);
    if (jm) c = mixc(c, [60, 58, 54], 0.6);
    return [c[0], c[1], c[2], 255, jm ? 0.1 : 0.6];
  });
}
function texRoofTiles(base, { glazed = false, size = 2.0, pitch = 0.25, seed = 5 } = {}) {
  const c0 = hex(base); const N = 256;
  return paint(N, N, (u, v) => {
    const X = u * size, Y = v * size;
    const w = 0.5 + 0.5 * Math.sin(X * 2 * Math.PI / pitch);
    const r = ((Y % 0.32) + 0.32) % 0.32 / 0.32;
    const n = fbm(u * 4, v * 4, seed, 4);
    let c = mixc(c0, [10, 10, 10], 0.35 * (1 - w) + 0.15 * n + (r < 0.1 ? 0.3 : 0));
    if (glazed) c = mixc(c, [255, 255, 255], 0.08 * w);
    return [c[0], c[1], c[2], 255, w * 0.6 + r * 0.4];
  });
}
function texWindow(frame, { panes = [2, 3], interior = 'mix', seed = 6 } = {}) {
  // 4 variants in a 2x2 atlas: plain dark, curtains, blinds, lit; the per-face
  // variant comes from the material suffix assigned at export time.
  const f = hex(frame); const N = 256;
  return [0, 1, 2, 3].map((variant) => paint(N, N, (u, v) => {
    const fw = 0.055;
    let fr = u < fw || u > 1 - fw || v < fw * 0.8 || v > 1 - fw * 0.8;
    if (panes[0] > 1) { const mu = (u * panes[0]) % 1; fr = fr || mu < 0.025 * panes[0] || mu > 1 - 0.025 * panes[0]; }
    if (panes[1] > 1) { const mv = (v * panes[1]) % 1; fr = fr || mv < 0.018 * panes[1] || mv > 1 - 0.018 * panes[1]; }
    if (fr) return [f[0], f[1], f[2], 255, 1];
    let c = [22, 24, 26];
    const sky = mixc([70, 85, 100], [150, 165, 180], v);           // faint sky reflection
    if (variant === 1) c = v > 0.35 ? [160, 142, 112] : [30, 30, 30];
    if (variant === 2) c = (v * 30) % 1 < 0.5 ? [190, 188, 178] : [150, 148, 140];
    if (variant === 3) c = [120, 112, 92];
    c = mixc(c, sky, 0.22);
    return [c[0], c[1], c[2], 255, 0];
  }));
}
function texCurtain(glass, mullion, spandrel, { module = 1.5, floor = 3.8, seed = 7 } = {}) {
  const g = hex(glass), m = hex(mullion), s = hex(spandrel); const W = 256, H = 512;
  return paint(W, H, (u, v) => {
    // texture covers 2 modules x 2 floors
    const X = u * 2, Y = v * 2;
    const fx = X % 1, fy = Y % 1;
    const cell = hash(Math.floor(X), Math.floor(Y), seed);
    if (fx < 0.05 || fx > 0.95) return [m[0], m[1], m[2], 255, 1];
    if (fy < 0.22) return [s[0], s[1], s[2], 255, 0.5];
    let c = mixc(g, [10, 12, 14], cell * 0.35);
    c = mixc(c, [190, 200, 210], (fy - 0.22) * 0.25);
    return [c[0], c[1], c[2], 255, 0];
  });
}
function texPunched(wall, glass, { bay = 3.2, floor = 3.4, ww = 1.7, wh = 1.9, sill = 0.9, seed = 8 } = {}) {
  const w = hex(wall), g = hex(glass); const N = 256;
  return paint(N, N, (u, v) => {
    const X = u * bay, Y = v * floor;
    const inWin = Math.abs(X - bay / 2) < ww / 2 && Y > sill && Y < sill + wh;
    if (inWin) { const c = mixc(g, [150, 160, 170], (Y - sill) / wh * 0.3); return [c[0], c[1], c[2], 255, 0]; }
    const n = fbm(u * 4, v * 4, seed, 4); const c = mixc(w, [40, 40, 40], 0.18 * n);
    return [c[0], c[1], c[2], 255, 0.7];
  });
}

// material library keyed by the Blender material name
const MATDEF = {
  granite_light: ['stone', '#c4beb0'], granite_warm: ['stone', '#beaf98'], granite_golden: ['stone', '#c8b694'],
  granite_white: ['stone', '#d6d2c8'], granite_grey: ['stone', '#a09e98'], granite_dark: ['stone', '#78746e'],
  rustic_light: ['rustic', '#bab4a6'], rustic_warm: ['rustic', '#b0a48e'], rustic_golden: ['rustic', '#beac8c'],
  rustic_white: ['rustic', '#ccc8be'], rustic_grey: ['rustic', '#96948e'], trim_light: ['stone', '#dedace'],
  stucco_cream: ['noise', '#ded2b6', 0.2], stucco_white: ['noise', '#e8e4da', 0.18], stucco_grey: ['noise', '#b0aea8', 0.2],
  stucco_ochre: ['noise', '#ceb084', 0.2], stucco_pink: ['noise', '#d2b4a5', 0.2],
  brick_red: ['brick', '#964230', '#803628', '#b9b4aa'], brick_red_banded: ['brick', '#9c4632', '#84382a', '#b9b4aa', [1.25, 0.32]],
  brick_brown: ['brick', '#78523a', '#684834', '#968c7d'], brick_grey: ['brick', '#70706c', '#5c5e5c', '#aaa8a0'],
  brick_grey_red: ['brick', '#6e6e6a', '#606060', '#aaa8a0', [1.6, 0.26], '#964432'], brick_cream: ['brick', '#c4b08c', '#b4a07e', '#c8c3b9'],
  roof_tile_red: ['rooftile', '#964632'], roof_tile_grey: ['rooftile', '#48484a'], roof_slate: ['rooftile', '#464a52'],
  glazed_tile_blue: ['glazed', '#285c6e'], glazed_tile_green: ['glazed', '#326946'], copper_patina: ['noise', '#5f9680', 0.35, 0.3, 0.2],
  roof_flat: ['noise', '#807e78', 0.3], concrete: ['noise', '#9e9c96', 0.25], concrete_dark: ['noise', '#6e6c68', 0.25],
  concrete_white: ['noise', '#d2d2cd', 0.15],
  window_hist_white: ['window', '#e8e4da', [2, 3]], window_hist_dark: ['window', '#282e2a', [2, 3]],
  window_hist_green: ['window', '#344c3c', [2, 4]], window_shop: ['window', '#1e1e20', [3, 1]],
  window_modern: ['window', '#aaacaf', [2, 1]], window_lane: ['window', '#6e3c28', [2, 2]],
  curtain_blue: ['curtain', '#3a566e', '#96999f', '#46484f'], curtain_green: ['curtain', '#3e5c56', '#96999f', '#46484f'],
  curtain_grey: ['curtain', '#464c52', '#b4b6b9', '#46484f'], curtain_silver: ['curtain', '#6e7882', '#c8cacd', '#5a5c60'],
  curtain_gold: ['curtain', '#786440', '#968259', '#6e5f46'],
  facade_tile_white: ['punched', '#d2cec4', '#283037'], facade_tile_beige: ['punched', '#c4b498', '#283037'],
  facade_tile_grey: ['punched', '#969694', '#283037'], facade_tile_pink: ['punched', '#c4a89c', '#283037'],
  facade_hist_dist: ['punched', '#b4aa96', '#283037', { bay: 3.8, ww: 1.5, wh: 2.4, floor: 4.0 }],
  asphalt: ['asphalt', '#343436'], asphalt_old: ['asphalt', '#403f3e'], paint_white: ['flat', '#ebebe6', 0.6],
  paint_yellow: ['flat', '#e6b428', 0.6], paving_sidewalk: ['tiles', '#96948e', '#88867f', 2.4, 0.6, 0.3],
  paving_plaza: ['tiles', '#b2aca0', '#a09a8e', 4.0, 1.0, 0.5], paving_deck: ['tiles', '#a8a092', '#989184', 3.2, 0.8, 0.4],
  paving_red: ['tiles', '#8c5c4c', '#7a5040', 0.8, 0.2, 0.1], curb_granite: ['tiles', '#afaca5', '#a5a29b', 4.0, 1.0, 0.3],
  grass: ['grass', '#4e7030'], grass_park: ['grass', '#46682c'], hedge: ['grass', '#325526'], soil: ['noise', '#46382a', 0.3],
  metal_dark: ['metal', '#242826', 0.3, 0.45], metal_black: ['metal', '#141416', 0.3, 0.4], metal_grey: ['metal', '#82868a', 0.6, 0.35],
  metal_green: ['metal', '#284637', 0.3, 0.45], steel_bridge: ['metal', '#808484', 0.35, 0.45], steel_stainless: ['metal', '#bec0c3', 1.0, 0.25],
  bronze: ['metal', '#6e5032', 1.0, 0.4], gold: ['metal', '#d2aa50', 1.0, 0.3], glass_clear: ['glass', '#c8d2d7'],
  glass_dark: ['metal', '#14181c', 0.2, 0.05], glass_globe: ['metal', '#96a0af', 0.7, 0.05], pearl_pink: ['metal', '#c84678', 0.55, 0.18],
  pearl_silver: ['metal', '#bec0c8', 0.8, 0.22], lamp_glass: ['emit', '#f5f0e1', 0.0], signal_housing: ['metal', '#191919', 0.2, 0.5],
  signal_red: ['emit', '#ff2814', 2.0], signal_green: ['emit', '#28ff78', 2.0], signal_off: ['metal', '#3c3c37', 0.1, 0.2],
  sign_blue: ['flat', '#14469f', 0.4], sign_white: ['flat', '#e6e6e6', 0.4], canopy_glass: ['glass', '#bec8cd'],
  flag_red: ['flat', '#c81419', 0.7], bench_wood: ['flat', '#785232', 0.7], riverbed: ['flat', '#28261e', 1],
  bank_granite: ['stone', '#9c9a94'], bank_concrete: ['noise', '#94928c', 0.25], bronze_red: ['metal', '#965238', 1.0, 0.32],
  sign_red: ['flat', '#961919', 0.4], sign_gold: ['metal', '#be9646', 0.8, 0.3], sign_black: ['flat', '#161618', 0.35],
  sign_green: ['flat', '#195a3c', 0.4], sign_cream: ['flat', '#dccdaa', 0.5], awning_red: ['flat', '#821e1c', 0.8],
  awning_green: ['flat', '#1e4632', 0.8], rubber: ['flat', '#191919', 0.9],
};

const matCache = new Map();
const texCache = new Map();
function makeMaterial(name) {
  const base = name.replace(/\.\d+$/, '').replace(/_v\d$/, '');
  const variant = +(name.match(/_v(\d)$/) || [0, 0])[1];
  const def = MATDEF[base];
  if (!def) return new THREE.MeshStandardMaterial({ color: 0xbbbbbb, roughness: 0.8 });
  const [kind] = def;
  const tkey = base;
  let m;
  const T = (fn, size) => {
    if (!texCache.has(tkey)) { const t = fn(); texCache.set(tkey, t); }
    const t = texCache.get(tkey);
    if (Array.isArray(t)) return t;
    if (size) t.repeat.set(1 / size, 1 / size);
    return t;
  };
  switch (kind) {
    case 'stone': case 'rustic': {
      const t = T(() => texStone(def[1], { rustic: kind === 'rustic', bw: kind === 'rustic' ? 1.4 : 1.1, bh: kind === 'rustic' ? 0.62 : 0.48, seed: base.length }), 2.4);
      const n = normalFrom(t, kind === 'rustic' ? 6 : 2.5); n.repeat.copy(t.repeat);
      m = new THREE.MeshStandardMaterial({ map: t, normalMap: n, roughness: 0.75 }); break;
    }
    case 'brick': {
      const t = T(() => texBrick(def[1], def[2], def[3], { band: def[4], bandColor: def[5] || '#ddd5c4' }), 2.5);
      const n = normalFrom(t, 3); n.repeat.copy(t.repeat);
      m = new THREE.MeshStandardMaterial({ map: t, normalMap: n, roughness: 0.85 }); break;
    }
    case 'noise': {
      const t = T(() => texNoise(def[1], { varr: def[2] ?? 0.25 }), 4);
      m = new THREE.MeshStandardMaterial({ map: t, roughness: 0.85, metalness: def[4] ?? 0 }); break;
    }
    case 'rooftile': case 'glazed': {
      const t = T(() => texRoofTiles(def[1], { glazed: kind === 'glazed' }), 2.0);
      const n = normalFrom(t, 4); n.repeat.copy(t.repeat);
      m = new THREE.MeshStandardMaterial({ map: t, normalMap: n, roughness: kind === 'glazed' ? 0.25 : 0.7 }); break;
    }
    case 'window': {
      const ts = T(() => texWindow(def[1], { panes: def[2] }));
      m = new THREE.MeshStandardMaterial({ map: ts[variant % 4], roughness: 0.12, metalness: 0.1, envMapIntensity: 1.2 }); break;
    }
    case 'curtain': {
      const t = T(() => texCurtain(def[1], def[2], def[3]));
      t.repeat.set(1 / 3.0, 1 / 7.6);
      m = new THREE.MeshStandardMaterial({ map: t, roughness: 0.12, metalness: 0.55, envMapIntensity: 1.3 }); break;
    }
    case 'punched': {
      const o = def[3] || {};
      const t = T(() => texPunched(def[1], def[2], o));
      t.repeat.set(1 / (o.bay || 3.2), 1 / (o.floor || 3.4));
      m = new THREE.MeshStandardMaterial({ map: t, roughness: 0.6, metalness: 0.05 }); break;
    }
    case 'asphalt': {
      const t = T(() => texNoise(def[1], { varr: 0.3, fine: 0.18, speck: 0.02, seed: 11 }), 5);
      m = new THREE.MeshStandardMaterial({ map: t, roughness: 0.92 }); break;
    }
    case 'tiles': {
      const t = T(() => texTiles(def[1], def[2], { size: def[3], tw: def[4], th: def[5] }), def[3]);
      const n = normalFrom(t, 2); n.repeat.copy(t.repeat);
      m = new THREE.MeshStandardMaterial({ map: t, normalMap: n, roughness: 0.75 }); break;
    }
    case 'grass': {
      const t = T(() => texNoise(def[1], { varr: 0.35, fine: 0.25, dark: [10, 20, 5], seed: 13 }), 3);
      m = new THREE.MeshStandardMaterial({ map: t, roughness: 0.95 }); break;
    }
    case 'metal': m = new THREE.MeshStandardMaterial({ color: def[1], metalness: def[2], roughness: def[3] }); break;
    case 'glass': m = new THREE.MeshStandardMaterial({ color: def[1], metalness: 0.1, roughness: 0.05, transparent: true, opacity: 0.35 }); break;
    case 'emit': m = new THREE.MeshStandardMaterial({ color: def[1], emissive: def[1], emissiveIntensity: def[2], roughness: 0.3 }); break;
    default: m = new THREE.MeshStandardMaterial({ color: def[1], roughness: def[2] ?? 0.6 });
  }
  m.name = name;
  return m;
}
function materialFor(name) {
  if (!matCache.has(name)) matCache.set(name, makeMaterial(name));
  return matCache.get(name);
}

// ---------------------------------------------------------------------------
// loading
// ---------------------------------------------------------------------------
async function fetchBuffer(url, onProgress) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  const total = +res.headers.get('content-length') || 0;
  const reader = res.body.getReader();
  const chunks = []; let got = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value); got += value.length; onProgress(got, total);
  }
  let buf = new Uint8Array(got); let o = 0;
  for (const c of chunks) { buf.set(c, o); o += c.length; }
  // gzip magic: decompress here unless the server already did (Content-Encoding: gzip)
  if (buf[0] === 0x1f && buf[1] === 0x8b) {
    const ds = new Response(new Blob([buf]).stream().pipeThrough(new DecompressionStream('gzip')));
    buf = new Uint8Array(await ds.arrayBuffer());
  }
  return buf.buffer;
}

// ---------------------------------------------------------------------------
// app
// ---------------------------------------------------------------------------
const canvas = $('view');
// "#low" (or a phone) = no shadows, lower resolution, no far context ring
const LOW = location.hash === '#low' || matchMedia('(pointer: coarse)').matches;
const renderer = new THREE.WebGLRenderer({ canvas, antialias: !LOW, powerPreference: 'high-performance' });
renderer.setPixelRatio(LOW ? Math.min(window.devicePixelRatio, 0.85) : Math.min(window.devicePixelRatio, 1.5));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.AgXToneMapping ?? THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.82;
renderer.shadowMap.enabled = !LOW;
renderer.shadowMap.type = THREE.PCFShadowMap;
MAX_ANISO = Math.min(8, renderer.capabilities.getMaxAnisotropy());

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(70, window.innerWidth / window.innerHeight, 0.15, 9000);
scene.fog = new THREE.FogExp2(0xc4c8c8, 0.00032);

// sky + sun
const sunDir = new THREE.Vector3();
{
  const el = THREE.MathUtils.degToRad(SUN.elevation), az = THREE.MathUtils.degToRad(SUN.azimuth);
  sunDir.set(Math.sin(az) * Math.cos(el), Math.sin(el), -Math.cos(az) * Math.cos(el)).normalize();
}
const sky = new Sky(); sky.scale.setScalar(20000);
sky.material.uniforms.turbidity.value = 4.5;
sky.material.uniforms.rayleigh.value = 1.6;
sky.material.uniforms.mieCoefficient.value = 0.005;
sky.material.uniforms.mieDirectionalG.value = 0.8;
sky.material.uniforms.sunPosition.value.copy(sunDir);
scene.add(sky);
const sun = new THREE.DirectionalLight(0xffd8aa, 3.0);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
Object.assign(sun.shadow.camera, { left: -120, right: 120, top: 120, bottom: -120, near: 1, far: 900 });
sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.6;
scene.add(sun, sun.target);
scene.add(new THREE.HemisphereLight(0xb4c8e0, 0x5e594c, 0.55));
{
  const pm = new THREE.PMREMGenerator(renderer);
  const env = new THREE.Scene(); const s2 = sky.clone(); env.add(s2);
  scene.environment = pm.fromScene(env, 0, 0.1, 30000).texture;
}

let world = null;
const walkMeshes = [];
const raycaster = new THREE.Raycaster(); raycaster.firstHitOnly = true;
const down = new THREE.Vector3(0, -1, 0);

const status = (t) => { $('status').textContent = t; };
const setProgress = (p) => { $('progress').firstElementChild.style.width = `${(p * 100).toFixed(1)}%`; $('progress').setAttribute('aria-valuenow', String(Math.round(p * 100))); };

async function load() {
  status('载入数据 world.json…');
  world = await (await fetch('assets/world.json')).json();
  const loader = new GLTFLoader();
  const done = new Map();
  let manifest = {};
  try { manifest = await (await fetch('assets/manifest.json')).json(); } catch { /* optional */ }
  const files = ASSETS.filter((k) => (!manifest.files || manifest.files[k]) && !(LOW && k === 'context'));
  const sizes = files.map((k) => (manifest.files?.[k]?.bytes) || 3e6);
  const totalBytes = sizes.reduce((a, b) => a + b, 0);
  let base = 0;
  for (let i = 0; i < files.length; i++) {
    const key = files[i];
    const url = `assets/${manifest.files?.[key]?.file || key + '.glb'}`;
    status(`下载模型 ${key}…`);
    let buf;
    try {
      buf = await fetchBuffer(url, (got) => setProgress((base + Math.min(got, sizes[i])) / totalBytes * 0.9));
    } catch (e) { console.warn('skip', key, e); base += sizes[i]; continue; }
    base += sizes[i];
    const gltf = await loader.parseAsync(buf, '');
    gltf.scene.traverse((o) => {
      if (!o.isMesh) return;
      const mats = Array.isArray(o.material) ? o.material : [o.material];
      const repl = mats.map((m) => materialFor(m.name || ''));
      o.material = Array.isArray(o.material) ? repl : repl[0];
      o.castShadow = key !== 'ground' && key !== 'context';
      o.receiveShadow = true;
      if (WALKABLE.has(key)) { o.geometry.computeBoundsTree(); walkMeshes.push(o); }
    });
    scene.add(gltf.scene);
    done.set(key, gltf.scene);
  }
  status('生成水面、树木、路灯与轮渡…');
  buildWater();
  buildTrees();
  buildLamps();
  buildFerry();
  buildMinimap();
  buildTeleports();
  setProgress(1);
  status('准备就绪。点击「进入外滩」，Esc 可随时暂停。');
  $('start').disabled = false;
}

// ---------------------------------------------------------------------------
// water
// ---------------------------------------------------------------------------
let waterNormal;
function buildWater() {
  const N = 256;
  waterNormal = (() => {
    const t = paint(N, N, (u, v) => {
      const h = fbm(u * 8, v * 8, 21, 8, 4) * 0.7 + fbm(u * 32, v * 32, 22, 32, 2) * 0.3;
      return [0, 0, 0, 255, h];
    }, false);
    const n = normalFrom(t, 5); n.repeat.set(1 / 18, 1 / 18); return n;
  })();
  // silt-laden Huangpu water: khaki brown, choppy from the constant boat traffic
  const mat = new THREE.MeshStandardMaterial({ color: 0x4a4534, roughness: 0.07, metalness: 0.0, normalMap: waterNormal,
    normalScale: new THREE.Vector2(0.85, 0.85), envMapIntensity: 1.0 });
  const z = world.levels.water;
  for (const p of world.water) {
    const sh = new THREE.Shape(p.ext.map(([x, y]) => new THREE.Vector2(x, y)));
    for (const h of p.holes || []) sh.holes.push(new THREE.Path(h.map(([x, y]) => new THREE.Vector2(x, y))));
    const g = new THREE.ShapeGeometry(sh);
    g.rotateX(-Math.PI / 2);
    // ShapeGeometry is in XY; after rotateX(-90) y -> -z, which matches Blender y -> three -z
    const uv = g.attributes.uv; for (let i = 0; i < uv.count; i++) uv.setXY(i, uv.getX(i), uv.getY(i));
    const m = new THREE.Mesh(g, mat); m.position.y = z; m.receiveShadow = true; scene.add(m);
  }
  // wide river beyond the detailed area (context ring has its own water)
  const bed = new THREE.Mesh(new THREE.PlaneGeometry(30000, 30000), new THREE.MeshStandardMaterial({ color: 0x4a4534, roughness: 0.1, normalMap: waterNormal }));
  bed.rotation.x = -Math.PI / 2; bed.position.y = z - 0.05; scene.add(bed);
}

// ---------------------------------------------------------------------------
// trees (instanced): trunk + clustered leaf blobs with an alpha-tested leaf texture
// ---------------------------------------------------------------------------
function leafTexture(c1, c2, seed) {
  const a = hex(c1), b = hex(c2);
  const t = paint(256, 256, (u, v, px, py) => {
    const n = fbm(u * 10, v * 10, seed, 10, 3);
    const cell = hash(Math.floor(u * 24), Math.floor(v * 24), seed);
    const alpha = n + cell * 0.35 > 0.62 ? 255 : 0;
    const c = mixc(a, b, cell);
    return [c[0], c[1], c[2], alpha];
  });
  return t;
}
function treeGeometry(kind) {
  const trunkH = { plane: 3.2, camphor: 2.4, ginkgo: 4 }[kind];
  const trunk = new THREE.CylinderGeometry(0.22, 0.32, trunkH + 1.5, 7); trunk.translate(0, (trunkH + 1.5) / 2 - 0.2, 0);
  const crowns = [];
  const R = { plane: 4.6, camphor: 4.4, ginkgo: 2.6 }[kind];
  const H = { plane: 14, camphor: 11, ginkgo: 13 }[kind];
  const n = kind === 'ginkgo' ? 5 : 7;
  for (let i = 0; i < n; i++) {
    const g = new THREE.IcosahedronGeometry(R * (0.55 + 0.25 * hash(i, 1, kind.length)), 1);
    const a = i / n * Math.PI * 2;
    const r = i === 0 ? 0 : R * 0.45;
    const y = kind === 'ginkgo' ? trunkH + (H - trunkH) * (0.2 + 0.65 * i / n) : trunkH + (H - trunkH) * (0.45 + 0.25 * hash(i, 3, 7));
    g.translate(Math.cos(a) * r, y, Math.sin(a) * r);
    crowns.push(g);
  }
  return { trunk, crown: mergeGeoms(crowns) };
}
function mergeGeoms(list) {
  let count = 0; for (const g of list) count += g.attributes.position.count;
  const pos = new Float32Array(count * 3), nor = new Float32Array(count * 3), uv = new Float32Array(count * 2);
  let o = 0;
  for (const g0 of list) {
    const g = g0.index ? g0.toNonIndexed() : g0;
    pos.set(g.attributes.position.array, o * 3); nor.set(g.attributes.normal.array, o * 3);
    if (g.attributes.uv) uv.set(g.attributes.uv.array, o * 2);
    o += g.attributes.position.count;
  }
  const out = new THREE.BufferGeometry();
  out.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  out.setAttribute('normal', new THREE.BufferAttribute(nor, 3));
  out.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
  return out;
}
function buildTrees() {
  const kinds = { plane: ['#4e6e2c', '#7a8c34'], camphor: ['#2f5226', '#58782e'], ginkgo: ['#7a8c30', '#a8a83a'] };
  const bark = { plane: 0x8e8e78, camphor: 0x463c32, ginkgo: 0x5a5246 };
  const byKind = {};
  for (const t of world.trees) (byKind[t[3]] ||= []).push(t);
  const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), p = new THREE.Vector3();
  for (const [kind, list] of Object.entries(byKind)) {
    const { trunk, crown } = treeGeometry(kind);
    const lt = leafTexture(kinds[kind][0], kinds[kind][1], kind.length * 7); lt.repeat.set(2, 2);
    const trunkM = new THREE.InstancedMesh(trunk, new THREE.MeshStandardMaterial({ color: bark[kind], roughness: 0.9 }), list.length);
    const crownM = new THREE.InstancedMesh(crown, new THREE.MeshStandardMaterial({ map: lt, alphaTest: 0.5, side: THREE.DoubleSide, roughness: 0.75 }), list.length);
    list.forEach((t, i) => {
      p.copy(B(t[0], t[1], t[2])); q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), t[5]); s.setScalar(t[4]);
      m4.compose(p, q, s); trunkM.setMatrixAt(i, m4); crownM.setMatrixAt(i, m4);
    });
    for (const m of [trunkM, crownM]) { m.castShadow = true; m.receiveShadow = true; scene.add(m); }
  }
}

// ---------------------------------------------------------------------------
// lamps & signals (instanced)
// ---------------------------------------------------------------------------
function buildLamps() {
  const pole = new THREE.CylinderGeometry(0.08, 0.14, 1, 8); pole.translate(0, 0.5, 0);
  const globe = new THREE.SphereGeometry(0.28, 12, 8);
  const types = { bund: 7.6, promenade: 4.3, street: 8.4 };
  const metal = new THREE.MeshStandardMaterial({ color: 0x242826, roughness: 0.45, metalness: 0.3 });
  const glass = new THREE.MeshStandardMaterial({ color: 0xf5f0e1, emissive: 0x332a1a, roughness: 0.3 });
  const poles = new THREE.InstancedMesh(pole, metal, world.lamps.length);
  const globes = new THREE.InstancedMesh(globe, glass, world.lamps.length);
  const m4 = new THREE.Matrix4();
  world.lamps.forEach((l, i) => {
    const h = types[l.type] || 7;
    m4.makeScale(1, h, 1).setPosition(B(l.pos[0], l.pos[1], l.z)); poles.setMatrixAt(i, m4);
    m4.makeTranslation(B(l.pos[0], l.pos[1], l.z + h + 0.2)); globes.setMatrixAt(i, m4);
  });
  poles.castShadow = true; scene.add(poles, globes);
  // signal poles with an arm over the lanes
  const sp = new THREE.CylinderGeometry(0.13, 0.16, 6.8, 8); sp.translate(0, 3.4, 0);
  const arm = new THREE.BoxGeometry(1, 0.14, 0.14); arm.translate(0.5, 6.25, 0);
  const head = new THREE.BoxGeometry(0.3, 1.0, 0.4); head.translate(0, 5.65, 0);
  const grey = new THREE.MeshStandardMaterial({ color: 0x82868a, metalness: 0.6, roughness: 0.35 });
  const black = new THREE.MeshStandardMaterial({ color: 0x151515, emissive: 0x200000, roughness: 0.5 });
  const n = world.signals.length;
  const P = new THREE.InstancedMesh(sp, grey, n), A = new THREE.InstancedMesh(arm, grey, n), H = new THREE.InstancedMesh(head, black, n * 2);
  const q = new THREE.Quaternion(), up = new THREE.Vector3(0, 1, 0);
  world.signals.forEach((s, i) => {
    const pos = B(s.pos[0], s.pos[1], s.z);
    // arm points to the left of travel: Blender heading h + 90deg; three yaw = angle in XZ plane
    const yaw = s.h + Math.PI / 2;
    q.setFromAxisAngle(up, yaw);
    m4.compose(pos, q, new THREE.Vector3(1, 1, 1)); P.setMatrixAt(i, m4);
    m4.compose(pos, q, new THREE.Vector3(s.arm, 1, 1)); A.setMatrixAt(i, m4);
    for (let k = 0; k < 2; k++) {
      const d = s.arm * (0.45 + 0.4 * k);
      const hp = pos.clone().add(new THREE.Vector3(Math.cos(yaw) * d, 0, -Math.sin(yaw) * d));
      m4.compose(hp, q, new THREE.Vector3(1, 1, 1)); H.setMatrixAt(i * 2 + k, m4);
    }
  });
  for (const m of [P, A, H]) { m.castShadow = true; scene.add(m); }
}

// ---------------------------------------------------------------------------
// ferry: 东金线 (Jinling Rd <-> Dongchang Rd), runs along the real route
// ---------------------------------------------------------------------------
const ferry = { group: null, path: null, len: 0, s: 0, dir: 1, phase: 'dock', timer: 12, speed: 0, aboard: false, local: new THREE.Vector3() };
const DOCK_TIME = 18, CRUISE = 13;
function buildFerry() {
  const route = world.ferry_routes.find((r) => r.name.includes('东金')) || world.ferry_routes[0];
  if (!route) return;
  const pts = route.pts.map(([x, y]) => B(x, y, world.levels.water));
  ferry.path = new THREE.CatmullRomCurve3(pts, false, 'centripetal', 0.2);
  ferry.len = ferry.path.getLength();
  const g = new THREE.Group();
  const white = new THREE.MeshStandardMaterial({ color: 0xe9e6dc, roughness: 0.6 });
  const hull = new THREE.MeshStandardMaterial({ color: 0x2c4a6e, roughness: 0.5 });
  const red = new THREE.MeshStandardMaterial({ color: 0x9c2a22, roughness: 0.6 });
  const deckM = new THREE.MeshStandardMaterial({ color: 0x6e6a60, roughness: 0.9 });
  const glass = new THREE.MeshStandardMaterial({ color: 0x223344, roughness: 0.1, metalness: 0.4 });
  // double-ended river ferry ~38 m x 10 m (x = along the route)
  const hullShape = new THREE.Shape();
  hullShape.moveTo(-19, -3.2); hullShape.lineTo(19, -3.2); hullShape.quadraticCurveTo(21.5, 0, 19, 3.2);
  hullShape.lineTo(-19, 3.2); hullShape.quadraticCurveTo(-21.5, 0, -19, -3.2);
  const hg = new THREE.ExtrudeGeometry(hullShape, { depth: 2.2, bevelEnabled: false }); hg.rotateX(-Math.PI / 2); hg.translate(0, -1.2, 0);
  hg.scale(1, 1, 1.55);
  const hm = new THREE.Mesh(hg, hull); g.add(hm);
  const deck = new THREE.Mesh(new THREE.BoxGeometry(40, 0.2, 9.6), deckM); deck.position.y = 1.0; g.add(deck);
  const band = new THREE.Mesh(new THREE.BoxGeometry(41, 0.35, 10), red); band.position.y = 0.85; g.add(band);
  const cabin = new THREE.Mesh(new THREE.BoxGeometry(16, 2.6, 6.2), white); cabin.position.y = 2.4; g.add(cabin);
  const win = new THREE.Mesh(new THREE.BoxGeometry(16.1, 0.9, 6.3), glass); win.position.y = 2.7; g.add(win);
  const top = new THREE.Mesh(new THREE.BoxGeometry(6, 2.0, 4.6), white); top.position.y = 4.7; g.add(top);
  const tw = new THREE.Mesh(new THREE.BoxGeometry(6.1, 0.7, 4.7), glass); tw.position.y = 5.0; g.add(tw);
  const funnel = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.6, 2.2, 10), red); funnel.position.set(0, 6.6, 0); g.add(funnel);
  const railM = new THREE.MeshStandardMaterial({ color: 0xdddddd, metalness: 0.5, roughness: 0.3 });
  for (const zz of [-4.75, 4.75]) { const r = new THREE.Mesh(new THREE.BoxGeometry(38, 0.06, 0.06), railM); r.position.set(0, 2.1, zz); g.add(r); }
  for (let k = -18; k <= 18; k += 2) for (const zz of [-4.75, 4.75]) {
    const p = new THREE.Mesh(new THREE.BoxGeometry(0.05, 1.1, 0.05), railM); p.position.set(k, 1.6, zz); g.add(p);
  }
  g.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; } });
  ferry.group = g; scene.add(g);
  ferry.deckY = 1.1;
  ferry.s = 0; ferry.dir = 1; ferry.phase = 'dock'; ferry.timer = 10;
  placeFerry();
}
function placeFerry() {
  const t = THREE.MathUtils.clamp(ferry.s / ferry.len, 0, 1);
  const p = ferry.path.getPointAt(t);
  const tan = ferry.path.getTangentAt(t);
  ferry.group.position.copy(p);
  ferry.group.rotation.set(0, Math.atan2(-tan.z, tan.x), 0);
  ferry.group.position.y += Math.sin(performance.now() * 0.0012) * 0.06;
}
function updateFerry(dt) {
  if (!ferry.group) return;
  if (ferry.phase === 'dock') {
    ferry.timer -= dt;
    if (ferry.timer <= 0) { ferry.phase = 'cruise'; ferry.speed = 0; }
  } else {
    const remain = ferry.dir > 0 ? ferry.len - ferry.s : ferry.s;
    const target = remain < 60 ? Math.max(1.2, CRUISE * remain / 60) : CRUISE;
    ferry.speed += THREE.MathUtils.clamp(target - ferry.speed, -3 * dt, 1.5 * dt);
    ferry.s += ferry.dir * ferry.speed * dt;
    if (ferry.s >= ferry.len || ferry.s <= 0) {
      ferry.s = THREE.MathUtils.clamp(ferry.s, 0, ferry.len);
      ferry.dir *= -1; ferry.phase = 'dock'; ferry.timer = DOCK_TIME;
    }
  }
  placeFerry();
}
function ferryDockedAt() {
  if (!ferry.group || ferry.phase !== 'dock') return null;
  return ferry.s <= 0.5 ? 'puxi' : (ferry.s >= ferry.len - 0.5 ? 'pudong' : null);
}
const landing = {};
function terminalPoint(which) {
  if (landing[which]) return landing[which];
  const t = which === 'puxi' ? 0 : 1;
  const p = ferry.path.getPointAt(t);
  const tan = ferry.path.getTangentAt(t).multiplyScalar(which === 'puxi' ? -1 : 1);
  // first solid, open spot inland from the pontoon (fan out if straight inland is blocked)
  for (const ang of [0, 0.35, -0.35, 0.7, -0.7, 1.1, -1.1]) {
    const d = tan.clone().applyAxisAngle(new THREE.Vector3(0, 1, 0), ang);
    for (let r = 12; r <= 90; r += 3) {
      const q = p.clone().addScaledVector(d, r);
      const g = groundAt(q, 40);
      if (g !== null && g > world.levels.water + 1.0 && !blockedByBuilding(q.x, -q.z, 1.0)) {
        q.y = g; landing[which] = q; return q;
      }
    }
  }
  landing[which] = p.clone().addScaledVector(tan, 30);
  return landing[which];
}

// ---------------------------------------------------------------------------
// collision helpers (building footprints, 2D)
// ---------------------------------------------------------------------------
const GRID = 25; const grid = new Map();
function indexFootprints() {
  world.buildings.forEach((b, i) => {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const [x, y] of b.e) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }
    b.bb = [x0, y0, x1, y1];
    for (let gx = Math.floor(x0 / GRID); gx <= Math.floor(x1 / GRID); gx++)
      for (let gy = Math.floor(y0 / GRID); gy <= Math.floor(y1 / GRID); gy++) {
        const k = gx * 100003 + gy; if (!grid.has(k)) grid.set(k, []); grid.get(k).push(i);
      }
  });
}
function pip(x, y, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi) inside = !inside;
  }
  return inside;
}
function blockedByBuilding(x, y, r = RADIUS) {
  const k = Math.floor(x / GRID) * 100003 + Math.floor(y / GRID);
  const ids = grid.get(k); if (!ids) return false;
  for (const i of ids) {
    const b = world.buildings[i];
    if (x < b.bb[0] - r || x > b.bb[2] + r || y < b.bb[1] - r || y > b.bb[3] + r) continue;
    if (pip(x, y, b.e) || pip(x + r, y, b.e) || pip(x - r, y, b.e) || pip(x, y + r, b.e) || pip(x, y - r, b.e)) return true;
  }
  return false;
}
function groundAt(pos, from) {
  raycaster.set(new THREE.Vector3(pos.x, from, pos.z), down);
  raycaster.far = 60;
  let best = null;
  for (const m of walkMeshes) {
    const hit = raycaster.intersectObject(m, false)[0];
    if (hit && (!best || hit.point.y > best)) best = hit.point.y;
  }
  return best;
}

// ---------------------------------------------------------------------------
// player
// ---------------------------------------------------------------------------
const player = { pos: new THREE.Vector3(), vy: 0, yaw: 0, pitch: 0, fly: false };
const keys = new Set();
let locked = false, running = false, touchMove = { x: 0, y: 0 };

function spawn(tp) {
  const p = B(tp.pos[0], tp.pos[1], tp.z ?? 0.2);
  player.pos.copy(p);
  const g = groundAt(p, p.y + 30); if (g !== null) player.pos.y = g;
  const look = B(tp.look[0], tp.look[1]);
  player.yaw = Math.atan2(-(look.x - p.x), -(look.z - p.z));
  player.pitch = 0.05; player.vy = 0;
  ferry.aboard = false;
}

function movePlayer(dt) {
  const f = new THREE.Vector3(-Math.sin(player.yaw), 0, -Math.cos(player.yaw));
  const r = new THREE.Vector3(Math.cos(player.yaw), 0, -Math.sin(player.yaw));
  const wish = new THREE.Vector3();
  if (keys.has('KeyW') || keys.has('ArrowUp')) wish.add(f);
  if (keys.has('KeyS') || keys.has('ArrowDown')) wish.sub(f);
  if (keys.has('KeyD') || keys.has('ArrowRight')) wish.add(r);
  if (keys.has('KeyA') || keys.has('ArrowLeft')) wish.sub(r);
  wish.addScaledVector(f, -touchMove.y).addScaledVector(r, touchMove.x);
  if (wish.lengthSq() > 1) wish.normalize();
  const speed = player.fly ? FLY * (keys.has('ShiftLeft') || keys.has('ShiftRight') ? 3 : 1)
    : (keys.has('ShiftLeft') || keys.has('ShiftRight') ? RUN : WALK);
  if (player.fly) {
    const lookDir = new THREE.Vector3(-Math.sin(player.yaw) * Math.cos(player.pitch), Math.sin(player.pitch), -Math.cos(player.yaw) * Math.cos(player.pitch));
    const m = new THREE.Vector3();
    if (keys.has('KeyW') || keys.has('ArrowUp')) m.add(lookDir);
    if (keys.has('KeyS') || keys.has('ArrowDown')) m.sub(lookDir);
    if (keys.has('KeyD') || keys.has('ArrowRight')) m.add(r);
    if (keys.has('KeyA') || keys.has('ArrowLeft')) m.sub(r);
    if (keys.has('Space')) m.y += 1;
    if (keys.has('KeyC')) m.y -= 1;
    player.pos.addScaledVector(m, speed * dt);
    player.pos.y = Math.max(player.pos.y, -1);
    return;
  }
  if (ferry.aboard) {
    // walk on the ferry deck in its local frame
    ferry.local.addScaledVector(toFerryLocalDir(wish), speed * dt);
    ferry.local.x = THREE.MathUtils.clamp(ferry.local.x, -18.5, 18.5);
    ferry.local.z = THREE.MathUtils.clamp(ferry.local.z, -4.4, 4.4);
    if (Math.abs(ferry.local.x) < 8.3 && Math.abs(ferry.local.z) < 3.4) ferry.local.z = Math.sign(ferry.local.z || 1) * 3.4;
    ferry.local.y = ferry.deckY;
    player.pos.copy(ferry.local).applyMatrix4(ferry.group.matrixWorld);
    return;
  }
  const step = wish.multiplyScalar(speed * dt);
  for (const axis of ['x', 'z']) {
    if (!step[axis]) continue;
    const np = player.pos.clone(); np[axis] += step[axis];
    const bx = np.x, by = -np.z;
    if (blockedByBuilding(bx, by)) continue;
    const g = groundAt(np, player.pos.y + STEP + 0.3);
    if (g === null || g < world.levels.water + 0.3) continue;      // river / out of map
    if (g - player.pos.y > STEP) continue;                          // wall, parapet, kerb too high
    player.pos[axis] = np[axis];
  }
  const g = groundAt(player.pos, player.pos.y + STEP + 0.3);
  if (g !== null) {
    if (player.pos.y > g + 0.02) { player.vy -= 9.8 * dt; player.pos.y = Math.max(g, player.pos.y + player.vy * dt); }
    else { player.pos.y = g; player.vy = 0; }
  }
}
const _q = new THREE.Quaternion();
function toFerryLocalDir(v) {
  _q.copy(ferry.group.quaternion).invert();
  return v.clone().applyQuaternion(_q);
}

// ---------------------------------------------------------------------------
// HUD
// ---------------------------------------------------------------------------
let mapBase = null; const MAP = { x0: -700, y0: -1100, size: 2600 };
function buildMinimap() {
  const c = document.createElement('canvas'); c.width = c.height = 840;
  const ctx = c.getContext('2d');
  const S = c.width / MAP.size;
  const P = (x, y) => [(x - MAP.x0) * S, c.height - (y - MAP.y0) * S];
  ctx.fillStyle = '#2a2e2a'; ctx.fillRect(0, 0, c.width, c.height);
  ctx.fillStyle = '#3d5560';
  for (const w of world.water) { ctx.beginPath(); w.ext.forEach(([x, y], i) => { const [px, py] = P(x, y); i ? ctx.lineTo(px, py) : ctx.moveTo(px, py); }); ctx.closePath(); ctx.fill(); }
  ctx.strokeStyle = '#6e6a60';
  for (const r of world.roads) { ctx.lineWidth = Math.max(1, r.w * S); ctx.beginPath(); r.p.forEach(([x, y], i) => { const [px, py] = P(x, y); i ? ctx.lineTo(px, py) : ctx.moveTo(px, py); }); ctx.stroke(); }
  for (const b of world.buildings) {
    ctx.fillStyle = b.lm ? '#d8b46a' : '#8c877c';
    ctx.beginPath(); b.e.forEach(([x, y], i) => { const [px, py] = P(x, y); i ? ctx.lineTo(px, py) : ctx.moveTo(px, py); }); ctx.closePath(); ctx.fill();
  }
  if (ferry.path) {
    ctx.setLineDash([6, 6]); ctx.strokeStyle = '#6fb59a'; ctx.lineWidth = 2; ctx.beginPath();
    world.ferry_routes[0].pts.forEach(([x, y], i) => { const [px, py] = P(x, y); i ? ctx.lineTo(px, py) : ctx.moveTo(px, py); }); ctx.stroke(); ctx.setLineDash([]);
  }
  mapBase = c;
  $('map').addEventListener('click', () => $('map').classList.toggle('big'));
}
function drawMinimap() {
  const c = $('map-c'); const ctx = c.getContext('2d');
  const W = c.width; const scale = $('map').classList.contains('big') ? 1.0 : 2.4;
  const S = mapBase.width / MAP.size;
  const px = (player.pos.x - MAP.x0) * S, py = mapBase.height - ((-player.pos.z) - MAP.y0) * S;
  ctx.save(); ctx.clearRect(0, 0, W, W);
  ctx.translate(W / 2, W / 2); ctx.scale(scale * W / mapBase.width * 2, scale * W / mapBase.width * 2);
  ctx.translate(-px, -py);
  ctx.drawImage(mapBase, 0, 0);
  if (ferry.group) {
    const fx = (ferry.group.position.x - MAP.x0) * S, fy = mapBase.height - ((-ferry.group.position.z) - MAP.y0) * S;
    ctx.fillStyle = '#6fb59a'; ctx.beginPath(); ctx.arc(fx, fy, 6, 0, Math.PI * 2); ctx.fill();
  }
  ctx.restore();
  ctx.save(); ctx.translate(W / 2, W / 2); ctx.rotate(-player.yaw);
  ctx.fillStyle = '#f3ede1'; ctx.beginPath(); ctx.moveTo(0, -14); ctx.lineTo(9, 10); ctx.lineTo(0, 5); ctx.lineTo(-9, 10); ctx.closePath(); ctx.fill();
  ctx.restore();
}
function buildTeleports() {
  const box = $('tp');
  for (const t of world.teleports) {
    const b = document.createElement('button'); b.type = 'button'; b.textContent = t.name;
    b.addEventListener('click', () => { spawn(t); box.hidden = true; requestLock(); });
    box.appendChild(b);
  }
  indexFootprints();
}
function updateHud() {
  // nearest landmark
  const bx = player.pos.x, by = -player.pos.z;
  let best = null, bd = 90 * 90;
  for (const l of world.labels) { const d = (l.pos[0] - bx) ** 2 + (l.pos[1] - by) ** 2; if (d < bd) { bd = d; best = l; } }
  if (best) {
    $('place-name').textContent = (best.no && best.no !== '-' ? `外滩${best.no}号 · ` : '') + best.zh;
    $('place-meta').textContent = `${best.en} · ${best.year}${best.h ? ` · 高约 ${best.h} m` : ''}`;
  } else if (ferry.aboard) { $('place-name').textContent = '黄浦江上 · 东金线轮渡'; $('place-meta').textContent = '金陵东路渡口 ⇄ 东昌路渡口'; }
  else { $('place-name').textContent = by > 650 ? '苏州河北岸 · 虹口' : (bx > 250 ? '浦东 · 陆家嘴' : '外滩 · 中山东一路'); $('place-meta').textContent = ''; }
  // ferry status
  const st = $('ferry-state');
  if (!ferry.group) st.textContent = '—';
  else if (ferry.phase === 'dock') st.innerHTML = `停靠${ferryDockedAt() === 'puxi' ? '浦西 金陵东路' : '浦东 东昌路'}，<b>${Math.ceil(ferry.timer)} 秒</b>后开船`;
  else st.innerHTML = `航行中 → ${ferry.dir > 0 ? '浦东 东昌路' : '浦西 金陵东路'}`;
  // boarding prompt
  const prompt = $('prompt'); const be = $('btn-e');
  const docked = ferryDockedAt();
  let text = '';
  if (ferry.aboard && docked) text = `按 E 下船（${docked === 'puxi' ? '金陵东路渡口' : '东昌路渡口'}）`;
  else if (!ferry.aboard && docked) {
    const tp = terminalPoint(docked);
    if (tp.distanceTo(player.pos) < 45) text = '按 E 登上东金线轮渡';
  } else if (!ferry.aboard && ferry.path) {
    const near = ['puxi', 'pudong'].some((w) => terminalPoint(w).distanceTo(player.pos) < 45);
    if (near) text = '轮渡即将靠岸，请稍候…';
  }
  prompt.hidden = !text; prompt.textContent = text;
  be.hidden = !text || text.includes('稍候'); be.textContent = ferry.aboard ? '下船 E' : '上船 E';
}
function interact() {
  const docked = ferryDockedAt();
  if (!docked) return;
  if (ferry.aboard) {
    ferry.aboard = false;
    const tp = terminalPoint(docked);
    player.pos.copy(tp); const g = groundAt(tp, tp.y + 30); if (g !== null) player.pos.y = g;
  } else if (terminalPoint(docked).distanceTo(player.pos) < 45) {
    ferry.aboard = true; ferry.local.set(-12, ferry.deckY, 3.6);
  }
}

// ---------------------------------------------------------------------------
// input
// ---------------------------------------------------------------------------
function requestLock() {
  if (matchMedia('(pointer: coarse)').matches) return;
  try { const p = canvas.requestPointerLock(); if (p && p.catch) p.catch(() => {}); } catch { /* optional */ }
}
let lockedAt = 0;
document.addEventListener('pointerlockchange', () => {
  locked = document.pointerLockElement === canvas;
  if (locked) lockedAt = performance.now();
  if (!locked && running && $('tp').hidden && !matchMedia('(pointer: coarse)').matches) showPause();
});
function showPause() { $('intro').hidden = false; $('start').textContent = '继续漫游'; $('hud').hidden = true; running = false; }
document.addEventListener('mousemove', (e) => {
  if (!locked || performance.now() - lockedAt < 250) return;
  player.yaw -= e.movementX * 0.0022; player.pitch -= e.movementY * 0.0022;
  player.pitch = THREE.MathUtils.clamp(player.pitch, -1.45, 1.45);
});
window.addEventListener('keydown', (e) => {
  keys.add(e.code);
  if (!running) return;
  if (e.code === 'KeyE') interact();
  if (e.code === 'KeyT') { const tp = $('tp'); tp.hidden = !tp.hidden; if (!tp.hidden) document.exitPointerLock?.(); else requestLock(); }
  if (e.code === 'KeyM') $('map').classList.toggle('big');
  if (e.code === 'KeyF') { player.fly = !player.fly; if (!player.fly) player.vy = 0; }
});
window.addEventListener('keyup', (e) => keys.delete(e.code));
canvas.addEventListener('click', () => { if (running && !locked) requestLock(); });
$('btn-tp').addEventListener('click', () => { const tp = $('tp'); tp.hidden = !tp.hidden; });
$('btn-e').addEventListener('click', () => interact());
$('start').addEventListener('click', () => {
  $('intro').hidden = true; $('hud').hidden = false; running = true;
  if (!player.started) { spawn(world.teleports[0]); player.started = true; }
  requestLock();
});
// touch: left half = joystick, right half = look
{
  const touch = $('touch'); const stick = $('stick'); let moveId = null, lookId = null, sx = 0, sy = 0, lx = 0, ly = 0;
  touch.addEventListener('pointerdown', (e) => {
    if (e.clientX < window.innerWidth / 2 && moveId === null) { moveId = e.pointerId; sx = e.clientX; sy = e.clientY; stick.style.display = 'block'; stick.style.left = `${sx - 60}px`; stick.style.top = `${sy - 60}px`; }
    else if (lookId === null) { lookId = e.pointerId; lx = e.clientX; ly = e.clientY; }
    touch.setPointerCapture(e.pointerId);
  });
  touch.addEventListener('pointermove', (e) => {
    if (e.pointerId === moveId) {
      const dx = THREE.MathUtils.clamp((e.clientX - sx) / 50, -1, 1), dy = THREE.MathUtils.clamp((e.clientY - sy) / 50, -1, 1);
      touchMove = { x: dx, y: dy }; stick.firstElementChild.style.transform = `translate(${dx * 30}px, ${dy * 30}px)`;
    } else if (e.pointerId === lookId) {
      player.yaw -= (e.clientX - lx) * 0.005; player.pitch -= (e.clientY - ly) * 0.005; lx = e.clientX; ly = e.clientY;
      player.pitch = THREE.MathUtils.clamp(player.pitch, -1.45, 1.45);
    }
  });
  const end = (e) => {
    if (e.pointerId === moveId) { moveId = null; touchMove = { x: 0, y: 0 }; stick.style.display = 'none'; stick.firstElementChild.style.transform = ''; }
    if (e.pointerId === lookId) lookId = null;
  };
  touch.addEventListener('pointerup', end); touch.addEventListener('pointercancel', end);
}
window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight; camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

// ---------------------------------------------------------------------------
// loop
// ---------------------------------------------------------------------------
let lastT = performance.now(), hudT = 0;
const TIME_SCALE = location.hash === '#fastferry' ? 25 : 1;   // debug: speed up the ferry
function frame() {
  const now = performance.now();
  const dt = Math.min((now - lastT) / 1000, 0.05); lastT = now;
  if (world) {
    updateFerry(ferry.phase === 'cruise' ? dt * TIME_SCALE : dt);
    if (running) movePlayer(dt);
    camera.position.copy(player.pos); camera.position.y += player.fly ? 0 : EYE;
    if (ferry.aboard && ferry.group) {
      // keep looking where we look while the ferry turns
    }
    camera.rotation.set(player.pitch, player.yaw, 0, 'YXZ');
    sun.position.copy(camera.position).addScaledVector(sunDir, 400);
    sun.target.position.copy(camera.position);
    if (waterNormal) waterNormal.offset.set(performance.now() * 0.000006, performance.now() * 0.000004);
    hudT -= dt;
    if (running && hudT <= 0) { hudT = 0.25; updateHud(); }
    if (running && mapBase) drawMinimap();
  }
  renderer.render(scene, camera);
  requestAnimationFrame(frame);
}
// preview while loading: hover above the river looking at the Bund
camera.position.set(260, 60, 120); camera.lookAt(-150, 20, 0);
frame();
load().catch((e) => { console.error(e); status(`载入失败：${e.message}。请刷新重试。`); });
