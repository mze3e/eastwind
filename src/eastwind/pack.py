"""Fictional private-banking pack for the Eastwind Private workshop.

Clients, booking centres, and product kinds are invented. Citations name the
shape of a real regime so a talk can point at them; they are workshop
fiction, not legal advice and not a compliance opinion.

The pack supplies what kognita cannot know: how to load subjects by reference,
which attributes a rule turns on, and which regimes are in scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, select

from kognita import (
    Agent,
    Envelope,
    HashingEmbedder,
    Outcome,
    Policy,
    RuleContext,
    build_registry,
    index_item,
)
from kognita.vocabulary import Classification

AGENT_NAME = "eligibility-advisor"
AGENT_OWNER = "Head of Conduct, Eastwind Private"

PURPOSES = ("ELIGIBILITY_CHECK",)

# Domiciles the workshop treats as inside the permitted cross-border set.
PERMITTED_DOMICILES = ("SG", "HK", "AE")

CLIENTS: dict[str, dict[str, Any]] = {
    "CL-1001": {
        "id": "CL-1001",
        "name": "Mei Tan",
        "email": "mei.tan@clients.eastwind.example",
        "account": "SG-PB-1001842",
        "domicile": "SG",
        "booking_centre": "SG",
        "accredited_investor": True,
    },
    "CL-2002": {
        "id": "CL-2002",
        "name": "Lena Vogel",
        "email": "lena.vogel@clients.eastwind.example",
        "account": "HK-PB-2002771",
        "domicile": "DE",
        "booking_centre": "HK",
        "accredited_investor": False,
    },
}

INSTRUMENTS: dict[str, dict[str, Any]] = {
    "INS-MMF": {
        "id": "INS-MMF",
        "name": "Eastwind Private SGD Money Market",
        "kind": "MONEY_MARKET",
        "origin": "SG",
    },
    "INS-HK-NOTE": {
        "id": "INS-HK-NOTE",
        "name": "Eastwind Private HK Autocall Note",
        "kind": "STRUCTURED_NOTE",
        "origin": "HK",
    },
}

# Retrieval query for the ALLOW path. It names the product class, not a person.
HOUSE_QUERY = "Singapore money market eligibility accredited investor booking centre"

KNOWLEDGE: list[dict[str, Any]] = [
    {
        "title": "House view — SGD money market eligibility",
        "body": (
            "Singapore booking centre money market eligibility. An accredited "
            "investor domiciled in Singapore may be told that the Eastwind Private "
            "SGD money market is a non-complex cash product. This is house "
            "guidance for the relationship manager."
        ),
        "kind": "POLICY",
        "classification": Classification.C1,
        "zones": ["SG", "HK", "AE"],
        "source_label": "Eastwind Private House View, money market",
    },
    {
        "title": "SFC complex-product handling",
        "body": (
            "Hong Kong origin structured notes require an eligibility "
            "assessment before any cross-border conversation. A client "
            "domiciled outside the permitted set is outside this product."
        ),
        "kind": "POLICY",
        "classification": Classification.C1,
        "zones": ["HK", "SG"],
        "source_label": "SFC Code of Conduct para 5.5 (workshop fiction)",
    },
    {
        "title": "DFSA cross-border promotion",
        "body": (
            "A relationship manager acting from the DIFC may discuss a "
            "complex product only with a client in a permitted domicile. "
            "Germany is outside that set in this workshop pack."
        ),
        "kind": "POLICY",
        "classification": Classification.C1,
        "zones": ["AE"],
        "source_label": "DFSA COB 3; GEN 2 (workshop fiction)",
    },
    {
        "title": "Steering note — Mei Tan consolidation",
        "body": (
            "Consolidation of the Mei Tan relationship across booking centres "
            "is need-to-know. Holdings and the timetable stay with the "
            "steering group."
        ),
        "kind": "CLIENT_NOTE",
        "classification": Classification.C3,
        "zones": ["SG"],
        "source_label": "Steering group minutes",
    },
    {
        "title": "Unzoned draft — not visible",
        "body": (
            "A note with no zone is not visible in any zone. "
            "Entitlement fails closed when the zone list is missing."
        ),
        "kind": "POLICY",
        "classification": Classification.C1,
        "zones": [],
        "source_label": "Eastwind Private House View, unzoned draft",
    },
]


@dataclass(frozen=True)
class Scenario:
    """One workshop request. The envelope carries references, not client rows."""

    name: str
    title: str
    blurb: str
    expect: Outcome
    principal: str
    actor_location: str
    client_id: str
    instrument_id: str

    def envelope(self) -> Envelope:
        return Envelope(
            principal=self.principal,
            purpose="ELIGIBILITY_CHECK",
            tool="check_eligibility",
            actor_location=self.actor_location,
            agent_name=AGENT_NAME,
            subject_type="client",
            subject_id=self.client_id,
            subjects={"instrument": self.instrument_id},
        )


ALLOW = Scenario(
    name="allow",
    title="Singapore money-market eligibility",
    blurb=(
        "An SG relationship manager asks whether an accredited client "
        "domiciled in Singapore may hear house guidance on a non-complex "
        "money-market fund. The MAS regime is in scope. Expect ALLOW, then "
        "entitled retrieval, then a redacted egress call."
    ),
    expect=Outcome.ALLOW,
    principal="rm.sg@eastwind.example",
    actor_location="SG",
    client_id="CL-1001",
    instrument_id="INS-MMF",
)

DENY = Scenario(
    name="deny",
    title="Cross-border structured note",
    blurb=(
        "An AE relationship manager asks whether a Germany-domiciled client "
        "who is not an accredited investor may be offered an HK-origin "
        "autocall. HK_SFC and DIFC_DFSA both apply. Expect DENY. Retrieval "
        "does not run. OpenAI is not called."
    ),
    expect=Outcome.DENY,
    principal="rm.ae@eastwind.example",
    actor_location="AE",
    client_id="CL-2002",
    instrument_id="INS-HK-NOTE",
)

SCENARIOS: dict[str, Scenario] = {ALLOW.name: ALLOW, DENY.name: DENY}


def client_envelope(
    tool: str,
    *,
    client_id: str = "CL-1001",
    instrument_id: str = "INS-MMF",
    principal: str = "rm.sg@eastwind.example",
    actor_location: str = "SG",
    arguments: dict[str, Any] | None = None,
) -> Envelope:
    """An envelope over the existing clients and instruments."""
    return Envelope(
        principal=principal,
        purpose="ELIGIBILITY_CHECK",
        tool=tool,
        actor_location=actor_location,
        agent_name=AGENT_NAME,
        subject_type="client",
        subject_id=client_id,
        subjects={"instrument": instrument_id},
        arguments=dict(arguments or {}),
    )


class EastwindPack:
    """Domain pack composed with kognita's decision engine."""

    name = "eastwind"

    def load_subjects(self, envelope: Envelope, session: Session | None = None) -> dict[str, Any]:
        """Resolve rows the envelope names.

        This is the pack's own reference data, which the decision point needs
        in order to know the attributes. It is not governed retrieval: a denial
        still does not search the knowledge store or call a model.
        """
        loaded: dict[str, Any] = {}
        for kind, ref in envelope.all_subjects().items():
            table = CLIENTS if kind == "client" else INSTRUMENTS if kind == "instrument" else {}
            row = table.get(str(ref))
            if row is None:
                raise LookupError(f"{kind} {ref!r} is not in the Eastwind Private pack")
            loaded[kind] = row
        return loaded

    def resolve_attributes(self, envelope: Envelope, subjects: dict[str, Any]) -> dict[str, Any]:
        """Attributes policy turns on. Names, emails, and account numbers stay out."""
        client = subjects.get("client") or {}
        instrument = subjects.get("instrument") or {}
        attributes = {
            "actor_location": envelope.actor_location,
            "client_domicile": client.get("domicile"),
            "accredited_investor": bool(client.get("accredited_investor")),
            "booking_centre": client.get("booking_centre"),
            "product_kind": instrument.get("kind"),
            "instrument_origin": instrument.get("origin"),
        }
        # A typed handling label is the pack's, not the model's. The classifier
        # must not overwrite it, including when the argument text names another.
        if envelope.tool == "typed_classification":
            attributes["classification"] = Classification.C0.value
        return attributes

    def rules(self) -> dict[str, Any]:
        return build_registry()

    def engages(self, policy: Policy, context: RuleContext) -> bool:
        """Skip regimes the request never touches, so they cannot deny it by accident."""
        attrs = context.attributes
        if policy.applies_to and policy.applies_to != attrs.get("product_kind"):
            return False
        if policy.regime == "MAS_SG":
            return attrs.get("actor_location") == "SG"
        if policy.regime == "HK_SFC":
            return attrs.get("product_kind") == "STRUCTURED_NOTE"
        if policy.regime == "DIFC_DFSA":
            return attrs.get("actor_location") == "AE"
        if policy.regime == "PRODUCT_GOVERNANCE":
            return attrs.get("product_kind") == "STRUCTURED_NOTE"
        tool = context.envelope.tool
        if policy.regime == "CLASSIFIER_GATE":
            return tool in {"classify_question", "classify_tool", "vague_note"}
        if policy.regime == "HANDLING":
            return tool in {"injection_question", "typed_classification"}
        if policy.regime == "CLIENT_LETTER":
            return tool == "draft_client_letter"
        if policy.regime == "RELEASE_NOTE":
            return tool == "release_structured_note"
        if policy.regime == "TOOL_BAR":
            return tool == "offer_autocall"
        if policy.regime == "MONEY_MARKET_WINDOW":
            return tool == "historical_eligibility"
        return False


