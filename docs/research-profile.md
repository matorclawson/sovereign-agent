# A persistent research investigation

The research profile specializes the same Python agent. The shop remains the
default. Start with a fresh root; mixing shop, research and organization roots is
refused. The only authoritative lifecycle database is `<root>/agent.sqlite`.

```sh
sovereign-agent agent init --profile research --root ./research
sovereign-agent agent ask 'Find a low value of the bounded synthetic objective; compare to x=0 and state uncertainty.' --profile research --root ./research
```

Save the returned investigation identifier. Use it as `INVESTIGATION` below.
`status` without `--id` lists investigations. The question is a core Outcome;
immutable objective revisions, queue associations, operations and observations
reside in that same database. `assistant_work` owns claims, generations and restore
epochs. This profile's role is `investigation`; the older catering `research`
worker is unrelated.

```sh
sovereign-agent agent status --profile research --root ./research --id "$INVESTIGATION"
sovereign-agent agent serve --profile research --root ./research
sovereign-agent agent pause --profile research --root ./research --id "$INVESTIGATION"
sovereign-agent agent redirect 'Prioritize interpreting existing measurements; do not claim global optimality.' --profile research --root ./research --id "$INVESTIGATION"
sovereign-agent agent resume --profile research --root ./research --id "$INVESTIGATION"
sovereign-agent agent report --profile research --root ./research --id "$INVESTIGATION"
```

Without `--live`, `work` and `serve` perform mechanical collection only. A live
reasoning worker requires an explicitly authorized `SOVEREIGN_AGENT_LLM_MODEL`,
the existing OpenAI-compatible `SOVEREIGN_AGENT_LLM_BASE_URL`, and optional key in
`SOVEREIGN_AGENT_LLM_API_KEY`; append `--live --reasoning-effort provider-default`.
This neither provisions an endpoint nor grants provider spending. No model is
prescribed. `work` performs one wake; `serve` keeps durable availability with a
one-second local readiness check and no inference while idle. SIGINT/SIGTERM stop
the supervisor. Restart the same command and root. No organizational scheduler,
ZEO service installation, or web application is needed.

The first adapter can only measure a fixed deterministic synthetic objective at
`x` in `[-2,2]`. The model may choose a sample or replication, wait, interpret,
stop, or escalate, with reasons, a revisable belief and observation identities.
Its assertions remain interpretations. A model stop moves the Outcome to
VERIFYING, never operator acceptance. A changed objective revokes earlier plans;
collection of launched work stays permitted. Pause also revokes live plans;
resume does not restore their authority.

Every investigation reserves at most 12 inference requests, 12,000 output tokens,
24 admitted scientific actions and 12 evaluations cumulatively. Its objectives,
observations and history do not expire. An execution campaign lasts at most 600
seconds and draws only on the remaining cumulative allowance. Each request
reserves up to 2,000 output tokens before transport, including lost replies,
with a 32,768-byte context limit, 120-second request limit and one sequential
request. Counters survive restarts and revisions. They do not measure provider
billing or authorize API spend. Expiry or an invalid reply holds the queue for
operator inspection; there is no automatic model retry. Resume can enqueue a new
reasoning turn within the original budget. Status includes counters, next wake,
pending operations and recent interpretations; report gives the full history.
The shared inference lease survives objective redirection; a lost client holds
the lane for at most 180 seconds before another bounded request is admitted.

When a campaign expires, the investigation waits for an explicit authorized
allowance. `resume` cannot reset use or bypass an expired campaign. For example:

```sh
sovereign-agent agent allow --profile research --root ./research --id "$INVESTIGATION" --key session-2 --campaign-seconds 300 --campaign-calls 3 --evidence 'operator authorization reference'
sovereign-agent agent resume --profile research --root ./research --id "$INVESTIGATION"
```

Use a new session key for a new authorization. Reusing a key never refreshes its
clock or counters. New campaigns cannot raise the cumulative ceilings. The old
schema's initial deadline is preserved as migration history and grants no
execution authority. Status lists campaign counters, the cumulative counters,
and reservation records. The `calls` counter conservatively charges transport
attempts, including attempts later proven not to have performed inference.
Acknowledged token use is consumed; unused reservation is released. Missing
acknowledgement stays UNKNOWN with its entire exposure reserved. Only the
operator can release a proven zero-inference reservation, using
`release-inference no-inference --key RESERVATION --evidence PROOF`. This does
not reset the attempt count or erase the original events.

The approved subscription route is available through normal operation:

```sh
sovereign-agent agent work --profile research --root ./research --live --research-provider claude-subscription
sovereign-agent agent serve --profile research --root ./research --live --research-provider claude-subscription
```

This uses the existing Claude Code CLI with `claude-fable-5-1`, safe/restricted
mode, no provider tools, MCP or skills, one turn, no retries and the runtime's
time/output limits. The operator explicitly selected this existing subscription
route; the rejected literal zero-budget flag is omitted. API-key overrides are
refused. A CLI API-price valuation is recorded separately from billing; it is
not proof of an invoice or an enforceable dollar ceiling. Other operators must
establish their own authorized access contract. No provider installation,
credential copying or account/billing reconfiguration is performed here.

Operation intent precedes submission. Executor files under `.sovereign/executor/`
represent external work; the database alone grants authority. Stable operation
identity and an exclusive worker claim prevent duplicate measurements across a
lost acknowledgement. A claimed worker that dies before writing its result is
uncertain and is held rather than evaluated again. These guarantees apply to
this fixture, not arbitrary executors. Request cancellation using:

```sh
sovereign-agent agent cancel --profile research --root ./research --key "$OPERATION"
```

Cancellation is best effort: an already completed measurement is retained. Late
results carry their original objective revision and require fresh interpretation.
Malformed and conflicting results are held with their bytes preserved; they are
not silently repaired or admitted as new evidence. Proposal artifacts stay in
`.sovereign/runs/<work_id>/`; observation receipts and digests live in SQLite.

Status includes reasons and supported recovery actions. `work` without `--live`
collects late receipts and retires expired inference ownership without inference;
unknown usage remains charged. `recover --key OPERATION --evidence REVIEW` can
withdraw a provably undispatched fixture intent (no request/claim/result exists)
and fences its old plan. It can clear a conflict only after the operator restores
the exact originally accepted receipt. Neither operation repeats an experiment.
A dead claimed executor without a receipt remains UNKNOWN: request cancellation,
collect an eventual original receipt, or preserve it for operator diagnosis.
There is no automatic repeat or silent indefinite hold. Receipt reads refuse
FIFOs, devices, directories and symlinks without blocking.

This finite slice has no paper ingestion, arbitrary code execution, general
scientific memory graph, manuscript tools or delegation. Evidence must be treated
as untrusted data, never instructions granting tool access. Executing third-party
research code requires a separately approved isolation adapter; the owned fixture
subprocess is not such a boundary. The deterministic tests demonstrate lifecycle
mechanics, separately from any live-model scientific evaluation.
