"""``eastwind showcase`` scenarios for the kognita 0.4 surface.

Each function is one scenario on the Eastwind Private pack. They call the
real kognita APIs against a local SQLite store: no API key, no network.
Optional extras (Docling, OpenTelemetry, the framework adapters) are used
when installed and reported as skipped when they are not.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from kognita import EvidenceWriter, Run, ToolRegistry, create_all, make_engine, run_governed
from kognita.models import Policy
from kognita.vocabulary import Classification

from eastwind.pack import (
    AGENT_NAME,
    AGENT_OWNER,
    PURPOSES,
    USECASE_OWNERS,
    EastwindPack,
    client_envelope,
    register_usecases,
    seed_agent,
    seed_store,
)

PACK = EastwindPack()
USECASE = PURPOSES[0]
# Interaction, review and outcome reads only count events recorded up to
# their instant, so scenarios run at the wall clock. Read once per process.
NOW = datetime.now(timezone.utc)
RM = "rm.sg@eastwind.example"


class _Story:
    def __init__(self, name: str, title: str) -> None:
        from eastwind.showcase import ShowcaseResult

        self.result = ShowcaseResult(name)
        self.result.lines.append(f"Scenario  {name} — {title}")
        self.result.lines.append(f"  eastwind showcase {name}")
        self.result.lines.append("")

    def say(self, text: str = "") -> None:
        self.result.lines.append(text if not text else f"  {text}")

    def fact(self, key: str, value: Any) -> None:
        self.result.facts[key] = value


def _engine(path: Path) -> Any:
    engine = make_engine(path)
    create_all(engine)
    return engine


def _seeded(path: Path) -> tuple[Any, EvidenceWriter]:
    engine = _engine(path)
    with Session(engine) as session:
        seed_store(session)
        session.commit()
    return engine, EvidenceWriter(engine)


def _registry(ran: list[str] | None = None) -> ToolRegistry:
    calls = ran if ran is not None else []

    def _tool(envelope: Any, evaluation: Any, session: Session) -> str:
        calls.append(envelope.tool)
        return f"ran {envelope.tool}"

    registry = ToolRegistry()
    registry.register("check_eligibility", _tool, classification=Classification.C1)
    return registry


def _governed(session: Session, writer: EvidenceWriter, registry: ToolRegistry, **kw: Any) -> Any:
    return run_governed(
        session,
        client_envelope("check_eligibility", **kw),
        registry=registry,
        evidence=writer,
        pack=PACK,
        purposes=PURPOSES,
        run=Run(),
    )


def _failing(evaluation: Any) -> list[Any]:
    return [check for check in evaluation.checks if check.result.value != "pass"]


def _cite_first(evaluation: Any, check_name: str | None = None) -> str:
    for check in _failing(evaluation):
        if check_name is None or check.check == check_name:
            return f"{check.check}: {check.citation}"
    return "(no failing check)"


# --------------------------------------------------------------------------
# register
# --------------------------------------------------------------------------


def scenario_register(path: Path) -> Any:
    """An empty register denies; a registered use case cites its owner."""
    from kognita.usecases import list_usecases, suspend

    story = _Story("register", "use-case register")
    ran: list[str] = []
    registry = _registry(ran)

    empty_engine = _engine(path.with_name(path.stem + "-empty.db"))
    with Session(empty_engine) as session:
        seed_agent(session)
        session.commit()
    with Session(empty_engine) as session:
        empty = _governed(session, EvidenceWriter(empty_engine), registry)
        session.commit()
    story.fact("empty_outcome", empty.outcome.value)
    story.fact("empty_citation", _cite_first(empty.evaluation, "USE_CASE_REGISTERED"))
    story.fact("empty_ran", bool(ran))
    story.say(f"Empty register     {empty.outcome.value}   tool ran {bool(ran)}")
    story.say(f"cite    {story.result.facts['empty_citation']}")
    story.say("")

    engine, writer = _seeded(path)
    with Session(engine) as session:
        entries = list_usecases(session)
        for entry in entries:
            story.say(
                f"registered  {entry.usecase_id}  v{entry.version}  tier {entry.proposed_tier}  "
                f"{entry.status}  owner {entry.owner}"
            )
        story.fact("registered", [entry.usecase_id for entry in entries])
        story.fact("models", sorted(card for entry in entries for card in entry.approved_models))
        for card in story.result.facts["models"]:
            story.say(f"model card  {card}")
        allowed = _governed(session, writer, registry)
        session.commit()
    passing = next(c for c in allowed.evaluation.checks if c.check == "USE_CASE")
    story.fact("allow_outcome", allowed.outcome.value)
    story.fact("allow_citation", passing.citation)
    story.say(f"Registered, live   {allowed.outcome.value}   tool ran {bool(ran)}")
    story.say(f"cite    {passing.citation}")
    story.say("")

    with Session(engine) as session:
        suspend(session, USECASE, evidence=writer, actor_id=USECASE_OWNERS["control_function"])
        session.commit()
    with Session(engine) as session:
        suspended = _governed(session, writer, registry)
        session.commit()
    story.fact("suspended_outcome", suspended.outcome.value)
    story.fact("suspended_citation", _cite_first(suspended.evaluation))
    story.say(f"Suspended          {suspended.outcome.value}")
    story.say(f"cite    {story.result.facts['suspended_citation']}")
    story.say("The register replaces the free-text purpose list on every execution path.")
    story.say(f"Store   {path}")
    return story.result


# --------------------------------------------------------------------------
# contact: interaction record and do-not-contact
# --------------------------------------------------------------------------

CONTENT_LEVELS = [
    "general information",
    "house view",
    "contextualised insight",
    "investment discussion",
    "product recommendation",
    "transaction",
]
CHANNEL = "Secure Message"


def _content_policy(session: Session) -> None:
    session.add(
        Policy(
            regime="COMMUNICATION",
            rule_type="CONTENT_POLICY",
            rule={
                "levels": CONTENT_LEVELS,
                "lanes": ["client"],
                "prohibited_claims": ["guaranteed"],
            },
            citation="Eastwind content policy s2: no guaranteed returns (workshop fiction)",
            effective_from=NOW - timedelta(days=30),
        )
    )
    session.flush()


def _boundary(session: Session, writer: EvidenceWriter) -> None:
    from kognita.review import define_human_boundary

    define_human_boundary(
        session,
        USECASE,
        intervention="before a message reaches the client",
        who=AGENT_OWNER,
        must_review="the eligibility answer and its citations",
        evidence_seen="the rendered message and the policy checks",
        on_reject="the message is not sent",
        minimum_review_seconds=0,
        evidence=writer,
        now=NOW,
    )


def _send(session: Session, writer: EvidenceWriter, interaction_id: str, **kw: Any) -> dict[str, Any]:
    from kognita.communication import send_client_communication

    values: dict[str, Any] = {
        "channel": CHANNEL,
        "recipient_ref": "CL-1001-secure-inbox",
        "content": "The SGD money market is a non-complex cash product.",
        "level": "general information",
        "provenance": "human",
        "actor_id": RM,
        "now": NOW,
    }
    values.update(kw)
    return send_client_communication(session, interaction_id, evidence=writer, **values)


def _allow_final(session: Session, writer: EvidenceWriter, interaction_id: str) -> None:
    from kognita.review import record_final_decision

    record_final_decision(
        session,
        interaction_id,
        outcome="allow",
        evidence=writer,
        actor_id=RM,
        citation="Final decision: the eligibility answer was allowed",
        now=NOW,
    )


def _channel(session: Session, writer: EvidenceWriter) -> None:
    from kognita.communication import register_channel

    register_channel(
        session,
        CHANNEL,
        evidence=writer,
        human=AGENT_OWNER,
        citation="Approved channel: archived and supervised (workshop fiction)",
        archiving=True,
        supervision=True,
        now=NOW,
    )


def scenario_contact(path: Path) -> Any:
    """One interaction record per client; do-not-contact holds until a cited reversal."""
    from kognita.interaction import open_interaction
    from kognita.origination import OriginationError, originate, reverse_do_not_contact
    from kognita.reconstruct import reconstruct

    story = _Story("contact", "interaction record and do-not-contact")
    engine, writer = _seeded(path)
    with Session(engine) as session:
        _content_policy(session)
        _channel(session, writer)
        _boundary(session, writer)
        first = open_interaction(
            session,
            client_id="CL-1001",
            use_case=USECASE,
            approval_gate="human_approval",
            evidence=writer,
            interaction_id="int-mei-tan-1",
            now=NOW,
        )
        story.say(f"interaction  {first.id}  client CL-1001  use case {USECASE}")
        barred = originate(
            session,
            first.id,
            evidence=writer,
            trigger="schedule",
            candidate_set_size=12,
            criteria=["vulnerability"],
            do_not_contact=["vulnerability"],
            now=NOW,
        )
        story.fact("origination_outcome", barred["outcome"])
        story.say(f"origination  {barred['outcome']}  reasons vulnerability")

        refusal = ""
        try:
            originate(
                session,
                first.id,
                evidence=writer,
                trigger="RM request",
                candidate_set_size=12,
                criteria=["house-view change"],
                reasons=[
                    {
                        "fact": "eligibility",
                        "detail": "Mei Tan is an accredited investor domiciled in SG.",
                        "citation": "House View, money market",
                    }
                ],
                now=NOW,
            )
        except OriginationError as exc:
            refusal = str(exc)
        story.fact("reoriginate_refused", bool(refusal))
        story.say(f"RM retries   refused  {refusal}")

        second = open_interaction(
            session,
            client_id="CL-1001",
            use_case=USECASE,
            approval_gate="human_approval",
            evidence=writer,
            interaction_id="int-mei-tan-2",
            now=NOW,
        )
        _allow_final(session, writer, second.id)
        blocked = _send(session, writer, second.id)
        story.fact("later_contact_outcome", blocked["outcome"])
        story.fact("later_contact_sent", blocked["sent"])
        story.fact("later_contact_citation", blocked["citation"])
        story.say(f"later message, new interaction  {blocked['outcome']}  sent {blocked['sent']}")
        story.say(f"cite    {blocked['citation']}")

        reversal = reverse_do_not_contact(
            session,
            first.id,
            evidence=writer,
            human=AGENT_OWNER,
            citation="Conduct review 2026-10-06: vulnerability flag cleared (workshop fiction)",
            now=NOW,
        )
        story.say(f"reversal     by {AGENT_OWNER}  cites the conduct review")
        story.fact("reversal_human", reversal.get("human", AGENT_OWNER))
        sent = _send(session, writer, second.id)
        story.fact("after_reversal_outcome", sent["outcome"])
        story.fact("after_reversal_sent", sent["sent"])
        story.say(f"after reversal  {sent['outcome']}  sent {sent['sent']}")
        session.commit()
        report = reconstruct(session, first.id)
    questions = len(report.get("questions", []))
    story.fact("reconstruct_questions", questions)
    story.say(f"reconstruct {first.id}  answers {questions} questions from the record")
    story.say(f"Store   {path}")
    return story.result


def _model_answer(session: Session, writer: EvidenceWriter, interaction_id: str) -> str:
    """One offline model answer on the interaction. Returns its response hash."""
    from kognita import ActorType, EgressGuard, EgressPolicy
    from kognita.models import EvidenceEvent
    from kognita.vocabulary import EventType

    EgressGuard(policy=EgressPolicy(), evidence=writer).send(
        "Is the SGD money market a non-complex product?",
        lambda _text: "Yes. House guidance treats it as a non-complex cash product.",
        classification=Classification.C1,
        destination="api.openai.com",
        destination_is_local=False,
        session=session,
        correlation_id=interaction_id,
        actor_id=RM,
        actor_type=ActorType.HUMAN,
        provider="openai",
        model="gpt-4o-mini",
        model_version="gpt-4o-mini",
        use_case=USECASE,
    )
    event = session.exec(
        select(EvidenceEvent)
        .where(EvidenceEvent.event_type == EventType.MODEL_CALL)
        .where(EvidenceEvent.correlation_id == interaction_id)
        .order_by(EvidenceEvent.sequence.desc())
    ).first()
    return str(event.payload["response_hash"]) if event is not None else ""


# --------------------------------------------------------------------------
# communicate: governed client communication and intervention
# --------------------------------------------------------------------------


def scenario_communicate(path: Path) -> Any:
    """Approved channels, content rules, and a human pause, override and recovery."""
    from kognita.communication import CommunicationError, register_channel
    from kognita.interaction import attach, open_interaction
    from kognita.intervention import override_run, pause_run, recover_run
    from kognita.outcomes import record_outcome

    story = _Story("communicate", "governed client communication and intervention")
    engine, writer = _seeded(path)
    with Session(engine) as session:
        _content_policy(session)
        _channel(session, writer)
        personal = ""
        try:
            register_channel(
                session,
                "personal whatsapp",
                evidence=writer,
                human=AGENT_OWNER,
                citation="RM asked to use WhatsApp",
                archiving=False,
                supervision=False,
                now=NOW,
            )
        except CommunicationError as exc:
            personal = str(exc)
        story.fact("personal_refused", bool(personal))
        story.say(f"register personal whatsapp  refused  {personal}")

        interaction = open_interaction(
            session,
            client_id="CL-1001",
            use_case=USECASE,
            approval_gate="human_approval",
            evidence=writer,
            interaction_id="int-communicate",
            now=NOW,
        )
        undecided = _send(session, writer, interaction.id)
        story.fact("undecided_outcome", undecided["outcome"])
        story.say(f"no final decision   {undecided['outcome']}  cite {undecided['citation']}")
        _allow_final(session, writer, interaction.id)
        unregistered = _send(session, writer, interaction.id, channel="telegram")
        story.fact("unregistered_outcome", unregistered["outcome"])
        story.say(f"via telegram        {unregistered['outcome']}  cite {unregistered['citation']}")
        claim = _send(
            session,
            writer,
            interaction.id,
            content="Returns on the money market are guaranteed.",
        )
        story.fact("claim_outcome", claim["outcome"])
        story.say(f"'guaranteed' claim  {claim['outcome']}  cite {claim['citation']}")
        sent = _send(session, writer, interaction.id)
        story.fact("sent_outcome", sent["outcome"])
        story.fact("sent_level", sent.get("communication_level"))
        story.say(
            f"{CHANNEL}, general information  {sent['outcome']}  "
            f"level {sent.get('communication_level')}  provenance {sent.get('provenance')}"
        )
        story.say("")

        run = Run()
        result = run_governed(
            session,
            client_envelope("check_eligibility"),
            registry=_registry(),
            evidence=writer,
            pack=PACK,
            purposes=PURPOSES,
            run=run,
        )
        attach(
            session,
            interaction.id,
            evidence=writer,
            correlation_id=result.evaluation.request_id,
            run_id=run.id,
            now=NOW,
        )
        paused = pause_run(
            session, run.id, evidence=writer, human=AGENT_OWNER,
            citation="Conduct desk pause: client called in (workshop fiction)", now=NOW,
        )
        story.say(f"pause    run {run.id[:8]}  by {AGENT_OWNER}")
        overridden = override_run(
            session, run.id, evidence=writer, human=AGENT_OWNER,
            citation="Conduct desk override: answer held for review", outcome="deny", now=NOW,
        )
        story.say("override deny  cites the conduct desk")
        recovered = recover_run(
            session, run.id, evidence=writer, human=AGENT_OWNER,
            citation="Conduct desk recovery: review complete", now=NOW,
        )
        story.say("recover  the run continues under the same evidence chain")
        story.fact("interventions", [p.get("action", "") for p in (paused, overridden, recovered)])

        answer_hash = _model_answer(session, writer, interaction.id)
        complaint = record_outcome(
            session,
            interaction.id,
            kind="client complaint",
            summary="Client said the message arrived after the market closed.",
            evidence=writer,
            actor_id=AGENT_OWNER,
            citation="Complaints handling: every complaint is recorded (workshop fiction)",
            output_hash=answer_hash,
        )
        story.fact("complaint_kind", complaint.get("kind"))
        story.fact("complaint_model_version", complaint.get("model_version"))
        story.say(
            f"complaint  {complaint.get('kind')}  model {complaint.get('model_version')}  "
            f"approver {complaint.get('approver')}"
        )
        story.say(f"cite    {complaint.get('rule')}")
        session.commit()
    story.say(f"Store   {path}")
    return story.result


# --------------------------------------------------------------------------
# outcomes: outcomes, near misses, review queue, metrics
# --------------------------------------------------------------------------


def scenario_outcomes(path: Path) -> Any:
    """Outcomes and near misses on the record, a review queue, and the metrics."""
    from kognita.interaction import open_interaction
    from kognita.outcomes import (
        near_miss_register,
        outcome_metrics,
        record_near_miss,
        record_outcome,
    )
    from kognita.review import (
        coverage_report,
        enqueue_for_review,
        record_review_finding,
    )

    story = _Story("outcomes", "outcomes, near misses, review queue and metrics")
    engine, writer = _seeded(path)
    with Session(engine) as session:
        interaction = open_interaction(
            session,
            client_id="CL-1001",
            use_case=USECASE,
            approval_gate="human_approval",
            evidence=writer,
            interaction_id="int-outcomes",
        )
        answer = _model_answer(session, writer, interaction.id)
        from kognita.review import record_final_decision

        record_final_decision(
            session,
            interaction.id,
            outcome="allow",
            evidence=writer,
            actor_id=RM,
            citation="Final decision: the eligibility answer was allowed",
        )
        correction = record_outcome(
            session,
            interaction.id,
            kind="correction",
            summary="RM corrected the booking centre in the answer.",
            evidence=writer,
            actor_id=RM,
            citation="Outcomes: corrections are recorded (workshop fiction)",
            output_hash=answer,
        )
        story.say(f"outcome    {correction['kind']}  model {correction['model_version']}  approver {correction['approver']}")
        bad_kind = ""
        try:
            record_outcome(
                session, interaction.id, kind="looked fine", summary="x",
                evidence=writer, actor_id=RM, citation="x", output_hash=answer,
            )
        except Exception as exc:  # noqa: BLE001 - shown on screen
            bad_kind = str(exc)
        story.fact("bad_kind_refused", bool(bad_kind))
        story.say(f"free-text kind refused  {bad_kind}")

        near = record_near_miss(
            session,
            kind="verifier block",
            summary="Verifier blocked a draft that named the C3 steering note.",
            evidence=writer,
            actor_id=AGENT_OWNER,
            citation="Near-miss register: a verifier block is recorded (workshop fiction)",
            interaction_id=interaction.id,
            usecase_id=USECASE,
            agent=AGENT_NAME,
            model_version="gpt-4o-mini",
        )
        story.say(f"near miss  {near['kind']}  use case {near.get('usecase_id', USECASE)}")

        # A denied call is a derived near miss: the register counts it.
        _governed(session, writer, _registry(), client_id="CL-2002", instrument_id="INS-HK-NOTE")

        queued = enqueue_for_review(
            session,
            interaction.id,
            evidence=writer,
            reasons=["product complexity", "classifier confidence below 0.7"],
            risk="high",
            citation="Risk-based review: a high-risk response is queued (workshop fiction)",
            actor_id=AGENT_OWNER,
            response_hash=answer,
        )
        story.say(f"queued     for review  risk {queued.risk}  timing {queued.timing}")
        finding = record_review_finding(
            session,
            interaction.id,
            reviewer=USECASE_OWNERS["control_function"],
            outcome="confirmed problem",
            finding="Answer omitted the booking-centre caveat.",
            evidence=writer,
        )
        story.fact("finding", finding.get("outcome"))
        story.say(f"finding    {finding.get('outcome')}  by {USECASE_OWNERS['control_function']}")
        session.commit()

        register = near_miss_register(session)
        story.fact("near_misses", {row.kind: row.count for row in register})
        for row in register:
            story.say(f"near-miss register  {row.kind:<24} {row.count}")
        metrics = outcome_metrics(session, usecase_id=USECASE)
        shown: dict[str, Any] = {}
        for row in metrics:
            for name, value in row.metrics.items():
                shown[name] = value.value if value.measured else "not measured"
                story.say(f"metric     {name:<17} {shown[name]!s:<14} {value.citation}")
        story.fact("metrics", shown)
        coverage = coverage_report(session)
        lane = coverage["by_use_case"][0] if coverage["by_use_case"] else {}
        story.fact("coverage_queued", lane.get("share_queued"))
        story.fact("coverage_reviewed", lane.get("share_reviewed"))
        story.say(
            f"coverage   queued {lane.get('share_queued')}  reviewed {lane.get('share_reviewed')}  "
            f"cite {coverage.get('citation')}"
        )
    story.say(f"Store   {path}")
    return story.result


# --------------------------------------------------------------------------
# breaker: circuit breaker, provider revocation, kill-switch drills
# --------------------------------------------------------------------------


def scenario_breaker(path: Path) -> Any:
    """Drills on a material use case, a tripped breaker, revocation and reinstatement."""
    from kognita.breaker import (
        affected_clients,
        evaluate_breakers,
        reset_breaker,
        run_kill_switch_drill,
        set_breaker_threshold,
    )
    from kognita.outcomes import record_near_miss
    from kognita.registry import set_kill_switch
    from kognita.revocation import reinstate, revoke

    story = _Story("breaker", "circuit breaker, revocation and kill-switch drills")
    engine = _engine(path)
    with Session(engine) as session:
        seed_agent(session)
        register_usecases(session, residual_materiality="high")
        seed_store(session)
        session.commit()
    writer = EvidenceWriter(engine)
    registry = _registry()
    owner = AGENT_OWNER

    def decide_once(label: str, check: str | None = None) -> Any:
        with Session(engine) as session:
            result = _governed(session, writer, registry)
            session.commit()
        cite = _cite_first(result.evaluation, check) if result.outcome.value != "ALLOW" else ""
        story.say(f"{label:<30} {result.outcome.value}")
        if cite:
            story.say(f"cite    {cite}")
        return result, cite

    undrilled, cite = decide_once("material, no drill scheduled", "KILL_SWITCH_DRILL")
    story.fact("undrilled_outcome", undrilled.outcome.value)
    story.fact("undrilled_citation", cite)
    with Session(engine) as session:
        drill = run_kill_switch_drill(
            session,
            USECASE,
            AGENT_NAME,
            evidence=writer,
            actor_id=owner,
            citation="Quarterly kill-switch drill (workshop fiction)",
            fallback="The RM used the house eligibility manual",
        )
        session.commit()
    story.fact("drill_latency", drill["latency_seconds"])
    story.say(
        f"drill run  by {drill['activated_by']}  denied in {drill['latency_seconds']:.3f}s  "
        f"fallback: {drill['fallback']}"
    )
    drilled, _ = decide_once("after the drill")
    story.fact("drilled_outcome", drilled.outcome.value)
    story.say("")

    with Session(engine) as session:
        set_breaker_threshold(
            session,
            "usecase",
            USECASE,
            threshold=2,
            window_seconds=3600,
            evidence=writer,
            actor_id=owner,
            citation="Breaker: two confirmed problems in an hour (workshop fiction)",
        )
        for summary in ("Draft named the wrong booking centre.", "Draft cited a retired house view."):
            record_near_miss(
                session,
                kind="unsafe draft",
                summary=summary,
                evidence=writer,
                actor_id=owner,
                citation="Near-miss register: an unsafe draft is recorded",
                usecase_id=USECASE,
                agent=AGENT_NAME,
            )
        evaluate_breakers(session, evidence=writer)
        session.commit()
    story.say(f"threshold 2 flags in 1h on {USECASE}; two unsafe drafts recorded")
    broken, cite = decide_once("next decision", "CIRCUIT_BREAKER")
    story.fact("breaker_outcome", broken.outcome.value)
    story.fact("breaker_citation", cite)
    with Session(engine) as session:
        reset_breaker(
            session, "usecase", USECASE, evidence=writer, actor_id=owner,
            citation="Breaker reset: both drafts reviewed and fixed (workshop fiction)",
        )
        session.commit()
    reset, _ = decide_once("after the owner's reset")
    story.say("Reset closes the breaker; the two flags stay on the evidence chain.")
    story.fact("reset_outcome", reset.outcome.value)
    story.say("")

    import json

    from kognita import FailureMode

    from eastwind.showcase import _chat_body, _gateway, _Spy

    reply = json.dumps(
        {"model": "eastwind-local", "choices": [{"message": {"content": "the market is open"}}]}
    ).encode()
    spy = _Spy(reply)
    gateway = _gateway(
        engine, writer, spy, upstream="http://127.0.0.1:9", failure_mode=FailureMode.FAIL_CLOSED
    )

    def through_gateway(label: str) -> Any:
        with Session(engine) as session:
            response = gateway.handle(
                "POST",
                "/v1/chat/completions",
                {"agent_name": AGENT_NAME},
                _chat_body("House guidance on the SGD money market."),
                session=session,
            )
            session.commit()
        evaluation = response.evaluation
        story.say(f"{label:<30} HTTP {response.status}  {evaluation.outcome.value}  forwarded {len(spy.calls)}")
        if evaluation.outcome.value != "ALLOW":
            story.say(f"cite    {_cite_first(evaluation, 'REVOCATION')}")
        return response

    with Session(engine) as session:
        revoked = revoke(
            session, "provider", "127.0.0.1", evidence=writer, actor_id=owner,
            citation="Vendor incident: provider suspended pending review (workshop fiction)",
        )
        session.commit()
        revocation_id = revoked.id
    story.say("revoke --provider 127.0.0.1 (the gateway stand-in)")
    blocked = through_gateway("gateway call, provider revoked")
    story.fact("provider_revoked_status", blocked.status)
    story.fact("provider_revoked_forwarded", len(spy.calls))
    with Session(engine) as session:
        reinstate(
            session, revocation_id or 0, evidence=writer, actor_id=owner,
            citation="Vendor review closed: provider reinstated (workshop fiction)",
        )
        session.commit()
    story.say("reinstate  every accountable owner of every use case naming the provider")
    restored = through_gateway("gateway call, reinstated")
    story.fact("reinstated_status", restored.status)
    story.fact("reinstated_forwarded", len(spy.calls))

    with Session(engine) as session:
        agent_revocation = revoke(
            session, "agent", AGENT_NAME, evidence=writer, actor_id=owner,
            citation="Agent revoked: unexplained tool calls (workshop fiction)",
        )
        session.commit()
        agent_revocation_id = agent_revocation.id
        refused = ""
        try:
            set_kill_switch(session, AGENT_NAME, False, evidence=writer, actor_id=owner)
        except Exception as exc:  # noqa: BLE001 - shown on screen
            refused = str(exc)
        session.rollback()
    story.fact("kill_switch_release_refused", bool(refused))
    story.say("revoke agent  kill switch engaged; releasing it is refused")
    story.say(f"cite    {refused}")
    stopped, cite = decide_once("agent revoked")
    story.fact("agent_revoked_outcome", stopped.outcome.value)
    with Session(engine) as session:
        reinstate(
            session, agent_revocation_id or 0, evidence=writer, actor_id=owner,
            citation="Agent review closed (workshop fiction)",
        )
        session.commit()
    story.say("")

    with Session(engine) as session:
        from kognita.interaction import open_interaction

        open_interaction(
            session, client_id="CL-1001", use_case=USECASE, evidence=writer,
            interaction_id="int-breaker",
        )
        _model_answer(session, writer, "int-breaker")
        session.commit()
    with Session(engine) as session:
        window = affected_clients(
            session,
            model="gpt-4o-mini",
            start=NOW - timedelta(days=1),
            end=datetime.now(timezone.utc) + timedelta(minutes=1),
        )
    clients = window.get("clients", [])
    story.fact("affected_clients", [row.get("client_id") for row in clients])

    story.say(
        f"evidence affected --model gpt-4o-mini  clients "
        f"{', '.join(str(row.get('client_id')) for row in clients) or 'none'}"
    )
    story.say(f"Store   {path}")
    return story.result


# --------------------------------------------------------------------------
# kognita CLI, in process
# --------------------------------------------------------------------------


def _cli(*args: str) -> tuple[int, str]:
    """Run ``kognita <args>`` in this process and capture what it prints."""
    import contextlib
    import io

    from kognita.cli import main

    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            code = main(list(args))
        except SystemExit as exc:  # argparse and some commands exit
            code = exc.code if isinstance(exc.code, int) else 1
    return int(code or 0), out.getvalue().strip()


# --------------------------------------------------------------------------
# policy: the policy language
# --------------------------------------------------------------------------

DOMICILE_RULE = """\
id: eastwind-domicile
regime: MAS_SG
rule_type: ATTRIBUTE_ALLOWLIST
citation: "MAS Guidelines on Fair Dealing (FAA-G11); Eastwind house adoption s3 (workshop fiction)."
effective_from: "2024-01-01T00:00:00+00:00"
rule:
  allow:
    client_domicile:
      - SG
      - HK
      - AE
  on_violation: fail
  description: "Singapore booking may assess eligibility for permitted domiciles."
