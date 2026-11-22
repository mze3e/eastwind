#!/usr/bin/env node
// Drive every step and every choice of the 3D walkthrough at several window sizes and look for layout problems.
//
//   node scripts/check_story.cjs                        # build the site, serve it, check laptop, tablet and phone
//   node scripts/check_story.cjs --all                  # every size listed below
//   node scripts/check_story.cjs --sizes phone,laptop --steps know-border,do-stop
//   node scripts/check_story.cjs --base http://127.0.0.1:8301/story/   # use a server that is already running
//
// A "state" is a step as it arrives, and then the step after each of its choices. For each state the script waits
// for the choreography to finish, then checks, in the window's own pixels:
//   - nothing on the page chrome runs off the screen, and the page does not scroll sideways;
//   - the top bar, the caption, the counters, the footer and any open drawer do not overlap one another;
//   - the labels in the picture are not cut off by the window, do not cover the chrome or the caption, and do not
//     pile on top of one another;
//   - no text is clipped inside its box, and every button and link is at least 24 by 24 pixels (WCAG 2.5.8);
//   - every button has a name a screen reader can say, and the step is announced.
// It also opens the talk page and the one-pager at each size: no sideways scroll, every picture loaded, no small
// buttons, and the same console, request and CSP rules.
// Once per size it also tabs through the page (skip link first, a visible focus ring on every stop, nothing
// off screen), checks that Escape closes the drawers, and that the arrow keys move between steps.
// Across the whole run it fails on any console error, uncaught exception, failed request or CSP violation.
//
// It writes a screenshot of every state and a contact sheet per size to --out, and exits 1 if anything is wrong.
// Software rendering is slow (about 7 frames a second), so the choreography is sped up with --speed.
// Needs Playwright and Chromium. Without --base it also needs the Python environment to build the site.
const fs = require('fs');
const os = require('os');
const net = require('net');
const path = require('path');
const { spawn, spawnSync } = require('child_process');

let chromium;
try { ({ chromium } = require('playwright')); } catch (error) {
  console.error('This check needs Playwright: npm install playwright && npx playwright install chromium');
  process.exit(2);
}

const ROOT = path.resolve(__dirname, '..');
const SIZES = {
  desktop: [1440, 810], laptop: [1280, 720], 'tablet-wide': [1024, 768],
  tablet: [768, 1024], phone: [390, 844], 'phone-landscape': [844, 390],
};
const TOUCH = new Set(['tablet-wide', 'tablet', 'phone', 'phone-landscape']);
const QUICK = ['laptop', 'tablet', 'phone'];

function parse(argv) {
  const options = { sizes: QUICK, steps: null, base: null, out: path.join(os.tmpdir(), 'eastwind-story-check'), speed: 8 };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i], value = () => argv[++i];
    if (a === '--all') options.sizes = Object.keys(SIZES);
    else if (a === '--sizes') options.sizes = value().split(',');
    else if (a === '--steps') options.steps = value().split(',');
    else if (a === '--base') options.base = value();
    else if (a === '--out') options.out = path.resolve(value());
    else if (a === '--speed') options.speed = Number(value());
    else { console.error(`unknown option ${a}`); process.exit(2); }
  }
  for (const size of options.sizes) if (!SIZES[size]) { console.error(`unknown size ${size}; choose from ${Object.keys(SIZES).join(', ')}`); process.exit(2); }
  return options;
}

/** Build the site into a temporary folder and serve it with the headers vercel.json sets. */
async function startServer() {
  const port = await new Promise((resolve) => { const s = net.createServer().listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => resolve(p)); }); });
  const site = fs.mkdtempSync(path.join(os.tmpdir(), 'eastwind-site-'));
  const args = ['scripts/build_demo_page.py', '--output', path.join(site, 'index.html'), '--serve', '--port', String(port)];
  const haveUv = spawnSync('uv', ['--version']).status === 0;
  const child = haveUv ? spawn('uv', ['run', 'python', ...args], { cwd: ROOT }) : spawn('python3', args, { cwd: ROOT });
  let log = '';
  child.stderr.on('data', (d) => { log += d; });
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`the site did not start in 3 minutes\n${log}`)), 180000);
    child.stdout.on('data', (d) => { log += d; if (/Serving/.test(String(d))) { clearTimeout(timer); resolve(); } });
    child.on('exit', (code) => { clearTimeout(timer); reject(new Error(`the site build stopped (${code})\n${log}`)); });
  });
  return { base: `http://127.0.0.1:${port}/story/`, stop: () => child.kill() };
}

