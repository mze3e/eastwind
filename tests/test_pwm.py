"""PWM mapping, full SHACL validation, and missing-data behavior."""
from hashlib import sha256

import pytest
from rdflib import Graph, RDF, RDFS
from sqlmodel import Session, select

from kognita import export_chain, make_engine
from kognita.models import Agent
from eastwind.agents.workflows import client_review
from eastwind.cli import main
from eastwind.pwm import ONTOLOGY, P, SHAPES, create_demo_store, export_graph, validate_graph


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    path = tmp_path_factory.mktemp("pwm") / "demo.db"
    create_demo_store(path)
    return path


def test_vendored_ontology_is_exact_010():
    assert sha256(ONTOLOGY.read_bytes()).hexdigest() == "2457e99880b3b388fc2c643623f604a6ad74cb93eee4c0914431726e02838a40"
    assert sha256(SHAPES.read_bytes()).hexdigest() == "08426559ab67d5ca8ef2e0210514807a22e4f688ac198a65c25d62b3000d7371"


def test_export_maps_live_register_and_verified_evidence(demo):
    with Session(make_engine(demo)) as session:
        graph = export_graph(session, demo_profile=True)
        evidence = export_chain(session)
        agent = session.exec(select(Agent)).one()
        registered_tools = {name for name in agent.tool_allowlist if not name.startswith("_")}
    assert len(list(graph.subjects(RDF.type, P.AIUseCase))) == 1
    assert len(list(graph.subjects(RDF.type, P.AIAgent))) == 1
    assert len(list(graph.subjects(RDF.type, P.ApprovedSource))) == 1
    tool_nodes = list(graph.subjects(RDF.type, P.Tool))
    assert {str(graph.value(tool, RDFS.label)) for tool in tool_nodes} == registered_tools
    assert {str(value) for value in graph.objects(None, P.recordHash)} == {
        event["event_hash"] for event in evidence["events"]}
    assert len(list(graph.subjects(RDF.type, P.EvidenceRecord))) == evidence["event_count"]
    assert len(list(graph.objects(None, P.approvedForUseCase))) == 1
    assert not any("_deployment" in str(value) for value in graph.objects(None, P.agentIdentifier))
    conforms, report = validate_graph(graph)
    assert conforms, report


def test_missing_identifier_fails_full_shapes(demo, tmp_path, capsys):
    with Session(make_engine(demo)) as session:
        graph = export_graph(session, demo_profile=True)
    agent = next(graph.subjects(RDF.type, P.AIAgent))
    graph.remove((agent, P.agentIdentifier, None))
    conforms, report = validate_graph(graph)
    assert not conforms
    assert "agentIdentifier" in report
    broken = tmp_path / "broken.ttl"
    graph.serialize(destination=broken, format="turtle")
    assert main(["pwm", "validate", "--file", str(broken)]) == 1
    assert "Conforms: False" in capsys.readouterr().out


def test_missing_register_cannot_pass_vacuously():
    conforms, report = validate_graph(Graph())
    assert not conforms
    assert "incomplete" in report


def test_existing_register_is_exported_without_invented_profile(tmp_path):
    path = tmp_path / "workflow.db"
    client_review(path)
    with Session(make_engine(path)) as session:
        graph = export_graph(session)
        with pytest.raises(ValueError, match="no recorded synthetic PWM profile"):
            export_graph(session, demo_profile=True)
    assert any(graph.subjects(RDF.type, P.AIUseCase))
    assert any(graph.subjects(RDF.type, P.AIAgent))
    assert any(graph.subjects(RDF.type, P.ApprovedSource))
    conforms, report = validate_graph(graph)
    assert not conforms
    assert "retentionPolicy" in report or "deploymentMode" in report


def test_profile_is_bound_to_current_deployment(tmp_path):
    path = tmp_path / "changed.db"
    create_demo_store(path)
    engine = make_engine(path)
    with Session(engine) as session:
        agent = session.exec(select(Agent)).one()
        agent.deployment_hash = "different-deployment"
        session.add(agent)
        session.commit()
    with Session(engine) as session:
        with pytest.raises(ValueError, match="does not match the current agent deployment"):
            export_graph(session, demo_profile=True)


def test_cli_exports_and_validates_demo(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "export.ttl"
    assert main(["pwm", "export", "-o", str(output)]) == 0
    assert output.is_file()
    assert main(["pwm", "validate", str(output)]) == 0
    assert "Conforms: True" in capsys.readouterr().out
    assert main(["pwm", "validate"]) == 0
    assert "Conforms: True" in capsys.readouterr().out
    assert main(["pwm", "export", "--db", str(tmp_path / "missing.db")]) == 1
    assert not (tmp_path / "missing.db").exists()


def test_expired_source_is_not_exported_as_currently_approved(tmp_path):
    from dataclasses import replace
    from datetime import datetime, timedelta, timezone
    from kognita import EvidenceWriter
    from kognita.sources import _load, register_source

    path = tmp_path / "expired.db"
    create_demo_store(path)
    engine = make_engine(path)
    with Session(engine) as session:
        source = _load(session).entries[0]
        expired = replace(source, expiry=datetime.now(timezone.utc) - timedelta(days=1))
        register_source(session, expired, evidence=EvidenceWriter(engine), interaction_id="source:update")
        session.commit()
    with Session(engine) as session:
        graph = export_graph(session, demo_profile=True)
    assert any(graph.subjects(RDF.type, P.ApprovedSource))
    assert not list(graph.objects(None, P.approvedForUseCase))


def test_export_does_not_include_unrelated_environment_secrets(demo, monkeypatch):
    monkeypatch.setenv("EASTWIND_LLM_API_KEY", "example-test-only-secret")
    with Session(make_engine(demo)) as session:
        graph = export_graph(session, demo_profile=True)
    assert "example-test-only-secret" not in graph.serialize(format="turtle")


def test_profile_rejects_changed_use_case(tmp_path):
    from kognita import EvidenceWriter
    from kognita.usecases import suspend

    path = tmp_path / "changed-usecase.db"
    create_demo_store(path)
    engine = make_engine(path)
    with Session(engine) as session:
        suspend(session, "ELIGIBILITY_CHECK", evidence=EvidenceWriter(engine),
                actor_id="Head of Conduct, Eastwind Private")
        session.commit()
    with Session(engine) as session:
        with pytest.raises(ValueError, match="does not match the current use-case version"):
            export_graph(session, demo_profile=True)


def test_demo_store_never_replaces_existing_file(tmp_path):
    path = tmp_path / "existing.db"
    path.write_bytes(b"existing content")
    with pytest.raises(FileExistsError):
        create_demo_store(path)
    assert path.read_bytes() == b"existing content"
