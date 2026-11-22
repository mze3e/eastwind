// App: loads the captured story, builds the world, and drives it step by step along a path.
import { Stage, THREE } from './engine.js';
import { buildWorld } from './world.js';
import { buildColleague } from './st-colleague.js';
import { buildKnow } from './st-know.js';
import { buildDo } from './st-do.js';
import { buildProve } from './st-prove.js';
import { buildBreak } from './st-break.js';

const $ = (id) => document.getElementById(id);
const el = (tag, props = {}, ...kids) => {
  const node = Object.assign(document.createElement(tag), props);
  for (const k of kids) node.append(k);
  return node;
};
const plain = (html) => { const d = document.createElement('div'); d.innerHTML = html; return d.textContent.replace(/\s+/g, ' ').trim(); };

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

  // ------------------------------------------------------------ steps and paths
  const steps = [];
  story.chapters.forEach((chapter) => chapter.steps.forEach((step) => steps.push({ ...step, chapter: chapter.id, chapterName: chapter.name, tag: chapter.tag })));
  const byId = new Map(steps.map((s, i) => [s.id, i]));
  const paths = new Map(story.paths.map((p) => [p.id, p]));
  let pathId = story.defaultPath, pathSet = new Set(paths.get(pathId).steps);
  const inPath = (i) => pathSet.has(steps[i].id);

  let counters = null;
  const ctx = {
    stage, scene: stage.scene, labels: stage.labels, data, story, THREE,
    // Every label in the picture is also written to a transcript, so nothing exists only as a drawing.
    tag(html, anchor, opts) {
      const text = plain(html);
      if (text && ![...$('taglog').children].some((li) => li.textContent === text)) $('taglog').append(el('li', { textContent: text }));
      return stage.labels.add(html, anchor, opts);
    },
    flash(color = '#ff6b6b') { const f = $('flash'); f.style.setProperty('--flash', color); f.classList.add('on'); setTimeout(() => f.classList.remove('on'), 180); },
    setCounters(items) {
      if (counters) counters.remove();
      counters = null;
      if (!items) return;
      counters = el('div', { className: 'counters', ariaHidden: 'true' });
      for (const item of items) { const c = el('div', { className: 'counter' }, `${item.label}`); const b = el('b', { textContent: String(item.value) }); c.append(b); counters.append(c); item.node = b; }
      document.body.append(counters);
      return items;
    },
  };

  // Steps that arrive alive play their most telling choice first; the presenter can still pick another.
  ctx.autoChoose = (i) => { if (picked === null) choose(i); };
  const world = buildWorld(ctx);
  const stations = {
    welcome: world, recap: world, more: world, colleague: buildColleague(ctx), know: buildKnow(ctx),
    do: buildDo(ctx), prove: buildProve(ctx), break: buildBreak(ctx),
  };
  $('loading').classList.add('gone');

  // ----------------------------------------------------------- chrome
  const chapterButtons = [];
  const seenChapters = new Set();
  const chapters = story.chapters;
  chapters.forEach((chapter) => {
    const b = el('button', { type: 'button', textContent: chapter.tag || chapter.name, title: chapter.name });
    b.addEventListener('click', () => {
      const ids = chapter.steps.map((s) => byId.get(s.id));
      const target = ids.find(inPath);
      if (target === undefined) { setPath('full'); go(ids[0]); } else go(target);
    });
    chapterButtons.push(b); $('chapters').append(b);
  });

  let dotButtons = [];
  function rebuildDots() {
    const box = $('dots'); box.replaceChildren(); dotButtons = [];
    let last = null;
    steps.forEach((s, i) => {
      if (!inPath(i)) return;
      const b = el('button', { type: 'button', title: s.title, ariaLabel: `Step: ${s.title}` });
      if (last !== null && last !== s.chapter) b.classList.add('gap');
      b.addEventListener('click', () => go(i));
      box.append(el('li', {}, b)); dotButtons.push([i, b]); last = s.chapter;
    });
  }

  $('honest').textContent = `Workshop fiction. Synthetic data. The AI model is an offline stand-in; the decisions you see are real Kognita ${story.meta.kognita} results, replayed from a run built ${story.meta.built_at}.`;

  // ----------------------------------------------------------- state
  let current = -1, scope = null, choiceScope = null, picked = null;
  const seen = new Set();

  function setPath(id) {
    if (!paths.has(id)) return;
    pathId = id; pathSet = new Set(paths.get(id).steps);
    rebuildDots(); if (current >= 0) { renderChrome(); writeUrl(); }
  }

  function writeUrl() {
    const search = pathId === story.defaultPath ? '' : `?path=${pathId}`;
    history.replaceState(null, '', `${location.pathname}${search}#${steps[current].id}`);
  }

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
    $('taglog').replaceChildren();
    renderMap(step);
    $('notes-text').textContent = step.say || '';
    $('mech-cmd').textContent = step.mechanics ? `$ ${step.mechanics.command}` : '';
    const table = $('mech-facts'); table.replaceChildren();
    for (const [k, v] of (step.mechanics && step.mechanics.facts) || []) table.append(el('tr', {}, el('td', { textContent: k }), el('td', { textContent: v })));
  }

  // The map of everything else: tiles that say honestly where each capability can be seen.
  function renderMap(step) {
    const box = $('map'); box.replaceChildren();
    box.hidden = !step.capabilities;
    if (!step.capabilities) return;
    const filters = [['all', 'All'], ['story', 'In this walkthrough'], ['console', 'In the console'], ['cli', 'On the command line'], ['none', 'Not demonstrated']];
    const bar = el('div', { className: 'mapbar', role: 'group', ariaLabel: 'Show' });
    const tiles = el('ul', { className: 'tiles' });
    const apply = (kind) => {
      for (const b of bar.children) b.setAttribute('aria-pressed', String(b.dataset.kind === kind));
      for (const li of tiles.children) li.hidden = !(kind === 'all' || li.dataset.kinds.split(' ').includes(kind));
    };
    for (const [kind, label] of filters) {
      const b = el('button', { type: 'button', textContent: label }); b.dataset.kind = kind;
      b.addEventListener('click', () => apply(kind)); bar.append(b);
    }
    const groupName = Object.fromEntries(step.groups);
    for (const cap of step.capabilities) {
      const kinds = cap.see.map((s) => s.kind);
      const li = el('li', { className: `tile g-${cap.group}` }); li.dataset.kinds = kinds.join(' ');
      const links = el('p', { className: 'where' });
      for (const s of cap.see) {
        if (s.kind === 'story') { links.append(el('a', { href: `#${s.step}`, textContent: `Watch it: ${s.label}` })); }
        else if (s.kind === 'console') { links.append(el('a', { href: `/admin${s.path}`, className: 'console', textContent: 'Open it in the console' })); }
        else if (s.kind === 'cli') { links.append(el('span', { textContent: 'On the command line: ' }), el('code', { textContent: s.command })); }
        else links.append(el('small', { textContent: 'Part of Kognita. Not demonstrated here.' }));
      }
      li.append(el('span', { className: 'chip', textContent: groupName[cap.group] }), el('h3', { textContent: cap.title }), el('p', { textContent: cap.promise }), links);
      tiles.append(li);
    }
    box.append(bar, tiles); apply('all');
    // The console exists only where the site was deployed with it, which the build records.
    box.classList.toggle('has-console', !!story.meta.console);
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

  const pathOrder = () => steps.map((s, i) => i).filter(inPath);
  const nextIndex = () => pathOrder().find((i) => i > current);
  const previousIndex = () => [...pathOrder()].reverse().find((i) => i < current);

  function renderChrome() {
    const step = steps[current];
    seenChapters.add(step.chapter);
    seen.add(current);
    chapters.forEach((c, i) => {
      const b = chapterButtons[i];
      if (c.id === step.chapter) b.setAttribute('aria-current', 'step'); else b.removeAttribute('aria-current');
      b.classList.toggle('done', seenChapters.has(c.id));
      b.classList.toggle('skipped', !c.steps.some((s) => pathSet.has(s.id)));
    });
    dotButtons.forEach(([i, b]) => { b.classList.toggle('on', i === current); b.classList.toggle('seen', i !== current && seen.has(i)); });
    const order = pathOrder(), position = order.indexOf(current);
    const p = paths.get(pathId);
    $('pathinfo').textContent = position >= 0 ? `${p.label} · step ${position + 1} of ${order.length}` : `${p.label}`;
    $('btn-back').disabled = previousIndex() === undefined;
    $('btn-next').textContent = nextIndex() === undefined ? 'Start again' : current === 0 ? 'Start →' : 'Next →';
  }

  function go(index, { quiet = false } = {}) {
    if (index < 0 || index >= steps.length) return;
    if (!inPath(index)) setPath('full');       // opening a step directly never hides it
    const step = steps[index], first = current < 0;
    if (scope) scope.cancel(); if (choiceScope) choiceScope.cancel();
    stage.labels.clear(); ctx.setCounters(null);
    scope = stage.scope(); choiceScope = null; picked = null;
    current = index;
    const layout = step.layout === 'map' ? 'map' : (step.chapter === 'welcome' || step.chapter === 'recap') ? 'wide' : 'side';
    document.body.dataset.layout = layout; stage.setWide(layout !== 'side');
    renderPanel(step); renderChoices(step); renderChrome();
    if (!quiet) writeUrl();

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
    if (choice.path) setPath(choice.path);
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

  const next = () => { const n = nextIndex(); go(n === undefined ? pathOrder()[0] : n); };
  const back = () => { const p = previousIndex(); if (p !== undefined) go(p); };
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
    const onControl = document.activeElement && ['BUTTON', 'A', 'INPUT', 'SELECT'].includes(document.activeElement.tagName);
    if (k === 'ArrowRight' || k === 'PageDown') { e.preventDefault(); next(); }
    else if ((k === ' ' || k === 'Enter') && !onControl) { e.preventDefault(); next(); }
    else if (k === 'ArrowLeft' || k === 'PageUp') { e.preventDefault(); back(); }
    else if (k === 'Home') go(pathOrder()[0]);
    else if (k === 'End') go(pathOrder().pop());
    else if (/^[1-9]$/.test(k)) choose(Number(k) - 1);
    else if (k === 'n' || k === 'N') toggle(notes.btn, notes.drawer, mech);
    else if (k === 'm' || k === 'M') toggle(mech.btn, mech.drawer, notes);
    else if (k === 'f' || k === 'F') $('btn-full').click();
  });

  window.addEventListener('hashchange', () => { const i = byId.get(location.hash.slice(1)); if (i !== undefined && i !== current) go(i, { quiet: true }); });
  // A small hook for the preview renderer and for tests: navigation, a camera override and a time scale.
  window.eastwindStory = {
    go, choose, setPath, view: (cam) => stage.view(cam, { snap: true }), speed: (n) => { stage.speed = n; },
    steps: steps.map((s) => s.id), get current() { return current; }, get path() { return pathId; },
  };

  const wanted = new URLSearchParams(location.search).get('path');
  rebuildDots();
  if (wanted && paths.has(wanted)) setPath(wanted);
  const start = byId.get(location.hash.slice(1));
  go(start !== undefined ? start : pathOrder()[0], { quiet: start === undefined && !wanted });
}

boot();
