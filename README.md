# Eastwind Private

Workshop demo for **Governed Agents That Survive Audit** (Ahmed Muzammil, AgentCon Singapore). [Kognita](https://github.com/mze3e/kognita) 0.3 decides whether an eligibility question was allowed before any knowledge is retrieved, cites the rule, and keeps a tamper-evident record. The same Eastwind Private pack then walks the rest of that surface: egress, classification, run budgets, human approval, pinned replay, the AI gateway, the MCP proxy, and the conformance kit.

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
eastwind showcase all
```

`deny` does not retrieve and does not call a model. `allow --echo-model` retrieves, then shows the redacted prompt and the restored reply with no API key. `verify` checks the hash chain in `.eastwind/evidence.db`. `showcase all` is the longer tour, one sqlite file per scenario under `.eastwind/showcase/`. It stays on this machine.

## Live demo

The talk page is built when this repository deploys to Vercel. The build runs the three projector commands above, in that order, on a temporary store, and publishes their output as a static page. The build clears `OPENAI_API_KEY` and uses the offline echo model only.

https://eastwind.vercel.app

That address is a placeholder until the deployment hostname is confirmed.

`scripts/vercel_build.sh` installs this package (Python 3.12 or newer, `kognita[openai]>=0.3,<0.4` from `uv.lock`) and `scripts/build_demo_page.py` writes `public/index.html`. Eastwind Private on that page is the same workshop fiction as the rest of this repo. `showcase all` stays on this machine: some of those beats bind a local port.

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

kognita 0.3 ships the AI gateway (`kognita serve`) and `kognita.adapters.OpenAICompatibleEmbedder`. Chat completions are still the OpenAI SDK behind `EgressGuard.send` (`src/eastwind/openai_chat.py`). Retrieval in this demo uses `HashingEmbedder`, so the corpus stays on the machine. `eastwind showcase gateway` points that same SDK at `kognita serve`, which fronts a local stand-in. Swap in `OpenAICompatibleEmbedder` when you want hosted embeddings. Treat that endpoint as remote (`is_local` is false). The optional `kognita.graph` extra is left off this path for the same reason. `kognita scaffold` builds a separate app, so this pack does not run it.

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

Further regimes engage only for the tool that demonstrates them, so the original ALLOW and DENY envelopes still resolve the same way. `CLASSIFIER_GATE` covers free-text questions. `HANDLING` covers a typed classification. `CLIENT_LETTER` holds a letter for one human. `RELEASE_NOTE` holds a structured-note release for two signatures. `TOOL_BAR` refuses an autocall offer. `MONEY_MARKET_WINDOW` is the effective-dated domicile list. Citations stay the workshop fiction already on the pack.

## Showcase

`eastwind showcase <name>` prints one beat. `eastwind showcase all` runs them in this order. Each beat writes `.eastwind/showcase/<name>.db`.

| Command | What the room should see |
|---|---|
| `eastwind showcase authorise` | Outcome order `DENY > ESCALATE > HUMAN_APPROVAL > ALLOW`. The AE structured-note request is `DENY` with `HK_SFC` and `DIFC_DFSA` citations and a single `POLICY_DECISION`. Retrieval is not called. The SG money-market request is `ALLOW`, retrieval runs, and the `C3` note and the unzoned draft stay out. An empty purpose list is `DENY`. `unregistered-rogue-agent` is `DENY`. The kill switch on `eligibility-advisor` is `DENY` and names the Head of Conduct, Eastwind Private. |
| `eastwind showcase egress` | `EgressGuard` on Mei Tan’s email, account, and name. `C1` to a remote destination is `ALLOW`. `C2` remote is `REDACT`: the provider side sees the tokens, the caller gets the identifiers back. `C2` to a local destination is `ALLOW` and the callable sees the email. `C3` remote raises before the callable. |
| `eastwind showcase classify` | `ask()` on a vague eligibility question is `ESCALATE` below the confidence floor, with no retrieval. A clear email classifies `C2` and is `ALLOW`. Prompt text that names `C0`, a purpose, or a principal does not widen that decision. A claimed-public sentence stays on the classifier floor. `run_governed()` executes the clear tool and withholds the vague one. A typed `C0` attribute is used as given and the classifier is not consulted. |
| `eastwind showcase budget` | A `Run` with `max_calls=1` allows the first tool call and `DENY`s the second, citing `max_calls`. A run already past `wall_clock_seconds`, a `C2` tool under a `C1` `classification_ceiling`, and a call priced above `max_cost_usd` are each `DENY` citing that cap. The tool body ran once. |
| `eastwind showcase approval` | `draft_client_letter` returns `HUMAN_APPROVAL`, writes a checkpoint, and does not call the tool. `continue_run()` without a grant does not execute. A granted approval resumes and the tool runs. `release_structured_note` needs two signatures: one mark leaves it unconfirmed and unexecuted; `confirm()` by the Head of Conduct, Eastwind Private, then `continue_run()`, runs it. |
| `eastwind showcase replay` | The ALLOW decision replays `ALLOW`. Erasing the response body keeps that replay. `supersede_policy()` on the money-market window leaves the pinned decision matching. `kognita evidence reconstruct` writes `replay-report.json` and `replay-report.txt`. A tampered knowledge row and a tampered retained prompt fail replay. An in-place citation edit is refused; the same citation written into the row fails replay. |
| `eastwind showcase effective` | Lena Vogel, domicile DE, asked from HK about the SGD money market. As of March 2026 the window denies Germany. The April successor adds DE. Asking again as of March is still `DENY`. As of October 2026 it is `ALLOW`. `replay_decision()` of the recorded March decision stays `DENY`. |
| `eastwind showcase gateway` | `kognita serve` fronts a local OpenAI-compatible stand-in. The SDK’s `base_url` is that gateway. The listed agent is forwarded; the caller sees Mei Tan’s email and the stand-in does not. A missing agent name and an unlisted agent are HTTP 403 `DENY`. With the evidence store down, `FAIL_CLOSED` returns 503 and does not forward. `DEGRADED` forwards only a local model below `C2`, then writes the `ALLOW` once the store answers again. A remote destination, and a local email whose header claims `C0`, are `DENY` and are not forwarded. An approved system trigger is forwarded as actor `SYSTEM`. |
| `eastwind showcase mcp` | `kognita serve --mcp` fronts a local MCP server of Eastwind tools. `house_view` is forwarded. `offer_autocall` is `DENY`, `vague_note` is `ESCALATE`, and `draft_client_letter` is `HUMAN_APPROVAL`. Those three never reach the tool server. |
| `eastwind showcase conformance` | kognita’s conformance kit, bound to this pack, including the human-approval envelope. Each `test_*` prints `PASS`. |

The gateway beat needs the name `upstream.eastwind.example` to resolve to `127.0.0.1`. Egress treats `localhost` as trusted and will not redact it, so the stand-in has to look remote while the bytes stay on this machine. The scenario appends that hosts line when it can. The serve process is started with the agent and the purpose only: `kognita serve` has no pack argument, and loading every regime with no actor location would deny the call. The in-process store-down beats pass `EastwindPack` with an empty actor location so those regimes stay unengaged. A live OpenAI completion remains `eastwind run allow` when `OPENAI_API_KEY` is set.

## Tests

Offline tests cover `decide`, the dual-regime denial, the missing retrieval and model call, redaction with a fake completer, chain verification, tamper detection, the CLI, and every showcase scenario. The conformance kit’s human-approval case is bound to `draft_client_letter`, so that case runs here. The original ALLOW and DENY outcomes are unchanged. An empty purpose list fails closed inside `eastwind showcase authorise`.

```bash
pytest                 # live test skips without OPENAI_API_KEY
pytest -m "not openai" # offline suite, including every showcase
pytest -m openai       # one real chat completion; needs the key
```

## Layout

```
src/eastwind/pack.py           fictional clients, rules, knowledge
src/eastwind/run.py            envelope → decide → retrieve → egress
src/eastwind/showcase.py       one scenario per kognita 0.3 feature
src/eastwind/local_servers.py  local OpenAI and MCP stand-ins
src/eastwind/openai_chat.py    chat completions callable used by the guard
src/eastwind/cli.py            eastwind run | showcase | verify | export | doctor
scripts/build_demo_page.py     static talk page from the offline commands
scripts/vercel_build.sh        Vercel build: install, then build the page
vercel.json                    static output in public/
tests/                         offline governance and showcase, plus an optional live call
```

## License

MIT. Kognita is MIT as well: <https://github.com/mze3e/kognita>.
