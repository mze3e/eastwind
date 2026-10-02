"""CLI smoke tests. No network."""

from __future__ import annotations

import json
from pathlib import Path

from eastwind.cli import main


def test_deny_cli_prints_both_regimes_and_skips_the_model(tmp_path: Path, capsys):
    db = tmp_path / "evidence.db"
    code = main(["run", "deny", "--db", str(db), "--fresh"])
    captured = capsys.readouterr()
    assert code == 0, captured.err
    out = captured.out
    assert "Decision  DENY" in out
    assert "HK_SFC" in out
    assert "DIFC_DFSA" in out
    assert "PRODUCT_GOVERNANCE" in out
    assert "Retrieval  not called" in out
    assert "Model call not made" in out
    assert "lena.vogel@" not in out
    assert "chain verified" in out


def test_echo_model_redacts_without_calling_openai(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    db = tmp_path / "evidence.db"
    code = main(["run", "allow", "--db", str(db), "--fresh", "--echo-model"])
    captured = capsys.readouterr()
    assert code == 0, captured.err
    out = captured.out
    assert "Egress     REDACT" in out
    assert "destination local-echo" in out
    provider = out.split("provider saw:", 1)[1].split("caller received", 1)[0]
    restored = out.split("caller received", 1)[1]
    assert "mei.tan@clients.eastwind.example" not in provider
    assert "Mei Tan" not in provider
    assert "SG-PB-1001842" not in provider
    assert "[EMAIL_1]" in provider
    assert "mei.tan@clients.eastwind.example" in restored
    assert "Mei Tan" in restored
    assert "OpenAI was not called." in restored


def test_allow_cli_can_skip_the_model(tmp_path: Path, capsys):
    db = tmp_path / "evidence.db"
    code = main(["run", "allow", "--db", str(db), "--fresh", "--skip-model"])
    captured = capsys.readouterr()
    assert code == 0, captured.err
    out = captured.out
    assert "Decision  ALLOW" in out
    assert "House view — SGD money market eligibility" in out
    assert "Steering note" not in out
    assert "mei.tan@" not in out
    assert "SG-PB-1001842" not in out
    assert "--skip-model" in out


def test_both_then_export_round_trip(tmp_path: Path, capsys):
    db = tmp_path / "evidence.db"
    export_path = tmp_path / "audit.json"
    code = main(["run", "both", "--db", str(db), "--fresh", "--skip-model"])
    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert "Decision  DENY" in captured.out
    assert "Decision  ALLOW" in captured.out

    assert main(["verify", "--db", str(db)]) == 0
    capsys.readouterr()
    assert main(["export", "--db", str(db), "-o", str(export_path)]) == 0
    payload = json.loads(export_path.read_text())
    assert payload["kognita_evidence_export"] == 1
    assert payload["event_count"] >= 2
    assert main(["verify", "--file", str(export_path)]) == 0


def test_doctor_does_not_print_a_key(capsys, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret-value")
    code = main(["doctor"])
    captured = capsys.readouterr()
    assert code == 0
    assert "sk-test-secret-value" not in captured.out
    assert "OPENAI_API_KEY            set" in captured.out
    assert "kognita" in captured.out
