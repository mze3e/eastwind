// Kit: procedural building blocks. No external models or textures, so the story
// loads from one origin and works offline.
import { THREE, ease } from './engine.js';

export const C = {
  navy: 0x0b1626, deep: 0x0f2036, floor: 0x12263d, grid: 0x1e3b5c, slate: 0x2c4a6b, mid: 0x3d6288,
  paper: 0xeef3f9, ink: 0x0d1b2e, white: 0xffffff,
  gold: 0xe5b567, cyan: 0x4cc9f0, amber: 0xffb547, blue: 0x7aa2ff, violet: 0xa78bfa,
  good: 0x3ecf8e, bad: 0xff6b6b, grey: 0x8fa3b8,
};
export const css = (hex) => `#${hex.toString(16).padStart(6, '0')}`;
export const FONT = 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';

export const mat = (color, o = {}) => new THREE.MeshStandardMaterial({ color, roughness: 0.5, metalness: 0.1, ...o });
export const emissive = (color, intensity = 1, o = {}) =>
  new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: intensity, roughness: 0.4, metalness: 0, ...o });
export const basic = (color, opacity = 1, o = {}) => new THREE.MeshBasicMaterial({ color, transparent: opacity < 1, opacity, ...o });

// ---------------------------------------------------------------- geometry

export function roundedBoxGeometry(w, h, d, r = 0.12) {
  const b = Math.min(0.04, d / 4, r / 2);
  const iw = w - 2 * b, ih = h - 2 * b, x = -iw / 2, y = -ih / 2, rr = Math.max(0.001, r - b);
  const s = new THREE.Shape();
  s.moveTo(x + rr, y); s.lineTo(x + iw - rr, y); s.quadraticCurveTo(x + iw, y, x + iw, y + rr);
  s.lineTo(x + iw, y + ih - rr); s.quadraticCurveTo(x + iw, y + ih, x + iw - rr, y + ih);
  s.lineTo(x + rr, y + ih); s.quadraticCurveTo(x, y + ih, x, y + ih - rr);
  s.lineTo(x, y + rr); s.quadraticCurveTo(x, y, x + rr, y);
  const g = new THREE.ExtrudeGeometry(s, { depth: Math.max(0.001, d - 2 * b), bevelEnabled: true, bevelThickness: b, bevelSize: b, bevelSegments: 2, curveSegments: 6 });
  g.translate(0, 0, -(d - 2 * b) / 2);
  return g;
}

export function slab(w, h, d, r, material) {
  const m = new THREE.Mesh(roundedBoxGeometry(w, h, d, r), material);
  return m;
}

// ----------------------------------------------------------------- sprites

let glowTex;
export function glowTexture() {
  if (glowTex) return glowTex;
  const c = document.createElement('canvas'); c.width = c.height = 128;
  const g = c.getContext('2d');
  const grad = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  grad.addColorStop(0, 'rgba(255,255,255,1)'); grad.addColorStop(0.25, 'rgba(255,255,255,.55)');
  grad.addColorStop(0.6, 'rgba(255,255,255,.12)'); grad.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = grad; g.fillRect(0, 0, 128, 128);
  glowTex = new THREE.CanvasTexture(c); glowTex.colorSpace = THREE.SRGBColorSpace;
  return glowTex;
}

export function glowSprite(color, size = 2, opacity = 0.8) {
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTexture(), color, transparent: true, opacity, depthWrite: false, blending: THREE.AdditiveBlending }));
  s.scale.set(size, size, 1);
  return s;
}

let blobTex;
export function shadowBlob(radius = 1, opacity = 0.45) {
  if (!blobTex) {
    const c = document.createElement('canvas'); c.width = c.height = 128;
    const g = c.getContext('2d');
    const grad = g.createRadialGradient(64, 64, 4, 64, 64, 64);
    grad.addColorStop(0, 'rgba(0,0,0,.9)'); grad.addColorStop(1, 'rgba(0,0,0,0)');
    g.fillStyle = grad; g.fillRect(0, 0, 128, 128);
    blobTex = new THREE.CanvasTexture(c);
  }
  const m = new THREE.Mesh(new THREE.PlaneGeometry(radius * 2, radius * 2),
    new THREE.MeshBasicMaterial({ map: blobTex, transparent: true, opacity, depthWrite: false }));
  m.rotation.x = -Math.PI / 2; m.position.y = 0.02;
  return m;
}

