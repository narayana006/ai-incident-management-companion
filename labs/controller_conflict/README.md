# Controller-conflict lab (K8S-01)

There is no runnable live target in this directory, on purpose.

The Chapter 6 controller-conflict experiment, K8S-01, ran once per treatment in one disposable
`kind` cluster. Its record is preserved under `fixtures/ch06/K8S-01/` and pinned by SHA-256 in
`fixtures/ch06/k8s01_source_manifest.json`. `make ch06-k8s-mechanism` verifies those pins and
regenerates the observation table, report, and Figure 6.6 from the record. It never contacts a
cluster.

The legacy runner that produced the record, `fixtures/ch06/K8S-01/runner.py`, is kept as evidence
and exits immediately if executed. It does not meet the release conditions in
`LIVE-PROTOCOL.md`, which lists what a future `make ch06-k8s-live` target must satisfy before it
can ship: pinned image digests, an offline metrics manifest, a fresh cluster per run, cleanup on
every exit path, and no time-to-live treatment until an expiring-override controller exists.

Do not point anything in this repository at a shared or production cluster.
