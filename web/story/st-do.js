// Chapter 3, DO: what may the AI do? An authority ladder, an approval gate and a
// release door, an emergency stop, and a budget of calls.
import { THREE, ease, reducedMotion } from './engine.js';
import {
  C, css, FONT, robot, person, platform, gate, packet, panel, sheet, stampMesh, icon, slab,
  roundRect, fit, glowSprite, ringPulse, shards, shadowBlob, link, basic, emissive, mat,
} from './kit.js';
import { X } from './world.js';

const ROT = 0.96;                                  // gates face the camera at the same angle as in KNOW
const ROBOT_AT = new THREE.Vector3(-5.8, 0, 1.2);
const GATE1 = new THREE.Vector3(-0.8, 0, 0);       // approval: a person decides
const GATE2 = new THREE.Vector3(3.8, 0, 0);        // release: checks run again
const PAD_AT = new THREE.Vector3(7.8, 0, 0);
const GAUGE_X = -0.6;

export function buildDo(ctx) {
  const { stage, data } = ctx;
  const x0 = X.do;
  const group = new THREE.Group(); group.position.x = x0; stage.scene.add(group);
  const temp = new THREE.Group(); group.add(temp);
  let tags = [];
  const say = (html, anchor, opts) => { const t = ctx.tag(html, anchor, opts); tags.push(t); return t; };
  const at = (x, y, z = 0) => new THREE.Vector3(x0 + x, y, z);
  const clearTemp = () => { for (const c of temp.children.slice()) temp.remove(c); };
  const clearTags = () => { for (const t of tags) ctx.labels.remove(t); tags = []; };

  // ------------------------------------------------------------ the cast
  const bot = robot({ accent: C.amber }); bot.position.copy(ROBOT_AT); bot.rotation.y = 0.95; group.add(bot);
  const officer = person({ suit: 0x1f8a78, accent: C.paper, prop: 'clip' }); officer.position.set(0.9, 0, 3.0); officer.rotation.y = -0.5; group.add(officer);
  const botPad = platform(1.9, C.amber); botPad.position.copy(ROBOT_AT); group.add(botPad);
  stage.frameFns.add((t) => {
    if (reducedMotion) return;
    const u = bot.userData; u.hover.position.y = u.baseY + (bot.userData.lift || 0) + Math.sin(t * 1.6) * 0.1;
    officer.userData.bob.head.position.y = 2.05 + Math.sin(t * 1.3) * 0.02;
  });

  // ------------------------------------------------------------- two gates
  const g1 = gate({ color: C.amber, width: 3.0, height: 3.6 }); g1.position.copy(GATE1); g1.rotation.y = ROT; group.add(g1);
  const g2 = gate({ color: C.good, width: 3.0, height: 3.6 }); g2.position.copy(GATE2); g2.rotation.y = ROT; group.add(g2);
  const gateTone = { wait: C.amber, ok: C.good, bad: C.bad, idle: C.cyan };
  const door2 = new THREE.Mesh(new THREE.PlaneGeometry(3.0, 3.6), new THREE.MeshBasicMaterial({ color: C.bad, transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false }));
  door2.position.set(0, 1.8, 0); g2.add(door2);                          // slams shut when the emergency stop is engaged
  const pad = platform(1.9, C.good); pad.position.copy(PAD_AT); group.add(pad);
  const padLabel = panel(3.2, 0.8, (g, W, H) => {
    g.clearRect(0, 0, W, H); g.fillStyle = css(C.good); g.font = `800 ${H * 0.4}px ${FONT}`; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText('RELEASED', W / 2, H * 0.5);
  }); padLabel.position.set(PAD_AT.x, 0.06, PAD_AT.z); padLabel.rotation.x = -Math.PI / 2; group.add(padLabel);

  // ---------------------------------------------------- emergency stop button
  const stop = new THREE.Group(); stop.position.set(-2.6, 0, 3.8); group.add(stop);
  const stopBase = new THREE.Mesh(new THREE.CylinderGeometry(1.0, 1.15, 0.5, 32), mat(C.slate)); stopBase.position.y = 0.25;
  const domeMat = emissive(C.bad, 0.9);
  const dome = new THREE.Mesh(new THREE.SphereGeometry(0.72, 28, 14, 0, Math.PI * 2, 0, Math.PI / 2), domeMat); dome.position.y = 0.5;
  const siren = glowSprite(C.bad, 7, 0); siren.position.y = 1.4;
  stop.add(stopBase, dome, siren, shadowBlob(1.5, 0.5));
  const pressStop = (k) => { dome.scale.y = 1 - 0.45 * k; domeMat.emissiveIntensity = 0.9 + 1.8 * k; };

  // ------------------------------------------------------- authority ladder
  const ladder = new THREE.Group(); ladder.visible = false; group.add(ladder);
  const levels = data.colleague.level; const NAMES = ctx.story.chapters.find((c) => c.id === 'do').steps[0].levels;
  const stairs = [];
  NAMES.forEach((name, i) => {
    const h = 0.5 + i * 0.72;
    const m = mat(i === levels ? C.amber : 0x24405f, { transparent: true, opacity: i === levels ? 1 : 0.55, roughness: 0.5 });
    const block = slab(1.45, h, 1.7, 0.12, m); block.position.set(-4.4 + i * 1.6, h / 2, -0.6); ladder.add(block);
    stairs.push({ block, h, name, x: -4.4 + i * 1.6 });
  });
  const ceiling = new THREE.Mesh(new THREE.PlaneGeometry(1.6, 4.2), new THREE.MeshBasicMaterial({ color: C.amber, transparent: true, opacity: 0.16, side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending }));
  ceiling.position.set(-4.4 + 0.8, 2.6, 0.5); ladder.add(ceiling);
  const lockIcon = icon('lock', C.amber, 0.9); lockIcon.position.set(-4.4 + 0.8, 3.2, 0.6); ladder.add(lockIcon);

  // mandate gauge
  const gauge = new THREE.Group(); gauge.visible = false; group.add(gauge);
  const zones = ['low', 'moderate', 'high'], zoneColor = [C.good, C.amber, C.bad];
  zones.forEach((z, i) => {
    const b = slab(1.7, 0.46, 0.5, 0.1, emissive(zoneColor[i], 0.5)); b.position.set(GAUGE_X + i * 1.8, 0.5, 3.6); gauge.add(b);
    const t = panel(1.55, 0.4, (g, W, H) => { g.clearRect(0, 0, W, H); g.fillStyle = '#0b1626'; g.font = `800 ${H * 0.52}px ${FONT}`; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(z.toUpperCase(), W / 2, H * 0.52); });
    t.position.set(GAUGE_X + i * 1.8, 0.5, 3.88); gauge.add(t);
  });
  const ceilMark = new THREE.Mesh(new THREE.BoxGeometry(0.1, 1.5, 0.1), emissive(C.white, 1.5)); ceilMark.position.set(GAUGE_X + 1 * 1.8 + 0.9, 0.8, 3.6); gauge.add(ceilMark);

  // ----------------------------------------------------------- call budget
  const budget = new THREE.Group(); budget.visible = false; group.add(budget);
  const cells = [];
  const calls = data.budget.calls;
  calls.forEach((c, i) => {
    const x = -3.4 + i * 3.6;
    const cell = panel(3.2, 1.5, (g, W, H) => {
      g.clearRect(0, 0, W, H); g.fillStyle = 'rgba(14,30,52,.95)'; roundRect(g, 4, 4, W - 8, H - 8, H * 0.14); g.fill();
      g.strokeStyle = 'rgba(160,200,255,.35)'; g.lineWidth = 4; g.stroke();
      g.fillStyle = css(C.amber); g.font = `800 ${H * 0.34}px ${FONT}`; g.textBaseline = 'middle'; g.fillText(`${i + 1}`, W * 0.07, H * 0.5);
      g.fillStyle = '#eaf1f9'; fit(g, c.label, W * 0.22, H * 0.5, W * 0.74, H * 0.2);
    }, { ppu: 150 });
    cell.position.set(x, 2.4, 0.2); budget.add(cell); cells.push({ cell, x });
  });
  const limitWall = new THREE.Mesh(new THREE.PlaneGeometry(0.1, 3.4), new THREE.MeshBasicMaterial({ color: C.bad, transparent: true, opacity: 0.9 }));
  limitWall.position.set(2.0, 2.4, 0.2); budget.add(limitWall);
  const pips = [];
  for (let i = 0; i < data.budget.limit; i++) { const p = new THREE.Mesh(new THREE.SphereGeometry(0.34, 20, 14), emissive(C.amber, 1.4)); p.position.set(-5.2 + i * 0.95, 5.0, 0.2); budget.add(p); pips.push(p); }

  const cageGroup = new THREE.Group(); cageGroup.visible = false; group.add(cageGroup);
  const cageBox = new THREE.BoxGeometry(2.6, 4.0, 2.6);
  cageGroup.add(new THREE.LineSegments(new THREE.EdgesGeometry(cageBox), new THREE.LineBasicMaterial({ color: C.bad })));
  cageGroup.add(new THREE.Mesh(cageBox, new THREE.MeshBasicMaterial({ color: C.bad, transparent: true, opacity: 0.09, depthWrite: false })));
  cageGroup.position.copy(ROBOT_AT).add(new THREE.Vector3(0, 2.1, 0));

  // ------------------------------------------------------------- helpers
  const setGate = (g, tone) => g.userData.set(gateTone[tone]);
  const proposalSheet = () => sheet({ w: 2.7, h: 3.3, title: 'PROPOSAL', lines: [`${p.client}`, `Move ${p.amount} into the ${p.product}`, `Approver: ${p.approver}`], tone: C.amber });
  const p = ctx.story.chapters.find((c) => c.id === 'do').steps.find((s) => s.id === 'do-approval').proposal;
  const gateCentre = (g) => new THREE.Vector3(g.position.x, 1.9, 0);
  const hand = () => new THREE.Vector3(ROBOT_AT.x + 0.8, 2.0, ROBOT_AT.z + 0.2);

  function hideAll() {
    ladder.visible = false; gauge.visible = false; budget.visible = false; cageGroup.visible = false;
    g1.visible = g2.visible = pad.visible = padLabel.visible = false; stop.visible = false; officer.visible = false;
    bot.visible = true; botPad.visible = true; bot.position.copy(ROBOT_AT); bot.userData.lift = 0; bot.userData.mood(C.amber); bot.rotation.y = 0.95;
    siren.material.opacity = 0; pressStop(0); door2.material.opacity = 0; setGate(g1, 'wait'); setGate(g2, 'ok');
  }
  function showApprovalSet() { g1.visible = g2.visible = pad.visible = padLabel.visible = stop.visible = officer.visible = true; setGate(g1, 'wait'); setGate(g2, 'ok'); }

  async function newProposal(s, { quick = false } = {}) {
    const sh = proposalSheet(); sh.position.copy(hand()); sh.scale.setScalar(0.001); temp.add(sh);
    await s.scale(sh, 1, quick ? 0.2 : 0.5, ease.back);
    return sh;
  }

  // ------------------------------------------------------------- authority
  async function enterAuthority(s) {
    hideAll(); ladder.visible = true; gauge.visible = false; botPad.visible = false;
    const step0 = stairs[0];
    bot.position.set(step0.x, step0.h, -0.3);
    for (let i = 0; i < stairs.length; i++) {
      const st = stairs[i]; st.block.scale.y = 0.001; st.block.position.y = 0;
      s.tween(0.5, (k) => { st.block.scale.y = Math.max(0.001, k); st.block.position.y = (st.h * k) / 2; }, ease.out).catch(() => {});
      await s.wait(0.09);
    }
    ladderLabels(0.2);
    say('<b>Higher levels are locked</b>', new THREE.Vector3(x0 + 3.2, 6.9, 0), { tone: 'bad', delay: 1.4 });
  }

  function ladderLabels(delay = 0) {
    stairs.forEach((st, i) => {
      if (i === levels) return;
      say(`<small>L${i}</small>${st.name}`, new THREE.Vector3(x0 + st.x, st.h + 1.0, -0.4), { delay: delay + i * 0.12 });
    });
    const here = stairs[levels];
    say(`<b>L${levels} · ${here.name}</b><small>This colleague is here. Set by the bank, not by the AI.</small>`, new THREE.Vector3(x0 + here.x, here.h + 3.6, 0), { tone: 'warn', cls: 'wrap', delay: delay + 0.3 });
  }

  async function playMandate(s, which) {
    clearTemp(); clearTags(); hideAll(); ladder.visible = true; gauge.visible = true; botPad.visible = false;
    const stp = stairs[0]; bot.position.set(stp.x, stp.h, -0.3);
    for (const st of stairs) { st.block.scale.y = 1; st.block.position.y = st.h / 2; }
    ladderLabels();
    say('<b>Mei Tan’s mandate</b><small>moderate risk at most</small>', at(GAUGE_X - 1.1, 0.7, 3.6), { tone: 'gold', align: 'left' });
    const risk = data.suitability[which === 'safe' ? 'INS-MMF' : 'INS-HK-NOTE'].product_risk;
    const slot = zones.indexOf(risk);
    const tok = packet(zoneColor[slot], 0.34); tok.position.set(GAUGE_X + 1.8 + 0.9, 5.2, 3.6); temp.add(tok);
    say(`<b>${which === 'safe' ? 'Money market fund' : 'Structured note'}</b><small>${risk} risk</small>`, tok, { offset: [0, 0.9, 0], tone: which === 'safe' ? 'good' : 'bad' });
    await s.wait(0.5);
    await s.glide(tok, [GAUGE_X + slot * 1.8, 1.5, 3.6], 1.0, 0.6);
    if (data.suitability[which === 'safe' ? 'INS-MMF' : 'INS-HK-NOTE'].suitable) {
      const ok = icon('check', C.good, 0.9); ok.position.set(GAUGE_X + slot * 1.8, 1.6, 3.9); temp.add(ok); await s.scale(ok, 1, 0.4, ease.back);
      say('<b>Fits the mandate</b>', at(GAUGE_X + 1.8, 0.05, 3.9), { tone: 'good', cls: 'big', align: 'bottom' });
    } else {
      ctx.flash('#ff6b6b'); shards(s, temp, tok.position.clone(), C.bad); tok.visible = false;
      const x = icon('cross', C.bad, 0.9); x.position.set(GAUGE_X + slot * 1.8, 1.6, 3.9); temp.add(x); await s.scale(x, 1, 0.4, ease.back);
      say('<b>Over the mandate’s ceiling</b>', at(GAUGE_X + 1.8, 0.05, 3.9), { tone: 'bad', cls: 'big', align: 'bottom' });
    }
  }

  // -------------------------------------------------------------- approval
  let held = null;
  async function enterApproval(s) {
    hideAll(); showApprovalSet(); stop.visible = false;
    ctx.setCounters(null);
    say('<b>AI colleague</b>', bot, { offset: [0, 3.3, 0], tone: 'warn' });
    say('<b>Risk officer</b>', officer, { offset: [0, 2.9, 0], tone: 'good' });
    await s.wait(0.5);
    const sh = await newProposal(s); held = sh;
    await s.glide(sh, [GATE1.x - 2.3, 2.9, 1.6], 1.2, 0.6);
    setGate(g1, 'wait'); ringPulse(s, temp, new THREE.Vector3(GATE1.x, 1.9, 0), C.amber, { rotY: ROT, to: 2.6 }).catch(() => {});
    say('<b>Paused for a person</b><small>The work is saved, not lost</small>', at(GATE1.x - 2.3, 5.6), { tone: 'warn', cls: 'big' });
    sh.userData.bob = true;
    s.frame((t) => { if (!reducedMotion && sh.parent && sh.userData.bob) sh.position.y = 2.9 + Math.sin(t * 2.2) * 0.06; });
  }

  async function playApproval(s, which) {
    // The held proposal is still where enterApproval left it; if not, rebuild that state.
    if (!held || !held.parent) { clearTemp(); clearTags(); hideAll(); showApprovalSet(); stop.visible = false; held = await newProposal(s, { quick: true }); }
    for (const t of tags) if (t.el.textContent.includes('Paused')) ctx.labels.remove(t);
    const sh = held;
    sh.userData.bob = false;
    sh.position.set(GATE1.x - 2.3, 2.9, 1.6);
    await s.wait(0.5);
    if (which === 'deny') {
      setGate(g1, 'bad'); ctx.flash('#ff6b6b');
      shards(s, temp, sh.position.clone(), C.bad, 34); temp.remove(sh); held = null;
      const st = stampMesh('DENIED', C.bad); st.position.set(GATE1.x + 0.2, 3.3, 1.8); st.scale.setScalar(2.4); temp.add(st); await s.scale(st, 1, 0.45, ease.bounce);
      say('<b>Nothing was released</b>', at(GATE1.x, 5.6), { tone: 'bad', cls: 'big', delay: 0.4 });
      return;
    }
    setGate(g1, 'ok'); ringPulse(s, temp, new THREE.Vector3(GATE1.x, 1.9, 0), C.good, { rotY: ROT, to: 2.8 }).catch(() => {});
    const ap = icon('check', C.good, 0.9); ap.position.set(GATE1.x, 4.4, 0.9); temp.add(ap); await s.scale(ap, 1, 0.35, ease.back);
    await s.glide(sh, [GATE2.x - 1.8, 2.9, 1.4], 1.1, 0.5);
    setGate(g2, 'wait'); const again = say('<b>Checks run again</b>', at(GATE2.x, 5.0), { tone: 'warn', delay: 0.1 });
    await s.wait(0.9); setGate(g2, 'ok'); ctx.labels.remove(again);
    ringPulse(s, temp, new THREE.Vector3(GATE2.x, 1.9, 0), C.good, { rotY: ROT, to: 2.8 }).catch(() => {});
    await s.glide(sh, [PAD_AT.x, 1.8, 0.4], 1.1, 0.5);
    const st = stampMesh('RELEASED', C.good); st.position.set(PAD_AT.x - 0.4, 3.6, 1.6); st.scale.setScalar(2.4); temp.add(st); await s.scale(st, 1, 0.45, ease.bounce);
    say('<b>Released as a proposal</b><small>No trade is placed in this demo</small>', at(PAD_AT.x, 5.2), { tone: 'good', cls: 'big', delay: 0.4 });
    held = null;
  }

  // ------------------------------------------------------------ emergency stop
  let approved2 = null;
  async function enterStop(s) {
    hideAll(); showApprovalSet(); stop.visible = true;
    setGate(g1, 'ok'); setGate(g2, 'ok');
    say('<b>Emergency stop</b>', at(-2.6, 2.4, 3.8), { tone: 'bad' });
    const sh = await newProposal(s, { quick: true }); approved2 = sh;
    sh.position.set(GATE2.x - 1.8, 2.9, 1.4);
    const ap = icon('check', C.good, 0.9); ap.position.set(GATE1.x, 4.4, 0.9); temp.add(ap);
    say('<b>Approved</b><small>by the risk officer, not yet released</small>', at(GATE2.x - 1.8, 5.6), { tone: 'good' });
    s.frame((t) => { if (!reducedMotion && sh.parent) sh.position.y = 2.8 + Math.sin(t * 2.2) * 0.06; });
  }

  async function engageStop(s) {
    await s.tween(0.25, pressStop, ease.out);
    ctx.flash('#ff2d3d');
    await s.tween(0.5, (k) => { siren.material.opacity = 0.9 * k; }, ease.out);
    s.frame((t) => { if (!reducedMotion) siren.material.opacity = 0.55 + Math.sin(t * 7) * 0.35; });
    setGate(g2, 'bad'); setGate(g1, 'bad');
    door2.scale.y = 0.001; door2.position.y = 3.6; door2.material.opacity = 0.7;
    await s.tween(0.45, (k) => { door2.scale.y = Math.max(0.001, k); door2.position.y = 3.6 - (3.6 * k) / 2; }, ease.bounce);
  }

  async function playStop(s, which) {
    clearTemp(); clearTags(); hideAll(); showApprovalSet(); stop.visible = true; setGate(g1, 'ok'); setGate(g2, 'ok');
    say('<b>Emergency stop</b>', at(-2.6, 2.4, 3.8), { tone: 'bad' });
    if (which === 'stop') {
      const sh = proposalSheet(); sh.position.set(GATE2.x - 1.8, 2.9, 1.4); temp.add(sh);
      const ap = icon('check', C.good, 0.9); ap.position.set(GATE1.x, 4.4, 0.9); temp.add(ap);
      const okTag = say('<b>Approved</b><small>not yet released</small>', at(GATE2.x - 1.8, 5.6), { tone: 'good' });
      await s.wait(0.9);
      ctx.labels.remove(okTag);
      await engageStop(s);
      await s.glide(sh, [GATE2.x - 2.6, 2.9, 1.6], 0.5, 0.2);
      const st = stampMesh('WITHHELD', C.bad); st.position.set(GATE2.x, 3.4, 1.8); st.scale.setScalar(2.4); temp.add(st); await s.scale(st, 1, 0.45, ease.bounce);
      say('<b>Approved, but not released</b><small>the stop wins</small>', at(GATE2.x, 6.0), { tone: 'bad', cls: 'big', delay: 0.3 });
    } else {
      await engageStop(s);
      cageGroup.visible = true; bot.userData.mood(C.bad);
      const req = packet(C.amber, 0.3); req.position.copy(hand()); temp.add(req);
      await s.glide(req, [ROBOT_AT.x + 1.9, 2.2, ROBOT_AT.z], 0.5, 0.2);
      ctx.flash('#ff6b6b'); shards(s, temp, req.position.clone(), C.bad); temp.remove(req);
      const x = icon('cross', C.bad, 1.0); x.position.set(ROBOT_AT.x + 0.2, 4.4, ROBOT_AT.z + 1.4); temp.add(x); await s.scale(x, 1, 0.35, ease.back);
      say('<b>Request refused</b><small>The emergency stop is engaged</small>', at(ROBOT_AT.x, 5.4, ROBOT_AT.z), { tone: 'bad', cls: 'big', delay: 0.3 });
    }
  }

  // ---------------------------------------------------------------- limits
  async function enterLimits(s) {
    hideAll(); budget.visible = true; botPad.visible = true; bot.position.set(-6.2, 0, 1.4);
    ctx.setCounters([{ label: 'Call limit', value: data.budget.limit }, { label: 'Calls made', value: 0 }]);
    for (const { cell } of cells) { cell.material.opacity = 1; }
    pips.forEach((p) => { p.visible = true; p.scale.setScalar(1); });
    say('<b>Limit: 2 calls</b>', new THREE.Vector3(x0 + limitWall.position.x, 4.3, 0), { tone: 'bad' });
    say('<b>The task needs 3</b>', at(0.4, 0.3, 1.6), { tone: 'warn', align: 'center' });
  }

  async function playLimits(s) {
    clearTemp(); clearTags(); await enterLimits(s);
    await s.wait(0.5);
    let made = 0;
    for (let i = 0; i < calls.length; i++) {
      const { cell, x } = cells[i], ok = calls[i].allowed;
      const pk = packet(ok ? C.cyan : C.amber, 0.28); pk.position.copy(hand()); temp.add(pk);
      await s.glide(pk, [x, 2.4, 0.6], 0.9, 0.7);
      if (ok) {
        temp.remove(pk); made += 1;
        const tick = icon('check', C.good, 0.8); tick.position.set(x + 1.3, 3.5, 0.5); temp.add(tick); await s.scale(tick, 1, 0.3, ease.back);
        const pip = pips[i]; if (pip) await s.scale(pip, 0.001, 0.4, ease.in);
        ctx.setCounters([{ label: 'Call limit', value: data.budget.limit }, { label: 'Calls made', value: made }]);
      } else {
        ctx.flash('#ff6b6b'); shards(s, temp, pk.position.clone(), C.bad); temp.remove(pk);
        const x2 = icon('cross', C.bad, 0.9); x2.position.set(x, 3.6, 0.5); temp.add(x2); await s.scale(x2, 1, 0.3, ease.back);
        const st = stampMesh('BUDGET SPENT', C.bad, { w: 4.2 }); st.position.set(2.0, 6.3, 1.4); st.scale.setScalar(2.2); temp.add(st); await s.scale(st, 1, 0.45, ease.bounce);
      }
      await s.wait(0.25);
    }
  }

  // ------------------------------------------------------------- interface
  const cams = {
    'do-authority': { pos: [1.0, 6.0, 20.0], look: [1.0, 2.7, 0], dur: 2.4, arc: 3, fit: 8.6 },
    'do-approval': { pos: [1.0, 5.4, 20.0], look: [1.0, 2.7, 0], dur: 1.8, arc: 1, fit: 9.6 },
    'do-stop': { pos: [1.0, 5.4, 20.0], look: [1.0, 2.7, 0], dur: 1.6, arc: 1, fit: 9.6 },
    'do-limits': { pos: [0.6, 5.0, 19.0], look: [0.6, 2.7, 0], dur: 1.8, arc: 1, fit: 8.4 },
  };

  return {
    group,
    camera: (id) => {
      const c = cams[id] || cams['do-approval'];
      return { ...c, pos: [x0 + c.pos[0], c.pos[1], c.pos[2]], look: [x0 + c.look[0], c.look[1], c.look[2]] };
    },
    async enter(id, step, s) {
      clearTemp(); clearTags(); ctx.setCounters(null); held = null;
      if (id === 'do-authority') { await enterAuthority(s); await s.wait(1.2); ctx.autoChoose(0); }
      else if (id === 'do-approval') await enterApproval(s);
      else if (id === 'do-stop') await enterStop(s);
      else if (id === 'do-limits') { await enterLimits(s); await s.wait(1.0); ctx.autoChoose(0); }
    },
    async choose(id, choiceId, step, s) {
      if (id === 'do-authority') return playMandate(s, choiceId);
      if (id === 'do-approval') return playApproval(s, choiceId);
      if (id === 'do-stop') return playStop(s, choiceId);
      if (id === 'do-limits') return playLimits(s);
    },
  };
}
