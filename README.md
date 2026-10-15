# AI-Driven Incident Management Companion

Companion code for the book *AI-Driven Incident Management*: reproducible
fixtures, calculations, figures, and labs for every chapter that cites a companion target.

No file under `fixtures/`, `generated/`, or `data/generated/` is production incident data.
Every dataset, generated output, and figure carries an in-file label such as
`illustrative_constructed` or `proposed_design`, and the chapter text says the same.

## Quick start

```sh
git clone https://github.com/narayana006/ai-incident-management-companion.git
cd ai-incident-management-companion
make test        # 228 tests, under a second
make all         # regenerate every artifact under generated/
make help        # list every target with a one-line description
```

Requirements: Python 3.11 or newer. Standard library only. Nothing to install, no network
access, no cloud credentials, no container runtime. Nothing writes outside this directory.
Pass a different interpreter with `make PYTHON=python3.11 test`.

New to this? Read [docs/USER-GUIDE.md](docs/USER-GUIDE.md): what to run for each chapter, which
files to open, how to do the Appendix C exercises, and how to run without `make`.

## Layout

| Directory | Contents |
|---|---|
| `scripts/` | One script per chapter mechanism. Each is runnable on its own and through `make`. |
| `tests/` | Unit and adversarial tests. `make test` publishes the figures it checks first, so it is self-contained. |
| `fixtures/` | Constructed inputs, including the pinned CAL-01 calibration input (`ch04/`) and the pinned K8S-01 experiment record (`ch06/K8S-01/`). |
| `generated/` | Every output a target produces, committed so drift is visible. Published figures land in `generated/published-figures/`. |
| `data/generated/` | The constructed Chapter 2 incident ledger. |
| `templates/` | Worksheets and packets the chapters ask the reader to copy and fill in. |
| `diagrams/src/` | Accessible SVG and JSON figure sources, with hand-recorded render reviews under `diagrams/qa/`. |
| `labs/` | Protocol documents only. There is no runnable live target; `labs/controller_conflict/README.md` explains why. |

## Targets

```sh
make ch01-replay
make ch02-baseline
make ch03-readiness
make calibration
make calibration-verify
make ch05-change-gate
make ch05-change-gate-verify
make ch06-guard
make ch06-k8s-mechanism
make ch06-figures
make ch06
make ch07-governed-agent
make ch08-incident-replay
make ch09-retrieval-eval
make ch10-human-boundary
make ch11-readiness
make test
make all
make clean
```

`make ch01-replay` assembles the Chapter 1 cited brief from constructed,
source-scoped evidence. The comparison is deterministic and stops at a
responder-verification candidate; it never changes production.

`make ch02-baseline` regenerates the illustrative Chapter 2 incident ledger,
summary, and duration-band figure using only the Python standard library.

`make ch03-readiness` validates the fourteen-layer worksheet and writes gap
reports by layer and contract field. The output is a read-only decision aid: it
does not rank layers, infer work priority, or authorize a production action.
Start with `templates/ch03-layer-readiness.csv`, replace the blank ownership
and evidence fields, and link evidence for every `true` contract field.

`make calibration` regenerates the Chapter 4 CAL-01 bin summary, finite-sample
interval table, reliability figure, provenance note, and run manifest from one
pinned 254-row fixture at `fixtures/ch04/CAL-01/synthetic_smoke.csv`. Every row
is `illustrative_constructed`. The lab rejects correlated duplicate rows and
version pooling, and has no network or production write path. Its 0.70 and
0.90 lines are illustrative design values, not recommendations.
`make calibration-verify` fails when the input hash or a committed output drifts.

`make ch05-change-gate` evaluates nineteen constructed change cases. It writes
exact proposal and evidence bindings, a declared/live comparison, a
freeze-exception packet, an execution-time recheck record, and Figures 5.1–5.2.
The negative cases cover missing, denied, partial, stale, and conflicting
evidence; silence and timeout; an acknowledgement bound to a stale artifact;
changed artifact and scope; interacting work;
current-policy stop; wrong executor; verification failure; idempotent retry;
and gate self-change. Each acknowledgement in the fixture carries the
`decision_binding_sha256` its signer computed from the proposal and evidence the
signer saw; the gate recomputes that hash and holds on mismatch, so editing the
fixture's evidence, policy, or catalog invalidates the committed
acknowledgements by design. The executor records a simulated effect and has no
production credential. The demonstration exercises the proposed binding
mechanics; it does not establish change safety or an effect on approval time or
failures. `make ch05-change-gate-verify` fails when the committed packet,
decisions, comparisons, manifest, or figures drift from their sources.

`make ch06-guard` runs a constructed, deterministic blast-radius guard. It
validates typed evidence, current controller ownership, action-class and
executor scope, useful serving headroom, an exercised inverse, and a cumulative
impact vector. Its process-local single writer makes check-and-reserve atomic
for the fixture, tests concurrent admission and idempotent retry, and simulates
the admitted effect without an external write. This demonstrates mechanics; it
does not establish production safety or distributed durability.

