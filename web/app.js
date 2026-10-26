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

const ASSETS = ['ground', 'bridges', 'landmarks', 'buildings_core', 'buildings_back', 'lujiazui', 'furniture', 'context'];
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
  // slim frames and dark rooms: from the street, daytime windows read dark
  const f = hex(frame); const N = 256;
  return [0, 1, 2, 3].map((variant) => paint(N, N, (u, v) => {
    const fw = 0.04;
    let fr = u < fw || u > 1 - fw || v < fw * 0.8 || v > 1 - fw * 0.8;
    if (panes[0] > 1) { const mu = (u * panes[0]) % 1; fr = fr || mu < 0.016 * panes[0] || mu > 1 - 0.016 * panes[0]; }
    if (panes[1] > 1) { const mv = (v * panes[1]) % 1; fr = fr || mv < 0.012 * panes[1] || mv > 1 - 0.012 * panes[1]; }
    if (fr) return [f[0], f[1], f[2], 255, 1];
    let c = [20, 22, 24];
    const sky = mixc([60, 72, 86], [120, 134, 150], v);           // faint sky reflection
    if (variant === 1) c = v > 0.35 ? [112, 98, 78] : [26, 26, 26];
    if (variant === 2) c = (v * 30) % 1 < 0.5 ? [120, 118, 110] : [92, 90, 84];
    if (variant === 3) c = [92, 86, 70];
    c = mixc(c, sky, 0.12);
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

function texLeafy(base, { seed = 15 } = {}) {
  // clipped box and privet: small overlapping leaves, dark gaps, sunlit tips
  const c0 = hex(base); const N = 256;
  return paint(N, N, (u, v) => {
    const n = fbm(u * 16, v * 16, seed, 16, 3), m = fbm(u * 48, v * 48, seed + 7, 48, 2);
    const h = n * 0.6 + m * 0.4;
    const cell = hash(Math.floor(u * 40), Math.floor(v * 40), seed);
    let c = mixc(c0, [8, 14, 6], Math.max(0, 0.55 - h) * 1.6);
    c = mixc(c, [150, 160, 90], Math.max(0, h - 0.6) * 0.9 + cell * 0.05);
    return [c[0], c[1], c[2], 255, h];
  });
}

// material library keyed by the Blender material name
const MATDEF = {
  // weathered stone and render, matching the Blender palette (multiplied by the baked per-building colour)
  granite_light: ['stone', '#b8b0a0'], granite_warm: ['stone', '#b4a38a'], granite_golden: ['stone', '#bca886'],
  granite_white: ['stone', '#c8c3b8'], granite_grey: ['stone', '#96938c'], granite_dark: ['stone', '#78746e'],
  rustic_light: ['rustic', '#aca596'], rustic_warm: ['rustic', '#a69882'], rustic_golden: ['rustic', '#b2a080'],
  rustic_white: ['rustic', '#beb9ae'], rustic_grey: ['rustic', '#96948e'], trim_light: ['stone', '#d0cabc'],
  stucco_cream: ['noise', '#d0c2a4', 0.2], stucco_white: ['noise', '#d6d1c5', 0.18], stucco_grey: ['noise', '#b0aea8', 0.2],
  stucco_ochre: ['noise', '#ceb084', 0.2], stucco_pink: ['noise', '#d2b4a5', 0.2],
  brick_red: ['brick', '#964230', '#803628', '#b9b4aa'], brick_red_banded: ['brick', '#9c4632', '#84382a', '#b9b4aa', [1.25, 0.32]],
  brick_brown: ['brick', '#78523a', '#684834', '#968c7d'], brick_grey: ['brick', '#70706c', '#5c5e5c', '#aaa8a0'],
  brick_grey_red: ['brick', '#6e6e6a', '#606060', '#aaa8a0', [1.6, 0.26], '#964432'], brick_cream: ['brick', '#c4b08c', '#b4a07e', '#c8c3b9'],
  roof_tile_red: ['rooftile', '#964632'], roof_tile_grey: ['rooftile', '#48484a'], roof_slate: ['rooftile', '#464a52'],
  glazed_tile_blue: ['glazed', '#285c6e'], glazed_tile_green: ['glazed', '#326946'], copper_patina: ['noise', '#5f9680', 0.35, 0.3, 0.2],
  roof_flat: ['noise', '#807e78', 0.3], concrete: ['noise', '#9e9c96', 0.25], concrete_dark: ['noise', '#6e6c68', 0.25],
  concrete_white: ['noise', '#c2c1ba', 0.15],
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
  paving_plaza: ['tiles', '#a8a296', '#979185', 4.0, 1.0, 0.5], paving_deck: ['tiles', '#9e968a', '#8f897c', 3.2, 0.8, 0.4],
  paving_red: ['tiles', '#8c5c4c', '#7a5040', 0.8, 0.2, 0.1], curb_granite: ['tiles', '#afaca5', '#a5a29b', 4.0, 1.0, 0.3],
  grass: ['grass', '#4e7030'], grass_park: ['grass', '#46682c'], hedge: ['leafy', '#3c5e2a'], soil: ['noise', '#46382a', 0.3],
  lawn_base: ['grass', '#486a2c'], hedge_inner: ['leafy', '#2c4422'],
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
  flower_yellow: ['flowers', '#e2b21e', '#4a6a2a'], flower_white: ['flowers', '#e8e4d6', '#4a6a2a'],
  flower_purple: ['flowers', '#962e78', '#4a6a2a'], flower_pink: ['flowers', '#de78a0', '#4a6a2a'],
  flower_orange: ['flowers', '#e87e16', '#4a6a2a'], flower_red: ['flowers', '#c41c1a', '#4a6a2a'],
  leaf_flowerbed: ['grass', '#38582a'], bin_blue: ['flat', '#1e50a0', 0.45], bin_black: ['flat', '#222224', 0.45],
  bin_brown: ['flat', '#6e4226', 0.5], bin_red: ['flat', '#b01e1e', 0.45], post_green: ['metal', '#00683e', 0.2, 0.4],
  hydrant_red: ['metal', '#b01a16', 0.2, 0.45], cabinet_grey: ['metal', '#b0b2ac', 0.3, 0.5], sign_brown: ['flat', '#643c26', 0.5],
  far_city: ['noise', '#6e6a64', 0.3],
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
      m = reflective(new THREE.MeshStandardMaterial({ map: ts[variant % 4], roughness: 0.12, metalness: 0.1 }), 0.45); break;
    }
    case 'curtain': {
      const t = T(() => texCurtain(def[1], def[2], def[3]));
      t.repeat.set(1 / 3.0, 1 / 7.6);
      m = reflective(new THREE.MeshStandardMaterial({ map: t, roughness: 0.12, metalness: 0.55 }), 0.8); break;
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
    case 'flowers': {
      const t = T(() => paint(128, 128, (u, v) => {
        const n = fbm(u * 24, v * 24, 31, 24, 3);
        const c = n > 0.47 ? hex(def[1]) : mixc(hex(def[2]), hex(def[1]), Math.max(0, n - 0.3));
        return [c[0], c[1], c[2], 255, n];
      }), 0.6);
      const n = normalFrom(t, 4); n.repeat.copy(t.repeat);
      m = new THREE.MeshStandardMaterial({ map: t, normalMap: n, roughness: 0.8 }); break;
    }
    case 'leafy': {
      const t = T(() => texLeafy(def[1]), 1.2);
      const n = normalFrom(t, 5); n.repeat.copy(t.repeat);
      m = new THREE.MeshStandardMaterial({ map: t, normalMap: n, roughness: 0.8 }); break;
    }
    case 'grass': {
      const t = T(() => texNoise(def[1], { varr: 0.35, fine: 0.25, dark: [10, 20, 5], seed: 13 }), 3);
      m = new THREE.MeshStandardMaterial({ map: t, roughness: 0.95 }); break;
    }
    // reflections show only the sky, not the streets around: keep them modest
    case 'metal': m = reflective(new THREE.MeshStandardMaterial({ color: def[1], metalness: def[2], roughness: def[3] }), 0.6); break;
    case 'glass': m = reflective(new THREE.MeshStandardMaterial({ color: def[1], metalness: 0.1, roughness: 0.05, transparent: true, opacity: 0.35 }), 0.8); break;
    case 'emit': m = new THREE.MeshStandardMaterial({ color: def[1], emissive: def[1], emissiveIntensity: def[2], roughness: 0.3 }); break;
    default: m = new THREE.MeshStandardMaterial({ color: def[1], roughness: def[2] ?? 0.6 });
  }
  m.name = name;
  return m;
}
// vc: the mesh carries per-building colours (vertex colour 'Col', baked by export_web.py)
function materialFor(name, vc = false) {
  const key = vc ? name + '|vc' : name;
  if (!matCache.has(key)) {
    let m = makeMaterial(name);
    if (vc) { m = m.clone(); m.vertexColors = true; }
    matCache.set(key, m);
  }
  return matCache.get(key);
}
// the surrounding city is kilometres away and half hidden by haze: Lambert shading
// with the same colour texture, no normal maps, no shadows
const cheapCache = new Map();
function cheapMaterialFor(name, vc = false) {
  const key = vc ? name + '|vc' : name;
  if (!cheapCache.has(key)) {
    const m = materialFor(name);
    const c = new THREE.MeshLambertMaterial({ map: m.map || null, color: m.map ? 0xffffff : m.color, vertexColors: vc });
    c.name = name + '_far';
    cheapCache.set(key, c);
  }
  return cheapCache.get(key);
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
  const buf = new Uint8Array(got); let o = 0;
  for (const c of chunks) { buf.set(c, o); o += c.length; }
  return gunzip(buf);
}
// gzip magic: decompress here unless the server already did (Content-Encoding: gzip)
async function gunzip(buf) {
  if (buf[0] !== 0x1f || buf[1] !== 0x8b) return buf.buffer;
  const ds = new Response(new Blob([buf]).stream().pipeThrough(new DecompressionStream('gzip')));
  return ds.arrayBuffer();
}
// hosts that serve no binary files: the manifest lists the model as base64 text parts
async function fetchParts(urls, onProgress) {
  const texts = []; let got = 0;
  for (const url of urls) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`${url}: ${res.status}`);
    const t = await res.text(); texts.push(t); got += t.length; onProgress(got);
  }
  const bin = atob(texts.join('').replace(/\s+/g, ''));
  const buf = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
  return gunzip(buf);
}

