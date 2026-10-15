# K8S-01 Committed-Evidence Report

> Observed once in the stated test environment; mechanism demonstration only.
> The default command reads committed files and does not create a cluster or execute a treatment.

## Exact endpoints

- Controller input: `HorizontalPodAutoscaler/cpu-svc.spec.maxReplicas`
- Controller decision: `HorizontalPodAutoscaler/cpu-svc.status.desiredReplicas`
- Owned target field: `Deployment/cpu-svc.spec.replicas`
- Observed workload state: `Deployment/cpu-svc.status.readyReplicas`

## Recorded treatments

| Run | Treatment | Status | Independent unit | Observation |
|---|---|---|---|---|
| `S01A` | `direct_write` | `completed` | one sequential run in one disposable configuration | The active controller overwrote the direct desired-state write in this recorded run. |
| `S01B` | `setpoint_override` | `completed` | one sequential run in one disposable configuration | Changing the active controller's configuration changed the governed state in this recorded run. |
| `NOT-RUN` | `ttl_override` | `not_run` | no completed run | No completed TTL treatment exists in the committed evidence. |

The two completed treatments were run sequentially, not randomized or replicated.
The legacy summary's combined timing and oscillation columns are retained as raw
record fields but are not used for a comparative, frequency, convergence, or safety claim.

## Unsupported inferences

- comparative speed
- safety
- general performance
- oscillation frequency
- production generalization
- TTL cleanup
- user-facing improvement
