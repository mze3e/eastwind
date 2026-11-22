"""The 3D walkthrough: its data is a real run, its words are plain, and its page stays locked down.

The walkthrough draws and animates; it decides nothing. These tests check what it is allowed to say.
Everything runs offline. Nothing here needs a browser: the visual and CSP checks were made by
driving the built site in headless Chromium (see the README), and `node --check` below guards
the modules against a syntax slip.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from eastwind import story as story_module
from eastwind.story import PATHS, build_story, capture_story, onepager_facts
from eastwind.words import CAPABILITIES, WORKFLOW_WORDS

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"

#: Words an executive should not meet on a primary screen. They belong in "Show the mechanics".
JARGON = ("SHACL", "RDF", "ontology", "hash", "JSON", "ALLOW", "DENY", "ESCALATE", "HUMAN_APPROVAL",
          "regime", "triple", "sha256", "ATTRIBUTE_ALLOWLIST", "REQUIRES_FLAG", "S1-", "S3-", "C1", "C2", "C3")
#: Fields that show raw data on purpose (a prompt, a checker's own message) or hold the technical layer.
RAW = {"mechanics", "privacy", "tamper", "chain"}


@pytest.fixture(scope="module")
def captured():
    data = capture_story()
    return data, build_story(data)


def _steps(story):
    return [step for chapter in story["chapters"] for step in chapter["steps"]]


def _primary_strings(value, key=""):
    """Every string a presenter's audience reads, which is everything except the raw/technical fields."""
    if key in RAW:
        return
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _primary_strings(v, k)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _primary_strings(item, key)


# --------------------------------------------------------------- the capture

def test_capture_is_the_real_run(captured):
    data, _ = captured
    deny, allow = data["borders"]["deny"], data["borders"]["allow"]
    assert deny["outcome"] == "DENY" and not deny["retrieval_called"] and not deny["model_called"]
    assert {f["regime"] for f in deny["failed"]} >= {"HK_SFC", "DIFC_DFSA", "PRODUCT_GOVERNANCE"}
    assert len(deny["failed"]) == 4 and deny["passed"] + len(deny["failed"]) == deny["total"]
    assert allow["outcome"] == "ALLOW" and allow["retrieval_called"] and allow["model_called"]
    assert len(allow["documents"]) == 2 and len(allow["withheld"]) == 1
    assert data["roles"]["visitor"]["blocked"] and data["roles"]["visitor"]["retrieved"] == []
    assert not data["roles"]["agent"]["blocked"] and not data["roles"]["relationship_manager"]["blocked"]
    rb = data["rebalance"]["facts"]
    assert rb["held"] and rb["checkpoint"] and rb["approved_executed"] and not rb["denied_executed"]
    assert rb["approved_before_stop"] and not rb["stopped_executed"]
    assert [call["allowed"] for call in data["budget"]["calls"]] == [True, True, False]
    chain = data["chain"]
    assert chain["count"] == chain["earlier"] + len(chain["window"])
    assert chain["tamper"]["broken_at"] == chain["tamper"]["sequence"]
    assert data["replay"]["outcome"] == "ALLOW" and data["replay"]["chain"]["intact"]
    assert data["pwm"]["conforms"] and data["colleague"]["level"] == 0


def test_provider_side_text_never_carries_a_client_identifier(captured):
    data, story = captured
    egress = data["borders"]["allow"]["egress"]
    originals = [pair["original"] for pair in egress["pairs"]]
    assert originals and all(token in egress["sent"] for token in egress["tokens"])
    privacy = next(s for s in _steps(story) if s["id"] == "know-privacy")["privacy"]
    for text in privacy["after"] + [privacy["reply_out"]]:
        assert not any(original in text for original in originals), text
    assert all(any(original in text for text in privacy["before"]) for original in originals)