`make ch06-k8s-mechanism` is read-only with respect to the K8S-01 record under
`fixtures/ch06/K8S-01/`. It verifies pinned hashes, exact endpoint names, and
the two committed sequential runs, then regenerates a manifest, observation
table, report, and Figure 6.6. The direct-write and setpoint treatments each
have one completed run in one disposable configuration. The TTL treatment is
marked `not_run`. No comparative, safety, user-outcome, or production inference
is supported. The legacy runner that produced the record is kept in the same
directory as evidence and exits immediately if executed.

`make ch06-figures` validates the accessible SVG sources under `diagrams/src/`
and publishes Figures 6.1–6.5 to `generated/published-figures/`. `make ch06`
runs all three Chapter 6 targets.

`make ch07-governed-agent` runs nineteen constructed negative and ambiguity
cases through the Chapter 7 boundary and publishes Figures 7.1–7.3. The fixture
resolves required evidence from class policy, binds canonical action/evidence/
validation digests, validates per-call server and caller scope, atomically
claims a nonce across simulated executor replicas, distinguishes replay from
target idempotency, and reconciles a crash after simulated target acceptance.
It also tests retrieved and tool-output injection, catalog change,
cross-environment scope, poisoned agent messages, coordinator failure, planning
limits, provenance alteration, and an indeterminate target. The target has no
external write path. Passing demonstrates only deterministic fixture behavior;
it is not production-security, cryptographic, distributed-durability, or
exactly-once evidence.

`make ch08-incident-replay` replays one constructed incident through the
Chapter 8 lifecycle on a symbolic clock: state transitions with authority
checks, two role-scoped Late Arrival briefs cut from the same evidence
boundary, a tri-state post-fix sentinel (`recovery_supported`,
`recovery_not_supported`, `indeterminate`), publication gating by audience, and
a close record with residual risk. Every artifact is written to
`generated/ch08_incident_replay.json`. Nothing in it is a measured production
result.

`make ch09-retrieval-eval` scores ten constructed retrieval queries against a
small runbook corpus and writes per-query results, aggregate metrics, and a
report under `generated/ch09/`. It applies lifecycle, scope, access, and
hostile-content eligibility before anything is served, scores abstention on
the served artifact, and treats instruction-like retrieved text as untrusted
data. Hit@K and Recall@K are reported separately: Hit@K is 1 when any adequate
document reached the responder, Recall@K is the share of a query's adequate
documents that reached it. Both read 5 / 7 here, and only because every
answerable query in this fixture has exactly one adequate document; the unit
tests score a constructed query with two adequate documents of which one is
served, where Hit@3 is 1.000 and Recall@3 is 0.500. The last five report rows
are measured invariants rather than rates: their numerators are re-derived from
the served artifact, so a weakened eligibility filter shows up as a non-zero
count. The target runs `--write` and
then `--verify`, so a drifted committed output fails the target. The fixture is
explicitly illustrative; the metrics demonstrate definitions, not retrieval
quality.

`make ch10-human-boundary` classifies the seven Chapter 10 tabletop cases in
`fixtures/ch10/human-boundary-cases.json` as human-owned, blocked, or eligible
for policy evaluation, using a plain conjunction with no weighting, and fails
if any classification disagrees with the case's expected answer. The
classifier does not read the expected field, so the check is real.

`make ch11-readiness` validates the Chapter 11 Phase 0 gate ledger, emits the
fixed-policy recommendation `continue`, `narrow`, `hold`, or `stop`, builds a
planning-only ninety-day starter plan, writes provenance, and publishes Figures
11.1–11.2. Every catalogued gate is required. Unsatisfied, unverified, or
expired gates remain visible and cannot be weighted or averaged away. The
reader may not edit each gate's failure disposition. A reviewed `not_applicable`
state is limited to the consequence gate for early read-only work and requires
an evidence record, owner, distinct reviewer, reason, expiry, recertification
trigger, and next action. The tool emits no readiness percentage or action
authority. Start from `fixtures/ch11/readiness-assessment.json`; the committed
example is explicitly illustrative and correctly returns `narrow` for an
unsupported evidence source. Supporting risk, cost/ownership, governance, and
starter-plan templates live under `templates/`. The mechanism checks the fixed
catalog, schema, required references, roles, dates, expiry, and state semantics;
it does not dereference evidence or verify that a reader-recorded state is true.

## Publishing figures into a book build

By default every figure-publishing target writes to `generated/published-figures/`.
To publish into a manuscript tree instead, set `BOOK_FIGURE_ROOT`:

```sh
BOOK_FIGURE_ROOT=../manuscript-v4/figures make ch06-figures
```

Each figure manifest records `published_path` as the location the run actually
wrote to: relative to the companion root when the figure stays inside it,
absolute when it is published into an external tree. A manifest never claims a
path the run did not write, which also means `make ch05-change-gate-verify`
only passes against figures published to the default root.

## License

MIT. See `LICENSE`.
