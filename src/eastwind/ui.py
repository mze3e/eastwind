"""HTML for the console: plain English first, the mechanics one click away.

No JavaScript and no external resources, so the console keeps the strict content policy it
has always had. Every value is escaped unless it is explicitly wrapped in ``Raw``, which only
this module and the page code that builds markup from escaped parts use.
"""
from __future__ import annotations

import html as _html
from typing import Any, Iterable

#: What the console may load: its own markup and inline styles, nothing else.
CSP = ("default-src 'none'; style-src 'unsafe-inline'; connect-src 'self'; form-action 'self'; "
       "base-uri 'none'; frame-ancestors 'none'")


class Raw(str):
    """Markup that is already safe. Everything else passed to a helper is escaped."""


def esc(value: Any) -> str:
    return str(value) if isinstance(value, Raw) else _html.escape(str(value), quote=True)


def _flatten(items: Iterable[Any]) -> Iterable[Any]:
    for item in items:
        if item is None or item is False:
            continue
        if isinstance(item, (list, tuple)) and not isinstance(item, Raw):
            yield from _flatten(item)
        else:
            yield item


def h(tag_name: str, /, *kids: Any, cls: str | None = None, **attrs: Any) -> Raw:
    """Build one element. ``cls`` is the class; other attributes use underscores for hyphens."""
    parts = [tag_name]
    if cls:
        parts.append(f'class="{esc(cls)}"')
    for key, value in attrs.items():
        if value is None or value is False:
            continue
        key = key.rstrip("_").replace("_", "-")
        parts.append(key if value is True else f'{key}="{esc(value)}"')
    inner = "".join(esc(kid) for kid in _flatten(kids))
    return Raw(f"<{' '.join(parts)}>{inner}</{tag_name}>")


def void(tag_name: str, /, **attrs: Any) -> Raw:
    parts = [tag_name] + [f'{k.rstrip("_").replace("_", "-")}="{esc(v)}"' for k, v in attrs.items() if v is not None]
    return Raw(f"<{' '.join(parts)}>")


# ------------------------------------------------------------------ components

_ICONS = {
    "good": '<path d="M3 8.5l3.2 3.2L13 5"/>',
    "bad": '<path d="M4 4l8 8M12 4l-8 8"/>',
    "warn": '<path d="M8 3v6.5M8 12.5v.5"/>',
    "info": '<circle cx="8" cy="8" r="2.2"/>',
}


def icon(tone: str) -> Raw:
    return Raw(f'<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">{_ICONS.get(tone, _ICONS["info"])}</svg>')


def stamp(tone: str, text: str) -> Raw:
    """A plain-word verdict. The word carries the meaning; the colour only backs it up."""
    return h("span", icon(tone), text, cls=f"stamp {tone}")


def dot(tone: str) -> Raw:
    """A small status dot. The words beside it carry the meaning."""
    return h("i", cls=f"tdot {tone}", aria_hidden="true")


def card(*kids: Any, tone: str = "", cls: str = "") -> Raw:
    return h("section", *kids, cls=" ".join(x for x in ("card", tone, cls) if x))


def grid(*kids: Any, cols: int = 3) -> Raw:
    return h("div", *kids, cls=f"grid c{cols}")


def stat(label: str, value: Any, tone: str = "", note: str = "") -> Raw:
    return h("div", h("span", label, cls="k"), h("b", value, cls=f"v {tone}"), h("small", note) if note else None, cls="stat")


def mechanics(*kids: Any, summary: str = "Show the mechanics", open_: bool = False) -> Raw:
    """The raw data behind a page: codes, ids, hashes and JSON. Closed by default."""
    return h("details", h("summary", summary), h("div", *kids, cls="inner"), cls="mechanics", open=open_ or None)


def table(headers: Iterable[str], rows: Iterable[Iterable[Any]], cls: str = "") -> Raw:
    head = h("tr", [h("th", c, scope="col") for c in headers])
    body = [h("tr", [h("td", c) for c in row]) for row in rows]
    return h("div", h("table", h("thead", head), h("tbody", body)), cls=f"scroll {cls}".strip())


def pre(text: str) -> Raw:
    return h("pre", text)


def para(*kids: Any, cls: str = "") -> Raw:
    return h("p", *kids, cls=cls or None)


