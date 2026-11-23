"""The console: plain English first, mechanics behind a click, and nothing riskier than before.

These add to tests/test_admin.py and tests/test_vercel.py, which still pass unchanged and so keep
pinning the raw markup, the token checks and the public-demo limits.
"""
from __future__ import annotations

import html
import json
import re

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from eastwind import ui
from eastwind.admin import create_app
from eastwind.ui import Raw, h
from eastwind.words import POLICY_WORDS, TOOL_WORDS, WORKFLOW_WORDS
from kognita.models import Agent, Policy

TOKEN = "console-test-token"
PAGES = ["/", "/tour", "/agents", "/policies", "/policies?role=relationship_manager", "/policies?role=visitor", "/approvals",
         "/kill-switch", "/budgets", "/evidence", "/replay", "/reconstruction", "/pwm", "/workflows"]
JARGON = ("ALLOW", "DENY", "HUMAN_APPROVAL", "ESCALATE", "SHACL", "RDF", "ontology", "hash", "JSON", "sha256", "triple",
          "ATTRIBUTE_ALLOWLIST", "REQUIRES_FLAG")


def text_of(markup: str) -> str:
    """What a person reads: the page without its mechanics, scripts, styles or tags."""
    markup = re.sub(r'<details class="mechanics".*?</details>', " ", markup, flags=re.S)
    markup = re.sub(r"<style.*?</style>|<script.*?</script>", " ", markup, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", " ", markup))


@pytest.fixture
def local(tmp_path):
    app = create_app(tmp_path / "local", TOKEN)
    with TestClient(app) as client:
        yield client
    app.state.engine.dispose()


@pytest.fixture
def mounted(tmp_path):
    """The console as Vercel mounts it, under /admin, in public-demo mode."""
    app = create_app(tmp_path / "public", public_demo=True, prefix="/admin")
    with TestClient(app) as client:
        yield client
    app.state.engine.dispose()


# ----------------------------------------------------------- the html helpers

def test_helpers_escape_everything_that_is_not_marked_safe():
    assert h("p", "<script>alert(1)</script>") == "<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>"
    assert h("p", Raw("<b>ok</b>")) == "<p><b>ok</b></p>"
    assert h("a", "x", href='"><img src=x onerror=alert(1)>') == '<a href="&quot;&gt;&lt;img src=x onerror=alert(1)&gt;">x</a>'
    assert ui.void("input", name="role", value="agent") == '<input name="role" value="agent">'
    assert "&lt;i&gt;" in ui.stamp("good", "<i>")
    assert ui.table(["<h>"], [["<c>"]]).count("&lt;") == 2


def test_an_attribute_called_name_does_not_collide_with_the_tag_name():
    # The tag is positional-only, so name="role" is just an attribute.
    assert h("select", "x", name="role") == '<select name="role">x</select>'


# ------------------------------------------------------------------- the pages

def test_every_page_works_and_leaks_no_token(local):
    for url in PAGES:
        response = local.get(url)
        assert response.status_code == 200, url
        assert TOKEN not in response.text


def test_every_link_and_form_is_mounted_where_vercel_puts_it(mounted):
    mounted.post("/workflows", data={"workflow": "client-review", "role": "agent"})
    mounted.post("/workflows", data={"workflow": "rebalance", "role": "agent"})
    seen = 0
    for url in PAGES + ["/tour"]:
        page = mounted.get(url).text
        for ref in re.findall(r'(?:href|action)="(/[^"#]*)"', page):
            seen += 1
            assert ref.startswith(("/admin/", "/admin?", "/story/")) or ref == "/admin", (url, ref)
    assert seen > 100
    # The walkthrough link is never prefixed, because the walkthrough is a sibling of the console.
    assert 'href="/story/"' in mounted.get("/").text


def test_pages_run_no_script_and_load_nothing_from_elsewhere(local):
    local.post("/workflows", data={"token": TOKEN, "workflow": "client-review", "role": "agent"})
    for url in PAGES:
        page = local.get(url).text
        assert "<script" not in page.lower(), url
        visible = re.sub(r'<details class="mechanics".*?</details>', " ", page, flags=re.S)
        assert not re.search(r"(?:src|href|action)=\"https?://", visible), url


def test_the_pages_are_plain_english(local):
    local.post("/workflows", data={"token": TOKEN, "workflow": "client-review", "role": "agent"})
    local.post("/workflows", data={"token": TOKEN, "workflow": "rebalance", "role": "agent"})
    problems = []
    for url in PAGES:
        visible = text_of(local.get(url).text)
        for word in JARGON:
            if re.search(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", visible):
                problems.append(f"{url}: {word}")
    assert not problems, "\n".join(problems)


def test_the_mechanics_are_still_one_click_away(local):
    for url in ["/agents", "/policies", "/evidence", "/budgets", "/replay", "/pwm", "/kill-switch"]:
        assert 'class="mechanics"' in local.get(url).text, url


def test_the_colleague_page_counts_every_registered_tool(local):
    with Session(local.app.state.engine) as session:
        registered = [k for k in session.exec(select(Agent)).one().tool_allowlist if not k.startswith("_")]
    page = text_of(local.get("/agents").text)
    assert f"{len(registered)} approved" in page
    # Two tools may never share a plain-English name, or one would vanish from the list.
    assert len({TOOL_WORDS[k] for k in registered}) == len(registered)


def test_every_rule_in_the_register_is_described_in_a_sentence(local):
    with Session(local.app.state.engine) as session:
        regimes = {p.regime for p in session.exec(select(Policy)).all()}
    assert regimes <= set(POLICY_WORDS), regimes - set(POLICY_WORDS)
    page = text_of(local.get("/policies").text)
    assert all(POLICY_WORDS[r][1] in page for r in regimes)


def test_the_policy_page_still_pins_the_raw_field_table_inside_the_mechanics(local):
    page = local.get("/policies?role=agent").text
    mech = re.search(r'<details class="mechanics".*?</details>', page, re.S).group(0)
    assert "<td>email</td><td>masked</td>" in mech and "<td>tax_identifier</td><td>denied</td>" in mech


def test_each_role_sees_the_file_the_policy_says(local):
    agent, manager, visitor = (text_of(local.get(f"/policies?role={r}").text) for r in ("agent", "relationship_manager", "visitor"))
    assert "Mei Tan" in agent and "mei.tan@clients" not in agent and "SG-PB-1001842" not in agent
    assert "mei.tan@clients.eastwind.example" in manager and "SG-PB-1001842" in manager
    assert "Mei Tan" not in visitor and "mei.tan" not in visitor


# ------------------------------------------------------------------ the verdicts

def post(client, path, **values):
    return client.post(path, data={"token": TOKEN, **values})


def held_proposal(client):
    result = post(client, "/workflows", workflow="rebalance", role="agent", max_calls="4")
    assert result.status_code == 200
    run_id = re.search(r'&quot;run_id&quot;: &quot;([^&]+)&quot;', result.text).group(1)
    approval = re.search(r'&quot;approval_id&quot;: (\d+)', result.text).group(1)
    return {"run": run_id, "approval": approval}


def test_the_inbox_is_empty_then_shows_a_real_proposal_with_three_ways_to_answer(local):
    empty = text_of(local.get("/approvals").text)
    assert "Nothing is waiting for a person" in empty and "Create a proposal" in empty
    held_proposal(local)
    page = local.get("/approvals").text
    visible = text_of(page)
    assert "Move S$5,000 into the SGD money market" in visible and "Mei Tan" in visible
    assert all(label in visible for label in ("Approve", "Deny", "Approve, but hold the release"))


def test_each_decision_says_in_plain_words_what_happened(local):
    held = held_proposal(local)
    assert "Denied" in text_of(post(local, "/approvals/resolve", **held, resolution="deny").text)
    held = held_proposal(local)
    released = text_of(post(local, "/approvals/resolve", **held, resolution="approve").text)
    assert "Released as a proposal" in released and "Nothing is traded" in released
    held = held_proposal(local)
    assert post(local, "/approvals/grant", **held).status_code == 200
    post(local, "/kill-switch", state="engage")
    stopped = text_of(post(local, "/approvals/resolve", **held, resolution="approve").text)
    assert "Approved, but not released" in stopped and "Released as a proposal" not in stopped
    post(local, "/kill-switch", state="release")


def test_the_emergency_stop_page_says_which_state_it_is_in(local):
    assert "Running normally" in text_of(local.get("/kill-switch").text)
    engaged = text_of(post(local, "/kill-switch", state="engage").text)
    assert "STOPPED" in engaged and "Release the stop" in engaged
    assert "Running normally" in text_of(post(local, "/kill-switch", state="release").text)


def test_a_task_that_stops_data_leaving_says_stopped_not_allowed(local):
    raw = post(local, "/workflows", workflow="egress", role="agent").text
    page = text_of(raw)
    # The verdict is Stopped. Reading the file first was allowed, and the page says so, then shows the send being stopped.
    assert re.search(r'class="stamp good">.*?Stopped', raw, re.S) and "Sending it to an outside provider: Stopped" in page
    assert "did not leave the bank" in page and "Calls to the provider: 0" in page
    review = text_of(post(local, "/workflows", workflow="client-review", role="visitor", max_calls="4").text)
    assert "Blocked" in review and "Nothing was fetched" in review
    mine = text_of(post(local, "/workflows", workflow="client-review", role="agent", max_calls="4").text)
    assert "AI colleague was given the client profile and account holdings" in mine


def test_the_receipt_says_what_it_proves_and_catches_the_edit(local):
    post(local, "/workflows", workflow="client-review", role="agent", max_calls="4")
    receipt = text_of(local.get("/evidence").text)
    assert re.search(r"All \d+ entries match their seals", receipt)
    caught = post(local, "/evidence/tamper", actor_id="someone-else").text
    assert "Detected" in text_of(caught) and "failed Python verification" in caught


def test_a_budget_that_was_used_in_full_is_not_called_spent(local):
    post(local, "/workflows", workflow="client-review", role="agent", max_calls="4")
    page = text_of(local.get("/budgets").text)
    assert "4 of 4 calls used" in page and "Used every call" in page and "Budget spent" not in page


def test_the_run_a_task_page_offers_every_task_and_marks_the_two_that_need_the_command_line(mounted):
    page = text_of(mounted.get("/workflows").text)
    assert all(label in page for label, _, _ in WORKFLOW_WORDS.values())
    assert page.count("Run it with: eastwind workflow") == 2 and "eastwind workflow degraded" in page and "eastwind workflow mcp" in page


def test_raw_json_is_still_the_first_pre_on_a_result_page(local):
    page = post(local, "/workflows", workflow="research", role="agent").text
    first = re.search(r"<pre>(.*?)</pre>", page, re.S).group(1)
    assert json.loads(html.unescape(first))["workflow"] == "research"
