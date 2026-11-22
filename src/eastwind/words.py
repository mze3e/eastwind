"""Plain-English vocabulary shared by the walkthrough, the console and the one-pager.

Pure data. It imports nothing, so the serverless console can use it without pulling in the
command line (and with it the test tools the function does not install). Every entry says
what a Kognita code means to a person who does not read policy engines. Raw codes stay in
each page's "Show the mechanics" section.
"""
from __future__ import annotations

OUTCOME_WORDS = {"ALLOW": "Allowed", "DENY": "Blocked", "HUMAN_APPROVAL": "Waiting for a person",
                 "ESCALATE": "Sent to a person"}
OUTCOME_TONE = {"ALLOW": "good", "DENY": "bad", "HUMAN_APPROVAL": "warn", "ESCALATE": "warn"}

FIELD_LABELS = {"name": "Name", "email": "Email", "risk_profile": "Risk profile",
                "investment_horizon_years": "Investment horizon", "tax_identifier": "Tax ID"}

#: The same fields, for use inside a sentence.
FIELD_PHRASES = {"name": "name", "email": "email", "risk_profile": "risk profile",
                 "investment_horizon_years": "investment horizon", "tax_identifier": "tax ID",
                 "account": "account number"}

DESKS = {"SG": "Singapore", "AE": "Dubai", "HK": "Hong Kong"}

ROLE_WORDS = {"relationship_manager": "Relationship manager", "agent": "AI colleague", "visitor": "Visitor"}
#: The same roles inside a sentence.
ROLE_PHRASES = {"relationship_manager": "relationship manager", "agent": "AI colleague", "visitor": "visitor"}

#: The seven independence levels Kognita registers, lowest first.
LEVEL_WORDS = ("Look things up", "Explain", "Recommend", "Draft", "Act after approval",
               "Act within limits", "Act freely")

CLASS_WORDS = {"C0": "Public", "C1": "Internal", "C2": "Confidential", "C3": "Restricted"}

RISK_WORDS = {"low": "Low", "moderate": "Moderate", "medium": "Medium", "high": "High"}

#: Why a check failed, in words a director would use. Keyed by regime. The agent-identity
#: check names the two desks, so it is built from the data where it is used.
REASONS = {
    "HK_SFC": "Hong Kong securities rules: this client lives outside the permitted countries.",
    "DIFC_DFSA": "Dubai financial centre rules: this client lives outside the permitted countries.",
    "PRODUCT_GOVERNANCE": "Product rules: this product is only for accredited investors, and this client is not one.",
}

#: What each rule in the policy register says, in one sentence. Keyed by regime.
POLICY_WORDS = {
    "MAS_SG": ("Singapore desk", "A Singapore-desk request is allowed only for clients who live in Singapore, Hong Kong or Dubai."),
    "HK_SFC": ("Hong Kong securities rules", "Structured notes are only for clients who live in Singapore, Hong Kong or Dubai."),
    "DIFC_DFSA": ("Dubai financial centre rules", "A Dubai-desk request is allowed only for clients who live in Singapore, Hong Kong or Dubai."),
    "PRODUCT_GOVERNANCE": ("Product rules", "Structured notes are only offered to accredited investors."),
    "CLASSIFIER_GATE": ("Sensitivity check", "If the classifier is less than 80% sure how sensitive something is, it is not let through."),
    "HANDLING": ("Handling rules", "These checks only pass for public material."),
    "ROLE_ENTITLEMENT": ("Who may read what", "Only people and AI roles with permission for the source may read client records."),
    "TRADE_PROPOSAL": ("Trade proposals", "A trade proposal always needs a named person to approve it."),
    "CLIENT_LETTER": ("Client letters", "A letter to a client needs a person to approve it."),
    "RELEASE_NOTE": ("Releasing a note", "Releasing a structured note needs two signatures."),
    "TOOL_BAR": ("Barred tool", "An autocall note cannot be released through this tool at all."),
    "MONEY_MARKET_WINDOW": ("Money-market window", "Money-market eligibility is for clients who live in Singapore, Hong Kong or Dubai."),
}
#: Used for a rule this table does not know yet, so a new rule is never shown as a raw code.
POLICY_FALLBACK = {
    "ATTRIBUTE_ALLOWLIST": "Allowed only when the request matches the permitted values.",
    "REQUIRES_FLAG": "Allowed only when a required condition is met.",
    "REQUIRES_HUMAN_APPROVAL": "A named person must approve.",
    "TWO_SIGNATURE_APPROVAL": "Two named people must sign.",
    "PROHIBITED": "Not permitted.",
}

