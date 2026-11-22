"""PWM 0.10 register and evidence export.

Mapping follows Kognita's docs/ontology/pwm/tools/register_roundtrip.py and
roundtrip.py, copyright Kognita contributors, MIT license. The demo profile
adds explicitly synthetic information not present in Kognita's register.
"""
from __future__ import annotations

from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from urllib.parse import quote

from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef, XSD
from rdflib.namespace import DCTERMS, OWL, SKOS
from sqlmodel import Session, select

from kognita import export_chain, verify_chain
from kognita.models import Agent, EvidenceEvent, _WorkloadCredential
from kognita.sources import _load as load_sources
from kognita.usecases import list_usecases

P = Namespace("https://ahmedmuzammil.com/ontology/pwm#")
PROV = Namespace("http://www.w3.org/ns/prov#")
ROLE = Namespace("https://www.omg.org/spec/Commons/RolesAndCompositions/")
PERSON = URIRef("https://spec.edmcouncil.org/fibo/ontology/FND/AgentsAndPeople/People/Person")
ONTOLOGY = files("eastwind").joinpath("pwm_data/pwm.ttl")
SHAPES = files("eastwind").joinpath("pwm_data/pwm-shapes.ttl")
LEVELS = ("L0Retrieve", "L1Explain", "L2Recommend", "L3Draft", "L4ActAfterApproval", "L5BoundedAutonomy", "L6BroadAutonomy")
RATINGS = {"low": "RatingLow", "medium": "RatingMedium", "high": "RatingHigh", "critical": "RatingCritical"}


def _iri(kind: str, value: str) -> URIRef:
    return URIRef(f"urn:eastwind:{kind}:{quote(str(value), safe='')}")


def _date(value) -> Literal:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return Literal(value.astimezone(timezone.utc), datatype=XSD.dateTime)


def _concept(ont: Graph, scheme: str, notation: str) -> URIRef:
    for concept in ont.subjects(SKOS.inScheme, P[scheme]):
        if str(ont.value(concept, SKOS.notation)) == str(notation):
            return concept
    raise ValueError(f"PWM has no {scheme} concept for {notation!r}")


def _person(graph: Graph, name: str) -> URIRef:
    node = _iri("person", name)
    graph.add((node, RDF.type, PERSON))
    graph.add((node, RDFS.label, Literal(name)))
    return node


def _role(graph: Graph, uc: URIRef, kind: str, name: str) -> URIRef:
    node = _iri("role", f"{uc}:{kind}:{name}")
    graph.add((node, RDF.type, P[kind]))
    graph.add((node, ROLE.isPlayedBy, _person(graph, name)))
    graph.add((uc, P.hasAccountabilityRole, node))
    return node


