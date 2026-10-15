# Constructed Chapter 1 Context Brief

> Illustrative fixture. This is not production incident data or a model-performance result.

**Replay cutoff:** `2026-01-01T00:05:00Z`  
**Freshness policy:** `ch01-replay-freshness@1.0.0`

## Required-source status

| Evidence | Class | Subject | Retrieval | Authorization | Health | Computed freshness | Age / max (s) |
|---|---|---|---|---|---|---|---:|
| `E-01` | live_state_observation | `public-surface-a` | retrieved | allowed | healthy | within_policy | 29 / 120 |
| `E-02` | recorded_intent | `public-surface-a` | retrieved | allowed | healthy | within_policy | 2678700 / 2764800 |
| `E-03` | live_state_observation | `route-object-a` | retrieved | allowed | healthy | within_policy | 23 / 120 |
| `E-04` | live_state_observation | `protection-control-a` | retrieved | allowed | healthy | within_policy | 20 / 120 |
| `E-05` | recorded_intent | `route-object-a` | retrieved | allowed | healthy | within_policy | 4061100 / 5184000 |

## Inspectable evidence references

| Evidence | Source | Adapter | Calling principal | Valid time | Retrieval time | Verified immutable reference |
|---|---|---|---|---|---|---|
| `E-01` | `edge_telemetry` | `edge-read-v1` | `incident-evidence-edge-reader` | `2026-01-01T00:04:30Z` | `2026-01-01T00:04:35Z` | `sha256:273098d99e7b7d2a51b0c3de8f70ed925dd4dff10ff254f803ef5da2b5cd7652` |
| `E-02` | `architecture_record` | `record-read-v1` | `incident-evidence-record-reader` | `2025-12-01T00:00:00Z` | `2026-01-01T00:04:36Z` | `sha256:6b74f3a70b0b248e306ab4eac2f157ba55234b0ccc78af12b23ab9bd69d4a3df` |
| `E-03` | `routing_state` | `route-read-v1` | `incident-evidence-route-reader` | `2026-01-01T00:04:38Z` | `2026-01-01T00:04:39Z` | `sha256:f45482b75f83e45e658f23e31757294ca744e7b8a9339de1a3b7ac38381741ea` |
| `E-04` | `protection_counters` | `counter-read-v1` | `incident-evidence-counter-reader` | `2026-01-01T00:04:40Z` | `2026-01-01T00:04:41Z` | `sha256:ecb3a35a9a79a66c187e7f439f9bc09498d8e47821ee4f0c4d40c03cba50d376` |
| `E-05` | `change_record` | `change-read-v1` | `incident-evidence-change-reader` | `2025-11-15T00:00:00Z` | `2026-01-01T00:04:42Z` | `sha256:a7e3d3d3345b3f02db8ecf89203d676996efee0231cb9febd4f329755d09f082` |
| `E-06` | `deterministic_context_assembler` | `local-fixture-replay-v2` | `local-read-only-replay` | `2026-01-01T00:05:00Z` | `2026-01-01T00:05:00Z` | `sha256:eddfa1291e067165ac451c546b6b0ffe2a994a8614eafdbd12d8948dad593875` |

### Exact source coverage and query parameters

```json
{
  "E-01": {
    "coverage": {
      "surface": "public-surface-a",
      "region": "region-a",
      "window_start": "2026-01-01T00:00:00Z",
      "window_end": "2026-01-01T00:05:00Z"
    },
    "query_parameters": {
      "metric": "edge_pressure_and_service_errors",
      "surface": "public-surface-a",
      "window_start": "2026-01-01T00:00:00Z",
      "window_end": "2026-01-01T00:05:00Z"
    }
  },
  "E-02": {
    "coverage": {
      "surface": "public-surface-a",
      "record_version": "design-v7"
    },
    "query_parameters": {
      "subject": "public-surface-a",
      "version": "design-v7"
    }
  },
  "E-03": {
    "coverage": {
      "surface": "public-surface-a",
      "region": "region-a",
      "route_object": "route-object-a"
    },
    "query_parameters": {
      "route_object": "route-object-a",
      "surface": "public-surface-a",
      "include_effective_next_hops": true
    }
  },
  "E-04": {
    "coverage": {
      "surface": "public-surface-a",
      "region": "region-a",
      "protection_control": "protection-control-a",
      "window_start": "2026-01-01T00:00:00Z",
      "window_end": "2026-01-01T00:05:00Z",
      "filter": "traffic_class=affected"
    },
    "query_parameters": {
      "counter": "evaluated_requests",
      "surface": "public-surface-a",
      "window_start": "2026-01-01T00:00:00Z",
      "window_end": "2026-01-01T00:05:00Z",
      "filter": "traffic_class=affected"
    }
  },
  "E-05": {
    "coverage": {
      "surface": "public-surface-a",
      "route_object": "route-object-a",
      "change_id": "change-fixture-17"
    },
    "query_parameters": {
      "route_object": "route-object-a",
      "before": "2026-01-01T00:05:00Z"
    }
  }
}
```

## Derived working claim

Configured forwarding state differs from recorded intent. Edge telemetry and the scoped control counter corroborate a likely bypass for the affected surface. Responder verification is required before an action proposal.

**Outcome:** `candidate_for_responder_verification`  
**Class:** `derived_claim`  
**Subject:** `public-surface-a`  
**Parents actually present:** `E-01`, `E-02`, `E-03`, `E-04`, `E-05`

### Source gaps

- None

### Validation or rule failures

- None

### Derived-envelope coverage

```json
{
  "surface": "public-surface-a",
  "region": "region-a",
  "window_start": "2026-01-01T00:00:00Z",
  "window_end": "2026-01-01T00:05:00Z"
}
```

### Derived-envelope query

```json
{
  "rule_id": "route-conflict-v2",
  "required_evidence_ids": [
    "E-01",
    "E-02",
    "E-03",
    "E-04",
    "E-05"
  ],
  "replay_cutoff": "2026-01-01T00:05:00Z"
}
```

### Transformation versions

```json
{
  "entity_mapping": "fixture-map-v2",
  "comparison_rule": "route-conflict-v2",
  "code": "ch01-context-replay-v2",
  "model": null,
  "prompt": null
}
```

## Next verification

- collect a fresh routing snapshot
- verify destination capacity before proposing a traffic move
