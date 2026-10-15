# Chapter 5 constructed change-gate fixtures

These files contain generic, constructed records. They are not production
change data and do not establish that a change is safe.

From the `companion` directory, run:

```sh
make ch05-change-gate
```

The command evaluates every case without a network connection or production
credential. It writes an inspectable decision ledger, declared/live comparison,
freeze-exception packet, and provenance manifest under `generated/ch05/`.

The `policy.json` values are demonstration values. They are not a universal
freshness policy, approval window, or standard-change catalog.