// ------------------------------------------------------------------ in the page
// These run inside the browser, so they use nothing from this file.

function inspectLayout() {
  const problems = [];
  const vw = window.innerWidth, vh = window.innerHeight;
  const rect = (el) => { const r = el.getBoundingClientRect(); return { l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height }; };
  const shown = (el) => {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || el.closest('[hidden]')) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const overlap = (a, b) => Math.max(0, Math.min(a.r, b.r) - Math.max(a.l, b.l)) * Math.max(0, Math.min(a.b, b.b) - Math.max(a.t, b.t));
  const label = (el) => {
    const id = el.id ? `#${el.id}` : el.className && typeof el.className === 'string' ? `.${el.className.split(' ')[0]}` : el.tagName.toLowerCase();
    const text = (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 30);
    return text ? `${id} "${text}"` : id;
  };
  const all = (selector, root = document) => [...root.querySelectorAll(selector)].filter(shown);

  if (document.documentElement.scrollWidth > vw + 1) problems.push(`the page scrolls sideways (${document.documentElement.scrollWidth}px wide in a ${vw}px window)`);

  const panel = document.getElementById('panel');
  const compact = document.body.hasAttribute('data-compact');
  const panelBox = rect(panel);
  // In a sheet or rail the caption scrolls inside its panel, so only the part that shows can overlap anything.
  const clip = (box) => {
    if (!compact) return box;
    const l = Math.max(box.l, panelBox.l), t = Math.max(box.t, panelBox.t), r = Math.min(box.r, panelBox.r), b = Math.min(box.b, panelBox.b);
    return r > l && b > t ? { l, t, r, b, w: r - l, h: b - t } : null;
  };

  const groups = {
    'top bar': all('.brand, #chapters, .tools button'),
    'footer': all('.foot .nav button, .foot .dots, .pathinfo, .honest'),
    'caption': all('.kicker, #title, #point, .legend li, .result, .choices button, .taglog, .map, .callouts div').map((el) => ({ el, clipped: true })),
    'counters': all('.counter'),
    'drawer': all('.drawer'),
  };
  const boxes = [];
  for (const [group, items] of Object.entries(groups)) {
    for (const item of items) {
      const el = item.el || item;
      const box = item.clipped ? clip(rect(el)) : rect(el);
      if (box && box.w > 0 && box.h > 0) boxes.push({ group, el, box });
    }
  }

  for (const { group, el, box } of boxes) {
    if (box.l < -1 || box.t < -1 || box.r > vw + 1 || box.b > vh + 1) problems.push(`${group}: ${label(el)} runs off the screen`);
  }
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i], b = boxes[j];
      if (a.el.contains(b.el) || b.el.contains(a.el)) continue;
      if (a.group === b.group && a.group !== 'caption') continue;
      if (overlap(a.box, b.box) > 6) problems.push(`${a.group} ${label(a.el)} overlaps ${b.group} ${label(b.el)}`);
    }
  }

  // The caption itself must fit in the panel it sits in, or at least be reachable by scrolling it.
  if (compact && panel.scrollHeight > panel.clientHeight + 1 && getComputedStyle(panel).overflowY === 'visible') problems.push('the caption is taller than its panel and cannot scroll');

  // Labels in the picture.
  const tags = all('#labels .tag').filter((el) => Number(getComputedStyle(el).opacity) > 0.9);
  const tagBoxes = tags.map((el) => ({ el, box: rect(el) }));
  for (const { el, box } of tagBoxes) {
    if (box.l < -1 || box.t < -1 || box.r > vw + 1 || box.b > vh + 1) problems.push(`label ${label(el)} is cut off by the window edge`);
    for (const other of boxes) {
      if (overlap(box, other.box) > 6) problems.push(`label ${label(el)} covers ${other.group} ${label(other.el)}`);
    }
  }
  for (let i = 0; i < tagBoxes.length; i++) {
    for (let j = i + 1; j < tagBoxes.length; j++) {
      const a = tagBoxes[i], b = tagBoxes[j];
      const smaller = Math.min(a.box.w * a.box.h, b.box.w * b.box.h);
      if (smaller > 0 && overlap(a.box, b.box) / smaller > 0.25) problems.push(`labels ${label(a.el)} and ${label(b.el)} overlap`);
    }
  }

  // Text that does not fit its box.
  for (const el of all('.choices button, .tag, .tile, .result, #point, #title, .legend li, .honest, .pathinfo, .foot button, .tools button, .counter, .kicker')) {
    if (el.scrollWidth > el.clientWidth + 1) problems.push(`text is clipped in ${label(el)}`);
  }

  // Touch targets. Links inside a sentence are exempt, as the guideline allows.
  const targets = all('button, a[href]').filter((el) => !el.matches('.skip') && !(el.tagName === 'A' && el.closest('p, li, .tile')));
  for (const el of targets) {
    const r = el.getBoundingClientRect();
    if (r.right < 0 || r.left > vw || r.bottom < 0 || r.top > vh) continue;
    if (r.width < 23.5 || r.height < 23.5) problems.push(`${label(el)} is only ${Math.round(r.width)} by ${Math.round(r.height)} pixels`);
  }

  // Names a screen reader can say.
  for (const el of document.querySelectorAll('button, a[href]')) {
    const name = (el.getAttribute('aria-label') || el.textContent || el.title || '').trim();
    if (!name) problems.push(`${label(el)} has no accessible name`);
  }
  if (!document.getElementById('announce').textContent.trim()) problems.push('the step was not announced');
  const here = document.querySelectorAll('#chapters [aria-current]').length;
  if (here !== 1) problems.push(`${here} chapter buttons say they are current`);
  if (!document.getElementById('title').textContent.trim()) problems.push('the step has no title');
  return problems;
}