// ------------------------------------------------------------ canvas panels

export function roundRect(g, x, y, w, h, r) {
  g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath();
}

export function wrap(g, text, x, y, maxWidth, lineHeight, maxLines = 99) {
  const words = String(text).split(/\s+/); let line = ''; let n = 0;
  for (let i = 0; i < words.length; i++) {
    const test = line ? `${line} ${words[i]}` : words[i];
    if (g.measureText(test).width > maxWidth && line) {
      if (++n >= maxLines) { g.fillText(`${line}…`, x, y); return y + lineHeight; }
      g.fillText(line, x, y); y += lineHeight; line = words[i];
    } else line = test;
  }
  g.fillText(line, x, y);
  return y + lineHeight;
}

/** Draw text no wider than maxWidth by shrinking the font; returns the size used. */
export function fit(g, text, x, y, maxWidth, size, weight = 700) {
  let px = size;
  g.font = `${weight} ${px}px ${FONT}`;
  while (g.measureText(text).width > maxWidth && px > size * 0.5) { px -= 1; g.font = `${weight} ${px}px ${FONT}`; }
  g.fillText(text, x, y);
  return px;
}

/** A plane textured from a 2D canvas. `draw(ctx, W, H)` can be re-run with panel.redraw(). */
export function panel(width, height, draw, { ppu = 200, opacity = 1, depthTest = true } = {}) {
  const c = document.createElement('canvas');
  c.width = Math.round(width * ppu); c.height = Math.round(height * ppu);
  const g = c.getContext('2d');
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 4;
  // Printed colors must stay true: tone mapping would turn white paper grey.
  const material = new THREE.MeshBasicMaterial({ map: tex, transparent: true, opacity, depthTest, side: THREE.DoubleSide, toneMapped: false });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(width, height), material);
  mesh.userData.redraw = (fn = draw) => { g.clearRect(0, 0, c.width, c.height); fn(g, c.width, c.height); tex.needsUpdate = true; };
  mesh.userData.redraw(draw);
  return mesh;
}

/** Small vector icons drawn to a canvas: check, cross, lock, dot, arrow. */
export function icon(kind, color = C.good, size = 0.7) {
  const p = panel(size, size, (g, W, H) => {
    g.clearRect(0, 0, W, H); const col = css(color);
    g.lineCap = 'round'; g.lineJoin = 'round'; g.strokeStyle = col; g.fillStyle = col; g.lineWidth = W * 0.1;
    g.beginPath(); g.arc(W / 2, H / 2, W * 0.44, 0, 7); g.fillStyle = 'rgba(8,18,32,.88)'; g.fill(); g.stroke();
    g.beginPath();
    if (kind === 'check') { g.moveTo(W * 0.28, H * 0.52); g.lineTo(W * 0.44, H * 0.67); g.lineTo(W * 0.73, H * 0.34); g.stroke(); }
    else if (kind === 'cross') { g.moveTo(W * 0.33, H * 0.33); g.lineTo(W * 0.67, H * 0.67); g.moveTo(W * 0.67, H * 0.33); g.lineTo(W * 0.33, H * 0.67); g.stroke(); }
    else if (kind === 'lock') {
      g.fillStyle = col; roundRect(g, W * 0.3, H * 0.46, W * 0.4, H * 0.28, W * 0.04); g.fill();
      g.lineWidth = W * 0.07; g.beginPath(); g.arc(W / 2, H * 0.46, W * 0.14, Math.PI, 0); g.stroke();
    } else if (kind === 'dot') { g.fillStyle = col; g.arc(W / 2, H / 2, W * 0.14, 0, 7); g.fill(); }
  }, { ppu: 160 });
  return p;
}

