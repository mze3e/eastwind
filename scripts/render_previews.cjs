#!/usr/bin/env node
// Render the preview stills the landing page uses, from the real 3D walkthrough.
//
//   uv run python scripts/build_demo_page.py        # writes public/ and web/story/data.json is not needed
//   node scripts/render_previews.cjs                # needs Playwright and Chromium
//
// It serves public/ on a loopback port, opens each step headless, lets the choreography finish,
// hides the page chrome, and writes web/story/previews/*.jpg. Software rendering is slow, so each
// capture waits for the animation to settle. The images are committed: the build does not need a
// browser, and the stills are refreshed by hand when the scenes change.
const http = require('http');
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const ROOT = path.resolve(__dirname, '..');
const PUBLIC = path.join(ROOT, 'public');
const OUT = path.join(ROOT, 'web', 'story', 'previews');

// [file, step, choice index or null, seconds to let it play, close camera or null]
// The cameras are tighter than the walkthrough's own, because a still has no caption panel to leave room for.
const SHOTS = [
  ['hero', 'colleague-hire', null, 14, null],
  ['know', 'know-border', 0, 30, { pos: [29.5, 4.6, 13.2], look: [29.5, 4.0, 0] }],
  ['do', 'do-stop', 0, 26, { pos: [61.0, 4.4, 12.6], look: [61.0, 3.0, 0] }],
  ['prove', 'prove-tamper', 0, 40, { pos: [90.2, 5.2, 13.4], look: [90.2, 4.9, 0] }],
];

const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json' };

function serve() {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      const url = decodeURIComponent(req.url.split('?')[0]);
      let file = path.join(PUBLIC, url.endsWith('/') ? url + 'index.html' : url);
      if (!file.startsWith(PUBLIC) || !fs.existsSync(file)) { res.writeHead(404); res.end(); return; }
      res.writeHead(200, { 'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream' });
      fs.createReadStream(file).pipe(res);
    }).listen(0, '127.0.0.1', () => resolve(server));
  });
}

(async () => {
  if (!fs.existsSync(path.join(PUBLIC, 'story', 'data.json'))) throw new Error('run scripts/build_demo_page.py first');
  fs.mkdirSync(OUT, { recursive: true });
  const server = await serve();
  const base = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({ args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  // Under 980px wide the caption panel is hidden and the scene is centred, which suits a still.
  const page = await browser.newPage({ viewport: { width: 960, height: 540 }, deviceScaleFactor: 2 });
  await page.goto(`${base}/story/index.html`);
  await page.waitForFunction(() => window.eastwindStory, null, { timeout: 30000 });
  await page.addStyleTag({ content: '.top,.foot,.choices,.drawer,.panel,.counters,#flash,.nogl,.loading{display:none!important}' });
  const only = process.argv.slice(2);   // optional shot names: node scripts/render_previews.cjs prove
  for (const [name, step, choice, seconds, cam] of SHOTS.filter(([n]) => !only.length || only.includes(n))) {
    await page.evaluate((s) => window.eastwindStory.go(window.eastwindStory.steps.indexOf(s)), step);
    await page.waitForTimeout(2500);
    if (choice !== null) await page.evaluate((i) => window.eastwindStory.choose(i), choice);
    await page.waitForTimeout(seconds * 1000);
    if (cam) { await page.evaluate((c) => window.eastwindStory.view(c), cam); await page.waitForTimeout(1500); }
    const file = path.join(OUT, `${name}.jpg`);
    await page.screenshot({ path: file, type: 'jpeg', quality: 86 });
    console.log('wrote', path.relative(ROOT, file), fs.statSync(file).size, 'bytes');
  }
  await browser.close();
  server.close();
})();
