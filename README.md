# Eastwind Private

Workshop demo for **Governed Agents That Survive Audit** (Ahmed Muzammil, AgentCon Singapore). [Kognita](https://github.com/mze3e/kognita) decides whether an eligibility question was allowed before any knowledge is retrieved, cites the rule, and keeps a tamper-evident record.

Eastwind Private, its clients, and every citation below are workshop fiction. They are not legal advice.

## Projector runbook

Citations printed by these commands are workshop fiction.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

eastwind run deny --fresh
eastwind run allow --echo-model
eastwind verify
```

`deny` does not retrieve and does not call a model. `allow --echo-model` retrieves, then shows the redacted prompt and the restored reply with no API key. `verify` checks the hash chain in `.eastwind/evidence.db`.

With `OPENAI_API_KEY` set, use the live call in place of the echo, then verify again:

```bash
eastwind run allow
eastwind verify
```

## Quickstart

Python 3.12 or newer. The three commands above are the demo. The rest is for people reading ahead.

`allow --skip-model` stops after retrieval. `both` runs DENY and then ALLOW on one store.

```bash
cp .env.example .env
eastwind run allow
eastwind run both --fresh
eastwind export -o audit.json
kognita evidence verify --db .eastwind/evidence.db
kognita evidence export --db .eastwind/evidence.db -o audit.json
```

| Variable | Role |
|---|---|
| `OPENAI_API_KEY` | Sent only on the `ALLOW` path, and only inside `EgressGuard.send`. Absent: the decision and retrieval still run, and the model is not called. |
| `OPENAI_MODEL` | Chat model. Default `gpt-4o-mini`. |

`--fresh` deletes the store first. Default path: `.eastwind/evidence.db`.

## What you should see

**DENY — cross-border structured note.** An AE relationship manager asks about a Germany-domiciled client and an HK-origin autocall. `decide` returns `DENY`. The basis names both regimes. Each citation is workshop fiction:

- `HK_SFC` — SFC Code of Conduct para 5.5 (workshop fiction)
- `DIFC_DFSA` — DFSA COB 3; GEN 2 (workshop fiction)
- `PRODUCT_GOVERNANCE` — Eastwind Private Product Governance Standard s9 (workshop fiction)

The purpose check and the agent registry pass. The outcome is still `DENY`. Retrieval was not called. The model was not called. That request’s evidence is a single `POLICY_DECISION`.

**ALLOW — Singapore money market.** An SG relationship manager asks about an accredited Singapore client and a non-complex money-market fund. `decide` returns `ALLOW`. Retrieval then returns the house view visible in zone `SG` at ceiling `C2`. A `C3` steering note that names the client stays in the store. A DFSA note zoned only for `AE` is not returned.

`eastwind run allow --echo-model` classifies the prompt as `C2` (it contains an email and an account number) and `EgressGuard` returns `REDACT`. The provider side sees `[TERM_1]`, `[EMAIL_1]`, and `[ACCOUNT_1]`. The caller sees those tokens restored. The echo destination is marked remote so the guard behaves as it will for OpenAI, and the callable itself stays on the machine.

With `OPENAI_API_KEY` set, `eastwind run allow` uses that same guard around a chat completion to `api.openai.com`. `MODEL_CALL` and `EGRESS` land on the chain with a manifest hash and no client content. `eastwind verify` reports the chain intact.

## From the talk to this repo

| The talk | Where it happens |
|---|---|
| Authorize before discovery | `src/eastwind/run.py` calls `decide` and `record` before `retrieve`. On `DENY`, `retrieve` is not called. |
| Fail closed | `DENY > ESCALATE > HUMAN_APPROVAL > ALLOW`. One failing check denies. Both regimes are kept. |
| Cited rules | Every `Check` carries `regime` and `citation`. The citations are workshop fiction. A check with an empty citation fails the conformance kit. |
| Evidence you can verify and export | `EvidenceWriter` hash-chains `POLICY_DECISION`, and on allow also `RETRIEVAL`, `MODEL_CALL`, and `EGRESS`. `eastwind verify` and `kognita evidence verify` recompute the chain. `export` writes a portable artifact. |

Kognita is the decision engine (`pip install kognita`, and `kognita[openai]` for the OpenAI SDK and embeddings adapter). This repo does not reimplement it.

## How one request moves

`src/eastwind/run.py` is the path the audience should read.

1. The envelope names a principal, a purpose, a tool, a location, a client id, and an instrument id. It holds identifiers.
2. The pack loads those rows so `decide` can see domicile, product kind, and the accredited-investor flag. Names, emails, and account numbers stay out of the attributes.
3. `decide(envelope, load_snapshot(session), ...)` is pure. `record` appends `POLICY_DECISION`.
4. `DENY` returns. Retrieval does not run. The OpenAI callable is not invoked.
5. `ALLOW` calls `retrieve` inside the caller's zone and classification ceiling, classifies the prompt with `PatternClassifier`, and passes it to `EgressGuard.send`. The callable is an OpenAI chat completion (`src/eastwind/openai_chat.py`). The guard is the only path to the SDK.

kognita 0.2.0 exposes `LLMConfig` and `kognita.adapters.OpenAICompatibleEmbedder`. It does not ship a chat-completions client. Chat goes through the guard; retrieval in this demo uses `HashingEmbedder`, so the corpus stays on the machine. Swap in `OpenAICompatibleEmbedder` when you want hosted embeddings. Treat that endpoint as remote (`is_local` is false).

`PatternRedactor` is a floor. It catches the email, account, and client-name patterns this demo plants in the prompt. It will miss a name written in prose that you did not list. A production pack should supply its own redactor. The tests check that the planted identifiers do not leave the guard.

## Domain pack

`src/eastwind/pack.py`

| | ALLOW | DENY |
|---|---|---|
| Principal | `rm.sg@eastwind.example` | `rm.ae@eastwind.example` |
| Location | SG | AE |
| Client | `CL-1001` Mei Tan, domicile SG, accredited | `CL-2002` Lena Vogel, domicile DE, not accredited |
| Instrument | `INS-MMF` SGD money market, origin SG | `INS-HK-NOTE` autocall, origin HK |

Regimes engage only when they are in scope. `MAS_SG` engages for an SG actor. `HK_SFC` and product governance engage for a structured note. `DIFC_DFSA` engages for an AE actor looking at a structured note. An un-engaged rule is skipped so it cannot deny a request it does not cover.

The agent `eligibility-advisor` is on the registry, accountable to the Head of Conduct, Eastwind Private. An unregistered agent is denied. That case is in the conformance tests.

## Tests

Offline tests cover `decide`, the dual-regime denial, the missing retrieval and model call, redaction with a fake completer, chain verification, tamper detection, and the CLI.

```bash
pytest                 # live test skips without OPENAI_API_KEY
pytest -m "not openai" # governance only
pytest -m openai       # one real chat completion; needs the key
```

## Layout

```
src/eastwind/pack.py         fictional clients, rules, knowledge
src/eastwind/run.py          envelope → decide → retrieve → egress
src/eastwind/openai_chat.py  chat completions callable used by the guard
src/eastwind/cli.py          eastwind run | verify | export | doctor
tests/                       offline governance, plus an optional live call
```

## License

MIT. Kognita is MIT as well: <https://github.com/mze3e/kognita>.