// --------------------------------------------------------------- characters

export function robot({ accent = C.cyan } = {}) {
  const g = new THREE.Group();
  const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.5, 0.75, 8, 20), mat(C.paper, { roughness: 0.35 }));
  body.position.y = 1.1;
  const belly = new THREE.Mesh(new THREE.TorusGeometry(0.5, 0.045, 10, 36), emissive(accent, 1.6));
  belly.rotation.x = Math.PI / 2; belly.position.y = 0.95;
  const head = new THREE.Group(); head.position.y = 2.18;
  const skull = new THREE.Mesh(new THREE.SphereGeometry(0.62, 28, 20), mat(C.paper, { roughness: 0.3 })); skull.scale.set(1, 0.82, 0.95);
  const visor = new THREE.Mesh(new THREE.SphereGeometry(0.5, 24, 16), mat(0x08111f, { roughness: 0.15, metalness: 0.4 }));
  visor.scale.set(1.02, 0.6, 0.62); visor.position.set(0, 0.02, 0.4);
  const eyeMat = emissive(accent, 2.2);
  const eyes = [-0.2, 0.2].map((x) => { const e = new THREE.Mesh(new THREE.SphereGeometry(0.08, 12, 10), eyeMat); e.position.set(x, 0.05, 0.69); e.scale.set(1, 1.25, 0.6); return e; });
  const ant = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.025, 0.38, 8), mat(C.grey)); ant.position.y = 0.68;
  const bulb = new THREE.Mesh(new THREE.SphereGeometry(0.09, 12, 10), emissive(C.gold, 2)); bulb.position.y = 0.9;
  head.add(skull, visor, ...eyes, ant, bulb);
  const arms = [-1, 1].map((s) => {
    const pivot = new THREE.Group(); pivot.position.set(s * 0.62, 1.45, 0);
    const arm = new THREE.Mesh(new THREE.CapsuleGeometry(0.11, 0.5, 6, 12), mat(C.paper, { roughness: 0.35 })); arm.position.y = -0.3; arm.rotation.z = s * 0.1;
    const hand = new THREE.Mesh(new THREE.SphereGeometry(0.14, 12, 10), mat(accent, { roughness: 0.3 })); hand.position.set(s * 0.05, -0.64, 0);
    pivot.add(arm, hand); return pivot;
  });
  const halo = glowSprite(accent, 3.0, 0.3); halo.position.y = 1.7;
  const shadow = shadowBlob(0.95, 0.5);
  const hover = new THREE.Group(); hover.add(body, belly, head, ...arms, halo);
  hover.position.y = 0.3;
  g.add(shadow, hover);
  g.userData = { hover, head, arms, eyeMat, eyes, halo, belly, accent, baseY: 0.3 };
  g.userData.mood = (color) => { eyeMat.color.set(color); eyeMat.emissive.set(color); belly.material.color.set(color); belly.material.emissive.set(color); halo.material.color.set(color); };
  return g;
}

/** A faceless mannequin: role is shown by color and prop, never by features. */
export function person({ suit = 0x3b6aa0, accent = C.gold, prop = 'lanyard' } = {}) {
  const g = new THREE.Group();
  const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.4, 0.95, 8, 18), mat(suit, { roughness: 0.6 })); body.position.y = 1.05;
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.33, 22, 16), mat(0xe6edf6, { roughness: 0.45 })); head.position.y = 2.05;
  const sash = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.9, 0.06), mat(accent, { roughness: 0.4 })); sash.position.set(0, 1.2, 0.4); sash.rotation.z = 0.1;
  g.add(body, head, sash);
  if (prop === 'case') { const c = slab(0.55, 0.4, 0.18, 0.05, mat(0x5a3b22, { roughness: 0.6 })); c.position.set(0.6, 0.45, 0.1); g.add(c); }
  if (prop === 'clip') { const c = slab(0.4, 0.55, 0.05, 0.04, mat(C.paper)); c.position.set(0.55, 1.15, 0.28); c.rotation.y = -0.4; g.add(c); }
  if (prop === 'hood') { const h = new THREE.Mesh(new THREE.SphereGeometry(0.4, 18, 12, 0, Math.PI * 2, 0, Math.PI * 0.62), mat(suit, { roughness: 0.8 })); h.position.y = 2.08; g.add(h); }
  g.add(shadowBlob(0.8, 0.5));
  g.userData.bob = { body, head };
  return g;
}

