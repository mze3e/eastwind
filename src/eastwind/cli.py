"""Command line for the Eastwind Private governed-agents demo."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlmodel import Session

from kognita import __version__ as kognita_version
from kognita import export_chain, make_engine, verify_chain, verify_export
from kognita.evidence import ChainBreak
from kognita.vocabulary import CheckResult

from eastwind import __version__
from eastwind.openai_chat import DEFAULT_MODEL
from eastwind.run import ScenarioResult, run_scenario
from eastwind.showcase import SCENARIO_ORDER, run_all, run_named

DEFAULT_DB = Path(".eastwind/evidence.db")


def _db_path(raw: str) -> Path:
    return Path(raw)


def _reset_store(path: Path) -> None:
    for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
        if candidate.exists():
            candidate.unlink()


_RESULT_LABEL = {
    CheckResult.PASS: "PASS",
    CheckResult.FAIL: "FAIL",
    CheckResult.ESCALATE: "ESCALATE",
    CheckResult.REQUIRES_HUMAN: "HUMAN",
}


def _echo_model(redacted: str) -> str:
    """Deterministic stand-in so a room without an API key can see redaction."""
    missing = [token for token in ("[TERM_1]", "[EMAIL_1]", "[ACCOUNT_1]") if token not in redacted]
    if missing:
        raise RuntimeError(
            "egress redaction did not replace the planted client identifiers: "
            + ", ".join(missing)
        )
    return (
        "House guidance supports explaining the money-market fund to "
        "[TERM_1] ([EMAIL_1]), account [ACCOUNT_1]. "
        "This reply was produced locally. OpenAI was not called."
    )


def _print_result(result: ScenarioResult, *, db: Path) -> None:
    evaluation = result.evaluation
    scenario = result.scenario
    envelope = evaluation.envelope
    print(f"Scenario  {scenario.name} - {scenario.title}")
    print(f"  {scenario.blurb}")
    print()
    print("Envelope  (references only; the client row is not the prompt)")
    print(f"  principal       {envelope.principal}")
    print(f"  agent           {envelope.agent_name}")
    print(f"  purpose         {envelope.purpose}")
    print(f"  tool            {envelope.tool}")
    print(f"  actor_location  {envelope.actor_location}")
    print(f"  client          {envelope.subject_id}")
    print(f"  instrument      {envelope.subjects.get('instrument')}")
    print()
    print(
        f"Decision  {evaluation.outcome.value}"
        f"    request {evaluation.request_id}"
    )
    for check in evaluation.checks:
        mark = _RESULT_LABEL.get(check.result, check.result.value.upper())
        print(f"  {mark:<16} {check.regime:<20} {check.citation}")
        print(f"  {'':<16} {check.check}")
    if evaluation.outcome.value == "DENY":
        passed = [c.check for c in evaluation.checks if c.result is CheckResult.PASS]
        print()
        print(
            "Fail closed. Passing checks: "
            + ", ".join(passed)
            + ". Outcome: DENY."
        )
    print()
    if result.retrieval_called:
        print(f"Retrieval  {len(result.retrieved_titles)} entitled fragment(s)")
        for title, source in zip(result.retrieved_titles, result.retrieved_sources, strict=True):
            print(f"  - {title}")
            print(f"    {source}")
        print("  The C3 steering note stays out: the caller ceiling is C2.")
    else:
        print("Retrieval  not called")
    print()
    if result.model_called and result.egress is not None:
        egress = result.egress
        classification = (
            result.classification.value if result.classification is not None else ""
        )
        print(
            f"Egress     {egress.decision.value}"
            f"    classification {classification}"
            f"    destination {egress.destination}"
            f"    local {egress.destination_is_local}"
        )
        print(f"  redacted spans  {egress.redacted_span_count}  ({', '.join(egress.token_map)})")
        print(f"  manifest hash   {egress.manifest_hash}")
        print("  provider saw:")
        for line in egress.sent_text.splitlines():
            print(f"    {line}")
        print("  caller received (tokens restored):")
        response = egress.response if isinstance(egress.response, str) else str(egress.response)
        for line in response.splitlines() or ["(empty)"]:
            print(f"    {line}")
    else:
        reason = result.model_skip_reason or "not called"
        print(f"Model call not made - {reason}")
    print()
    noun = "event" if result.chain_length == 1 else "events"
    print(
        "Evidence   chain verified, "
        f"{result.chain_length} {noun} in the store; "
        f"this request: {', '.join(result.event_types) or '(none)'}"
    )
    print(f"Store      {db}")
    print(f"Export     kognita evidence export --db {db} --correlation-id {evaluation.request_id}")
    print()


def cmd_doctor(_args: argparse.Namespace) -> int:
    key = os.environ.get("OPENAI_API_KEY", "")
    model = os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)
    print(f"eastwind {__version__}")
    print(f"kognita     {kognita_version}")
    print(f"python      {sys.version.split()[0]}")
    print(f"OPENAI_MODEL              {model}")
    print(f"OPENAI_API_KEY            {'set' if key else 'not set'}")
    try:
        import openai

        print(f"openai sdk                {getattr(openai, '__version__', 'installed')}")
    except ImportError:
        print("openai sdk                not installed (pip install 'eastwind[openai]')")
    return 0



def cmd_run(args: argparse.Namespace) -> int:
    from eastwind.llm import GatewayClient, MockClient, Settings

    llm = Settings.from_env(args.llm)
    if llm.provider != "mock":
        llm.validate()
    db = _db_path(args.db)
    if args.fresh:
        _reset_store(db)
    engine = make_engine(db)
    names = ["deny", "allow"] if args.scenario == "both" else [args.scenario]
    destination = "local-mock"
    if args.echo_model:
        completer, local = _echo_model, False
        destination = "local-echo"
    elif args.skip_model:
        completer, local = None, True
    elif llm.provider == "mock":
        completer, local = MockClient().answer, True
    else:
        from kognita import Run, create_all
        from kognita.models import RunRecord
        from eastwind.pack import _headers, seed_agent, register_usecases

        gateway_db = os.getenv("EASTWIND_LLM_GATEWAY_DB", "")
        if not gateway_db:
            raise ValueError("EASTWIND_LLM_GATEWAY_DB must name the gateway's SQLite store")
        if not Path(gateway_db).is_file():
            raise ValueError("the configured gateway store does not exist")
        if Path(gateway_db).resolve() == db.resolve():
            raise ValueError("the gateway store must be separate from the scenario store")
        gateway_engine = make_engine(Path(gateway_db))
        create_all(gateway_engine)
        with Session(gateway_engine) as session:
            seed_agent(session)
            register_usecases(session)
            identity = _headers(session, model=llm.model)
            run = Run()
            session.add(RunRecord(id=run.id))
            identity["run_id"] = run.id
            session.commit()
        gateway_engine.dispose()
        client = GatewayClient(llm, identity)

        def completer(prompt: str) -> str:
            result = client.complete([{"role": "user", "content": prompt}])
            return result["choices"][0]["message"].get("content") or ""

        local = False
        destination = llm.provider
    exit_code = 0
    print("Eastwind Private")
    print()
    for name in names:
        result = run_scenario(
            name,
            engine=engine,
            completer=completer,
            destination=destination,
            destination_is_local=local,
            call_model=not args.skip_model,
        )
        _print_result(result, db=db)
        if args.echo_model and name == "allow" and result.model_called:
            print(
                "Callable   local echo. OpenAI was not contacted. "
                "Destination local-echo is marked remote, so a C2 prompt is redacted "
                "before the callable runs - the same guard a call to api.openai.com uses."
            )
            print()
        if result.guard_denied:
            exit_code = 1
    return exit_code


def cmd_verify(args: argparse.Namespace) -> int:
    if args.file:
        payload = json.loads(Path(args.file).read_text())
        try:
            count = verify_export(payload)
        except ChainBreak as exc:
            print(f"BROKEN: {exc}", file=sys.stderr)
            return 1
        print(f"export verified: {count} events, head {payload.get('head_hash', '')[:16]}")
        return 0

    engine = make_engine(_db_path(args.db))
    with Session(engine) as session:
        try:
            count = verify_chain(session)
        except ChainBreak as exc:
            print(f"BROKEN: {exc}", file=sys.stderr)
            return 1
    print(f"evidence chain verified: {count} events")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    engine = make_engine(_db_path(args.db))
    with Session(engine) as session:
        payload = export_chain(session, correlation_id=args.correlation_id)
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(text)
        print(
            f"wrote {payload['event_count']} events "
            f"({payload['interest_count']} of interest) to {args.output}"
        )
    else:
        print(text)
    return 0


def cmd_evidence_verify(args: argparse.Namespace) -> int:
    if args.with_npm and not args.file:
        raise ValueError("--with-npm requires --file")
    code = cmd_verify(args)
    if not args.with_npm:
        return code
    try:
        npm_code = subprocess.run(
            ["npx", "--yes", "@kognita/verify@0.9.0", args.file], check=False
        ).returncode
    except FileNotFoundError as exc:
        raise ValueError("--with-npm requires Node 22 or later and npx") from exc
    return int(bool(code or npm_code))


def cmd_evidence_tamper(args: argparse.Namespace) -> int:
    if Path(args.file).resolve() == Path(args.output).resolve():
        raise ValueError("tampered output must be a different file")
    payload = json.loads(Path(args.file).read_text())
    if not payload.get("events"):
        raise ValueError("cannot tamper with an empty chain")
    payload["events"][0]["actor_id"] += "-edited"
    Path(args.output).write_text(json.dumps(payload, indent=2))
    print(f"wrote tampered export to {args.output}")
    return 0


def cmd_showcase(args: argparse.Namespace) -> int:
    root = _db_path(args.db)
    if args.scenario == "all":
        results = run_all(root)
    else:
        results = [run_named(args.scenario, root)]
    for result in results:
        print(result.text())
        print()
    return 0


def _pwm_graph(args: argparse.Namespace):
    from eastwind.pwm import create_demo_store, export_graph

    is_demo = args.db is None
    db = Path(args.db) if args.db else Path(".eastwind/pwm/demo.db")
    if not db.exists():
        if not is_demo:
            raise ValueError(f"PWM source store does not exist: {db}")
        create_demo_store(db)
    engine = make_engine(db)
    try:
        with Session(engine) as session:
            return export_graph(session, demo_profile=is_demo or args.demo_profile,
                                include_evidence=not args.no_evidence)
    finally:
        engine.dispose()


def cmd_pwm_export(args: argparse.Namespace) -> int:
    graph = _pwm_graph(args)
    rdf = graph.serialize(format="turtle")
    if args.output:
        Path(args.output).write_text(rdf, encoding="utf-8")
        print(f"wrote {len(graph)} RDF triples to {args.output}")
    else:
        print(rdf, end="")
    return 0


def cmd_pwm_validate(args: argparse.Namespace) -> int:
    from rdflib import Graph
    from eastwind.pwm import validate_graph

    if args.input and args.file:
        raise ValueError("provide one RDF input")
    input_path = args.input or args.file
    if input_path and args.db:
        raise ValueError("provide an RDF input or --db, not both")
    graph = Graph().parse(input_path) if input_path else _pwm_graph(args)
    conforms, report = validate_graph(graph)
    print(report, end="" if report.endswith("\n") else "\n")
    return 0 if conforms else 1


def cmd_workflow(args: argparse.Namespace) -> int:
    from eastwind.agents.workflows import WORKFLOWS, run_workflow
    from eastwind.llm import Settings

    settings = Settings.from_env(args.llm)
    if settings.provider != "mock":
        raise ValueError("wealth workflows currently require the offline mock model")
    names = list(WORKFLOWS) if args.name == "all" else [args.name]
    for name in names:
        options = {}
        if name == "client-review":
            options["role"] = args.role
        elif name == "suitability":
            options["product_id"] = args.product
        elif name == "research":
            options["source_id"] = args.source
        print(run_workflow(name, Path(args.db), **options).text())
    return 0


def cmd_anthropic_bridge(args: argparse.Namespace) -> int:
    from eastwind.llm.bridge import serve

    serve(args.port, args.alias, os.getenv("EASTWIND_ANTHROPIC_BRIDGE_TOKEN", ""),
          os.getenv("ANTHROPIC_API_KEY", ""))
    return 0


def cmd_mock_serve(args: argparse.Namespace) -> int:
    from eastwind.llm.server import serve

    print(f"Mock LLM listening on http://{args.host}:{args.port}", flush=True)
    serve(args.host, args.port)
    return 0


def cmd_admin(args: argparse.Namespace) -> int:
    import ipaddress
    import secrets

    import uvicorn
    from eastwind.admin import create_app

    try:
        local = args.host == "localhost" or ipaddress.ip_address(args.host).is_loopback
    except ValueError:
        local = False
    if not local:
        raise ValueError("admin must bind to a loopback address")
    token = os.environ.get("EASTWIND_ADMIN_TOKEN") or secrets.token_urlsafe(32)
    if not os.environ.get("EASTWIND_ADMIN_TOKEN"):
        print(f"Generated local admin token: {token}", flush=True)
    print(f"Eastwind Admin: http://{args.host}:{args.port}", flush=True)
    uvicorn.run(create_app(Path(args.db), token), host=args.host, port=args.port, access_log=False)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eastwind",
        description="Eastwind Private eligibility decisions, before retrieval or a model call.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    admin = sub.add_parser("admin", help="serve the local administration UI")
    admin.add_argument("--host", default="127.0.0.1")
    admin.add_argument("--port", type=int, default=8090)
    admin.add_argument("--db", default=".eastwind/admin", help="directory for admin stores")
    admin.set_defaults(func=cmd_admin)

    pwm = sub.add_parser("pwm", help="export and validate PWM 0.10 RDF")
    pwm_sub = pwm.add_subparsers(dest="pwm_command", required=True)
    pwm_export = pwm_sub.add_parser("export")
    pwm_export.add_argument("--db", help="existing Kognita SQLite store")
    pwm_export.add_argument("--demo-profile", action="store_true", help="include recorded synthetic demo declarations")
    pwm_export.add_argument("--no-evidence", action="store_true")
    pwm_export.add_argument("-o", "--output", help="write Turtle to this file")
    pwm_export.set_defaults(func=cmd_pwm_export)
    pwm_validate = pwm_sub.add_parser("validate")
    pwm_validate.add_argument("input", nargs="?", help="RDF file to validate")
    pwm_validate.add_argument("--file", help="RDF file to validate")
    pwm_validate.add_argument("--db", help="existing Kognita SQLite store")
    pwm_validate.add_argument("--demo-profile", action="store_true")
    pwm_validate.add_argument("--no-evidence", action="store_true")
    pwm_validate.set_defaults(func=cmd_pwm_validate)

    from eastwind.agents.workflows import WORKFLOWS
    workflow = sub.add_parser("workflow", help="run synthetic wealth agent workflows")
    workflow.add_argument("name", choices=[*WORKFLOWS, "all"])
    workflow.add_argument("--db", default=".eastwind/workflows", help="directory for workflow stores")
    workflow.add_argument("--llm", choices=["mock", "openai", "anthropic", "xai", "ollama", "openai-compatible"])
    workflow.add_argument("--role", choices=["agent", "relationship_manager", "visitor"], default="agent")
    workflow.add_argument("--product", choices=["INS-MMF", "INS-HK-NOTE"], default="INS-MMF")
    workflow.add_argument("--source", default="eastwind-house-view")
    workflow.set_defaults(func=cmd_workflow)

    bridge = sub.add_parser("anthropic-bridge", help="serve the native Anthropic adapter behind Kognita")
    bridge_sub = bridge.add_subparsers(dest="bridge_command", required=True)
    bridge_serve = bridge_sub.add_parser("serve")
    bridge_serve.add_argument("--alias", default="127.0.0.2")
    bridge_serve.add_argument("--port", type=int, default=8093)
    bridge_serve.set_defaults(func=cmd_anthropic_bridge)

    mock = sub.add_parser("mock-llm", help="run the local deterministic model service")
    mock_sub = mock.add_subparsers(dest="mock_command", required=True)
    mock_serve = mock_sub.add_parser("serve")
    mock_serve.add_argument("--host", default="127.0.0.1")
    mock_serve.add_argument("--port", type=int, default=8091)
    mock_serve.set_defaults(func=cmd_mock_serve)

    doctor = sub.add_parser("doctor", help="show kognita, the OpenAI SDK, and whether a key is set")
    doctor.set_defaults(func=cmd_doctor)

    run = sub.add_parser("run", help="run the ALLOW scenario, the DENY scenario, or both")
    run.add_argument("scenario", choices=["allow", "deny", "both"])
    run.add_argument("--db", default=str(DEFAULT_DB), help="SQLite evidence store")
    run.add_argument("--fresh", action="store_true", help="delete the store before running")
    model_flags = run.add_mutually_exclusive_group()
    model_flags.add_argument(
        "--skip-model",
        action="store_true",
        help="stop after a permitted retrieval; do not call OpenAI",
    )
    model_flags.add_argument(
        "--echo-model",
        action="store_true",
        help="on ALLOW, send the prompt through the guard to a local echo instead of OpenAI",
    )
    run.add_argument("--llm", choices=["mock", "openai", "anthropic", "xai", "ollama", "openai-compatible"])
    run.set_defaults(func=cmd_run)

    verify = sub.add_parser("verify", help="verify the evidence chain, or an exported file")
    verify.add_argument("--db", default=str(DEFAULT_DB))
    verify.add_argument("--file", help="verify an exported JSON artifact instead of the store")
    verify.set_defaults(func=cmd_verify)

    export = sub.add_parser("export", help="write a portable evidence artifact")
    export.add_argument("--db", default=str(DEFAULT_DB))
    export.add_argument("--correlation-id", help="mark one request as of interest")
    export.add_argument("-o", "--output", help="write to a file instead of stdout")
    export.set_defaults(func=cmd_export)

    evidence = sub.add_parser("evidence", help="export and verify portable evidence")
    evidence_sub = evidence.add_subparsers(dest="evidence_command", required=True)
    evidence_export = evidence_sub.add_parser("export")
    evidence_export.add_argument("--db", default=str(DEFAULT_DB))
    evidence_export.add_argument("--correlation-id")
    evidence_export.add_argument("-o", "--output")
    evidence_export.set_defaults(func=cmd_export)
    evidence_verify = evidence_sub.add_parser("verify")
    evidence_verify.add_argument("--db", default=str(DEFAULT_DB))
    evidence_verify.add_argument("--file")
    evidence_verify.add_argument("--with-npm", action="store_true")
    evidence_verify.set_defaults(func=cmd_evidence_verify)
    evidence_tamper = evidence_sub.add_parser("tamper")
    evidence_tamper.add_argument("--file", required=True)
    evidence_tamper.add_argument("-o", "--output", required=True)
    evidence_tamper.set_defaults(func=cmd_evidence_tamper)

    showcase = sub.add_parser(
        "showcase",
        help="run one kognita scenario (0.3 and 0.4 features), or all of them",
    )
    showcase.add_argument(
        "scenario",
        choices=[*SCENARIO_ORDER, "all"],
        help="scenario name, or all",
    )
    showcase.add_argument(
        "--db",
        default=str(Path(".eastwind/showcase")),
        help="directory (or .db path) for the scenario stores",
    )
    showcase.set_defaults(func=cmd_showcase)

    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