def export_graph(session: Session, *, demo_profile: bool = False, include_evidence: bool = True) -> Graph:
    """Export the effective register. Missing values remain absent.

    demo_profile applies only to Eastwind's named synthetic sample. It is not
    inferred for other registrations and is not an operational attestation.
    """
    verify_chain(session)
    ontology = Graph().parse(str(ONTOLOGY), format="turtle")
    graph = Graph()
    graph.bind("pwm", P)
    graph.bind("prov", PROV)
    graph.bind("rdfs", RDFS)
    profile = None
    if demo_profile:
        for event in session.exec(select(EvidenceEvent).order_by(EvidenceEvent.sequence)).all():
            if event.payload.get("action") == "PWM_DEMO_PROFILE":
                profile = event.payload
                profile_event = event
        if profile is None:
            raise ValueError("the store has no recorded synthetic PWM profile")
        profile_uri = _iri("profile", "synthetic-pwm-0.10")
        graph.add((profile_uri, RDFS.label, Literal("Synthetic Eastwind PWM profile")))
        graph.add((profile_uri, RDFS.comment, Literal("Illustrative declarations, not runtime or supervisory attestation.")))
        graph.add((profile_uri, PROV.wasDerivedFrom, _iri("event", str(profile_event.sequence))))
    entries = list_usecases(session, as_of=datetime.now(timezone.utc))
    source_usecases: dict[str, list[str]] = {}
    for entry in entries:
        if profile and entry.usecase_id == profile.get("usecase") and entry.content_hash != profile.get("usecase_hash"):
            raise ValueError("synthetic PWM profile does not match the current use-case version")
        node = _iri("usecase", entry.usecase_id)
        purpose = _iri("purpose", entry.usecase_id)
        graph.add((node, RDF.type, P.AIUseCase))
        graph.add((node, RDFS.label, Literal(entry.usecase_id)))
        graph.add((node, OWL.versionInfo, Literal(str(entry.version))))
        graph.add((purpose, RDF.type, P.Purpose))
        graph.add((purpose, RDFS.label, Literal(entry.purpose)))
        graph.add((node, P.hasPurpose, purpose))
        if entry.jurisdiction:
            graph.add((node, P.approvedJurisdiction, Literal(entry.jurisdiction)))
        if entry.status:
            graph.add((node, P.lifecycleStatus, _concept(ontology, "UseCaseStatusScheme", entry.status)))
        if entry.proposed_tier is not None:
            graph.add((node, P.riskTier, _concept(ontology, "RiskTierScheme", str(entry.proposed_tier))))
        graph.add((node, P.isMediated, Literal(not entry.unmediated)))
        if entry.review_date:
            graph.add((node, P.nextReviewDate, _date(entry.review_date)))
        if entry.data_sensitivity:
            data_classes = {"public": "C0", "internal": "C1", "confidential": "C2", "highly sensitive": "C3"}
            if entry.data_sensitivity in data_classes:
                graph.add((node, P.usesDataClass, _concept(ontology, "DataClassificationScheme", data_classes[entry.data_sensitivity])))
        for field, role in (("business_owner", "BusinessOwner"), ("technology_owner", "TechnologyOwner"),
                            ("knowledge_lead", "KnowledgeLead")):
            if getattr(entry, field):
                _role(graph, node, role, getattr(entry, field))
        if entry.approved_models:
            graph.add((node, P.modelType, Literal(entry.approved_models[0])))
        for dependency in entry.depends_on or entry.model_providers:
            dep = _iri("provider", dependency)
            graph.add((dep, RDF.type, P.ModelProvider))
            graph.add((dep, RDFS.label, Literal(dependency)))
            graph.add((node, P.dependsOn, dep))
        if entry.deployment_mode:
            graph.add((node, P.deploymentMode, Literal(entry.deployment_mode)))
        failure_mode = entry.record.get("failure_mode")
        if failure_mode:
            graph.add((node, P.gatewayFailureMode, _concept(ontology, "GatewayFailureModeScheme", failure_mode)))
        if entry.retention_days is not None:
            retention = _iri("retention", entry.usecase_id)
            graph.add((retention, RDF.type, P.RetentionPolicy))
            graph.add((retention, P.retentionDuration, Literal(entry.retention_days, datatype=XSD.nonNegativeInteger)))
            graph.add((node, P.retentionPolicy, retention))
        if entry.residual_materiality or entry.inherent_materiality:
            assessment = _iri("assessment", entry.usecase_id)
            graph.add((assessment, RDF.type, P.RiskMaterialityAssessment))
            graph.add((assessment, P.assesses, node))
            graph.add((node, P.hasMaterialityAssessment, assessment))
            for name, value in (("inherentMateriality", entry.inherent_materiality), ("residualMateriality", entry.residual_materiality)):
                if value in RATINGS:
                    graph.add((assessment, P[name], P[RATINGS[value]]))
            if entry.rating_approved and entry.rating_approved_by:
                control = _iri("control-function", entry.rating_approved_by)
                graph.add((control, RDF.type, P.DesignatedControlFunction))
                graph.add((control, ROLE.isPlayedBy, _person(graph, entry.rating_approved_by)))
                graph.add((assessment, P.approvedBy, control))
            if profile and entry.usecase_id == profile.get("usecase"):
                # Explicit synthetic assessment, not fields in Kognita's register.
                graph.add((assessment, DCTERMS.source, profile_uri))
                for name, level in profile["assessment"].items():
                    graph.add((assessment, P[name], P[level]))
        for source_id in entry.approved_sources:
            source_usecases.setdefault(source_id, []).append(entry.usecase_id)

    from kognita.registry import _deployment_hash

    for agent in session.exec(select(Agent)).all():
        deployment = (agent.tool_allowlist or {}).get("_deployment")
        current_hash = _deployment_hash(agent, deployment) if isinstance(deployment, dict) else None
        if profile and agent.name == profile.get("agent") and (
                agent.deployment_hash != profile.get("deployment_hash") or current_hash != agent.deployment_hash):
            raise ValueError("synthetic PWM profile does not match the current agent deployment")
        node = _iri("agent", agent.name)
        graph.add((node, RDF.type, P.AIAgent))
        graph.add((node, P.agentIdentifier, Literal(agent.name)))
        graph.add((node, RDFS.label, Literal(agent.name)))
        if agent.version:
            graph.add((node, OWL.versionInfo, Literal(agent.version)))
        if agent.autonomy_level is not None and 0 <= agent.autonomy_level < len(LEVELS):
            graph.add((node, P.maxAutonomyLevel, P[LEVELS[agent.autonomy_level]]))
        for usecase in agent.use_cases or []:
            graph.add((node, P.registeredForUseCase, _iri("usecase", usecase)))
            graph.add((node, P.hasPurpose, _iri("purpose", usecase)))
        if current_hash:
            graph.add((node, P.deploymentVersion, Literal(current_hash)))
        if agent.deployment_hash:
            graph.add((node, P.approvedDeploymentVersion, Literal(agent.deployment_hash)))
        if agent.review_date:
            graph.add((node, P.nextReviewDate, _date(agent.review_date)))
        if agent.deployment_date:
            graph.add((node, P.deploymentDate, _date(agent.deployment_date)))
        if agent.owner_exec:
            graph.add((node, P.agentOwner, _person(graph, agent.owner_exec)))
        if agent.principal:
            graph.add((node, P.operatesFor, _person(graph, agent.principal)))
        if agent.model:
            model = _iri("model", agent.model)
            graph.add((model, RDF.type, P.AIModel))
            graph.add((model, RDFS.label, Literal(agent.model)))
            graph.add((node, P.deploymentModel, model))
        if agent.environment:
            graph.add((node, P.deploymentEnvironment, Literal(agent.environment, datatype=XSD.string)))
        # Kognita stores a stop flag, not a lifecycle status. The demo profile
        # records its separate synthetic lifecycle declaration explicitly.
        if profile and agent.name == profile.get("agent"):
            graph.add((node, P.agentStatus, P[profile["agent_status"]]))
            graph.add((node, DCTERMS.source, profile_uri))
        credential = session.exec(select(_WorkloadCredential).where(
            _WorkloadCredential.agent_name == agent.name, _WorkloadCredential.revoked == False)
            .order_by(_WorkloadCredential.digest)).first()
        if credential:
            identity = _iri("identity", agent.name)
            graph.add((identity, RDF.type, P.WorkloadIdentity))
            graph.add((identity, P.credentialReference, Literal(str(_iri("credential-digest", credential.digest)), datatype=XSD.anyURI)))
            issuance = next((event for event in session.exec(select(EvidenceEvent).where(
                EvidenceEvent.correlation_id == f"credentials:{agent.name}")).all()
                if event.payload.get("action") == "CREDENTIAL_ISSUED"
                and event.payload.get("digest") == credential.digest), None)
            if issuance and issuance.actor_id:
                graph.add((identity, P.credentialIssuer, Literal(str(_iri("person", issuance.actor_id)), datatype=XSD.anyURI)))
            graph.add((identity, P.workloadSubject, Literal(agent.name, datatype=XSD.string)))
            if agent.environment:
                graph.add((identity, P.deploymentEnvironment, Literal(agent.environment, datatype=XSD.string)))
            graph.add((node, P.workloadIdentity, identity))
        for dimension in ("per_minute", "per_hour", "max_clients", "max_daily_actions",
                          "max_daily_transactions", "max_value"):
            maximum = (agent.blast_radius or {}).get(dimension)
            if maximum is not None:
                limit = _iri("blast-limit", f"{agent.name}:{dimension}")
                graph.add((limit, RDF.type, P.BlastRadiusLimit))
                graph.add((limit, P.limitDimension, Literal(dimension)))
                graph.add((limit, P.limitMaximum, Literal(str(maximum), datatype=XSD.decimal)))
                graph.add((node, P.hasBlastRadiusLimit, limit))
        for name, metadata in (agent.tool_allowlist or {}).items():
            if name.startswith("_") or not isinstance(metadata, dict):
                continue
            tool = _iri("tool", f"{agent.name}:{name}")
            graph.add((tool, RDF.type, P.Tool))
            graph.add((tool, RDFS.label, Literal(name)))
            graph.add((node, P.permittedTool, tool))
            level = metadata.get("required_level")
            if type(level) is int and 0 <= level < len(LEVELS):
                graph.add((tool, P.requiredAutonomyLevel, P[LEVELS[level]]))
            if metadata.get("verb"):
                graph.add((tool, P.actionVerb, _concept(ontology, "ActionVerbScheme", metadata["verb"])))
            duration = metadata.get("max_duration", 30.0)
            graph.add((tool, P.maximumDurationSeconds, Literal(str(duration), datatype=XSD.decimal)))
            if profile and agent.name == profile.get("agent") and name in profile["tools"]:
                # Profile declarations describe the synthetic workflow, not runtime proof.
                tool_profile = profile["tools"][name]
                graph.add((tool, DCTERMS.source, profile_uri))
                graph.add((tool, P.reversibilityClass, P[tool_profile["reversibility"]]))
                graph.add((tool, P.supportsCancellation, Literal(tool_profile["supports_cancellation"])))
                graph.add((tool, P.decisionSeparatedSteps, Literal(tool_profile["decision_separated_steps"])))

    for source in load_sources(session).entries:
        node = _iri("source", f"{source.source_id}:{source.version}")
        graph.add((node, RDF.type, P.ApprovedSource))
        graph.add((node, RDFS.label, Literal(source.source_id)))
        graph.add((node, DCTERMS.identifier, Literal(source.source_id)))
        graph.add((node, DCTERMS.type, Literal(source.kind)))
        graph.add((node, OWL.versionInfo, Literal(source.version)))
        graph.add((node, PROV.generatedAtTime, _date(source.effective)))
        graph.add((node, PROV.wasAttributedTo, _person(graph, source.owner)))
        if source.expiry:
            graph.add((node, P.validUntil, _date(source.expiry)))
        now = datetime.now(timezone.utc)
        if not source.superseded_by and source.effective <= now and (source.expiry is None or source.expiry > now):
            for usecase in source_usecases.get(source.source_id, []):
                graph.add((node, P.approvedForUseCase, _iri("usecase", usecase)))

    if include_evidence:
        _export_evidence(graph, ontology, export_chain(session))
    return graph