def seed_agent(session: Session) -> None:
    """Register ``eligibility-advisor`` once. The kill switch stays off."""
    if session.exec(select(Agent).where(Agent.name == AGENT_NAME)).first() is not None:
        return
    session.add(
        Agent(
            name=AGENT_NAME,
            version="0.1.0",
            owner_exec=AGENT_OWNER,
            risk_class="HIGH",
            materiality_tier="T2",
            kill_switch=False,
        )
    )
    session.flush()


def seed_store(session: Session, embedder: HashingEmbedder | None = None) -> None:
    """Insert the agent, the rules, and the knowledge corpus once."""
    seed_agent(session)
    if session.exec(select(Policy)).first() is not None:
        return

    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    permitted = list(PERMITTED_DOMICILES)
    rows = [
        Policy(
            regime="MAS_SG",
            rule_type="ATTRIBUTE_ALLOWLIST",
            rule={
                "allow": {
                    "actor_location": ["SG"],
                    "client_domicile": permitted,
                },
                "on_violation": "fail",
                "description": (
                    "Singapore booking may assess eligibility for permitted domiciles."
                ),
            },
            citation=(
                "MAS Guidelines on Fair Dealing (FAA-G11); "
                "house adoption s3 (workshop fiction)"
            ),
            effective_from=start,
        ),
        Policy(
            regime="HK_SFC",
            rule_type="ATTRIBUTE_ALLOWLIST",
            applies_to="STRUCTURED_NOTE",
            rule={
                "allow": {"client_domicile": permitted},
                "on_violation": "fail",
                "description": (
                    "HK-origin structured notes are eligible only for permitted domiciles."
                ),
            },
            citation="SFC Code of Conduct para 5.5 (workshop fiction)",
            effective_from=start,
        ),
        Policy(
            regime="DIFC_DFSA",
            rule_type="ATTRIBUTE_ALLOWLIST",
            applies_to="STRUCTURED_NOTE",
            rule={
                "allow": {"client_domicile": permitted},
                "on_violation": "fail",
                "description": (
                    "DIFC promotion of structured notes is limited to permitted domiciles."
                ),
            },
            citation="DFSA COB 3; GEN 2 (workshop fiction)",
            effective_from=start,
        ),
        Policy(
            regime="PRODUCT_GOVERNANCE",
            rule_type="REQUIRES_FLAG",
            applies_to="STRUCTURED_NOTE",
            rule={
                "flags": ["accredited_investor"],
                "on_violation": "fail",
                "description": "Structured notes require an accredited-investor flag.",
            },
            citation="Eastwind Private Product Governance Standard s9 (workshop fiction)",
            effective_from=start,
        ),
        Policy(
            regime="CLASSIFIER_GATE",
            rule_type="CLASSIFIER_CONFIDENCE",
            rule={"min_confidence": 0.8},
            citation=(
                "Eastwind Private Product Governance Standard s9 — "
                "uncertainty is not permission (workshop fiction)"
            ),
            effective_from=start,
        ),
        Policy(
            regime="HANDLING",
            rule_type="ATTRIBUTE_ALLOWLIST",
            rule={
                "allow": {"classification": ["C0"]},
                "on_violation": "fail",
                "description": "This tool permits a typed public label only.",
            },
            citation="Eastwind Private Product Governance Standard s9 (workshop fiction)",
            effective_from=start,
        ),
        Policy(
            regime="CLIENT_LETTER",
            rule_type="REQUIRES_HUMAN_APPROVAL",
            rule={"tools": ["draft_client_letter"]},
            citation="Eastwind Private Product Governance Standard s9 (workshop fiction)",
            effective_from=start,
        ),
        Policy(
            regime="RELEASE_NOTE",
            rule_type="TWO_SIGNATURE_APPROVAL",
            rule={"tools": ["release_structured_note"]},
            citation="Eastwind Private Product Governance Standard s9 (workshop fiction)",
            effective_from=start,
        ),
        Policy(
            regime="TOOL_BAR",
            rule_type="PROHIBITED",
            rule={
                "description": "An autocall is not released through this tool.",
                "on_violation": "fail",
            },
            citation="SFC Code of Conduct para 5.5 (workshop fiction)",
            effective_from=start,
        ),
        Policy(
            regime="MONEY_MARKET_WINDOW",
            rule_type="ATTRIBUTE_ALLOWLIST",
            applies_to="MONEY_MARKET",
            rule={
                "allow": {"client_domicile": list(PERMITTED_DOMICILES)},
                "on_violation": "fail",
                "description": (
                    "Money-market house guidance stays inside the permitted domiciles."
                ),
            },
            citation=(
                "MAS Guidelines on Fair Dealing (FAA-G11); "
                "house adoption s3 (workshop fiction)"
            ),
            effective_from=start,
        ),
    ]
    for row in rows:
        session.add(row)

    embedder = embedder or HashingEmbedder()
    for item in KNOWLEDGE:
        index_item(
            session,
            title=item["title"],
            body=item["body"],
            embedder=embedder,
            kind=item["kind"],
            classification=item["classification"],
            zones=item["zones"],
            source_label=item["source_label"],
        )
