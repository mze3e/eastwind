#!/usr/bin/env python3
"""Build the public AgentCon page from the offline projector commands.

The page is the stdout of these commands, in order, on one fresh store:

    eastwind run deny --fresh
    eastwind run allow --echo-model
    eastwind verify

OPENAI_API_KEY is cleared before those commands run. The live chat callable
is replaced with a refusal for the duration of the build, so this script
cannot take the OpenAI path.
"""

from __future__ import annotations

import argparse
import html
import os
import re
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
    os.environ["OPENAI_API_KEY"] = ""
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


def render_html(demo: DemoTranscripts, *, built_at: datetime) -> str:
    stamp = built_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    fail_closed = next(
        (line.strip() for line in demo.deny.splitlines() if line.startswith("Fail closed.")),
        "",
    )
    fail_closed_html = f"<p class=\"fail-closed\">{_esc(fail_closed)}</p>" if fail_closed else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Governed Agents That Survive Audit — Eastwind Private</title>
  <meta name="description" content="Workshop fiction for Ahmed Muzammil's AgentCon Singapore talk. Offline DENY, ALLOW echo, and evidence verify.">
  <style>
    :root {{
      color-scheme: light;
      --ink: #1c1915;
      --muted: #514a40;
      --paper: #f4f0e6;
      --card: #fffdf8;
      --line: #ddd4c4;
      --deny: #7a221c;
      --deny-bg: #f8e6e1;
      --allow: #1a5340;
      --allow-bg: #e3f2ea;
      --verify: #1a3358;
      --verify-bg: #e4ebf6;
      --banner: #2a2118;
      --banner-ink: #fff8ee;
    }}
    * {{ box-sizing: border-box; }}
    html {{ font-size: 20px; }}
    body {{
      margin: 0;
      background: var(--paper);
      color: var(--ink);
      font-family: Georgia, "Iowan Old Style", Palatino, "Palatino Linotype", serif;
      line-height: 1.45;
    }}
    a {{ color: var(--verify); }}
    .banner {{
      background: var(--banner);
      color: var(--banner-ink);
      padding: 0.85rem 1.4rem;
      font-family: "Segoe UI", system-ui, sans-serif;
      font-size: 1rem;
      letter-spacing: 0.01em;
    }}
    .banner strong {{ font-weight: 700; }}
    .wrap {{
      max-width: 70rem;
      margin: 0 auto;
      padding: 1.6rem 1.4rem 3.5rem;
    }}
    header.talk h1 {{
      font-size: 2.5rem;
      line-height: 1.08;
      margin: 0.25rem 0 0.6rem;
      font-weight: 700;
    }}
    .eyebrow, .meta, nav, .command, .section-kicker, footer {{
      font-family: "Segoe UI", system-ui, sans-serif;
    }}
    .eyebrow {{
      margin: 0;
      color: var(--muted);
      font-size: 0.95rem;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}
    .meta {{
      margin: 0.2rem 0 0;
      font-size: 1.15rem;
    }}
    .lede {{
      font-size: 1.2rem;
      max-width: 46rem;
    }}
    nav {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.6rem;
      margin: 1.2rem 0 0.4rem;
    }}
    nav a {{
      text-decoration: none;
      border: 2px solid var(--ink);
      border-radius: 999px;
      padding: 0.25rem 0.85rem;
      color: var(--ink);
      font-weight: 650;
      background: var(--card);
    }}
    section {{
      margin-top: 1.8rem;
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 0.7rem;
      padding: 1.15rem 1.2rem 1.3rem;
      scroll-margin-top: 0.8rem;
    }}
    section.deny {{ border-top: 8px solid var(--deny); }}
    section.allow {{ border-top: 8px solid var(--allow); }}
    section.verify {{ border-top: 8px solid var(--verify); }}
    .section-kicker {{
      margin: 0;
      font-size: 0.85rem;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--muted);
    }}
    h2 {{
      margin: 0.15rem 0 0.35rem;
      font-size: 2rem;
      line-height: 1.1;
    }}
    .command {{
      display: inline-block;
      margin: 0.2rem 0 0.8rem;
      padding: 0.25rem 0.55rem;
      background: #241f1a;
      color: #f6f1e7;
      border-radius: 0.35rem;
      font-family: ui-monospace, "Cascadia Code", "Source Code Pro", Menlo, Consolas, monospace;
      font-size: 0.95rem;
    }}
    .claim {{ margin-top: 0; font-size: 1.15rem; }}
    .checks {{
      list-style: none;
      padding: 0;
      margin: 0.8rem 0;
    }}
    .check {{
      display: grid;
      grid-template-columns: 6.2rem 11rem 1fr;
      gap: 0.35rem 0.8rem;
      align-items: baseline;
      padding: 0.55rem 0;
      border-top: 1px solid var(--line);
      font-family: "Segoe UI", system-ui, sans-serif;
    }}
    .check .detail {{
      grid-column: 2 / -1;
      color: var(--muted);
      font-size: 0.95rem;
    }}
    .mark {{
      font-weight: 750;
      letter-spacing: 0.04em;
      font-size: 0.95rem;
    }}
    .mark-fail {{ color: var(--deny); }}
    .mark-pass {{ color: var(--allow); }}
    .mark-escalate, .mark-human {{ color: #6a4a12; }}
    .regime {{
      font-family: ui-monospace, "Cascadia Code", Menlo, Consolas, monospace;
      font-weight: 700;
    }}
    .fail-closed {{
      background: var(--deny-bg);
      color: var(--deny);
      padding: 0.7rem 0.85rem;
      border-radius: 0.4rem;
      font-family: "Segoe UI", system-ui, sans-serif;
      font-weight: 650;
    }}
    .pair {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 0.9rem;
    }}
    .panel {{
      border-radius: 0.45rem;
      padding: 0.75rem 0.8rem 0.9rem;
    }}
    .panel h3 {{
      margin: 0 0 0.45rem;
      font-family: "Segoe UI", system-ui, sans-serif;
      font-size: 1rem;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}
    .panel.provider {{ background: var(--deny-bg); }}
    .panel.provider h3 {{ color: var(--deny); }}
    .panel.restored {{ background: var(--allow-bg); }}
    .panel.restored h3 {{ color: var(--allow); }}
    .verify-result {{
      margin: 0.4rem 0 0.8rem;
      font-size: 2rem;
      line-height: 1.15;
      color: var(--verify);
    }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: ui-monospace, "Cascadia Code", "Source Code Pro", Menlo, Consolas, monospace;
      font-size: 0.92rem;
      line-height: 1.4;
    }}
    .panel pre {{ background: transparent; color: var(--ink); padding: 0; }}
    details {{ margin-top: 1rem; }}
    summary {{
      cursor: pointer;
      font-family: "Segoe UI", system-ui, sans-serif;
      font-weight: 650;
    }}
    details pre {{
      margin-top: 0.6rem;
      background: #221e19;
      color: #f6f1e7;
      padding: 0.9rem 1rem;
      border-radius: 0.4rem;
    }}
    footer {{
      margin-top: 1.8rem;
      color: var(--muted);
      font-size: 0.95rem;
    }}
    footer p {{ margin: 0.35rem 0; }}
    @media (max-width: 800px) {{
      html {{ font-size: 18px; }}
      .check {{ grid-template-columns: 5.4rem 1fr; }}
      .check .citation {{ grid-column: 1 / -1; }}
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
    <header class="talk">
      <p class="eyebrow">AgentCon Singapore · 5 November 2026</p>
      <h1>Governed Agents That Survive Audit</h1>
      <p class="meta">Ahmed Muzammil · Eastwind Private</p>
      <p class="lede">A read-only record of the projector commands. An AE structured-note question is denied before retrieval or a model call. A Singapore money-market question is allowed, then shown as a redacted echo and the restored reply. The evidence hash chain verifies.</p>
      <p class="lede">Offline echo model only. This deployment does not set an API key and does not call OpenAI.</p>
      <nav>
        <a href="#deny">DENY</a>
        <a href="#allow">ALLOW</a>
        <a href="#verify">Verify</a>
      </nav>
    </header>

    <section class="deny" id="deny">
      <p class="section-kicker">Cross-border structured note · AE</p>
      <h2>DENY</h2>
      <code class="command">eastwind run deny --fresh</code>
      <p class="claim">HK_SFC and DIFC_DFSA both fail. Retrieval is not called. The model is not called.</p>
      {_checks_html(demo.deny_checks)}
      {fail_closed_html}
      <details open>
        <summary>Command output</summary>
        {_pre(demo.deny, "transcript")}
      </details>
    </section>

    <section class="allow" id="allow">
      <p class="section-kicker">Singapore money market · SG</p>
      <h2>ALLOW</h2>
      <code class="command">eastwind run allow --echo-model</code>
      <p class="claim">The house view in zone SG at ceiling C2 is retrieved. The prompt is classified C2. Egress returns REDACT. The provider side sees placeholder tokens. The caller sees those tokens restored. The reply is a local echo.</p>
      {_checks_html(demo.allow_checks)}
      <div class="pair">
        <div class="panel provider">
          <h3>Provider saw · redacted</h3>
          {_pre(demo.provider, "provider")}
        </div>
        <div class="panel restored">
          <h3>Caller received · restored</h3>
          {_pre(demo.restored, "restored")}
        </div>
      </div>
      <details open>
        <summary>Command output</summary>
        {_pre(demo.allow, "transcript")}
      </details>
    </section>

    <section class="verify" id="verify">
      <p class="section-kicker">Same store, after DENY then ALLOW</p>
      <h2>Hash chain</h2>
      <code class="command">eastwind verify</code>
      <p class="verify-result">{_esc(demo.verify.strip())}</p>
      <p class="claim">{demo.verify_events} events recomputed from the hash chain. The chain is intact.</p>
      <details open>
        <summary>Command output</summary>
        {_pre(demo.verify, "transcript")}
      </details>
    </section>

    <footer>
      <p><strong>Workshop fiction.</strong> Eastwind Private, its clients, and every citation above are invented for this talk.</p>
      <p>Built { _esc(stamp) } from eastwind { _esc(eastwind_version) } and kognita { _esc(kognita_version) }, by running the three commands above on a temporary store. The published site is this static page.</p>
    </footer>
  </div>
</body>
</html>
"""


def build_page(output: Path) -> str:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the static Eastwind talk page.")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="HTML file to write (default: public/index.html)",
    )
    args = parser.parse_args(argv)
    try:
        build_page(args.output)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