// ------------------------------------------------------------- set pieces

export function platform(radius, color = C.gold, label) {
  const g = new THREE.Group();
  const disc = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius + 0.4, 0.36, 64), mat(0x0f2036, { roughness: 0.9 })); disc.position.y = -0.18;
  // The top is printed: a soft radial wash with fine rings, so it reads as a floor, not a flat disc.
  const c = document.createElement('canvas'); c.width = c.height = 512; const cg = c.getContext('2d');
  const wash = cg.createRadialGradient(256, 256, 10, 256, 256, 256); wash.addColorStop(0, '#1d3d63'); wash.addColorStop(0.7, '#142c49'); wash.addColorStop(1, '#0f2036');
  cg.fillStyle = wash; cg.fillRect(0, 0, 512, 512); cg.strokeStyle = 'rgba(160,200,255,.13)'; cg.lineWidth = 2;
  for (const r of [60, 120, 180, 235]) { cg.beginPath(); cg.arc(256, 256, r, 0, 7); cg.stroke(); }
  for (let i = 0; i < 72; i++) { const a = (i / 72) * Math.PI * 2; cg.beginPath(); cg.moveTo(256 + Math.cos(a) * 240, 256 + Math.sin(a) * 240); cg.lineTo(256 + Math.cos(a) * 252, 256 + Math.sin(a) * 252); cg.stroke(); }
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 4;
  const top = new THREE.Mesh(new THREE.CircleGeometry(radius, 96), new THREE.MeshBasicMaterial({ map: tex })); top.rotation.x = -Math.PI / 2; top.position.y = 0.005;
  const rim = new THREE.Mesh(new THREE.TorusGeometry(radius, 0.07, 8, 96), emissive(color, 1.4)); rim.rotation.x = Math.PI / 2; rim.position.y = 0.01;
  const inner = new THREE.Mesh(new THREE.RingGeometry(radius * 0.55, radius * 0.56, 96), basic(color, 0.3)); inner.rotation.x = -Math.PI / 2; inner.position.y = 0.012;
  // A flat glow on the floor. A camera-facing sprite here would be sliced by the floor plane.
  const halo = new THREE.Mesh(new THREE.CircleGeometry(radius * 1.15, 64), new THREE.MeshBasicMaterial({ map: glowTexture(), color, transparent: true, opacity: 0.2, depthWrite: false, blending: THREE.AdditiveBlending }));
  halo.rotation.x = -Math.PI / 2; halo.position.y = 0.02;
  g.add(disc, top, rim, inner, halo);
  g.userData = { rim, inner, halo };
  return g;
}

export function gate({ color = C.cyan, width = 3.6, height = 3.8 } = {}) {
  const g = new THREE.Group();
  const pillarMat = mat(C.slate, { roughness: 0.5 });
  const lamp = emissive(color, 1.8);
  const pillars = [-1, 1].map((s) => { const p = slab(0.42, height, 0.5, 0.1, pillarMat); p.position.set(s * (width / 2 + 0.21), height / 2, 0); return p; });
  const bar = slab(width + 1.2, 0.42, 0.55, 0.1, pillarMat); bar.position.y = height + 0.2;
  const tops = [-1, 1].map((s) => { const t = new THREE.Mesh(new THREE.SphereGeometry(0.15, 14, 10), lamp); t.position.set(s * (width / 2 + 0.21), height + 0.55, 0); return t; });
  const curtainMat = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.18, side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending });
  const curtain = new THREE.Mesh(new THREE.PlaneGeometry(width, height), curtainMat); curtain.position.y = height / 2;
  const ring = new THREE.Mesh(new THREE.TorusGeometry(Math.min(width, height) * 0.38, 0.04, 8, 64), basic(color, 0)); ring.position.y = height / 2;
  g.add(...pillars, bar, ...tops, curtain, ring, shadowBlob(2.4, 0.4));
  g.userData = { curtainMat, lamp, ring, color, tops, height, width };
  g.userData.set = (hex) => { curtainMat.color.set(hex); lamp.color.set(hex); lamp.emissive.set(hex); ring.material.color.set(hex); };
  return g;
}

