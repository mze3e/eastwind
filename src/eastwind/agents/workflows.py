"""Reproducible synthetic wealth agents using Kognita tool governance."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from sqlmodel import Session, select
from kognita import (ActorType, Classification, EvidenceWriter, Run, ToolRegistry, continue_run,
                     create_all, make_engine, run_governed, verify_chain)
from kognita.approvals import grant
from kognita.models import Agent, Approval, Policy
from kognita.usecases import load_register
from kognita.registry import set_kill_switch
from kognita.sources import Source, check_grounding, register_source, _load

from eastwind.agents.data import ACCOUNT, CLIENT, MANDATE, PRODUCTS, ROLE_FIELDS, SOURCE, SOURCES
from eastwind.llm import MockClient
from eastwind.pack import (AGENT_NAME, AGENT_OWNER, CLIENTS, INSTRUMENTS, PURPOSES,
                           EastwindPack, _access, client_envelope, seed_store)


class WealthPack(EastwindPack):
    """Only policy attributes are loaded before the retrieval decision."""

    def load_subjects(self, envelope, session=None):
        subjects = {}
        for kind, reference in envelope.all_subjects().items():
            if kind == "client":
                row = CLIENTS.get(str(reference))
                fields = ("id", "domicile", "accredited_investor", "booking_center")
            elif kind in {"instrument", "product"}:
                row = INSTRUMENTS.get(str(reference))
                fields = ("id", "kind", "origin")
            else:
                row, fields = None, ()
            if row is None:
                raise LookupError(f"{kind} {reference!r} is not in the synthetic register")
            subjects[kind] = {key: row[key] for key in fields}
        return subjects


PACK = WealthPack()
APPROVER = "risk.officer@eastwind.example"


def _suitable(product_id: str) -> bool:
    ranks = {"low": 1, "moderate": 2, "high": 3}
    return ranks[PRODUCTS[product_id]["risk"]] <= min(
        ranks[CLIENT["risk_profile"]], ranks[MANDATE["risk_ceiling"]])


@dataclass
class WorkflowResult:
    name: str
    facts: dict = field(default_factory=dict)
    steps: list = field(default_factory=list)
    database: str = ""

    def text(self) -> str:
        return json.dumps({"workflow": self.name, "steps": self.steps,
                           "facts": self.facts, "database": self.database}, indent=2, sort_keys=True)


class WealthAgent:
    """A host interprets model tool calls only after Kognita admits each call."""

    def __init__(self, path: Path, *, role: str = "agent"):
        if role not in ROLE_FIELDS:
            raise ValueError("unknown role")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = make_engine(path)
        create_all(self.engine)
        self.writer = EvidenceWriter(self.engine)
        self.role = role
        self.reads: list[str] = []
        self.proposals: list[dict] = []
        self.registry = ToolRegistry()
        for name in {call.name for wf in ("client-review", "suitability", "rebalance", "research")
                     for call in MockClient().plan(wf)}:
            self.registry.register(name, self._tool, classification=Classification.C2)
        self.registry.register("model_call", self._tool, classification=Classification.C1)
        with Session(self.engine) as session:
            seed_store(session)
            registered = session.exec(select(Agent).where(Agent.name == AGENT_NAME)).first()
            policy = session.exec(select(Policy).where(Policy.regime == "ROLE_ENTITLEMENT")).first()
            trade_policy = session.exec(select(Policy).where(Policy.regime == "TRADE_PROPOSAL")).first()
            required = {call.name for wf in ("client-review", "suitability", "rebalance", "research")
                        for call in MockClient().plan(wf)} | {"model_call"}
            entry = load_register(session).get(PURPOSES[0])
            if (registered is None or not required.issubset(registered.tool_allowlist or {})
                    or policy is None or policy.rule_type != "REQUIRES_FLAG"
                    or not policy.is_effective(datetime.now(timezone.utc))
                    or "source_permitted" not in policy.rule.get("flags", [])
                    or trade_policy is None or trade_policy.rule_type != "REQUIRES_HUMAN_APPROVAL"
                    or not trade_policy.is_effective(datetime.now(timezone.utc))
                    or "propose_trade" not in trade_policy.rule.get("tools", [])
                    or entry is None or SOURCE["id"] not in entry.approved_sources):
                raise ValueError("workflow store lacks required mandate or policies; choose a new store")
            source = Source(source_id=SOURCE["id"], kind="house view", version=SOURCE["version"],
                            owner=SOURCE["owner"], effective=SOURCE["effective"], expiry=SOURCE["expiry"])
            if _load(session).get(source.source_id, source.version) is None:
                register_source(session, source, evidence=self.writer, interaction_id="source:house-view")
            session.commit()

    def _tool(self, envelope, evaluation, session):
        name = envelope.tool
        args = envelope.arguments
        if name == "model_call":
            from kognita import EgressGuard, EgressPolicy, PatternRedactor

            workflow = args["workflow"]
            output = EgressGuard(policy=EgressPolicy(), redactor=PatternRedactor(), evidence=self.writer).send(
                workflow, lambda _: json.dumps(MockClient().complete([], workflow=workflow)),
                classification=Classification.C1, destination="local-mock", destination_is_local=True,
                session=session, correlation_id=evaluation.request_id,
                actor_id=envelope.agent_name or envelope.principal,
                actor_type=ActorType.AGENT if envelope.agent_name else ActorType.HUMAN, provider="mock", model="eastwind-mock", model_version="1")
            return output.response
        if name == "client_profile":
            fields = ROLE_FIELDS[self.role]
            if all(value == "denied" for value in fields.values()):
                return json.dumps({"denied": True})
            self.reads.append("client_profile")
            data = {key: CLIENT[key] if access == "visible" else "[MASKED]"
                    for key, access in fields.items() if access != "denied"}
            data["source_version"] = CLIENT["version"]
            return json.dumps(data, sort_keys=True)
        if name == "account_holdings":
            if self.role == "visitor":
                return json.dumps({"denied": True})
            self.reads.append("account_holdings")
            return json.dumps({"account_id": ACCOUNT["id"] if self.role == "relationship_manager" else "[MASKED]",
                               "source_version": ACCOUNT["version"], "holdings": ACCOUNT["holdings"]}, sort_keys=True)
        if name == "product_profile":
            self.reads.append("product_profile")
            return json.dumps(PRODUCTS[args.get("product_id", "INS-MMF")], sort_keys=True)
        if name == "check_suitability":
            product = PRODUCTS[args.get("product_id", "INS-MMF")]
            suitable = _suitable(product["id"])
            return json.dumps({"suitable": suitable, "risk_profile": CLIENT["risk_profile"],
                               "product_risk": product["risk"], "mandate": MANDATE["id"], "mandate_version": MANDATE["version"]})
        if name == "propose_trade":
            product_id = args.get("product_id", "INS-MMF")
            if not _suitable(product_id):
                return json.dumps({"denied": True, "reason": "product exceeds the mandate risk ceiling"})
            proposal = {"client_id": CLIENT["id"], "product_id": product_id, "amount": 5000,
                        "status": "proposal", "approver": APPROVER}
            self.proposals.append(proposal)
            return json.dumps(proposal, sort_keys=True)
        if name == "approved_sources":
            return json.dumps({"source_id": SOURCE["id"], "version": SOURCE["version"]})
        if name == "retrieve_house_view":
            source_id = args.get("source_id", SOURCE["id"])
            claim = SimpleNamespace(claim_id="research", source_system=source_id,
                                    source_record=args.get("version", SOURCE["version"]))
            check = check_grounding(session, claim, usecase_id=PURPOSES[0], evidence=self.writer,
                                    interaction_id=evaluation.request_id)
            if check.result.value != "pass":
                return json.dumps({"denied": True, "citation": check.check})
            self.reads.append("house_view")
            return json.dumps({"source_id": source_id, "version": SOURCE["version"], "text": SOURCE["text"]})
        if name in {"summarize_review", "summarize_research"}:
            return json.dumps({"summary": "Prepared from permitted synthetic records.", "tool": name})
        raise ValueError(f"unknown tool: {name}")

    def call(self, session: Session, name: str, *, run: Run | None = None, arguments: dict | None = None,
             interaction_id: str | None = None):
        args = {**(arguments or {}), "role": self.role}
        envelope = client_envelope(name, instrument_id=args.get("product_id", "INS-MMF"), arguments=args)
        if self.role == "relationship_manager":
            envelope = replace(envelope, agent_name=None)
        else:
            envelope = _access(session, envelope)
        return run_governed(session, envelope, registry=self.registry, evidence=self.writer,
                            pack=PACK, purposes=PURPOSES, run=run or Run(), interaction_id=interaction_id)

    def execute_plan(self, session: Session, name: str, *, run: Run | None = None,
                     arguments: dict | None = None, interaction_id: str | None = None) -> list:
        run = run or Run()
        model = self.call(session, "model_call", run=run,
                          arguments={**(arguments or {}), "workflow": name}, interaction_id=interaction_id)
        if model.outcome.value != "ALLOW" or model.data is None:
            return [model]
        response = json.loads(model.data)
        calls = response["choices"][0]["message"]["tool_calls"]
        results = []
        for call in calls:
            tool = call["function"]["name"]
            params = {**json.loads(call["function"]["arguments"]), **(arguments or {})}
            result = self.call(session, tool, run=run, arguments=params, interaction_id=interaction_id)
            results.append(result)
            if result.outcome.value != "ALLOW" or (_data(result) or {}).get("denied"):
                break
        return results


def _data(result):
    return json.loads(result.data) if result.data else None


def client_review(path: Path, *, role: str = "agent", max_calls: int = 4) -> WorkflowResult:
    agent = WealthAgent(path, role=role)
    result = WorkflowResult("client-review", database=str(path))
    from kognita.interaction import open_interaction

    with Session(agent.engine) as session:
        interaction = open_interaction(session, client_id=CLIENT["id"], use_case=PURPOSES[0],
                                       evidence=agent.writer)
        steps = agent.execute_plan(session, "client-review", run=Run(max_calls=max_calls),
                                   interaction_id=interaction.id)
        result.steps = [{"tool": step.evaluation.envelope.tool, "outcome": step.outcome.value,
                         "request_id": step.evaluation.request_id, "data": _data(step)} for step in steps]
        result.facts = {"role": role, "interaction_id": interaction.id,
                        "field_access": ROLE_FIELDS[role], "sources": SOURCES,
                        "retrieved": list(agent.reads),
                        "chain_length": verify_chain(session)}
        session.commit()
    agent.engine.dispose()
    return result


def suitability(path: Path, *, product_id: str = "INS-MMF") -> WorkflowResult:
    if product_id not in PRODUCTS:
        raise ValueError("unknown product")
    agent = WealthAgent(path)
    result = WorkflowResult("suitability", database=str(path))
    with Session(agent.engine) as session:
        steps = agent.execute_plan(session, "suitability", run=Run(max_calls=4),
                                   arguments={"product_id": product_id})
        result.steps = [{"tool": step.evaluation.envelope.tool, "outcome": step.outcome.value,
                         "data": _data(step)} for step in steps]
        result.facts = {"suitability": _data(steps[-1]), "retrieved": list(agent.reads),
                        "chain_length": verify_chain(session)}
        session.commit()
    agent.engine.dispose()
    return result


def research(path: Path, *, source_id: str = SOURCE["id"]) -> WorkflowResult:
    agent = WealthAgent(path)
    result = WorkflowResult("research", database=str(path))
    with Session(agent.engine) as session:
        steps = agent.execute_plan(session, "research", run=Run(max_calls=4), arguments={"source_id": source_id})
        result.steps = [{"tool": step.evaluation.envelope.tool, "outcome": step.outcome.value,
                         "data": _data(step)} for step in steps]
        result.facts = {"retrieved": list(agent.reads), "chain_length": verify_chain(session)}
        session.commit()
    agent.engine.dispose()
    return result


def rebalance(path: Path) -> WorkflowResult:
    agent = WealthAgent(path)
    result = WorkflowResult("rebalance", database=str(path))
    with Session(agent.engine) as session:
        hold_run = Run(max_calls=4)
        steps = agent.execute_plan(session, "rebalance", run=hold_run, arguments={"case": str(uuid4())})
        held = steps[-1]
        if held.outcome.value != "HUMAN_APPROVAL":
            raise RuntimeError(f"proposal did not suspend: {held.outcome.value}")
        approval = session.exec(select(Approval).where(Approval.decision_id == held.evaluation.decision_id)).one()
        checkpoint = bool(hold_run.continuation_hash)
        run_id = hold_run.id
        session.commit()
        denied = continue_run(session, run_id, {approval.id: False}, evidence=agent.writer,
                              registry=agent.registry, approver_name=APPROVER)
        session.commit()
        granted_run = Run()
        waiting = agent.call(session, "propose_trade", run=granted_run, arguments={"case": str(uuid4())})
        approved = session.exec(select(Approval).where(Approval.decision_id == waiting.evaluation.decision_id)).one()
        session.commit()
        released = continue_run(session, granted_run.id, {approved.id: True}, evidence=agent.writer,
                                registry=agent.registry, approver_name=APPROVER)
        session.commit()
        stopped_run = Run()
        waiting2 = agent.call(session, "propose_trade", run=stopped_run, arguments={"case": str(uuid4())})
        approved2 = session.exec(select(Approval).where(Approval.decision_id == waiting2.evaluation.decision_id)).one()
        session.commit()
        grant(session, approved2, approver_name=APPROVER, evidence=agent.writer,
              correlation_id=waiting2.evaluation.request_id)
        approved_before_stop = approved2.status.value == "APPROVED"
        session.commit()
        set_kill_switch(session, AGENT_NAME, True, evidence=agent.writer, actor_id=AGENT_OWNER,
                        reason="Simulated stop before release")
        session.commit()
        blocked = continue_run(session, stopped_run.id, {approved2.id: True}, evidence=agent.writer,
                               registry=agent.registry, approver_name=APPROVER)
        result.steps = [{"tool": item.evaluation.envelope.tool, "outcome": item.outcome.value}
                        for item in steps]
        set_kill_switch(session, AGENT_NAME, False, evidence=agent.writer, actor_id=AGENT_OWNER,
                        reason="Simulated stop completed")
        result.facts = {"held": held.approval_required, "checkpoint": checkpoint,
                        "denied_executed": denied.data is not None, "approved_executed": released.data is not None,
                        "approved_before_stop": approved_before_stop, "stopped_executed": blocked.data is not None,
                        "proposal_count": len(agent.proposals),
                        "released_proposal": agent.proposals[0] if agent.proposals else None,
                        "chain_length": verify_chain(session)}
        session.commit()
    agent.engine.dispose()
    return result


def budget(path: Path) -> WorkflowResult:
    agent = WealthAgent(path)
    result = WorkflowResult("budget", database=str(path))
    with Session(agent.engine) as session:
        steps = agent.execute_plan(session, "client-review", run=Run(max_calls=2))
        result.steps = [{"tool": step.evaluation.envelope.tool, "outcome": step.outcome.value}
                        for step in steps]
        result.facts = {"retrieved": list(agent.reads),
                        "budget_citations": [c.citation for c in steps[-1].evaluation.checks if c.check == "BUDGET"],
                        "chain_length": verify_chain(session)}
        session.commit()
    agent.engine.dispose()
    return result


def kill_switch(path: Path) -> WorkflowResult:
    agent = WealthAgent(path)
    result = WorkflowResult("kill-switch", database=str(path))
    with Session(agent.engine) as session:
        set_kill_switch(session, AGENT_NAME, True, evidence=agent.writer, actor_id=AGENT_OWNER,
                        reason="Simulated emergency stop")
        steps = agent.execute_plan(session, "client-review", run=Run(max_calls=4))
        set_kill_switch(session, AGENT_NAME, False, evidence=agent.writer, actor_id=AGENT_OWNER,
                        reason="Simulated emergency cleared")
        result.steps = [{"tool": step.evaluation.envelope.tool, "outcome": step.outcome.value}
                        for step in steps]
        result.facts = {"retrieved": list(agent.reads),
                        "checks": [c.check for c in steps[-1].evaluation.checks if c.result.value == "fail"],
                        "chain_length": verify_chain(session)}
        session.commit()
    agent.engine.dispose()
    return result


def egress(path: Path) -> WorkflowResult:
    from kognita import EgressDenied, EgressGuard, EgressPolicy, PatternRedactor

    agent = WealthAgent(path)
    sent = []
    result = WorkflowResult("egress", database=str(path))
    with Session(agent.engine) as session:
        steps = agent.execute_plan(session, "client-review", run=Run(max_calls=4))
        if not steps or steps[0].data is None:
            raise ValueError("client data was not admitted")
        try:
            EgressGuard(policy=EgressPolicy(), redactor=PatternRedactor(), evidence=agent.writer).send(
                steps[0].data, lambda text: sent.append(text),
                classification=Classification.C3, destination="remote-provider", destination_is_local=False,
                session=session, correlation_id="egress:" + str(uuid4()), actor_id=AGENT_NAME,
                actor_type=ActorType.AGENT)
        except EgressDenied:
            blocked = True
        else:
            blocked = False
        result.steps = [{"tool": step.evaluation.envelope.tool, "outcome": step.outcome.value}
                        for step in steps]
        result.facts = {"blocked": blocked, "classification": "C3", "provider_calls": len(sent),
                        "chain_length": verify_chain(session)}
        session.commit()
    agent.engine.dispose()
    return result


def mcp(path: Path) -> WorkflowResult:
    import subprocess
    from eastwind.local_servers import McpStandIn, free_port, serve_in_thread, wait_for_port
    from eastwind.pack import _headers
    from eastwind.showcase import _kognita_cmd, _outcome_of, _rpc, _rpc_text

    agent = WealthAgent(path)
    with Session(agent.engine) as session:
        planned = agent.call(session, "model_call", arguments={"workflow": "research"})
        if planned.outcome.value != "ALLOW" or planned.data is None:
            raise ValueError("research plan was not admitted")
        plan = json.loads(planned.data)["choices"][0]["message"]["tool_calls"]
        headers = _headers(session)
        session.commit()
    agent.engine.dispose()
    backend = McpStandIn()
    thread = serve_in_thread(backend)
    port = free_port()
    config = path.with_suffix(".mcp.json")
    config.write_text(json.dumps({"servers": [{"name": "eastwind", "url": backend.url}],
        "policy_pack": "eastwind.pack:EastwindPack", "evidence_database": str(path),
        "purposes": list(PURPOSES), "actor": {"principal": "rm.sg@eastwind.example",
        "purpose": PURPOSES[0], "agent_names": [AGENT_NAME], "actor_location": "SG"}}))
    command = _kognita_cmd("serve", "--mcp", "--root-config", str(config),
                           "--host", "127.0.0.1", "--port", str(port))
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_for_port(port)
        if "retrieve_house_view" not in [call["function"]["name"] for call in plan]:
            raise ValueError("research plan did not request house view")
        status, body = _rpc(port, "house_view", {"note": "Singapore money market eligibility"}, headers)
    finally:
        process.terminate()
        process.wait(timeout=10)
        backend.shutdown()
        backend.server_close()
        thread.join(timeout=5)
    with Session(agent.engine) as session:
        chain_length = verify_chain(session)
    agent.engine.dispose()
    return WorkflowResult("mcp", steps=[{"tool": "house_view", "status": status,
        "outcome": _outcome_of(body) or ("ALLOW" if status == 200 and "result" in body and "error" not in body else ""),
        "text": _rpc_text(body)}], facts={"backend_calls": list(backend.calls),
        "chain_length": chain_length}, database=str(path))


def degraded(path: Path) -> WorkflowResult:
    # Exercise Kognita gateway outage modes with a deterministic local transport.
    from kognita import FailureMode
    from kognita.models import RunRecord
    from eastwind.pack import _headers, register_usecases, seed_agent
    from eastwind.showcase import _Spy, _Toggle, _chat_body, _engine, _gateway

    engine = _engine(path)
    with Session(engine) as session:
        seed_agent(session)
        register_usecases(session)
        headers = _headers(session)
        run = Run()
        session.add(RunRecord(id=run.id))
        headers["run_id"] = run.id
        session.commit()
    reply = json.dumps(MockClient().complete([], model="eastwind-local")).encode()
    benign = _chat_body("House guidance on the SGD money market.")
    identifying = _chat_body(f"Email {CLIENT['email']} about account {ACCOUNT['id']}.")
    with Session(engine) as session:
        setup = _gateway(engine, EvidenceWriter(engine), _Spy(reply), upstream="http://127.0.0.1:9",
                         failure_mode=FailureMode.FAIL_CLOSED)
        setup_response = setup.handle("POST", "/v1/chat/completions", headers, identifying, session=session)
        if setup_response.status != 200:
            raise ValueError("could not bind the simulated gateway run")
        session.commit()
    with Session(engine) as session:
        closed_spy = _Spy(reply)
        closed = _gateway(engine, _Toggle(engine), closed_spy, upstream="http://127.0.0.1:9",
                          failure_mode=FailureMode.FAIL_CLOSED)
        closed_result = closed.handle("POST", "/v1/chat/completions", headers, benign, session=session)
        local_spy = _Spy(reply)
        local_writer = _Toggle(engine)
        local = _gateway(engine, local_writer, local_spy, upstream="http://127.0.0.1:9",
                         failure_mode=FailureMode.DEGRADED)
        local_result = local.handle("POST", "/v1/chat/completions", headers, benign, session=session)
        local_writer.down = False
        local.handle("GET", "/v1/chat/completions", {}, b"")
        remote_spy = _Spy(reply)
        remote = _gateway(engine, _Toggle(engine), remote_spy, upstream="https://api.openai.com",
                          failure_mode=FailureMode.DEGRADED)
        remote_result = remote.handle("POST", "/v1/chat/completions", headers, benign, session=session)
        c2_spy = _Spy(reply)
        c2 = _gateway(engine, _Toggle(engine), c2_spy, upstream="http://127.0.0.1:9",
                      failure_mode=FailureMode.DEGRADED)
        c2_result = c2.handle("POST", "/v1/chat/completions", headers, identifying, session=session)
        session.commit()
    with Session(engine) as session:
        chain_ok = verify_chain(session) >= 0
    engine.dispose()
    return WorkflowResult("degraded", facts={"fail_closed_status": closed_result.status,
        "fail_closed_forwarded": len(closed_spy.calls), "degraded_local_status": local_result.status,
        "degraded_local_forwarded": len(local_spy.calls), "degraded_remote_outcome": remote_result.evaluation.outcome.value,
        "degraded_remote_forwarded": len(remote_spy.calls), "degraded_c2_outcome": c2_result.evaluation.outcome.value,
        "degraded_c2_forwarded": len(c2_spy.calls), "degraded_chain": chain_ok}, database=str(path))


def replay(path: Path) -> WorkflowResult:
    from kognita import replay_decision
    from kognita.reconstruct import reconstruct

    from kognita.models import GovernanceDecision, InteractionLink
    from kognita.vocabulary import Outcome

    if not path.exists():
        client_review(path)
    engine = make_engine(path)
    with Session(engine) as session:
        decision = session.exec(select(GovernanceDecision).where(
            GovernanceDecision.tool == "client_profile",
            GovernanceDecision.outcome == Outcome.ALLOW
        ).order_by(GovernanceDecision.id.desc())).first()
        if decision is None:
            raise ValueError("no permitted client review is available to replay")
        request_id = decision.request_id
        evaluation = replay_decision(session, request_id)
        link = session.exec(select(InteractionLink).where(InteractionLink.correlation_id == request_id)).first()
        interaction_id = link.interaction_id if link else request_id
        report = reconstruct(session, interaction_id)
        result = WorkflowResult("replay", facts={"request_id": request_id, "interaction_id": interaction_id,
            "outcome": evaluation.outcome.value, "report": report,
            "chain_length": verify_chain(session)}, database=str(path))
    engine.dispose()
    return result


WORKFLOWS = {"client-review": client_review, "suitability": suitability, "rebalance": rebalance,
             "research": research, "egress": egress, "budget": budget, "kill-switch": kill_switch,
             "mcp": mcp, "degraded": degraded, "replay": replay}


def run_workflow(name: str, root: Path, **kwargs) -> WorkflowResult:
    if name not in WORKFLOWS:
        raise ValueError(f"unknown workflow: {name}")
    root.mkdir(parents=True, exist_ok=True)
    path = root / ("client-review.db" if name == "replay" else f"{name}.db")
    return WORKFLOWS[name](path, **kwargs)
