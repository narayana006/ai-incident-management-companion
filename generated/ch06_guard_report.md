# Chapter 6 Guard Fixture Report

> Constructed mechanism demonstration. It tests deterministic demotion,
> serialized reservation, and executor scope; it does not establish production safety.

| Case | Outcome | Reasons | Reservation | Idempotent replay |
|---|---|---|---|---|
| `valid-first` | `admit` | — | `RSV-bac428a56e862f88` | `false` |
| `idempotent-retry` | `admit` | — | `RSV-bac428a56e862f88` | `true` |
| `stale-serving-evidence` | `demote` | EVIDENCE_STALE:serving | `—` | `false` |
| `denied-serving-source` | `demote` | EVIDENCE_DENIED:serving | `—` | `false` |
| `direct-write-against-owner` | `demote` | CONTROLLER_SURFACE_MISMATCH, EXECUTOR_SCOPE_DENIED | `—` | `false` |
| `executor-scope-denied` | `demote` | TARGET_OUT_OF_CLASS_SCOPE, EVIDENCE_SUBJECT_MISMATCH:serving, EVIDENCE_SUBJECT_MISMATCH:owner, EVIDENCE_SUBJECT_MISMATCH:reliability, EXECUTOR_SCOPE_DENIED | `—` | `false` |
| `inverse-not-verified` | `demote` | INVERSE_NOT_VERIFIED | `—` | `false` |
| `valid-second` | `admit` | — | `RSV-144a1c8df2208c5a` | `false` |
| `cumulative-budget-exceeded` | `demote` | CUMULATIVE_BUDGET_EXCEEDED | `—` | `false` |

## Serialized reservation ledger

| Reservation | Actor | Class | State | Impact vector |
|---|---|---|---|---|
| `external-human-1` | `recorded_human_action` | `external-record@recorded` | `spent` | capacity_units_removed=0; failure_domains_affected=0; user_exposure_units=5; persistent_state_writes=0; canonical_policy_units=0 |
| `RSV-bac428a56e862f88` | `guarded_executor` | `worker_evict@1` | `reserved` | capacity_units_removed=1; failure_domains_affected=1; user_exposure_units=10; persistent_state_writes=0; canonical_policy_units=1 |
| `RSV-144a1c8df2208c5a` | `guarded_executor` | `worker_evict@1` | `reserved` | capacity_units_removed=1; failure_domains_affected=1; user_exposure_units=10; persistent_state_writes=0; canonical_policy_units=1 |

The ledger is an in-memory, process-local single writer. A production guard needs a
durable strongly consistent store or equivalent serialization mechanism, plus crash
reconciliation. The fixture makes no production, performance, or safety claim.
