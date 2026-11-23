// Chapter 2, KNOW: what may the AI see? A gate in front of a vault, a library,
// and a wall between the bank and an outside AI provider.
import { THREE, ease, reducedMotion } from './engine.js';
import {
  C, css, FONT, robot, person, platform, gate, vault, packet, panel, sheet, stampMesh, icon,
  roundRect, wrap, fit, glowSprite, ringPulse, shards, shadowBlob, link, basic, emissive, mat,
} from './kit.js';
import { X } from './world.js';

const SLOT = new THREE.Vector3(-4.9, 0, 1.0);
const GATE_AT = new THREE.Vector3(-1.4, 0, 0);
const GATE_ROT = 0.96;
const VAULT_AT = new THREE.Vector3(3.2, 0, 0);

export function buildKnow(ctx) {
  const { stage, data, story } = ctx;
  const x0 = X.know;
  const group = new THREE.Group(); group.position.x = x0; stage.scene.add(group);
  const temp = new THREE.Group(); group.add(temp);          // things in flight: cleared on every reset
  let tags = [];                                              // labels made by the current choice
  const say = (html, anchor, opts) => { const t = ctx.tag(html, anchor, opts); tags.push(t); return t; };
  const at = (x, y, z = 0) => new THREE.Vector3(x0 + x, y, z);

  // ---------------------------------------------------------------- avatars
  const avatars = {
    relationship_manager: person({ suit: 0x3b6aa0, accent: C.gold, prop: 'case' }),
    agent: robot({ accent: C.cyan }),
    visitor: person({ suit: 0x8b9db2, accent: 0xc4cfdb, prop: 'hood' }),
    desk: person({ suit: 0x3b6aa0, accent: C.gold, prop: 'case' }),
  };
  for (const a of Object.values(avatars)) { a.position.copy(SLOT); a.rotation.y = 0.95; a.visible = false; group.add(a); }
  stage.frameFns.add((t) => {
    if (reducedMotion) return;
    const u = avatars.agent.userData; u.hover.position.y = u.baseY + Math.sin(t * 1.6) * 0.1;
    for (const key of ['relationship_manager', 'visitor', 'desk']) avatars[key].userData.bob.head.position.y = 2.05 + Math.sin(t * 1.4) * 0.02;
  });
  const pedestal = platform(1.9, C.cyan); pedestal.position.copy(SLOT); group.add(pedestal);

  // ------------------------------------------------------------------- gate
  const gt = gate({ color: C.cyan, width: 3.6, height: 3.9 });
  gt.position.copy(GATE_AT); gt.rotation.y = GATE_ROT; group.add(gt);
  const gateTone = { idle: C.cyan, ok: C.good, bad: C.bad, wait: C.amber };
  const setGate = (tone) => gt.userData.set(gateTone[tone]);
  const gateCentre = () => new THREE.Vector3(GATE_AT.x, 2.0, GATE_AT.z);

  // ------------------------------------------------------------------ vault
  const vt = vault({ color: C.blue, w: 5.0, h: 5.6, d: 3.2 }); vt.position.copy(VAULT_AT); group.add(vt);
  const door = vt.userData.door;
  const doorState = { open: 0 };
  const setDoor = (k) => {
    // Retract into the top edge: scale down, keeping the top fixed.
    const s = Math.max(0.001, 1 - k), full = vt.userData.h - 0.1;
    doorState.open = k; door.scale.y = s; door.position.y = vt.userData.h - 0.05 - (full * s) / 2;
  };

  // client file
  const rows = { name: null, email: null, risk_profile: null, investment_horizon_years: null, tax_identifier: null };
  const file = { mode: 'sealed', rows: [], account: null, holdings: null, shown: 0 };
  const card = panel(3.6, 4.8, (g, W, H) => drawFile(g, W, H, file), { ppu: 200 });
  card.position.set(VAULT_AT.x, 3.0, 0.1); group.add(card);
  // World y of row i, matching drawFile's layout, so chips leave from the row they came from.
  const rowY = (i, n) => 3.0 + 2.4 - 4.8 * 0.2 - ((4.8 * 0.76) / n) * (i + 0.5);

  function drawFile(g, W, H, f) {
    g.clearRect(0, 0, W, H);
    g.fillStyle = '#eef3f9'; roundRect(g, 4, 4, W - 8, H - 8, W * 0.045); g.fill();
    g.fillStyle = '#16345a'; roundRect(g, 4, 4, W - 8, H * 0.14, W * 0.045); g.fill(); g.fillRect(4, H * 0.08, W - 8, H * 0.06);
    g.fillStyle = '#eaf1f9'; g.textBaseline = 'middle'; g.font = `800 ${W * 0.062}px ${FONT}`; g.fillText('CLIENT FILE', W * 0.07, H * 0.075);
    g.font = `500 ${W * 0.05}px ${FONT}`; g.fillStyle = '#a9c3e4'; g.fillText('synthetic client', W * 0.07, H * 0.115);
    if (f.mode === 'sealed') {
      g.fillStyle = '#31475f'; g.textAlign = 'center'; g.font = `700 ${W * 0.085}px ${FONT}`;
      g.fillText('SEALED', W / 2, H * 0.52);
      g.font = `500 ${W * 0.056}px ${FONT}`; g.fillStyle = '#5b7490'; g.fillText('nothing has been read', W / 2, H * 0.6);
      g.textAlign = 'left'; return;
    }
    const all = [...f.rows, f.account].filter(Boolean);
    const top = H * 0.2, step = (H * 0.76) / (all.length + (f.holdings ? 1 : 0));
    all.forEach((r, i) => {
      if (i >= f.shown) return;
      const y = top + i * step;
      g.fillStyle = '#6a7f96'; g.font = `700 ${W * 0.048}px ${FONT}`; g.textBaseline = 'alphabetic'; g.fillText(r.label.toUpperCase(), W * 0.07, y + step * 0.3);
      const maxW = W * 0.86;
      if (r.access === 'visible') { g.fillStyle = '#0d1b2e'; fit(g, String(r.value), W * 0.07, y + step * 0.72, maxW, W * 0.075); }
      else if (r.access === 'masked') {
        g.fillStyle = '#c47d00'; g.font = `700 ${W * 0.075}px ${FONT}`; g.fillText('••••••••••', W * 0.07, y + step * 0.74);
        g.font = `800 ${W * 0.046}px ${FONT}`; g.textAlign = 'right'; g.fillText('MASKED', W * 0.93, y + step * 0.7); g.textAlign = 'left';
      } else {
        g.strokeStyle = '#b3c0cf'; g.setLineDash([10, 8]); g.lineWidth = 4; g.beginPath(); g.moveTo(W * 0.07, y + step * 0.6); g.lineTo(W * 0.5, y + step * 0.6); g.stroke(); g.setLineDash([]);
        g.fillStyle = '#8fa0b3'; g.font = `800 ${W * 0.046}px ${FONT}`; g.textAlign = 'right'; g.fillText('NOT AVAILABLE', W * 0.93, y + step * 0.68); g.textAlign = 'left';
      }
      g.strokeStyle = '#d7e0ea'; g.lineWidth = 2; g.beginPath(); g.moveTo(W * 0.06, y + step * 0.92); g.lineTo(W * 0.94, y + step * 0.92); g.stroke();
    });
    if (f.holdings && f.shown >= all.length) {
      const y = top + all.length * step;
      g.fillStyle = '#6a7f96'; g.font = `700 ${W * 0.048}px ${FONT}`; g.fillText('HOLDS', W * 0.07, y + step * 0.3);
      g.fillStyle = '#0d1b2e'; fit(g, `S$${f.holdings.amount.toLocaleString('en-US')} · ${f.holdings.product}`, W * 0.07, y + step * 0.72, W * 0.86, W * 0.06);
    }
  }
  const redrawFile = () => card.userData.redraw((g, W, H) => drawFile(g, W, H, file));

  // library (documents inside the vault)
  const library = new THREE.Group(); library.visible = false; group.add(library);
  const docSheets = [];
  const lock = icon('lock', C.bad, 0.8); lock.visible = false; library.add(lock);

  // ----------------------------------------------------- privacy: wall + cloud
  const privacy = new THREE.Group(); privacy.visible = false; group.add(privacy);
  const wall = new THREE.Mesh(new THREE.PlaneGeometry(9, 5.6), new THREE.MeshBasicMaterial({ color: C.blue, transparent: true, opacity: 0.09, side: THREE.DoubleSide, depthWrite: false }));
  wall.rotation.y = GATE_ROT; wall.position.set(0.2, 2.8, 0); privacy.add(wall);
  const wallEdge = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.PlaneGeometry(9, 5.6)), new THREE.LineBasicMaterial({ color: C.blue, transparent: true, opacity: 0.7 }));
  wallEdge.rotation.y = GATE_ROT; wallEdge.position.copy(wall.position); privacy.add(wallEdge);
  const ringMat = emissive(C.cyan, 1.6);
  const filter = new THREE.Mesh(new THREE.TorusGeometry(1.7, 0.1, 14, 56), ringMat); filter.rotation.y = GATE_ROT; filter.position.set(0.2, 2.7, 0); privacy.add(filter);
  const filterGlow = glowSprite(C.cyan, 5.2, 0.3); filterGlow.position.copy(filter.position); privacy.add(filterGlow);
  const cloud = new THREE.Group(); cloud.position.set(6.0, 3.4, -0.4); privacy.add(cloud);
  const cloudMat = new THREE.MeshStandardMaterial({ color: 0xdfe9f7, roughness: 0.9, emissive: 0x335577, emissiveIntensity: 0.4 });
  [[0, 0, 0, 1.3], [1.3, -0.2, 0.2, 1.0], [-1.3, -0.25, 0, 1.0], [0.5, 0.7, 0, 0.9], [-0.6, 0.55, 0.3, 0.8]].forEach(([x, y, z, r]) => { const s = new THREE.Mesh(new THREE.SphereGeometry(r, 18, 14), cloudMat); s.position.set(x, y, z); cloud.add(s); });
  stage.frameFns.add((t) => { if (!reducedMotion) cloud.position.y = 3.4 + Math.sin(t * 0.8) * 0.12; });
  const BANK = new THREE.Vector3(-5.4, 0, 1.4);   // where the AI stands in the privacy scene

  // ---------------------------------------------------------------- helpers
  const ALL = [avatars.relationship_manager, avatars.agent, avatars.visitor, avatars.desk];
  function clearTemp() { for (const c of temp.children.slice()) temp.remove(c); }
  function clearTags() { for (const t of tags) ctx.labels.remove(t); tags = []; }
  function hideScene() {
    for (const a of ALL) a.visible = false;
    library.visible = false; privacy.visible = false; card.visible = false; vt.visible = false; gt.visible = false; pedestal.visible = false;
  }
  function showVault() { vt.visible = true; gt.visible = true; pedestal.visible = true; setDoor(0); setGate('idle'); }
  function resetFile(mode = 'sealed') { file.mode = mode; file.rows = []; file.account = null; file.holdings = null; file.shown = 0; redrawFile(); card.visible = true; }
  async function appear(s, who) {
    for (const a of ALL) a.visible = false;
    who.visible = true; who.scale.setScalar(0.001);
    await s.scale(who, 1, 0.45, ease.back);
  }
  const hand = (who) => new THREE.Vector3(SLOT.x + 0.7, 1.7, SLOT.z);
  const chip = (text, tone = C.cyan) => panel(1.9, 0.42, (g, W, H) => {
    g.clearRect(0, 0, W, H); g.fillStyle = 'rgba(8,16,28,.92)'; roundRect(g, 2, 2, W - 4, H - 4, H * 0.3); g.fill();
    g.strokeStyle = css(tone); g.lineWidth = 3; g.stroke(); g.fillStyle = '#eaf1f9'; g.font = `700 ${H * 0.42}px ${FONT}`; g.textBaseline = 'middle'; g.fillText(text, H * 0.3, H * 0.52);
  }, { ppu: 170 });

  async function sendPacket(s, tone = C.cyan) {
    const p = packet(tone, 0.3); p.position.copy(hand()); temp.add(p);
    await s.glide(p, [gateCentre().x, 2.0, 0.6], 0.9, 0.5);
    return p;
  }

  // ---------------------------------------------------------------- roles
  async function playRole(s, role) {
    const view = data.roles[role];
    clearTemp(); clearTags(); hideScene(); showVault(); resetFile('sealed');
    ctx.setCounters([{ label: 'Records fetched', value: 0 }]);
    await appear(s, avatars[role]);
    say(`<b>${view.label}</b>`, avatars[role], { offset: [0, role === 'agent' ? 3.4 : 2.9, 0], tone: role === 'agent' ? '' : 'gold' });
    await s.wait(0.35);
    const p = await sendPacket(s);
    setGate('wait'); ringPulse(s, temp, new THREE.Vector3(GATE_AT.x, 2.0, GATE_AT.z), C.amber, { rotY: GATE_ROT, to: 2.6 }).catch(() => {});
    const checking = say('Checking at the gate…', gateCentre(), { offset: [0, 2.6, 0] });
    await s.wait(0.9); ctx.labels.remove(checking);

    if (view.blocked) {
      setGate('bad'); ctx.flash('#ff6b6b');
      p.userData.set(C.bad);
      await s.glide(p, [SLOT.x + 0.7, 1.7, SLOT.z], 0.7, 0.3);
      shards(s, temp, p.position.clone(), C.bad); temp.remove(p);
      const st = stampMesh('BLOCKED', C.bad); st.position.set(GATE_AT.x + 0.2, 3.1, 1.6); st.scale.setScalar(2.4); temp.add(st);
      await s.scale(st, 1, 0.45, ease.bounce);
      say('<b>Nothing was fetched.</b><small>There is nothing to leak.</small>', new THREE.Vector3(x0 + VAULT_AT.x, 6.4, 0), { tone: 'bad', cls: 'big' });
      return;
    }
    setGate('ok'); ringPulse(s, temp, new THREE.Vector3(GATE_AT.x, 2.0, GATE_AT.z), C.good, { rotY: GATE_ROT, to: 2.8 }).catch(() => {});
    await s.glide(p, [VAULT_AT.x - 1.2, 2.8, 1.6], 0.9, 0.5);
    temp.remove(p);
    await s.tween(0.8, (k) => setDoor(k), ease.inOut);
    file.mode = 'open'; file.rows = view.fields; file.account = { ...view.account, key: 'account' }; file.holdings = view.holdings;
    const total = view.fields.length + 1;
    for (let i = 1; i <= total + (view.holdings ? 1 : 0); i++) { file.shown = i; redrawFile(); await s.wait(0.22); }
    ctx.setCounters([{ label: 'Records fetched', value: view.retrieved.length }]);
    // What the person actually receives flies out to them.
    const given = [...view.fields, view.account].map((f, i) => ({ f, i })).filter(({ f }) => f.access === 'visible');
    const rowCount = view.fields.length + 1 + (view.holdings ? 1 : 0);
    for (const { f, i } of given) {
      const c = chip(`${f.label}: ${f.value}`); c.position.set(VAULT_AT.x, rowY(i, rowCount), 1.0); temp.add(c);
      s.glide(c, [SLOT.x + 0.9, 3.2 + (i % 3) * 0.1, 1.2], 0.9, 1.0).then(() => s.tween(0.4, (k) => { c.material.opacity = 1 - k; })).then(() => temp.remove(c)).catch(() => {});
      await s.wait(0.18);
    }
    const masked = [...view.fields, view.account].filter((f) => f.access === 'masked').length;
    const denied = [...view.fields, view.account].filter((f) => f.access === 'denied').length;
    say(`<b>${given.length} fields shown</b><small>${masked} masked · ${denied} not available</small>`, new THREE.Vector3(x0 + VAULT_AT.x, 6.6, 0), { tone: 'good', cls: 'big' });
  }

  // --------------------------------------------------------------- border
  const lamp = (ok, text) => `<b>${ok ? '✓' : '✕'}</b> ${text}`;

  function buildLibrary(entries) {
    for (const d of docSheets) library.remove(d);
    docSheets.length = 0;
    lock.visible = false;
    const n = entries.length, gap = 1.8;
    entries.forEach((e, i) => {
      const d = sheet({ w: 1.7, h: 2.4, title: e.head, lines: [e.body], tone: e.tone, dashed: !!e.dashed, stamp: e.stamp });
      d.position.set(VAULT_AT.x + (i - (n - 1) / 2) * gap, 2.9, 0.1); library.add(d); docSheets.push(d); d.userData.entry = e;
    });
    library.visible = true;
  }

  async function playBorder(s, which, step) {
    const choice = step.choices.find((c) => c.id === which);
    const view = data.borders[which], deny = which === 'deny';
    clearTemp(); clearTags(); hideScene(); showVault(); card.visible = false;
    ctx.setCounters([{ label: 'Documents read', value: 0 }, { label: 'AI calls', value: 0 }]);
    const entries = [...view.documents.map((t) => ({ head: 'Approved', body: t.replace(/ - /g, ': '), tone: C.good })),
      ...(view.withheld || [{}]).map(() => ({ head: 'Confidential', body: 'Steering note. Above this person’s clearance.', tone: C.bad, dashed: true }))];
    if (deny) buildLibrary([{ head: 'Approved', body: 'House guidance', tone: C.good }, { head: 'Approved', body: 'Policy library', tone: C.good }, { head: 'Confidential', body: 'Steering note', tone: C.bad, dashed: true }]);
    else buildLibrary(entries);
    lock.visible = false;
    await appear(s, avatars.desk);
    say(`<b>${choice.desk}</b><small>“${choice.ask}”</small>`, avatars.desk, { offset: [0, 3.0, 0], tone: 'gold', cls: 'wrap' });
    await s.wait(0.5);
    const p = await sendPacket(s);
    setGate('wait'); ringPulse(s, temp, new THREE.Vector3(GATE_AT.x, 2.0, GATE_AT.z), C.amber, { rotY: GATE_ROT, to: 2.6 }).catch(() => {});
    await s.wait(0.8);

    if (deny) {
      setGate('bad'); ctx.flash('#ff6b6b'); p.userData.set(C.bad);
      const rows = step.reasons.map((r, i) => `<li style="animation-delay:${(0.5 + i * 0.45).toFixed(2)}s"><b>✕</b><span>${r}</span></li>`).join('');
      say(`<b>${view.failed.length} of ${view.total} checks failed</b><ul>${rows}</ul>`, new THREE.Vector3(x0 + 3.6, 9.0, 0), { tone: 'bad', cls: 'card', align: 'bottom' });
      await s.glide(p, [SLOT.x + 0.7, 1.7, SLOT.z], 0.8, 0.3);
      shards(s, temp, p.position.clone(), C.bad); temp.remove(p);
      const st = stampMesh('BLOCKED', C.bad); st.position.set(GATE_AT.x + 0.3, 3.2, 1.8); st.scale.setScalar(2.4); temp.add(st);
      await s.scale(st, 1, 0.45, ease.bounce);
      return;
    }
    setGate('ok'); ringPulse(s, temp, new THREE.Vector3(GATE_AT.x, 2.0, GATE_AT.z), C.good, { rotY: GATE_ROT, to: 2.8 }).catch(() => {});
    say(`<b>All ${view.total} checks passed</b>`, gateCentre().add(new THREE.Vector3(x0, 0, 0)), { offset: [0, 2.7, 0], tone: 'good', cls: 'big' });
    await s.glide(p, [VAULT_AT.x - 1.2, 2.8, 1.6], 0.9, 0.5); temp.remove(p);
    await s.tween(0.7, (k) => setDoor(k), ease.inOut);
    const entitled = docSheets.filter((d) => d.userData.entry.tone === C.good);
    let read = 0;
    for (const d of entitled) {
      s.scale(d, 0.62, 0.9, ease.inOut).catch(() => {});
      await s.glide(d, [SLOT.x - 0.75 + read * 1.5, 6.1, 1.6], 0.9, 1.2);
      read += 1; ctx.setCounters([{ label: 'Documents read', value: read }, { label: 'AI calls', value: 0 }]);
      await s.wait(0.15);
    }
    const locked = docSheets.find((d) => d.userData.entry.tone === C.bad);
    if (locked) { lock.position.set(locked.position.x, locked.position.y, 0.25); lock.visible = true; say('<b>Stayed out</b><small>above the caller’s clearance</small>', new THREE.Vector3(x0 + locked.position.x, 5.4, 0), { tone: 'bad' }); }
    const q = view.egress ? 1 : 0;
    ctx.setCounters([{ label: 'Documents read', value: read }, { label: 'AI calls', value: q }]);
  }

  // -------------------------------------------------------------- sources
  async function playSource(s, which) {
    clearTemp(); clearTags(); hideScene(); showVault(); card.visible = false;
    buildLibrary([{ head: 'House view', body: 'Owner: Chief Investment Office. Version 1.', tone: C.good, stamp: { text: 'APPROVED', color: C.good } },
      { head: 'Memo', body: 'Looks relevant. Nobody approved it.', tone: C.amber, dashed: true }]);
    await appear(s, avatars.agent);
    const wants = say('<b>The AI wants a source</b>', avatars.agent, { offset: [0, 3.4, 0] });
    const target = docSheets[which === 'approved' ? 0 : 1];
    await s.wait(0.4);
    const p = packet(C.cyan, 0.3); p.position.copy(hand()); temp.add(p);
    await s.glide(p, [VAULT_AT.x - 1.4, 2.8, 1.6], 1.0, 0.6);
    setGate('wait');
    await s.wait(0.5);
    ctx.labels.remove(wants);
    if (which === 'approved') {
      setGate('ok'); await s.tween(0.7, (k) => setDoor(k), ease.inOut); temp.remove(p);
      s.scale(target, 1.2, 1.0, ease.inOut).catch(() => {});
      await s.glide(target, [SLOT.x + 2.2, 3.2, 2.8], 1.0, 1.2);
      say('<b>✓ On the approved register</b>', target, { offset: [0, 1.9, 0], tone: 'good' });
    } else {
      setGate('bad'); ctx.flash('#ff6b6b'); p.userData.set(C.bad);
      await s.tween(0.7, (k) => setDoor(k * 0.45), ease.inOut);
      const x = icon('cross', C.bad, 1.1); x.position.set(target.position.x, 3.0, 0.4); temp.add(x);
      await s.scale(x, 1, 0.35, ease.back);
      for (let i = 0; i < 4; i++) { target.position.x += (i % 2 ? -0.14 : 0.14); await s.wait(0.05); }
      await s.glide(p, [SLOT.x + 0.7, 1.7, SLOT.z], 0.7, 0.2); shards(s, temp, p.position.clone(), C.bad); temp.remove(p);
      say('<b>✕ Not on the register</b><small>refused, however relevant it looks</small>', target, { offset: [0, 1.6, 0], tone: 'bad' });
    }
  }

  // -------------------------------------------------------------- privacy
  /** Lay text out in chunks so highlighted spans (names, tokens) never split across lines. */
  function chunks(line, marks) {
    if (!marks.length) return line.split(/(\s+)/).filter(Boolean).map((t) => ({ t, hit: false }));
    const re = new RegExp(`(${marks.map((m) => m.replace(/[.*+?^${'$'}{}()|[\]\\]/g, '\\$&')).join('|')})`, 'g');
    return line.split(re).filter(Boolean).flatMap((part) => (marks.includes(part) ? [{ t: part, hit: true }] : part.split(/(\s+)/).filter(Boolean).map((t) => ({ t, hit: false }))));
  }

  function drawText(lines, marks, tone) {
    return (g, W, H) => {
      g.clearRect(0, 0, W, H); g.fillStyle = '#eef3f9'; roundRect(g, 4, 4, W - 8, H - 8, W * 0.03); g.fill();
      g.fillStyle = css(tone); roundRect(g, 4, 4, W - 8, H * 0.15, W * 0.03); g.fill(); g.fillRect(4, H * 0.09, W - 8, H * 0.06);
      g.fillStyle = '#0d1b2e'; g.textBaseline = 'middle'; g.font = `800 ${W * 0.05}px ${FONT}`; g.fillText(lines.title, W * 0.05, H * 0.082);
      g.textBaseline = 'alphabetic'; g.font = `650 ${W * 0.062}px ${FONT}`;
      const lh = W * 0.1, maxX = W * 0.95; let y = H * 0.3;
      for (const line of lines.body) {
        let x = W * 0.05;
        for (const c of chunks(line, marks)) {
          const w = g.measureText(c.t).width;
          if (x + w > maxX && c.t.trim()) { x = W * 0.05; y += lh; }
          if (!c.t.trim() && x === W * 0.05) continue;
          if (c.hit) { g.fillStyle = lines.markColor; roundRect(g, x - 4, y - W * 0.058, w + 8, W * 0.078, 7); g.fill(); g.fillStyle = '#0d1b2e'; } else g.fillStyle = '#31475f';
          g.fillText(c.t, x, y); x += w;
        }
        y += lh * 1.25;
      }
    };
  }

  async function playPrivacy(s, which, step) {
    clearTemp(); clearTags(); hideScene(); privacy.visible = true;
    const pv = step.privacy, pairs = pv.pairs;
    const originals = pairs.map((p) => p.original), tokens = pairs.map((p) => p.token);
    ctx.setCounters([{ label: 'Details sent out', value: 0 }]);
    avatars.agent.visible = true; avatars.agent.position.copy(BANK); avatars.agent.rotation.y = 0.9;
    pedestal.visible = true; pedestal.position.copy(BANK);
    say('<b>Inside the bank</b>', new THREE.Vector3(x0 + BANK.x, 4.4, 0), { tone: 'gold' });
    say('<b>Outside AI provider</b><small>a local stand-in in this demo</small>', new THREE.Vector3(x0 + 6.0, 5.6, 0), { tone: '' });
    const W = 3.9, Hh = 2.5;
    const firstSentence = (t) => t.split(/(?<=\.)\s/)[0];
    const lines2 = (a) => a.slice(0, 2);
    const make = (lines, marks, tone) => panel(W, Hh, drawText(lines, marks, tone), { ppu: 190 });
    const mk = (title, body, markColor) => ({ title, body, markColor });
    await s.wait(0.2);

    if (which === 'block') {
      const file = sheet({ w: 2.0, h: 2.6, title: 'CONFIDENTIAL', lines: ['Highest handling level. Not for any outside party.'], tone: C.bad, dashed: true });
      file.position.set(-3.0, 3.4, 1.6); temp.add(file); file.scale.setScalar(0.001); await s.scale(file, 1, 0.4, ease.back);
      const fileTag = say('<b>Highly confidential file</b>', file, { offset: [0, 1.6, 0], tone: 'bad' });
      await s.glide(file, [filter.position.x - 1.2, 2.9, 0.8], 1.0, 0.6);
      ringMat.color.set(C.bad); ringMat.emissive.set(C.bad); ctx.flash('#ff6b6b');
      ringPulse(s, temp, filter.position.clone(), C.bad, { rotY: GATE_ROT, to: 3.4 }).catch(() => {});
      await s.glide(file, [-3.0, 3.4, 1.6], 0.8, 0.5);
      ctx.labels.remove(fileTag);
      shards(s, temp, file.position.clone(), C.bad); temp.remove(file);
      const st = stampMesh('STOPPED', C.bad); st.position.set(0.8, 4.9, 1.4); st.scale.setScalar(2.4); temp.add(st);
      await s.scale(st, 1, 0.45, ease.bounce);
      say('<b>Nothing left the bank</b>', new THREE.Vector3(x0 + 0.4, 6.6, 0), { tone: 'bad', cls: 'big', delay: 0.4 });
      return;
    }
    ringMat.color.set(C.cyan); ringMat.emissive.set(C.cyan);
    const out = make(mk('QUESTION · REAL DETAILS', lines2(pv.before), '#ffd89a'), originals, C.amber);
    out.position.set(-2.6, 3.6, 2.0); temp.add(out); out.scale.setScalar(0.001); await s.scale(out, 1, 0.45, ease.back);
    const realTag = say('<b>Real names and numbers</b>', out, { offset: [0, 1.4, 0], tone: 'warn' });
    await s.wait(0.9);
    await s.glide(out, [filter.position.x - 0.6, 3.0, 0.9], 1.0, 0.4);
    ringPulse(s, temp, filter.position.clone(), C.cyan, { rotY: GATE_ROT, to: 3.2 }).catch(() => {});
    ctx.labels.remove(realTag);                 // the words change at the gate, so this label ends here
    await s.scale(out, 0.85, 0.2);
    out.userData.redraw(drawText(mk('QUESTION · WHAT THE PROVIDER SEES', lines2(pv.after), '#9fe4ff'), tokens, C.cyan));
    await s.scale(out, 1, 0.25, ease.back);
    ctx.setCounters([{ label: 'Details sent out', value: 0 }]);
    await s.glide(out, [cloud.position.x - 2.6, 3.4, 0.9], 1.1, 0.5);
    const replacedTag = say(`<b>${pairs.length} details replaced</b><small>placeholders only</small>`, out, { offset: [0, 1.5, 0], tone: '' });
    await s.wait(0.8);
    ctx.labels.remove(replacedTag);
    temp.remove(out);
    const back = make(mk('REPLY · FROM THE PROVIDER', [firstSentence(pv.reply_out)], '#9fe4ff'), tokens, C.cyan);
    back.position.set(cloud.position.x - 2.6, 3.4, 0.9); temp.add(back);
    await s.glide(back, [filter.position.x + 0.4, 3.0, 0.9], 1.1, 0.5);
    ringPulse(s, temp, filter.position.clone(), C.good, { rotY: GATE_ROT, to: 3.2 }).catch(() => {});
    back.userData.redraw(drawText(mk('REPLY · RESTORED FOR THE BANK', [firstSentence(pv.reply_in)], '#9de6c2'), originals, C.good));
    await s.glide(back, [-2.6, 3.6, 2.0], 1.1, 0.5);
    say('<b>Real names restored</b><small>only inside the bank</small>', back, { offset: [0, 1.5, 0], tone: 'good' });
  }

  // ------------------------------------------------------------- interface
  const cams = {
    'know-roles': { pos: [0.2, 5.2, 17.4], look: [-0.1, 2.6, 0], dur: 2.4, arc: 3, fit: 8.4 },
    'know-border': { pos: [0.2, 5.8, 19.0], look: [-0.1, 3.1, 0], dur: 1.8, arc: 1, fit: 8.6 },
    'know-sources': { pos: [0.2, 5.2, 17.4], look: [-0.1, 2.6, 0], dur: 1.6, arc: 1, fit: 8.4 },
    'know-privacy': { pos: [0.9, 5.6, 19.6], look: [0.9, 3.0, 0], dur: 1.8, arc: 1, fit: 8.6 },
  };
  return {
    group,
    camera: (id) => {
      const c = cams[id] || cams['know-roles'];
      return { ...c, pos: [x0 + c.pos[0], c.pos[1], c.pos[2]], look: [x0 + c.look[0], c.look[1], c.look[2]] };
    },
    async enter(id, step, s) {
      clearTemp(); clearTags(); hideScene();
      pedestal.position.copy(SLOT); avatars.agent.position.copy(SLOT);
      ctx.setCounters(null);
      const order = { 'know-roles': 1, 'know-border': 0, 'know-sources': 0, 'know-privacy': 0 };
      if (id === 'know-roles') { showVault(); resetFile('sealed'); say('<b>Who is asking?</b>', at(-5.6, 3.6), { cls: 'big' }); }
      if (id === 'know-border') { showVault(); buildLibrary([{ head: 'Approved', body: 'House guidance', tone: C.good }, { head: 'Approved', body: 'Policy library', tone: C.good }, { head: 'Confidential', body: 'Steering note', tone: C.bad, dashed: true }]); }
      if (id === 'know-sources') { showVault(); buildLibrary([{ head: 'House view', body: 'Owner: Chief Investment Office. Version 1.', tone: C.good, stamp: { text: 'APPROVED', color: C.good } }, { head: 'Memo', body: 'Looks relevant. Nobody approved it.', tone: C.amber, dashed: true }]); }
      if (id === 'know-privacy') { privacy.visible = true; avatars.agent.visible = true; avatars.agent.position.copy(BANK); pedestal.visible = true; pedestal.position.copy(BANK); say('<b>Inside the bank</b>', at(BANK.x, 4.4), { tone: 'gold' }); say('<b>Outside AI provider</b><small>a local stand-in in this demo</small>', at(6.0, 5.6), {}); }
      // Each chapter step arrives alive: play the most telling choice first.
      await s.wait(1.4);
      ctx.autoChoose(order[id]);
    },
    async choose(id, choiceId, step, s) {
      if (id === 'know-roles') return playRole(s, choiceId);
      if (id === 'know-border') return playBorder(s, choiceId, step);
      if (id === 'know-sources') return playSource(s, choiceId);
      if (id === 'know-privacy') return playPrivacy(s, choiceId, step);
    },
  };
}
