"""The walkthrough on small screens and for people who do not use a mouse.

Color contrast is worked out from the stylesheet itself, so a palette change that makes text hard to
read fails here. The page's accessibility hooks are checked as text. The real layout checks (nothing
overlaps, nothing is cut off, focus is visible at phone, tablet and laptop sizes) need a browser, so they
live in scripts/check_story.cjs; the last test runs a short pass of it when `EASTWIND_BROWSER_CHECK=1`.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STORY = ROOT / "web" / "story"


def read(name: str) -> str:
    return (STORY / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------- color contrast

def _rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _luminance(color: tuple[int, int, int]) -> float:
    def channel(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(_rgb(a)), _luminance(_rgb(b))), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _tokens() -> dict[str, str]:
    root = re.search(r":root \{(.*?)\}", read("story.css"), re.S).group(1)
    return dict(re.findall(r"--(\w+):\s*(#[0-9a-fA-F]{3,6})", root))


#: The darkest surfaces text sits on: the page, a glass panel and the dark chips and code blocks.
SURFACES = ("#0b1626", "#08101c", "#050b14")


def test_the_palette_tokens_are_found():
    tokens = _tokens()
    assert {"navy", "ink", "muted", "gold", "good", "bad", "amber", "cyan", "blue"} <= set(tokens)


def test_light_text_on_the_dark_surfaces_meets_wcag_aa():
    tokens = _tokens()
    css = read("story.css")
    light = {f"--{name}" for name in ("ink", "muted", "gold", "good", "bad", "amber", "cyan", "blue")}
    colors = {name: tokens[name.removeprefix("--")] for name in light}
    # Literal text colors in the stylesheet: anything light is text on a dark surface.
    for hex_value in set(re.findall(r"(?<![-\w])color:\s*(#[0-9a-fA-F]{6})\b", css)):
        if _luminance(_rgb(hex_value)) > 0.35:
            colors[hex_value] = hex_value
    failures = [(name, surface, round(contrast(value, surface), 2))
                for name, value in colors.items() for surface in SURFACES if contrast(value, surface) < 4.5]
    assert not failures, failures


def test_dark_text_on_each_accent_meets_wcag_aa():
    # Buttons, the current chapter and the picked choice are filled with the accent and carry navy text.
    tokens = _tokens()
    for accent in ("gold", "good", "bad", "amber", "cyan", "blue"):
        assert contrast(tokens["navy"], tokens[accent]) >= 4.5, accent


def test_the_dark_text_on_a_filled_button_is_the_navy_of_the_page():
    css = read("story.css")
    navy = _tokens()["navy"]
    for rule in re.findall(r"[^{}]*(?:\.picked|\[aria-pressed=\"true\"\]|\.primary|\[aria-current=\"step\"\])[^{}]*\{[^}]*\}", css):
        for color in re.findall(r"(?<![-\w])color:\s*(#[0-9a-fA-F]{6})", rule):
            assert color.lower() == navy.lower(), rule.strip()


# ------------------------------------------------------------ the page's hooks

def test_the_page_has_landmarks_a_skip_link_and_announces_each_step():
    page = read("index.html")
    assert '<a class="skip" href="#panel">' in page
    assert re.search(r'<main class="panel" id="panel" tabindex="-1">', page)
    assert re.search(r'id="announce" role="status" aria-live="polite"', page)
    for landmark in ("<header", "<nav", "<main", "<footer", "<aside"):
        assert landmark in page
    assert 'lang="en"' in page and 'name="viewport"' in page
    assert page.count("<h1") == 1


def test_focus_is_always_visible_and_motion_is_optional():
    css, engine = read("story.css"), read("engine.js")
    assert "button:focus-visible" in css and "a:focus-visible" in css
    assert "prefers-reduced-motion: reduce" in css
    # The camera does not glide for people who ask for less motion, and the idle drift stops.
    assert re.search(r"if \(reducedMotion\) \{ this\.snap\(pos, look\)", engine)
    assert "const drift = reducedMotion ? 0 : 1" in engine


def test_escape_closes_the_drawers_and_the_keys_do_not_fight_the_controls():
    app = read("app.js")
    assert "k === 'Escape'" in app
    # Space and Enter move on only when no button or link has focus, so they never fire twice.
    assert re.search(r"\(k === ' ' \|\| k === 'Enter'\) && !onControl", app)


def test_every_small_screen_rule_hangs_off_the_attributes_the_script_sets():
    css, app = read("story.css"), read("app.js")
    for attribute in ('data-shell="sheet"', 'data-shell="rail"', "data-compact", 'data-size="phone"', 'data-size="tablet"'):
        assert attribute in css, attribute
    # The thresholds live in one place in the script; the CSS comment says what they are.
    assert "const side = w >= 1280 && h >= 720, rail = !side && w > h && h < 720;" in app
    assert "w < 700 || h < 500 ? 'phone'" in app
    assert 'at least 1280 by 720' in css and 'under 720px high' in css and '700px' in css


def test_small_layouts_list_what_the_picture_shows_instead_of_floating_labels():
    css = read("story.css")
    assert re.search(r'body\[data-compact\] #labels \{ display: none; \}', css)
    assert 'content: "What the picture shows"' in css
    # The list is built from the same labels, so nothing exists only as a drawing.
    assert "taglog" in read("app.js") and "tag(html, anchor, opts)" in read("app.js")


def test_dots_are_big_enough_to_touch_and_hidden_where_they_would_not_fit():
    css = read("story.css")
    dots = re.search(r"\.dots button \{([^}]*)\}", css).group(1)
    assert "min-width: 24px" in dots and "min-height: 24px" in dots
    assert re.search(r'body\[data-compact\] \.dots \{ display: none; \}', css)


# -------------------------------------------------------------- the browser check

def test_the_browser_check_names_every_size_the_readme_promises():
    script = (ROOT / "scripts" / "check_story.cjs").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    block = script.split("const SIZES = {", 1)[1].split("};", 1)[0]
    names = set(re.findall(r"'?([a-z-]+)'?: \[\d+, \d+\]", block))
    assert names == {"desktop-wide", "desktop", "laptop", "laptop-short", "tablet-wide", "tablet", "phone", "phone-landscape"}
    for name in names:
        assert name in readme, f"the README does not mention the {name} size"


@pytest.mark.skipif(os.environ.get("EASTWIND_BROWSER_CHECK") != "1", reason="opt in with EASTWIND_BROWSER_CHECK=1 (needs node, Playwright and Chromium)")
def test_a_short_pass_of_the_browser_check_finds_nothing(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    result = subprocess.run(
        [node, str(ROOT / "scripts" / "check_story.cjs"), "--sizes", "phone,laptop", "--steps", "welcome,know-border,break-outage", "--out", str(tmp_path)],
        cwd=ROOT, capture_output=True, text=True, timeout=900,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-1500:]
