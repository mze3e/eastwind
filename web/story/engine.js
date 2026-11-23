// Engine: renderer, camera rig, cancellable animation scopes, and a DOM label layer.
// Nothing here knows about the story. It is the stage the chapters are built on.
import * as THREE from '../vendor/three/three.module.js';

export { THREE };

export const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

export class Cancelled extends Error {}

export const ease = {
  linear: (k) => k,
  inOut: (k) => (k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2),
  out: (k) => 1 - Math.pow(1 - k, 3),
  in: (k) => k * k * k,
  back: (k) => { const c = 1.9; return 1 + (c + 1) * Math.pow(k - 1, 3) + c * Math.pow(k - 1, 2); },
  bounce: (k) => {
    const n = 7.5625, d = 2.75;
    if (k < 1 / d) return n * k * k;
    if (k < 2 / d) return n * (k -= 1.5 / d) * k + 0.75;
    if (k < 2.5 / d) return n * (k -= 2.25 / d) * k + 0.9375;
    return n * (k -= 2.625 / d) * k + 0.984375;
  },
};

/**
 * A scope owns the animations of one step. Cancelling it rejects everything
 * still pending, so jumping to another step never lets old choreography run.
 */
export class Scope {
  constructor(engine) { this.engine = engine; this.dead = false; this.items = new Set(); this.cleanups = []; }

  tween(seconds, update, easing = ease.inOut) {
    const promise = new Promise((resolve, reject) => {
      if (this.dead) return reject(new Cancelled());
      const item = { t: 0, dur: Math.max(0.0001, reducedMotion ? seconds * 0.12 : seconds), update, easing, resolve, reject };
      this.items.add(item);
      this.engine.tweens.add(item);
    });
    // Cancelling a step rejects whatever is still running. Callers that await it get the rejection
    // (and stop); callers that fire and forget must not raise an unhandled rejection.
    promise.catch(() => {});
    return promise;
  }

  wait(seconds) { return this.tween(seconds, () => {}, ease.linear); }

  /** Run `fn` every frame until the scope is cancelled. */
  frame(fn) { const f = (t, dt) => fn(t, dt); this.engine.frameFns.add(f); this.cleanups.push(() => this.engine.frameFns.delete(f)); }

  onCancel(fn) { this.cleanups.push(fn); }

  /** Animate any numeric properties of an object. */
  to(target, props, seconds, easing = ease.inOut) {
    const from = {}; for (const k of Object.keys(props)) from[k] = target[k];
    return this.tween(seconds, (k) => { for (const key of Object.keys(props)) target[key] = from[key] + (props[key] - from[key]) * k; }, easing);
  }

  move(object, to, seconds, easing = ease.inOut) {
    const a = object.position.clone(); const b = new THREE.Vector3(...to);
    return this.tween(seconds, (k) => object.position.lerpVectors(a, b, k), easing);
  }

  /** Move along a gentle arc: a straight line lifted by `lift` at the middle. */
  glide(object, to, seconds, lift = 0.6, easing = ease.inOut) {
    const a = object.position.clone(); const b = new THREE.Vector3(...to);
    return this.tween(seconds, (k) => { object.position.lerpVectors(a, b, k); object.position.y += Math.sin(k * Math.PI) * lift; }, easing);
  }

  scale(object, to, seconds, easing = ease.out) {
    const a = object.scale.clone(); const b = new THREE.Vector3(to, to, to);
    return this.tween(seconds, (k) => object.scale.lerpVectors(a, b, k), easing);
  }

  fade(material, to, seconds) { const a = material.opacity; return this.tween(seconds, (k) => { material.opacity = a + (to - a) * k; }, ease.linear); }

  color(material, to, seconds = 0.35) {
    const a = material.color.clone(); const b = new THREE.Color(to);
    return this.tween(seconds, (k) => material.color.lerpColors(a, b, k), ease.linear);
  }

  cancel() {
    this.dead = true;
    for (const item of this.items) { this.engine.tweens.delete(item); item.reject(new Cancelled()); }
    this.items.clear();
    for (const fn of this.cleanups) fn();
    this.cleanups = [];
  }

  /** Run choreography and swallow only cancellation. */
  async run(fn) {
    try { await fn(this); } catch (error) { if (!(error instanceof Cancelled)) throw error; }
  }
}

/** HTML tags pinned to 3D points. Text stays crisp and selectable at any size. */
export class Labels {
  constructor(root, camera) { this.root = root; this.camera = camera; this.items = new Set(); this.tmp = new THREE.Vector3(); }

