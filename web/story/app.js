// App: loads the captured story, builds the world, and drives it step by step.
import { Stage, THREE } from './engine.js';
import { buildWorld } from './world.js';
import { buildColleague } from './st-colleague.js';
import { buildKnow } from './st-know.js';
import { buildDo } from './st-do.js';
import { buildProve } from './st-prove.js';

const $ = (id) => document.getElementById(id);
const el = (tag, props = {}, ...kids) => {
  const node = Object.assign(document.createElement(tag), props);
  for (const k of kids) node.append(k);
  return node;
};

async function boot() {
  const stage = new Stage($('stage'), $('labels'));
  if (!stage.hasGL) { $('nogl').hidden = false; document.body.classList.add('nogl'); }

  let payload;
  try {
    const res = await fetch('data.json', { cache: 'no-cache' });
    if (!res.ok) throw new Error(String(res.status));
    payload = await res.json();
  } catch (error) {
    $('loading').textContent = 'Could not load data.json. Serve this folder over http (see the README) rather than opening the file directly.';
    return;
  }
  const { data, story } = payload;

  // ------------------------------------------------------------ steps
  const steps = [];
  story.chapters.forEach((chapter) => chapter.steps.forEach((step) => steps.push({ ...step, chapter: chapter.id, chapterName: chapter.name, tag: chapter.tag })));
  const byId = new Map(steps.map((s, i) => [s.id, i]));

  let counters = null;
  const ctx = {
    stage, scene: stage.scene, labels: stage.labels, data, story, THREE,
    tag: (html, anchor, opts) => stage.labels.add(html, anchor, opts),
    flash(color = '#ff6b6b') { const f = $('flash'); f.style.setProperty('--flash', color); f.classList.add('on'); setTimeout(() => f.classList.remove('on'), 180); },
    setCounters(items) {
      if (counters) counters.remove();
      counters = null;
      if (!items) return;
      counters = el('div', { className: 'counters' });
      counters.style.cssText = 'top:4.1rem;left:calc(min(460px,38vw) + 2.4rem);right:1.2rem;justify-content:flex-start';
      for (const item of items) { const c = el('div', { className: 'counter' }, `${item.label}`); const b = el('b', { textContent: String(item.value) }); c.append(b); counters.append(c); item.node = b; }
      document.body.append(counters);
      return items;
    },
  };

  // Steps that arrive alive play their most telling choice first; the presenter can still pick another.
  ctx.autoChoose = (i) => { if (picked === null) choose(i); };
  const world = buildWorld(ctx);
  const stations = { welcome: world, recap: world, colleague: buildColleague(ctx), know: buildKnow(ctx), do: buildDo(ctx), prove: buildProve(ctx) };
  $('loading').classList.add('gone');

  // ----------------------------------------------------------- chrome
  const chapterButtons = [];
  const seenChapters = new Set();
  const chapters = story.chapters;
  chapters.forEach((chapter, ci) => {
    const first = byId.get(chapter.steps[0].id);
    const label = chapter.tag || chapter.name;
    const b = el('button', { type: 'button', textContent: label, title: chapter.name });
    b.addEventListener('click', () => go(first));
    chapterButtons.push(b); $('chapters').append(b);
  });

  const dotButtons = steps.map((s, i) => {
    const b = el('button', { type: 'button', title: s.title, ariaLabel: `Step ${i + 1}: ${s.title}` });
    if (i > 0 && steps[i - 1].chapter !== s.chapter) b.classList.add('gap');
    b.addEventListener('click', () => go(i));
    $('dots').append(el('li', {}, b)); return b;
  });

  $('honest').textContent = `Fiction. Synthetic data. The AI model is an offline stand-in; the decisions you see are real Kognita ${story.meta.kognita} results, replayed from a run built ${story.meta.built_at}.`;

  // ----------------------------------------------------------- state
  let current = -1, scope = null, choiceScope = null, picked = null;
  const seen = new Set();

  function renderPanel(step) {
    document.body.dataset.chapter = step.chapter;
    $('kicker').textContent = step.tag ? `${step.tag} · ${step.chapterName}` : step.chapterName;
    $('title').textContent = step.title;
    $('point').textContent = step.point;
    const legend = $('legend'); legend.replaceChildren();
    for (const [k, v] of step.legend || []) legend.append(el('li', {}, el('b', { textContent: k }), v));
    const callouts = $('callouts'); callouts.replaceChildren();
    for (const [k, v] of step.callouts || []) callouts.append(el('div', {}, el('dt', { textContent: k }), el('dd', { textContent: v })));
    const result = $('result'); result.hidden = true; result.textContent = ''; result.className = 'result';
    $('notes-text').textContent = step.say || '';
    $('mech-cmd').textContent = step.mechanics ? `$ ${step.mechanics.command}` : '';
    const table = $('mech-facts'); table.replaceChildren();
    for (const [k, v] of (step.mechanics && step.mechanics.facts) || []) table.append(el('tr', {}, el('td', { textContent: k }), el('td', { textContent: v })));
  }

  function renderChoices(step) {
    const box = $('choices'); box.replaceChildren();
    (step.choices || []).forEach((choice, i) => {
      const b = el('button', { type: 'button' }, el('kbd', { textContent: String(i + 1) }), choice.label);
      b.classList.add('nudge');
      b.addEventListener('click', () => choose(i));
      box.append(b);
    });
  }

  function renderChrome() {
    const step = steps[current];
    seenChapters.add(step.chapter);
    seen.add(current);
    chapters.forEach((c, i) => {
      const b = chapterButtons[i];
      if (c.id === step.chapter) b.setAttribute('aria-current', 'step'); else b.removeAttribute('aria-current');
      b.classList.toggle('done', seenChapters.has(c.id));
    });
    dotButtons.forEach((b, i) => { b.classList.toggle('on', i === current); b.classList.toggle('seen', i !== current && seen.has(i)); });
    $('btn-back').disabled = current === 0;
    $('btn-next').textContent = current === steps.length - 1 ? 'Start again' : current === 0 ? 'Start →' : 'Next →';
  }

  function go(index, { quiet = false } = {}) {
    if (index < 0 || index >= steps.length) return;
    const step = steps[index], first = current < 0;
    if (scope) scope.cancel(); if (choiceScope) choiceScope.cancel();
    stage.labels.clear(); ctx.setCounters(null);
    scope = stage.scope(); choiceScope = null; picked = null;
    current = index;
    const wide = step.chapter === 'welcome' || step.chapter === 'recap';
    document.body.dataset.layout = wide ? 'wide' : 'side'; stage.setWide(wide);
    renderPanel(step); renderChoices(step); renderChrome();
    if (!quiet) history.replaceState(null, '', `#${step.id}`);

    const station = stations[step.chapter];
    if (station && stage.hasGL) {
      const cam = station.camera(step.id) || station.camera('default');
      if (cam) stage.view(cam, { snap: first });
      world.setActive(step.chapter);
      scope.run((s) => station.enter(step.id, step, s, ctx));
    }
  }

  function choose(i) {
    const step = steps[current], choice = (step.choices || [])[i];
    if (!choice) return;
    picked = i;
    [...$('choices').children].forEach((b, k) => { b.classList.remove('nudge'); b.classList.toggle('picked', k === i); });
    const result = $('result'); result.hidden = false; result.textContent = choice.result; result.className = `result ${choice.tone || ''}`;
    result.style.animation = 'none'; void result.offsetWidth; result.style.animation = '';
    const station = stations[step.chapter];
    if (station && stage.hasGL) {
      if (choiceScope) choiceScope.cancel();
      choiceScope = stage.scope();
      choiceScope.run((s) => station.choose(step.id, choice.id, step, s, ctx));
    }
  }

  const next = () => (current === steps.length - 1 ? go(0) : go(current + 1));
  const back = () => go(current - 1);
  $('btn-next').addEventListener('click', next);
  $('btn-back').addEventListener('click', back);
  const toggle = (btn, drawer, other) => {
    const open = drawer.hidden; drawer.hidden = !open; btn.setAttribute('aria-pressed', String(open));
    if (open && other) { other.drawer.hidden = true; other.btn.setAttribute('aria-pressed', 'false'); }
  };
  const notes = { btn: $('btn-notes'), drawer: $('notes') }, mech = { btn: $('btn-mech'), drawer: $('mech') };
  notes.btn.addEventListener('click', () => toggle(notes.btn, notes.drawer, mech));
  mech.btn.addEventListener('click', () => toggle(mech.btn, mech.drawer, notes));
  $('btn-full').addEventListener('click', () => { if (document.fullscreenElement) document.exitFullscreen(); else document.documentElement.requestFullscreen?.(); });

  window.addEventListener('keydown', (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const k = e.key;
    if (k === 'ArrowRight' || k === 'PageDown' || k === ' ' || k === 'Enter') { if (document.activeElement && document.activeElement.tagName === 'BUTTON' && (k === ' ' || k === 'Enter')) return; e.preventDefault(); next(); }
    else if (k === 'ArrowLeft' || k === 'PageUp') { e.preventDefault(); back(); }
    else if (k === 'Home') go(0);
    else if (k === 'End') go(steps.length - 1);
    else if (/^[1-9]$/.test(k)) choose(Number(k) - 1);
    else if (k === 'n' || k === 'N') toggle(notes.btn, notes.drawer, mech);
    else if (k === 'm' || k === 'M') toggle(mech.btn, mech.drawer, notes);
    else if (k === 'f' || k === 'F') $('btn-full').click();
  });

  window.addEventListener('hashchange', () => { const i = byId.get(location.hash.slice(1)); if (i !== undefined && i !== current) go(i, { quiet: true }); });
  // A small hook for the preview renderer and for tests: step ids, navigation, and a camera override.
  window.eastwindStory = { go, choose, view: (cam) => stage.view(cam, { snap: true }), steps: steps.map((s) => s.id), get current() { return current; } };

  const start = byId.get(location.hash.slice(1));
  go(start !== undefined ? start : 0, { quiet: start === undefined });
}

boot();
