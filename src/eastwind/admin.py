"""Server-rendered console for the synthetic wealth demo.

Plain English first: each page answers one question a director would ask. The codes, ids and
JSON that Kognita actually recorded sit behind "Show the mechanics" on every page. The console
runs no script, takes the same form fields it always has, and keeps every protection the local
(token) and public (synthetic, ephemeral) modes had.
"""
from __future__ import annotations

import copy
import hmac
import json
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlmodel import Session, select

from kognita import Run, continue_run, export_chain, replay_decision, verify_chain, verify_export
from kognita.approvals import ApprovalError, grant
from kognita.evidence import ChainBreak
from kognita.models import Agent, Approval, EvidenceEvent, GovernanceDecision, Policy, RunRecord
from kognita.reconstruct import reconstruct
from kognita.registry import set_kill_switch
from kognita.usecases import list_usecases

from eastwind import ui
from eastwind.agents.data import ACCOUNT, CLIENT, MANDATE, PRODUCTS, PROPOSAL_AMOUNT, ROLE_FIELDS, SOURCES
from eastwind.agents.workflows import APPROVER, WORKFLOWS, WealthAgent, client_review
from eastwind.pack import AGENT_NAME, AGENT_OWNER
from eastwind.pwm import create_demo_store, export_graph, validate_graph
from eastwind.ui import Raw, card, grid, h, mechanics, para, pre, stamp, stat, table
from eastwind.words import (CLASS_WORDS, DESKS, EVENT_WORDS, FIELD_LABELS, GROUP_WORDS, LEVEL_WORDS, OUTCOME_TONE,
                            OUTCOME_WORDS, POLICY_FALLBACK, POLICY_WORDS, PWM_NODES, RISK_WORDS, ROLE_PHRASES, ROLE_WORDS,
                            TOOL_WORDS, WORKFLOW_WORDS)

SOURCE_TITLES = {"client_profile": "Client profile", "account_holdings": "Account holdings",
                 "product_profile": "Product register", "house_view": "House view"}


def _json(value) -> str:
    return json.dumps(value, indent=2, default=str, sort_keys=True)


def _when(value) -> str:
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
    return str(value)


def _desk(principal: str | None) -> str:
    code = (principal or "").split("@")[0].split(".")[-1].upper()
    return DESKS.get(code, "its own")


def _tool(name: str) -> str:
    return TOOL_WORDS.get(name, name.replace("_", " ").capitalize())


def _create_app_pieces(root: Path):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    db = root / "admin.db"
    agent = WealthAgent(db)
    agent.engine.dispose()
    demo_db = root / "pwm-demo.db"
    if not demo_db.exists():
        create_demo_store(demo_db)
    from kognita import make_engine
    return db, make_engine(db), make_engine(demo_db)