// ---------------------------------------------------------------------------
// app
// ---------------------------------------------------------------------------
const canvas = $('view');
// "#low" (or a phone) = no shadows, lower resolution, no far context ring; "#stats" = frame stats
const LOW = location.hash === '#low' || matchMedia('(pointer: coarse)').matches;
const STATS = location.hash === '#stats';
// MSAA is costly on high-DPI screens, where the extra pixels already smooth edges
const renderer = new THREE.WebGLRenderer({ canvas, antialias: !LOW && window.devicePixelRatio <= 1.25,
  powerPreference: 'high-performance' });
// adaptive resolution: the pixel ratio moves between DPR_MIN and DPR_MAX to hold the frame rate
const DPR_MAX = LOW ? Math.min(window.devicePixelRatio, 0.85) : Math.min(window.devicePixelRatio, 1.5);
const DPR_MIN = LOW ? 0.5 : 0.6;
let dpr = DPR_MAX;
renderer.setPixelRatio(dpr);
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.AgXToneMapping ?? THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.8;
// AgX with a look like the renders' "Medium High Contrast": three.js ships AgX
// without looks, which leaves sunlit stone milky and flat. As in Blender's OCIO
// config the contrast pivots on middle grey in AgX's log encoding, before the
// sigmoid; a little saturation goes on after it.
const LOOK = { contrast: 1.3, saturation: 0.95 };
{
  const src = THREE.ShaderChunk.tonemapping_pars_fragment;
  const i0 = src.indexOf('vec3 AgXToneMapping('), i1 = src.indexOf('vec3 NeutralToneMapping(');
  const sig = 'color = agxDefaultContrastApprox( color );';
  const custom = 'vec3 CustomToneMapping( vec3 color ) { return color; }';
  if (i0 >= 0 && i1 > i0 && src.slice(i0, i1).includes(sig) && src.includes(custom)) {
    const grey = ((Math.log2(0.18) + 12.47393) / (4.026069 + 12.47393)).toFixed(4);   // 0.18 in AgX log
    const agx = src.slice(i0, i1).replace('vec3 AgXToneMapping(', 'vec3 AgXLookToneMapping(').replace(sig,
      `color = clamp( ( color - ${grey} ) * ${LOOK.contrast.toFixed(3)} + ${grey}, 0.0, 1.0 );\n\t${sig}\n` +
      `\tcolor = mix( vec3( dot( color, vec3( 0.2126, 0.7152, 0.0722 ) ) ), color, ${LOOK.saturation.toFixed(3)} );`);
    THREE.ShaderChunk.tonemapping_pars_fragment = src.replace(custom,
      `${agx}vec3 CustomToneMapping( vec3 color ) { return AgXLookToneMapping( color ); }`);
    renderer.toneMapping = THREE.CustomToneMapping;
  }
}
renderer.shadowMap.enabled = !LOW;
renderer.shadowMap.type = THREE.PCFShadowMap;
renderer.shadowMap.autoUpdate = false;          // re-rendered only when the player has moved (see frame)
MAX_ANISO = Math.min(8, renderer.capabilities.getMaxAnisotropy());

