"""Data and plain-English copy for the Eastwind walkthrough.

The 3D walkthrough in ``web/story`` draws and animates; it decides nothing.
Everything it shows comes from this module, and everything here comes from a
real run of Kognita on one synthetic store:

1. ``capture_story`` runs the governed scenarios and workflows, once for every
   branch a presenter can choose, and checks its own results. If a claim the
   story would make is false, the capture raises and the build fails.
2. ``build_story`` turns the capture into display-ready steps: a headline, one
   plain sentence, a talk track, and the technical detail for the
   "Show the mechanics" drawer.

Display copy lives here, not in JavaScript, so tests can check it for jargon
and against the data. The AI model is the offline stand-in; the governance
decisions are real Kognita decisions. Nothing here calls a network.
"""
from __future__ import annotations

import copy
import json
import re
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rdflib import RDF
from sqlmodel import Session, select

from kognita import __version__ as kognita_version
from kognita import export_chain, make_engine, verify_chain, verify_export
from kognita.evidence import ChainBreak
from kognita.models import Agent
from kognita.usecases import list_usecases
from kognita.vocabulary import CheckResult, Classification

from eastwind import __version__ as eastwind_version
from eastwind.agents.data import PRODUCTS, ROLE_FIELDS
from eastwind.agents.workflows import (APPROVER, budget, client_review, egress, kill_switch, rebalance,
                                       replay, research, suitability)
from eastwind.cli import _echo_model
from eastwind.pack import AGENT_NAME, AGENT_OWNER, CLIENTS, KNOWLEDGE
from eastwind.pwm import LEVELS, P, create_demo_store, export_graph, validate_graph
from eastwind.run import run_scenario

SCHEMA = 1

# ---------------------------------------------------------------------------
# Plain-English vocabulary. Raw codes stay in each step's ``mechanics``.
# ---------------------------------------------------------------------------

OUTCOME_WORDS = {"ALLOW": "Allowed", "DENY": "Blocked", "HUMAN_APPROVAL": "Waiting for a person",
                 "ESCALATE": "Sent to a person"}

FIELD_LABELS = {"name": "Name", "email": "Email", "risk_profile": "Risk profile",
                "investment_horizon_years": "Investment horizon", "tax_identifier": "Tax ID"}

FIELD_PHRASES = {"name": "name", "email": "email", "risk_profile": "risk profile",
                 "investment_horizon_years": "investment horizon", "tax_identifier": "tax ID",
                 "account": "account number"}

DESKS = {"SG": "Singapore", "AE": "Dubai", "HK": "Hong Kong"}

TOOL_WORDS = {"client_profile": "Read the client profile", "account_holdings": "Read the account holdings",
              "product_profile": "Read the product", "summarize_review": "Summarise the review"}

ROLE_WORDS = {"relationship_manager": "Relationship manager", "agent": "AI colleague", "visitor": "Visitor"}

LEVEL_WORDS = ("Look things up", "Explain", "Recommend", "Draft", "Act after approval",
               "Act within limits", "Act freely")

#: Why a check failed, in words a director would use. Keyed by regime, then by check id.
REASONS = {
    "HK_SFC": "Hong Kong securities rules: this client lives outside the permitted countries.",
    "DIFC_DFSA": "Dubai financial centre rules: this client lives outside the permitted countries.",
    "PRODUCT_GOVERNANCE": "Product rules: this product is only for accredited investors, and this client is not one.",
}  # S1-IDENTITY is built from the data in _reason: it names the two desks.

#: Evidence record types, as a person would name them, and a colour group for the 3D chain.
EVENT_WORDS = {
    "POLICY_DECISION": ("Decision", "decision"), "TOOL_CALL": ("Tool used", "work"),
    "RETRIEVAL": ("Documents fetched", "work"), "MODEL_CALL": ("AI model called", "work"),
    "APPROVAL": ("Human approval", "human"), "INTERVENTION": ("Human step-in or stop", "human"),
    "EGRESS": ("Outbound data check", "privacy"), "INTERACTION": ("Client conversation opened", "setup"),
    "POLICY_CHANGE": ("Setup or rule change", "setup"), "CLAIM": ("Statement recorded", "work"),
    "FINAL_DECISION": ("Final outcome", "final"),
}

PWM_NODES = (  # (id, PWM class, label, ring)
    ("usecase", "AIUseCase", "AI use case", 0),
    ("business", "BusinessOwner", "Business owner", 1),
    ("technology", "TechnologyOwner", "Tech owner", 1),
    ("control", "DesignatedControlFunction", "Control", 1),
    ("risk", "RiskMaterialityAssessment", "Risk rating", 1),
    ("agent", "AIAgent", "AI agent", 1),
    ("model", "AIModel", "AI model", 2),
    ("providers", "ModelProvider", "Providers", 2),
    ("identity", "WorkloadIdentity", "Identity", 2),
    ("tools", "Tool", "Tools", 2),
    ("source", "ApprovedSource", "Source", 2),
    ("retention", "RetentionPolicy", "Retention", 2),
    ("evidence", "EvidenceRecord", "Evidence", 2),
)

