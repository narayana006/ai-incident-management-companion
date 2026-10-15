# User guide

This guide is for readers of *AI-Driven Incident Management* who want to run the companion code
alongside the chapters. It assumes you can open a terminal and have used `git` once. Nothing
here requires cloud access, a Kubernetes cluster, or any package installation.

## 1. What the companion is, and is not

The companion is a set of small, deterministic programs, one per chapter mechanism. Each one
reads a constructed input under `fixtures/`, applies the rule the chapter describes, and writes
its result under `generated/`. Every output is committed, so you can read the results without
running anything, and you can re-run any target and confirm you get the identical bytes.

It is not a product, a service, or a live system. Every incident, dataset and score in it is
constructed for illustration and is labelled as such inside the file. Nothing in it contacts a
network, a cluster, or a cloud account. The one program that once did, the original
controller-conflict runner, is kept under `fixtures/ch06/K8S-01/` as evidence and exits
immediately if run.

## 2. Before you start

| Need | Notes |
|---|---|
| Python 3.11 or newer | Check with `python3 --version`. Nothing else to install. |
| `make` | Present on macOS and Linux. On Windows, use the direct commands in section 9 instead. |
| `git` | Only for cloning. You can also download a zip from the release page. |

## 3. Get the code

Use the release the book was built against:

```sh
git clone --branch v1.0.1 https://github.com/narayana006/ai-incident-management-companion.git
cd ai-incident-management-companion
```

Or open the Releases page on GitHub, download the zip for the same release, and unzip it
anywhere. The folder works from any location; it never reads or writes outside itself.

## 4. First run

```sh
make test
```

You should see the figures publish, then:

```
Ran 228 tests in 0.4s

OK (skipped=2)
```

The two skipped tests compare generated numbers against the book's manuscript files, which are
not part of the companion. Skipping them is expected. Anything other than `OK` means something
in the folder was changed; section 8 says how to restore it.

Then:

```sh
make help
```

prints every target with a one-line description.

## 5. How to read what it produces

Every target writes files under `generated/` (and the Chapter 2 ledger under `data/generated/`).
Each chapter has a Markdown report you can read directly, and a JSON or CSV file with the same
content for programs. Figures referenced in the book are published as SVG under
`generated/published-figures/` and can be opened in any browser.

Open the `.md` report first. It states what the run did, what it did not do, and the
limitations that apply. The JSON or CSV beside it holds every decision, reason code, and number.

## 6. Chapter by chapter

Run the command when the chapter tells you to, then open the files listed.

| Chapter | Command | Open | What to look for |
|---|---|---|---|
| 1 | `make ch01-replay` | `generated/ch01_context_brief.md` | Each evidence source's status: usable, stale, denied, or missing. The brief stops at a verification candidate; it never recommends an action. |
| 2 | `make ch02-baseline` | `generated/ch02_duration_summary.csv`, `data/generated/ch02_constructed_incident_ledger.csv`, `generated/figure-2-2-duration-distribution.svg` | The numbers in Table 2.1, and how mean, median, nearest-rank p95, and the three-longest share disagree on the same rows. |
| 3 | `make ch03-readiness` | `generated/ch03_layer_readiness_report.md`, `generated/ch03_layer_readiness_gaps.csv` | One gap row per missing field per layer. No score, no ranking. To assess your own services, copy `templates/ch03-layer-readiness.csv`, fill it in, and run `python3 scripts/ch03_readiness_report.py --input your-copy.csv`. |
| 4 | `make calibration` | `generated/ch04_calibration_bin_summary.csv`, `generated/ch04_calibration_interval_table.csv`, `generated/ch04_calibration_provenance.md`, `generated/figure-4-1-calibration-reliability.svg` | Per-bin observed rate with its finite-sample interval. The bin with ten of ten correct shows an interval of about 0.72 to 1.00, which is the chapter's point. |
| 5 | `make ch05-change-gate` | `generated/ch05/change_gate_decisions.json`, `generated/ch05/freeze_exception_packet.md`, `generated/published-figures/figure-5-1-*.svg` | Nineteen cases. Each HOLD carries reason codes such as `ACKNOWLEDGEMENT_MISSING`, `ARTIFACT_CHANGED_AFTER_APPROVAL`, `ACKNOWLEDGEMENT_BINDING_MISMATCH`. Silence never executes. |
| 6 | `make ch06` | `generated/ch06_guard_report.md`, `generated/ch06_guard_decisions.json`, `generated/ch06_k8s01_report.md`, `generated/ch06_k8s01_observations.csv`, `generated/figure-6-6-*.svg` | The guard's admit or demote per case with the cumulative budget before and after. In the K8S-01 table, the direct-write and setpoint rows are observed once each and the TTL row is `not_run`. |
| 7 | `make ch07-governed-agent` | `generated/ch07_governed_agent_report.md`, `generated/ch07_governed_agent_results.json` | Nineteen cases covering replay, scope, nonce reuse, injected tool output, and provenance tampering. Model output never carries authority fields through. |
| 8 | `make ch08-incident-replay` | `generated/ch08_incident_replay.md` | The two Late Arrival briefs cut from the same evidence boundary for two roles, and the sentinel's three-state result after the fix. |
| 9 | `make ch09-retrieval-eval` | `generated/ch09/retrieval_evaluation_report.md`, `generated/ch09/per_query_results.csv` | Hit@3 and Recall@3 reported separately, abstention scored on what was served, and the blocked-candidate counts. |
| 10 | `make ch10-human-boundary` | `generated/ch10_human_boundary_report.md` | Seven cases classified by a plain conjunction with no weighting. To try your own, copy `fixtures/ch10/human-boundary-cases.json` and run `python3 scripts/ch10_human_boundary.py --fixture your-copy.json`. |
| 11 | `make ch11-readiness` | `generated/ch11_readiness_report.md`, `generated/ch11_phase_0_gate_ledger.csv`, `generated/ch11_readiness_decision.json` | One recommendation, `continue`, `narrow`, `hold` or `stop`, driven by the worst gate, never an average. The committed example returns `narrow`. Templates for the risk register, cost sheet, and review agenda are under `templates/`. |