def button(label: str, tone: str = "primary", *, small: bool = False) -> Raw:
    return h("button", label, type="submit", cls=f"btn {tone}{' small' if small else ''}")


def action(url: str, label: str, *, hidden: dict[str, str] | None = None, fields: Iterable[Any] = (),
           tone: str = "primary", public_demo: bool = False, small: bool = False, note: str = "") -> Raw:
    """A form with one button. In local mode it also asks for the admin token, as every action always has."""
    inputs = [void("input", type="hidden", name=k, value=v) for k, v in (hidden or {}).items()]
    token = None if public_demo else h(
        "label", "Admin token ", void("input", type="password", name="token", required="required", autocomplete="off"),
        cls="token")
    return h("form", inputs, list(fields), token, button(label, tone, small=small), h("small", note) if note else None,
             method="post", action=url, cls="action")


def pills(items: Iterable[tuple[str, str]], active: str) -> Raw:
    """Links styled as a segmented control. Each item is (label, url); `active` is the url that is current."""
    return h("nav", [h("a", label, href=url, cls="on" if url == active else None,
                       aria_current="page" if url == active else None) for label, url in items], cls="pills")


def ladder(names: Iterable[str], current: int) -> Raw:
    """The seven independence levels, lowest first, with the registered one lit."""
    items = [h("li", h("b", f"L{i}"), h("span", name), cls=f"l{i}" + (" here" if i == current else " locked" if i > current else ""))
             for i, name in enumerate(names)]
    return h("ol", items, cls="ladder", aria_label="Independence levels, lowest first")


def meter(used: Any, maximum: Any, label: str) -> Raw:
    try:
        used_n, max_n = float(used), float(maximum)
    except (TypeError, ValueError):
        return h("span", label)
    if max_n <= 0:
        return h("span", label)
    return h("span", h("progress", f"{used} of {maximum}", value=used_n, max=max_n, cls="meter"), h("small", label), cls="metered")


def file_row(label: str, access: str, value: Any = None) -> Raw:
    """One row of a client file: shown, masked behind dots, or not available at all."""
    shown = (h("b", value) if access == "visible" else
             h("b", "••••••••••", cls="dots") if access == "masked" else h("i", "not available"))
    tag = {"visible": "", "masked": "Masked", "denied": "Not available"}[access]
    return h("div", h("span", label, cls="k"), shown, h("em", tag) if tag else None, cls=f"frow {access}")


def timeline(items: Iterable[tuple[str, str, str, str]]) -> Raw:
    """Each item: (group, headline, detail, link-or-empty). The group picks the dot colour."""
    out = []
    for group, headline, detail, link in items:
        title = h("a", headline, href=link) if link else h("span", headline)
        out.append(h("li", h("i", cls=f"dot {group}"), h("div", h("b", title), h("small", detail)), cls=f"t {group}"))
    return h("ol", out, cls="timeline")


# --------------------------------------------------------------------- layout

NAV = (
    ("Overview", (("Dashboard", "/"), ("Guided tour", "/tour"))),
    ("Know: what may it see?", (("What can it see?", "/policies"),)),
    ("Do: what may it do?", (("Your AI colleague", "/agents"), ("Run a task", "/workflows"),
                              ("Waiting for a person", "/approvals"), ("Emergency stop", "/kill-switch"),
                              ("Spending limits", "/budgets"))),
    ("Prove: what can we show?", (("The receipt", "/evidence"), ("Would we decide the same?", "/replay"),
                                  ("Rebuild what happened", "/reconstruction"), ("AI passport", "/pwm"))),
)