const scene = new THREE.Scene();
// the fog hides everything beyond ~6 km, so a nearer far plane costs nothing visible
const camera = new THREE.PerspectiveCamera(70, window.innerWidth / window.innerHeight, 0.15, 6500);
scene.fog = new THREE.FogExp2(0xc4c8c8, 0.0004);

// sky + sun
const sunDir = new THREE.Vector3();
{
  const el = THREE.MathUtils.degToRad(SUN.elevation), az = THREE.MathUtils.degToRad(SUN.azimuth);
  sunDir.set(Math.sin(az) * Math.cos(el), Math.sin(el), -Math.cos(az) * Math.cos(el)).normalize();
}
const sky = new Sky(); sky.scale.setScalar(20000);
sky.material.uniforms.turbidity.value = 7;           // Shanghai's hazy blue, not an alpine one
sky.material.uniforms.rayleigh.value = 1.3;
sky.material.uniforms.mieCoefficient.value = 0.0025;
sky.material.uniforms.mieDirectionalG.value = 0.75;
sky.material.uniforms.sunPosition.value.copy(sunDir);
if (sky.material.uniforms.cloudCoverage) {        // fair weather: small, thin clouds as in the renders
  Object.assign(sky.material.uniforms.cloudCoverage, { value: 0.2 });
  Object.assign(sky.material.uniforms.cloudScale, { value: 0.0004 });
  Object.assign(sky.material.uniforms.cloudDensity, { value: 0.25 });
}
// Light as in the Blender scene: a strong, warm, low sun lamp is the key light and
// the sky (strength 0.05 there) only a cool fill
// (its colour is the Blender lamp's, which is scene-linear: as an sRGB hex it came out twice as orange)
const sun = new THREE.DirectionalLight(new THREE.Color().setRGB(1.0, 0.8, 0.6, THREE.LinearSRGBColorSpace), 3.5);
sun.castShadow = true;
// One shadow map over +-110 m around the player: 4096 texels (5.4 cm) where the GPU
// takes big textures, else 2048. Its centre snaps to whole texels in light space (see
// updateShadows), so re-centring it as the player walks leaves every shadow edge in place.
// Small biases: shadows start at the foot of what casts them, nothing seems to hover.
const SHADOW = { half: 110, size: renderer.capabilities.maxTextureSize >= 8192 ? 4096 : 2048 };
sun.shadow.mapSize.set(SHADOW.size, SHADOW.size);
Object.assign(sun.shadow.camera, { left: -SHADOW.half, right: SHADOW.half, top: SHADOW.half, bottom: -SHADOW.half, near: 1, far: 900 });
sun.shadow.bias = -0.00006; sun.shadow.normalBias = 0.1;
// the shadow camera's axes (Matrix4.lookAt from the sun towards its target, up = +y)
const shadowX = new THREE.Vector3().crossVectors(new THREE.Vector3(0, 1, 0), sunDir).normalize();
const shadowY = new THREE.Vector3().crossVectors(sunDir, shadowX);
scene.add(sun, sun.target);
const hemi = new THREE.HemisphereLight(0xb4c8e0, 0x8c7c64, 0.8);   // sky above, light bounced off sunlit paving below
scene.add(hemi);
// The sky never changes: render the atmosphere shader once into a cube map for the
// background and a prefiltered copy for reflections (glass, water, metal). It is not
// the scene's environment light: three's sky has a bright circumsolar halo and a
// glowing lower half, and as diffuse light it outshone the sun twelvefold, leaving
// every facade flat and white.
const SKY_LEVEL = 0.4;          // sky brightness relative to the sun, matched to the renders
// The renders look through a 30 km haze volume: a grey veil over the sky, thin
// overhead and thick at the horizon (three's sky alone is an alpine deep blue with
// a white horizon, which the river then mirrors)
const VEIL = { color: [0.7, 0.7, 0.68], zenith: 0.1, horizon: 0.68 };
let ENV = null;
{
  const skyScene = new THREE.Scene(); skyScene.add(sky);
  skyScene.add(new THREE.Mesh(new THREE.SphereGeometry(5000, 32, 16), new THREE.ShaderMaterial({
    side: THREE.BackSide, transparent: true, depthWrite: false, depthTest: false,
    uniforms: { veil: { value: new THREE.Vector3(...VEIL.color) }, a0: { value: VEIL.zenith }, a1: { value: VEIL.horizon } },
    vertexShader: 'varying vec3 vDir;\nvoid main() { vDir = position; gl_Position = projectionMatrix * modelViewMatrix * vec4( position, 1.0 ); }',
    fragmentShader: 'uniform vec3 veil; uniform float a0, a1; varying vec3 vDir;\n'
      + 'void main() { float y = max( normalize( vDir ).y, 0.0 ); gl_FragColor = vec4( veil, mix( a1, a0, pow( y, 0.66 ) ) ); }',
  })));
  const cubeRT = new THREE.WebGLCubeRenderTarget(LOW ? 256 : 512, { type: THREE.HalfFloatType });
  new THREE.CubeCamera(1, 30000, cubeRT).update(renderer, skyScene);
  scene.background = cubeRT.texture;
  scene.backgroundIntensity = SKY_LEVEL;
  // reflections leave the sun disc out: its glint comes from the DirectionalLight
  if (sky.material.uniforms.showSunDisc) sky.material.uniforms.showSunDisc.value = 0;
  const pm = new THREE.PMREMGenerator(renderer);
  ENV = pm.fromScene(skyScene, 0, 0.1, 30000).texture;
  pm.dispose();
}
// reflective materials see the sky at the brightness the background shows it
const reflective = (m, k = 1) => { m.envMap = ENV; m.envMapIntensity = SKY_LEVEL * k; return m; };

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
    const entry = manifest.files?.[key] || {};
    status(`下载模型 ${key}…`);
    let buf;
    try {
      const progress = (got) => setProgress((base + Math.min(got, sizes[i])) / totalBytes * 0.9);
      buf = entry.parts ? await fetchParts(entry.parts.map((p) => `assets/${p}`), progress)
        : await fetchBuffer(`assets/${entry.file || key + '.glb'}`, progress);
    } catch (e) { console.warn('skip', key, e); base += sizes[i]; continue; }
    base += sizes[i];
    const gltf = await loader.parseAsync(buf, '');
    const far = key === 'context';
    gltf.scene.traverse((o) => {
      o.matrixAutoUpdate = false;     // static city: compute matrices once, not every frame
      o.updateMatrix();
      if (!o.isMesh) return;
      const mats = Array.isArray(o.material) ? o.material : [o.material];
      const vc = !!o.geometry.attributes.color;
      const repl = mats.map((m) => (far ? cheapMaterialFor(m.name || '', vc) : materialFor(m.name || '', vc)));
      o.material = Array.isArray(o.material) ? repl : repl[0];
      o.castShadow = key !== 'ground' && !far;
      o.receiveShadow = !far;
      if (WALKABLE.has(key)) { o.geometry.computeBoundsTree(); walkMeshes.push(o); }
    });
    scene.add(gltf.scene);
    gltf.scene.updateMatrixWorld(true);
    // benches, bins and flower beds (300 m cells) are only drawn within 450 m
    if (key === 'furniture') gltf.scene.traverse((o) => { if (o.isMesh) addCull(o, 450); });
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
  // ripples: finer texels and gentler slopes than a sharp chop, so the low sun's
  // glitter path shimmers instead of breaking into blocky texel-sized sparks
  const N = 512;
  waterNormal = (() => {
    const t = paint(N, N, (u, v) => {
      const h = fbm(u * 8, v * 8, 21, 8, 4) * 0.75 + fbm(u * 24, v * 24, 22, 24, 2) * 0.25;
      return [0, 0, 0, 255, h];
    }, false);
    const n = normalFrom(t, 7); n.repeat.set(1 / 18, 1 / 18); return n;
  })();
  // silt-laden Huangpu water: khaki brown, choppy from the constant boat traffic
  const mat = reflective(new THREE.MeshStandardMaterial({ color: 0x4a4534, roughness: 0.14, metalness: 0.0, normalMap: waterNormal,
    normalScale: new THREE.Vector2(0.6, 0.6) }), 0.42);
  const z = world.levels.water;
  const parts = [];
  for (const p of world.water) {
    const sh = new THREE.Shape(p.ext.map(([x, y]) => new THREE.Vector2(x, y)));
    for (const h of p.holes || []) sh.holes.push(new THREE.Path(h.map(([x, y]) => new THREE.Vector2(x, y))));
    const g = new THREE.ShapeGeometry(sh);
    // ShapeGeometry is in XY; after rotateX(-90) y -> -z, which matches Blender y -> three -z
    g.rotateX(-Math.PI / 2);
    parts.push(g);
  }
  // one mesh for all the river polygons: one draw call
  const m = new THREE.Mesh(mergeGeoms(parts), mat); m.position.y = z; m.receiveShadow = true;
  m.matrixAutoUpdate = false; m.updateMatrix(); scene.add(m);
  // wide river beyond the detailed area (context ring has its own water)
  const bed = new THREE.Mesh(new THREE.PlaneGeometry(30000, 30000), reflective(new THREE.MeshStandardMaterial({ color: 0x4a4534, roughness: 0.12, normalMap: waterNormal }), 0.42));
  bed.rotation.x = -Math.PI / 2; bed.position.y = z - 0.05; scene.add(bed);
}

