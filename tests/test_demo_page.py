"""The public talk page is the offline projector run. No network."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _builder():
    path = ROOT / "scripts" / "build_demo_page.py"
    spec = importlib.util.spec_from_file_location("build_demo_page", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_talk_page_is_the_offline_projector_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-talk-page-must-not-leak")
    page = _builder().build_page(tmp_path / "index.html")
    text = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert text == page

    assert "Workshop fiction." in text
    assert "Eastwind Private is a fictional institution." in text
    assert "Governed Agents That Survive Audit" in text
    assert "5 November 2026" in text
    assert "Ahmed Muzammil" in text

    assert "eastwind run deny --fresh" in text
    assert "Decision  DENY" in text
    assert "HK_SFC" in text
    assert "DIFC_DFSA" in text
    assert "SFC Code of Conduct para 5.5 (workshop fiction)" in text
    assert "DFSA COB 3; GEN 2 (workshop fiction)" in text
    assert "Retrieval  not called" in text
    assert "Model call not made" in text
    assert "lena.vogel@clients.eastwind.example" not in text

    assert "eastwind run allow --echo-model" in text
    assert "Decision  ALLOW" in text
    assert "Egress     REDACT" in text
    assert "House view — SGD money market eligibility" in text
    provider = text.split("panel provider", 1)[1].split("panel restored", 1)[0]
    restored = text.split("panel restored", 1)[1].split("Command output", 1)[0]
    assert "mei.tan@clients.eastwind.example" not in provider
    assert "Mei Tan" not in provider
    assert "SG-PB-1001842" not in provider
    assert "[EMAIL_1]" in provider
    assert "[TERM_1]" in provider
    assert "[ACCOUNT_1]" in provider
    assert "mei.tan@clients.eastwind.example" in restored
    assert "Mei Tan" in restored
    assert "SG-PB-1001842" in restored
    assert "OpenAI was not called." in restored

    assert "eastwind verify" in text
    assert "evidence chain verified:" in text
    assert "sk-talk-page-must-not-leak" not in text
    assert "<script" not in text.lower()


def test_vercel_config_publishes_the_static_page():
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    assert config["framework"] is None
    assert config["outputDirectory"] == "public"
    assert "scripts/vercel_build.sh" in config["buildCommand"]
    script = (ROOT / "scripts" / "vercel_build.sh").read_text(encoding="utf-8")
    assert "uv sync --frozen --extra dev" in script
    assert "build_demo_page.py" in script
    builder = (ROOT / "scripts" / "build_demo_page.py").read_text(encoding="utf-8")
    assert '"--echo-model"' in builder
    assert "OpenAIChat" in builder