  add(html, anchor, { tone = '', offset = [0, 0, 0], cls = '', delay = 0, persistent = false, align = 'top' } = {}) {
    const el = document.createElement('div');
    el.className = `tag ${tone} ${cls}`.trim();
    el.innerHTML = html;
    el.style.opacity = '0';
    this.root.appendChild(el);
    const item = { el, anchor, align, offset: new THREE.Vector3(...offset), persistent, born: performance.now() + delay * 1000, shown: false };
    this.items.add(item);
    return item;
  }

  remove(item) { item.el.remove(); this.items.delete(item); }

  clear(includePersistent = false) {
    for (const item of [...this.items]) if (includePersistent || !item.persistent) this.remove(item);
  }

  update(width, height, shiftX = 0) {
    for (const item of this.items) {
      const world = this.tmp;
      if (item.anchor.isObject3D) item.anchor.getWorldPosition(world); else world.copy(item.anchor);
      world.add(item.offset);
      world.project(this.camera);
      // A label whose object has been taken out of the scene would otherwise sit at that object's last local position.
      const gone = item.anchor.isObject3D && !item.anchor.isScene && !item.anchor.parent;
      const behind = gone || world.z > 1 || world.z < -1;
      const x = (world.x * 0.5 + 0.5) * width;
      const y = (-world.y * 0.5 + 0.5) * height;
      const ready = performance.now() >= item.born;
      const shift = { top: '-50%, -100%', bottom: '-50%, 0', left: '-100%, -50%', right: '0, -50%', center: '-50%, -50%' }[item.align] || '-50%, -100%';
      item.el.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px) translate(${shift})`;
      item.el.style.opacity = behind || !ready ? '0' : '1';
    }
  }
}

export class Stage {
  constructor(canvas, labelRoot) {
    this.canvas = canvas;
    this.tweens = new Set();
    this.frameFns = new Set();
    this.last = performance.now();
    this.time = 0;
    this.paused = false;
    this.shiftX = 0;
    this.shiftTarget = 0;
    this.speed = 1;   // a test hook: automated checks run the choreography faster
    this.wide = false;
    this.driftTarget = 1; this.driftNow = 1;   // how much the camera sways: a view can ask for none (see `view`)
    this.shell = 'side';       // 'side': caption panel at the left. 'sheet': under the picture. 'rail': a left rail on short windows. app.js decides.
    this.insetTop = 0; this.insetBottom = 0; this.insetLeft = 0; this.shiftY = 0;
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0b1626);
    this.scene.fog = new THREE.Fog(0x0b1626, 90, 300);
    // The near plane is as far out as the scenes allow (nothing is nearer than about 11 units): depth precision falls
    // with distance and rises with the near plane, and the overview is seen from 100 units or more.
    this.camera = new THREE.PerspectiveCamera(42, 1, 1, 500);
    this.lookTarget = new THREE.Vector3(0, 1.5, 0);
    this.camBase = new THREE.Vector3(0, 8, 18);
    this.camera.position.copy(this.camBase);
    this.flight = null;
    this.labels = new Labels(labelRoot, this.camera);
    this.hasGL = this._initRenderer();
    this.resize();
    window.addEventListener('resize', () => this.resize());
    document.addEventListener('visibilitychange', () => { this.paused = document.hidden; if (!this.paused) this.last = performance.now(); });
    this._loop = this._loop.bind(this);
    requestAnimationFrame(this._loop);
  }

  _initRenderer() {
    try {
      this.renderer = new THREE.WebGLRenderer({ canvas: this.canvas, antialias: true, powerPreference: 'high-performance' });
    } catch (error) {
      this.renderer = null;
      return false;
    }
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;
    return true;
  }

  scope() { return new Scope(this); }

  /** Title-card steps use the full width; the others leave room for the caption panel. */
  setWide(wide) { this.wide = wide; this.shiftTarget = wide && this.shell === 'side' ? 0 : this.shiftDefault; }

  /**
   * On narrow windows the caption is a sheet along the bottom, and on short ones a rail at the left.
   * `top`, `bottom` and `left` are the pixels covered by the bars and the caption, so the picture is
   * framed in what is left between them. A title card keeps the caption, so it never gets the full width.
   */
  setShell(shell, { top = 0, bottom = 0, left = 0 } = {}) {
    if (shell === this.shell && top === this.insetTop && bottom === this.insetBottom && left === this.insetLeft) return;
    this.shell = shell; this.insetTop = top; this.insetBottom = bottom; this.insetLeft = left;
    this.resize();
  }

  resize() {
    const w = Math.max(1, window.innerWidth), h = Math.max(1, window.innerHeight);
    this.width = w; this.height = h;
    this.camera.aspect = w / h;
    // Keep the subject clear of the caption panel on wide screens, or above the sheet on small ones.
    const compact = this.shell !== 'side';
    this.shiftDefault = compact ? this.insetLeft / 2 : Math.min(240, w * 0.17);
    this.shiftTarget = this.wide && !compact ? 0 : this.shiftDefault;
    this.shiftX = this.shiftTarget;
    this.shiftY = compact ? (this.insetTop - this.insetBottom) / 2 : 0;   // the picture moves down by this
    this.camera.setViewOffset(w, h, -this.shiftX, -this.shiftY, w, h);
    if (this.renderer) this.renderer.setSize(w, h, false);
    if (this.currentView) { const c = this.fitView(this.currentView); this.snap(c.pos, c.look); }
  }

  /**
   * Work out where the camera must stand so `cam.fit` world units either side of the
   * look target fit in the part of the screen the caption panel leaves free. A taller or
   * narrower viewport simply stands further back.
   */
  fitView(cam) {
    const p = new THREE.Vector3(...cam.pos), l = new THREE.Vector3(...cam.look);
    const dir = p.clone().sub(l); const d0 = dir.length(); dir.normalize();
    const compact = this.shell !== 'side';
    const side = !compact && !this.wide;
    const freeLeft = side ? Math.min(460, this.width * 0.38) + 40 : this.insetLeft;
    const free = Math.max(0.2, (this.width - freeLeft) / this.width);
    const freeHeight = compact ? Math.max(0.2, (this.height - this.insetTop - this.insetBottom) / this.height) : 1;
    const tanHalf = Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2));
    // The scenes are about twice as wide as they are tall. Width decides, unless the free part is very wide and short.
    const need = cam.fit ? Math.max(cam.fit / (tanHalf * this.camera.aspect * free), (cam.fit * 0.5) / (tanHalf * freeHeight)) : 0;
    // `maxDist` lets a very wide scene be cropped on a narrow screen instead of shrinking into the fog.
    return { pos: l.clone().addScaledVector(dir, Math.max(d0, Math.min(need, cam.maxDist ?? Infinity))).toArray(), look: cam.look };
  }

  /** Go to a camera preset, fitted to this viewport. Re-fitted on resize. */
  view(cam, { snap = false } = {}) {
    this.currentView = cam;
    this.driftTarget = cam.drift ?? 1;           // a far overview is still: thin lines and tiny points crawl when the camera sways
    if (snap) this.driftNow = this.driftTarget;
    const c = this.fitView(cam);
    if (snap) { this.snap(c.pos, c.look); return Promise.resolve(); }
    return this.fly(c.pos, c.look, cam.dur ?? 2.2, cam.arc ?? 2);
  }

  /** Glide the camera. `arc` lifts it mid-flight for a walkthrough feel. */
  fly(pos, look, seconds = 1.8, arc = 0) {
    if (reducedMotion) { this.snap(pos, look); return Promise.resolve(); }   // no gliding for people who ask for less motion
    if (this.flightScope) this.flightScope.cancel();
    const scope = this.flightScope = this.scope();
    const p0 = this.camBase.clone(), l0 = this.lookTarget.clone();
    const p1 = new THREE.Vector3(...pos), l1 = new THREE.Vector3(...look);
    return scope.run((s) => s.tween(seconds, (k) => {
      this.camBase.lerpVectors(p0, p1, k);
      this.camBase.y += Math.sin(k * Math.PI) * arc;
      this.lookTarget.lerpVectors(l0, l1, k);
    }, ease.inOut));
  }

  snap(pos, look) { if (this.flightScope) this.flightScope.cancel(); this.camBase.set(...pos); this.lookTarget.set(...look); }

  _loop() {
    requestAnimationFrame(this._loop);
    if (this.paused) return;
    const now = performance.now();
    const dt = Math.min((now - this.last) / 1000, 0.1) * this.speed;
    this.last = now;
    this.time += dt;
    for (const item of [...this.tweens]) {
      item.t += dt;
      const k = Math.min(1, item.t / item.dur);
      item.update(item.easing(k));
      if (k >= 1) { this.tweens.delete(item); item.resolve(); }
    }
    for (const fn of this.frameFns) fn(this.time, dt);
    if (Math.abs(this.shiftTarget - this.shiftX) > 0.4) {
      this.shiftX += (this.shiftTarget - this.shiftX) * Math.min(1, dt * 4);
      this.camera.setViewOffset(this.width, this.height, -this.shiftX, -this.shiftY, this.width, this.height);
    }
    this.driftNow += (this.driftTarget - this.driftNow) * Math.min(1, dt * 2);
    const drift = reducedMotion ? 0 : this.driftNow;
    this.camera.position.set(
      this.camBase.x + Math.sin(this.time * 0.23) * 0.35 * drift,
      this.camBase.y + Math.sin(this.time * 0.31) * 0.18 * drift,
      this.camBase.z);
    this.camera.lookAt(this.lookTarget);
    if (this.renderer) this.renderer.render(this.scene, this.camera);
    this.labels.update(this.width, this.height, 0);
  }
}