function pageBasics() {
  const problems = [];
  if (!document.documentElement.lang) problems.push('the page has no language');
  if (!document.title.trim()) problems.push('the page has no title');
  if (document.querySelectorAll('h1').length !== 1) problems.push(`the page has ${document.querySelectorAll('h1').length} h1 headings`);
  if (document.querySelectorAll('main').length !== 1) problems.push('the page needs exactly one main landmark');
  const skip = document.querySelector('a.skip');
  if (!skip || !document.querySelector(skip.getAttribute('href'))) problems.push('the skip link does not lead anywhere');
  const ids = [...document.querySelectorAll('[id]')].map((el) => el.id);
  const dupes = ids.filter((id, i) => ids.indexOf(id) !== i);
  if (dupes.length) problems.push(`repeated ids: ${[...new Set(dupes)].join(', ')}`);
  return problems;
}

function describeFocus() {
  const el = document.activeElement;
  if (!el || el === document.body) return null;
  const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
  return {
    name: (el.getAttribute('aria-label') || el.textContent || el.title || el.tagName).trim().replace(/\s+/g, ' ').slice(0, 30),
    skip: el.matches('a.skip'),
    inWindow: r.left >= -1 && r.top >= -1 && r.right <= window.innerWidth + 1 && r.bottom <= window.innerHeight + 1 && r.width > 0,
    ring: cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) >= 2,
  };
}

// ------------------------------------------------------------------ the run

const slug = (text) => text.replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '').toLowerCase();

async function settle(page) {
  await page.waitForFunction(() => window.eastwindStory.busy() === 0, null, { timeout: 90000, polling: 200 });
  // Transitions and entrance animations that have an end; the pulsing nudge on the choices never ends.
  await page.evaluate(() => Promise.all(document.getAnimations()
    .filter((a) => a.effect && a.effect.getComputedTiming().iterations !== Infinity)
    .map((a) => a.finished.catch(() => {}))));
  await page.waitForTimeout(250);
}

