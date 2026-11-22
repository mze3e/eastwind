// Chapter 1: meet the colleague, and its passport (the PWM record).
import { THREE, ease, reducedMotion } from './engine.js';
import { C, css, FONT, robot, panel, roundRect, glowSprite, link, mat, emissive } from './kit.js';
import { X } from './world.js';

export function buildColleague(ctx) {
  const { stage } = ctx;
  const x0 = X.colleague;
  const group = new THREE.Group(); group.position.x = x0; stage.scene.add(group);
  const pwm = ctx.data.pwm, colleague = ctx.data.colleague;

  const bot = robot({ accent: C.cyan }); group.add(bot);
  stage.frameFns.add((t) => {
    const u = bot.userData;
    u.hover.position.y = u.baseY + (reducedMotion ? 0 : Math.sin(t * 1.6) * 0.1);
    if (!reducedMotion) { u.head.rotation.y = Math.sin(t * 0.7) * 0.18; u.arms[0].rotation.z = Math.sin(t * 1.3) * 0.04; }
    u.halo.material.opacity = 0.3 + (reducedMotion ? 0 : Math.sin(t * 2) * 0.06);
  });

  const leaders = new THREE.Group(); group.add(leaders);
  const passport = new THREE.Group(); passport.visible = false; group.add(passport);
  const cover = panel(3.4, 4.6, (g, W, H) => {
    g.clearRect(0, 0, W, H);
    const grad = g.createLinearGradient(0, 0, W, H); grad.addColorStop(0, '#16345a'); grad.addColorStop(1, '#0c2140');
    g.fillStyle = grad; roundRect(g, 4, 4, W - 8, H - 8, W * 0.05); g.fill();
    g.strokeStyle = css(C.gold); g.lineWidth = 5; roundRect(g, W * 0.05, W * 0.05, W * 0.9, H - W * 0.1, W * 0.035); g.stroke();
    g.textAlign = 'center'; g.fillStyle = css(C.gold);
    g.font = `800 ${W * 0.075}px ${FONT}`; g.fillText('PASSPORT', W / 2, H * 0.16);
    g.beginPath(); g.arc(W / 2, H * 0.38, W * 0.2, 0, 7); g.lineWidth = 6; g.stroke();
    g.beginPath(); g.arc(W / 2, H * 0.38, W * 0.12, 0, 7); g.stroke();
    g.font = `800 ${W * 0.12}px ${FONT}`; g.fillText('AI', W / 2, H * 0.4);
    g.fillStyle = '#eaf1f9'; g.font = `700 ${W * 0.075}px ${FONT}`; g.fillText(colleague.name, W / 2, H * 0.66);
    g.fillStyle = '#a9bbcf'; g.font = `500 ${W * 0.056}px ${FONT}`;
    g.fillText('Private Wealth Management', W / 2, H * 0.76); g.fillText('open standard (PWM)', W / 2, H * 0.82);
    g.fillStyle = css(C.gold); g.font = `700 ${W * 0.048}px ${FONT}`; g.fillText('ILLUSTRATIVE PROFILE', W / 2, H * 0.92);
  });
  passport.add(cover);

  // The passport's contents as a graph: hub and spokes, from the real PWM export.
  const graph = new THREE.Group(); graph.visible = false; group.add(graph);
  const nodes = [];
  const rings = { 0: [], 1: [], 2: [] };
  pwm.nodes.forEach((n) => rings[n.ring].push(n));
  const hubPos = new THREE.Vector3(0, 0, 0);
  const place = (list, radius, phase) => list.forEach((n, i) => {
    const a = phase + (i / list.length) * Math.PI * 2;
    n.pos = new THREE.Vector3(Math.cos(a) * radius * 1.25, Math.sin(a) * radius * 0.82, Math.sin(a * 2) * 0.8);
  });
  rings[0].forEach((n) => { n.pos = hubPos.clone(); });
  place(rings[1], 2.5, 0.3); place(rings[2], 4.2, 0.15);
  for (const n of pwm.nodes) {
    const size = 0.26 + Math.min(0.2, Math.log2(n.count + 1) * 0.05) + (n.ring === 0 ? 0.25 : 0);
    const colour = n.ring === 0 ? C.gold : n.ring === 1 ? C.cyan : C.blue;
    const mesh = new THREE.Mesh(new THREE.SphereGeometry(size, 24, 18), emissive(colour, 1.1));
    const halo = glowSprite(colour, size * 5, 0.5); mesh.add(halo);
    mesh.position.copy(n.pos); mesh.scale.setScalar(0.001); graph.add(mesh);
    const edge = n.ring === 0 ? null : link(hubPos.toArray(), n.pos.toArray(), colour, 0.35);
    if (edge) { edge.visible = false; graph.add(edge); }
    nodes.push({ n, mesh, edge });
  }
  graph.position.set(3.4, 3.3, 0);
  stage.frameFns.add((t) => { if (!reducedMotion && graph.visible) graph.rotation.y = Math.sin(t * 0.25) * 0.28; });

  const cams = {
    'colleague-hire': { pos: [0, 4.1, 13.5], look: [0, 2.3, 0], dur: 2.8, arc: 5, fit: 9.6 },
    'colleague-passport': { pos: [1.8, 5.2, 21], look: [1.8, 3.1, 0], dur: 2.2, arc: 2, fit: 9.6 },
  };

  const reset = () => {
    leaders.clear(); leaders.children.slice().forEach((c) => leaders.remove(c));
    passport.visible = false; graph.visible = false;
    for (const { mesh, edge } of nodes) { mesh.scale.setScalar(0.001); if (edge) edge.visible = false; }
    bot.visible = true; bot.position.set(0, 0, 0); bot.rotation.y = 0; bot.userData.mood(C.cyan);
  };

  async function wave(s) {
    const arm = bot.userData.arms[1];
    for (let i = 0; i < 2; i++) { await s.to(arm.rotation, { z: -2.3 }, 0.28, ease.out); await s.to(arm.rotation, { z: -1.6 }, 0.28, ease.inOut); }
    await s.to(arm.rotation, { z: 0 }, 0.4);
  }

  return {
    group,
    camera: (id) => {
      const c = cams[id] || cams['colleague-hire'];
      return { ...c, pos: [x0 + c.pos[0], c.pos[1], c.pos[2]], look: [x0 + c.look[0], c.look[1], c.look[2]] };
    },
    async enter(id, step, s) {
      reset();
      if (id === 'colleague-hire') {
        const anchors = [[-3.6, 5.1], [-4.1, 3.6], [-3.6, 2.1], [3.6, 5.1], [4.1, 3.6], [3.6, 2.1]];
        step.callouts.forEach(([k, v], i) => {
          const [ax, ay] = anchors[i];
          leaders.add(link([ax < 0 ? -0.5 : 0.5, 1.9, 0], [ax, ay, 0], C.gold, 0.45));
          ctx.tag(`<b>${k}</b><small>${v}</small>`, new THREE.Vector3(x0 + ax, ay, 0), { tone: 'gold', cls: 'wrap', delay: 0.5 + i * 0.35, align: ax < 0 ? 'left' : 'right' });
        });
        s.wait(0.3).then(() => wave(s)).catch(() => {});
      }
      if (id === 'colleague-passport') {
        bot.visible = false;
        passport.visible = true; passport.position.set(-7.0, 3.4, 0.5); passport.scale.setScalar(0.001);
        passport.rotation.y = 0.35;
        await s.scale(passport, 0.72, 0.7, ease.back);
        graph.visible = true;
        for (let i = 0; i < nodes.length; i++) {
          const { n, mesh, edge } = nodes[i];
          if (edge) edge.visible = true;
          s.scale(mesh, 1, 0.5, ease.back).catch(() => {});
          // Labels sit outside their node, away from the hub, so a dense graph stays readable.
          const dx = n.pos.x, dy = n.pos.y, horizontal = Math.abs(dx) > Math.abs(dy) * 0.9;
          const align = n.ring === 0 ? 'top' : horizontal ? (dx > 0 ? 'right' : 'left') : (dy > 0 ? 'top' : 'bottom');
          const off = n.ring === 0 ? [0, 0.7, 0] : horizontal ? [Math.sign(dx) * 0.5, 0, 0] : [0, Math.sign(dy) * 0.5, 0];
          ctx.tag(`${n.label}${n.count > 1 ? ` <b>${n.count}</b>` : ''}`, mesh, { offset: off, align, tone: n.ring === 0 ? 'gold' : '', delay: 0 });
          await s.wait(0.16);
        }
        // One tag for the verdict and the honesty note, above the passport and clear of the graph's labels.
        ctx.tag(`${pwm.conforms ? 'Passes the standard’s checks' : 'Does not conform'} <b>${pwm.triples} facts</b>`
          + '<small>Illustrative profile for this synthetic demo, not an attestation</small>',
          new THREE.Vector3(x0 - 7.0, 5.5, 0), { tone: pwm.conforms ? 'good' : 'bad', cls: 'wrap', delay: 0.2 });
      }
    },
    choose() {},
  };
}
