# Chapter 5 Freeze-Exception Packet

> Constructed illustration. This packet supports a named human decision; it
> does not approve the exception, prove safety, or establish complete dependency
> coverage.

## Proposal binding

- Proposal: `P-FREEZE-001`
- Proposal binding: `sha256:e12d83b9fc7e9162d37f350358cef0a871a6b283746db54b9c263fff22218d0f`
- Exact artifact: `sha256:ef7c37009538f2f6ecd36c665ff375282a1c83a6839b6ef2bacfcc2beb5b57a1`
- Resolved targets: `route-a`
- Requested authority path: `named_positive_acknowledgement`
- Proposer production write credential: `none`

The deadline and justification are assertions by `request-owner`; they are not
authorization tokens.

## Decision-time evidence

Snapshot: `sha256:a78a87c2030a222306c3c39e453deab7efbbe0044dcebe9cf3423277c33482bd`

| Claim | State | Evidence ID | Freshness | Source health |
|---|---|---|---|---|
| `declared_configuration` | `usable` | `E-DECLARED-OK` | `within_policy` | `healthy` |
| `current_configuration` | `usable` | `E-LIVE-DECISION-OK` | `within_policy` | `healthy` |
| `in_flight_changes` | `usable` | `E-INFLIGHT-DECISION-NONE` | `within_policy` | `healthy` |
| `dependency_coverage` | `usable` | `E-DEPENDENCY-DECISION-OK` | `within_policy` | `healthy` |
| `canonical_reliability_state` | `usable` | `E-RELIABILITY-DECISION-GO` | `within_policy` | `healthy` |
| `signer_authority` | `usable` | `E-AUTHORITY-OK` | `within_policy` | `healthy` |

## Declared/live comparison

| Subject | Field | Declared | Observed | Result |
|---|---|---|---|---|
| `route-a` | `owner` | `"service-a"` | `"service-a"` | `match` |
| `route-a` | `route_mode` | `"shared"` | `"shared"` | `match` |
| `route-a` | `security_boundary` | `"boundary-a"` | `"boundary-a"` | `match` |

## Dependency interpretation

- Coverage status: `bounded_complete_for_policy`
- Checked classes: `synchronous, asynchronous, shared_state, recovery`
- Excluded classes: `none recorded`
- Observed reachable subjects: `service-b`
- Interpretation: a lower bound under the stated representation and window;
  it is not a maximum blast-radius claim.

## Preconditions, stop, and recovery

- Preconditions: all required evidence is usable under claim-specific policy.
- Preconditions: declared and scoped live configuration match on the touched subject.
- Preconditions: no interacting change is reported in the stated scope.
- Preconditions: the canonical reliability policy permits the change.
- Stop on: `target-state-mismatch`.
- Stop on: `canonical-reliability-policy-block`.
- Stop on: `verification-source-unavailable`.
- Verification: `exact-target-state`.
- Reviewed reversal: `restore-reviewed-snapshot`.

## Authority

- Current status: `AWAITING_POSITIVE_ACKNOWLEDGEMENT`
- Policy: `ch05-change-gate-policy@1.0.0`
- Decision expires: `2026-02-10T12:05:00Z`
- Silence: `HOLD`
- Required executor: `change-executor-v1`
- A separately credentialed executor rechecks artifact, scope, policy,
  evidence, signer authority, and state immediately before simulated execution.

## Alternatives retained

- **automatic exception approval:** the action is outside the human-approved standard catalog.
- **approval by timeout:** silence carries no authority.

## Provenance

- Transformation: `ch05-change-gate-v1.0.0`
- Packet payload: `sha256:dcc1cee2fdbc50a3a703ab84bf99533b897fd6035d2c01b9ea6548a82eaddb15`
- `policy`: `sha256:1ce2dc3bc78cceefcfd7d7a2be106c4d86606ff2e3a4502c49a0652d6d9f21e1`
- `catalog`: `sha256:1c69230704ca8cae4e34c67933223ba274b7be402a9be1c9d496899109a98cb8`
- `scenarios`: `sha256:1dd5928bff4902915894f230b00d9bc125918d8915636a6e06d94cb6875830c7`
- `template`: `sha256:d0e941a98f008042bc9785966dfcebe2447e86ab8f7a04c2b99643dc1735281d`