def _export_evidence(graph: Graph, ontology: Graph, payload: dict) -> None:
    for event in payload["events"]:
        node = _iri("event", str(event["sequence"]))
        graph.add((node, RDF.type, P.EvidenceRecord))
        graph.add((node, P.eventType, _concept(ontology, "EvidenceEventTypeScheme", event["event_type"])))
        graph.add((node, P.recordHash, Literal(event["event_hash"])))
        graph.add((node, P.evidenceSequence, Literal(event["sequence"], datatype=XSD.nonNegativeInteger)))
        if event.get("schema_version") is not None:
            graph.add((node, P.schemaVersion, Literal(str(event["schema_version"]))))
        graph.add((node, PROV.generatedAtTime, _date(event["recorded_at"])))
        if event["prev_hash"] == "0" * 64:
            graph.add((node, P.chainStart, Literal(True)))
        else:
            graph.add((node, P.previousRecordHash, Literal(event["prev_hash"])))
        if event.get("payload_hash"):
            graph.add((node, P.contentHash, Literal(event["payload_hash"])))
        if event.get("actor_type"):
            graph.add((node, P.actorType, _concept(ontology, "ActorTypeScheme", event["actor_type"])))
        if event.get("classification"):
            graph.add((node, P.classification, _concept(ontology, "DataClassificationScheme", event["classification"])))
        if event.get("signature"):
            graph.add((node, P.signature, Literal(event["signature"])))
        if event.get("key_id"):
            key = _iri("key", event["key_id"])
            graph.add((key, RDF.type, P.SigningKey))
            graph.add((key, P.keyId, Literal(event["key_id"])))
            graph.add((key, P.publicKeyReference, Literal(str(key))))
            graph.add((node, P.signedBy, key))