"""

DOMICILE_SCENARIOS = """\
rule: eastwind-domicile
scenarios:
  - name: "a client domiciled in Germany is refused"
    given:
      principal: "rm.sg@eastwind.example"
      purpose: ELIGIBILITY_CHECK
      tool: check_eligibility
      actor_location: SG
      attributes:
        client_domicile: DE
    when:
      tool: check_eligibility
    then:
      decision: DENY
      cites: eastwind-domicile
  - name: "a client domiciled in Singapore is allowed"
    given:
      principal: "rm.sg@eastwind.example"
      purpose: ELIGIBILITY_CHECK
      tool: check_eligibility
      actor_location: SG
      attributes:
        client_domicile: SG
    when:
      tool: check_eligibility
    then:
      decision: ALLOW
"""

UNCITED_RULE = """\
id: eastwind-research
regime: MAS_SG
rule_type: ATTRIBUTE_ALLOWLIST
effective_from: "2024-01-01T00:00:00+00:00"
rule:
  allow:
    research_distribution:
      - permitted
  on_violation: fail
  description: "[NEEDS CLARIFICATION: which research may an RM forward?]"
"""


def scenario_policy(path: Path) -> Any:
    """YAML policy files: strict validation, colocated scenarios, diff, explain, load."""
    import json

    story = _Story("policy", "policy language")
    root = path.with_suffix("")
    current = root / "current"
    proposed = root / "proposed"
    draft = root / "draft"
    for folder in (current, proposed, draft):
        folder.mkdir(parents=True, exist_ok=True)
    (current / "eastwind-domicile.yaml").write_text(DOMICILE_RULE)
    (current / "eastwind-domicile.scenarios.yaml").write_text(DOMICILE_SCENARIOS)
    (proposed / "eastwind-domicile.yaml").write_text(
        DOMICILE_RULE.replace("      - AE\n", "      - AE\n      - GB\n")
    )
    (proposed / "eastwind-domicile.scenarios.yaml").write_text(DOMICILE_SCENARIOS)
    (draft / "eastwind-research.yaml").write_text(UNCITED_RULE)

    code, text = _cli("policy", "validate", "--strict", str(current))
    story.fact("strict_ok", code == 0)
    story.say(f"$ kognita policy validate --strict current/   exit {code}")
    story.say(f"  {text.splitlines()[-1] if text else ''}")

    code, text = _cli("policy", "validate", "--strict", str(draft))
    story.fact("draft_refused", code != 0)
    story.say(f"$ kognita policy validate --strict draft/     exit {code}")
    for line in text.splitlines()[:4]:
        story.say(f"  {line}")

    code, text = _cli("policy", "test", str(current))
    story.fact("scenarios_ok", code == 0)
    story.say(f"$ kognita policy test current/                exit {code}")
    for line in text.splitlines()[:4]:
        story.say(f"  {line}")

    code, text = _cli("policy", "diff", str(current), str(proposed))
    story.fact("diff_modified", "## MODIFIED" in text)
    story.say(f"$ kognita policy diff current/ proposed/      exit {code}")
    for line in text.splitlines():
        if line.startswith("##") or "GB" in line or "- id:" in line:
            story.say(f"  {line}")

    envelope = {
        "principal": "rm.sg@eastwind.example",
        "purpose": "ELIGIBILITY_CHECK",
        "tool": "check_eligibility",
        "actor_location": "SG",
        "attributes": {"client_domicile": "DE"},
        "purposes": ["ELIGIBILITY_CHECK"],
    }
    code, text = _cli(
        "policy", "explain", "--envelope", json.dumps(envelope), "--policy", str(current)
    )
    story.fact("explain_cites", "FAA-G11" in text)
    story.say(f"$ kognita policy explain --envelope '<DE client>'   exit {code}")
    for line in text.splitlines():
        if line.startswith("other"):
            break  # the engine's own checks follow; the rule's block is the point
        if line.strip().startswith(("outcome", "engaged", "citation", "check", "result")):
            story.say(f"  {line.strip()}")

    db = str(path)
    engine = _engine(path)
    engine.dispose()
    code, text = _cli("policy", "load", "--db", db, str(current))
    story.fact("load_ok", code == 0)
    story.say(f"$ kognita policy load --db {path.name} current/   exit {code}")
    story.say(f"  {text.splitlines()[-1] if text else ''}")
    code, text = _cli("policy", "load", "--db", db, str(draft))
    story.fact("uncited_load_refused", code != 0)
    story.say(f"$ kognita policy load --db {path.name} draft/     exit {code}  (an uncited rule is refused)")
    story.say(f"Store   {path}")
    return story.result


# --------------------------------------------------------------------------
# packs: list, show, load, update
# --------------------------------------------------------------------------


def scenario_packs(path: Path) -> Any:
    """Built-in packs by folder name, a load into the store, and a pinned update."""
    from kognita.models import EvidenceEvent
    from kognita.packs.catalog import builtin_data
    from kognita.packs.update import update_pack
    from kognita.vocabulary import EventType

    story = _Story("packs", "packs: list, show, load and update")
    root = path.with_suffix("")
    user_root = root / "user"
    managed_root = root / "managed"
    user_root.mkdir(parents=True, exist_ok=True)
    managed_root.mkdir(parents=True, exist_ok=True)
    roots = ("--user-root", str(user_root), "--managed-root", str(managed_root))

    code, text = _cli("packs", "list", *roots)
    names = [line.split()[0] for line in text.splitlines() if line.strip()]
    story.fact("packs", names)
    story.say(f"$ kognita packs list   exit {code}")
    story.say(f"  {', '.join(names)}")

    code, text = _cli("packs", "show", "private-banking", *roots)
    lines = text.splitlines()
    story.fact("private_banking_rules", max(len(lines) - 1, 0))
    story.say(f"$ kognita packs show private-banking   exit {code}  ({max(len(lines) - 1, 0)} rules)")
    for line in lines[:5]:
        story.say(f"  {line}")

    engine = _engine(path)
    engine.dispose()
    code, text = _cli("packs", "load", "two-signature-approval-chains", "--db", str(path), *roots)
    story.fact("load_ok", code == 0)
    story.say(f"$ kognita packs load two-signature-approval-chains --db {path.name}   exit {code}")
    story.say(f"  {text.splitlines()[-1] if text else ''}")

    builtin = builtin_data()

    def offline(url: str, *, tamper: bool = False) -> bytes:
        """Serve the pinned files from the installed wheel instead of GitHub."""
        marker = "/geo-fencing/"
        rel = url.split(marker, 1)[1]
        blob = (builtin / "geo-fencing" / rel).read_bytes()
        if tamper and rel.endswith(".yaml") and "scenarios" not in rel:
            blob = blob.replace(b"ATTRIBUTE_DENYLIST", b"ATTRIBUTE_ALLOWLIST")
        return blob

    refused = update_pack(
        "geo-fencing",
        db=str(path),
        managed_root=managed_root,
        user_root=user_root,
        transport=lambda url: offline(url, tamper=True),
    )
    story.fact("tampered_refused", refused.refused)
    story.fact("tampered_reason", refused.reason)
    story.say(
        f"packs update geo-fencing, tampered file   refused {refused.refused}  reason {refused.reason}"
    )
    installed = update_pack(
        "geo-fencing",
        db=str(path),
        managed_root=managed_root,
        user_root=user_root,
        transport=offline,
    )
    story.fact("pinned_installed", not installed.refused)
    story.say(
        f"packs update geo-fencing, pin matches    installed {not installed.refused}  "
        f"{installed.source_hash[:19]}"
    )
    with Session(_engine(path)) as session:
        changes = session.exec(
            select(EvidenceEvent).where(EvidenceEvent.event_type == EventType.POLICY_CHANGE)
        ).all()
        actions = [str(event.payload.get("action", "")) for event in changes]
    story.fact("policy_change_actions", actions)
    story.say(f"POLICY_CHANGE evidence  {', '.join(a for a in actions if a)}")
    story.say("The transport serves the wheel's own files, so this runs offline;")
    story.say("the real command fetches https://github.com/mze3e/kognita and checks the same pin.")
    story.say(f"Store   {path}")
    return story.result


# --------------------------------------------------------------------------
# recorder: flight recorder and OpenTelemetry
# --------------------------------------------------------------------------


def scenario_recorder(path: Path) -> Any:
    """``kognita recorder`` over the store; OpenTelemetry only with an endpoint."""
    story = _Story("recorder", "flight recorder and OpenTelemetry")
    engine, writer = _seeded(path)
    registry = _registry()
    run_ids: list[str] = []
    with Session(engine) as session:
        denied = {"client_id": "CL-2002", "instrument_id": "INS-HK-NOTE"}
        for kwargs in ({}, denied, denied, denied):
            run = Run()
            run_governed(
                session,
                client_envelope("check_eligibility", **kwargs),
                registry=registry,
                evidence=writer,
                pack=PACK,
                purposes=PURPOSES,
                run=run,
            )
            run_ids.append(run.id)
        session.commit()
    engine.dispose()
    db = str(path)

    code, text = _cli("recorder", "runs", "--db", db)
    story.fact("runs_listed", sum(1 for run_id in run_ids if run_id in text))
    story.say(f"$ kognita recorder runs   exit {code}")
    for line in text.splitlines()[:4]:
        story.say(f"  {line}")

    import json

    code, text = _cli("recorder", "show", "--db", db, run_ids[1])
    shown = json.loads(text) if code == 0 else {}
    failing = [
        item
        for decision in shown.get("decisions", [])
        for item in decision.get("citations", [])
        if item.get("result") == "fail"
    ]
    story.fact("show_outcome", shown.get("latest_outcome"))
    story.fact("show_failing_citations", len(failing))
    story.say(f"$ kognita recorder show <denied run>   exit {code}  outcome {shown.get('latest_outcome')}")
    for item in failing[:3]:
        story.say(f"  {item['regime']:<8} {item['check']}")
        story.say(f"           cite {item['citation']}")

    export = path.with_suffix(".run.json")
    code, text = _cli("recorder", "export", "--db", db, "-o", str(export), run_ids[0])
    story.fact("export_written", export.is_file())
    story.say(f"$ kognita recorder export <allowed run> -o {export.name}   exit {code}  (self-verifying JSON)")

    code, text = _cli("recorder", "alerts", "--db", db)
    alerts = json.loads(text).get("alerts", []) if code == 0 else []
    story.fact("alerts_fired", [a["kind"] for a in alerts if a.get("fired")])
    story.say(f"$ kognita recorder alerts   exit {code}")
    for alert in alerts:
        state = "FIRED" if alert.get("fired") else ("ok" if alert.get("measured") else "not measured")
        story.say(f"  {alert['kind']:<28} {state:<13} {alert['citation']}")

    from kognita.otel import OtelError, attach

    try:
        message = attach(EvidenceWriter(engine))
        story.fact("otel", "attached")
        story.say(f"otel   attached  {message}")
    except OtelError as exc:
        story.fact("otel", "refused")
        story.say(f"otel   not attached  {exc}")
        story.say("A process that looks monitored and is not is refused. Install kognita[otel]")
        story.say("and set OTEL_EXPORTER_OTLP_ENDPOINT to export each evidence event.")
    story.say(f"Store   {path}")
    return story.result


# --------------------------------------------------------------------------
# ingest: structured document ingestion (Docling, optional)
# --------------------------------------------------------------------------

HOUSE_VIEW_MD = """\
Internal. House guidance for relationship managers.