export function vault({ color = C.blue, w = 5, h = 5.4, d = 3.2 } = {}) {
  const g = new THREE.Group();
  const box = new THREE.BoxGeometry(w, h, d);
  const glass = new THREE.Mesh(box, new THREE.MeshStandardMaterial({ color: 0x1d3a5c, transparent: true, opacity: 0.18, roughness: 0.1, metalness: 0.2, depthWrite: false }));
  glass.position.y = h / 2;
  const edges = new THREE.LineSegments(new THREE.EdgesGeometry(box), new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.9 }));
  edges.position.y = h / 2;
  const base = slab(w + 0.6, 0.3, d + 0.6, 0.1, mat(C.slate)); base.position.y = 0.15;
  const door = new THREE.Mesh(new THREE.PlaneGeometry(w - 0.1, h - 0.1), new THREE.MeshStandardMaterial({ color: 0x24456b, transparent: true, opacity: 0.55, roughness: 0.25, metalness: 0.3, side: THREE.DoubleSide, depthWrite: false }));
  door.position.set(0, h / 2, d / 2 + 0.02);
  g.add(base, glass, edges, door, shadowBlob(3.4, 0.4));
  g.userData = { door, edges, h, w, d };
  return g;
}

export function packet(color = C.cyan, size = 0.28) {
  const g = new THREE.Group();
  const core = new THREE.Mesh(new THREE.OctahedronGeometry(size, 0), emissive(color, 2.2));
  const halo = glowSprite(color, size * 7, 0.65);
  g.add(core, halo);
  g.userData = { core, halo, set(hex) { core.material.color.set(hex); core.material.emissive.set(hex); halo.material.color.set(hex); } };
  return g;
}

/** A document sheet: paper with a header band and a few lines. */
export function sheet({ w = 2.2, h = 2.8, title = '', lines = [], tone = C.cyan, stamp = null, dashed = false } = {}) {
  return panel(w, h, (g, W, H) => {
    g.clearRect(0, 0, W, H);
    g.fillStyle = '#eef3f9'; roundRect(g, 4, 4, W - 8, H - 8, W * 0.04); g.fill();
    g.fillStyle = css(tone); roundRect(g, 4, 4, W - 8, H * 0.17, W * 0.04); g.fill(); g.fillRect(4, H * 0.09, W - 8, H * 0.08);
    g.fillStyle = '#0d1b2e'; g.font = `800 ${W * 0.098}px ${FONT}`; g.textBaseline = 'middle';
    g.fillText(title, W * 0.07, H * 0.095);
    g.font = `600 ${W * 0.088}px ${FONT}`; g.fillStyle = '#26405c'; g.textBaseline = 'alphabetic';
    let y = H * 0.33;
    for (const line of lines) y = wrap(g, line, W * 0.07, y, W * 0.86, W * 0.118, 5) + H * 0.01;
    if (dashed) { g.setLineDash([12, 10]); g.strokeStyle = '#ff6b6b'; g.lineWidth = 6; roundRect(g, 10, 10, W - 20, H - 20, W * 0.04); g.stroke(); }
    if (stamp) {
      g.save(); g.translate(W * 0.55, H * 0.82); g.rotate(-0.28); g.strokeStyle = css(stamp.color); g.fillStyle = css(stamp.color); g.lineWidth = 7;
      g.font = `800 ${W * 0.115}px ${FONT}`; const tw = g.measureText(stamp.text).width;
      roundRect(g, -tw / 2 - 18, -W * 0.09, tw + 36, W * 0.15, 10); g.stroke(); g.textAlign = 'center'; g.fillText(stamp.text, 0, W * 0.02); g.restore();
    }
  });
}