TOOL_WORDS = {
    "check_eligibility": "Check eligibility", "classify_question": "Classify a question",
    "injection_question": "Screen a question for tricks", "classify_tool": "Classify sensitivity",
    "typed_classification": "Apply a handling label", "draft_client_letter": "Draft a client letter",
    "release_structured_note": "Release a structured note", "offer_autocall": "Offer an autocall note",
    "historical_eligibility": "Check past eligibility", "house_view": "Look up the house view",
    "vague_note": "Handle a vague note", "model_call": "Ask the AI model",
    "client_profile": "Read the client profile", "account_holdings": "Read the account holdings",
    "summarize_review": "Summarize the review", "product_profile": "Read the product",
    "check_suitability": "Check suitability", "propose_trade": "Propose a trade",
    "approved_sources": "List approved sources", "retrieve_house_view": "Read the house view",
    "summarize_research": "Summarize the research",
}

#: Evidence record types as a person would name them, with a color group.
EVENT_WORDS = {
    "POLICY_DECISION": ("Decision", "decision"), "TOOL_CALL": ("Tool used", "work"),
    "RETRIEVAL": ("Documents fetched", "work"), "MODEL_CALL": ("AI model called", "work"),
    "APPROVAL": ("Human approval", "human"), "INTERVENTION": ("Human step-in or stop", "human"),
    "EGRESS": ("Outbound data check", "privacy"), "INTERACTION": ("Client conversation opened", "setup"),
    "POLICY_CHANGE": ("Setup or rule change", "setup"), "CLAIM": ("Statement recorded", "work"),
    "FINAL_DECISION": ("Final outcome", "final"),
}

#: The tasks the console can run. group: know, do, prove, break.
WORKFLOW_WORDS = {
    "client-review": ("Review a client file", "know",
                      "Ask for a client's profile and holdings as one of three people, and see what each is given."),
    "research": ("Use the house view", "know",
                 "Read the bank's approved house view. It is checked against the approved-source register first."),
    "egress": ("Send confidential data out", "know",
               "Try to send the client file to an outside provider. The highest-sensitivity data is stopped at the door."),
    "suitability": ("Check a product against the mandate", "do",
                    "Check a product against this client's risk profile and mandate before anyone proposes it."),
    "rebalance": ("Prepare a trade proposal", "do",
                  "The AI prepares a proposal and pauses. It waits in the inbox until a named person decides."),
    "budget": ("Run out of calls", "do",
               "Give the AI a budget of two calls for a task that needs three. The third is refused."),
    "kill-switch": ("Ask during an emergency stop", "do",
                    "Engage the emergency stop in a separate drill and ask the AI for something."),
    "replay": ("Replay a past decision", "prove",
               "Take a recorded decision and run it again today, against the rules that applied then."),
    "mcp": ("Governed tool calls", "break",
            "Route a tool call through the governed proxy. Needs the command line: it starts a local server."),
    "degraded": ("The record keeper goes down", "break",
                 "Cut the record keeper in four ways and see what still runs. Needs the command line."),
}
GROUP_WORDS = {"know": "Know: what may it see?", "do": "Do: what may it do?",
               "prove": "Prove: what can we show?", "break": "What if it breaks?"}