# SGD money market

An accredited investor domiciled in Singapore may be told that the Eastwind
Private SGD money market is a non-complex cash product. Tom &amp; Jerry Ltd
is the sub-custodian.

## Booking centre

Singapore booking centre only.

# Steering group

Confidential. Need-to-know. Consolidation of the Mei Tan relationship stays
with the steering group.
"""


def _docling_installed() -> bool:
    return importlib.util.find_spec("docling") is not None


def scenario_ingest(path: Path) -> Any:
    """A markdown house view, one item per section, each with a locator and a rule."""
    from kognita import HashingEmbedder

    story = _Story("ingest", "structured document ingestion")
    if not _docling_installed():
        story.fact("skipped", "docling extra not installed")
        story.say("skipped  the [docling] extra is not installed.")
        story.say("Install it with:  pip install 'kognita[docling]>=0.4,<0.5'")
        story.say("Core kognita does not import Docling, so nothing else is affected.")
        return story.result

    from kognita.ingest import ingest

    engine, _writer = _seeded(path)
    source = path.with_suffix(".house-view.md")
    source.write_text(HOUSE_VIEW_MD)
    with Session(engine) as session:
        refused = ""
        try:
            ingest(session, source, embedder=HashingEmbedder(), zones=[])
        except Exception as exc:  # noqa: BLE001 - shown on screen
            refused = str(exc)
        session.rollback()
        story.fact("empty_zones_refused", bool(refused))
        story.say(f"zones=[]   refused  {refused}")
        items = ingest(
            session,
            source,
            embedder=HashingEmbedder(),
            zones=["SG"],
            document="house-view-2026-10",
        )
        session.commit()
        rows = [
            {
                "title": item.title,
                "classification": item.classification.value,
                "locator": item.source_label,
                "rule": item.classification_rule or "",
            }
            for item in items
        ]
    story.fact("items", [(row["title"], row["classification"]) for row in rows])
    for row in rows:
        story.say(f"section  {row['classification']}  {row['locator']}")
        if row["rule"]:
            story.say(f"         rule {row['rule']}")
    story.say("A nested section is never classified below its parent; the preamble is a floor.")
    story.say(f"Store   {path}")
    return story.result


# --------------------------------------------------------------------------
# adapters: framework adapters (optional extras)
# --------------------------------------------------------------------------

ADAPTER_EXTRAS = {
    "hermes-agent": "kognita.adapters.hermes",
    "openai-agents": "kognita.adapters.openai_agents",
    "langgraph": "kognita.adapters.langgraph",
    "pydantic-ai": "kognita.adapters.pydantic_ai",
}


def _distribution(name: str) -> str:
    from importlib import metadata

    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return ""


def scenario_adapters(path: Path) -> Any:
    """The binding every adapter shares, and which framework extras are installed."""
    import importlib

    from kognita import FailureMode
    from kognita.adapters.binding import Binding, GovernedRefusal
    from kognita.adapters.hermes import HermesAdapter

    from eastwind.showcase import _gateway, _Spy

    story = _Story("adapters", "framework adapters")
    engine, writer = _seeded(path)
    installed: dict[str, str] = {}
    for extra, module in ADAPTER_EXTRAS.items():
        importlib.import_module(module)  # importing an adapter does not import its framework
        version = _distribution(extra)
        installed[extra] = version
        state = f"installed {version}" if version else "skipped (extra not installed)"
        story.say(f"kognita[{extra}]  {state}")
    story.fact("installed", {k: v for k, v in installed.items() if v})
    story.fact("skipped", [k for k, v in installed.items() if not v])
    story.say("")

    def check_eligibility(client: str) -> str:
        return f"eligibility answered for {client}"

    with Session(engine) as session:
        binding = Binding(
            session=session,
            evidence=writer,
            pack=PACK,
            gateway=_gateway(
                engine, writer, _Spy(b"{}"), upstream="http://127.0.0.1:9",
                failure_mode=FailureMode.FAIL_CLOSED,
            ),
            registry=ToolRegistry(),
            principal=RM,
            purpose=USECASE,
            agent_name=AGENT_NAME,
            purposes=PURPOSES,
            actor_location="SG",
            subject_type="client",
            subject_id="CL-1001",
        )
        governed = binding.wrap(check_eligibility)
        allowed = governed(client="CL-1001")
        story.fact("allowed", allowed)
        story.say(f"wrapped tool, CL-1001   ALLOW  {allowed}")

        binding.subject_id = "CL-2002"
        refusal: GovernedRefusal | None = None
        try:
            governed(client="CL-2002")
        except GovernedRefusal as exc:
            refusal = exc
        story.fact("refused", refusal is not None)
        story.say(f"wrapped tool, CL-2002   {refusal.result.outcome.value if refusal else 'ran'}  tool body not called")
        if refusal is not None:
            for citation in refusal.result.citations[:2]:
                story.say(f"cite    {citation}")

        directive = HermesAdapter(binding).pre_tool_call("check_eligibility", {"client": "CL-2002"})
        story.fact("hermes_directive", (directive or {}).get("action"))
        story.say(f"Hermes pre_tool_call    {(directive or {}).get('action', 'run')}")
        session.commit()
    story.say("Every adapter calls this binding: tools through run_governed, models through")
    story.say("the AI gateway. A framework that is not installed is skipped, not faked.")
    story.say(f"Store   {path}")
    return story.result