def validate_graph(graph: Graph) -> tuple[bool, str]:
    from pyshacl import validate

    required = (P.AIUseCase, P.AIAgent, P.ApprovedSource)
    missing = [str(cls) for cls in required if not any(graph.subjects(RDF.type, cls))]
    if missing:
        return False, "Export is incomplete: missing " + ", ".join(missing)
    shapes = Graph().parse(str(SHAPES), format="turtle")
    ontology = Graph().parse(str(ONTOLOGY), format="turtle")
    conforms, _, report = validate(graph, shacl_graph=shapes, ont_graph=ontology, inference="rdfs")
    return bool(conforms), str(report)


def create_demo_store(path: Path) -> None:
    """Create a separate synthetic register with an explicit retention period."""
    import os
    from tempfile import TemporaryDirectory

    from kognita import ActorType, EvidenceWriter, create_all, make_engine
    from kognita.vocabulary import EventType
    from eastwind.agents.workflows import WealthAgent
    from eastwind.pack import _headers, register_usecases, seed_agent, seed_store
    from kognita.usecases import load_register

    if path.exists():
        raise FileExistsError(f"refusing to replace {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".pwm-", dir=path.parent) as temp:
        candidate = Path(temp) / "demo.db"
        engine = make_engine(candidate)
        create_all(engine)
        with Session(engine) as session:
            seed_agent(session)
            register_usecases(session, retention_days=365, deployment_mode="library")
            seed_store(session)
            _headers(session)
            agent = session.exec(select(Agent).where(Agent.name == "eligibility-advisor")).one()
            tool_names = [name for name in agent.tool_allowlist if not name.startswith("_")]
            entry = load_register(session).get("ELIGIBILITY_CHECK")
            if entry is None:
                raise ValueError("synthetic use case was not registered")
            EvidenceWriter(engine).emit(session, correlation_id="pwm:synthetic-profile",
                event_type=EventType.POLICY_CHANGE, actor_type=ActorType.HUMAN, actor_id=agent.owner_exec,
                payload={"action": "PWM_DEMO_PROFILE", "agent": agent.name, "usecase": "ELIGIBILITY_CHECK",
                         "agent_status": "StatusLive", "deployment_hash": agent.deployment_hash,
                         "usecase_hash": entry.content_hash, "assessment": {"impact": "RatingLow",
                         "complexity": "RatingLow", "reliance": "RatingLow"},
                         "tools": {name: {"reversibility": "Irreversible", "supports_cancellation": False,
                                          "decision_separated_steps": True} for name in tool_names},
                         "description": "Synthetic profile declarations for the demo; not an operational attestation."})
            session.commit()
        engine.dispose()
        agent = WealthAgent(candidate)
        agent.engine.dispose()
        # Linking publishes only if the destination is still absent.
        os.link(candidate, path)
