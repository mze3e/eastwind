"""Command line for the Eastwind Private workshop demo."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlmodel import Session

from kognita import __version__ as kognita_version
from kognita import export_chain, make_engine, verify_chain, verify_export
from kognita.evidence import ChainBreak
from kognita.vocabulary import CheckResult

from eastwind import __version__
from eastwind.openai_chat import DEFAULT_MODEL, OpenAIChat
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
    print(f"Scenario  {scenario.name} — {scenario.title}")
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
        print(f"Model call not made — {reason}")
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
        print("openai sdk                not installed (pip install 'kognita[openai]')")
    return 0


def _completer_for(call_model: bool) -> tuple[OpenAIChat | None, bool]:
    if not call_model:
        return None, False
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return None, False
    chat = OpenAIChat(api_key=key, model=os.environ.get("OPENAI_MODEL", DEFAULT_MODEL))
    return chat, chat.destination_is_local


def cmd_run(args: argparse.Namespace) -> int:
    db = _db_path(args.db)
    if args.fresh:
        _reset_store(db)
    engine = make_engine(db)
    names = ["deny", "allow"] if args.scenario == "both" else [args.scenario]
    # Build the client once. DENY never calls it. A missing key leaves it None.
    destination = "api.openai.com"
    if args.echo_model:
        completer, local = _echo_model, False
        destination = "local-echo"
    else:
        completer, local = _completer_for(not args.skip_model)
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
                "before the callable runs — the same guard a call to api.openai.com uses."
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eastwind",
        description="Eastwind Private eligibility decisions, before retrieval or a model call.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

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

    showcase = sub.add_parser(
        "showcase",
        help="run one kognita 0.3 scenario, or all of them",
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
