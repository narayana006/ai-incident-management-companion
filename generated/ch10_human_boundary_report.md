# Chapter 10 Human-Boundary Tabletop

> Constructed rule explanation. This report grants no production authority and does not score people.

- Policy version: `human-boundary-policy-1`
- Fixture digest: `3266b120ae959d4761dcb1243be4112d53376215d734de0c8fde8b07cd817324`
- Cases: 7
- Expected classifications matched: 7

| Case | Result | Human owned | Unattended path | Reasons |
|---|---|---:|---:|---|
| bounded-validated-restart | `eligible_for_policy_evaluation` | no | allowed for policy evaluation | all declared gates satisfied |
| new-controller-and-population | `human_owned_unattended_blocked` | yes | blocked | NOVEL_OR_OUTSIDE_POLICY, BOUNDS_INCOMPLETE, INVERSE_NOT_CURRENT_AND_EXERCISED, POPULATION_NOT_VALIDATED |
| external-recovery-commitment | `human_owned` | yes | blocked | COMMITMENT_REQUIRES_HUMAN, ORGANIZATIONALLY_SENSITIVE |
| close-with-indeterminate-user-path | `human_owned_unattended_blocked` | yes | blocked | COMMITMENT_REQUIRES_HUMAN, ORGANIZATIONALLY_SENSITIVE, EVIDENCE_NOT_CURRENT_AUTHORIZED_AND_SCOPED |
| staffing-from-operational-traces | `human_owned_unattended_blocked` | yes | blocked | COMMITMENT_REQUIRES_HUMAN, NOVEL_OR_OUTSIDE_POLICY, ORGANIZATIONALLY_SENSITIVE, PEOPLE_DECISION_REQUIRES_HUMAN, ACTION_CLASS_NOT_VALIDATED, BOUNDS_INCOMPLETE, EVIDENCE_NOT_CURRENT_AUTHORIZED_AND_SCOPED, INVERSE_NOT_CURRENT_AND_EXERCISED, POPULATION_NOT_VALIDATED |
| destructive-unexercised-restore | `human_owned_unattended_blocked` | yes | blocked | NOVEL_OR_OUTSIDE_POLICY, ACTION_CLASS_NOT_VALIDATED, BOUNDS_INCOMPLETE, INVERSE_NOT_CURRENT_AND_EXERCISED |
| missing-cumulative-impact-dimension | `human_owned_unattended_blocked` | yes | blocked | BOUNDS_INCOMPLETE |

## Interpretation

- Constructed cases explain a boundary and are not production evidence.
- A result never grants authority or proves an action safe.
- Human-owned decisions remain subject to organizational review and accountability.

Run digest: `bee77a3c4f7b33cd40e025392dd630fe70cbafe4f39db2add92996cd56e0053e`