// ---------------------------------------------------------------------------
// trees (instanced): forked trunk with bark + a crown of alpha-tested leaf cards
// ---------------------------------------------------------------------------
const TREE = {
  // London plane (悬铃木): flaking camouflage bark, broad crown, leaves just turning;
  // camphor (香樟): evergreen, dark glossy, low dense dome; ginkgo (银杏): slim, fan leaves yellowing
  plane: { trunkH: 3.0, crownY: 9.2, R: 4.8, Ry: 4.0, cards: 110, card: 2.6, limbs: 3, leaf: 'lobed',
    leaves: ['#4c6a28', '#5a762c', '#6a8030', '#87883a', '#9a8a3c'] },
  camphor: { trunkH: 2.2, crownY: 7.0, R: 4.6, Ry: 3.4, cards: 110, card: 2.3, limbs: 4, leaf: 'oval',
    leaves: ['#26421e', '#30502a', '#3e602c', '#4f7032'] },
  ginkgo: { trunkH: 3.4, crownY: 8.6, R: 2.7, Ry: 4.4, cards: 70, card: 2.0, limbs: 0, leaf: 'fan',
    leaves: ['#7e8c30', '#9aa034', '#b8aa3a', '#cdb444'] },
};
function leafCardTexture(kind) {
  // a sprig of leaves on a transparent card, drawn with canvas paths
  const spec = TREE[kind]; const S = 256;
  const c = document.createElement('canvas'); c.width = c.height = S;
  const ctx = c.getContext('2d');
  let s = kind.length * 7919 + 17; const rnd = () => (s = (s * 16807) % 2147483647) / 2147483647;
  ctx.strokeStyle = 'rgb(70,58,40)'; ctx.lineWidth = 2;                   // twigs
  for (let i = 0; i < 5; i++) {
    const a = rnd() * Math.PI * 2; ctx.beginPath(); ctx.moveTo(S / 2, S / 2);
    ctx.lineTo(S * (0.5 + Math.cos(a) * 0.36), S * (0.5 + Math.sin(a) * 0.36)); ctx.stroke();
  }
  for (let i = 0; i < (spec.leaf === 'fan' ? 80 : 64); i++) {
    const r = Math.sqrt(rnd()) * 0.4, a = rnd() * Math.PI * 2;
    const [cr, cg, cb] = hex(spec.leaves[Math.floor(rnd() * spec.leaves.length)]);
    const k = 0.72 + 0.4 * rnd() - 0.22 * (1 - r / 0.4);       // leaves deeper in the sprig are darker
    ctx.fillStyle = `rgb(${Math.min(255, cr * k) | 0},${Math.min(255, cg * k) | 0},${Math.min(255, cb * k) | 0})`;
    ctx.save(); ctx.translate((0.5 + Math.cos(a) * r) * S, (0.5 + Math.sin(a) * r) * S); ctx.rotate(rnd() * Math.PI * 2);
    const L = S * (spec.leaf === 'fan' ? 0.07 : 0.085) * (0.75 + 0.5 * rnd());
    if (spec.leaf === 'fan') { ctx.beginPath(); ctx.moveTo(0, 0); ctx.arc(0, 0, L, -0.9, 0.9); ctx.closePath(); ctx.fill(); }
    else if (spec.leaf === 'lobed') {
      for (const t of [-0.8, 0, 0.8]) { ctx.beginPath(); ctx.ellipse(Math.cos(t) * L * 0.35, Math.sin(t) * L * 0.35, L * 0.6, L * 0.34, t, 0, Math.PI * 2); ctx.fill(); }
    } else { ctx.beginPath(); ctx.ellipse(0, 0, L, L * 0.42, 0, 0, Math.PI * 2); ctx.fill(); }
    ctx.restore();
  }
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = MAX_ANISO;
  return t;
}
function barkTexture(kind) {
  const t = paint(128, 256, (u, v) => {
    const n = fbm(u * 4, v * 8, 41, 4, 3), m = fbm(u * 8, v * 16, 42, 8, 2);
    let c;
    if (kind === 'plane') c = n > 0.55 ? [192, 184, 150] : (m > 0.52 ? [112, 114, 90] : [150, 145, 122]);   // flaking patches
    else {
      const f = Math.abs(Math.sin((u * 10 + n * 2.5) * Math.PI));                               // vertical furrows
      c = mixc(kind === 'ginkgo' ? [110, 104, 92] : [86, 74, 62], [34, 30, 26], Math.pow(1 - f, 4) * 0.8 + 0.15 * m);
    }
    c = mixc(c, [40, 38, 32], 0.25 * m);
    return [c[0], c[1], c[2], 255];
  });
  t.repeat.set(1, 2);
  return t;
}
function treeGeometry(kind) {
  const spec = TREE[kind];
  let s = kind.length * 104729 + 3; const rnd = () => (s = (s * 16807) % 2147483647) / 2147483647;
  // trunk and the main limbs forking into the crown
  const parts = [];
  const trunk = new THREE.CylinderGeometry(0.2, 0.3, spec.trunkH + 0.4, 8, 1, true); trunk.translate(0, (spec.trunkH + 0.4) / 2 - 0.2, 0);
  parts.push(trunk);
  const up = new THREE.Vector3(0, 1, 0);
  const limbs = spec.limbs || 1;
  for (let i = 0; i < limbs; i++) {
    const a = (i / limbs + rnd() * 0.2) * Math.PI * 2;
    const tip = spec.limbs ? new THREE.Vector3(Math.cos(a) * spec.R * 0.5, spec.crownY + 0.5, Math.sin(a) * spec.R * 0.5)
      : new THREE.Vector3(0, spec.crownY + spec.Ry * 0.8, 0);                     // ginkgo: a central leader
    const base = new THREE.Vector3(0, spec.trunkH - 0.2, 0);
    const d = tip.clone().sub(base); const len = d.length();
    const g = new THREE.CylinderGeometry(0.08, 0.17, len, 6, 1, true); g.translate(0, len / 2, 0);
    g.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(up, d.normalize())); g.translate(base.x, base.y, base.z);
    parts.push(g);
  }
  // leaf cards in an ellipsoid shell, front faces turned outward, normals bent
  // outward so the crown shades like a volume; each card twice (both windings)
  const pos = [], nor = [], uv = [];
  const C = new THREE.Vector3(0, spec.crownY, 0);
  const n = new THREE.Vector3(), t1 = new THREE.Vector3(), t2 = new THREE.Vector3(), p = new THREE.Vector3(), o = new THREE.Vector3();
  for (let i = 0; i < spec.cards; i++) {
    const z = rnd() * 2 - 1, a = rnd() * Math.PI * 2, q = Math.sqrt(1 - z * z);
    const f = 0.5 + 0.5 * Math.cbrt(rnd());
    const taper = spec.leaf === 'fan' ? 1 - 0.35 * Math.max(0, z) : 1;           // ginkgo narrows upwards
    p.set(Math.cos(a) * q * spec.R * f * taper, spec.crownY + z * spec.Ry * f, Math.sin(a) * q * spec.R * f * taper);
    o.copy(p).sub(C).normalize();
    n.set(o.x + (rnd() - 0.5) * 1.4, o.y + (rnd() - 0.5) * 1.4, o.z + (rnd() - 0.5) * 1.4).normalize();
    t1.set(Math.abs(n.y) < 0.9 ? 0 : 1, Math.abs(n.y) < 0.9 ? 1 : 0, 0).cross(n).normalize(); t2.crossVectors(n, t1);
    const h = spec.card * (0.8 + 0.4 * rnd()) / 2;
    const rot = rnd() * Math.PI * 2, cs = Math.cos(rot) * h, sn = Math.sin(rot) * h;
    const corners = [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([x, y]) => p.clone()
      .addScaledVector(t1, x * cs - y * sn).addScaledVector(t2, x * sn + y * cs));
    const bent = o.clone().multiplyScalar(0.7).addScaledVector(n, 0.3).normalize();
    for (const [i0, i1, i2] of [[0, 1, 2], [0, 2, 3], [0, 2, 1], [0, 3, 2]]) {
      for (const k of [i0, i1, i2]) {
        pos.push(corners[k].x, corners[k].y, corners[k].z); nor.push(bent.x, bent.y, bent.z);
        uv.push(k === 1 || k === 2 ? 1 : 0, k >= 2 ? 1 : 0);
      }
    }
  }
  const crown = new THREE.BufferGeometry();
  crown.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  crown.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3));
  crown.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  return { trunk: mergeGeoms(parts), crown };
}
function mergeGeoms(list0) {
  const list = list0.map((g) => (g.index ? g.toNonIndexed() : g));   // count after de-indexing
  let count = 0; for (const g of list) count += g.attributes.position.count;
  const pos = new Float32Array(count * 3), nor = new Float32Array(count * 3), uv = new Float32Array(count * 2);
  let o = 0;
  for (const g of list) {
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
// Distance culling: small things (trees, street furniture) are hidden beyond a range
// where they would be a few pixels in the haze anyway. Checked a few times a second.
const cullList = [];
function addCull(obj, maxDist) {
  const sphere = obj.isInstancedMesh ? obj.boundingSphere : (obj.geometry.boundingSphere || (obj.geometry.computeBoundingSphere(), obj.geometry.boundingSphere));
  const c = sphere.center.clone().applyMatrix4(obj.matrixWorld);
  cullList.push({ obj, c, r: sphere.radius, max: maxDist });
}
function distanceCull() {
  for (const e of cullList) e.obj.visible = e.c.distanceTo(camera.position) - e.r < e.max;
}
function buildTrees() {
  // instanced per species and per 250 m cell, so off-screen and distant cells are skipped
  const CELL = 250;
  const groups = {};
  for (const t of world.trees) {
    if (!TREE[t[3]]) continue;
    const key = `${t[3]}|${Math.floor(t[0] / CELL)}|${Math.floor(t[1] / CELL)}`;
    (groups[key] ||= []).push(t);
  }
  const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), p = new THREE.Vector3();
  const tint = new THREE.Color();
  const shared = {};
  for (const [key, list] of Object.entries(groups)) {
    const kind = key.split('|')[0];
    if (!shared[kind]) {
      const { trunk, crown } = treeGeometry(kind);
      shared[kind] = { trunk, crown, trunkMat: new THREE.MeshStandardMaterial({ map: barkTexture(kind), roughness: 0.92 }),
        crownMat: new THREE.MeshStandardMaterial({ map: leafCardTexture(kind), alphaTest: 0.45, roughness: 0.72 }) };
    }
    const sh = shared[kind];
    const trunkM = new THREE.InstancedMesh(sh.trunk, sh.trunkMat, list.length);
    const crownM = new THREE.InstancedMesh(sh.crown, sh.crownMat, list.length);
    list.forEach((t, i) => {
      p.copy(B(t[0], t[1], t[2])); q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), t[5]); s.setScalar(t[4]);
      m4.compose(p, q, s); trunkM.setMatrixAt(i, m4); crownM.setMatrixAt(i, m4);
      // no two crowns quite the same shade
      const h = hash(Math.round(t[0] * 10), Math.round(t[1] * 10), 5);
      tint.setRGB(0.84 + 0.26 * h, 0.88 + 0.18 * h, 0.86 + 0.1 * (1 - h)); crownM.setColorAt(i, tint);
    });
    for (const m of [trunkM, crownM]) {
      m.castShadow = true; m.receiveShadow = true; m.matrixAutoUpdate = false; m.updateMatrix();
      m.computeBoundingSphere(); scene.add(m); m.updateMatrixWorld(true);
      addCull(m, 1100);
    }
  }
}

