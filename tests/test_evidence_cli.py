"""Evidence verifier CLI tests; the npm integration is explicitly opt-in."""
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from eastwind.cli import main


def node_supported():
    if not shutil.which('node') or not shutil.which('npx'):
        return False
    try:
        version = subprocess.run(['node', '--version'], capture_output=True, text=True, check=True).stdout.strip()
        return int(version.lstrip('v').split('.')[0]) >= 22
    except (OSError, ValueError, subprocess.CalledProcessError):
        return False


@pytest.fixture
def bundle(tmp_path):
    db = tmp_path / 'store.db'
    path = tmp_path / 'bundle.json'
    assert main(['run', 'deny', '--db', str(db), '--fresh']) == 0
    assert main(['evidence', 'export', '--db', str(db), '-o', str(path)]) == 0
    return path


def test_combined_verifier_runs_both_and_propagates_failures(bundle, tmp_path, monkeypatch):
    calls = []

    def npm(command, *, check):
        calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr('eastwind.cli.subprocess.run', npm)
    assert main(['evidence', 'verify', '--file', str(bundle), '--with-npm']) == 0
    assert calls[-1] == ['npx', '--yes', '@kognita/verify@0.9.0', str(bundle)]
    edited = tmp_path / 'edited.json'
    assert main(['evidence', 'tamper', '--file', str(bundle), '-o', str(edited)]) == 0
    assert main(['evidence', 'verify', '--file', str(edited), '--with-npm']) == 1
    assert len(calls) == 2
    monkeypatch.setattr('eastwind.cli.subprocess.run', lambda *args, **kwargs: SimpleNamespace(returncode=1))
    assert main(['evidence', 'verify', '--file', str(bundle), '--with-npm']) == 1


def test_missing_options_and_npx_fail_without_changing_source(bundle, tmp_path, monkeypatch, capsys):
    missing_db = tmp_path / 'missing.db'
    assert main(['evidence', 'verify', '--db', str(missing_db), '--with-npm']) == 1
    assert not missing_db.exists()
    before = bundle.read_bytes()
    assert main(['evidence', 'tamper', '--file', str(bundle), '-o', str(bundle)]) == 1
    assert bundle.read_bytes() == before

    def missing(*args, **kwargs):
        raise FileNotFoundError('npx')

    monkeypatch.setattr('eastwind.cli.subprocess.run', missing)
    assert main(['evidence', 'verify', '--file', str(bundle), '--with-npm']) == 1
    assert 'requires Node 22 or later and npx' in capsys.readouterr().err


@pytest.mark.npm
@pytest.mark.skipif(os.getenv('EASTWIND_TEST_NPM') != '1', reason='npm integration requires explicit network opt-in')
@pytest.mark.skipif(not node_supported(), reason='Node 22 or later and npx are required')
def test_independent_npm_verifier_and_tamper(bundle):
    script = Path(__file__).resolve().parents[1] / 'scripts' / 'check_evidence.sh'
    result = subprocess.run([str(script), str(bundle)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Both verifiers rejected the edited copy.' in result.stdout