CSS = """
:root{color-scheme:dark;--navy:#0b1626;--deep:#0f2036;--panel:rgba(18,36,60,.72);--line:rgba(255,255,255,.12);--ink:#eaf1f9;--muted:#a9bbcf;
--gold:#e5b567;--good:#3ecf8e;--bad:#ff6b6b;--warn:#ffb547;--info:#7aa2ff;--cyan:#4cc9f0;
--serif:Georgia,"Iowan Old Style",Palatino,"Palatino Linotype",serif;--sans:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
--mono:ui-monospace,"Cascadia Code","Source Code Pro",Menlo,Consolas,monospace}
*{box-sizing:border-box}html{font-size:17px}
html{background:var(--navy)}body{margin:0;min-height:100vh;background:radial-gradient(1100px 520px at 75% -8%,#17314f 0%,transparent 62%);color:var(--ink);font:1rem/1.55 var(--sans)}
a{color:var(--cyan)}a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible{outline:3px solid var(--gold);outline-offset:2px}
.skip{position:absolute;left:-999px;top:0;background:var(--gold);color:#0b1626;padding:.6rem 1rem;z-index:10;border-radius:0 0 8px 0}.skip:focus{left:0}
.banner{background:#05101d;border-bottom:1px solid var(--line);color:var(--muted);padding:.65rem 1.2rem;font-size:.88rem}.banner strong{color:var(--gold)}
header.top{display:flex;flex-wrap:wrap;align-items:center;gap:.8rem 1.4rem;padding:.9rem 1.2rem .4rem;max-width:76rem;margin:0 auto}
.brand{font:700 1.25rem var(--serif);color:var(--ink);text-decoration:none;display:flex;align-items:center;gap:.55rem}
.brand i{width:1rem;height:1rem;border-radius:50%;background:conic-gradient(var(--gold),#f7dca6,var(--gold));box-shadow:0 0 14px rgba(229,181,103,.6)}
.cta{margin-left:auto;background:var(--gold);color:#0b1626;text-decoration:none;font-weight:800;padding:.55rem 1rem;border-radius:10px}
nav.main{max-width:76rem;margin:0 auto;padding:0 1.2rem .6rem;display:flex;flex-wrap:wrap;gap:.3rem 1.4rem}
nav.main .grp{display:flex;flex-wrap:wrap;align-items:center;gap:.25rem}
nav.main .gl{font-size:.7rem;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin-right:.2rem}
nav.main a{color:var(--ink);text-decoration:none;font-size:.9rem;padding:.3rem .65rem;border-radius:999px;border:1px solid transparent}
nav.main a:hover{border-color:var(--line);background:rgba(255,255,255,.06)}nav.main a.on{background:var(--gold);color:#0b1626;font-weight:700}
main{max-width:76rem;margin:0 auto;padding:.4rem 1.2rem 3rem}
h1{font:700 clamp(1.8rem,3.4vw,2.6rem)/1.1 var(--serif);margin:.6rem 0 .3rem;letter-spacing:-.01em}
h2{font:700 1.3rem/1.2 var(--serif);margin:1.6rem 0 .6rem}h3{margin:.2rem 0 .3rem;font-size:1.05rem}
.lede{font-size:1.12rem;color:#d7e3f1;max-width:46rem;margin:.2rem 0 1.2rem}.muted,small{color:var(--muted)}small{font-size:.85rem}
.grid{display:grid;gap:1rem;margin:1rem 0}.c1{grid-template-columns:1fr}.c2{grid-template-columns:repeat(2,1fr)}.c3{grid-template-columns:repeat(3,1fr)}.c4{grid-template-columns:repeat(4,1fr)}
.card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:1.1rem 1.2rem;backdrop-filter:blur(8px)}
.card.good{border-top:4px solid var(--good)}.card.bad{border-top:4px solid var(--bad)}.card.warn{border-top:4px solid var(--warn)}.card.info{border-top:4px solid var(--info)}
.card h3 a{color:inherit;text-decoration:none}.kick{font-size:.75rem;font-weight:800;letter-spacing:.14em;text-transform:uppercase;margin:0 0 .2rem}
.kick.know{color:var(--cyan)}.kick.do{color:var(--warn)}.kick.prove{color:var(--info)}.kick.break{color:var(--bad)}
.stat{display:flex;flex-direction:column;gap:.1rem}.stat .k{font-size:.75rem;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.stat .v{font:700 1.7rem/1.1 var(--serif)}.v.good{color:var(--good)}.v.bad{color:var(--bad)}.v.warn{color:var(--warn)}.v.info{color:var(--info)}
.tdot{flex:none;width:.7rem;height:.7rem;border-radius:50%;background:var(--info)}.tdot.good{background:var(--good)}.tdot.bad{background:var(--bad)}.tdot.warn{background:var(--warn)}
.stamp{display:inline-flex;align-items:center;gap:.4rem;font-weight:800;padding:.28rem .75rem;border-radius:999px;border:2px solid currentColor;font-size:.92rem;white-space:nowrap}
.stamp svg{width:1.05em;height:1.05em;fill:none;stroke:currentColor;stroke-width:2.2;stroke-linecap:round;stroke-linejoin:round}
.stamp.good{color:var(--good);background:rgba(62,207,142,.1)}.stamp.bad{color:var(--bad);background:rgba(255,107,107,.1)}
.stamp.warn{color:var(--warn);background:rgba(255,181,71,.1)}.stamp.info{color:var(--info);background:rgba(122,162,255,.1)}
.btn{font:700 .95rem var(--sans);padding:.65rem 1.15rem;border-radius:10px;border:1px solid var(--line);color:var(--ink);background:rgba(255,255,255,.08);cursor:pointer}
.btn:hover{background:rgba(255,255,255,.16)}.btn.primary{background:var(--gold);border-color:var(--gold);color:#0b1626}.btn.primary:hover{filter:brightness(1.08);background:var(--gold)}
.btn.good{background:var(--good);border-color:var(--good);color:#06231a}.btn.bad{background:var(--bad);border-color:var(--bad);color:#2a0709}.btn.warn{background:var(--warn);border-color:var(--warn);color:#2b1a00}
.btn.small{padding:.4rem .8rem;font-size:.85rem}
form.action{display:flex;flex-wrap:wrap;align-items:center;gap:.5rem .8rem;margin:.6rem 0}form.action .token{font-size:.8rem;color:var(--muted)}
input,select{font:inherit;color:var(--ink);background:#0a1a2d;border:1px solid var(--line);border-radius:8px;padding:.4rem .6rem}
label{color:var(--muted);font-size:.9rem}
.pills{display:inline-flex;flex-wrap:wrap;gap:.3rem;padding:.25rem;border:1px solid var(--line);border-radius:999px;background:rgba(255,255,255,.04);margin:.4rem 0 1rem}
.pills a{color:var(--ink);text-decoration:none;padding:.4rem .9rem;border-radius:999px;font-weight:600}.pills a.on{background:var(--gold);color:#0b1626}
details.mechanics{margin-top:1.6rem;border:1px solid var(--line);border-radius:12px;background:rgba(5,11,20,.55)}
details.mechanics>summary{cursor:pointer;padding:.8rem 1.1rem;font-weight:700;color:var(--muted)}details.mechanics[open]>summary{color:var(--ink)}
details.mechanics .inner{padding:0 1.1rem 1.1rem}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:.88rem;margin:.5rem 0}
th,td{text-align:left;border-bottom:1px solid var(--line);padding:.45rem .5rem;vertical-align:top;overflow-wrap:anywhere}th{color:var(--muted);font-weight:700;font-size:.78rem;letter-spacing:.06em;text-transform:uppercase}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#050b14;color:#dbe7f5;padding:1rem;border-radius:10px;font:.82rem/1.45 var(--mono);margin:.5rem 0}
code{font-family:var(--mono);font-size:.85em;background:#050b14;padding:.1rem .35rem;border-radius:5px}
.frow{display:flex;align-items:baseline;gap:.8rem;padding:.55rem .2rem;border-bottom:1px solid var(--line)}.frow .k{min-width:9.5rem;font-size:.75rem;letter-spacing:.09em;text-transform:uppercase;color:var(--muted)}
.frow b{font-size:1.05rem}.frow.masked b{color:var(--warn);letter-spacing:.1em}.frow.denied i{color:var(--muted);font-style:normal;border-bottom:2px dashed var(--muted)}
.frow em{margin-left:auto;font-style:normal;font-size:.72rem;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}.frow.masked em{color:var(--warn)}
.ladder{list-style:none;display:flex;gap:.4rem;align-items:flex-end;padding:0;margin:.8rem 0;min-height:11rem}
.ladder li{flex:1;display:flex;flex-direction:column;justify-content:flex-end;gap:.15rem;padding:.5rem .4rem;border-radius:10px 10px 4px 4px;background:rgba(122,162,255,.18);border:1px solid var(--line);font-size:.78rem;text-align:center}
.ladder b{font-size:.9rem}.ladder li.here{background:var(--warn);color:#2b1a00;border-color:var(--warn);font-weight:700}.ladder li.locked{opacity:.55}
.l0{height:3rem}.l1{height:4.2rem}.l2{height:5.4rem}.l3{height:6.6rem}.l4{height:7.8rem}.l5{height:9rem}.l6{height:10.2rem}
progress.meter{width:100%;height:.8rem;accent-color:var(--warn)}.metered{display:flex;flex-direction:column;gap:.1rem;min-width:9rem}
.timeline{list-style:none;margin:.6rem 0;padding:0}.timeline li{display:flex;gap:.8rem;padding:.55rem 0;border-bottom:1px solid var(--line)}
.dot{flex:none;width:.8rem;height:.8rem;border-radius:3px;margin-top:.4rem;background:#7f93aa}.dot.decision{background:var(--info)}.dot.work{background:#a78bfa}.dot.human{background:var(--warn)}.dot.privacy{background:var(--cyan)}.dot.final{background:var(--good)}
.timeline b a{color:var(--ink);text-decoration:none}.timeline b a:hover{text-decoration:underline}.timeline small{display:block}
.qgrid{display:grid;grid-template-columns:repeat(2,1fr);gap:.6rem}.q{padding:.6rem .8rem;border-radius:10px;font-weight:600}.q.yes{background:rgba(62,207,142,.14)}.q.no{background:rgba(255,181,71,.2)}
.q small{display:block;font-weight:800;letter-spacing:.08em;text-transform:uppercase}.q.yes small{color:var(--good)}.q.no small{color:var(--warn)}
.result{display:flex;flex-wrap:wrap;align-items:center;gap:.8rem 1.2rem}.result h2{margin:0}
.steps{list-style:none;padding:0;margin:.5rem 0;display:grid;gap:.5rem}.steps li{display:flex;gap:.7rem;align-items:center;padding:.55rem .8rem;border-radius:10px;background:rgba(255,255,255,.04);border:1px solid var(--line)}.steps li>span:not(.stamp){flex:1}.row{display:flex;flex-wrap:wrap;gap:.4rem .9rem;align-items:flex-start}
.empty{text-align:center;padding:2rem 1rem}.empty h3{font:700 1.3rem var(--serif)}
.rules{list-style:none;padding:0;margin:.4rem 0}.rule{padding:.5rem 0;border-bottom:1px solid var(--line)}.rule small{display:block}
.proposal{display:grid;gap:.15rem}.proposal b{font:700 1.4rem var(--serif)}
footer{max-width:76rem;margin:0 auto;padding:0 1.2rem 2rem;color:var(--muted);font-size:.85rem}
@media (max-width:860px){.c3,.c4,.c2{grid-template-columns:minmax(0,1fr)}.qgrid{grid-template-columns:minmax(0,1fr)}.frow{flex-wrap:wrap;row-gap:.1rem}.frow .k{min-width:0;flex:1 1 100%}.frow em{margin-left:0}.cta{margin-left:0}.ladder{min-height:9rem}.ladder li span{display:none}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
@media print{body{background:#fff;color:#000}.banner,header.top,nav.main,footer,form.action{display:none}.card{border:1px solid #999;background:#fff}}
"""