// ---------------------------------------------------------------------------
// lamps & signals (instanced)
// ---------------------------------------------------------------------------
function buildLamps() {
  const pole = new THREE.CylinderGeometry(0.08, 0.14, 1, 8); pole.translate(0, 0.5, 0);
  const globe = new THREE.SphereGeometry(0.28, 12, 8);
  const types = { bund: 7.6, promenade: 4.3, street: 8.4 };
  const metal = reflective(new THREE.MeshStandardMaterial({ color: 0x242826, roughness: 0.45, metalness: 0.3 }));
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
  const grey = reflective(new THREE.MeshStandardMaterial({ color: 0x82868a, metalness: 0.6, roughness: 0.35 }));
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
  const glass = reflective(new THREE.MeshStandardMaterial({ color: 0x223344, roughness: 0.1, metalness: 0.4 }));
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
  const railM = reflective(new THREE.MeshStandardMaterial({ color: 0xdddddd, metalness: 0.5, roughness: 0.3 }));
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
  // small map: click to open the full map; full map: click anywhere to go there
  $('map').addEventListener('click', (e) => {
    if (!bigMap()) { setBigMap(true); return; }
    const cv = $('map-c'); const r = cv.getBoundingClientRect();
    const cx = (e.clientX - r.left) / r.width * cv.width, cy = (e.clientY - r.top) / r.height * cv.height;
    if (cx < 0 || cy < 0 || cx > cv.width || cy > cv.height) { setBigMap(false); return; }
    const S = mapBase.width / MAP.size, k = cv.width / mapBase.width;
    teleportTo(MAP.x0 + cx / k / S, MAP.y0 + (mapBase.height - cy / k) / S);
    setBigMap(false);
  });
}
const bigMap = () => $('map').classList.contains('big');
function setBigMap(on) {
  $('map').classList.toggle('big', on);
  const c = $('map-c'); const size = on ? 840 : 420;
  if (c.width !== size) { c.width = size; c.height = size; }
  $('map-hint').hidden = !on;
  if (on) document.exitPointerLock?.(); else if (running) requestLock();
  mapT = 0;                                   // redraw on the next frame
}
let flashUntil = 0;
function flash(text) {
  const p = $('prompt'); p.textContent = text; p.hidden = false; flashUntil = performance.now() + 2500;
}
function teleportTo(bx, by) {
  // nearest walkable spot to the clicked point: outside buildings, on the ground, not in the river
  const tryAt = (x, y) => {
    if (blockedByBuilding(x, y, 0.5)) return null;
    const p = B(x, y, 0); const g = groundAt(new THREE.Vector3(p.x, 40, p.z), 40);
    if (g === null || g < world.levels.water + 0.3) return null;
    return new THREE.Vector3(p.x, g, p.z);
  };
  let spot = tryAt(bx, by);
  for (let r = 3; !spot && r <= 300; r += 3) {
    const n = Math.max(8, Math.round(2 * Math.PI * r / 3));
    for (let i = 0; i < n && !spot; i++) spot = tryAt(bx + Math.cos(2 * Math.PI * i / n) * r, by + Math.sin(2 * Math.PI * i / n) * r);
  }
  if (!spot) { flash('那里超出可漫游范围'); return false; }
  ferry.aboard = false;
  player.pos.copy(spot); player.vy = 0;
  if (player.fly) player.pos.y += 25;
  hudT = 0;
  return true;
}
function drawMinimap() {
  const c = $('map-c'); const ctx = c.getContext('2d');
  const W = c.width;
  const S = mapBase.width / MAP.size;
  const px = (player.pos.x - MAP.x0) * S, py = mapBase.height - ((-player.pos.z) - MAP.y0) * S;
  if (bigMap()) {
    // the whole map, north up, with the teleport places for orientation
    const k = W / mapBase.width;
    ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, W, W);
    ctx.drawImage(mapBase, 0, 0, W, W);
    ctx.font = '600 20px "Noto Sans SC", sans-serif'; ctx.textBaseline = 'middle';
    // the places sit close together along the river: each label takes the first
    // free spot right, left, above or below its dot (or further down the right side)
    const taken = [];
    for (const t of world.teleports) {
      const tx = (t.pos[0] - MAP.x0) * S * k, ty = (mapBase.height - (t.pos[1] - MAP.y0) * S) * k;
      ctx.fillStyle = '#d8b46a'; ctx.beginPath(); ctx.arc(tx, ty, 5, 0, Math.PI * 2); ctx.fill();
      const w = ctx.measureText(t.name).width;
      const spots = [[tx + 9, ty], [tx - 9 - w, ty], [tx - w / 2, ty - 20], [tx - w / 2, ty + 20],
        [tx + 9, ty + 22], [tx + 9, ty - 22], [tx + 9, ty + 44], [tx + 9, ty - 44]];
      const free = spots.find(([x, y]) => x > 2 && x + w < W - 2 &&
        !taken.some((b) => x < b[2] && x + w > b[0] && y - 12 < b[3] && y + 12 > b[1]));
      if (!free) continue;
      taken.push([free[0] - 4, free[1] - 12, free[0] + w + 4, free[1] + 12]);
      ctx.lineWidth = 4; ctx.strokeStyle = 'rgba(14,20,22,0.85)'; ctx.strokeText(t.name, free[0], free[1]);
      ctx.fillStyle = '#f3ede1'; ctx.fillText(t.name, free[0], free[1]);
    }
    if (ferry.group) {
      const fx = (ferry.group.position.x - MAP.x0) * S * k, fy = (mapBase.height - ((-ferry.group.position.z) - MAP.y0) * S) * k;
      ctx.fillStyle = '#6fb59a'; ctx.beginPath(); ctx.arc(fx, fy, 7, 0, Math.PI * 2); ctx.fill();
    }
    ctx.save(); ctx.translate(px * k, py * k); ctx.rotate(-player.yaw);
    ctx.fillStyle = '#f3ede1'; ctx.strokeStyle = '#0e1416'; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(0, -16); ctx.lineTo(10, 11); ctx.lineTo(0, 6); ctx.lineTo(-10, 11); ctx.closePath(); ctx.fill(); ctx.stroke();
    ctx.restore();
    return;
  }
  const scale = 2.4;
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
  if (performance.now() > flashUntil) { prompt.hidden = !text; prompt.textContent = text; }
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
let lockedAt = 0, skipMoves = 0;
document.addEventListener('pointerlockchange', () => {
  locked = document.pointerLockElement === canvas;
  // Chrome follows the lock with one mousemove that undoes the cursor's last move
  // (hundreds of pixels); on a slow first frame it arrives after the 250 ms window
  if (locked) { lockedAt = performance.now(); skipMoves = 1; }
  if (!locked && running && $('tp').hidden && !bigMap() && !matchMedia('(pointer: coarse)').matches) showPause();
});
function showPause() { $('intro').hidden = false; $('start').textContent = '继续漫游'; $('hud').hidden = true; running = false; }
document.addEventListener('mousemove', (e) => {
  if (!locked || bigMap()) return;
  if (skipMoves > 0 || performance.now() - lockedAt < 250) { skipMoves = 0; return; }
  player.yaw -= e.movementX * 0.0022; player.pitch -= e.movementY * 0.0022;
  player.pitch = THREE.MathUtils.clamp(player.pitch, -1.45, 1.45);
});
window.addEventListener('keydown', (e) => {
  keys.add(e.code);
  if (!running) return;
  if (e.code === 'KeyE') interact();
  if (e.code === 'KeyT') { const tp = $('tp'); tp.hidden = !tp.hidden; if (!tp.hidden) document.exitPointerLock?.(); else requestLock(); }
  if (e.code === 'KeyM') setBigMap(!bigMap());
  if (e.code === 'Escape' && bigMap()) setBigMap(false);
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
  renderer.shadowMap.needsUpdate = true;
});

