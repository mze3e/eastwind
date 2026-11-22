"""Local, server-rendered administration for the synthetic wealth demo."""
from __future__ import annotations

import copy
import hmac
import json
from contextlib import asynccontextmanager
from html import escape
from pathlib import Path
from urllib.parse import parse_qs
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

from eastwind.agents.data import MANDATE, ROLE_FIELDS, SOURCES
from eastwind.agents.workflows import APPROVER, WORKFLOWS, WealthAgent, client_review
from eastwind.pack import AGENT_NAME, AGENT_OWNER
from eastwind.pwm import create_demo_store, export_graph, validate_graph


def _e(value) -> str:
    return escape(str(value), quote=True)


def _json(value) -> str:
    return _e(json.dumps(value, indent=2, default=str, sort_keys=True))


def _table(headers, rows) -> str:
    head = ''.join(f'<th>{_e(value)}</th>' for value in headers)
    body = ''.join('<tr>' + ''.join(f'<td>{_e(value)}</td>' for value in row) + '</tr>' for row in rows)
    return f'<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def _form(action: str, fields: str, button: str) -> str:
    return (f'<form method="post" action="{_e(action)}">{fields}'
            '<label>Admin token <input type="password" name="token" required autocomplete="off"></label> '
            f'<button type="submit">{_e(button)}</button></form>')


def _input(name: str, label: str, value: str = '') -> str:
    return f'<label>{_e(label)} <input name="{_e(name)}" value="{_e(value)}" required></label> '


def _select(name: str, values) -> str:
    options = ''.join(f'<option value="{_e(value)}">{_e(value)}</option>' for value in values)
    return f'<label>{_e(name.title())} <select name="{_e(name)}">{options}</select></label> '


