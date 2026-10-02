"""Offline decisions: ALLOW, dual-regime DENY, fail closed, citations."""

from __future__ import annotations

import pytest
from sqlmodel import Session

from kognita import CheckResult, Outcome, create_all, decide, load_snapshot, make_engine
from kognita.testing import ConformanceCase, Harness

from eastwind.pack import (
    ALLOW,
    DENY,
    PURPOSES,
    EastwindPack,
    seed_store,
)

PACK = EastwindPack()


def _evaluate(envelope):
    engine = make_engine(":memory:")
    create_all(engine)
    with Session(engine) as session:
        seed_store(session)
        session.commit()
        subjects = PACK.load_subjects(envelope, session)
        attributes = PACK.resolve_attributes(envelope, subjects)
        return decide(
            envelope,
            load_snapshot(session),
            attributes=attributes,
            subjects=subjects,
            rules=PACK.rules(),
            purposes=PURPOSES,
            engages=PACK.engages,
        )


def test_allow_is_permitted_under_mas():
    evaluation = _evaluate(ALLOW.envelope())
    assert evaluation.outcome is Outcome.ALLOW
    regimes = {check.regime for check in evaluation.checks}
    assert "MAS_SG" in regimes
    assert all(check.result is CheckResult.PASS for check in evaluation.checks)
    assert all(check.citation.strip() for check in evaluation.checks)


def test_deny_cites_both_regimes_and_fails_closed():
    evaluation = _evaluate(DENY.envelope())
    assert evaluation.outcome is Outcome.DENY
    basis = evaluation.basis()
    regimes = {check.regime for check in basis}
    assert {"HK_SFC", "DIFC_DFSA"} <= regimes
    assert "PRODUCT_GOVERNANCE" in regimes
    assert all(check.result is CheckResult.FAIL for check in basis)
    citations = {check.regime: check.citation for check in basis}
    assert "SFC Code of Conduct para 5.5" in citations["HK_SFC"]
    assert "DFSA COB 3; GEN 2" in citations["DIFC_DFSA"]
    # Purpose and the agent registry pass. They do not overturn the denial.
    assert any(
        check.regime == "INTERNAL" and check.result is CheckResult.PASS
        for check in evaluation.checks
    )


def test_decision_attributes_omit_client_identifiers():
    evaluation = _evaluate(DENY.envelope())
    blob = repr(evaluation.attributes) + repr(evaluation.envelope.to_dict())
    assert "lena.vogel@" not in blob
    assert "HK-PB-2002771" not in blob
    assert evaluation.attributes["client_domicile"] == "DE"
    assert evaluation.attributes["product_kind"] == "STRUCTURED_NOTE"


def test_decide_writes_nothing():
    engine = make_engine(":memory:")
    create_all(engine)
    with Session(engine) as session:
        seed_store(session)
        session.commit()
        from sqlmodel import select

        from kognita import EvidenceEvent, GovernanceDecision

        before_decisions = len(session.exec(select(GovernanceDecision)).all())
        before_events = len(session.exec(select(EvidenceEvent)).all())
        subjects = PACK.load_subjects(DENY.envelope(), session)
        attributes = PACK.resolve_attributes(DENY.envelope(), subjects)
        decide(
            DENY.envelope(),
            load_snapshot(session),
            attributes=attributes,
            subjects=subjects,
            rules=PACK.rules(),
            purposes=PURPOSES,
            engages=PACK.engages,
        )
        assert len(session.exec(select(GovernanceDecision)).all()) == before_decisions
        assert len(session.exec(select(EvidenceEvent)).all()) == before_events


class TestEastwindConformance(ConformanceCase):
    """kognita's own kit: fail closed, cited, replayable, evidenced."""

    @pytest.fixture(autouse=True)
    def _bind(self):
        self.harness = Harness(pack=EastwindPack(), purposes=PURPOSES, seed=seed_store)
        self.allow_envelope = ALLOW.envelope()
        self.deny_envelope = DENY.envelope()
