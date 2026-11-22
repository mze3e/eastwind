# Eastwind Private

Eastwind Private is a governed-agents demo on `kognita==0.9.0`. It demonstrates policy checks before retrieval, governed agent tools, human approval, and tamper-evident records. Clients, data, policies, and trade proposals are fictional. No workflow places a trade.

## Offline quickstart

Python 3.12 or newer and [uv](https://docs.astral.sh/uv/) are required. The default model is deterministic and runs locally without a key.

```bash
uv sync --frozen --extra dev
uv run eastwind workflow all
uv run eastwind admin
```

Open `http://127.0.0.1:8090`. Set `EASTWIND_ADMIN_TOKEN` to choose an action token, or use the one printed at startup. Each action form asks for the token. Pages are readable without a token on the local host, so use synthetic data on a trusted machine. The server accepts loopback bindings only. Its persistent stores default to `.eastwind/admin`; use `--db DIR` to change them.

For the longer command-line showcase, run `uv run eastwind showcase all --db /tmp/eastwind-showcase`. Its gateway and MCP demonstrations use local stand-ins. The optional ingestion and framework-adapter examples report a skip when their extras are absent. The static site (the demo page and the 3D walkthrough below) is rebuilt with `uv run python scripts/build_demo_page.py`.

## Walkthrough for executives

A guided 3D story for an audience that does not read policy engines. One AI colleague at a fictional private bank: **Know** what it may see, **Do** what it may do, **Prove** what the bank can show afterwards. You drive it.

```bash
uv run python scripts/build_demo_page.py --serve    # builds public/ and serves it on 127.0.0.1:8000
```

Open `http://127.0.0.1:8000/` for the demo page, or go straight to `/story/`. Use a modern browser with WebGL. Without WebGL the story still runs as text and the pictures are off.

| Key | Does |
|---|---|
| `←` `→` or `Space` | Previous and next step |
| `1` `2` `3` | Pick the choice shown at the bottom (who is asking, approve or deny, hit the stop, edit an entry) |
| `N` | Talk track for the step, in plain words |
| `M` | Show the mechanics: the command to reproduce the step and the rule codes behind it |
| `F` | Full screen |
| `#know-border` etc. | Any step can be opened directly by its id, and the address bar follows you |

Sixteen steps: a welcome; meet the colleague and its PWM passport; Know (who is asking, the wrong desk, approved sources, names that never leave the bank); Do (authority is not access, a person approves, the emergency stop wins, a budget of calls); Prove (a sealed record, checking the seals, an edited entry caught, a report that lists its gaps); and a recap.

How it stays honest:

- **The decisions are real.** `src/eastwind/story.py` runs the governed scenarios and workflows on one synthetic store, once for every branch you can choose, and writes `story/data.json`. If a claim the story would make is not true of the run, the build fails. The walkthrough replays that recording, so it needs no application server, no key and no model call in the room.
- **The model is a stand-in.** Nothing contacts a provider. The footer of every step says so.
- **The words are tested.** All on-screen copy is written in `story.py`, not in JavaScript, so `tests/test_story.py` can check it: no jargon on a primary screen (the codes live behind `M`), numbers match the data, and nothing about a client who was never retrieved or a document that was withheld is shipped.
- **Edits are described exactly.** The tamper step shows that an edited entry is detected and where. It does not claim that a fully rewritten record would be: that needs a checkpoint published outside the system, as the Evidence section notes.

The pictures are drawn with [three.js](https://threejs.org) 0.187.0, vendored unmodified in `web/vendor/three` with its checksums, so it runs from one origin with no CDN. `/story/` is served with a content policy that permits only same-origin scripts; the demo page at `/` still runs none. `--serve` applies the same headers as `vercel.json`, so what you present locally is what is deployed. The stills on the demo page come from the real scenes: refresh them with `node scripts/render_previews.cjs` (needs Playwright and Chromium) and commit `web/story/previews`.

## Vercel public demo

The Git-connected Vercel configuration builds the static demo page at `/` and the 3D walkthrough at `/story/`, and routes `/admin/` to `api/index.py`, a Python 3.12 FastAPI function. The configuration sets `EASTWIND_PUBLIC_DEMO=1`; no provider key or admin token is needed. The function always uses the in-process mock and rejects real-provider requests. It does not start `kognita serve` or contact an external service. The MCP and degraded gateway drills need the local CLI and are disabled in the public UI.

Each function instance seeds synthetic records under `/tmp`. State is shared by visitors on that instance, can disappear on restart, and is not synchronized across instances. A later request may reach a different instance, so an approval can disappear between requests. Never enter real client data. The public evidence page verifies the Python chain and shows the npm command for local verification; it does not run npm in the function. The normal `eastwind admin` command remains token-protected and local-only.

Dependencies come from `pyproject.toml` and `uv.lock`; optional development and provider extras are excluded from the function. Vercel's [Python runtime documentation](https://vercel.com/docs/functions/runtimes/python) describes the ASGI entrypoint and its 500 MB uncompressed bundle limit. The demo page keeps a restrictive content policy that runs no script (it adds only its own preview images); the walkthrough permits same-origin scripts and nothing else; the admin permits same-origin forms.

## Guided tour

To see how the agent uses permitted context, acts within its mandate, and leaves a verifiable record, go to **Admin > Tour: Permitted context, mandated action, provable record**:

1. **Permitted context:** compare the relationship manager and agent in **Policies and entitlements**, then run **client-review** in **Workflows**. The agent sees masked or denied fields; the policy decision precedes retrieval. The **research** workflow checks the house-view source.
2. **Mandated action:** inspect **Agents**, then run **rebalance**. The proposal suspends in **Approvals**. Approve or deny it to resume the run. To test release controls, approve a new proposal without releasing it, engage the **Kill switch**, then resolve it with approve. The stopped proposal is withheld.
3. **Provable record:** inspect **Evidence**, verify the chain, and edit a copy in the tamper demonstration. Use **Replay** for a decision and **Reconstruction** for a review interaction. Missing evidence remains identified as missing.

**Budgets** shows run limits and consumption. Set the call budget in the workflow form; a limit of two demonstrates exhaustion. The kill-switch, MCP, and degraded-mode drills use isolated stores. The admin switch governs the admin store and its pending approvals.

## Workflows

`uv run eastwind workflow NAME` accepts `client-review`, `suitability`, `rebalance`, `research`, `egress`, `budget`, `kill-switch`, `mcp`, `degraded`, `replay`, or `all`. Separate stores live under `.eastwind/workflows`, configurable with `--db DIR`. Examples:

```bash
uv run eastwind workflow client-review --role relationship_manager
uv run eastwind workflow client-review --role visitor
uv run eastwind workflow suitability --product INS-HK-NOTE
uv run eastwind workflow research --source unapproved
```

The visitor is denied before retrieval, the high-risk product is unsuitable for the synthetic mandate, and the unapproved source is not read. The rebalance CLI scenario demonstrates denial, approval, and a stop after approval. The admin version leaves proposals suspended for the queue. Replay uses an existing client review in the workflow directory or creates one if needed. Wealth workflows currently support `--llm mock` only; other providers fail closed.

## Models and the gateway

`eastwind run allow --llm mock` uses the in-process mock. `eastwind mock-llm serve` exposes an OpenAI-compatible mock at `http://127.0.0.1:8091`, which can be configured as a Kognita gateway upstream. See `.env.example` for all settings; no keys are required for offline commands.

For `eastwind run`, select `--llm openai`, `anthropic`, `xai`, `ollama`, or `openai-compatible`, or set `EASTWIND_LLM_PROVIDER`. `EASTWIND_LLM_MODEL` selects the approved model; the compatible preset requires it. Provider origin presets are `https://api.openai.com`, `https://api.x.ai`, and `http://127.0.0.1:11434`. Set `EASTWIND_LLM_BASE_URL` to the gateway's upstream origin for other compatible services such as vLLM, LM Studio, Groq, Together, or Mistral. `EASTWIND_LLM_KEY_ENV` optionally names a different key variable. Ollama normally needs no key.

Real calls require a local `kognita serve` gateway and its existing SQLite store, with an admitted agent and approved use case, provider contract, and model card. Set `EASTWIND_LLM_GATEWAY_URL` to the gateway origin and `EASTWIND_LLM_GATEWAY_DB` to the store passed to the gateway. Keep that store separate from the Eastwind scenario store. The gateway owns the provider credential. For example, after preparing its registers and exporting the settings:

```bash
KOGNITA_PROVIDER_KEY="$OPENAI_API_KEY" kognita serve --provider openai-compatible \
  --upstream "$EASTWIND_LLM_BASE_URL" --purpose ELIGIBILITY_CHECK \
  --purposes ELIGIBILITY_CHECK --agent eligibility-advisor \
  --principal rm.sg@eastwind.example --actor-location SG \
  --db "$EASTWIND_LLM_GATEWAY_DB" --host 127.0.0.1 --port 8080
# In another terminal, with the same model, gateway, and key settings:
uv run eastwind run allow --llm openai --db .eastwind/scenario.db
```

The gateway store must approve the selected provider and model; absent settings or approvals fail closed. Eastwind checks for the gateway's characteristic response but does not authenticate a malicious local service. Protect the host and gateway configuration.

Anthropic uses a native adapter behind a local bridge. Install `uv sync --extra dev --extra anthropic`, set `ANTHROPIC_API_KEY`, and set `EASTWIND_ANTHROPIC_BRIDGE_TOKEN` to a random secret of at least 32 ASCII characters. Start `eastwind anthropic-bridge serve`; configure the gateway upstream as `http://127.0.0.2:8093` and its `KOGNITA_PROVIDER_KEY` as the bridge token. Register `127.0.0.2` as the provider for the bridge model card and contract. If a proxy is configured, set `NO_PROXY=127.0.0.1,127.0.0.2` for the gateway. Then select `--llm anthropic`. The bridge supports text, tool calls, and tool results; unsupported options fail closed. Optional SDK extras are `anthropic` and `openai`.

## Evidence and PWM

```bash
uv run eastwind run deny --db /tmp/eastwind-evidence.db
uv run eastwind evidence export --db /tmp/eastwind-evidence.db -o /tmp/eastwind-evidence.json
uv run kognita evidence verify --file /tmp/eastwind-evidence.json
uv run eastwind evidence verify --file /tmp/eastwind-evidence.json --with-npm
uv run eastwind evidence tamper --file /tmp/eastwind-evidence.json -o /tmp/eastwind-edited.json
scripts/check_evidence.sh /tmp/eastwind-evidence.json
```

The script verifies the original using Python and `npx --yes @kognita/verify@0.9.0`, then requires both to reject an edited copy. It needs Node 22 or later and npx; npx may download the published verifier. Both commands check hash integrity. Verification without an independently trusted checkpoint cannot detect a consistently rewritten chain. A public key is needed to independently authenticate signatures.

```bash
uv run eastwind pwm export -o /tmp/eastwind-pwm.ttl
uv run eastwind pwm validate /tmp/eastwind-pwm.ttl
```

The default commands create `.eastwind/pwm/demo.db`, a separate synthetic register with a recorded illustrative profile for fields Kognita does not store. The profile is bound to use-case and deployment hashes and is not an operational attestation. Use `--db PATH` on `pwm export` or `pwm validate` to use an existing store. Missing metadata remains missing and can cause nonconformance; `--demo-profile` requires a matching recorded profile. `--no-evidence` omits evidence records. Export verifies the source chain, while SHACL validates RDF structure rather than signatures. The vendored PWM 0.10 source, checksums, and licenses are in `src/eastwind/pwm_data/README.md`. The admin PWM page offers both its store and the separate demo profile.

## Feature map

Run a showcase entry as `uv run eastwind showcase NAME`, a workflow as `uv run eastwind workflow NAME`, or use the named Admin page. Multiple names in a row cover related parts of a feature.

| Kognita feature | Eastwind demonstration |
|---|---|
| Policy decisions, authorization before retrieval, role masking | Showcase `authorise`; workflow `client-review`; Admin Policies, Workflows |
| Agent and use-case registry, lifecycle, model cards | Showcase `register`; Admin Agents, PWM |
| Effective-dated policies, policy language and packs | Showcase `effective`, `policy`, `packs`; Admin Policies |
| Classification and injection checks | Showcase `classify` |
| Approved source register and grounding | Workflow `research`; Admin Policies, Workflows |
| Egress, redaction, field minimization, opaque content refusal | Showcase `egress`, `providerkey`; workflow `egress` |
| Run budgets and isolation | Showcase `budget`; workflow `budget`; Admin Budgets |
| Human approvals, continuations, two signatures | Showcase `approval`; workflow `rebalance`; Admin Approvals |
| Kill switch, revocation, circuit breaker and drills | Showcase `breaker`; workflow `kill-switch`, `rebalance`; Admin Kill switch, Approvals |
| Gateway and provider-held credentials | Showcase `gateway`, `providerkey`; local mock server and gateway configuration above |
| MCP proxy and governed tool calls | Showcase `mcp`; workflow `mcp` |
| Fail-closed and degraded operation | Showcase `gateway`; workflow `degraded` |
| Evidence chain, exports, independent verification and tamper detection | `eastwind evidence`; `scripts/check_evidence.sh`; Admin Evidence |
| Replay, reconstruction, pinned decisions and retention | Showcase `replay`; workflow `replay`; Admin Replay, Reconstruction |
| Ingestion, source locators and classifications | Showcase `ingest` (optional extra) |
| Interactions, do-not-contact, client communication | Showcase `contact`, `communicate` |
| Outcomes, review queue and monitoring | Showcase `outcomes`, `recorder` |
| Conformance kit and framework bindings | Showcase `conformance`, `adapters` (some bindings require extras) |
| Agent autonomy, credentials and delegated authority | Showcase `autonomy`, `credentials`, `authority`; Admin Agents |
| Blast radius, anomaly containment, taint and system triggers | Showcase `blastradius`, `anomaly`, `taint`, `triggers` |
| Document proposals and compensating recovery | Showcase `proposal`, `recovery` |
| PWM 0.10 registers and SHACL | `eastwind pwm export`, `eastwind pwm validate`; Admin PWM |

Kognita also provides claim-release verification, stale-fact and definition controls, memory and learning governance, fairness and evaluation gates, reasoning-trace controls, signed evidence and key management, external anchors and review, recovery bundles, dependency and concentration reports, provider failover, incident reporting, and runtime-assurance attestations. Eastwind does not provide dedicated scenarios or admin controls for these capabilities; consult Kognita's documentation before using them.

## Tests

```bash
uv run pytest -q -m "not openai and not live"
EASTWIND_TEST_NPM=1 uv run pytest -q -m npm
```

The offline suite never calls a real provider and skips the npm integration unless explicitly enabled. The npm test also skips when Node 22 or later or npx is unavailable. The live-provider test requires `EASTWIND_RUN_LIVE=1` and a configured gateway. CI installs Node 22 and exercises the independent verifier and edited-copy failure separately from the offline suite.

The site builder and Vercel configuration remain in `scripts/build_demo_page.py`, `scripts/vercel_build.sh`, and `vercel.json`. `tests/test_story.py` covers the walkthrough: its data, its copy, the vendored three.js, the built site, and the page policy.

## License

Eastwind is MIT licensed; see `LICENSE`. The vendored PWM files carry the attribution and license described in `src/eastwind/pwm_data/README.md`.