#: The parts of an AI passport (a PWM export) as a person would name them: (id, PWM class, label, ring).
PWM_NODES = (  # (id, PWM class, label, ring)
    ("usecase", "AIUseCase", "AI use case", 0),
    ("business", "BusinessOwner", "Business owner", 1),
    ("technology", "TechnologyOwner", "Tech owner", 1),
    ("control", "DesignatedControlFunction", "Control", 1),
    ("risk", "RiskMaterialityAssessment", "Risk rating", 1),
    ("agent", "AIAgent", "AI agent", 1),
    ("model", "AIModel", "AI model", 2),
    ("providers", "ModelProvider", "Providers", 2),
    ("identity", "WorkloadIdentity", "Identity", 2),
    ("tools", "Tool", "Tools", 2),
    ("source", "ApprovedSource", "Source", 2),
    ("retention", "RetentionPolicy", "Retention", 2),
    ("evidence", "EvidenceRecord", "Evidence", 2),
)

# ----------------------------------------------------------- capability map
# One entry per capability. Titles and promises are plain; `see` says honestly where it can be seen:
#   ("story", step id)   in the 3D walkthrough
#   ("console", path)    on a page of the live console
#   ("cli", command)     in the demo command line only
#   ("none", "")         part of Kognita, with no demonstration here
# Every row of the README feature map is here, and so is each item the README lists as having no
# dedicated scenario. `tests/test_story.py` checks that the two stay in step.
CAPABILITIES = (
    ("decisions", "know", "Permission before retrieval",
     "The question is asked first: may this person, for this purpose, see this? A refusal returns nothing at all.",
     ("story", "know-roles"), ("console", "/policies")),
    ("registry", "meet", "A register of AI colleagues",
     "Every AI agent is registered with an owner, a purpose, a risk rating and a model. An unregistered one is refused.",
     ("story", "colleague-hire"), ("console", "/agents")),
    ("effective", "know", "Rules with start and end dates",
     "Policies carry effective dates, and can be written in a plain policy language and shared as packs.",
     ("cli", "eastwind showcase effective policy packs"), None),
    ("classify", "know", "Sensitivity and trick detection",
     "Questions are classified by how sensitive they are and screened for attempts to talk the AI round.",
     ("cli", "eastwind showcase classify"), None),
    ("sources", "know", "Only approved sources",
     "The AI may only rely on documents on the approved register, with a known owner, version and dates.",
     ("story", "know-sources"), ("console", "/policies")),
    ("egress", "know", "Names never leave the bank",
     "Before a question goes to an outside provider, identifying details are swapped for placeholders. The most sensitive data cannot leave at all.",
     ("story", "know-privacy"), ("console", "/workflows")),
    ("budgets", "do", "A budget on every task",
     "Each task gets a limit on calls, so a runaway loop stops by itself.",
     ("story", "do-limits"), ("console", "/budgets")),
    ("approvals", "do", "People decide the big calls",
     "A trade proposal pauses, is saved, and waits for a named person. Some actions need two signatures.",
     ("story", "do-approval"), ("console", "/approvals")),
    ("stop", "do", "An emergency stop that wins",
     "One switch halts an agent, even for something already approved. Access can be revoked and a breaker can trip.",
     ("story", "do-stop"), ("console", "/kill-switch")),
    ("gateway", "do", "The bank holds the keys",
     "AI calls go through a gateway that holds the provider's credentials, so the agent does not hold them.",
     ("cli", "eastwind showcase gateway providerkey"), None),
    ("mcp", "do", "Governed tool calls",
     "Tool calls from agents pass through a proxy that applies the same checks before anything runs.",
     ("cli", "eastwind workflow mcp"), None),
    ("failclosed", "break", "Safe when the record keeper is down",
     "If a decision cannot be recorded, the system can refuse every call, or carry on only with a local model and content that names no client, and record it once it can.",
     ("story", "break-outage"), None),
    ("evidence", "prove", "A sealed record anyone can check",
     "Every decision goes into a record sealed entry to entry. The export can be checked by independent programs, and an edit is detected.",
     ("story", "prove-receipt"), ("console", "/evidence")),
    ("replay", "prove", "Replay and rebuild",
     "A past decision can be re-run against the inputs it had, and the story of an interaction rebuilt, including what was never recorded.",
     ("story", "prove-rebuild"), ("console", "/replay")),
    ("ingest", "know", "Reading documents with their labels",
     "Documents are split into sections that keep their source location and classification. Needs an optional extra.",
     ("cli", "eastwind showcase ingest"), None),
    ("contact", "do", "Client contact rules",
     "Interactions are recorded, do-not-contact is respected, and client communication is checked before it goes.",
     ("cli", "eastwind showcase contact communicate"), None),
    ("outcomes", "prove", "Outcomes and monitoring",
     "Results are recorded, queued for review, and monitored.",
     ("cli", "eastwind showcase outcomes recorder"), None),
    ("conformance", "prove", "A test kit for other systems",
     "A conformance kit and bindings for agent frameworks let another system prove it follows the same rules.",
     ("cli", "eastwind showcase conformance adapters"), None),
    ("autonomy", "do", "Independence that is granted, not assumed",
     "Each agent has a level of independence, its own credentials, and authority delegated by a person for a time.",
     ("story", "do-authority"), None),
    ("blast", "do", "Limiting the damage",
     "Hard limits on reach, detection of unusual behavior, containment of tainted data, and system triggers.",
     ("cli", "eastwind showcase blastradius anomaly taint triggers"), None),
    ("proposals", "do", "Proposals and recovery",
     "Changes to documents are proposed first, and a compensating action can undo what went wrong.",
     ("cli", "eastwind showcase proposal recovery"), None),
    ("passport", "meet", "An open passport for every AI",
     "The register is exported in an open standard for private wealth management (PWM) that auditors and other systems can read.",
     ("story", "colleague-passport"), ("console", "/pwm")),
    # Part of Kognita, with no dedicated demonstration here (the README says so).
    ("claims", "more", "Checking claims before release", "Statements are verified against their sources before they are released.", ("none", ""), None),
    ("stale", "more", "Stale facts and definitions", "Controls for facts that have gone stale and for definitions that have changed.", ("none", ""), None),
    ("memory", "more", "Memory and learning rules", "What an agent may remember and learn from is governed.", ("none", ""), None),
    ("fairness", "more", "Fairness and evaluation gates", "A model must pass evaluation and fairness checks before it is used.", ("none", ""), None),
    ("reasoning", "more", "Reasoning-trace controls", "What a model says about its own reasoning is labelled and controlled.", ("none", ""), None),
    ("keys", "more", "Signing and key management", "Evidence can be signed, with keys that are rotated and revoked.", ("none", ""), None),
    ("anchors", "more", "External checkpoints and review", "Checkpoints can be published outside the system and reviewed by others.", ("none", ""), None),
    ("recovery", "more", "Recovery bundles", "Recovery bundles are available for restoring a deployment.", ("none", ""), None),
    ("dependency", "more", "Dependency and concentration reports", "How much depends on one provider or one model is reported.", ("none", ""), None),
    ("failover", "more", "Provider failover", "If a provider fails, calls can move to another approved one.", ("none", ""), None),
    ("incidents", "more", "Incident reporting", "Incidents and near misses are opened, tracked and closed with evidence.", ("none", ""), None),
    ("attestation", "more", "Runtime-assurance attestations", "A statement of what was assured at runtime can be produced.", ("none", ""), None),
)
CAPABILITY_GROUPS = {"meet": "Meet", "know": "Know", "do": "Do", "prove": "Prove", "break": "What if it breaks?",
                     "more": "More in Kognita"}
