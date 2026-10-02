"""Authorize, then act.

The order is the demo:

1. Build an envelope of references.
2. Resolve attributes and ``decide`` — before any knowledge retrieval.
3. ``record`` the decision on the evidence chain.
4. On DENY, return. ``retrieve`` is not called. The model callable is not called.
5. On ALLOW, retrieve within entitlement, classify the prompt, and send it
   through ``EgressGuard``. The provider sees redacted text. Evidence records
   the manifest hash, not the content.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from sqlmodel import Session, select

from kognita import (
    ActorType,
    Classification,
    EgressDenied,
    EgressGuard,
    EgressPolicy,
    EgressResult,
    Envelope,
    Evaluation,
    EvidenceEvent,
    EvidenceWriter,
    HashingEmbedder,
    Outcome,
    PatternClassifier,
    PatternRedactor,
    create_all,
    decide,
    load_snapshot,
    record,
    retrieve,
    verify_chain,
)
from kognita.db import session_scope
from kognita.retrieval import ceiling_for
from kognita.vocabulary import EventType

from eastwind.pack import (
    HOUSE_QUERY,
    SCENARIOS,
    EastwindPack,
    Scenario,
    seed_store,
)

Completer = Callable[[str], Any]

PACK = EastwindPack()
CLASSIFIER = PatternClassifier()


@dataclass
class ScenarioResult:
    """What one governed run did, including the calls it refused to make."""

    scenario: Scenario
    evaluation: Evaluation
    retrieved_titles: list[str] = field(default_factory=list)
    retrieved_sources: list[str] = field(default_factory=list)
    retrieval_called: bool = False
    model_called: bool = False
    model_skip_reason: str | None = None
    classification: Classification | None = None
    egress: EgressResult | None = None
    guard_denied: bool = False
    event_types: list[str] = field(default_factory=list)
    chain_length: int = 0


def render_prompt(client: dict[str, Any], instrument: dict[str, Any], snippets: list[str]) -> str:
    """Caller-side prompt. Client identifiers are present so the guard can redact them."""
    guidance = "\n".join(f"- {snippet}" for snippet in snippets) or "- (no entitled guidance)"
    return (
        f"Client {client['name']} ({client['email']}) holds account {client['account']}.\n"
        f"Domicile {client['domicile']}. Accredited investor: "
        f"{'yes' if client['accredited_investor'] else 'no'}.\n"
        f"Product: {instrument['name']} (origin {instrument['origin']}, kind {instrument['kind']}).\n"
        f"\nEntitled house guidance:\n{guidance}\n"
        f"\nQuestion: May this relationship manager explain eligibility for this "
        f"product to the client, and what may they say?"
    )


def _events_for(engine: Any, request_id: str) -> list[str]:
    with Session(engine) as session:
        rows = session.exec(
            select(EvidenceEvent)
            .where(EvidenceEvent.correlation_id == request_id)
            .order_by(EvidenceEvent.sequence)
        ).all()
    return [EventType(row.event_type).value for row in rows]


def run_scenario(
    name: str,
    *,
    engine: Any,
    evidence: EvidenceWriter | None = None,
    completer: Completer | None = None,
    destination: str = "api.openai.com",
    destination_is_local: bool = False,
    call_model: bool = True,
) -> ScenarioResult:
    """Run one scenario. ``completer`` is invoked only after an ALLOW, inside the guard."""
    scenario = SCENARIOS[name]
    create_all(engine)
    writer = evidence or EvidenceWriter(engine)
    embedder = HashingEmbedder()
    envelope: Envelope = scenario.envelope()

    prompt: str | None = None
    redact_terms: list[str] = []
    classification: Classification | None = None
    retrieved_titles: list[str] = []
    retrieved_sources: list[str] = []
    retrieval_called = False

    with session_scope(engine) as session:
        seed_store(session, embedder)
        subjects = PACK.load_subjects(envelope, session)
        attributes = PACK.resolve_attributes(envelope, subjects)
        evaluation = decide(
            envelope,
            load_snapshot(session),
            attributes=attributes,
            subjects=subjects,
            rules=PACK.rules(),
            purposes=("ELIGIBILITY_CHECK",),
            engages=PACK.engages,
        )
        evaluation = record(
            session,
            evaluation,
            evidence=writer,
            classification=Classification.C2,
        )

        if evaluation.outcome is Outcome.ALLOW:
            retrieval_called = True
            hits = retrieve(
                session,
                HOUSE_QUERY,
                zone=envelope.actor_location,
                embedder=embedder,
                evidence=writer,
                correlation_id=evaluation.request_id,
                actor_id=envelope.agent_name or envelope.principal,
                actor_type=ActorType.AGENT,
                ceiling=ceiling_for(envelope.is_admin),
            )
            retrieved_titles = [hit.title for hit in hits]
            retrieved_sources = [hit.source_label for hit in hits]
            client = subjects["client"]
            prompt = render_prompt(
                client,
                subjects["instrument"],
                [hit.snippet for hit in hits],
            )
            redact_terms = [str(client["name"])]
            classification = CLASSIFIER.classify(prompt)

    model_called = False
    guard_denied = False
    skip: str | None = None
    egress: EgressResult | None = None

    if evaluation.outcome is not Outcome.ALLOW:
        skip = "decision was not ALLOW"
    elif not call_model:
        skip = "model call skipped (--skip-model)"
    elif completer is None:
        skip = "OPENAI_API_KEY is not set"
    elif prompt is None or classification is None:
        skip = "no prompt to send"
    else:
        guard = EgressGuard(
            policy=EgressPolicy(),
            redactor=PatternRedactor(extra_terms=redact_terms),
            evidence=writer,
        )
        with session_scope(engine) as session:
            try:
                egress = guard.send(
                    prompt,
                    completer,
                    classification=classification,
                    destination=destination,
                    destination_is_local=destination_is_local,
                    session=session,
                    correlation_id=evaluation.request_id,
                    actor_id=envelope.agent_name or envelope.principal,
                    actor_type=ActorType.AGENT,
                )
            except EgressDenied as exc:
                # The guard writes the refusal, then raises. Catching it here
                # lets that evidence commit. The completer was not called.
                guard_denied = True
                skip = str(exc)
            else:
                model_called = True

    with Session(engine) as session:
        chain_length = verify_chain(session)

    return ScenarioResult(
        scenario=scenario,
        evaluation=evaluation,
        retrieved_titles=retrieved_titles,
        retrieved_sources=retrieved_sources,
        retrieval_called=retrieval_called,
        model_called=model_called,
        model_skip_reason=None if model_called else skip,
        classification=classification,
        egress=egress,
        guard_denied=guard_denied,
        event_types=_events_for(engine, evaluation.request_id),
        chain_length=chain_length,
    )