def test_the_shipped_json_leaks_nothing_it_should_not(captured, monkeypatch):
    data, story = captured
    blob = json.dumps({"data": data, "story": story})
    # The client the Dubai request was about is never retrieved, so nothing about them may ship.
    for needle in ("Lena Vogel", "lena.vogel@", "HK-PB-2002771"):
        assert needle not in blob
    # A withheld document is counted, never named.
    assert "Steering note" not in blob and "consolidation" not in blob.lower()
    assert "sk-" not in blob and "OPENAI_API_KEY" not in blob


def test_a_claim_the_run_cannot_back_fails_the_build(monkeypatch):
    monkeypatch.setattr(story_module, "REASONS", {})
    with pytest.raises(RuntimeError, match="plain-English reason"):
        capture_story()


# ------------------------------------------------------------------ the copy

def test_primary_copy_is_plain_english(captured):
    _, story = captured
    problems = []
    for step in _steps(story):
        for text in _primary_strings({k: v for k, v in step.items() if k not in RAW}):
            for word in JARGON:
                if re.search(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", text):
                    problems.append(f"{step['id']}: {word!r} in {text!r}")
    assert not problems, "\n".join(problems)


def test_copy_is_short_enough_to_read_from_the_back_of_a_room(captured):
    _, story = captured
    for step in _steps(story):
        assert len(step["title"]) <= 60, step["id"]
        assert len(step["point"]) <= 260, step["id"]
        for choice in step.get("choices", []):
            assert len(choice["label"]) <= 60 and len(choice["result"]) <= 200, (step["id"], choice["id"])


def test_numbers_in_the_copy_come_from_the_data(captured):
    data, story = captured
    steps = {s["id"]: s for s in _steps(story)}
    deny = data["borders"]["deny"]
    border = {c["id"]: c for c in steps["know-border"]["choices"]}
    assert f"{len(deny['failed'])} separate reasons" in border["deny"]["result"]
    assert len(steps["know-border"]["reasons"]) == len(deny["failed"])
    chain = data["chain"]
    assert str(chain["count"]) in steps["prove-receipt"]["point"]
    assert f"{chain['count']} of {chain['count']}" in steps["prove-verify"]["point"]
    assert str(chain["tamper"]["sequence"]) in steps["prove-tamper"]["choices"][0]["result"]
    calls = data["budget"]["calls"]
    assert f"{len(calls)} calls" in steps["do-limits"]["choices"][0]["result"]
    assert steps["do-approval"]["proposal"]["amount"] == f"S${data['rebalance']['proposal']['amount']:,}"


def test_every_step_is_complete_and_unique(captured):
    _, story = captured
    steps = _steps(story)
    ids = [s["id"] for s in steps]
    assert len(ids) == len(set(ids)) and len(steps) == 18
    for step in steps:
        assert step["title"] and step["point"] and step["say"] and step["mechanics"]["command"]
        choice_ids = [c["id"] for c in step.get("choices", [])]
        assert len(choice_ids) == len(set(choice_ids))
        assert all(c["tone"] in ("good", "bad") for c in step.get("choices", []))


# ------------------------------------------------------------ the web sources

def test_vendored_three_matches_the_recorded_checksums():
    folder = WEB / "vendor" / "three"
    readme = (folder / "README.md").read_text(encoding="utf-8")
    for name in ("three.core.js", "three.module.js"):
        recorded = re.search(rf"{re.escape(name)}: SHA-256 ([0-9a-f]{{64}})", readme)
        assert recorded, f"{name} has no recorded checksum"
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == recorded.group(1)
    assert "MIT" in (folder / "LICENSE").read_text(encoding="utf-8")


def test_the_walkthrough_loads_nothing_from_outside_its_own_origin():
    for path in (WEB / "story").glob("*"):
        if path.suffix in {".js", ".css", ".html"}:
            text = path.read_text(encoding="utf-8")
            assert not re.search(r"https?://", text), path.name
    page = (WEB / "story" / "index.html").read_text(encoding="utf-8")
    scripts = re.findall(r"<script\b[^>]*>", page)
    assert scripts == ['<script type="module" src="app.js">'], scripts


def test_every_step_the_data_names_has_a_scene(captured):
    """A scene is found by the step's chapter. Chapters that tell several steps must also name each one."""
    _, story = captured
    sources = "".join(p.read_text(encoding="utf-8") for p in (WEB / "story").glob("*.js"))
    app = (WEB / "story" / "app.js").read_text(encoding="utf-8")
    registry = app.split("const stations = {", 1)[1].split("};", 1)[0]
    stations = set(re.findall(r"\b(\w+):", registry))
    missing = []
    for chapter in story["chapters"]:
        if chapter["id"] not in stations:
            missing.append(chapter["id"])
            continue
        if len(chapter["steps"]) > 1:
            missing += [s["id"] for s in chapter["steps"] if f"'{s['id']}'" not in sources and f'"{s["id"]}"' not in sources]
    assert not missing, missing


def capture_story_ids():
    # Step ids are static copy, so they can be read without running Kognita again.
    text = (ROOT / "src" / "eastwind" / "story.py").read_text(encoding="utf-8")
    return re.findall(r'"id": "((?:welcome|recap|colleague-\w+|know-\w+|do-\w+|prove-\w+|break-\w+|more-\w+))"', text)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_every_module_parses():
    for path in sorted((WEB / "story").glob("*.js")):
        result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
        assert result.returncode == 0, f"{path.name}: {result.stderr}"


# ---------------------------------------------------------- the built site

def _builder():
    path = ROOT / "scripts" / "build_demo_page.py"
    spec = importlib.util.spec_from_file_location("build_demo_page_site", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_built_site_is_complete_and_self_contained(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-site-must-not-leak")
    builder = _builder()
    builder.build_site(tmp_path)
    for name in builder.SITE_FILES:
        assert (tmp_path / name).is_file(), name
    payload = json.loads((tmp_path / "story" / "data.json").read_text(encoding="utf-8"))
    assert payload["story"]["schema"] == 1 and len(_steps(payload["story"])) == 18
    assert "sk-site-must-not-leak" not in (tmp_path / "story" / "data.json").read_text(encoding="utf-8")

    landing = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert 'href="/story/"' in landing and 'href="/admin/"' in landing
    assert 'href="/onepager/"' in landing and 'href="/story/#more-map"' in landing and 'href="/story/?path=quick"' in landing
    onepager = (tmp_path / "onepager" / "index.html").read_text(encoding="utf-8")
    assert "<script" not in onepager.lower() and "https://" not in onepager and "<h1>An AI colleague that can show its work</h1>" in onepager
    assert "<script" not in landing.lower()
    # Every still the landing page shows was shipped with it.
    for name in re.findall(r'src="/story/previews/(\w+\.jpg)"', landing):
        assert (tmp_path / "story" / "previews" / name).is_file(), name
    # The walkthrough must run offline: the copied page points at files that were copied.
    story_page = (tmp_path / "story" / "index.html").read_text(encoding="utf-8")
    for ref in re.findall(r'(?:src|href)="([^"#]+)"', story_page):
        if not ref.startswith(("../", "/")):
            assert (tmp_path / "story" / ref).is_file(), ref


def test_the_local_server_applies_the_headers_vercel_would():
    builder = _builder()
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    assert builder._matches("/story/:path*", "/story/app.js") and builder._matches("/story/:path*", "/story")
    assert builder._matches("/", "/") and not builder._matches("/", "/story/")
    assert not builder._matches("/story/:path*", "/storyboard")
    assert {rule["source"] for rule in config["headers"]} >= {"/", "/story", "/story/", "/story/:path*"}


# ------------------------------------------------------------ the page policy

def _policy(source):
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    rule = next(item for item in config["headers"] if item["source"] == source)
    header = next(h for h in rule["headers"] if h["key"] == "Content-Security-Policy")
    return {part.split()[0]: part.split()[1:] for part in header["value"].split(";") if part.strip()}


def test_the_walkthrough_may_run_its_own_scripts_and_nothing_else():
    for source in ("/story", "/story/", "/story/:path*"):
        policy = _policy(source)
        assert policy["default-src"] == ["'none'"]
        assert policy["script-src"] == ["'self'"]                      # no inline script, no third party, no eval
        assert policy["connect-src"] == ["'self'"] and policy["form-action"] == ["'none'"]
        assert "img-src" not in policy and "frame-src" not in policy
    assert _policy("/story") == _policy("/story/") == _policy("/story/:path*")


def test_the_landing_page_still_runs_no_script():
    for source in ("/", "/index.html", "/onepager", "/onepager/"):
        policy = _policy(source)
        assert policy["default-src"] == ["'none'"] and "script-src" not in policy
        assert policy["img-src"] == ["'self'"] and policy["form-action"] == ["'none'"]


def test_the_function_bundle_leaves_the_web_sources_out():
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    assert "web/**" in config["functions"]["api/index.py"]["excludeFiles"]
    script = (ROOT / "scripts" / "vercel_build.sh").read_text(encoding="utf-8")
    assert "public/story/data.json" in script and "three.module.js" in script and "public/onepager/index.html" in script


# ------------------------------------------------------- the capability map

def _readme():
    return (ROOT / "README.md").read_text(encoding="utf-8")


def test_the_map_matches_the_readme_feature_table_row_for_row():
    readme = _readme()
    section = readme.split("## Feature map", 1)[1].split("\n## ", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("|") and not line.startswith("|---") and "Kognita feature" not in line]
    assert len(rows) == sum(1 for c in CAPABILITIES if c[1] != "more")
    # Kognita's own list of what Eastwind does not demonstrate.
    sentence = readme.split("Kognita also provides ", 1)[1].split(". Eastwind does not provide", 1)[0]
    items = [part.strip().removeprefix("and ") for part in sentence.split(",")]
    assert len(items) == sum(1 for c in CAPABILITIES if c[1] == "more") == 12


def test_every_capability_points_at_something_that_exists(local_console_routes):
    from eastwind.agents.workflows import WORKFLOWS
    from eastwind.showcase import SCENARIO_ORDER
    ids = [c[0] for c in CAPABILITIES]
    assert len(ids) == len(set(ids))
    for cid, group, title, promise, primary, secondary in CAPABILITIES:
        assert title and promise and group in {"meet", "know", "do", "prove", "break", "more"}, cid
        for kind_ref in (primary, secondary):
            if not kind_ref:
                continue
            kind, ref = kind_ref
            assert kind in {"story", "console", "cli", "none"}, cid
            if kind == "console":
                assert ref in local_console_routes, (cid, ref)
            if kind == "cli":
                words = ref.split()
                assert words[0] == "eastwind", (cid, ref)
                if words[1] == "showcase":
                    assert set(words[2:]) <= set(SCENARIO_ORDER), (cid, ref)
                elif words[1] == "workflow":
                    assert words[2] in WORKFLOWS, (cid, ref)
    # Part of Kognita with no demonstration here never claims a place to see it.
    assert all(c[4][0] == "none" and c[5] is None for c in CAPABILITIES if c[1] == "more")


@pytest.fixture(scope="module")
def local_console_routes(tmp_path_factory):
    """The pages the console really serves, read from the application itself."""
    from eastwind.admin import create_app
    app = create_app(tmp_path_factory.mktemp("console"), "token-for-route-listing")
    return {route.path for route in app.routes if "GET" in getattr(route, "methods", ())}


def test_the_map_step_links_only_to_real_steps_and_is_plain_english(captured):
    _, story = captured
    ids = {s["id"] for s in _steps(story)}
    tile_step = next(s for s in _steps(story) if s["id"] == "more-map")
    assert tile_step["layout"] == "map" and len(tile_step["capabilities"]) == len(CAPABILITIES)
    for cap in tile_step["capabilities"]:
        for see in cap["see"]:
            if see["kind"] == "story":
                assert see["step"] in ids
    shown = [c for c in tile_step["capabilities"] if any(s["kind"] != "none" for s in c["see"])]
    assert len(shown) == 22 and len(tile_step["capabilities"]) - len(shown) == 12


def test_the_console_flag_follows_the_deployment(monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("EASTWIND_CONSOLE", raising=False)
    assert story_module._console_deployed() is False
    monkeypatch.setenv("VERCEL", "1")
    assert story_module._console_deployed() is True


# ---------------------------------------------------------- presenter paths

def test_paths_are_ordered_derived_and_never_skip_silently(captured):
    _, story = captured
    order = [s["id"] for s in _steps(story)]
    paths = {p["id"]: p for p in story["paths"]}
    assert set(paths) == set(PATHS) and story["defaultPath"] == "full"
    assert paths["full"]["steps"] == order                           # the default skips nothing
    for p in paths.values():
        assert p["steps"] == [i for i in order if i in set(p["steps"])]   # always in story order
        assert p["steps"][0] == "welcome" and p["steps"][-1] == "recap"
    assert len(paths["quick"]["steps"]) < len(paths["standard"]["steps"]) < len(paths["full"]["steps"])
    assert paths["quick"]["minutes"] < paths["standard"]["minutes"] < paths["full"]["minutes"]


def test_a_paths_time_is_worked_out_from_its_steps_and_shown_in_its_label(captured):
    _, story = captured
    steps = {s["id"]: s for s in _steps(story)}
    welcome = steps["welcome"]
    for p in story["paths"]:
        seconds = sum(story_module.SECONDS_PER_STEP + story_module.SECONDS_PER_CHOICE
                      * len([c for c in steps[i].get("choices", []) if "path" not in c]) for i in p["steps"])
        assert p["seconds"] == seconds and p["minutes"] == max(1, round(seconds / 60))
        choice = next(c for c in welcome["choices"] if c["path"] == p["id"])
        assert f"about {p['minutes']} min" in choice["label"] and f"{len(p['steps'])} steps" in choice["result"]
    assert [c["path"] for c in welcome["choices"]] == list(PATHS)


# --------------------------------------------------------------- what if it breaks

def test_the_outage_step_says_what_the_drill_did(captured):
    data, story = captured
    step = next(s for s in _steps(story) if s["id"] == "break-outage")
    assert [c["id"] for c in step["choices"]] == ["strict", "local", "remote", "identifying"]
    out = data["outage"]
    assert out["strict"]["passed_on"] == 0 and out["local"]["passed_on"] == 1
    assert out["remote"]["passed_on"] == 0 and out["identifying"]["passed_on"] == 0 and out["chain_ok"] is True
    tones = {c["id"]: c["tone"] for c in step["choices"]}
    assert tones == {"strict": "bad", "local": "good", "remote": "bad", "identifying": "bad"}
    assert all(len(c["label"]) <= 30 for c in step["choices"])


# -------------------------------------------------------------------- the one-pager

def test_the_one_pager_is_built_from_the_run(captured):
    data, story = captured
    facts = onepager_facts(data, story)
    shown = [n for n, _ in facts["numbers"]]
    assert len(shown) == 4 and len(set(shown)) == 4
    assert shown[0] == str(len(data["borders"]["deny"]["failed"]))
    assert str(data["chain"]["count"]) in shown
    assert f"#{data['chain']['tamper']['sequence']}" in shown
    caps = facts["capabilities"]
    assert caps["total"] == len(CAPABILITIES) and caps["shown"] + caps["not_shown"] == caps["total"]
    problems = []
    for text in list(_primary_strings(facts)):
        for word in JARGON:
            if re.search(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", text):
                problems.append((word, text))
    assert not problems, problems


def test_the_one_pager_keeps_three_columns_in_print():
    # An A4 page is 794px wide, so a plain max-width rule would reshape the printout. It must be screen-only.
    builder = _builder()
    assert "@media screen and (max-width" in builder.ONEPAGER_CSS
    assert not re.search(r"@media \(max-width", builder.ONEPAGER_CSS)
    assert "@page { size: A4;" in builder.ONEPAGER_CSS
