#!/usr/bin/env python3
"""Build the public Eastwind site: the talk page and the 3D walkthrough.

The talk page shows the stdout of these commands, in order, on one fresh store:

    eastwind run deny --fresh
    eastwind run allow --echo-model
    eastwind verify

The walkthrough in web/story replays a real Kognita run captured by eastwind.story. Both are
built offline. OPENAI_API_KEY is cleared before those commands run. The live chat callable
is replaced with a refusal for the duration of the build, so this script
cannot take the OpenAI path.

    uv run python scripts/build_demo_page.py             # writes public/
    uv run python scripts/build_demo_page.py --serve     # and serves it on 127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

from eastwind import __version__ as eastwind_version
from eastwind.cli import main as eastwind_main
from eastwind.openai_chat import OpenAIChat
from eastwind.pack import CLIENTS, KNOWLEDGE
from kognita import __version__ as kognita_version

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "public" / "index.html"
WEB = REPO_ROOT / "web"

_CHECK_LINE = re.compile(r"^  (PASS|FAIL|ESCALATE|HUMAN)\s+(\S+)\s+(.+?)\s*$")
_DETAIL_LINE = re.compile(r"^ {18}(.*)$")
_VERIFY_LINE = re.compile(r"evidence chain verified: (\d+) events")

_COMMANDS: tuple[tuple[str, list[str]], ...] = (
    ("deny", ["run", "deny", "--fresh"]),
    ("allow", ["run", "allow", "--echo-model"]),
    ("verify", ["verify"]),
)


@dataclass(frozen=True)
class CheckRow:
    mark: str
    regime: str
    citation: str
    detail: str


@dataclass(frozen=True)
class DemoTranscripts:
    deny: str
    allow: str
    verify: str
    provider: str
    restored: str
    deny_checks: tuple[CheckRow, ...]
    allow_checks: tuple[CheckRow, ...]
    verify_events: int


def _refuse_live_model(self: OpenAIChat, redacted: str) -> str:
    raise RuntimeError("the talk page refused a live model call")


def _run(argv: list[str], cwd: Path) -> str:
    stdout = StringIO()
    stderr = StringIO()
    previous = Path.cwd()
    try:
        os.chdir(cwd)
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = eastwind_main(argv)
    finally:
        os.chdir(previous)
    if code != 0:
        detail = stderr.getvalue().strip() or stdout.getvalue().strip() or f"exit {code}"
        raise RuntimeError(f"eastwind {' '.join(argv)} failed: {detail}")
    return stdout.getvalue()


def _parse_checks(transcript: str) -> tuple[CheckRow, ...]:
    rows: list[CheckRow] = []
    lines = transcript.splitlines()
    index = 0
    while index < len(lines):
        match = _CHECK_LINE.match(lines[index])
        if match is None:
            index += 1
            continue
        detail = ""
        if index + 1 < len(lines):
            detail_match = _DETAIL_LINE.match(lines[index + 1])
            if detail_match is not None:
                detail = detail_match.group(1).strip()
                index += 1
        rows.append(
            CheckRow(
                mark=match.group(1),
                regime=match.group(2),
                citation=match.group(3).strip(),
                detail=detail,
            )
        )
        index += 1
    return tuple(rows)


def _between(transcript: str, start: str, end: str | None) -> str:
    chunk = transcript.split(start, 1)[1]
    if end is not None:
        chunk = chunk.split(end, 1)[0]
    lines: list[str] = []
    for line in chunk.splitlines():
        if line.startswith("    "):
            lines.append(line[4:])
        elif line.strip():
            lines.append(line.strip())
    return "\n".join(lines).strip()


def _require(transcript: str, needle: str, label: str) -> None:
    if needle not in transcript:
        raise RuntimeError(f"{label} is missing {needle!r}")


def capture_demo() -> DemoTranscripts:
    """Run the three projector commands on a temporary store."""
    saved_key = os.environ.get("OPENAI_API_KEY")
    saved_provider = os.environ.get("EASTWIND_LLM_PROVIDER")
    os.environ["OPENAI_API_KEY"] = ""
    os.environ["EASTWIND_LLM_PROVIDER"] = "mock"
    original_call = OpenAIChat.__call__
    OpenAIChat.__call__ = _refuse_live_model  # type: ignore[method-assign]
    try:
        with tempfile.TemporaryDirectory(prefix="eastwind-demo-") as raw:
            cwd = Path(raw)
            transcripts = {
                name: _run(argv, cwd) for name, argv in _COMMANDS
            }
    finally:
        OpenAIChat.__call__ = original_call  # type: ignore[method-assign]
        if saved_key is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = saved_key
        if saved_provider is None:
            os.environ.pop("EASTWIND_LLM_PROVIDER", None)
        else:
            os.environ["EASTWIND_LLM_PROVIDER"] = saved_provider

    deny = transcripts["deny"]
    allow = transcripts["allow"]
    verify = transcripts["verify"]

    _require(deny, "Decision  DENY", "DENY")
    _require(deny, "HK_SFC", "DENY")
    _require(deny, "DIFC_DFSA", "DENY")
    _require(deny, "Retrieval  not called", "DENY")
    _require(deny, "Model call not made", "DENY")
    _require(allow, "Decision  ALLOW", "ALLOW")
    _require(allow, "Egress     REDACT", "ALLOW")
    _require(allow, "[TERM_1]", "ALLOW")
    _require(allow, "[EMAIL_1]", "ALLOW")
    _require(allow, "[ACCOUNT_1]", "ALLOW")
    _require(allow, "OpenAI was not called.", "ALLOW")
    _require(allow, "OpenAI was not contacted.", "ALLOW")
    _require(verify, "evidence chain verified:", "verify")

    house_view = next(
        item["title"] for item in KNOWLEDGE if str(item["title"]).startswith("House view")
    )
    _require(allow, house_view, "ALLOW")
    if "Retrieval  not called" in allow:
        raise RuntimeError("ALLOW path did not retrieve")

    allowed = CLIENTS["CL-1001"]
    denied = CLIENTS["CL-2002"]
    if denied["email"] in deny or denied["account"] in deny:
        raise RuntimeError("DENY transcript included the denied client's identifiers")

    if "provider saw:" not in allow or "caller received" not in allow:
        raise RuntimeError("ALLOW transcript has no redacted/restored prompt")
    provider = _between(allow, "provider saw:", "caller received")
    restored = _between(allow, "caller received (tokens restored):", "Evidence")
    for planted in (allowed["name"], allowed["email"], allowed["account"]):
        if planted in provider:
            raise RuntimeError("redaction failed: a client identifier reached the provider side")
        if planted not in restored:
            raise RuntimeError("restore failed: a client identifier was missing from the caller side")
    for token in ("[TERM_1]", "[EMAIL_1]", "[ACCOUNT_1]"):
        if token not in provider:
            raise RuntimeError(f"provider side is missing {token}")

    deny_checks = _parse_checks(deny)
    by_regime = {row.regime: row for row in deny_checks}
    for regime in ("HK_SFC", "DIFC_DFSA"):
        row = by_regime.get(regime)
        if row is None or row.mark != "FAIL":
            raise RuntimeError(f"DENY did not fail closed on {regime}")

    verify_match = _VERIFY_LINE.search(verify)
    if verify_match is None:
        raise RuntimeError("verify did not report an event count")
    verify_events = int(verify_match.group(1))
    if verify_events < 1:
        raise RuntimeError("verify reported an empty chain")

    secret = saved_key or ""
    for transcript in (deny, allow, verify):
        if secret and secret in transcript:
            raise RuntimeError("a demo transcript contains OPENAI_API_KEY")

    return DemoTranscripts(
        deny=deny,
        allow=allow,
        verify=verify,
        provider=provider,
        restored=restored,
        deny_checks=deny_checks,
        allow_checks=_parse_checks(allow),
        verify_events=verify_events,
    )


def _esc(value: str) -> str:
    return html.escape(value, quote=True)


def _checks_html(rows: tuple[CheckRow, ...]) -> str:
    items: list[str] = []
    for row in rows:
        detail = f"<span class=\"detail\">{_esc(row.detail)}</span>" if row.detail else ""
        items.append(
            "<li class=\"check\">"
            f"<span class=\"mark mark-{row.mark.lower()}\">{_esc(row.mark)}</span>"
            f"<span class=\"regime\">{_esc(row.regime)}</span>"
            f"<span class=\"citation\">{_esc(row.citation)}</span>"
            f"{detail}"
            "</li>"
        )
    return "<ul class=\"checks\">" + "".join(items) + "</ul>"


def _pre(text: str, css: str) -> str:
    return f"<pre class=\"{css}\">{_esc(text.rstrip())}</pre>"


def _preview(name: str, alt: str) -> str:
    """An <img> for a preview still, only if the still exists, so a fresh checkout never shows a broken image."""
    if not (WEB / "story" / "previews" / f"{name}.jpg").is_file():
        return ""
    return (f'<img src="/story/previews/{name}.jpg" alt="{_esc(alt)}" width="1280" height="720" '
            'loading="lazy" decoding="async">')


_CARDS = (
    ("know", "know-roles", "Know", "What may it see?",
     "The AI sees only what the person asking is entitled to see. A request from the wrong desk is "
     "refused before anything is read, and client names never leave the bank.",
     "A Dubai request is blocked for four separate reasons, with nothing read and no AI call made."),
    ("do", "do-approval", "Do", "What may it do?",
     "The bank sets how independent the AI is. Big decisions wait for a named person, and an emergency "
     "stop beats an approval that was already given.",
     "An approved proposal is withheld at the release door when the stop is hit."),
    ("prove", "prove-tamper", "Prove", "What can we show?",
     "Every decision goes into a sealed record that anyone can check. Edit one entry and the break is "
     "found. Gaps in the record are listed, not hidden.",
     "One edited entry out of the whole record is caught, and the checker says exactly where."),
)


def render_html(demo: DemoTranscripts, *, built_at: datetime) -> str:
    stamp = built_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    fail_closed = next(
        (line.strip() for line in demo.deny.splitlines() if line.startswith("Fail closed.")),
        "",
    )
    fail_closed_html = f"<p class=\"fail-closed\">{_esc(fail_closed)}</p>" if fail_closed else ""
    hero_img = _preview("hero", "A friendly AI assistant with its job, manager and limits labelled around it")
    cards = "".join(
        f"""
      <a class="card {key}" href="/story/#{step}">
        <div class="shot">{_preview(key, alt)}</div>
        <div class="body">
          <p class="kick">{kicker}</p>
          <h2>{question}</h2>
          <p>{text}</p>
          <span class="go">See it in 3D &rarr;</span>
        </div>
      </a>"""
        for key, step, kicker, question, text, alt in _CARDS
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Governed Agents That Survive Audit - Eastwind Private</title>
  <meta name="description" content="A guided 3D walkthrough of an AI assistant at a fictional private bank: what it may see, what it may do, and the proof it leaves behind. Workshop fiction for Ahmed Muzammil's AgentCon Singapore talk.">
  <style>
    :root {{
      color-scheme: dark;
      --navy: #0b1626; --deep: #0f2036; --line: rgba(255,255,255,.11);
      --ink: #eaf1f9; --muted: #a9bbcf; --gold: #e5b567;
      --cyan: #4cc9f0; --amber: #ffb547; --blue: #7aa2ff; --good: #3ecf8e; --bad: #ff6b6b;
      --serif: Georgia, "Iowan Old Style", Palatino, "Palatino Linotype", serif;
      --sans: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
      --mono: ui-monospace, "Cascadia Code", "Source Code Pro", Menlo, Consolas, monospace;
    }}
    * {{ box-sizing: border-box; }}
    html {{ font-size: 18px; }}
    body {{ margin: 0; background: radial-gradient(1200px 600px at 70% -10%, #17314f 0%, var(--navy) 60%); color: var(--ink); font-family: var(--sans); line-height: 1.55; }}
    a {{ color: var(--cyan); }}
    .banner {{ background: #05101d; border-bottom: 1px solid var(--line); color: var(--muted); padding: .7rem 1.4rem; font-size: .9rem; }}
    .banner strong {{ color: var(--gold); }}
    .wrap {{ max-width: 74rem; margin: 0 auto; padding: 2rem 1.4rem 3.5rem; }}
    .hero {{ display: grid; grid-template-columns: 1.05fr 1fr; gap: 2.2rem; align-items: center; padding: 1.2rem 0 2.4rem; }}
    .eyebrow {{ margin: 0; color: var(--gold); font-size: .85rem; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; }}
    h1 {{ font: 700 clamp(2.2rem, 4.6vw, 3.6rem)/1.05 var(--serif); margin: .5rem 0 .8rem; letter-spacing: -.015em; }}
    .meta {{ margin: 0 0 1rem; color: var(--muted); font-size: .95rem; }}
    .lede {{ font-size: 1.18rem; color: #d7e3f1; max-width: 34rem; margin: 0 0 1.4rem; }}
    .cta {{ display: flex; flex-wrap: wrap; gap: .8rem; margin: 0 0 .9rem; }}
    .btn {{ display: inline-block; padding: .85rem 1.4rem; border-radius: 12px; border: 1px solid var(--line); background: rgba(255,255,255,.06); color: var(--ink); text-decoration: none; font-weight: 650; }}
    .btn:hover {{ background: rgba(255,255,255,.12); }}
    .btn.primary {{ background: var(--gold); border-color: var(--gold); color: #0b1626; font-weight: 800; font-size: 1.08rem; padding: .95rem 1.7rem; box-shadow: 0 10px 34px rgba(229,181,103,.28); }}
    .btn.primary:hover {{ filter: brightness(1.08); background: var(--gold); }}
    .keys {{ margin: 0; color: var(--muted); font-size: .85rem; }}
    kbd {{ font: 700 .75rem var(--mono); padding: .1rem .4rem; border-radius: 6px; background: rgba(255,255,255,.1); }}
    .hero .shot {{ border-radius: 18px; overflow: hidden; border: 1px solid var(--line); box-shadow: 0 24px 70px rgba(0,0,0,.5); background: var(--deep); aspect-ratio: 16 / 9; }}
    .hero .shot img, .card .shot img {{ display: block; width: 100%; height: 100%; object-fit: cover; }}
    .cards {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 1.1rem; margin: .5rem 0 2.2rem; }}
    .card {{ display: flex; flex-direction: column; border-radius: 16px; border: 1px solid var(--line); background: rgba(15,32,54,.7); text-decoration: none; color: inherit; overflow: hidden; transition: transform .18s, border-color .18s; }}
    .card:hover {{ transform: translateY(-3px); border-color: rgba(255,255,255,.3); }}
    .card .shot {{ aspect-ratio: 16 / 9; background: var(--deep); }}
    .card .body {{ padding: 1.1rem 1.2rem 1.3rem; display: flex; flex-direction: column; gap: .35rem; flex: 1; }}
    .kick {{ margin: 0; font-size: .8rem; font-weight: 800; letter-spacing: .14em; text-transform: uppercase; }}
    .card.know .kick {{ color: var(--cyan); }} .card.do .kick {{ color: var(--amber); }} .card.prove .kick {{ color: var(--blue); }}
    .card h2 {{ margin: 0; font: 700 1.5rem/1.15 var(--serif); }}
    .card p {{ margin: 0; color: #cfdbea; font-size: .98rem; }}
    .go {{ margin-top: auto; padding-top: .6rem; font-weight: 700; color: var(--ink); }}
    .honest {{ border: 1px solid var(--line); border-radius: 14px; padding: 1rem 1.2rem; background: rgba(255,255,255,.03); color: var(--muted); font-size: .95rem; }}
    .honest strong {{ color: var(--ink); }}
    .honest ul {{ margin: .4rem 0 0; padding-left: 1.2rem; }}
    details.mechanics {{ margin-top: 2rem; border: 1px solid var(--line); border-radius: 14px; background: rgba(8,16,28,.6); }}
    details.mechanics > summary {{ cursor: pointer; padding: 1rem 1.2rem; font-weight: 700; font-size: 1.05rem; }}
    details.mechanics > .inner {{ padding: 0 1.2rem 1.4rem; }}
    section.run {{ margin-top: 1.4rem; border: 1px solid var(--line); border-radius: 12px; padding: 1rem 1.1rem 1.2rem; background: rgba(255,255,255,.03); }}
    section.deny {{ border-top: 6px solid var(--bad); }} section.allow {{ border-top: 6px solid var(--good); }} section.verify {{ border-top: 6px solid var(--blue); }}
    .section-kicker {{ margin: 0; font-size: .8rem; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }}
    h3 {{ margin: .15rem 0 .35rem; font: 700 1.6rem/1.1 var(--serif); }}
    .command {{ display: inline-block; margin: .2rem 0 .8rem; padding: .25rem .55rem; background: #050b14; color: #cfe3ff; border-radius: 6px; font-family: var(--mono); font-size: .88rem; }}
    .claim {{ margin-top: 0; }}
    .checks {{ list-style: none; padding: 0; margin: .8rem 0; }}
    .check {{ display: grid; grid-template-columns: 5.6rem 11rem 1fr; gap: .3rem .8rem; align-items: baseline; padding: .5rem 0; border-top: 1px solid var(--line); font-size: .92rem; }}
    .check .detail {{ grid-column: 2 / -1; color: var(--muted); font-size: .88rem; }}
    .mark {{ font-weight: 800; letter-spacing: .04em; font-size: .88rem; }}
    .mark-fail {{ color: var(--bad); }} .mark-pass {{ color: var(--good); }} .mark-escalate, .mark-human {{ color: var(--amber); }}
    .regime {{ font-family: var(--mono); font-weight: 700; }}
    .fail-closed {{ background: rgba(255,107,107,.14); color: #ffb3b3; padding: .7rem .85rem; border-radius: 8px; font-weight: 650; }}
    .pair {{ display: grid; grid-template-columns: 1fr 1fr; gap: .9rem; margin-top: .6rem; }}
    .panel {{ border-radius: 10px; padding: .75rem .8rem .9rem; }}
    .panel h4 {{ margin: 0 0 .45rem; font-size: .85rem; letter-spacing: .06em; text-transform: uppercase; }}
    .panel.provider {{ background: rgba(255,107,107,.12); }} .panel.provider h4 {{ color: #ffb3b3; }}
    .panel.restored {{ background: rgba(62,207,142,.12); }} .panel.restored h4 {{ color: #9de6c2; }}
    .verify-result {{ margin: .4rem 0 .8rem; font: 700 1.7rem/1.15 var(--serif); color: var(--blue); }}
    pre {{ margin: 0; white-space: pre-wrap; word-break: break-word; font: .84rem/1.4 var(--mono); color: #dbe7f5; }}
    details.out {{ margin-top: 1rem; }} details.out > summary {{ cursor: pointer; font-weight: 650; }}
    details.out pre {{ margin-top: .6rem; background: #050b14; padding: .9rem 1rem; border-radius: 8px; }}
    footer {{ margin-top: 2rem; color: var(--muted); font-size: .88rem; }}
    footer p {{ margin: .35rem 0; }}
    @media (max-width: 900px) {{
      html {{ font-size: 17px; }}
      .hero {{ grid-template-columns: 1fr; }} .cards {{ grid-template-columns: 1fr; }}
      .check {{ grid-template-columns: 5.2rem 1fr; }} .check .citation {{ grid-column: 1 / -1; }}
      .pair {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="banner">
    <strong>Workshop fiction.</strong>
    Eastwind Private is a fictional institution. The clients, products, and citations on this page are not real and are not legal advice.
  </div>
  <div class="wrap">
    <header class="hero">
      <div>
        <p class="eyebrow">AgentCon Singapore · 5 November 2026</p>
        <h1>An AI colleague that can show its work</h1>
        <p class="meta">Talk: Governed Agents That Survive Audit · Ahmed Muzammil · Eastwind Private</p>
        <p class="lede">Watch one AI assistant do real work at a private bank, and see how it is kept safe: what it may see, what it may do, and the proof it leaves behind.</p>
        <div class="cta">
          <a class="btn primary" href="/story/">Start the walkthrough &rarr;</a>
          <a class="btn" href="/admin/">Open the live admin console</a>
        </div>
        <p class="keys">Presenting? <kbd>&larr;</kbd> <kbd>&rarr;</kbd> to move, <kbd>1</kbd> <kbd>2</kbd> <kbd>3</kbd> to choose, <kbd>N</kbd> talk track, <kbd>M</kbd> mechanics, <kbd>F</kbd> full screen.</p>
      </div>
      <div class="shot">{hero_img}</div>
    </header>

    <section class="cards" aria-label="The three questions">{cards}
    </section>

    <section class="honest" aria-label="How to read this">
      <strong>What is real here.</strong>
      <ul>
        <li>The bank, its clients and every citation are invented for the talk. The data is synthetic.</li>
        <li>The AI model is an offline stand-in. No provider is contacted and no key is used.</li>
        <li>The decisions are real Kognita results. The walkthrough replays a run made when this page was built, so it does not depend on a live system in the room.</li>
      </ul>
    </section>

    <details class="mechanics">
      <summary>Show the mechanics: the command transcripts behind the story</summary>
      <div class="inner">
        <section class="run deny" id="deny">
          <p class="section-kicker">Cross-border structured note · AE</p>
          <h3>DENY</h3>
          <code class="command">eastwind run deny --fresh</code>
          <p class="claim">HK_SFC and DIFC_DFSA both fail. Retrieval is not called. The model is not called.</p>
          {_checks_html(demo.deny_checks)}
          {fail_closed_html}
          <details class="out" open>
            <summary>Command output</summary>
            {_pre(demo.deny, "transcript")}
          </details>
        </section>

        <section class="run allow" id="allow">
          <p class="section-kicker">Singapore money market · SG</p>
          <h3>ALLOW</h3>
          <code class="command">eastwind run allow --echo-model</code>
          <p class="claim">The house view in zone SG at ceiling C2 is retrieved. The prompt is classified C2. Egress returns REDACT. The provider side sees placeholder tokens. The caller sees those tokens restored. The reply is a local echo.</p>
          {_checks_html(demo.allow_checks)}
          <div class="pair">
            <div class="panel provider">
              <h4>Provider saw · redacted</h4>
              {_pre(demo.provider, "provider")}
            </div>
            <div class="panel restored">
              <h4>Caller received · restored</h4>
              {_pre(demo.restored, "restored")}
            </div>
          </div>
          <details class="out" open>
            <summary>Command output</summary>
            {_pre(demo.allow, "transcript")}
          </details>
        </section>

        <section class="run verify" id="verify">
          <p class="section-kicker">Same store, after DENY then ALLOW</p>
          <h3>Hash chain</h3>
          <code class="command">eastwind verify</code>
          <p class="verify-result">{_esc(demo.verify.strip())}</p>
          <p class="claim">{demo.verify_events} events recomputed from the hash chain. The chain is intact.</p>
          <details class="out" open>
            <summary>Command output</summary>
            {_pre(demo.verify, "transcript")}
          </details>
        </section>
      </div>
    </details>

    <footer>
      <p><strong>Workshop fiction.</strong> Eastwind Private, its clients, and every citation above are invented for this talk.</p>
      <p>Built { _esc(stamp) } from eastwind { _esc(eastwind_version) } and kognita { _esc(kognita_version) }, by running the three commands above on a temporary store. The published site is this static page and the 3D walkthrough it links to.</p>
    </footer>
  </div>
</body>
</html>
"""