async function checkSize(browser, base, name, options, report) {
  const [width, height] = SIZES[name];
  const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1, isMobile: TOUCH.has(name), hasTouch: TOUCH.has(name) });
  const page = await context.newPage();
  let where = 'loading';
  const note = (problem) => report.push({ size: name, where, problem });
  page.on('pageerror', (error) => note(`uncaught exception: ${error.message}`));
  page.on('console', (message) => { if (message.type() === 'error') note(`console error: ${message.text()}`); });
  page.on('requestfailed', (request) => note(`request failed: ${request.url()}`));
  page.on('response', (response) => { if (response.status() >= 400 && !/favicon/.test(response.url())) note(`${response.status()} for ${response.url()}`); });
  await page.addInitScript(() => document.addEventListener('securitypolicyviolation', (event) => { (window.__csp = window.__csp || []).push(`${event.violatedDirective} blocked ${event.blockedURI}`); }));

  await page.goto(base);
  await page.waitForFunction(() => window.eastwindStory, null, { timeout: 60000 });
  await page.evaluate((speed) => window.eastwindStory.speed(speed), options.speed);
  const steps = await page.evaluate(() => window.eastwindStory.steps);
  const wanted = options.steps ? steps.filter((s) => options.steps.includes(s)) : steps;

  where = 'page basics';
  for (const problem of await page.evaluate(pageBasics)) note(problem);

  const folder = path.join(options.out, name);
  fs.rmSync(folder, { recursive: true, force: true });
  fs.mkdirSync(folder, { recursive: true });
  const shots = [];
  let count = 0;

  const capture = async (step, choice) => {
    where = choice === null ? step : `${step} › choice ${choice + 1}`;
    await settle(page);
    const found = await page.evaluate(inspectLayout);
    for (const problem of [...new Set(found)].slice(0, 12)) note(problem);
    const file = `${String(++count).padStart(2, '0')}-${slug(step)}${choice === null ? '' : `-c${choice + 1}`}.png`;
    await page.screenshot({ path: path.join(folder, file) });
    shots.push({ file, title: where, bad: found.length > 0 });
  };

  for (const step of wanted) {
    await page.evaluate((s) => window.eastwindStory.go(window.eastwindStory.steps.indexOf(s)), step);
    await capture(step, null);
    const choices = await page.evaluate(() => document.querySelectorAll('#choices button').length);
    for (let i = 0; i < choices; i++) {
      await page.evaluate((n) => window.eastwindStory.choose(n), i);
      await capture(step, i);
    }
    if (step === 'welcome') await page.evaluate(() => window.eastwindStory.setPath('full'));   // the welcome choices pick a path
  }

  // Keyboard, once per size, from the first step.
  where = 'keyboard';
  await page.evaluate(() => { window.eastwindStory.go(0); document.activeElement && document.activeElement.blur(); });
  await settle(page);
  const stops = [];
  for (let i = 0; i < 14; i++) { await page.keyboard.press('Tab'); stops.push(await page.evaluate(describeFocus)); }
  if (!stops[0] || !stops[0].skip) note(`the first Tab stop is ${stops[0] ? `"${stops[0].name}"` : 'nothing'}, not the skip link`);
  for (const stop of stops.filter(Boolean)) {
    if (!stop.inWindow) note(`Tab reaches "${stop.name}" but it is off screen`);
    if (!stop.ring) note(`"${stop.name}" shows no focus ring`);
  }
  await page.evaluate(() => document.activeElement && document.activeElement.blur());
  await page.keyboard.press('n');
  if (await page.evaluate(() => document.getElementById('notes').hidden)) note('N did not open the talk track');
  await page.keyboard.press('Escape');
  if (await page.evaluate(() => !document.getElementById('notes').hidden)) note('Escape did not close the talk track');
  const before = await page.evaluate(() => window.eastwindStory.current);
  await page.keyboard.press('ArrowRight');
  const after = await page.evaluate(() => window.eastwindStory.current);
  if (after === before) note('the right arrow did not move to the next step');
  await page.keyboard.press('ArrowLeft');
  if ((await page.evaluate(() => window.eastwindStory.current)) !== before) note('the left arrow did not come back');

  where = 'security policy';
  for (const violation of await page.evaluate(() => window.__csp || [])) note(`CSP violation: ${violation}`);

  await contactSheet(browser, folder, name, shots, width);
  await context.close();
  return count;
}