// ---------------------------------------------------------------------------
// loop
// ---------------------------------------------------------------------------
let lastT = performance.now(), hudT = 0, mapT = 0, shadowT = 0, cullT = 0;
const TIME_SCALE = location.hash === '#fastferry' ? 25 : 1;   // debug: speed up the ferry
const shadowAt = new THREE.Vector3(1e9, 0, 0);
// frame-time statistics for the adaptive resolution (and the #stats overlay)
const perf = { t: 0, n: 0, fps: 60 };
let statsEl = null;
if (STATS) {
  statsEl = document.createElement('div');
  Object.assign(statsEl.style, { position: 'fixed', left: '8px', top: '8px', zIndex: 50, font: '12px monospace',
    color: '#f3ede1', background: 'rgba(0,0,0,0.55)', padding: '4px 6px', pointerEvents: 'none' });
  document.body.appendChild(statsEl);
}
function adaptResolution(dt) {
  perf.t += dt; perf.n++;
  if (perf.t < 1.5) return;
  perf.fps = perf.n / perf.t; perf.t = 0; perf.n = 0;
  let next = dpr;
  if (perf.fps < 42) next = Math.max(DPR_MIN, dpr * 0.85);
  else if (perf.fps > 57 && dpr < DPR_MAX) next = Math.min(DPR_MAX, dpr * 1.1);
  if (Math.abs(next - dpr) > 0.02) {
    dpr = next;
    renderer.setPixelRatio(dpr);
    renderer.setSize(window.innerWidth, window.innerHeight);
  }
  if (statsEl) {
    const i = renderer.info.render;
    statsEl.textContent = `${perf.fps.toFixed(0)} fps · ${i.calls} draws · ${(i.triangles / 1e6).toFixed(2)} M tris · dpr ${dpr.toFixed(2)}`;
  }
}
function updateShadows(dt) {
  // The shadow map is cached: it is redrawn only after the player has moved a few
  // metres, or while the ferry sails nearby. Standing still costs no shadow pass.
  if (!renderer.shadowMap.enabled) return;
  shadowT -= dt;
  const ferryNear = ferry.group && ferry.phase === 'cruise' && ferry.group.position.distanceTo(camera.position) < 250;
  if (camera.position.distanceTo(shadowAt) > 3 || (ferryNear && shadowT <= 0)) {
    // snap the centre to the texel grid in the light's view plane: the map moves by
    // whole texels, so shadows do not swim or flicker when it is redrawn
    const texel = 2 * SHADOW.half / SHADOW.size, snap = (v) => Math.round(v / texel) * texel;
    const p = camera.position;
    shadowAt.copy(shadowX).multiplyScalar(snap(p.dot(shadowX)))
      .addScaledVector(shadowY, snap(p.dot(shadowY))).addScaledVector(sunDir, p.dot(sunDir));
    sun.position.copy(shadowAt).addScaledVector(sunDir, 400);
    sun.target.position.copy(shadowAt);
    sun.target.updateMatrixWorld();
    renderer.shadowMap.needsUpdate = true;
    shadowT = 0.25;
  }
}
function frame() {
  const now = performance.now();
  const dt = Math.min((now - lastT) / 1000, 0.05); lastT = now;
  if (world) {
    updateFerry(ferry.phase === 'cruise' ? dt * TIME_SCALE : dt);
    if (running) movePlayer(dt);
    camera.position.copy(player.pos); camera.position.y += player.fly ? 0 : EYE;
    camera.rotation.set(player.pitch, player.yaw, 0, 'YXZ');
    updateShadows(dt);
    if (waterNormal) waterNormal.offset.set(now * 0.000006, now * 0.000004);
    hudT -= dt; mapT -= dt; cullT -= dt;
    if (cullT <= 0) { cullT = 0.3; distanceCull(); }
    if (running && hudT <= 0) { hudT = 0.25; updateHud(); }
    if (running && mapBase && mapT <= 0) { mapT = 0.1; drawMinimap(); }
    adaptResolution(dt);
  }
  renderer.render(scene, camera);
  requestAnimationFrame(frame);
}
// preview while loading: hover above the river looking at the Bund
camera.position.set(260, 60, 120); camera.lookAt(-150, 20, 0);
frame();
load().catch((e) => { console.error(e); status(`载入失败：${e.message}。请刷新重试。`); });