COMMANDS = {
    "roles": "uv run eastwind workflow client-review --role agent",
    "deny": "uv run eastwind run deny --fresh",
    "allow": "uv run eastwind run allow --echo-model",
    "research": "uv run eastwind workflow research --source unapproved",
    "egress": "uv run eastwind workflow egress",
    "suitability": "uv run eastwind workflow suitability --product INS-HK-NOTE",
    "rebalance": "uv run eastwind workflow rebalance",
    "kill": "uv run eastwind workflow kill-switch",
    "budget": "uv run eastwind workflow budget",
    "evidence": "uv run eastwind evidence export -o evidence.json && uv run kognita evidence verify --file evidence.json",
    "tamper": "uv run eastwind evidence tamper --file evidence.json -o edited.json",
    "replay": "uv run eastwind workflow replay",
    "pwm": "uv run eastwind pwm export -o pwm.ttl && uv run eastwind pwm validate pwm.ttl",
}


def _require(condition: bool, message: str) -> None:
    """A story that cannot be backed by the run is not published."""
    if not condition:
        raise RuntimeError(f"story capture: {message}")


def _workflow(result) -> dict[str, Any]:
    payload = json.loads(result.text())
    payload.pop("database", None)
    return payload


def _event_summary(event: dict[str, Any]) -> dict[str, Any]:
    label, group = EVENT_WORDS.get(event["event_type"], (event["event_type"].replace("_", " ").capitalize(), "work"))
    return {"seq": event["sequence"], "type": event["event_type"], "label": label, "group": group,
            "actor": event["actor_id"], "hash": event["event_hash"][:10], "prev": event["prev_hash"][:10]}


# ---------------------------------------------------------------------------
# Capture: real runs, every branch.
# ---------------------------------------------------------------------------

def _role_view(path: Path, role: str) -> dict[str, Any]:
    run = _workflow(client_review(path, role=role))
    steps, facts = run["steps"], run["facts"]
    profile = next((s["data"] for s in steps if s["tool"] == "client_profile" and s["data"]), None)
    holdings = next((s["data"] for s in steps if s["tool"] == "account_holdings" and s["data"]), None)
    blocked = steps[0]["outcome"] != "ALLOW" or not facts["retrieved"]
    fields = []
    for key, label in FIELD_LABELS.items():
        access = facts["field_access"][key]
        value = profile.get(key) if profile and access == "visible" else None
        if key == "investment_horizon_years" and value is not None:
            value = f"{value} years"
        fields.append({"key": key, "label": label, "access": access, "value": value})
    if holdings is None:
        account = {"label": "Account number", "access": "denied", "value": None}
        held = None
    else:
        masked = holdings["account_id"] == "[MASKED]"
        account = {"label": "Account number", "access": "masked" if masked else "visible",
                   "value": None if masked else holdings["account_id"]}
        item = holdings["holdings"][0]
        held = {"amount": item["amount"], "product": PRODUCTS[item["product_id"]]["name"]}
    return {"role": role, "label": ROLE_WORDS[role], "blocked": blocked, "outcome": steps[0]["outcome"],
            "request_id": steps[0]["request_id"], "fields": fields, "account": account, "holdings": held,
            "retrieved": facts["retrieved"]}


def _scenario_view(engine, name: str) -> dict[str, Any]:
    kwargs = {"completer": _echo_model, "destination": "local-echo", "destination_is_local": False} \
        if name == "allow" else {}
    result = run_scenario(name, engine=engine, **kwargs)
    ev = result.evaluation
    checks = [{"check": c.check, "regime": c.regime, "citation": c.citation, "result": c.result.value}
              for c in ev.checks]
    failed = [c for c in checks if c["result"] == CheckResult.FAIL.value]
    view: dict[str, Any] = {
        "name": name, "outcome": ev.outcome.value, "request_id": ev.request_id,
        "principal": ev.envelope.principal, "location": ev.envelope.actor_location,
        "client_domicile": CLIENTS[ev.envelope.subject_id]["domicile"],
        "passed": sum(1 for c in checks if c["result"] == CheckResult.PASS.value), "failed": failed,
        "total": len(checks), "retrieval_called": result.retrieval_called, "model_called": result.model_called,
        "documents": result.retrieved_titles, "sources": result.retrieved_sources,
        "skip_reason": result.model_skip_reason,
    }
    if result.retrieval_called:
        # Only how many, never which: naming a document the caller may not see would disclose it.
        view["withheld"] = ["Confidential note" for k in KNOWLEDGE if k["classification"] is Classification.C3
                            and k["title"] not in result.retrieved_titles]
    if result.egress is not None:
        e = result.egress
        view["egress"] = {"decision": e.decision.value, "classification": result.classification.value,
                          "spans": e.redacted_span_count, "tokens": list(e.token_map),
                          "pairs": [{"token": k, "original": v} for k, v in e.token_map.items()],
                          "sent": e.sent_text, "received": e.response, "manifest_hash": e.manifest_hash}
    return view