/** The two static pages that sit beside the walkthrough: the talk page and the one-pager. */
async function checkPages(browser, base, name, options, report) {
  const [width, height] = SIZES[name];
  const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1, isMobile: TOUCH.has(name), hasTouch: TOUCH.has(name) });
  const page = await context.newPage();
  let where = '';
  const note = (problem) => report.push({ size: name, where, problem });
  page.on('pageerror', (error) => note(`uncaught exception: ${error.message}`));
  page.on('console', (message) => { if (message.type() === 'error') note(`console error: ${message.text()}`); });
  page.on('requestfailed', (request) => note(`request failed: ${request.url()}`));
  page.on('response', (response) => { if (response.status() >= 400 && !/favicon/.test(response.url())) note(`${response.status()} for ${response.url()}`); });
  await page.addInitScript(() => document.addEventListener('securitypolicyviolation', (event) => { (window.__csp = window.__csp || []).push(`${event.violatedDirective} blocked ${event.blockedURI}`); }));
  for (const route of ['../', '../onepager/']) {
    where = new URL(route, base).pathname;
    await page.goto(new URL(route, base).href);
    await page.waitForLoadState('load');
    const found = await page.evaluate(() => {
      const problems = [];
      if (document.documentElement.scrollWidth > window.innerWidth + 1) problems.push(`the page scrolls sideways (${document.documentElement.scrollWidth}px wide in a ${window.innerWidth}px window)`);
      for (const img of document.images) if (!img.complete || img.naturalWidth === 0) problems.push(`the picture ${img.getAttribute('src')} did not load`);
      for (const el of document.querySelectorAll('button, a[href]')) {
        const r = el.getBoundingClientRect();
        if (r.width > 0 && !el.closest('p, li') && (r.width < 23.5 || r.height < 23.5)) problems.push(`"${(el.textContent || '').trim().slice(0, 24)}" is only ${Math.round(r.width)} by ${Math.round(r.height)} pixels`);
      }
      if (document.querySelectorAll('h1').length !== 1) problems.push(`${document.querySelectorAll('h1').length} h1 headings`);
      if (!document.documentElement.lang) problems.push('no language set');
      return problems;
    });
    for (const problem of found) note(problem);
    for (const violation of await page.evaluate(() => window.__csp || [])) note(`CSP violation: ${violation}`);
    await page.screenshot({ path: path.join(options.out, `${name}-${route === '../' ? 'talk' : 'onepager'}.png`), fullPage: true });
  }
  await context.close();
}

/** One image per size with every state side by side, the ones with problems outlined in red. */
async function contactSheet(browser, folder, name, shots, width) {
  const thumb = width >= 1000 ? 420 : width >= 700 ? 300 : 200;
  const columns = Math.max(2, Math.floor(1800 / (thumb + 12)));
  const cells = shots.map((s) => `<figure class="${s.bad ? 'bad' : ''}"><img src="${s.file}" width="${thumb}" alt=""><figcaption>${s.title}</figcaption></figure>`).join('');
  const html = `<!doctype html><meta charset="utf-8"><style>body{margin:0;padding:12px;background:#222;font:12px system-ui;color:#ddd;width:${columns * (thumb + 12)}px}
    main{display:flex;flex-wrap:wrap;gap:12px}figure{margin:0;width:${thumb}px}img{display:block;border:2px solid #444}figure.bad img{border-color:#f55}figcaption{padding-top:3px}</style><main>${cells}</main>`;
  const file = path.join(folder, 'contact.html');
  fs.writeFileSync(file, html);
  const page = await browser.newPage({ viewport: { width: columns * (thumb + 12) + 24, height: 800 } });
  await page.goto(`file://${file}`);
  await page.waitForLoadState('load');
  await page.screenshot({ path: path.join(path.dirname(folder), `contact-${name}.png`), fullPage: true });
  await page.close();
}

(async () => {
  const options = parse(process.argv.slice(2));
  fs.mkdirSync(options.out, { recursive: true });
  let server = null, base = options.base;
  if (!base) { console.log('Building and serving the site...'); server = await startServer(); base = server.base; }
  const browser = await chromium.launch({ args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const report = [];
  const started = Date.now();
  try {
    for (const name of options.sizes) {
      const [w, h] = SIZES[name];
      const before = report.length;
      const states = await checkSize(browser, base, name, options, report);
      await checkPages(browser, base, name, options, report);
      const found = report.length - before;
      console.log(`${found ? 'FAIL' : 'ok  '} ${name} ${w}x${h}: ${states} states, ${found} problem${found === 1 ? '' : 's'}`);
    }
  } finally {
    await browser.close();
    if (server) server.stop();
  }
  fs.writeFileSync(path.join(options.out, 'report.json'), JSON.stringify(report, null, 2));
  for (const { size, where, problem } of report) console.log(`  [${size}] ${where}: ${problem}`);
  console.log(`Screenshots and contact sheets: ${options.out}  (${Math.round((Date.now() - started) / 1000)}s)`);
  process.exit(report.length ? 1 : 0);
})().catch((error) => { console.error(error); process.exit(2); });