def create_app(root: Path, token: str = "", *, public_demo: bool = False, prefix: str = "") -> FastAPI:
    """Create the console in token-protected or synthetic public mode."""
    if not public_demo and not token:
        raise ValueError("admin token must not be empty")
    db, engine, demo_engine = _create_app_pieces(root)
    root = Path(root)

    @asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        finally:
            engine.dispose()
            demo_engine.dispose()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.db = db
    app.state.engine = engine
    app.state.public_demo = public_demo
    pwm_cache: dict = {}

    # ----------------------------------------------------------------- helpers
    def u(path: str) -> str:
        return f"{prefix}{path}"

    def page(title: str, *body, status: int = 200, active: str = "") -> HTMLResponse:
        markup = ui.render_page(title, list(body), active=active, prefix=prefix, public_demo=public_demo)
        return HTMLResponse(markup, status_code=status, headers={
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Content-Security-Policy": ui.CSP})

    def act(path: str, label: str, **kwargs) -> Raw:
        return ui.action(u(path), label, public_demo=public_demo, **kwargs)

    def back(*links: tuple[str, str]) -> Raw:
        items: list = []
        for i, (name, path) in enumerate(links):
            if i:
                items.append(" · ")
            items.append(h("a", name, href=u(path)))
        return h("p", items, cls="muted")

    async def checked(request: Request) -> dict[str, str]:
        if request.headers.get("content-type", "").split(";")[0] != "application/x-www-form-urlencoded":
            raise HTTPException(415, "Expected a form")
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 16384:
                raise HTTPException(413, "Form too large")
            body.extend(chunk)
        try:
            data = parse_qs(body.decode("utf-8"), keep_blank_values=True, max_num_fields=20)
        except (UnicodeDecodeError, ValueError) as exc:
            raise HTTPException(400, "Invalid form") from exc
        if any(len(values) != 1 for values in data.values()):
            raise HTTPException(400, "Repeated form field")
        values = {key: items[0] for key, items in data.items()}
        supplied = values.pop("token", "")
        if not public_demo and not hmac.compare_digest(supplied.encode(), token.encode()):
            raise HTTPException(403, "Invalid admin token")
        if public_demo and any(values.get(key, "mock") not in ("", "mock") for key in ("llm", "provider")):
            raise HTTPException(400, "Public demo accepts only the mock model")
        return values

    def the_agent(session: Session) -> Agent:
        return session.exec(select(Agent).where(Agent.name == AGENT_NAME)).one()

    def pending_approvals(session: Session) -> list[tuple]:
        entries = []
        for run in session.exec(select(RunRecord)).all():
            if run.continuation_hash:
                for approval_id in run.approvals_pending:
                    item = session.get(Approval, approval_id)
                    if item:
                        entries.append((run.id, item.id, item.status.value, item.requester_id, item.expires_at))
        return entries

    def chain_status(session: Session) -> tuple[bool, int | str]:
        try:
            return True, verify_chain(session)
        except ChainBreak as exc:
            return False, str(exc)

    def proposal_summary() -> Raw:
        product = PRODUCTS["INS-MMF"]["name"]
        return h("div", h("small", "Proposal"), h("b", f"Move S${PROPOSAL_AMOUNT:,} into the {product}"),
                 h("small", f"for {CLIENT['name']}, approved by the risk officer"), cls="proposal")

    # --------------------------------------------------------------- overview
    @app.get("/", response_class=HTMLResponse)
    def dashboard():
        with Session(engine) as session:
            row = the_agent(session)
            ok, entries = chain_status(session)
            waiting = len(pending_approvals(session))
        running = not row.kill_switch
        overview = grid(
            card(stat("Your AI colleague", row.name, "good" if running else "bad"),
                 stamp("good", "Working") if running else stamp("bad", "Stopped by the emergency stop"),
                 para(h("a", "Meet it", href=u("/agents")), " · ", h("a", "Emergency stop", href=u("/kill-switch")), cls="muted")),
            card(stat("Waiting for a person", waiting, "warn" if waiting else "good"),
                 stamp("warn", "Needs a decision") if waiting else stamp("good", "Nothing waiting"),
                 para(h("a", "Open the inbox", href=u("/approvals")), cls="muted"), tone="warn" if waiting else ""),
            card(stat("The record", f"{entries} entries" if ok else "Broken", "good" if ok else "bad"),
                 stamp("good", "Every seal matches") if ok else stamp("bad", "A seal is broken"),
                 para(h("a", "See the receipt", href=u("/evidence")), cls="muted"), tone="" if ok else "bad"))
        questions = grid(
            card(h("p", "Know", cls="kick know"), h("h3", "What may it see?"),
                 para("The AI sees only what the person asking may see. Compare the manager, the AI and a visitor."),
                 para(h("a", "What can it see?", href=u("/policies")))),
            card(h("p", "Do", cls="kick do"), h("h3", "What may it do?"),
                 para("Big decisions wait for a person, an emergency stop wins, and every task has a budget."),
                 para(h("a", "Waiting for a person", href=u("/approvals")), " · ", h("a", "Run a task", href=u("/workflows")))),
            card(h("p", "Prove", cls="kick prove"), h("h3", "What can we show?"),
                 para("Every decision is in a sealed record. Replay a decision, or rebuild the story, gaps included."),
                 para(h("a", "The receipt", href=u("/evidence")), " · ", h("a", "AI passport", href=u("/pwm"))))
        )
        try_it = card(h("h3", "Try it now"), para("Each button runs a real governed task on synthetic data.", cls="muted"),
                      h("div", act("/workflows", "Ask the AI to review a client", hidden={"workflow": "client-review", "role": "agent"}),
                        act("/workflows", "Ask as a visitor", tone="bad", hidden={"workflow": "client-review", "role": "visitor"}),
                        act("/workflows", "Create a proposal for a person", tone="warn", hidden={"workflow": "rebalance", "role": "agent"}), cls="row"))
        story = (card(h("h3", "Prefer pictures?"), para("The 3D walkthrough tells the same story without a single table."),
                      para(h("a", "Watch the 3D walkthrough", href="/story/"))) if public_demo else None)
        return page("Your AI colleague, at a glance", para("Synthetic data only. Everything here is a real Kognita decision made on invented clients.", cls="lede"),
                    overview, questions, try_it, story, mechanics(
                        para(f"Agent: {row.name}. Kill switch: {'engaged' if row.kill_switch else 'off'}. Suspended runs: {waiting}. "
                             f"{'Chain verified: ' + str(entries) + ' events' if ok else 'Chain broken: ' + str(entries)}.")),
                    active="/")

    @app.get("/tour", response_class=HTMLResponse)
    def tour():
        steps = grid(
            card(h("p", "Permitted context", cls="kick know"), h("h3", "Who may see what"),
                 para("Compare the relationship manager and the AI colleague on ", h("a", "What can it see?", href=u("/policies")),
                      ", then ", h("a", "review a client", href=u("/workflows")), ". The AI is given masked or blocked fields, and the "
                      "check comes before anything is fetched. Research shows the approved-source check.")),
            card(h("p", "Mandated action", cls="kick do"), h("h3", "What it may do"),
                 para("Meet the colleague on ", h("a", "Your AI colleague", href=u("/agents")), ", then prepare a trade proposal. It waits in ",
                      h("a", "Waiting for a person", href=u("/approvals")), ". To test release controls, approve one without releasing it, "
                      "engage the ", h("a", "emergency stop", href=u("/kill-switch")), ", then approve: the action is withheld. Release the stop afterwards.")),
            card(h("p", "Provable record", cls="kick prove"), h("h3", "What we can show"),
                 para("Open ", h("a", "The receipt", href=u("/evidence")), " to check the seals and try to change history on a copy. "
                      "Use ", h("a", "Would we decide the same?", href=u("/replay")), " and ", h("a", "Rebuild what happened", href=u("/reconstruction")),
                      ". Anything that was not recorded stays visibly missing.")))
        return page("Guided tour", para("Three steps, with synthetic data: permitted context, mandated action, and a provable record.", cls="lede"),
                    steps, para("Also: ", h("a", "Spending limits", href=u("/budgets")), " and ", h("a", "AI passport", href=u("/pwm")), "."),
                    active="/tour")

    # -------------------------------------------------------------- the colleague
    @app.get("/agents", response_class=HTMLResponse)
    def agents():
        with Session(engine) as session:
            rows = session.exec(select(Agent)).all()
            jobs = {e.usecase_id: e.purpose for e in list_usecases(session, as_of=datetime.now(timezone.utc))}
        cards = []
        raw_tables = []
        for row in rows:
            tool_keys = [k for k in (row.tool_allowlist or {}) if not k.startswith("_")]
            tools = sorted(_tool(k) for k in tool_keys)
            level = row.autonomy_level if isinstance(row.autonomy_level, int) else 0
            job = jobs.get(row.purpose) or row.purpose
            tier = (row.materiality_tier or "").lstrip("T")
            cards.append(card(
                h("div", stamp("bad", "Stopped") if row.kill_switch else stamp("good", "Working"), cls="result"),
                h("h2", row.name),
                grid(card(h("small", "Job"), h("p", job)),
                     card(h("small", "Answers to"), h("p", row.owner_exec)),
                     card(h("small", "Works for"), h("p", f"The {_desk(row.principal)} relationship manager")), cols=3),
                grid(card(h("small", "Risk rating"), h("p", f"{RISK_WORDS.get((row.risk_class or '').lower(), row.risk_class)} (tier {tier})")),
                     card(h("small", "Tools"), h("p", f"{len(tools)} approved, nothing else"),
                          h("details", h("summary", "List them"), h("p", ", ".join(tools)), cls="plain")),
                     card(h("small", "Hard limits"), h("p", "None registered. Each task gets its own call budget.") if not row.blast_radius
                          else h("p", f"{len(row.blast_radius)} registered")), cols=3),
                h("h3", "How independent it is"),
                para(f"{LEVEL_WORDS[min(level, 6)]}. The bank sets this level, not the AI. Trade proposals also always wait for ", APPROVER, ".", cls="muted"),
                ui.ladder(LEVEL_WORDS, level)))
            raw_tables.append(table(["Field", "Value"], [
                ("Agent", row.name), ("Mandate and use cases", row.purpose), ("Tools", ", ".join(k for k in (row.tool_allowlist or {}) if not k.startswith("_"))),
                ("Data scopes", json.dumps(row.field_allowlist)), ("Permitted systems", ", ".join(row.permitted_systems or [])),
                ("Autonomy level", f"{row.autonomy_level} (Kognita registered level)"), ("Proposal approver", APPROVER),
                ("Risk tier", row.materiality_tier), ("Risk class", row.risk_class), ("Hard limits", json.dumps(row.blast_radius or {})),
                ("Owner", row.owner_exec), ("Synthetic client mandate", json.dumps(MANDATE))]))
        mandate = card(h("h3", "The client's mandate"),
                       para(f"{CLIENT['name']} has a {RISK_WORDS.get(MANDATE['risk_ceiling'], MANDATE['risk_ceiling'])}-risk mandate. "
                            "Nothing riskier than that can be proposed for them."),
                       para(f"Approver for proposals: {APPROVER}.", cls="muted"))
        return page("Your AI colleague", para("A new hire has a job, a manager and limits. So does this one.", cls="lede"),
                    cards, mandate, mechanics(raw_tables, para("The registered level is separate from the human approval policy for trade proposals.", cls="muted")),
                    active="/agents")

    # ------------------------------------------------------------- what may it see
    @app.get("/policies", response_class=HTMLResponse)
    def policies(role: str = "agent"):
        if role not in ROLE_FIELDS:
            raise HTTPException(400, "Unknown role")
        with Session(engine) as session:
            rows = session.exec(select(Policy)).all()
            register = [(p.regime, p.rule_type, p.citation) for p in rows]
            rules = []
            for p in rows:
                title, sentence = POLICY_WORDS.get(p.regime, (p.regime.replace("_", " ").title(), POLICY_FALLBACK.get(p.rule_type, "See the register.")))
                rules.append(h("li", h("b", title), h("span", f": {sentence}"), h("small", p.citation), cls="rule"))
        fields = ROLE_FIELDS[role]
        rows_html = []
        for key, label in FIELD_LABELS.items():
            access = fields[key]
            value = CLIENT[key] if access == "visible" else None
            if key == "investment_horizon_years" and value is not None:
                value = f"{value} years"
            rows_html.append(ui.file_row(label, access, value))
        account = {"relationship_manager": "visible", "agent": "masked", "visitor": "denied"}[role]
        rows_html.append(ui.file_row("Account number", account, ACCOUNT["id"] if account == "visible" else None))
        if role != "visitor":
            rows_html.append(ui.file_row("Holds", "visible", f"S${ACCOUNT['holdings'][0]['amount']:,} in {PRODUCTS[ACCOUNT['holdings'][0]['product_id']]['name']}"))
        access = {
            "relationship_manager": ["visible and masked fields", "visible", "visible", "visible"],
            "agent": ["visible, masked and denied fields", "visible holdings, masked account ID", "visible", "visible"],
            "visitor": ["denied", "denied", "denied", "denied"],
        }
        stances = {"relationship_manager": ("good", "Allowed"), "agent": ("warn", "Partly masked"), "visitor": ("bad", "Blocked")}
        def source_stamp(name: str) -> Raw:
            if role == "visitor":
                return stamp("bad", "Blocked")
            return stamp(*stances[role]) if name in ("client_profile", "account_holdings") else stamp("good", "Allowed")

        source_cards = [card(h("h3", SOURCE_TITLES.get(name, name)), source_stamp(name),
                             para(f"Owner: {v['owner']}. {CLASS_WORDS.get(v['classification'], v['classification'])} data.", cls="muted"),
                             para(f"Valid {v['effective'][:10]}" + (f" to {v['expiry'][:10]}" if v.get("expiry") else ""), cls="muted"))
                        for name, v in SOURCES.items()]
        raw_sources = [(name, v["owner"], v["classification"], v["lineage"], v["version"],
                        f"{v['effective']} to {v.get('expiry', 'not specified')}", ", ".join(v["purposes"])) for name, v in SOURCES.items()]
        pill_items = [(ROLE_WORDS[r], u(f"/policies?{urlencode({'role': r})}")) for r in ROLE_FIELDS]
        return page("What can it see?", para("The same client file looks different to each person. The check happens before anything is fetched.", cls="lede"),
                    ui.pills(pill_items, u(f"/policies?{urlencode({'role': role})}")),
                    grid(card(h("h2", f"The file, as the {ROLE_PHRASES[role]} sees it"), *rows_html, tone=stances[role][0]),
                         card(h("h2", "Where it comes from"), h("div", source_cards, cls="grid c2")), cols=2),
                    card(h("h2", "The rules"), h("ul", rules, cls="rules")),
                    mechanics(table(["Source", f"Access for {role}"], zip(SOURCES, access[role], strict=True)),
                              table(["Client profile field", role], ROLE_FIELDS[role].items()),
                              para("Account identifier: visible to the relationship manager, masked for the agent, denied to a visitor. "
                                   "Product and house-view access is subject to the workflow policy and source checks."),
                              h("h3", "Sources"),
                              table(["Source", "Owner", "Classification", "Lineage", "Version", "Freshness", "Permitted purposes"], raw_sources),
                              h("h3", "Policy register"), table(["Regime", "Rule", "Citation"], register)),
                    active="/policies")

    # ------------------------------------------------------ waiting for a person
    @app.get("/approvals", response_class=HTMLResponse)
    def approvals():
        with Session(engine) as session:
            entries = pending_approvals(session)
        cards = []
        for run_id, approval_id, status, requester, expires in entries:
            hidden = {"run": str(run_id), "approval": str(approval_id)}
            held = status != "PENDING"
            cards.append(card(
                h("div", stamp("warn", "Approved, not yet released") if held else stamp("warn", "Waiting for a person"), cls="result"),
                proposal_summary(),
                para(f"Asked for by {requester}. Expires {_when(expires)}.", cls="muted"),
                h("div", act("/approvals/resolve", "Approve", tone="good", hidden={**hidden, "resolution": "approve"}),
                  act("/approvals/resolve", "Deny", tone="bad", hidden={**hidden, "resolution": "deny"}),
                  None if held else act("/approvals/grant", "Approve, but hold the release", tone="warn", small=True, hidden=hidden,
                                        note="Records the approval without releasing. Use it to test the emergency stop."), cls="row"),
                tone="warn"))
        empty = card(h("div", h("h3", "Nothing is waiting for a person"),
                       para("The AI pauses on any trade proposal. Create one to see it arrive here.", cls="muted"),
                       act("/workflows", "Create a proposal", tone="warn", hidden={"workflow": "rebalance", "role": "agent"})), cls="empty")
        raw = table(["Run", "Approval", "Status", "Requester", "Expires"], entries)
        return page("Waiting for a person", para("The risk officer decides. Release checks run again after an approval, so a stop or a changed rule can still halt it.", cls="lede"),
                    cards or empty, mechanics(raw, para("Run the rebalance workflow to create a suspended proposal. The named synthetic risk officer resolves each request. "
                                                         "To test a stop after approval, approve without release, engage the switch, then resolve with approve.", cls="muted")),
                    active="/approvals")

    @app.post("/approvals/grant", response_class=HTMLResponse)
    async def grant_without_release(request: Request):
        values = await checked(request)
        try:
            approval_id = int(values.get("approval", ""))
        except ValueError:
            raise HTTPException(400, "Invalid approval")
        with Session(engine) as session:
            run = session.get(RunRecord, values.get("run", ""))
            item = session.get(Approval, approval_id)
            if not run or not run.continuation_hash or approval_id not in run.approvals_pending or not item:
                raise HTTPException(404, "Suspended approval not found")
            decision = session.get(GovernanceDecision, item.decision_id)
            if not decision or item.status.value != "PENDING":
                raise HTTPException(409, "Approval is not pending")
            from kognita import EvidenceWriter
            try:
                grant(session, item, approver_name=APPROVER, evidence=EvidenceWriter(engine), correlation_id=decision.request_id)
            except ApprovalError as exc:
                raise HTTPException(409, str(exc)) from exc
            session.commit()
        return page("Approval recorded", card(stamp("warn", "Approved, not yet released"),
                    para("The approval is recorded. The run is still suspended and the release checks will run again."),
                    back(("Back to the inbox", "/approvals"), ("Emergency stop", "/kill-switch")), tone="warn"), active="/approvals")

    @app.post("/approvals/resolve", response_class=HTMLResponse)
    async def resolve(request: Request):
        values = await checked(request)
        if values.get("resolution") not in {"approve", "deny"}:
            raise HTTPException(400, "Unknown resolution")
        try:
            approval_id = int(values.get("approval", ""))
        except ValueError:
            raise HTTPException(400, "Invalid approval")
        worker = WealthAgent(db)
        try:
            with Session(worker.engine) as session:
                run = session.get(RunRecord, values.get("run", ""))
                if not run or not run.continuation_hash or approval_id not in run.approvals_pending:
                    raise HTTPException(404, "Suspended approval not found")
                try:
                    result = continue_run(session, run.id, {approval_id: values["resolution"] == "approve"},
                                          evidence=worker.writer, registry=worker.registry, approver_name=APPROVER)
                except ApprovalError as exc:
                    raise HTTPException(409, str(exc)) from exc
                session.commit()
                output = {"outcome": result.outcome.value, "data": result.data,
                          "executed": result.data is not None, "approver": APPROVER}
        finally:
            worker.engine.dispose()
        if values["resolution"] == "deny":
            verdict = (stamp("bad", "Denied"), "Nothing was released.", "bad")
        elif output["executed"]:
            verdict = (stamp("good", "Released as a proposal"), "The checks ran again before release. Nothing is traded in this demo.", "good")
        else:
            verdict = (stamp("warn", "Approved, but not released"), "The release checks stopped it. For example, the emergency stop is on.", "warn")
        return page("Approval resolved", card(h("div", verdict[0], cls="result"), para(verdict[1]),
                    back(("Back to the inbox", "/approvals"), ("The receipt", "/evidence")), tone=verdict[2]),
                    mechanics(pre(_json(output))), active="/approvals")

    # ----------------------------------------------------------- emergency stop
    def stop_page():
        with Session(engine) as session:
            engaged = bool(the_agent(session).kill_switch)
        state = "engaged" if engaged else "off"
        body = card(
            h("div", stamp("bad", "STOPPED") if engaged else stamp("good", "Running normally"), cls="result"),
            para("The AI is refused everything, and anything already approved is withheld at release." if engaged
                 else "The AI is working. The emergency stop is off."),
            act("/kill-switch", "Release the stop" if engaged else "Engage the emergency stop", tone="good" if engaged else "bad",
                hidden={"state": "release" if engaged else "engage"}), tone="bad" if engaged else "good")
        return page("Emergency stop", para("One switch halts the AI, even for something a person already approved.", cls="lede"), body,
                    mechanics(para(f"Current state: {state}. This switch governs the admin store, including pending approvals.")), active="/kill-switch")

    @app.get("/kill-switch", response_class=HTMLResponse)
    def kill_switch():
        return stop_page()

    @app.post("/kill-switch", response_class=HTMLResponse)
    async def change_switch(request: Request):
        values = await checked(request)
        if values.get("state") not in {"engage", "release"}:
            raise HTTPException(400, "Unknown switch state")
        with Session(engine) as session:
            from kognita import EvidenceWriter
            set_kill_switch(session, AGENT_NAME, values["state"] == "engage", evidence=EvidenceWriter(engine),
                            actor_id=AGENT_OWNER, reason="Local admin action")
            session.commit()
        return stop_page()

    # ----------------------------------------------------------- spending limits
    @app.get("/budgets", response_class=HTMLResponse)
    def budgets():
        with Session(engine) as session:
            rows = session.exec(select(RunRecord)).all()
        items = []
        for r in rows:
            used_all = r.max_calls is not None and r.calls_used >= r.max_calls
            items.append(h("li", h("span", f"Task {str(r.id)[:8]}"), ui.meter(r.calls_used, r.max_calls, f"{r.calls_used} of {r.max_calls} calls used"),
                           stamp("warn", "Used every call") if used_all else stamp("good", "Within budget")))
        body = (card(h("ul", items, cls="steps")) if items else
                card(h("div", h("h3", "No tasks have run yet"), para("Run a client review to see its budget here.", cls="muted"),
                       act("/workflows", "Review a client", hidden={"workflow": "client-review", "role": "agent"})), cls="empty"))
        raw = table(["Run", "Calls used", "Maximum calls", "Tokens used", "Maximum tokens", "Cost used", "Maximum cost"],
                    [(r.id, r.calls_used, r.max_calls, r.tokens_used, r.max_tokens, r.cost_usd_used, r.max_cost_usd) for r in rows])
        return page("Spending limits", para("Every task gets a budget of calls. When it is used up, the AI stops, even mid-job.", cls="lede"),
                    body, card(h("h3", "See it run out"), para("Give the AI a budget of two calls for a task that needs three.", cls="muted"),
                               act("/workflows", "Run out of calls", tone="warn", hidden={"workflow": "budget", "role": "agent"})),
                    mechanics(para("Choose a call limit when running client review. A limit of 2 demonstrates exhaustion."), raw), active="/budgets")

    # -------------------------------------------------------------- the receipt
    @app.get("/evidence", response_class=HTMLResponse)
    def evidence():
        with Session(engine) as session:
            ok, count = chain_status(session)
            events = session.exec(select(EvidenceEvent).order_by(EvidenceEvent.sequence.desc()).limit(100)).all()
        recent = []
        for e in events[:25]:
            label, group = EVENT_WORDS.get(e.event_type.value, (e.event_type.value.replace("_", " ").capitalize(), "work"))
            recent.append((group, f"#{e.sequence} · {label}", f"{e.actor_id} · {_when(e.recorded_at)}", u(f"/evidence/event?sequence={e.sequence}")))
        raw_rows = [(e.sequence, e.event_type.value, e.actor_id, e.correlation_id, e.event_hash) for e in events]
        verdict = (card(h("div", stamp("good", f"All {count} entries match their seals"), cls="result"),
                        para("Each decision, tool use and approval is an entry, sealed to the one before it."), tone="good") if ok else
                   card(h("div", stamp("bad", "A seal is broken"), cls="result"), para(str(count)), tone="bad"))
        tamper = card(h("h3", "Try to change history"), para("This edits one entry in a copy and checks it. Your record is never touched.", cls="muted"),
                      act("/evidence/tamper", "Edit an entry in a copy", tone="warn",
                          fields=[h("label", "Replace the actor with ", ui.void("input", name="actor_id", value="edited-actor", required="required"))]))
        export = card(h("h3", "Take it away"), para(h("a", "Download the evidence file", href=u("/evidence/export")), cls=""),
                      para("Python verification runs here. Verify an exported bundle locally with ", h("code", "npx --yes @kognita/verify@0.9.0 evidence.json"), ".", cls="muted")
                      if public_demo else para("Anyone can check the file with a program that is not ours.", cls="muted"))
        lookup = h("form", h("label", "Entry number ", ui.void("input", name="sequence", required="required")), ui.button("View entry", "primary", small=True),
                   method="get", action=u("/evidence/event"), cls="action")
        return page("The receipt", para("A receipt, not a screenshot: the whole story of what the AI did, checkable by anyone.", cls="lede"), verdict,
                    grid(tamper, export, cols=2), card(h("h2", "Most recent entries"), ui.timeline(recent)),
                    mechanics(para(f"{'Chain verified: ' + str(count) + ' events' if ok else 'Chain broken: ' + str(count)}. Showing up to 100 latest events. "
                                   "The tamper demo edits a copy and verifies it; the source chain is untouched."),
                              lookup, table(["Sequence", "Type", "Actor", "Correlation", "Hash"], raw_rows)), active="/evidence")

    @app.get("/evidence/event", response_class=HTMLResponse)
    def evidence_event(sequence: int):
        with Session(engine) as session:
            event = session.exec(select(EvidenceEvent).where(EvidenceEvent.sequence == sequence)).first()
            if event is None:
                raise HTTPException(404, "Evidence event not found")
            details = {"sequence": event.sequence, "event_type": event.event_type.value,
                       "actor_type": event.actor_type.value, "actor_id": event.actor_id,
                       "correlation_id": event.correlation_id, "recorded_at": event.recorded_at,
                       "payload": event.payload, "payload_hash": event.payload_hash,
                       "previous_hash": event.prev_hash, "event_hash": event.event_hash}
        label, group = EVENT_WORDS.get(details["event_type"], (details["event_type"].replace("_", " ").capitalize(), "work"))
        return page("One entry in the record", card(h("h2", f"#{sequence} · {label}"),
                    para(f"Made by {details['actor_id']} ({details['actor_type'].lower()}) at {_when(event.recorded_at)}."),
                    para(f"It is sealed to entry #{sequence - 1}. Change it and that seal stops matching." if sequence > 1 else "It is the first entry.", cls="muted")),
                    back(("Back to the receipt", "/evidence")), mechanics(pre(_json(details)), open_=False), active="/evidence")

    @app.get("/evidence/export")
    def evidence_export():
        with Session(engine) as session:
            verify_chain(session)
            payload = export_chain(session)
        return Response(json.dumps(payload, indent=2), media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="evidence.json"', "Cache-Control": "no-store"})

    @app.post("/evidence/tamper", response_class=HTMLResponse)
    async def tamper(request: Request):
        values = await checked(request)
        with Session(engine) as session:
            verify_chain(session)
            artifact = copy.deepcopy(export_chain(session))
        if not artifact["events"]:
            raise HTTPException(409, "No evidence to edit")
        replacement = values.get("actor_id", "edited-actor")
        if not replacement or replacement == artifact["events"][0]["actor_id"]:
            raise HTTPException(400, "Enter a different actor")
        artifact["events"][0]["actor_id"] = replacement
        try:
            verify_export(artifact)
        except (ChainBreak, ValueError) as exc:
            return page("Tamper demonstration", card(h("div", stamp("bad", "Detected"), cls="result"),
                        para("The edited copy no longer matches its seals. The checker says where."),
                        para("Edited copy failed Python verification, as expected.", cls="muted"),
                        back(("Back to the receipt", "/evidence")), tone="bad"), mechanics(pre(str(exc))), active="/evidence")
        return page("Tamper demonstration", para("Unexpected: edited copy passed verification."), status=500, active="/evidence")

    # ------------------------------------------------ would we decide the same?
    def decision_rows(session: Session, limit: int):
        return session.exec(select(GovernanceDecision).order_by(GovernanceDecision.id.desc()).limit(limit)).all()

    @app.get("/replay", response_class=HTMLResponse)
    def replaypage():
        with Session(engine) as session:
            rows = decision_rows(session, 100)
        recent = [h("li", h("span", f"{_tool(r.tool)}", h("small", f" · {r.agent_name or r.principal} · {_when(r.decided_at)}")),
                    stamp(OUTCOME_TONE.get(r.outcome.value, "info"), OUTCOME_WORDS.get(r.outcome.value, r.outcome.value)),
                    act("/replay", "Replay", hidden={"request_id": r.request_id}, small=True))
                  for r in rows[:10]]
        body = (card(h("h2", "Recent decisions"), h("ul", recent, cls="steps")) if recent else
                card(h("div", h("h3", "Nothing to replay yet"), para("Review a client first.", cls="muted"),
                       act("/workflows", "Review a client", hidden={"workflow": "client-review", "role": "agent"})), cls="empty"))
        form = ui.action(u("/replay"), "Replay", public_demo=public_demo,
                         fields=[h("label", "Request ID ", ui.void("input", name="request_id", required="required"))])
        return page("Would we decide the same today?", para("Pick any recorded decision and run it again against the rules and inputs it had.", cls="lede"), body,
                    mechanics(para("Replay a recorded decision against its pinned inputs."), form,
                              table(["Request", "Tool", "Outcome"], [(r.request_id, r.tool, r.outcome.value) for r in rows])), active="/replay")

    @app.post("/replay", response_class=HTMLResponse)
    async def replay_action(request: Request):
        values = await checked(request)
        with Session(engine) as session:
            try:
                result = replay_decision(session, values.get("request_id", ""))
                output = {"request_id": result.request_id, "outcome": result.outcome.value,
                          "checks": [{"check": c.check, "result": c.result.value, "citation": c.citation} for c in result.checks]}
            except Exception as exc:
                return page("Replay failed", card(stamp("bad", "Could not replay"), para("That decision could not be replayed."),
                            back(("Back", "/replay")), tone="bad"), mechanics(pre(str(exc)), open_=True), status=400, active="/replay")
        failed = [c for c in output["checks"] if c["result"].lower() == "fail"]
        tone = OUTCOME_TONE.get(output["outcome"], "info")
        return page("Replay result", card(
            h("div", h("h2", "Same answer today:"), stamp(tone, OUTCOME_WORDS.get(output["outcome"], output["outcome"])), cls="result"),
            para(f"{len(output['checks']) - len(failed)} of {len(output['checks'])} checks passed" + (f"; {len(failed)} did not." if failed else ".")),
            back(("Back to decisions", "/replay"), ("The receipt", "/evidence")), tone=tone),
            mechanics(pre(_json(output))), active="/replay")

    # --------------------------------------------------- rebuild what happened
    @app.get("/reconstruction", response_class=HTMLResponse)
    def reconstruction():
        from kognita.models import Interaction
        with Session(engine) as session:
            rows = session.exec(select(Interaction)).all()
        items = [h("li", h("span", f"Review of {r.client_id}", h("small", f" · {r.use_case} · {str(r.id)[-8:]}")),
                   act("/reconstruction", "Rebuild", hidden={"interaction_id": r.id}, small=True)) for r in rows[-10:]]
        body = (card(h("h2", "Past interactions"), h("ul", items, cls="steps")) if items else
                card(h("div", h("h3", "Nothing to rebuild yet"), para("Review a client first.", cls="muted"),
                       act("/workflows", "Review a client", hidden={"workflow": "client-review", "role": "agent"})), cls="empty"))
        form = ui.action(u("/reconstruction"), "Reconstruct", public_demo=public_demo,
                         fields=[h("label", "Interaction or correlation ID ", ui.void("input", name="interaction_id", required="required"))])
        return page("Rebuild what happened", para("Reports identify missing evidence as well as recorded facts.", cls="lede"), body,
                    mechanics(form, table(["Interaction", "Client", "Use case"], [(r.id, r.client_id, r.use_case) for r in rows])), active="/reconstruction")

    @app.post("/reconstruction", response_class=HTMLResponse)
    async def reconstruct_action(request: Request):
        values = await checked(request)
        with Session(engine) as session:
            report = reconstruct(session, values.get("interaction_id", ""))
        questions = report.get("questions", []) if isinstance(report, dict) else []
        cells = [h("div", h("small", "Not recorded" if q["answer"] == "not recorded" else "Recorded"), q["question"],
                   cls="q " + ("no" if q["answer"] == "not recorded" else "yes")) for q in questions]
        intact = isinstance(report, dict) and (report.get("chain") or {}).get("intact")
        missing = sum(1 for q in questions if q["answer"] == "not recorded")
        return page("Rebuild what happened", card(
            h("div", stamp("good", "The record is intact") if intact else stamp("warn", "Check the record"), cls="result"),
            para(f"{len(questions) - missing} questions can be answered from the record. {missing} are marked not recorded: the gaps are shown, not hidden."),
            h("div", cells, cls="qgrid")), back(("Pick another", "/reconstruction")),
            mechanics(pre(_json(report)), summary="Reconstruction report (raw)"), active="/reconstruction")

    # -------------------------------------------------------------- AI passport
    def pwm_counts():
        if "counts" not in pwm_cache:
            from rdflib import RDF
            with Session(demo_engine) as session:
                graph = export_graph(session, demo_profile=True)
            counts = Counter(str(o).rsplit("#", 1)[-1] for _, _, o in graph.triples((None, RDF.type, None)))
            pwm_cache["counts"] = (len(graph), counts)
        return pwm_cache["counts"]

    @app.get("/pwm", response_class=HTMLResponse)
    def pwmpage():
        facts, counts = pwm_counts()
        parts = [card(stat(label, counts[cls], ""), cls="mini") for _, cls, label, _ in PWM_NODES if counts[cls]]
        downloads = card(h("h3", "Take the passport"), para(h("a", "Download the demonstration passport", href=u("/pwm/export?source=demo")), " · ",
                                                           h("a", "Download the live register", href=u("/pwm/export?source=admin"))),
                         para("Both are in the open PWM format, readable by an auditor or another system.", cls="muted"))
        check = card(h("h3", "Check it against the standard"),
                     para("The demonstration passport includes illustrative declarations. The live register has only what Kognita itself records, so it can fall short.", cls="muted"),
                     h("div", act("/pwm/validate", "Check the demonstration passport", hidden={"source": "demo"}),
                       act("/pwm/validate", "Check the live register", tone="warn", hidden={"source": "admin"}), cls="row"))
        return page("AI passport", para("Who owns this AI, who checks it, which model and tools it uses and which sources it may read, written in an open standard.", cls="lede"),
                    card(h("h2", f"The demonstration passport holds {facts} facts"), para("Illustrative profile for this synthetic demo, not an attestation.", cls="muted"),
                         h("div", parts, cls="grid c4")), grid(downloads, check, cols=2),
                    mechanics(para("The demo export includes explicit synthetic profile declarations. The admin store export includes only its recorded fields and can fail validation "
                                   "when metadata is missing. SHACL checks structure, not cryptographic signatures.")), active="/pwm")

    @app.get("/pwm/export")
    def pwm_export(source: str = "demo"):
        if source not in {"demo", "admin"}:
            raise HTTPException(400, "Unknown PWM source")
        with Session(demo_engine if source == "demo" else engine) as session:
            rdf = export_graph(session, demo_profile=source == "demo").serialize(format="turtle")
        return Response(rdf, media_type="text/turtle", headers={"Content-Disposition": 'attachment; filename="eastwind-pwm.ttl"', "Cache-Control": "no-store"})

    @app.post("/pwm/validate", response_class=HTMLResponse)
    async def pwm_validate(request: Request):
        values = await checked(request)
        source = values.get("source", "demo")
        if source not in {"demo", "admin"}:
            raise HTTPException(400, "Unknown PWM source")
        with Session(demo_engine if source == "demo" else engine) as session:
            graph = export_graph(session, demo_profile=source == "demo")
        conforms, report = validate_graph(graph)
        explanation = ("It has everything the standard asks for." if conforms else
                       "It is missing information the standard asks for. That is expected for the live register: it records only what Kognita itself stores.")
        return page("PWM validation", card(
            h("div", stamp("good", "Passes the standard") if conforms else stamp("warn", "Falls short of the standard"), cls="result"),
            para(f"Checked: the {'demonstration passport' if source == 'demo' else 'live register'}. {explanation}"),
            para(f"Conforms: {conforms}", cls="muted"), back(("Back to the passport", "/pwm")), tone="good" if conforms else "warn"),
            mechanics(pre(str(report)), summary="Validation report (raw)"), active="/pwm")

    # ------------------------------------------------------------- run a task
    @app.get("/workflows", response_class=HTMLResponse)
    def workflows():
        sections = []
        for group, title in GROUP_WORDS.items():
            cards = []
            for name, (label, g, blurb) in WORKFLOW_WORDS.items():
                if g != group:
                    continue
                local_only = name in {"mcp", "degraded"}
                if local_only and public_demo:
                    cards.append(card(h("h3", label), para(blurb, cls="muted"), stamp("info", "Needs the command line"),
                                      para(f"Run it with: eastwind workflow {name}", cls="muted")))
                    continue
                fields = []
                if name == "client-review":
                    fields = [h("label", "As ", h("select", [h("option", ROLE_WORDS[r], value=r, selected=(r == "agent") or None) for r in ROLE_FIELDS], name="role")),
                              h("label", "Call budget ", ui.void("input", name="max_calls", value="4", size="3", required="required"))]
                cards.append(card(h("h3", label), para(blurb, cls="muted"),
                                  act("/workflows", "Run it", fields=fields, hidden={"workflow": name, **({} if name == "client-review" else {"role": "agent"})},
                                      note="Drills use isolated simulation stores." if name in {"kill-switch", "mcp", "degraded"} else "")))
            sections.append((h("h2", title), grid(*cards, cols=3)))
        return page("Run a task", para("Each task is a real governed run on synthetic data. Results come back in plain English, with the raw record one click away.", cls="lede"),
                    sections, mechanics(para("Client review, suitability, research, egress, budget and replay use the admin store. Rebalance suspends for the approvals queue. "
                                             + ("The serverless demo uses an in-process mock. MCP and degraded gateway drills require the local CLI."
                                                if public_demo else "Kill-switch, MCP and degraded-mode drills use isolated simulation stores."))), active="/workflows")

    def summarize(name: str, role: str, out: dict) -> tuple[str, str, str, list[tuple[str, str]]]:
        """(tone, verdict word, headline, lines). The verdict is the right word for the task, not just Allowed or Blocked."""
        steps, facts = out.get("steps") or [], out.get("facts") or {}
        lines = [(OUTCOME_TONE.get(s.get("outcome", ""), "info"),
                  f"{_tool(s.get('tool', ''))}: {OUTCOME_WORDS.get(s.get('outcome', ''), s.get('outcome', ''))}") for s in steps]
        if name == "client-review":
            if not facts.get("retrieved"):
                return "bad", "Blocked", f"The {ROLE_PHRASES[role]} was blocked. Nothing was fetched.", lines
            seen = " and ".join(_tool(t).replace("Read the ", "").lower() for t in facts["retrieved"])
            lines += [("info", f"{FIELD_LABELS[k]}: {v}") for k, v in facts.get("field_access", {}).items() if k in FIELD_LABELS]
            return "good", "Allowed", f"The {ROLE_PHRASES[role]} was given the {seen}.", lines
        if name == "suitability":
            s = facts.get("suitability") or {}
            detail = f"{s.get('product_risk')} risk against a {s.get('risk_profile')}-risk client."
            return ("good", "Fits the mandate", f"Fits the mandate: {detail}", lines) if s.get("suitable") else \
                   ("bad", "Over the mandate", f"Does not fit the mandate: {detail}", lines)
        if name == "research":
            if "house_view" in (facts.get("retrieved") or []):
                return "good", "Allowed", "Read the approved house view.", lines
            return "bad", "Refused", "The source was refused: it is not on the approved register.", lines
        if name == "egress":
            if facts.get("blocked"):
                lines.append(("good", "Sending it to an outside provider: Stopped"))
                return "good", "Stopped", f"The confidential data did not leave the bank. Calls to the provider: {facts.get('provider_calls', 0)}.", lines
            return "bad", "Sent", "The data was sent.", lines
        if name == "budget":
            return "warn", "Budget spent", "The task needed more calls than it was given, so the last one was refused.", lines
        if name == "kill-switch":
            return "bad", "Blocked", "Refused while the emergency stop was on. Nothing was fetched.", lines
        if name == "replay":
            outcome = facts.get("outcome", "")
            return OUTCOME_TONE.get(outcome, "info"), OUTCOME_WORDS.get(outcome, outcome), f"Same answer today: {OUTCOME_WORDS.get(outcome, outcome)}.", lines
        if name == "rebalance":
            if out.get("suspended"):
                return "warn", "Waiting for a person", "The proposal is paused until a person decides.", []
            return OUTCOME_TONE.get(out.get("outcome", ""), "info"), OUTCOME_WORDS.get(out.get("outcome", ""), "Done"), "The proposal did not pause.", lines
        if name == "degraded":
            words = lambda key: OUTCOME_WORDS.get(facts.get(key, ""), "")  # noqa: E731
            return "info", "Four cases", "Four cases were tried with the record keeper down.", [
                ("bad", f"Strict mode: refused (status {facts.get('fail_closed_status')}); passed on: {facts.get('fail_closed_forwarded')}"),
                ("good", f"Degraded, local and low-risk: carried on (status {facts.get('degraded_local_status')}); passed on: {facts.get('degraded_local_forwarded')}"),
                ("bad", f"Degraded, outside provider: {words('degraded_remote_outcome')}; passed on: {facts.get('degraded_remote_forwarded')}"),
                ("bad", f"Degraded, identifying details: {words('degraded_c2_outcome')}; passed on: {facts.get('degraded_c2_forwarded')}")]
        return "info", "Done", "Done.", lines

    @app.post("/workflows", response_class=HTMLResponse)
    async def workflow_action(request: Request):
        values = await checked(request)
        name = values.get("workflow", "")
        role = values.get("role", "agent")
        if name not in WORKFLOWS or role not in ROLE_FIELDS:
            raise HTTPException(400, "Unknown workflow or role")
        if public_demo and name in {"mcp", "degraded"}:
            raise HTTPException(400, "This workflow requires the local CLI")
        try:
            max_calls = int(values.get("max_calls", "4"))
            if not 1 <= max_calls <= 100:
                raise ValueError("Call budget must be between 1 and 100")
            if name == "rebalance":
                worker = WealthAgent(db)
                try:
                    with Session(worker.engine) as session:
                        run = Run(max_calls=4)
                        steps = worker.execute_plan(session, "rebalance", run=run, arguments={"case": str(uuid4())})
                        held = steps[-1]
                        if not held.approval_required:
                            output = {"outcome": held.outcome.value, "suspended": False, "executed": held.data is not None}
                        else:
                            approval = session.exec(select(Approval).where(Approval.decision_id == held.evaluation.decision_id)).one()
                            output = {"outcome": held.outcome.value, "suspended": True, "run_id": run.id, "approval_id": approval.id}
                        session.commit()
                finally:
                    worker.engine.dispose()
            elif name == "client-review":
                output = json.loads(client_review(db, role=role, max_calls=max_calls).text())
            else:
                path = root / "drills" / f"{name}.db" if name in {"kill-switch", "mcp", "degraded"} else db
                output = json.loads(WORKFLOWS[name](path).text())
        except (ValueError, RuntimeError) as exc:
            return page("That did not run", card(stamp("bad", "Could not run"), para("The task could not be run."), back(("Run another task", "/workflows")), tone="bad"),
                        mechanics(pre(str(exc)), open_=True), status=400, active="/workflows")
        tone, verdict, headline, lines = summarize(name, role, output)
        next_links = [("Waiting for a person", "/approvals")] if name == "rebalance" and output.get("suspended") else []
        return page(WORKFLOW_WORDS[name][0], card(
            h("div", stamp(tone, verdict), h("h2", headline), cls="result"),
            h("ul", [h("li", ui.dot(t), h("span", line)) for t, line in lines], cls="steps") if lines else None,
            back(*next_links, ("The receipt", "/evidence"), ("Run another task", "/workflows")), tone=tone),
            mechanics(pre(_json(output))), active="/workflows")

    return app
