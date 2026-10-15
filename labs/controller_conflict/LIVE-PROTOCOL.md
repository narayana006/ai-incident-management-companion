# Optional K8S-01 live protocol — release hold

The publication command is intentionally read-only:

```sh
make ch06-k8s-mechanism
```

It validates and renders the committed mechanism evidence. It does not create a
cluster or imply that a new trial ran.

The legacy runner under `fixtures/ch06/K8S-01/runner.py` is preserved as part of
the evidence record and is **not** the publication live path. It currently:

- uses tagged rather than digest-pinned images;
- ignores non-zero exit codes from create, patch, scale, read, and restore
  commands;
- reuses one namespace and one cluster across treatments;
- assumes the resource-metrics API works instead of making it a precondition;
- writes into a shared trial index before a guaranteed cleanup decision; and
- has no `finally` path that proves the disposable environment was destroyed.

Do not run that file for a book exercise.

## Gate for adding a live target

A future `make ch06-k8s-live` may ship only when the repository includes and
tests all of the following:

1. A reviewed cluster-node image, workload image, load-generator image, and
   metrics-server image pinned by full `sha256` digest. Tags are metadata, not
   pins.
2. An offline metrics-server manifest whose bytes and image digest are pinned
   in the lab manifest. A fresh cluster must fail preflight until
   `pods.metrics.k8s.io` returns a usable sample for the target workload.
3. A new disposable cluster and namespace for every run. The generated context
   must match the run-specific kind context; a shared or production context is
   an unconditional stop.
4. Exact tool-version checks for `kind` and `kubectl`, plus the server version
   written into the run manifest.
5. Every external command executed without a shell, with its exit code checked.
   Standard output and standard error go to a step-specific file inside the
   run directory. One failed command makes the run incomplete.
6. Separate directories for samples, events, cluster metadata, command logs,
   and the manifest. A run directory is never reused or appended.
7. A `finally` cleanup path that deletes the exact run cluster. Cleanup failure
   leaves `completed=false`, records `cleanup_failed`, and returns a non-zero
   exit. No failed or partially cleaned run enters the completed summary.
8. Predeclared endpoint paths and outcomes. The four endpoints are:
   `HorizontalPodAutoscaler/cpu-svc.spec.maxReplicas`,
   `HorizontalPodAutoscaler/cpu-svc.status.desiredReplicas`,
   `Deployment/cpu-svc.spec.replicas`, and
   `Deployment/cpu-svc.status.readyReplicas`.
9. Treatment order and independent units declared before execution. A
   replicated study also needs randomized order, failure accounting, and an
   analysis plan. One run per treatment remains a mechanism observation.
10. TTL stays absent until its cleanup path, failure behavior, and cleanup
    evidence have actually been executed. Code presence is not evidence.

## Current blocker

The repository does not contain reviewed image digests or a pinned offline
metrics-server manifest for a new disposable run. Inventing those values would
turn a safety repair into theatre. The live target therefore remains withheld.
This is a release hold on optional new evidence, not a blocker for the
read-only committed-evidence command or the chapter's bounded mechanism claim.
