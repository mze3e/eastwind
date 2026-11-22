// Chapter 4, PROVE: what can we show? A chain of sealed records, a checker that walks
// it, an edit that breaks a seal, and a report that admits what it never recorded.
import { THREE, ease, reducedMotion } from './engine.js';
import {
  C, css, FONT, platform, panel, slab, stampMesh, icon, roundRect, fit, glowSprite, ringPulse,
  shards, link, basic, emissive, mat, packet,
} from './kit.js';
import { X } from './world.js';

const GROUP_COLOR = { decision: C.blue, work: C.violet, human: C.amber, privacy: C.cyan, setup: 0x7f93aa, final: C.good };
const GROUP_NAME = { decision: 'Decision', work: 'Work done', human: 'A person stepped in', privacy: 'Privacy check', setup: 'Setup', final: 'Final outcome' };
const PITCH = 0.82, ROW_Y = 2.0;

export function buildProve(ctx) {
  const { stage, data } = ctx;
  const x0 = X.prove;
  const group = new THREE.Group(); group.position.x = x0; stage.scene.add(group);
  const temp = new THREE.Group(); group.add(temp);
  let tags = [];
  const say = (html, anchor, opts) => { const t = ctx.tag(html, anchor, opts); tags.push(t); return t; };
  const at = (x, y, z = 0) => new THREE.Vector3(x0 + x, y, z);
  const clearTemp = () => { for (const c of temp.children.slice()) temp.remove(c); };
  const clearTags = () => { for (const t of tags) ctx.labels.remove(t); tags = []; };

  const chain = data.chain, win = chain.window, n = win.length;
  const tamperIdx = win.findIndex((e) => e.seq === chain.tamper.sequence);
  const xAt = (i) => (i - (n - 1) / 2) * PITCH;

  // ----------------------------------------------------------------- the rail
  const rail = slab(n * PITCH + 1.4, 0.16, 1.5, 0.06, mat(0x16314f, { roughness: 0.6 })); rail.position.set(0, ROW_Y - 0.9, 0); group.add(rail);
  const railGlow = new THREE.Mesh(new THREE.BoxGeometry(n * PITCH + 1.2, 0.04, 0.1), basic(C.blue, 0.6)); railGlow.position.set(0, ROW_Y - 0.8, 0.7); group.add(railGlow);
  const floor = platform(13.5, C.blue); group.add(floor);

  const blocks = [];
  win.forEach((e, i) => {
    const colour = GROUP_COLOR[e.group] || C.grey;
    const holder = new THREE.Group(); holder.position.set(xAt(i), ROW_Y, 0); group.add(holder);
    const body = slab(0.7, 1.05, 0.34, 0.08, mat(colour, { roughness: 0.35, emissive: colour, emissiveIntensity: 0.28 })); holder.add(body);
    const num = panel(0.7, 0.34, (g, W, H) => { g.clearRect(0, 0, W, H); g.fillStyle = '#0b1626'; g.textAlign = 'center'; g.textBaseline = 'middle'; fit(g, String(e.seq), W / 2, H * 0.52, W * 0.86, H * 0.62, 800); }, { ppu: 170 });
    num.position.set(0, 0.1, 0.2); holder.add(num);
    const lampMat = emissive(0x586b82, 0.6);
    const lamp = new THREE.Mesh(new THREE.SphereGeometry(0.11, 14, 10), lampMat); lamp.position.set(0, 0.68, 0.05); holder.add(lamp);
    const bond = i === 0 ? null : new THREE.Mesh(new THREE.BoxGeometry(PITCH - 0.7, 0.07, 0.07), basic(C.cyan, 0.55));
    if (bond) { bond.position.set(-PITCH / 2, 0, 0); holder.add(bond); }
    holder.scale.setScalar(0.001);
    blocks.push({ holder, body, lamp, lampMat, bond, e, colour });
  });

  // entries from before the window: a dim stack on the left, as a count and not as detail
  const older = new THREE.Group(); older.position.set(xAt(0) - 1.7, ROW_Y - 0.2, 0); group.add(older);
  for (let i = 0; i < 6; i++) { const b = slab(0.7, 0.9, 0.3, 0.07, mat(0x35506f, { roughness: 0.7 })); b.position.set(-i * 0.14, -i * 0.01, -i * 0.12); older.add(b); }

  // the checker's scan plane
  const scan = new THREE.Group(); scan.visible = false; group.add(scan);
  const scanBar = new THREE.Mesh(new THREE.PlaneGeometry(0.16, 3.6), basic(C.good, 0.85)); scanBar.position.y = ROW_Y; scan.add(scanBar);
  const scanGlow = glowSprite(C.good, 4.6, 0.5); scanGlow.position.y = ROW_Y; scan.add(scanGlow);
  const setScan = (hex) => { scanBar.material.color.set(hex); scanGlow.material.color.set(hex); };

  // the reconstruction report
  // Declared before the panel, because a panel draws itself as soon as it is made.
  const reportState = { shown: 0 };
  const reportRows = ctx.story.chapters.find((c) => c.id === 'prove').steps.find((s) => s.id === 'prove-rebuild').report;
  const reportSheet = panel(7.8, 4.6, (g, W, H) => drawReport(g, W, H), { ppu: 190 });
  reportSheet.position.set(0, 4.6, 0.6); reportSheet.visible = false; group.add(reportSheet);
  function drawReport(g, W, H) {
    g.clearRect(0, 0, W, H);
    g.fillStyle = '#eef3f9'; roundRect(g, 4, 4, W - 8, H - 8, W * 0.025); g.fill();
    g.fillStyle = '#16345a'; roundRect(g, 4, 4, W - 8, H * 0.13, W * 0.025); g.fill(); g.fillRect(4, H * 0.08, W - 8, H * 0.05);
    g.fillStyle = '#eaf1f9'; g.textBaseline = 'middle'; g.font = `800 ${W * 0.034}px ${FONT}`; g.fillText('RECONSTRUCTION REPORT', W * 0.035, H * 0.068);
    const cols = [{ title: 'RECORDED', ok: true, x: W * 0.03 }, { title: 'NOT RECORDED', ok: false, x: W * 0.515 }];
    const colW = W * 0.455, lists = cols.map((c) => reportRows.map((r, i) => ({ ...r, i })).filter((r) => r.recorded === c.ok));
    const rowH = (H * 0.74) / Math.max(...lists.map((l) => l.length), 1);
    cols.forEach((c, ci) => {
      g.fillStyle = c.ok ? '#1d7d57' : '#b86e00'; g.font = `800 ${H * 0.04}px ${FONT}`; g.textBaseline = 'middle'; g.fillText(`${c.ok ? '✓' : '?'}  ${c.title}`, c.x, H * 0.18);
      lists[ci].forEach((r, ri) => {
        if (r.i >= reportState.shown) return;
        const y = H * 0.22 + ri * rowH;
        g.fillStyle = c.ok ? 'rgba(62,207,142,.16)' : 'rgba(255,181,71,.24)'; roundRect(g, c.x, y + 3, colW, rowH - 8, 10); g.fill();
        g.fillStyle = '#0d1b2e'; g.textBaseline = 'middle'; fit(g, r.question, c.x + colW * 0.04, y + rowH * 0.5, colW * 0.92, rowH * 0.34, 700);
      });
    });
  }
  const redrawReport = () => reportSheet.userData.redraw((g, W, H) => drawReport(g, W, H));

  // ---------------------------------------------------------------- helpers
  function resetBlocks({ shown = true } = {}) {
    for (const b of blocks) {
      b.holder.scale.setScalar(shown ? 1 : 0.001); b.holder.rotation.set(0, 0, 0);
      b.lampMat.color.set(0x586b82); b.lampMat.emissive.set(0x586b82); b.lampMat.emissiveIntensity = 0.6;
      b.body.material.color.set(b.colour); b.body.material.emissive.set(b.colour); b.body.material.emissiveIntensity = 0.28;
      if (b.bond) b.bond.material.color.set(C.cyan);
    }
    scan.visible = false; reportSheet.visible = false; reportState.shown = 0; redrawReport();
  }
  const legend = () => Object.entries(GROUP_NAME).map(([k, v]) => `<span style="display:inline-flex;align-items:center;gap:.35rem;margin-right:.7rem"><i style="width:.7rem;height:.7rem;border-radius:3px;background:${css(GROUP_COLOR[k])};display:inline-block"></i>${v}</span>`).join('');
  const lamp = (b, hex) => { b.lampMat.color.set(hex); b.lampMat.emissive.set(hex); b.lampMat.emissiveIntensity = 1.8; };

  async function build(s, { quick = false } = {}) {
    for (let i = 0; i < n; i++) {
      s.scale(blocks[i].holder, 1, quick ? 0.15 : 0.35, ease.back).catch(() => {});
      await s.wait(quick ? 0.01 : 0.07);
    }
  }
  // Sweep the scanner from the older entries over blocks[0..to]. Each block is one entry, so
  // the counter is the real number of entries passed: all the earlier ones, then one per block.
  const walk = async (s, to, seconds, stopAt = -1) => {
    scan.visible = true; setScan(C.good);
    const start = -2.6;
    let last = -1;
    await s.tween(seconds, (k) => {
      const f = start + k * (to - start);
      scan.position.x = xAt(0) + f * PITCH - 0.4;
      const upto = Math.min(Math.floor(f + 0.6), to);
      while (last < upto) {
        last += 1; const b = blocks[last]; if (!b) break;
        if (last === stopAt) { lamp(b, C.bad); break; }
        lamp(b, C.good); if (b.bond) b.bond.material.color.set(C.good);
      }
      const passed = f < -1 ? Math.round(chain.earlier * Math.max(0, (f - start) / (-1 - start))) : chain.earlier + Math.max(0, Math.min(f + 1, to + 1));
      if (ctx.verifyCounter) ctx.verifyCounter(Math.min(chain.count, Math.round(passed)));
    }, ease.inOut);
  };

  // ------------------------------------------------------------ the steps
  async function enterReceipt(s) {
    resetBlocks({ shown: false });
    ctx.setCounters([{ label: 'Entries', value: chain.count }]);
    say(`<div style="font-size:.8rem;font-weight:600;line-height:1.7">${legend()}</div>`, at(0, 6.6), { cls: 'card', tone: '' });
    say(`<b>+ ${chain.earlier} earlier</b><small>entries before these</small>`, at(xAt(0) - 1.9, 3.5), { tone: '', delay: 0.4 });
    await build(s);
    const callout = (b, html, y, tone, delay) => {
      const x = xAt(blocks.indexOf(b));
      const stem = link([x, ROW_Y + 0.6, 0.2], [x, y - 0.1, 0.2], C.white, 0.35); temp.add(stem);
      say(html, at(x, y), { tone, delay });
    };
    const lastB = blocks[n - 1];
    callout(lastB, `<b>#${lastB.e.seq} · ${lastB.e.label}</b><small>sealed to #${lastB.e.seq - 1}</small>`, 3.9, 'good', 0.2);
    const human = blocks.find((b) => b.e.group === 'human');
    if (human) callout(human, `<b>#${human.e.seq} · ${human.e.label}</b><small>a person is on the record</small>`, 3.9, 'warn', 0.6);
    const decision = blocks.find((b) => b.e.group === 'decision' && b !== human);
    if (decision) callout(decision, `<b>#${decision.e.seq} · ${decision.e.label}</b><small>was it allowed?</small>`, 5.2, '', 0.9);
    // one packet runs the rail to show each entry is bound to the next
    const pk = packet(C.cyan, 0.16); pk.position.set(xAt(0), ROW_Y, 0.5); temp.add(pk);
    await s.tween(2.4, (k) => { pk.position.x = xAt(0) + k * (xAt(n - 1) - xAt(0)); }, ease.inOut);
    temp.remove(pk);
  }

  async function enterVerify(s) {
    resetBlocks(); clearTemp(); ctx.setCounters([{ label: 'Entries checked', value: 0 }]);
    say(`<b>${chain.count} entries</b><small>latest seal ${chain.head}…</small>`, at(0, 4.6), { cls: 'big', tone: '' });
  }

  async function playVerify(s) {
    resetBlocks(); clearTemp(); clearTags();
    const items = ctx.setCounters([{ label: 'Entries checked', value: 0 }]);
    ctx.verifyCounter = (v) => { if (items && items[0] && items[0].node) items[0].node.textContent = String(v); };
    await s.wait(0.4);
    await walk(s, n - 1, 3.6);
    ctx.verifyCounter(chain.count);
    ctx.verifyCounter = null;
    const st = stampMesh('ALL SEALS MATCH', C.good, { w: 5.4 }); st.position.set(0, 4.3, 1.2); st.scale.setScalar(2.2); temp.add(st); await s.scale(st, 1, 0.5, ease.bounce);
    say(`<b>${chain.count} of ${chain.count} entries match</b><small>latest seal ${chain.head}…</small>`, at(0, 6.2), { tone: 'good', cls: 'big', delay: 0.3 });
  }

  async function enterTamper(s) {
    resetBlocks(); clearTemp(); ctx.setCounters(null);
    say('<b>One record, edited in a copy</b><small>the original is untouched</small>', at(0, 5.0), { tone: '', cls: 'big' });
    const b = blocks[tamperIdx];
    if (b) say(`<b>#${b.e.seq}</b><small>${b.e.label}</small>`, at(xAt(tamperIdx), 3.9), { tone: 'warn' });
  }

  async function playTamper(s) {
    resetBlocks(); clearTemp(); clearTags();
    const b = blocks[tamperIdx], t = chain.tamper;
    const bx = xAt(tamperIdx);
    await ctx.stage.view({ pos: [x0 + bx, 3.8, 9.5], look: [x0 + bx, ROW_Y, 0], dur: 1.3, arc: 0, fit: 2.4 });
    const editTag = say(`<b>Edit entry #${t.sequence}</b><small>actor: ${t.original} → <b>${t.edited}</b></small>`, at(bx, 4.2), { tone: 'warn', cls: 'big', delay: 0.1 });
    await s.wait(0.9);
    for (let i = 0; i < 6; i++) { b.body.material.color.set(i % 2 ? C.amber : C.bad); await s.wait(0.07); }
    b.body.material.color.set(C.bad); b.body.material.emissive.set(C.bad);
    ctx.flash('#ff6b6b'); shards(s, temp, new THREE.Vector3(bx, ROW_Y, 0.3), C.bad, 30, 2.2);
    await s.tween(0.6, (k) => { b.holder.rotation.z = Math.sin(k * Math.PI * 4) * 0.12 * (1 - k); }, ease.linear);
    const cam = { pos: [x0 + 0.2, 6.5, 24], look: [x0, 2.4, 0], dur: 1.6, arc: 2, fit: 10.8 };
    ctx.stage.view(cam);
    await s.wait(1.2);
    const items = ctx.setCounters([{ label: 'Entries checked', value: 0 }]);
    ctx.verifyCounter = (v) => { if (items && items[0] && items[0].node) items[0].node.textContent = String(v); };
    await walk(s, tamperIdx, 2.8, tamperIdx);
    ctx.verifyCounter(t.sequence - 1); ctx.verifyCounter = null;
    setScan(C.bad); ctx.flash('#ff6b6b');
    ctx.labels.remove(editTag);
    const st = stampMesh('SEAL BROKEN', C.bad, { w: 4.6 }); st.position.set(bx, 4.3, 1.2); st.scale.setScalar(2.2); temp.add(st); await s.scale(st, 1, 0.5, ease.bounce);
    say(`<b>Detected at entry #${t.broken_at}</b><small>the checker stops at the first mismatch</small>`, at(bx, 5.6), { tone: 'bad', cls: 'big', delay: 0.3 });
    say(`<small>“${t.error}”</small>`, at(bx, 7.4), { tone: 'bad', cls: 'wrap', delay: 0.7 });
  }

  async function enterRebuild(s) {
    resetBlocks(); clearTemp(); ctx.setCounters(null);
    say('<b>Pick a past decision</b>', at(0, 4.2), { cls: 'big' });
  }

  async function playRebuild(s, which) {
    clearTemp(); clearTags();
    resetBlocks();
    const pad = ctx.data.replay;
    const home = cams['prove-rebuild'];
    ctx.stage.view({ ...home, pos: [x0 + home.pos[0], home.pos[1], home.pos[2]], look: [x0 + home.look[0], home.look[1], home.look[2]], dur: 1.2 });
    if (which === 'replay') {
      // A ring rewinds over the chain, then settles on the answer.
      const ring = new THREE.Mesh(new THREE.TorusGeometry(1.1, 0.07, 12, 60), emissive(C.cyan, 1.8)); ring.position.set(xAt(Math.floor(n / 2)), ROW_Y, 0.4); temp.add(ring);
      const halo = glowSprite(C.cyan, 4, 0.5); halo.position.copy(ring.position); temp.add(halo);
      say('<b>Rewinding</b><small>replaying against the rules that applied then</small>', at(0, 4.6), { tone: '', cls: 'big' });
      await s.tween(2.2, (k) => { ring.rotation.z = -k * Math.PI * 6; ring.position.x = xAt(n - 2) + k * (xAt(2) - xAt(n - 2)); halo.position.copy(ring.position); }, ease.inOut);
      ringPulse(s, temp, ring.position.clone(), C.good, { to: 3 }).catch(() => {});
      const st = stampMesh('SAME ANSWER TODAY', C.good, { w: 6 }); st.position.set(0, 4.8, 1.2); st.scale.setScalar(2.1); temp.add(st); await s.scale(st, 1, 0.5, ease.bounce);
      say(`<b>Allowed, as before</b><small>request ${pad.request_id.slice(0, 8)} · chain intact: ${pad.chain.intact ? 'yes' : 'no'}</small>`, at(0, 6.4), { tone: 'good', cls: 'big', delay: 0.3 });
    } else {
      reportSheet.visible = true; reportSheet.scale.setScalar(0.001); reportState.shown = 0; redrawReport();
      ctx.stage.view({ pos: [x0 + 0.4, 5.4, 13], look: [x0, 4.4, 0], dur: 1.3, arc: 0, fit: 4.4 });
      await s.scale(reportSheet, 1, 0.5, ease.back);
      for (let i = 1; i <= reportRows.length; i++) { reportState.shown = i; redrawReport(); await s.wait(0.4); }
      const missing = reportRows.filter((r) => !r.recorded).length;
      say(`<b>${missing} questions marked “not recorded”</b><small>the gaps are shown, not hidden</small>`, at(0, 7.4), { tone: 'warn', cls: 'big', delay: 0.2 });
    }
  }

  // ------------------------------------------------------------ interface
  const cams = {
    'prove-receipt': { pos: [0.2, 6.5, 24], look: [0, 2.4, 0], dur: 2.4, arc: 3, fit: 11.6 },
    'prove-verify': { pos: [0.2, 6.5, 24], look: [0, 2.4, 0], dur: 1.6, arc: 1, fit: 10.8 },
    'prove-tamper': { pos: [0.2, 6.5, 24], look: [0, 2.4, 0], dur: 1.6, arc: 1, fit: 10.8 },
    'prove-rebuild': { pos: [0.2, 6.5, 24], look: [0, 2.6, 0], dur: 1.6, arc: 1, fit: 10.8 },
  };

  return {
    group,
    camera: (id) => {
      const c = cams[id] || cams['prove-receipt'];
      return { ...c, pos: [x0 + c.pos[0], c.pos[1], c.pos[2]], look: [x0 + c.look[0], c.look[1], c.look[2]] };
    },
    async enter(id, step, s) {
      clearTemp(); clearTags(); ctx.setCounters(null);
      if (id === 'prove-receipt') await enterReceipt(s);
      else if (id === 'prove-verify') { await enterVerify(s); await s.wait(0.8); ctx.autoChoose(0); }
      else if (id === 'prove-tamper') await enterTamper(s);
      else if (id === 'prove-rebuild') { await enterRebuild(s); await s.wait(0.6); ctx.autoChoose(1); }
    },
    async choose(id, choiceId, step, s) {
      if (id === 'prove-verify') return playVerify(s);
      if (id === 'prove-tamper') return playTamper(s);
      if (id === 'prove-rebuild') return playRebuild(s, choiceId);
    },
  };
}