def _page(title: str, content: str, status: int = 200) -> HTMLResponse:
    links = [('Dashboard', '/'), ('Agents', '/agents'), ('Policies', '/policies'),
             ('Approvals', '/approvals'), ('Kill switch', '/kill-switch'), ('Budgets', '/budgets'),
             ('Evidence', '/evidence'), ('Replay', '/replay'), ('Reconstruction', '/reconstruction'),
             ('PWM', '/pwm'), ('Workflows', '/workflows'), ('Tour', '/tour')]
    nav = ' '.join(f'<a href="{url}">{label}</a>' for label, url in links)
    return HTMLResponse(f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{_e(title)} | Eastwind</title>
<style>body{{font:16px system-ui;max-width:1150px;margin:auto;padding:1rem;color:#162839}}
nav{{display:flex;flex-wrap:wrap;gap:.8rem}}a{{color:#145f78}}table{{border-collapse:collapse;width:100%;margin:1em 0}}
th,td{{text-align:left;border:1px solid #ccd7dc;padding:.45em;vertical-align:top}}th{{background:#eaf1f3}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f5f6;padding:1em}}form{{margin:1em 0;padding:1em;background:#eef5f4}}
input,select,button{{font:inherit;margin:.3em}}button{{cursor:pointer}} .note{{color:#405966}}</style></head>
<body><header><h1>Eastwind Admin</h1><nav>{nav}</nav></header><main><h2>{_e(title)}</h2>{content}</main></body></html>''', status_code=status,
        headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                 'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"})


def create_app(root: Path, token: str) -> FastAPI:
    """Create a local app with persistent records under root and a required action token."""
    if not token:
        raise ValueError('admin token must not be empty')
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    db = root / 'admin.db'
    agent = WealthAgent(db)
    agent.engine.dispose()
    demo_db = root / 'pwm-demo.db'
    if not demo_db.exists():
        create_demo_store(demo_db)
    from kognita import make_engine
    engine = make_engine(db)
    demo_engine = make_engine(demo_db)

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

    async def checked(request: Request) -> dict[str, str]:
        if request.headers.get('content-type', '').split(';')[0] != 'application/x-www-form-urlencoded':
            raise HTTPException(415, 'Expected a form')
        body = await request.body()
        if len(body) > 16384:
            raise HTTPException(413, 'Form too large')
        data = parse_qs(body.decode('utf-8'), keep_blank_values=True, max_num_fields=20)
        if any(len(values) != 1 for values in data.values()):
            raise HTTPException(400, 'Repeated form field')
        values = {key: items[0] for key, items in data.items()}
        supplied = values.pop('token', '')
        if not hmac.compare_digest(supplied.encode(), token.encode()):
            raise HTTPException(403, 'Invalid admin token')
        return values

    @app.get('/', response_class=HTMLResponse)
    def dashboard():
        with Session(engine) as session:
            current = session.exec(select(Agent).where(Agent.name == AGENT_NAME)).one()
            try:
                chain = f'{verify_chain(session)} verified evidence events'
            except ChainBreak as exc:
                chain = f'evidence chain broken: {exc}'
            pending = sum(1 for row in session.exec(select(RunRecord)).all() if row.continuation_hash)
        return _page('Dashboard', f'<p>Synthetic data only. Agent: {_e(current.name)}. Kill switch: '
                     f'{"engaged" if current.kill_switch else "off"}. Suspended runs: {pending}. '
                     f'{_e(chain)}.</p><p>To see permitted context, mandated action, '
                     '<a href="/tour">and a verifiable record, open Tour: Permitted context, mandated action, provable record</a>.</p>')

    @app.get('/agents', response_class=HTMLResponse)
    def agents():
        with Session(engine) as session:
            rows = session.exec(select(Agent)).all()
            body = ''
            for row in rows:
                tools = ', '.join(k for k in (row.tool_allowlist or {}) if not k.startswith('_'))
                body += _table(['Field', 'Value'], [('Agent', row.name), ('Mandate and use cases', row.purpose),
                    ('Tools', tools), ('Data scopes', json.dumps(row.field_allowlist)),
                    ('Permitted systems', ', '.join(row.permitted_systems or [])),
                    ('Autonomy level', f'{row.autonomy_level} (Kognita registered level)'),
                    ('Proposal approver', APPROVER), ('Risk tier', row.materiality_tier),
                    ('Risk class', row.risk_class), ('Hard limits', json.dumps(row.blast_radius or {})),
                    ('Owner', row.owner_exec), ('Synthetic client mandate', json.dumps(MANDATE))])
                body += '<p class="note">The registered level is separate from the human approval policy for trade proposals.</p>'
        return _page('Agent registry', body)

    @app.get('/policies', response_class=HTMLResponse)
    def policies(role: str = 'agent'):
        if role not in ROLE_FIELDS:
            raise HTTPException(400, 'Unknown role')
        with Session(engine) as session:
            rows = session.exec(select(Policy)).all()
            policies_table = _table(['Regime', 'Rule', 'Citation'], [(p.regime, p.rule_type, p.citation) for p in rows])
        from urllib.parse import urlencode
        roles = ' | '.join(f'<a href="/policies?{urlencode({"role": r})}">{_e(r)}</a>' for r in ROLE_FIELDS)
        fields = _table(['Client profile field', role], ROLE_FIELDS[role].items())
        access = {
            'relationship_manager': ['visible and masked fields', 'visible', 'visible', 'visible'],
            'agent': ['visible, masked and denied fields', 'visible holdings, masked account ID', 'visible', 'visible'],
            'visitor': ['denied', 'denied', 'denied', 'denied'],
        }
        source_access = _table(['Source', 'Access for ' + role], zip(SOURCES, access[role], strict=True))
        sources = _table(['Source', 'Owner', 'Classification', 'Lineage', 'Version', 'Freshness', 'Permitted purposes'],
                         [(name, v['owner'], v['classification'], v['lineage'], v['version'],
                           f"{v['effective']} to {v.get('expiry', 'not specified')}", ', '.join(v['purposes']))
                          for name, v in SOURCES.items()])
        return _page('Policies and entitlements', f'<p>Role: {roles}</p>{source_access}{fields}'
                     '<p>Account identifier: visible to the relationship manager, masked for the agent, denied to a visitor. '
                     'Product and house-view access is subject to the workflow policy and source checks.</p>'
                     f'<h3>Sources</h3>{sources}<h3>Policy register</h3>{policies_table}')

    @app.get('/approvals', response_class=HTMLResponse)
    def approvals():
        with Session(engine) as session:
            runs = session.exec(select(RunRecord)).all()
            entries = []
            for run in runs:
                if run.continuation_hash:
                    for approval_id in run.approvals_pending:
                        item = session.get(Approval, approval_id)
                        if item:
                            entries.append((run.id, item.id, item.status.value, item.requester_id, item.expires_at))
        forms = ''.join(_form('/approvals/resolve', f'<input type="hidden" name="run" value="{_e(run)}">'
                              f'<input type="hidden" name="approval" value="{_e(aid)}">'
                              + _select('resolution', ['approve', 'deny']), f'Resolve approval {aid}')
                        for run, aid, *_ in entries)
        forms += ''.join(_form('/approvals/grant', f'<input type="hidden" name="run" value="{_e(run)}">'
                               f'<input type="hidden" name="approval" value="{_e(aid)}">',
                               f'Approve without release {aid}')
                         for run, aid, status, *_ in entries if status == 'PENDING')
        return _page('Approvals queue', '<p>Run the rebalance workflow to create a suspended proposal. '
                     'The named synthetic risk officer resolves each request. Release checks run again. '
                     'To test a stop after approval, approve without release, engage the switch, then resolve with approve.</p>'
                     + _table(['Run', 'Approval', 'Status', 'Requester', 'Expires'], entries) + forms)

    @app.post('/approvals/grant', response_class=HTMLResponse)
    async def grant_without_release(request: Request):
        values = await checked(request)
        try:
            approval_id = int(values.get('approval', ''))
        except ValueError:
            raise HTTPException(400, 'Invalid approval')
        with Session(engine) as session:
            run = session.get(RunRecord, values.get('run', ''))
            item = session.get(Approval, approval_id)
            if not run or not run.continuation_hash or approval_id not in run.approvals_pending or not item:
                raise HTTPException(404, 'Suspended approval not found')
            decision = session.get(GovernanceDecision, item.decision_id)
            if not decision or item.status.value != 'PENDING':
                raise HTTPException(409, 'Approval is not pending')
            from kognita import EvidenceWriter
            try:
                grant(session, item, approver_name=APPROVER, evidence=EvidenceWriter(engine),
                      correlation_id=decision.request_id)
            except ApprovalError as exc:
                raise HTTPException(409, str(exc)) from exc
            session.commit()
        return _page('Approval recorded', '<p>Approval recorded. The run is still suspended and release checks will run again.</p><a href="/approvals">Back to queue</a>')

    @app.post('/approvals/resolve', response_class=HTMLResponse)
    async def resolve(request: Request):
        values = await checked(request)
        if values.get('resolution') not in {'approve', 'deny'}:
            raise HTTPException(400, 'Unknown resolution')
        try:
            approval_id = int(values.get('approval', ''))
        except ValueError:
            raise HTTPException(400, 'Invalid approval')
        worker = WealthAgent(db)
        try:
            with Session(worker.engine) as session:
                run = session.get(RunRecord, values.get('run', ''))
                if not run or not run.continuation_hash or approval_id not in run.approvals_pending:
                    raise HTTPException(404, 'Suspended approval not found')
                try:
                    result = continue_run(session, run.id, {approval_id: values['resolution'] == 'approve'},
                                          evidence=worker.writer, registry=worker.registry, approver_name=APPROVER)
                except ApprovalError as exc:
                    raise HTTPException(409, str(exc)) from exc
                session.commit()
                output = {'outcome': result.outcome.value, 'data': result.data,
                          'executed': result.data is not None, 'approver': APPROVER}
        finally:
            worker.engine.dispose()
        return _page('Approval resolved', '<pre>' + _json(output) + '</pre><a href="/approvals">Back to queue</a>')

    @app.get('/kill-switch', response_class=HTMLResponse)
    def kill_switch():
        with Session(engine) as session:
            row = session.exec(select(Agent).where(Agent.name == AGENT_NAME)).one()
            state = 'engaged' if row.kill_switch else 'off'
        form = _form('/kill-switch', _select('state', ['engage', 'release']), 'Update kill switch')
        return _page('Kill switch', f'<p>Current state: {state}. This switch governs the admin store, including pending approvals.</p>{form}')

    @app.post('/kill-switch', response_class=HTMLResponse)
    async def change_switch(request: Request):
        values = await checked(request)
        if values.get('state') not in {'engage', 'release'}:
            raise HTTPException(400, 'Unknown switch state')
        with Session(engine) as session:
            from kognita import EvidenceWriter
            set_kill_switch(session, AGENT_NAME, values['state'] == 'engage', evidence=EvidenceWriter(engine),
                            actor_id=AGENT_OWNER, reason='Local admin action')
            session.commit()
        return kill_switch()

    @app.get('/budgets', response_class=HTMLResponse)
    def budgets():
        with Session(engine) as session:
            rows = session.exec(select(RunRecord)).all()
            table = _table(['Run', 'Calls used', 'Maximum calls', 'Tokens used', 'Maximum tokens', 'Cost used', 'Maximum cost'],
                           [(r.id, r.calls_used, r.max_calls, r.tokens_used, r.max_tokens, r.cost_usd_used, r.max_cost_usd) for r in rows])
        return _page('Run budgets', '<p>Choose a call limit when running client review. A limit of 2 demonstrates exhaustion.</p>' + table)

    @app.get('/evidence', response_class=HTMLResponse)
    def evidence():
        with Session(engine) as session:
            try:
                count = verify_chain(session)
                verification = f'Chain verified: {count} events'
            except ChainBreak as exc:
                verification = f'Chain broken: {exc}'
            events = session.exec(select(EvidenceEvent).order_by(EvidenceEvent.sequence.desc()).limit(100)).all()
            rows = [(e.sequence, e.event_type.value, e.actor_id, e.correlation_id, e.event_hash) for e in events]
        form = _form('/evidence/tamper', _input('actor_id', 'Replacement actor in copy', 'edited-actor'),
                     'Verify an edited copy')
        detail = '<form method="get" action="/evidence/event">' + _input('sequence', 'Event sequence') + '<button>View event</button></form>'
        return _page('Evidence explorer', f'<p>{_e(verification)}. Showing up to 100 latest events. '
                     '<a href="/evidence/export">Download evidence JSON</a>.</p>'
                     '<p>The tamper demo edits a copy and verifies it; the source chain is untouched.</p>' + detail + form
                     + _table(['Sequence', 'Type', 'Actor', 'Correlation', 'Hash'], rows))

    @app.get('/evidence/event', response_class=HTMLResponse)
    def evidence_event(sequence: int):
        with Session(engine) as session:
            event = session.exec(select(EvidenceEvent).where(EvidenceEvent.sequence == sequence)).first()
            if event is None:
                raise HTTPException(404, 'Evidence event not found')
            details = {'sequence': event.sequence, 'event_type': event.event_type.value,
                       'actor_type': event.actor_type.value, 'actor_id': event.actor_id,
                       'correlation_id': event.correlation_id, 'recorded_at': event.recorded_at,
                       'payload': event.payload, 'payload_hash': event.payload_hash,
                       'previous_hash': event.prev_hash, 'event_hash': event.event_hash}
        return _page('Evidence event', '<pre>' + _json(details) + '</pre>')

    @app.get('/evidence/export')
    def evidence_export():
        with Session(engine) as session:
            verify_chain(session)
            payload = export_chain(session)
        return Response(json.dumps(payload, indent=2), media_type='application/json',
                        headers={'Content-Disposition': 'attachment; filename="evidence.json"', 'Cache-Control': 'no-store'})

    @app.post('/evidence/tamper', response_class=HTMLResponse)
    async def tamper(request: Request):
        values = await checked(request)
        with Session(engine) as session:
            verify_chain(session)
            artifact = copy.deepcopy(export_chain(session))
        if not artifact['events']:
            raise HTTPException(409, 'No evidence to edit')
        replacement = values.get('actor_id', 'edited-actor')
        if not replacement or replacement == artifact['events'][0]['actor_id']:
            raise HTTPException(400, 'Enter a different actor')
        artifact['events'][0]['actor_id'] = replacement
        try:
            verify_export(artifact)
        except (ChainBreak, ValueError) as exc:
            return _page('Tamper demonstration', '<p>Edited copy failed Python verification, as expected.</p><pre>' + _e(exc) + '</pre>')
        return _page('Tamper demonstration', '<p>Unexpected: edited copy passed verification.</p>', 500)

    @app.get('/replay', response_class=HTMLResponse)
    def replay_page():
        with Session(engine) as session:
            rows = session.exec(select(GovernanceDecision).order_by(GovernanceDecision.id.desc()).limit(100)).all()
            table = _table(['Request', 'Tool', 'Outcome'], [(r.request_id, r.tool, r.outcome.value) for r in rows])
        return _page('Replay', '<p>Replay a recorded decision against its pinned inputs.</p>'
                     + _form('/replay', _input('request_id', 'Request ID'), 'Replay') + table)

    @app.post('/replay', response_class=HTMLResponse)
    async def replay_action(request: Request):
        values = await checked(request)
        with Session(engine) as session:
            try:
                result = replay_decision(session, values.get('request_id', ''))
                output = {'request_id': result.request_id, 'outcome': result.outcome.value,
                          'checks': [{'check': c.check, 'result': c.result.value, 'citation': c.citation} for c in result.checks]}
            except Exception as exc:
                return _page('Replay failed', '<pre>' + _e(exc) + '</pre>', 400)
        return _page('Replay result', '<pre>' + _json(output) + '</pre>')

    @app.get('/reconstruction', response_class=HTMLResponse)
    def reconstruction():
        from kognita.models import Interaction
        with Session(engine) as session:
            rows = session.exec(select(Interaction)).all()
            table = _table(['Interaction', 'Client', 'Use case'], [(r.id, r.client_id, r.use_case) for r in rows])
        return _page('Reconstruction reports', '<p>Reports identify missing evidence as well as recorded facts.</p>'
                     + _form('/reconstruction', _input('interaction_id', 'Interaction or correlation ID'), 'Reconstruct') + table)

    @app.post('/reconstruction', response_class=HTMLResponse)
    async def reconstruct_action(request: Request):
        values = await checked(request)
        with Session(engine) as session:
            report = reconstruct(session, values.get('interaction_id', ''))
        return _page('Reconstruction report', '<pre>' + _json(report) + '</pre>')

    @app.get('/pwm', response_class=HTMLResponse)
    def pwm_page():
        return _page('PWM export and validation', '<p>The demo export includes explicit synthetic profile declarations. '
                     'The admin store export includes only its recorded fields and can fail validation when metadata is missing. '
                     'SHACL checks structure, not cryptographic signatures.</p><p><a href="/pwm/export?source=demo">Download demo RDF</a> | '
                     '<a href="/pwm/export?source=admin">Download admin store RDF</a></p>'
                     + _form('/pwm/validate', _select('source', ['demo', 'admin']), 'Validate RDF'))

    @app.get('/pwm/export')
    def pwm_export(source: str = 'demo'):
        if source not in {'demo', 'admin'}:
            raise HTTPException(400, 'Unknown PWM source')
        with Session(demo_engine if source == 'demo' else engine) as session:
            rdf = export_graph(session, demo_profile=source == 'demo').serialize(format='turtle')
        return Response(rdf, media_type='text/turtle', headers={'Content-Disposition': 'attachment; filename="eastwind-pwm.ttl"', 'Cache-Control': 'no-store'})

    @app.post('/pwm/validate', response_class=HTMLResponse)
    async def pwm_validate(request: Request):
        values = await checked(request)
        source = values.get('source', 'demo')
        if source not in {'demo', 'admin'}:
            raise HTTPException(400, 'Unknown PWM source')
        with Session(demo_engine if source == 'demo' else engine) as session:
            graph = export_graph(session, demo_profile=source == 'demo')
        conforms, report = validate_graph(graph)
        return _page('PWM validation', f'<p>Conforms: {_e(conforms)}</p><pre>{_e(report)}</pre>')

    @app.get('/workflows', response_class=HTMLResponse)
    def workflows():
        fields = (_select('workflow', WORKFLOWS) + _select('role', ROLE_FIELDS)
                  + _input('max_calls', 'Client review call budget', '4'))
        return _page('Run a workflow', '<p>Client review, suitability, research, egress, budget and replay use the admin store. '
                     'Rebalance suspends for the approvals queue. Kill-switch, MCP and degraded-mode drills use isolated simulation stores.</p>'
                     + _form('/workflows', fields, 'Run workflow'))

    @app.post('/workflows', response_class=HTMLResponse)
    async def workflow_action(request: Request):
        values = await checked(request)
        name = values.get('workflow', '')
        role = values.get('role', 'agent')
        if name not in WORKFLOWS or role not in ROLE_FIELDS:
            raise HTTPException(400, 'Unknown workflow or role')
        try:
            max_calls = int(values.get('max_calls', '4'))
            if not 1 <= max_calls <= 100:
                raise ValueError('Call budget must be between 1 and 100')
            if name == 'rebalance':
                worker = WealthAgent(db)
                try:
                    with Session(worker.engine) as session:
                        run = Run(max_calls=4)
                        steps = worker.execute_plan(session, 'rebalance', run=run, arguments={'case': str(uuid4())})
                        held = steps[-1]
                        if not held.approval_required:
                            output = {'outcome': held.outcome.value, 'suspended': False, 'executed': held.data is not None}
                        else:
                            approval = session.exec(select(Approval).where(Approval.decision_id == held.evaluation.decision_id)).one()
                            output = {'outcome': held.outcome.value, 'suspended': True, 'run_id': run.id, 'approval_id': approval.id}
                        session.commit()
                finally:
                    worker.engine.dispose()
            elif name == 'client-review':
                output = json.loads(client_review(db, role=role, max_calls=max_calls).text())
            else:
                path = root / 'drills' / f'{name}.db' if name in {'kill-switch', 'mcp', 'degraded'} else db
                output = json.loads(WORKFLOWS[name](path).text())
        except (ValueError, RuntimeError) as exc:
            return _page('Workflow failed', '<pre>' + _e(exc) + '</pre>', 400)
        return _page('Workflow result', '<pre>' + _json(output) + '</pre><p><a href="/approvals">Approvals queue</a> | '
                     '<a href="/evidence">Evidence</a> | <a href="/workflows">Run another workflow</a></p>')

    @app.get('/tour', response_class=HTMLResponse)
    def tour():
        return _page('Tour: Permitted context, mandated action, provable record', '''
<p>Follow these three steps with synthetic data:</p><ol>
<li><strong>Permitted context.</strong> Open <a href="/policies">Policies and entitlements</a>, compare the relationship manager and agent role views, then run <a href="/workflows">client-review</a>. The agent receives masked or denied fields and policy checks precede retrieval. Run research to see approved-source checks.</li>
<li><strong>Mandated action.</strong> Inspect the <a href="/agents">agent registry</a> and run the rebalance workflow. In <a href="/approvals">Approvals</a>, approve or deny its suspended proposal. To test release controls, suspend another proposal, approve without release, engage the <a href="/kill-switch">kill switch</a>, then resolve it with approve: the action is withheld. Release the switch afterward.</li>
<li><strong>Provable record.</strong> Open <a href="/evidence">Evidence</a> to verify the chain and edit a copy in the tamper demo. Use <a href="/replay">Replay</a> for a decision and <a href="/reconstruction">Reconstruction</a> for a review interaction. The evidence is a set of linked events, and fields that were not recorded remain absent.</li>
</ol><p>See <a href="/budgets">Run budgets</a> and <a href="/pwm">PWM</a> for the remaining controls and register export.</p>''')

    return app
