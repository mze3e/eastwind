// Chapter 5, BREAK: what if the record keeper goes down? The bank chose in advance:
// refuse everything, or carry on only with a local model and nothing that names a client.
import { THREE, ease, reducedMotion } from './engine.js';
import {
  C, css, FONT, robot, person, platform, gate, packet, panel, stampMesh, icon, slab, roundRect, glowSprite,
  ringPulse, shards, shadowBlob, link, basic, emissive, mat,
} from './kit.js';
import { X } from './world.js';

const ROT = 0.96;
const ASKER = new THREE.Vector3(-6.2, 0, 1.0);
const GATE_AT = new THREE.Vector3(-2.4, 0, 0);
const LOCAL_AT = new THREE.Vector3(2.0, 0, 2.0);
const RACK_AT = new THREE.Vector3(6.6, 0, -0.8);
const CLOUD_AT = new THREE.Vector3(1.4, 5.6, -6.0);

export function buildBreak(ctx) {
  const { stage, data } = ctx;
  const x0 = X.break;
  const out = data.outage;
  const group = new THREE.Group(); group.position.x = x0; stage.scene.add(group);
  const temp = new THREE.Group(); group.add(temp);
  let tags = [];
  let downTag = null;   // the 'record keeper down' label, replaced once the keeper is back
  const say = (html, anchor, opts) => { const t = ctx.tag(html, anchor, opts); tags.push(t); return t; };
  const at = (x, y, z = 0) => new THREE.Vector3(x0 + x, y, z);
  const clearTemp = () => { for (const c of temp.children.slice()) temp.remove(c); };
  const clearTags = () => { for (const t of tags) ctx.labels.remove(t); tags = []; };

  // ---------------------------------------------------------------- the cast
  const asker = person({ suit: 0x3b6aa0, accent: C.gold, prop: 'case' }); asker.position.copy(ASKER); asker.rotation.y = 0.95; group.add(asker);
  const pedestal = platform(1.9, C.bad); pedestal.position.copy(ASKER); group.add(pedestal);
  const gt = gate({ color: C.cyan, width: 3.4, height: 3.8 }); gt.position.copy(GATE_AT); gt.rotation.y = ROT; group.add(gt);
  const tone = { idle: C.cyan, ok: C.good, bad: C.bad, wait: C.amber };
  const setGate = (t) => gt.userData.set(tone[t]);
  const gateCentre = () => new THREE.Vector3(GATE_AT.x, 2.0, GATE_AT.z);

  // the local model: a small robot inside the bank
  const local = robot({ accent: C.good }); local.scale.setScalar(0.72); local.position.copy(LOCAL_AT); group.add(local);
  const localPad = platform(1.5, C.good); localPad.position.copy(LOCAL_AT); group.add(localPad);

  // the outside provider
  const cloud = new THREE.Group(); cloud.position.copy(CLOUD_AT); group.add(cloud);
  const cloudMat = new THREE.MeshStandardMaterial({ color: 0xdfe9f7, roughness: 0.9, emissive: 0x335577, emissiveIntensity: 0.4 });
  [[0, 0, 0, 1.2], [1.2, -0.2, 0.2, 0.9], [-1.2, -0.25, 0, 0.9], [0.5, 0.65, 0, 0.8], [-0.6, 0.5, 0.3, 0.7]]
    .forEach(([x, y, z, r]) => { const m = new THREE.Mesh(new THREE.SphereGeometry(r, 18, 14), cloudMat); m.position.set(x, y, z); cloud.add(m); });
  stage.frameFns.add((t) => { if (!reducedMotion) cloud.position.y = CLOUD_AT.y + Math.sin(t * 0.8) * 0.12; });

  // the record keeper: a rack of lamps that can lose power
  const rack = new THREE.Group(); rack.position.copy(RACK_AT); rack.rotation.y = -0.35; group.add(rack);
  rack.add(slab(2.4, 5.2, 1.7, 0.16, mat(C.slate, { roughness: 0.5 })), shadowBlob(2.2, 0.45));
  rack.children[0].position.y = 2.6;
  const lamps = [];
  for (let i = 0; i < 9; i++) {
    const m = emissive(C.good, 1.4);
    const bar = slab(1.8, 0.2, 0.12, 0.05, m); bar.position.set(0, 0.9 + i * 0.46, 0.9); rack.add(bar); lamps.push(m);
  }
  const rackSign = panel(2.9, 0.7, (g, W, H) => {
    g.clearRect(0, 0, W, H); g.fillStyle = 'rgba(8,16,28,.92)'; roundRect(g, 2, 2, W - 4, H - 4, H * 0.25); g.fill();
    g.fillStyle = css(C.blue); g.font = `800 ${H * 0.42}px ${FONT}`; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText('RECORD KEEPER', W / 2, H * 0.52);
  }, { ppu: 150 });
  rackSign.position.set(0, 5.75, 0.95); rack.add(rackSign);
  const cable = new THREE.Mesh(new THREE.BoxGeometry(5.2, 0.09, 0.09), basic(C.cyan, 0.7));
  cable.position.set(GATE_AT.x + 3.4, 0.35, 0); group.add(cable);
  const power = (k, colour = C.good) => {                       // 1 = on, 0 = off
    for (const m of lamps) { m.color.set(k > 0.05 ? colour : 0x2a3a4e); m.emissive.set(k > 0.05 ? colour : 0x000000); m.emissiveIntensity = 1.4 * k; }
    cable.material.color.set(k > 0.05 ? C.cyan : C.bad); cable.material.opacity = k > 0.05 ? 0.7 : 0.9;
  };

  // ---------------------------------------------------------------- helpers
  const hand = () => new THREE.Vector3(ASKER.x + 0.7, 1.8, ASKER.z + 0.1);
  const counters = (passed) => ctx.setCounters([{ label: 'Record keeper', value: passed === null ? 'Working' : 'Down' }, { label: 'Passed on', value: passed ?? 0 }]);
  const band = (text, colour) => panel(3.6, 0.6, (g, W, H) => {
    g.clearRect(0, 0, W, H); g.fillStyle = css(colour); roundRect(g, 2, 2, W - 4, H - 4, H * 0.3); g.fill();
    g.fillStyle = '#0b1626'; g.font = `800 ${H * 0.46}px ${FONT}`; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(text, W / 2, H * 0.54);
  }, { ppu: 150 });

  function reset() {
    clearTemp(); clearTags(); setGate('idle'); power(1); local.userData.mood(C.good); asker.visible = true;
  }

  async function powerCut(s) {
    ctx.flash('#ff6b6b');
    for (let i = 0; i < 4; i++) { power(i % 2 ? 1 : 0.3, i % 2 ? C.good : C.amber); await s.wait(0.09); }
    power(0);
    shards(s, temp, new THREE.Vector3(GATE_AT.x + 3.4, 0.4, 0.2), C.bad, 22, 1.6);
    downTag = say('<b>Record keeper down</b><small>decisions cannot be written</small>', at(RACK_AT.x, 7.2), { tone: 'bad', cls: 'big', delay: 0.1 });
    counters(0);
    await s.wait(0.5);
  }

  async function ask(s, { chip = null } = {}) {
    const p = packet(C.cyan, 0.3); p.position.copy(hand()); temp.add(p);
    if (chip) {
      const c = panel(1.8, 0.4, (g, W, H) => {
        g.clearRect(0, 0, W, H); g.fillStyle = 'rgba(8,16,28,.92)'; roundRect(g, 2, 2, W - 4, H - 4, H * 0.3); g.fill();
        g.strokeStyle = css(C.amber); g.lineWidth = 3; g.stroke(); g.fillStyle = '#eaf1f9'; g.font = `700 ${H * 0.42}px ${FONT}`;
        g.textBaseline = 'middle'; g.fillText(chip, H * 0.3, H * 0.52);
      }, { ppu: 160 });
      c.position.set(0, 0.7, 0); p.add(c);
    }
    await s.glide(p, [GATE_AT.x, 2.0, 0.7], 0.9, 0.5);
    setGate('wait'); ringPulse(s, temp, gateCentre(), C.amber, { rotY: ROT, to: 2.6 }).catch(() => {});
    await s.wait(0.7);
    return p;
  }

  async function refuse(s, p, label) {
    setGate('bad'); ctx.flash('#ff6b6b'); p.userData.set(C.bad);
    await s.glide(p, [ASKER.x + 0.7, 1.8, ASKER.z], 0.7, 0.3);
    shards(s, temp, p.position.clone(), C.bad); temp.remove(p);
    const st = stampMesh(label, C.bad, { w: 3.8 }); st.position.set(GATE_AT.x + 0.3, 3.4, 1.8); st.scale.setScalar(2.4); temp.add(st);
    await s.scale(st, 1, 0.45, ease.bounce);
  }

  // ---------------------------------------------------------------- the choices
  async function play(s, which) {
    reset();
    say('<b>Inside the bank</b>', at(ASKER.x, 4.5), { tone: 'gold' });
    say('<b>Outside provider</b>', at(CLOUD_AT.x, CLOUD_AT.y), { align: 'center' });
    await powerCut(s);

    if (which === 'strict') {
      const ribbon = band('STRICT MODE', C.bad); ribbon.position.set(GATE_AT.x, 5.0, 0.6); ribbon.rotation.y = ROT * 0.4; temp.add(ribbon);
      const p = await ask(s);
      await refuse(s, p, 'REFUSED');
      counters(out.strict.passed_on);
      say(`<b>Passed on: ${out.strict.passed_on}</b><small>no record, no action. Refused with status ${out.strict.status}.</small>`, at(GATE_AT.x + 0.6, 6.6), { tone: 'bad', cls: 'big', delay: 0.4 });
      return;
    }

    const ribbon = band('DEGRADED MODE', C.amber); ribbon.position.set(GATE_AT.x, 5.0, 0.6); ribbon.rotation.y = ROT * 0.4; temp.add(ribbon);

    if (which === 'local') {
      const p = await ask(s);
      setGate('ok'); ringPulse(s, temp, gateCentre(), C.good, { rotY: ROT, to: 2.8 }).catch(() => {});
      await s.glide(p, [LOCAL_AT.x - 0.8, 2.2, LOCAL_AT.z], 1.0, 0.6);
      temp.remove(p);
      local.userData.mood(C.cyan); ringPulse(s, temp, new THREE.Vector3(LOCAL_AT.x, 1.6, LOCAL_AT.z), C.cyan, { to: 2.2 }).catch(() => {});
      await s.wait(0.7);
      const reply = packet(C.good, 0.26); reply.position.set(LOCAL_AT.x - 0.8, 2.2, LOCAL_AT.z); temp.add(reply);
      await s.glide(reply, [ASKER.x + 0.8, 2.0, ASKER.z], 1.1, 0.7); temp.remove(reply);
      counters(out.local.passed_on);
      say(`<b>Passed on: ${out.local.passed_on}</b><small>a local model answered; nothing left the bank</small>`, at(GATE_AT.x + 0.6, 6.6), { tone: 'good', cls: 'big', delay: 0.2 });
      // the keeper comes back and the decision is written after the fact
      await s.wait(1.0);
      for (let i = 1; i <= 5; i++) { power(i / 5, C.good); await s.wait(0.18); }
      const memo = packet(C.blue, 0.2); memo.position.set(GATE_AT.x, 1.6, 0.4); temp.add(memo);
      await s.glide(memo, [RACK_AT.x - 1.4, 1.8, 0.6], 1.1, 0.5); temp.remove(memo);
      ctx.setCounters([{ label: 'Record keeper', value: 'Back' }, { label: 'Passed on', value: out.local.passed_on }]);
      if (downTag) ctx.labels.remove(downTag);
      say(`<b>Recorded afterwards</b><small>${out.chain_ok ? 'the record still checks out' : 'check the record'}</small>`, at(RACK_AT.x, 7.2), { tone: 'good', cls: 'big', delay: 0.2 });
      return;
    }

    if (which === 'remote') {
      const p = await ask(s);
      setGate('bad'); ctx.flash('#ff6b6b');
      await s.glide(p, [GATE_AT.x + 1.2, 3.2, -0.6], 0.6, 0.4);
      await s.glide(p, [ASKER.x + 0.7, 1.8, ASKER.z], 0.7, 0.3);
      shards(s, temp, p.position.clone(), C.bad); temp.remove(p);
      const st = stampMesh('REFUSED', C.bad, { w: 3.8 }); st.position.set(GATE_AT.x + 0.3, 3.4, 1.8); st.scale.setScalar(2.4); temp.add(st); await s.scale(st, 1, 0.45, ease.bounce);
      counters(out.remote.passed_on);
      say(`<b>Passed on: ${out.remote.passed_on}</b><small>degraded mode never goes outside</small>`, at(GATE_AT.x + 0.6, 6.6), { tone: 'bad', cls: 'big', delay: 0.4 });
      return;
    }

    // which === 'identifying'
    const p = await ask(s, { chip: 'A client’s name' });
    await refuse(s, p, 'REFUSED');
    counters(out.identifying.passed_on);
    say(`<b>Passed on: ${out.identifying.passed_on}</b><small>it names a client, so not even locally</small>`, at(GATE_AT.x + 0.6, 6.6), { tone: 'bad', cls: 'big', delay: 0.4 });
  }

  // ------------------------------------------------------------- interface
  const cam = { pos: [0.6, 5.6, 19.0], look: [0.6, 3.0, 0], dur: 2.4, arc: 3, fit: 9.8 };
  return {
    group,
    camera: () => ({ ...cam, pos: [x0 + cam.pos[0], cam.pos[1], cam.pos[2]], look: [x0 + cam.look[0], cam.look[1], cam.look[2]] }),
    async enter(id, step, s) {
      reset(); counters(null);
      say('<b>Inside the bank</b>', at(ASKER.x, 4.5), { tone: 'gold' });
      say('<b>Outside provider</b>', at(CLOUD_AT.x, CLOUD_AT.y), { align: 'center' });
      await s.wait(1.6);
      ctx.autoChoose(0);
    },
    async choose(id, choiceId, step, s) { return play(s, choiceId); },
  };
}
