"""Offline 0.5.1 scenarios using the public kognita control boundaries."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from kognita import (
    ActorType, Classification, Envelope, EvidenceWriter, Run, ToolRegistry,
    apply_proposal_tool, decide, load_snapshot, propose_document, record,
    run_governed, verify_chain,
)
from kognita.authority import Delegation, delegate, grant_to
from kognita.credentials import issue, revoke, verify
from kognita.models import Agent, BlastRadius, EvidenceEvent, KnowledgeItem, Proposal, RunRecord
from kognita.registry import approve_deployment, register
from kognita.usecases import load_register

from eastwind.pack import AGENT_NAME, AGENT_OWNER, PURPOSES, _access, _headers, client_envelope
from eastwind.showcase04 import PACK, RM, USECASE, _Story, _boundary, _seeded


def _configure(session: Session, writer: EvidenceWriter, **changes: Any) -> Agent:
    agent = session.exec(select(Agent).where(Agent.name == AGENT_NAME)).one()
    deployment = agent.tool_allowlist['_deployment']
    agent = register(session, name=agent.name, owner_exec=AGENT_OWNER,
                     version=agent.version, risk_class=agent.risk_class,
                     materiality_tier=agent.materiality_tier,
                     evidence=writer, actor_id=AGENT_OWNER, **changes)
    return approve_deployment(session, agent.name, deployment=deployment,
                              evidence=writer, actor_id=AGENT_OWNER)


def _permissions(session: Session) -> dict:
    agent = session.exec(select(Agent).where(Agent.name == AGENT_NAME)).one()
    return {k: dict(v) for k, v in agent.tool_allowlist.items() if not k.startswith('_')}


def _task(session: Session, writer: EvidenceWriter, env: Envelope, *,
          actions: tuple[str, ...] = ('read',), scope: dict | None = None) -> Envelope:
    """The authenticated host grants and attenuates an explicit human task."""
    now = datetime.now(timezone.utc)
    data = scope or {k: [v] for k, v in env.all_subjects().items()}
    data.setdefault('client', ['CL-1001'])
    for action in actions:
        grant_to(env.principal, action, timedelta(hours=2), data,
                 session=session, evidence=writer, actor_id=AGENT_OWNER, now=now)
    did = delegate(session, Delegation(
        human=env.principal, agent=AGENT_NAME, purpose=USECASE,
        client=data['client'][0], allowed_actions=list(actions), allowed_data=data,
        valid_from=now, valid_until=now + timedelta(hours=1), jurisdiction='SG',
        approval_threshold=actions[-1], task_ref='eligibility assessment',
    ), evidence=writer, actor_id=env.principal, now=now)
    credential = issue(session, AGENT_NAME, evidence=writer, actor_id=AGENT_OWNER)
    return replace(env, delegation_id=did, context={'_agent_credential': credential})


def _registry(*names: str, **metadata: Any) -> ToolRegistry:
    registry = ToolRegistry()
    for name in names or ('check_eligibility',):
        registry.register(name, lambda *_: 'House guidance noted.',
                          classification=Classification.C1, **metadata)
    return registry


def _call(session: Session, writer: EvidenceWriter, env: Envelope,
          *, registry: ToolRegistry | None = None, run: Run | None = None) -> Any:
    return run_governed(session, env, evidence=writer, registry=registry or _registry(env.tool),
                        pack=PACK, purposes=PURPOSES, run=run or Run())


def _decision(session: Session, env: Envelope) -> Any:
    subjects = PACK.load_subjects(env, session)
    return decide(env, load_snapshot(session), attributes=PACK.resolve_attributes(env, subjects),
                  subjects=subjects, rules=PACK.rules(), engages=PACK.engages,
                  purposes=PURPOSES, usecases=load_register(session))


def _show(story: _Story, label: str, result: Any, *, rules: tuple[str, ...]) -> None:
    evaluation = getattr(result, 'evaluation', result)
    story.fact(label + '_outcome', evaluation.outcome.value)
    checks = [c for c in evaluation.checks if c.check in rules]
    story.fact(label + '_checks', [c.to_dict() for c in checks])
    story.say(f'{label:<20} {evaluation.outcome.value}')
    for check in checks:
        story.say(f'cite    {check.check} {check.result.value}: {check.citation}')


def _finish(story: _Story, path: Path, session: Session) -> Any:
    story.fact('chain_length', verify_chain(session))
    session.commit()
    story.say(f'Store   {path}')
    return story.result


def scenario_autonomy(path: Path) -> Any:
    from kognita.autonomy import promote

    story = _Story('autonomy', 'autonomy levels and reviewed deployments')
    engine, writer = _seeded(path)
    with Session(engine) as session:
        env = _task(session, writer, client_envelope('check_eligibility'), actions=('read', 'analyse'))
        allowed = _call(session, writer, env)
        _show(story, 'allow', allowed, rules=('S1-IDENTITY', 'S1-DEPLOYMENT', 'S1-LEVEL'))
        permissions = _permissions(session)
        permissions['historical_eligibility'].update(verb='analyse', required_level=1, permissions=['analyse'])
        _configure(session, writer, tool_allowlist=permissions)
        denied = _call(session, writer, replace(env, tool='historical_eligibility'),
                       registry=_registry('historical_eligibility', verb='analyse', required_level=1))
        _show(story, 'deny', denied, rules=('S1-LEVEL',))
        try:
            promote(session, AGENT_NAME, evidence=writer, actor_id=AGENT_OWNER,
                    validator='Compliance Testing, Eastwind Private')
        except ValueError as exc:
            story.fact('promotion_refused', str(exc))
            story.say(f'promotion held   {exc}')
        story.say('L0 may read. L1 analysis needs earned promotion; an owner cannot simply raise the level.')
        return _finish(story, path, session)


def scenario_credentials(path: Path) -> Any:
    story = _Story('credentials', 'workload credentials bound to delegated tasks')
    engine, writer = _seeded(path)
    with Session(engine) as session:
        env = _access(session, client_envelope('check_eligibility'))
        secret = env.context['_agent_credential']
        story.fact('verified', verify(session, AGENT_NAME, secret))
        parent = Run(max_calls=10, max_tokens=1000, max_cost_usd=1.0, wall_clock_seconds=600)
        _show(story, 'allow', _call(session, writer, env, run=parent), rules=('S3-DELEGATION',))
        child = parent.delegate_to(AGENT_NAME, {
            'why': 'Read house guidance within the same registered workload',
            'allowed_actions': ['read'],
            'allowed_data': {'client': ['CL-1001'], 'instrument': ['INS-MMF']},
            'tools': ['check_eligibility'], 'autonomy_level': 0,
            'valid_until': datetime.now(timezone.utc) + timedelta(minutes=5),
            'max_calls': 2, 'max_tokens': 100, 'max_cost_usd': 0.1, 'wall_clock_seconds': 60,
        }, session=session, evidence=writer)
        transfer = next(e.payload for e in reversed(session.exec(select(EvidenceEvent).order_by(EvidenceEvent.sequence)).all())
                        if e.payload.get('action') == 'AUTHORITY_TRANSFERRED')
        child_env = replace(env, delegation_id=transfer['id'])
        _show(story, 'delegated', _call(session, writer, child_env, run=child), rules=('S6B-RUN-ISOLATION', 'S3-DELEGATION'))
        story.fact('parent_calls_reserved', parent.max_calls)
        story.say('bounded child task   cite S6B-DELEGATION; the parent reserves its capacity')
        missing = _call(session, writer, replace(env, context={}))
        _show(story, 'missing', missing, rules=('S2-CREDENTIAL',))
        revoke(session, AGENT_NAME, secret, evidence=writer, actor_id=AGENT_OWNER)
        story.fact('revoked_verified', verify(session, AGENT_NAME, secret))
        _show(story, 'deny', _call(session, writer, env), rules=('S2-CREDENTIAL',))
        story.say('The delegation is still named; a revoked workload secret cannot exercise it.')
        return _finish(story, path, session)


def scenario_authority(path: Path) -> Any:
    from kognita.authority import revoke as revoke_authority

    story = _Story('authority', 'human grants and attenuated delegated authority')
    engine, writer = _seeded(path)
    with Session(engine) as session:
        env = _access(session, client_envelope('check_eligibility'))
        _show(story, 'allow', _call(session, writer, env),
              rules=('S3-DELEGATION', 'S3-HUMAN-ENTITLEMENT'))
        now = datetime.now(timezone.utc)
        try:
            delegate(session, Delegation(human=RM, agent=AGENT_NAME, purpose=USECASE,
                client='CL-1001', allowed_actions=['execute'],
                allowed_data={'client': ['CL-1001']}, jurisdiction='SG',
                task_ref='eligibility assessment', valid_from=now,
                valid_until=now + timedelta(minutes=10)), evidence=writer, actor_id=RM, now=now)
        except ValueError as exc:
            story.fact('widening_refused', str(exc))
            story.say(f'widening refused  {exc}')
        revoke_authority(session, env.delegation_id, evidence=writer, actor_id=RM)
        _show(story, 'deny', _call(session, writer, env), rules=('S3-DELEGATION',))
        return _finish(story, path, session)


def scenario_blastradius(path: Path) -> Any:
    story = _Story('blastradius', 'independent action, product and transaction ceilings')
    engine, writer = _seeded(path)
    with Session(engine) as session:
        limits = BlastRadius(max_daily_actions=1, max_daily_transactions=0,
            products=['INS-MMF'], max_clients=1, jurisdictions=['SG'], execution_authority='none')
        _configure(session, writer, blast_radius=limits.model_dump(mode='json', exclude_none=True))
        env = _task(session, writer, replace(client_envelope('check_eligibility'),
            subjects={'product': 'INS-MMF'}), scope={'client': ['CL-1001'],
                'product': ['INS-MMF', 'INS-HK-NOTE']}, actions=('read', 'execute'))
        allowed = _call(session, writer, env)
        _show(story, 'allow', allowed, rules=('S4-DAILY-ACTIONS', 'S4-PRODUCTS', 'S4-DAILY-TRANSACTIONS'))
        _show(story, 'deny', _call(session, writer, env), rules=('S4-DAILY-ACTIONS',))
        wrong_product = _decision(session, replace(env, subjects={'product': 'INS-HK-NOTE'}))
        _show(story, 'product', wrong_product, rules=('S4-PRODUCTS',))
        permissions = _permissions(session)
        permissions['release_structured_note'].update(verb='execute', required_level=4, permissions=['execute'])
        _configure(session, writer, tool_allowlist=permissions)
        transaction = _decision(session, replace(env, tool='release_structured_note'))
        _show(story, 'transaction', transaction, rules=('S4-DAILY-TRANSACTIONS', 'S4-EXECUTION-AUTHORITY', 'S1-LEVEL'))
        story.say('A zero daily transaction ceiling independently denies execution; this read-only agent also lacks L4 authority.')
        return _finish(story, path, session)


def scenario_anomaly(path: Path) -> Any:
    story = _Story('anomaly', 'automatic containment and the kill switch')
    engine, writer = _seeded(path)
    with Session(engine) as session:
        permissions = _permissions(session)
        permissions.pop('offer_autocall')
        _configure(session, writer, tool_allowlist=permissions)
        env = _access(session, client_envelope('check_eligibility'))
        _show(story, 'allow', _call(session, writer, env), rules=('S1-LEVEL',))
        for _ in range(3):
            probe = _call(session, writer, replace(env, tool='offer_autocall'))
        _show(story, 'deny', probe, rules=('S6-PRIVILEGE-PROBING',))
        _show(story, 'stopped', _call(session, writer, env), rules=('KILL_SWITCH', 'S6-QUARANTINE', 'S2-CREDENTIAL'))
        agent = session.exec(select(Agent).where(Agent.name == AGENT_NAME)).one()
        story.fact('kill_switch', agent.kill_switch)
        story.fact('credential_live', verify(session, AGENT_NAME, env.context['_agent_credential']))
        events = session.exec(select(EvidenceEvent)).all()
        story.fact('containment_actions', [e.payload['action'] for e in events
            if e.payload.get('action', '').startswith('ANOMALY_')])
        return _finish(story, path, session)


def scenario_taint(path: Path) -> Any:
    story = _Story('taint', 'sticky client-data taint and public-content isolation')
    engine, writer = _seeded(path)
    with Session(engine) as session:
        permissions = _permissions(session)
        permissions['house_view']['client_data'] = True
        permissions['historical_eligibility']['public_content'] = True
        _configure(session, writer, tool_allowlist=permissions)
        env = _access(session, client_envelope('house_view'))
        run = Run()
        allowed = _call(session, writer, env, run=run, registry=_registry('house_view', client_data=True))
        _show(story, 'allow', allowed, rules=('S6B-RUN-ISOLATION',))
        public = replace(env, tool='historical_eligibility', subject_type=None, subject_id=None, subjects={})
        registry = _registry('historical_eligibility', public_content=True)
        _show(story, 'deny', _call(session, writer, public, run=run, registry=registry), rules=('S5-PUBLIC-CONTENT',))
        rotated = Run()
        _show(story, 'rotated', _call(session, writer, public, run=rotated, registry=registry), rules=('S5-PUBLIC-CONTENT',))
        story.fact('client_data', run.client_data)
        story.fact('rotated_client_data', rotated.client_data)
        story.fact('taint_citations', [e.payload['citation'] for e in session.exec(select(EvidenceEvent)).all()
            if e.payload.get('action') == 'CONTENT_TAINTED'])
        story.say('Removing client references or rotating the run does not clear workload provenance. cite S5-TAINT')
        return _finish(story, path, session)


def scenario_triggers(path: Path) -> Any:
    from kognita.gateway import ClientConfiguration, Gateway
    from eastwind.showcase import _Spy, _chat_body

    story = _Story('triggers', 'approved system triggers retain their system identity')
    engine, writer = _seeded(path)
    spy = _Spy(json.dumps({'model': 'eastwind-local', 'choices': [{'message': {'content': 'House guidance noted.'}}]}).encode())
    gateway = Gateway(engine=engine, evidence=writer, upstream='http://127.0.0.1:9',
        client=ClientConfiguration(principal=RM, purpose=USECASE,
                                   system_triggers=frozenset({'nightly-refresh'})),
        pack=PACK, purposes=PURPOSES, transport=spy)
    with Session(engine) as session:
        allowed = gateway.handle('POST', '/v1/chat/completions', {'system_trigger': 'nightly-refresh'},
                                 _chat_body('House guidance.'), session=session)
        denied = gateway.handle('POST', '/v1/chat/completions', {'system_trigger': 'unlisted-trigger'},
                                _chat_body('House guidance.'), session=session)
        _show(story, 'allow', allowed, rules=('SYSTEM_TRIGGER',))
        _show(story, 'deny', denied, rules=('SYSTEM_TRIGGER',))
        story.fact('forwarded', len(spy.calls))
        decisions = [e for e in session.exec(select(EvidenceEvent)).all()
                     if e.event_type == 'POLICY_DECISION']
        story.fact('actor', decisions[0].actor_type)
        story.fact('trigger_recorded', 'nightly-refresh' in json.dumps([e.payload for e in decisions]))
        return _finish(story, path, session)


def scenario_providerkey(path: Path) -> Any:
    from eastwind.local_servers import OpenAIStandIn, free_port, serve_in_thread, wait_for_port
    from eastwind.showcase import _chat_body, _kognita_cmd, _post_json

    story = _Story('providerkey', 'the gateway owns the provider credential')
    from eastwind.showcase import _engine
    from eastwind.pack import register_usecases, seed_agent
    engine = _engine(path)
    writer = EvidenceWriter(engine)
    with Session(engine) as session:
        seed_agent(session)
        register_usecases(session)
        headers = _headers(session)
        session.commit()
    server = OpenAIStandIn()
    thread = serve_in_thread(server)
    port = free_port()
    command = _kognita_cmd('serve', '--provider', 'openai-compatible', '--upstream', server.origin,
        '--purpose', USECASE, '--purposes', USECASE, '--agent', AGENT_NAME,
        '--principal', RM, '--actor-location', 'SG', '--db', str(path), '--port', str(port))
    secret = 'local-workshop-provider-credential'
    log_path = path.with_suffix('.serve.log')
    with log_path.open('w') as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                   env={**os.environ, 'KOGNITA_PROVIDER_KEY': secret})
        try:
            wait_for_port(port)
            allowed_status, allowed = _post_json(port, '/v1/chat/completions', _chat_body('House guidance.'), headers)
            inference_statuses = {'/v1/chat/completions': allowed_status}
            for endpoint, inputs in (
                ('/v1/completions', {'prompt': 'House guidance.'}),
                ('/v1/responses', {'input': [{'role': 'user', 'content': 'House guidance.'}]}),
                ('/v1/embeddings', {'input': ['House guidance.']}),
            ):
                status, _ = _post_json(port, endpoint,
                    json.dumps({'model': 'eastwind-local', **inputs}).encode(), headers)
                inference_statuses[endpoint] = status
            denied_status, denied = _post_json(port, '/v1/chat/completions', _chat_body('House guidance.'),
                                               {**headers, 'authorization': 'Bearer caller-secret'})
            endpoint_status, endpoint = _post_json(port, '/v1/files', _chat_body('House guidance.'), headers)
            attachment = json.dumps({'model': 'eastwind-local', 'messages': [{'role': 'user',
                'content': [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AA=='}}]}]}).encode()
            attachment_status, attachment_body = _post_json(port, '/v1/chat/completions', attachment, headers)
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()
    story.fact('allow_status', allowed_status)
    story.fact('deny_status', denied_status)
    story.fact('allow_outcome', 'ALLOW' if allowed_status == 200 else 'DENY')
    story.fact('deny_outcome', denied.get('outcome'))
    story.fact('forwarded', len(server.received))
    story.fact('provider_key_received', server.authorization == ['Bearer ' + secret] * 4)
    story.fact('inference_statuses', inference_statuses)
    story.fact('endpoint_status', endpoint_status)
    story.fact('attachment_status', attachment_status)
    for label, body in [('deny', denied), ('endpoint', endpoint), ('attachment', attachment_body)]:
        checks = body.get('checks', [])
        story.fact(label + '_checks', checks)
        for check in checks:
            story.say(f"cite    {check['check']}: {check['citation']}")
    story.say(f'gateway credential   HTTP {allowed_status}  provider received configured key {story.result.facts["provider_key_received"]}')
    story.say(f'caller credential    HTTP {denied_status}  forwarded {len(server.received)} total')
    with Session(engine) as session:
        serialized = json.dumps([e.payload for e in session.exec(select(EvidenceEvent)).all()])
        story.fact('secrets_absent', secret not in serialized and 'caller-secret' not in serialized
                   and secret not in log_path.read_text() and 'caller-secret' not in log_path.read_text())
        story.fact('allowlisted_response', bool(allowed.get('choices')) and 'provider_details' not in allowed)
        return _finish(story, path, session)


def scenario_proposal(path: Path) -> Any:
    from kognita.approvals import ApprovalError, grant, open_approval
    from kognita.canonical import canonical_hash

    story = _Story('proposal', 'propose a document, approve its exact diff, then apply once')
    engine, writer = _seeded(path)
    with Session(engine) as session:
        env = _access(session, client_envelope('check_eligibility'))
        decision = record(session, _decision(session, env), evidence=writer)
        target = session.exec(select(KnowledgeItem).order_by(KnowledgeItem.id)).first()
        before = target.title
        proposal = Proposal(kind='document_edit', before_snapshot={'title': before},
            change={'title': before + ' (reviewed)'}, proposer_id=AGENT_NAME,
            subject_type='knowledge_items', subject_id=str(target.id),
            rationale='Clarify the reviewed house guidance')
        propose_document(session, proposal, evidence=writer, correlation_id=decision.request_id)
        digest = canonical_hash({key: getattr(proposal, key) for key in (
            'kind', 'before_snapshot', 'change', 'rationale', 'subject_type', 'subject_id', 'proposer_id')})
        approval = open_approval(session, decision_id=decision.decision_id, envelope_hash=digest,
            proposal_id=proposal.id, requester_id=AGENT_NAME, scope='LOCAL', evidence=writer,
            correlation_id=decision.request_id)
        session.commit()
        story.fact('held_outcome', 'HUMAN_APPROVAL')
        story.fact('held_unchanged', target.title == before)
        def apply() -> Any:
            return apply_proposal_tool(session, proposal, target, approval, diff_hash=digest,
                approver_id=AGENT_OWNER, actor_type=ActorType.HUMAN, evidence=writer,
                correlation_id=decision.request_id)
        try:
            apply()
        except ApprovalError as exc:
            story.fact('pending_refused', str(exc))
            story.say(f'pending approval   HUMAN_APPROVAL  cite {exc}')
        grant(session, approval, approver_name=AGENT_OWNER, evidence=writer,
              correlation_id=decision.request_id)
        apply()
        session.commit()
        story.fact('allow_outcome', 'ALLOW')
        story.fact('applied_title', target.title)
        try:
            apply()
        except ApprovalError as exc:
            story.fact('deny_outcome', 'DENY')
            story.fact('reapply_refused', str(exc))
            story.say(f'repeated apply     DENY  cite {exc}')
        story.say('exact diff approved and applied   ALLOW  cite PROPOSAL-BINDING / PROPOSAL-HUMAN')
        return _finish(story, path, session)


def scenario_recovery(path: Path) -> Any:
    from kognita.interaction import attach, open_interaction
    from kognita.intervention import recover_run

    story = _Story('recovery', 'reverse compensations and retry after failure')
    engine, writer = _seeded(path)
    with Session(engine) as session:
        _boundary(session, writer)
        interaction = open_interaction(session, client_id='CL-1001', use_case=USECASE, evidence=writer)
        # Human-initiated reversible local operations: no agent authority claimed.
        run = Run()
        registry = ToolRegistry()
        effects: list[str] = []
        attempts: list[str] = []
        broken = True
        def undo(env: Envelope, *_: Any) -> None:
            attempts.append(env.tool)
            if env.tool == 'house_view' and broken:
                raise RuntimeError('temporary compensation outage')
            effects.remove(env.tool)
        def perform(env: Envelope, *_: Any) -> str:
            effects.append(env.tool)
            return 'House guidance noted.'
        for name in ('check_eligibility', 'house_view', 'historical_eligibility'):
            registry.register(name, perform, reversible=True, compensation=undo)
            env = replace(client_envelope(name), agent_name=None)
            result = _call(session, writer, env, registry=registry, run=run)
            _show(story, name, result, rules=('USE_CASE',))
        story.fact('allow_outcome', result.outcome.value)
        attach(session, interaction.id, run_id=run.id, evidence=writer)
        session.commit()
        failed = recover_run(session, run.id, evidence=writer, human=AGENT_OWNER, citation='S6C-RECOVER')
        session.commit()
        story.fact('failed_state', failed['control_state'])
        story.fact('first_steps', [(s['name'], s['outcome']) for s in failed['steps']])
        story.say(f"compensation failed   {failed['control_state']}  cite S6C-RECOVER")
        blocked = _call(session, writer, env, registry=registry, run=run)
        _show(story, 'deny', blocked, rules=('PAUSE',))
        broken = False
        recovered = recover_run(session, run.id, evidence=writer, human=AGENT_OWNER, citation='S6C-RECOVER')
        story.fact('recovered_state', recovered['control_state'])
        story.fact('retry_steps', [s['outcome'] for s in recovered['steps']])
        story.fact('attempts', attempts)
        story.fact('remaining_effects', effects)
        story.say(f"retry completed       {recovered['control_state']}  cite S6C-RECOVER; finished compensations skipped")
        return _finish(story, path, session)