def render_page(title: str, body: Any, *, active: str = "", prefix: str = "", public_demo: bool = False) -> str:
    """The whole document. `prefix` is where the console is mounted; links to the walkthrough are never prefixed."""
    groups = []
    for label, links in NAV:
        groups.append(h("div", h("span", label, cls="gl"),
                        [h("a", name, href=f"{prefix}{path}", cls="on" if path == active else None,
                           aria_current="page" if path == active else None) for name, path in links], cls="grp"))
    banner = (h("div", h("strong", "Public demo: "),
                "Data is synthetic; state is ephemeral and shared within this instance. Requests may reach a different "
                "instance and lose prior state. The in-process mock model runs without a gateway or external provider.",
                cls="banner", role="note") if public_demo else None)
    story = h("a", "Watch the 3D walkthrough", href="/story/", cls="cta") if public_demo else None
    document = (
        "<!doctype html>" + h("html", Raw(
            "<head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{esc(title)} | Eastwind</title><style>{CSS}</style></head>"
            + h("body",
                h("a", "Skip to the page", href="#main", cls="skip"),
                banner,
                h("header", h("a", h("i"), "Eastwind Private", href=f"{prefix}/", cls="brand"), story, cls="top"),
                h("nav", groups, cls="main", aria_label="Console sections"),
                h("main", h("h1", title), body, id="main"),
                h("footer", "Workshop fiction. The clients, products and citations are invented. "
                  "Everything technical is behind each page's “Show the mechanics”."))),
            lang="en"))
    return document