/** A big stamp that slams into place. */
export function stampMesh(text, color, { w = 3.6, h = 1.1 } = {}) {
  const p = panel(w, h, (g, W, H) => {
    g.clearRect(0, 0, W, H); g.strokeStyle = css(color); g.fillStyle = css(color); g.lineWidth = H * 0.07;
    roundRect(g, H * 0.05, H * 0.05, W - H * 0.1, H * 0.9, H * 0.18); g.stroke();
    g.font = `800 ${H * 0.5}px ${FONT}`; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(text, W / 2, H * 0.53);
  }, { ppu: 180 });
  p.material.depthTest = false; p.renderOrder = 10;
  return p;
}

export function ringPulse(scope, parent, position, color, { from = 0.3, to = 3, seconds = 0.9, rotY = 0 } = {}) {
  const m = new THREE.Mesh(new THREE.RingGeometry(0.92, 1, 64), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.9, side: THREE.DoubleSide, depthWrite: false }));
  m.position.copy(position); m.rotation.y = rotY; m.scale.setScalar(from); parent.add(m);
  const done = scope.tween(seconds, (k) => { m.scale.setScalar(from + (to - from) * k); m.material.opacity = 0.9 * (1 - k); }, ease.out);
  done.catch(() => {}).then(() => { parent.remove(m); m.geometry.dispose(); m.material.dispose(); });
  return done;
}

/** Burst of small shards, for blocks and shredded proposals. */
export function shards(scope, parent, position, color, count = 26, spread = 2.4) {
  const group = new THREE.Group(); group.position.copy(position); parent.add(group);
  const items = [];
  for (let i = 0; i < count; i++) {
    const m = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.12, 0.03), basic(color, 1));
    const v = new THREE.Vector3((Math.random() - 0.5) * spread, Math.random() * spread * 0.8, (Math.random() - 0.5) * spread);
    group.add(m); items.push({ m, v, spin: (Math.random() - 0.5) * 8 });
  }
  const done = scope.tween(1.1, (k) => {
    for (const it of items) { it.m.position.copy(it.v).multiplyScalar(k); it.m.position.y -= k * k * 1.6; it.m.rotation.z = it.spin * k; it.m.material.opacity = 1 - k; }
  }, ease.out);
  done.catch(() => {}).then(() => { parent.remove(group); items.forEach((it) => { it.m.geometry.dispose(); it.m.material.dispose(); }); });
  return done;
}

/** Ambient floating specks, for depth. */
export function dust(count = 260, box = [130, 24, 70], center = [45, 9, 0]) {
  const pos = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) { pos[i * 3] = center[0] + (Math.random() - 0.5) * box[0]; pos[i * 3 + 1] = center[1] + (Math.random() - 0.5) * box[1]; pos[i * 3 + 2] = center[2] + (Math.random() - 0.5) * box[2]; }
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  const pts = new THREE.Points(g, new THREE.PointsMaterial({ color: 0x9ec5ff, size: 0.12, transparent: true, opacity: 0.5, depthWrite: false, map: glowTexture(), blending: THREE.AdditiveBlending }));
  pts.userData.tick = (t) => { pts.position.y = Math.sin(t * 0.07) * 0.6; pts.rotation.y = Math.sin(t * 0.03) * 0.03; };
  return pts;
}

/** A thin line between two points, for links and callout leaders. */
export function link(a, b, color = C.gold, opacity = 0.4) {
  const g = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(...a), new THREE.Vector3(...b)]);
  return new THREE.Line(g, new THREE.LineBasicMaterial({ color, transparent: true, opacity }));
}