`make all` runs every chapter target in order.

## 7. Doing the Appendix C exercises

The exercises ask you to change an input and watch the mechanism respond. Two patterns:

**Scripts that accept your own input file.** Chapter 3 (`--input`), Chapter 9 (`--input`),
Chapter 10 (`--fixture`), and Chapter 11 (`--input`) take a path. Copy the fixture, edit the
copy, and pass it. The committed outputs are untouched.

**Scripts that read a fixed fixture.** Chapters 1, 2, 5, 6, 7 and 8 read their fixture from a
fixed path. Edit the fixture in place, run the target, read the result, then restore the file:

```sh
git checkout -- fixtures/ch01/evidence.json
```

If you downloaded a zip rather than cloning, keep a copy of the fixture before editing.

**Chapter 4 is pinned.** The calibration input is protected by a hash. If you edit it, `make
calibration` stops with `authoritative input hash mismatch` before anything runs. That is
deliberate: the chapter's numbers must come from the recorded input. To experiment, copy the
script's `INPUT_PATH` logic into a scratch script, or wait for a release that adds `--input`.

**Detecting drift.** Four targets have a verify mode that fails if any committed output no
longer matches its input: `make calibration-verify`, `make ch05-change-gate-verify`, the verify
half of `make ch09-retrieval-eval`, and `python3 scripts/ch08_incident_replay.py --verify`.
After an experiment, run them to confirm you have restored everything.

## 8. If something goes wrong

| Message | Meaning | Fix |
|---|---|---|
| `python3: command not found` or a version below 3.11 | Wrong or missing interpreter | Install Python 3.11+ and run `make PYTHON=python3.11 test`. |
| `make: command not found` | No `make` on this machine | Use the direct commands in section 9. |
| `pinned source file is missing` or `hash mismatch` | A file under `fixtures/ch04/` or `fixtures/ch06/K8S-01/` was edited or deleted | Restore it with `git checkout -- fixtures/` or re-download the release. |
| `FAILED (errors=…)` in `make test` | A fixture or output was changed | Run `git status` to see what changed, then `git checkout -- .` to restore. |
| `Chapter 5 generated artifacts are stale` | You edited a Chapter 5 input without regenerating | Run `make ch05-change-gate`, or restore the input. |

## 9. Running without make

Each target is one or two Python commands. On Windows, or anywhere without `make`, run these
from the companion folder with `python` or `python3`, whichever is 3.11 or newer.

```sh
python3 scripts/ch01_context_replay.py
python3 scripts/ch02_constructed_ledger.py
python3 scripts/ch03_readiness_report.py
python3 scripts/ch04_calibration_lab.py --write
python3 scripts/ch05_change_gate.py --write
python3 scripts/ch06_guard.py
python3 scripts/ch06_k8s_mechanism.py
python3 scripts/ch06_figures.py
python3 scripts/ch07_governed_agent.py
python3 scripts/ch08_incident_replay.py
python3 scripts/ch09_retrieval_eval.py --write
python3 scripts/ch09_retrieval_eval.py --verify
python3 scripts/ch10_human_boundary.py --verify
python3 scripts/ch11_readiness.py
python3 scripts/ch11_figures.py
```

To run the tests, publish the figures first, then run the suite:

```sh
python3 scripts/ch05_change_gate.py --write
python3 scripts/ch06_figures.py
python3 scripts/ch07_governed_agent.py
python3 scripts/ch11_readiness.py
python3 scripts/ch11_figures.py
python3 -m unittest discover -s tests -p "test_*.py"
```

## 10. What will never happen when you run this

- No connection to a Kubernetes cluster, a cloud account, or the network. There is no code path for it.
- No file written outside the companion folder.
- No deletion of anything you did not create.
- No production data read or produced. Every record is constructed and says so in the file.

## 11. Questions and problems

Open an issue on the repository's GitHub page. Include the command you ran, the full output, and
`python3 --version`.
