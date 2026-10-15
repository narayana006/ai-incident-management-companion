# Chapter 8 constructed incident replay

> Constructed fixture; demonstrates record behavior, not production performance.

- Incident: `incident-constructed-08`
- Replay digest: `57600fedfb9c296c0aa00354834bf5a738577d04b5712032dc76eb9f1c9bbccb`
- Lifecycle: `detected -> acknowledged -> assessed -> coordinated -> mitigating -> verifying_recovery -> monitoring -> closed -> reopened`
- Action result: `verified`
- Incident command: `human_only`

## Late Arrival briefs

- Technical responder: cutoff `sequence-08`, 3 visible claims.
- Communication owner: cutoff `sequence-08`, 1 visible claims.
- The briefs are read-only and carry no execution authority.

## Post-fix sentinel

- `all-required-criteria-pass`: `recovery_supported` (expected `recovery_supported`)
- `required-criterion-fails`: `recovery_not_supported` (expected `recovery_not_supported`)
- `required-source-missing`: `indeterminate` (expected `indeterminate`)

The sentinel reports evidence state only. A human commander retains recovery,
residual-risk, close, and reopen authority.