def build_page(output: Path) -> str:
    """Build the landing page only. This is what the offline tests check."""
    demo = capture_demo()
    page = render_html(demo, built_at=datetime.now(timezone.utc))
    if "Workshop fiction." not in page or "Eastwind Private is a fictional institution." not in page:
        raise RuntimeError("the page is missing the workshop-fiction label")
    secret = os.environ.get("OPENAI_API_KEY", "")
    if secret and secret in page:
        raise RuntimeError("the page contains OPENAI_API_KEY")
    destination = output if output.is_absolute() else REPO_ROOT / output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(page, encoding="utf-8")
    return page


#: Files the published site must contain, relative to its root.
SITE_FILES = (
    "index.html", "story/index.html", "story/story.css", "story/app.js", "story/data.json",
    "vendor/three/three.module.js", "vendor/three/three.core.js", "vendor/three/LICENSE",
)


def build_site(root: Path) -> None:
    """Landing page, 3D walkthrough, vendored three.js, and the data the walkthrough replays."""
    from eastwind.story import story_json

    root = root if root.is_absolute() else REPO_ROOT / root
    build_page(root / "index.html")
    for source, target in ((WEB / "story", root / "story"), (WEB / "vendor", root / "vendor")):
        shutil.copytree(source, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns("data.json"))
    payload = story_json()
    secret = os.environ.get("OPENAI_API_KEY", "")
    if secret and secret in payload:
        raise RuntimeError("the story data contains OPENAI_API_KEY")
    (root / "story" / "data.json").write_text(payload, encoding="utf-8")
    missing = [name for name in SITE_FILES if not (root / name).is_file()]
    if missing:
        raise RuntimeError(f"the site is missing: {', '.join(missing)}")


