// World: the ground, the path between stations, platforms, signs and ambient motion.
import { THREE, reducedMotion } from './engine.js';
import { C, platform, dust, packet, basic } from './kit.js';

/** Where each station sits along the path. */
export const X = { colleague: 0, know: 30, do: 60, prove: 90 };
export const ACCENT = { colleague: C.gold, know: C.cyan, do: C.amber, prove: C.blue };

export function buildWorld(ctx) {
  const { stage } = ctx;
  const scene = stage.scene;
  const group = new THREE.Group(); scene.add(group);

  scene.add(new THREE.HemisphereLight(0xaecbff, 0x0b1626, 1.05));
  const sun = new THREE.DirectionalLight(0xffffff, 1.5); sun.position.set(30, 40, 30); scene.add(sun);
  const rim = new THREE.DirectionalLight(0x6ea8ff, 0.7); rim.position.set(-20, 12, -30); scene.add(rim);
  const fill = new THREE.DirectionalLight(0xdbe8ff, 0.9); fill.position.set(0, 14, 60); scene.add(fill);

  const ground = new THREE.Mesh(new THREE.PlaneGeometry(1400, 800), new THREE.MeshStandardMaterial({ color: 0x0a1a2d, roughness: 1 }));
  ground.rotation.x = -Math.PI / 2; ground.position.set(45, -0.4, 0); group.add(ground);
  const grid = new THREE.GridHelper(900, 150, C.grid, C.grid);
  grid.material.transparent = true; grid.material.opacity = 0.16; grid.position.set(45, -0.38, 0); group.add(grid);

  // The path between stations, with data packets drifting along it.
  const path = new THREE.Mesh(new THREE.BoxGeometry(X.prove - X.colleague, 0.04, 1.2), basic(0x16314f, 0.9));
  path.position.set((X.prove + X.colleague) / 2, -0.3, 0); group.add(path);
  for (const s of [-0.6, 0.6]) {
    const l = new THREE.Mesh(new THREE.BoxGeometry(X.prove - X.colleague, 0.05, 0.05), basic(C.gold, 0.55));
    l.position.set((X.prove + X.colleague) / 2, -0.26, s); group.add(l);
  }
  const flow = [];
  for (let i = 0; i < 14; i++) { const p = packet([C.gold, C.cyan, C.amber, C.blue][i % 4], 0.12); p.userData.u = i / 14; group.add(p); flow.push(p); }
  stage.frameFns.add((t) => {
    if (reducedMotion) return;
    for (const p of flow) { const u = (p.userData.u + t * 0.018) % 1; p.position.set(X.colleague + u * (X.prove - X.colleague), -0.1 + Math.sin(t * 2 + p.userData.u * 9) * 0.08, 0); }
  });

  const platforms = {};
  for (const id of Object.keys(X)) {
    const r = id === 'know' ? 12.5 : 11;
    const p = platform(r, ACCENT[id]); p.position.set(X[id], 0, 0); group.add(p); platforms[id] = p;
  }

  const specks = dust(); group.add(specks);
  stage.frameFns.add((t) => specks.userData.tick(t));

  const mid = (X.prove + X.colleague) / 2;
  const overview = { pos: [mid, 54, 84], look: [mid, 0, 16], dur: 2.8, arc: 6, fit: 62 };
  const cams = {
    welcome: overview,
    recap: { pos: [mid, 54, 84], look: [mid, 0, 16], dur: 2.8, arc: 6, fit: 62 },
  };

  const lit = (id, on) => {
    const p = platforms[id];
    p.userData.halo.material.opacity = on ? 0.34 : 0.16;
    p.userData.rim.material.emissiveIntensity = on ? 2.4 : 1.1;
  };

  /** Light every platform for the overview steps, otherwise only the one in use. */
  const setActive = (chapter) => {
    const all = chapter === 'welcome' || chapter === 'recap';
    for (const id of Object.keys(X)) lit(id, all || id === chapter);
  };

  return {
    group, platforms, lit, setActive,
    camera: (stepId) => cams[stepId],
    enter(stepId, step, scope) {
      if (stepId === 'recap') {
        ctx.tag('<b>Know</b><small>only approved sources, only what a person may see</small>', new THREE.Vector3(X.know, 11, 0), { tone: 'good', cls: 'big wrap', delay: 0.6 });
        ctx.tag('<b>Do</b><small>the bank sets independence, people decide the big calls</small>', new THREE.Vector3(X.do, 11, 0), { tone: 'warn', cls: 'big wrap', delay: 1.0 });
        ctx.tag('<b>Prove</b><small>a sealed record anyone can check</small>', new THREE.Vector3(X.prove, 11, 0), { cls: 'big wrap', delay: 1.4 });
      }
      if (stepId === 'welcome') {
        ctx.tag('Meet the colleague', new THREE.Vector3(X.colleague, 7, 0), { tone: 'gold', cls: 'big', delay: 0.5 });
        ctx.tag('Know', new THREE.Vector3(X.know, 7, 0), { tone: 'good', cls: 'big', delay: 0.8 });
        ctx.tag('Do', new THREE.Vector3(X.do, 7, 0), { tone: 'warn', cls: 'big', delay: 1.1 });
        ctx.tag('Prove', new THREE.Vector3(X.prove, 7, 0), { cls: 'big', delay: 1.4 });
      }
    },
    choose() {},
    lit,
  };
}