def _pwm_view(root: Path) -> dict[str, Any]:
    path = root / "pwm.db"
    create_demo_store(path)
    engine = make_engine(path)
    try:
        with Session(engine) as session:
            graph = export_graph(session, demo_profile=True)
            entry = list_usecases(session, as_of=datetime.now(timezone.utc))[0]
    finally:
        engine.dispose()
    conforms, report = validate_graph(graph)
    counts = Counter(str(o).rsplit("#", 1)[-1] for _, _, o in graph.triples((None, RDF.type, None)))
    nodes = [{"id": nid, "label": label, "count": counts[cls], "ring": ring}
             for nid, cls, label, ring in PWM_NODES if counts[cls]]
    _require(conforms, "the demonstration PWM profile does not conform to the PWM shapes")
    _require(counts["AIUseCase"] == 1, "the PWM export should describe exactly one AI use case")
    return {"conforms": bool(conforms), "triples": len(graph), "people": counts["Person"], "nodes": nodes,
            "job": entry.purpose, "business_owner": entry.business_owner,
            "technology_owner": entry.technology_owner, "tier": entry.proposed_tier,
            "max_autonomy": entry.maximum_autonomy, "ontology": str(P)}


def capture_story(root: Path | None = None) -> dict[str, Any]:
    """Run Kognita on one synthetic store and return what the walkthrough may claim."""
    if root is None:
        with tempfile.TemporaryDirectory(prefix="eastwind-story-") as raw:
            return capture_story(Path(raw))
    root.mkdir(parents=True, exist_ok=True)
    db = root / "story.db"
    engine = make_engine(db)
    try:
        # The two projector scenarios, then the wealth workflows, all on one store so
        # the evidence chain below is the receipt for the whole walkthrough.
        borders = {name: _scenario_view(engine, name) for name in ("deny", "allow")}
    finally:
        engine.dispose()
    roles = {role: _role_view(db, role) for role in ROLE_FIELDS}
    approved = _workflow(research(db))
    unapproved = _workflow(research(db, source_id="unapproved-memo"))
    blocked_egress = _workflow(egress(db))
    suit = {pid: _workflow(suitability(db, product_id=pid))["facts"]["suitability"] for pid in PRODUCTS}
    held = _workflow(rebalance(db))
    stopped = _workflow(kill_switch(db))
    spend = _workflow(budget(db))
    replayed = _workflow(replay(db))

    engine = make_engine(db)
    try:
        with Session(engine) as session:
            count = verify_chain(session)
            artifact = export_chain(session)
            agent = session.exec(select(Agent).where(Agent.name == AGENT_NAME)).one()
            colleague = {"name": agent.name, "owner": agent.owner_exec, "tier": agent.materiality_tier,
                         "risk_class": agent.risk_class, "level": agent.autonomy_level,
                         "principal": agent.principal, "tools": len([k for k in (agent.tool_allowlist or {})
                                                                      if not k.startswith("_")]),
                         "systems": list(agent.permitted_systems or []), "model": agent.model,
                         "purpose": agent.purpose}
    finally:
        engine.dispose()
    events = artifact["events"]

    # Edit one record in a copy and verify it, exactly as the admin tamper demo does.
    window = [_event_summary(e) for e in events[-24:]]
    target = events[-24:][len(window) // 3]
    edited = copy.deepcopy(artifact)
    for item in edited["events"]:
        if item["sequence"] == target["sequence"]:
            item["actor_id"] = "edited-actor"
    try:
        verify_export(edited)
    except ChainBreak as exc:
        message = str(exc)
        match = re.search(r"at sequence (\d+)", message)
        tamper = {"sequence": target["sequence"], "original": target["actor_id"], "edited": "edited-actor",
                  "error": message, "broken_at": int(match.group(1)) if match else None}
    else:
        raise RuntimeError("story capture: an edited copy of the chain passed verification")

    deny, allow = borders["deny"], borders["allow"]
    rb = held["facts"]
    reconstruction = replayed["facts"]["report"]

    # Everything the story is about to say is checked against the run first.
    failed_regimes = {c["regime"] for c in deny["failed"]} | {c["check"] for c in deny["failed"]}
    _require(deny["outcome"] == "DENY" and not deny["retrieval_called"] and not deny["model_called"],
             "the Dubai request must be denied before retrieval and before any model call")
    _require({"HK_SFC", "DIFC_DFSA", "PRODUCT_GOVERNANCE", "S1-IDENTITY"} <= failed_regimes,
             "the Dubai request must fail the four checks the story names")
    _require(all(c["regime"] in REASONS or c["check"] == "S1-IDENTITY" for c in deny["failed"]),
             "every failed check needs a plain-English reason")
    _require(deny["client_domicile"] == "DE" and allow["client_domicile"] == "SG",
             "the border copy assumes a German client for the Dubai request and a Singapore client for the other")
    _require(allow["outcome"] == "ALLOW" and allow["retrieval_called"] and allow["model_called"]
             and len(allow["documents"]) >= 1 and allow["withheld"], "the Singapore request must be allowed")
    egr = allow["egress"]
    _require(egr["decision"] == "REDACT" and egr["tokens"], "the allowed request must be redacted on egress")
    _require(CLIENTS["CL-1001"]["name"] not in egr["sent"] and CLIENTS["CL-1001"]["email"] not in egr["sent"],
             "a client identifier reached the provider side")
    _require(CLIENTS["CL-1001"]["name"] in egr["received"], "the caller side was not restored")
    _require(roles["visitor"]["blocked"] and roles["visitor"]["retrieved"] == [],
             "the visitor must be blocked before any retrieval")
    _require(not roles["agent"]["blocked"] and not roles["relationship_manager"]["blocked"],
             "the manager and the AI colleague must be admitted")
    _require(unapproved["facts"]["retrieved"] == [] and approved["facts"]["retrieved"] == ["house_view"],
             "only the approved source may be read")
    _require(blocked_egress["facts"]["blocked"] and blocked_egress["facts"]["provider_calls"] == 0,
             "the confidential file must be blocked from leaving")
    _require(suit["INS-MMF"]["suitable"] and not suit["INS-HK-NOTE"]["suitable"], "mandate check changed")
    _require(rb["held"] and rb["checkpoint"] and rb["approved_executed"] and not rb["denied_executed"]
             and rb["approved_before_stop"] and not rb["stopped_executed"], "approval and stop behaviour changed")
    _require(stopped["steps"][0]["outcome"] == "DENY" and stopped["facts"]["retrieved"] == [],
             "the emergency stop must deny the next request")
    _require([s["outcome"] for s in spend["steps"]] == ["ALLOW", "DENY"], "the budget must run out on call three")
    _require(spend["facts"]["budget_citations"] == ["max_calls"], "the refusal must cite the call budget")
    _require(replayed["facts"]["outcome"] == "ALLOW" and reconstruction["chain"]["intact"],
             "the replayed decision must still be allowed")
    _require(tamper["broken_at"] == tamper["sequence"], "the tamper check should fail at the edited record")
    _require(colleague["level"] == 0, "the colleague's registered independence level changed")

    return {
        "schema": SCHEMA,
        "meta": {"built_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                 "eastwind": eastwind_version, "kognita": kognita_version, "synthetic": True},
        "colleague": colleague, "pwm": _pwm_view(root), "roles": roles, "borders": borders,
        "sources": {"approved": approved, "unapproved": unapproved,
                    "citation": unapproved["steps"][-1]["data"]["citation"]},
        "egress_block": blocked_egress["facts"],
        "suitability": suit, "rebalance": {"facts": rb, "proposal": rb["released_proposal"], "approver": APPROVER},
        "kill": {"steps": stopped["steps"], "checks": stopped["facts"]["checks"]},
        "budget": {"steps": spend["steps"], "limit": 2, "citations": spend["facts"]["budget_citations"],
                   # The AI's own planning call is allowed first, or no tool step would exist.
                   "calls": [{"label": "Plan the task", "allowed": True}]
                            + [{"label": TOOL_WORDS[st["tool"]], "allowed": st["outcome"] == "ALLOW"}
                               for st in spend["steps"]]},
        "chain": {"count": count, "earlier": count - len(window), "window": window,
                  "types": dict(Counter(e["event_type"] for e in events)), "head": artifact["head_hash"][:10],
                  "tamper": tamper},
        "replay": {"request_id": replayed["facts"]["request_id"], "outcome": replayed["facts"]["outcome"],
                   "questions": reconstruction["questions"], "chain": reconstruction["chain"]},
    }


# ---------------------------------------------------------------------------
# Copy: headline, one plain sentence, a talk track, and the mechanics.
# ---------------------------------------------------------------------------

def _desk(principal: str) -> str:
    """'rm.sg@eastwind.example' -> 'Singapore'. Raises if the desk is not one we can name."""
    code = principal.split("@")[0].split(".")[-1].upper()
    _require(code in DESKS, f"cannot name the desk for {principal}")
    return DESKS[code]


def _reason(failure: dict[str, Any], data: dict[str, Any]) -> str:
    if failure["check"] == "S1-IDENTITY":
        return (f"This AI is assigned to the {_desk(data['colleague']['principal'])} desk. "
                f"The request came from the {_desk(data['borders']['deny']['principal'])} desk.")
    return REASONS[failure["regime"]]


def _list(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _role_sentence(view: dict[str, Any]) -> str:
    if view["blocked"]:
        return "Blocked at the gate. Nothing was fetched, so there is nothing to leak."
    fields = view["fields"] + [dict(view["account"], key="account")]
    seen = [FIELD_PHRASES[f["key"]] for f in fields if f["access"] == "visible"]
    masked = [FIELD_PHRASES[f["key"]] for f in fields if f["access"] == "masked"]
    denied = [FIELD_PHRASES[f["key"]] for f in fields if f["access"] == "denied"]
    parts = [f"Sees {_list(seen)}."]
    if masked:
        parts.append(f"Hidden behind a mask: {_list(masked)}.")
    if denied:
        parts.append(f"Not available at all: {_list(denied)}.")
    return " ".join(parts)


def build_story(data: dict[str, Any]) -> dict[str, Any]:
    """Display-ready chapters. Every number below comes from ``data``."""
    c, pwm, roles, borders = data["colleague"], data["pwm"], data["roles"], data["borders"]
    deny, allow = borders["deny"], borders["allow"]
    rb, chain = data["rebalance"], data["chain"]
    egr = allow["egress"]
    proposal = rb["proposal"]
    amount = f"S${proposal['amount']:,}"
    n_types = Counter({k: v for k, v in chain["types"].items()})
    decisions = n_types.get("POLICY_DECISION", 0)
    approvals = n_types.get("APPROVAL", 0)
    reasons = [_reason(f, data) for f in deny["failed"]]
    unsuitable = data["suitability"]["INS-HK-NOTE"]
    pairs = egr["pairs"]
    after = egr["sent"].splitlines()[:3]
    before = list(after)
    reply_out = egr["received"]
    for pair in pairs:
        before = [line.replace(pair["token"], pair["original"]) for line in before]
        reply_out = reply_out.replace(pair["original"], pair["token"])
    _require(all(pair["token"] in reply_out for pair in pairs), "the provider-side reply should carry placeholders")
    calls = data["budget"]["calls"]
    ran = [x for x in calls if x["allowed"]]
    questions = data["replay"]["questions"]
    unanswered = [q["question"] for q in questions if q["answer"] == "not recorded"]

    chapters: list[dict[str, Any]] = [
        {"id": "welcome", "name": "Welcome", "tag": "", "steps": [{
            "id": "welcome", "title": "An AI colleague that can show its work",
            "point": "Eastwind Private is a fictional private bank. You will watch one AI assistant do "
                     "real work, and see how the bank keeps it safe.",
            "say": "Three questions every board asks about AI. Can it leak client data? Can it overreach? "
                   "Can we prove what happened? We will answer each by watching one AI colleague at work.",
            "legend": [["Know", "what it may see"], ["Do", "what it may do"], ["Prove", "what we can show"]],
            "mechanics": {"command": "uv run python scripts/build_demo_page.py",
                          "facts": [["Built", data["meta"]["built_at"]], ["Eastwind", data["meta"]["eastwind"]],
                                    ["Kognita", data["meta"]["kognita"]],
                                    ["Model", "offline stand-in; no provider is contacted"]]},
        }]},
        {"id": "colleague", "name": "The new colleague", "tag": "MEET", "steps": [
            {"id": "colleague-hire", "title": "Meet your newest colleague",
             "point": "This AI assistant checks whether a product may be discussed with a client. "
                      "Like any new hire, it has a job, a manager and limits.",
             "say": "Nobody gives a new hire the keys to everything on day one. The same applies here. "
                    "It has a written job, an accountable executive, and a set level of independence.",
             "callouts": [["Job", "Tell a relationship manager whether a client may be offered a product"],
                          ["Answers to", c["owner"]],
                          ["Risk rating", f"Medium (tier {c['tier'].lstrip('T')})"],
                          ["Works for", f"The {_desk(c['principal'])} relationship manager"],
                          ["Independence", f"{LEVEL_WORDS[c['level']]}. It cannot act alone."],
                          ["Tools", f"{c['tools']} approved tools, nothing else"]],
             "mechanics": {"command": COMMANDS["pwm"],
                           "facts": [["Agent", c["name"]], ["Registered level", f"L{c['level']}"],
                                     ["Tier", c["tier"]], ["Risk class", c["risk_class"]],
                                     ["Principal", c["principal"]], ["Systems", ", ".join(c["systems"])]]}},
            {"id": "colleague-passport", "title": "Every AI gets a passport",
             "point": "Its details are written in an open standard for private wealth management (PWM), "
                      "so an auditor or another system can read them without asking us.",
             "say": "This is the PWM passport. Who owns it, who checks it, which model and tools it uses, "
                    "which sources it may read. The demo profile is illustrative, so say so if asked.",
             "callouts": [["Facts recorded", f"{pwm['triples']}"],
                          ["Named people", f"{pwm['people']}"],
                          ["Standard's checks", "Passed" if pwm["conforms"] else "Not passed"],
                          ["Status", "Illustrative profile, not an attestation"]],
             "mechanics": {"command": COMMANDS["pwm"],
                           "facts": [["Ontology", pwm["ontology"]], ["Triples", str(pwm["triples"])],
                                     ["SHACL conforms", str(pwm["conforms"])],
                                     ["Use-case tier", str(pwm["tier"])], ["Max autonomy", str(pwm["max_autonomy"])]]}},
        ]},
        {"id": "know", "name": "What may it see?", "tag": "KNOW", "steps": [
            {"id": "know-roles", "title": "Who asks decides what they see",
             "point": "The same client file looks different to each person. The check happens at the gate, "
                      "before anything is fetched.",
             "say": "Pick each person in turn. Notice the AI sees less than the manager, and the visitor sees "
                    "nothing. A denial returns no data, not filtered data.",
             "choices": [{"id": r, "label": ROLE_WORDS[r], "result": _role_sentence(roles[r]),
                          "tone": "bad" if roles[r]["blocked"] else "good"}
                         for r in ("relationship_manager", "agent", "visitor")],
             "mechanics": {"command": COMMANDS["roles"],
                           "facts": [[ROLE_WORDS[r], f"{roles[r]['outcome']} · request {roles[r]['request_id'][:8]}"]
                                     for r in roles]}},
            {"id": "know-border", "title": "The right question from the wrong desk",
             "point": "Two requests reach the gate. One is blocked before anything is read. "
                      "The other is allowed, and the AI reads only what it is entitled to see.",
             "say": f"A {_desk(deny['principal'])} manager asks about a Hong Kong structured note for a German "
                    f"client. {len(reasons)} separate checks refuse it, each with its own reason. Then a "
                    f"{_desk(allow['principal'])} manager asks a question that passes every check.",
             "choices": [
                 {"id": "deny", "label": f"{_desk(deny['principal'])} asks about a structured note",
                  "desk": f"{_desk(deny['principal'])} desk", "ask": "Can I offer this client a Hong Kong structured note?",
                  "result": f"Blocked, for {len(reasons)} separate reasons. No documents were read and the AI "
                            "was never called.", "tone": "bad"},
                 {"id": "allow", "label": f"{_desk(allow['principal'])} asks about a money-market fund",
                  "desk": f"{_desk(allow['principal'])} desk", "ask": "May I explain this money-market fund to my client?",
                  "result": f"Allowed. The AI read {len(allow['documents'])} approved documents. "
                            f"{len(allow['withheld'])} confidential note stayed out.", "tone": "good"}],
             "reasons": reasons, "documents": allow["documents"], "withheld": allow["withheld"],
             "counters": {"deny": {"passed": deny["passed"], "total": deny["total"], "read": 0, "calls": 0},
                          "allow": {"passed": allow["passed"], "total": allow["total"],
                                    "read": len(allow["documents"]), "calls": 1}},
             "mechanics": {"command": COMMANDS["deny"],
                           "facts": [[f"{_desk(deny['principal'])} request", f"{deny['outcome']} · {deny['request_id'][:8]}"]]
                                    + [[f["regime"], f["citation"] + " · " + f["check"]] for f in deny["failed"]]
                                    + [[f"{_desk(allow['principal'])} request", f"{allow['outcome']} · {allow['request_id'][:8]}"],
                                       ["Withheld", f"{len(allow['withheld'])} confidential note above the caller's ceiling"]]}},
            {"id": "know-sources", "title": "Only approved sources",
             "point": "The AI may only use documents the bank has approved. An unapproved memo is refused, "
                      "however relevant it looks.",
             "say": "This is the filing-cabinet problem: three versions of a policy, one approved. "
                    "Approval status is checked at read time, not assumed.",
             "choices": [
                 {"id": "approved", "label": "Approved house view",
                  "result": "Read. Owner, version and dates are on file.", "tone": "good"},
                 {"id": "unapproved", "label": "Unapproved memo",
                  "result": "Refused. It is not on the approved-source register.", "tone": "bad"}],
             "mechanics": {"command": COMMANDS["research"],
                           "facts": [["Approved source", "eastwind-house-view v1"],
                                     ["Refusal citation", data["sources"]["citation"]]]}},
            {"id": "know-privacy", "title": "Names never leave the building",
             "point": "Before a question goes to an outside AI provider, client names and numbers are swapped "
                      "for placeholders. The answer comes back and the real names are put back.",
             "say": "The provider is outside the bank. It sees tokens, not people. And the most confidential "
                    "material cannot leave at all.",
             "choices": [
                 {"id": "redact", "label": "Send a normal question",
                  "result": f"Sent with {egr['spans']} details replaced by placeholders.", "tone": "good"},
                 {"id": "block", "label": "Try to send a highly confidential file",
                  "result": "Stopped at the door. Nothing left the bank.", "tone": "bad"}],
             "privacy": {"before": before, "after": after, "reply_out": reply_out, "reply_in": egr["received"],
                         "pairs": pairs},
             "mechanics": {"command": COMMANDS["allow"],
                           "facts": [["Egress decision", egr["decision"]], ["Classification", egr["classification"]],
                                     ["Spans redacted", str(egr["spans"])],
                                     ["Manifest hash", egr["manifest_hash"][:16] + "…"],
                                     ["Confidential file", f"blocked · provider calls {data['egress_block']['provider_calls']}"]]}},
        ]},
        {"id": "do", "name": "What may it do?", "tag": "DO", "steps": [
            {"id": "do-authority", "title": "Access is not authority",
             "point": "Being allowed to read a file does not let the AI act. How independent it may be is set "
                      "by the bank, and this colleague sits at the bottom of the ladder.",
             "say": "Seven levels, from looking things up to acting freely. This colleague is registered at the "
                    "first. Even a safe proposal still goes to a named person.",
             "levels": list(LEVEL_WORDS), "level": c["level"],
             "choices": [
                 {"id": "safe", "label": "Check a low-risk product",
                  "result": "Fits the client's mandate: low risk against a moderate-risk client.", "tone": "good"},
                 {"id": "risky", "label": "Check a high-risk product",
                  "result": f"Does not fit the mandate: {unsuitable['product_risk']} risk against a "
                            f"{unsuitable['risk_profile']}-risk client.", "tone": "bad"}],
             "mechanics": {"command": COMMANDS["suitability"],
                           "facts": [["Registered level", f"L{c['level']} ({LEVELS[c['level']]})"],
                                     ["Mandate", f"{unsuitable['mandate']} v{unsuitable['mandate_version']}"],
                                     ["Approver", rb["approver"]]]}},
            {"id": "do-approval", "title": "Big decisions wait for a person",
             "point": f"The AI prepared a proposal to move {amount} into the money-market fund for Mei Tan. "
                      "It cannot go further on its own. The risk officer decides.",
             "say": "The work is paused and saved, not abandoned. It resumes only after a named human decides. "
                    "No trade is placed in this demo.",
             "choices": [
                 {"id": "approve", "label": "Approve",
                  "result": "Released as a proposal. The checks ran again before release. Nothing is traded.",
                  "tone": "good"},
                 {"id": "deny", "label": "Deny",
                  "result": "Stopped. Nothing was released.", "tone": "bad"}],
             "proposal": {"amount": amount, "client": "Mei Tan", "product": "SGD money market",
                          "approver": "Risk officer"},
             "mechanics": {"command": COMMANDS["rebalance"],
                           "facts": [["Suspended with checkpoint", str(rb["facts"]["checkpoint"])],
                                     ["Approved run executed", str(rb["facts"]["approved_executed"])],
                                     ["Denied run executed", str(rb["facts"]["denied_executed"])],
                                     ["Approver", rb["approver"]]]}},
            {"id": "do-stop", "title": "Approved is not the same as released",
             "point": "A second proposal is approved. Then someone spots a problem and hits the emergency "
                      "stop. The stop wins, and the AI's next request is refused.",
             "say": "Approval can go stale. Release checks run again, so a stop, a revoked permission or a "
                    "changed rule can still halt something already approved.",
             "choices": [
                 {"id": "stop", "label": "Hit the emergency stop",
                  "result": "The approved proposal was withheld at the release door.", "tone": "bad"},
                 {"id": "ask", "label": "Ask the AI for anything now",
                  "result": "Refused. The emergency stop is engaged.", "tone": "bad"}],
             "mechanics": {"command": COMMANDS["kill"],
                           "facts": [["Approved before stop", str(rb["facts"]["approved_before_stop"])],
                                     ["Executed after stop", str(rb["facts"]["stopped_executed"])],
                                     ["Checks that refused", ", ".join(data["kill"]["checks"])]]}},
            {"id": "do-limits", "title": "A spending limit on every task",
             "point": "Each task gets a budget of calls. When it is used up, the AI stops, even mid-job.",
             "say": "A runaway loop cannot run up a bill or hammer a system. Here the limit is two calls "
                    "and the task needs three.",
             "choices": [{"id": "run", "label": f"Run a task with a limit of {data['budget']['limit']} calls",
                          "result": f"The task needed {len(calls)} calls. The first {len(ran)} ran. "
                                    "The next was refused because the budget was spent.",
                          "tone": "bad"}],
             "limit": data["budget"]["limit"], "calls": calls,
             "mechanics": {"command": COMMANDS["budget"],
                           "facts": [["Outcomes", " then ".join(s["outcome"] for s in data["budget"]["steps"])],
                                     ["Citation", ", ".join(data["budget"]["citations"])]]}},
        ]},
        {"id": "prove", "name": "What can we show?", "tag": "PROVE", "steps": [
            {"id": "prove-receipt", "title": "Every decision leaves a receipt",
             "point": f"Each decision, tool use and approval is written to a record. The run behind this "
                      f"story recorded {chain['count']} entries, each sealed to the one before it.",
             "say": f"{decisions} decisions and {approvals} human approvals are in this record, alongside the "
                    "setup steps. It is a receipt, not a screenshot. These entries come from the run that "
                    "produced this story.",
             "chain": chain["window"], "earlier": chain["earlier"], "count": chain["count"],
             "mechanics": {"command": COMMANDS["evidence"],
                           "facts": [["Entries", str(chain["count"])], ["Latest seal", chain["head"] + "…"]]
                                    + [[k, str(v)] for k, v in sorted(chain["types"].items())]}},
            {"id": "prove-verify", "title": "Anyone can check the seals",
             "point": f"A checker walks the whole record and recomputes every seal. "
                      f"{chain['count']} of {chain['count']} entries match.",
             "say": "The checker needs only the exported file, not access to our systems. An independent "
                    "JavaScript verifier is published for the same export.",
             "choices": [{"id": "verify", "label": "Check the seals",
                          "result": f"All {chain['count']} entries match their seals.", "tone": "good"}],
             "mechanics": {"command": COMMANDS["evidence"],
                           "facts": [["Verified entries", str(chain["count"])], ["Latest seal", chain["head"] + "…"]]}},
            {"id": "prove-tamper", "title": "Try to change history",
             "point": "Change one entry and its seal no longer matches. The edit is detected, and the "
                      "checker says exactly where.",
             "say": "This catches edits to any entry. Be precise if asked: to catch an entire record being "
                    "rewritten, publish a checkpoint outside the system.",
             "choices": [{"id": "tamper", "label": "Edit one entry",
                          "result": f"Detected. Entry {chain['tamper']['sequence']} no longer matches its seal.",
                          "tone": "bad"}],
             "tamper": chain["tamper"],
             "mechanics": {"command": COMMANDS["tamper"],
                           "facts": [["Edited entry", str(chain["tamper"]["sequence"])],
                                     ["Changed", f"{chain['tamper']['original']} → {chain['tamper']['edited']}"],
                                     ["Checker said", chain["tamper"]["error"]]]}},
            {"id": "prove-rebuild", "title": "Rebuild what happened, including the gaps",
             "point": "Pick any past decision and replay it against the rules that applied. The report also "
                      "says what was never recorded.",
             "say": "Most systems hide their gaps. This one lists them. 'Not recorded' is an honest answer an "
                    "auditor can work with.",
             "choices": [
                 {"id": "replay", "label": "Replay the decision",
                  "result": f"Same answer today: {OUTCOME_WORDS[data['replay']['outcome']].lower()}.", "tone": "good"},
                 {"id": "report", "label": "Show the report",
                  "result": f"{len(questions) - len(unanswered)} questions answered. "
                            f"{len(unanswered)} marked not recorded.", "tone": "good"}],
             "report": [{"question": q["question"], "recorded": q["answer"] != "not recorded"} for q in questions],
             "mechanics": {"command": COMMANDS["replay"],
                           "facts": [["Replayed request", data["replay"]["request_id"][:8]],
                                     ["Outcome", data["replay"]["outcome"]],
                                     ["Chain intact", str(data["replay"]["chain"]["intact"])]]
                                    + [["Not recorded", q] for q in unanswered]}},
        ]},
        {"id": "recap", "name": "Recap", "tag": "", "steps": [{
            "id": "recap", "title": "Know. Do. Prove.",
            "point": "An AI colleague can be useful and still be governed: trusted context in, controlled "
                     "action out, and a record of every decision.",
            "say": "Permissions before retrieval. Authority before action. A record of every decision. "
                   "The decisions you saw are real Kognita decisions; the AI model is an offline stand-in.",
            "legend": [["Know", "Only approved sources, only what the person may see."],
                       ["Do", "Independence is set by the bank, and people decide the big calls."],
                       ["Prove", "A sealed record, checkable by anyone, honest about its gaps."]],
            "mechanics": {"command": "uv run eastwind showcase all --db /tmp/eastwind-showcase",
                          "facts": [[f"{_desk(deny['principal'])} request", deny["outcome"]],
                                    [f"{_desk(allow['principal'])} request", allow["outcome"]],
                                    ["Record entries", str(chain["count"])]]},
        }]},
    ]
    return {"schema": SCHEMA, "meta": data["meta"], "chapters": chapters}


def story_json() -> str:
    """Capture and build, as the JSON the walkthrough loads."""
    data = capture_story()
    return json.dumps({"data": data, "story": build_story(data)}, indent=1, sort_keys=False)