def _vercel_headers() -> list[dict]:
    return json.loads((REPO_ROOT / "vercel.json").read_text(encoding="utf-8")).get("headers", [])


def _matches(source: str, path: str) -> bool:
    if source.endswith("/:path*"):
        return path == source[: -len("/:path*")] or path.startswith(source[: -len(":path*")])
    return source == path


def serve(root: Path, port: int) -> None:
    """Serve the built site on loopback with the headers vercel.json sets, so local equals deployed."""
    import functools
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    rules = _vercel_headers()

    class Handler(SimpleHTTPRequestHandler):
        def end_headers(self) -> None:
            path = self.path.split("?", 1)[0]
            sent: set[str] = set()
            for rule in rules:
                if _matches(rule["source"], path):
                    for header in rule["headers"]:
                        if header["key"] not in sent:  # several rules can match one path
                            sent.add(header["key"])
                            self.send_header(header["key"], header["value"])
            super().end_headers()

        def log_message(self, *args) -> None:  # keep the presenter's terminal quiet
            pass

    handler = functools.partial(Handler, directory=str(root))
    with ThreadingHTTPServer(("127.0.0.1", port), handler) as server:
        print(f"Serving {root} at http://127.0.0.1:{port}/  (Ctrl-C to stop)")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Eastwind site: the talk page and the 3D walkthrough.")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="landing page to write (default: public/index.html); the site is built in the same folder",
    )
    parser.add_argument("--serve", action="store_true", help="after building, serve the site on 127.0.0.1")
    parser.add_argument("--port", type=int, default=8000, help="port for --serve (default 8000)")
    args = parser.parse_args(argv)
    try:
        output = args.output if args.output.is_absolute() else REPO_ROOT / args.output
        build_site(output.parent)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {output.parent}")
    if args.serve:
        serve(output.parent, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
