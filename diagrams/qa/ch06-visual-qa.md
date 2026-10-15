Hand-recorded render review, not generated output.

# Chapter 6 Figure QA

Render date: 2026-08-18  
Renderer: `rsvg-convert`  
Review size: 1200 pixels wide  
Review directory: `tmp/ch06-figure-qa/`

| Figure | Visual check |
|---|---|
| 6.1 Guard outside the model | Pass — labels, branches, footer, and guard/executor boundary visible; no clipping |
| 6.2 Serving headroom | Pass — probe and useful-work paths distinct; formula and demotion path visible; no clipping |
| 6.3 Cumulative budget | Pass — cross-actor inputs, serialized writer, both outcomes, and lifecycle visible; no clipping |
| 6.4 Controller ownership | Pass — four ownership states and commitment recheck visible; no clipping |
| 6.5 Reliability policy | Pass — canonical input, permitted/demoted paths, hysteresis, and continued read-only help visible; no clipping |
| 6.6 K8S-01 mechanism | Pass — S01A and S01B separated, exact endpoints readable, n = 1 labels visible, TTL marked not run; no clipping |

All six SVGs include a title, long description, `role="img"`, and
`aria-labelledby="title desc"`. Visual inspection found no overlapping text,
cropped labels, decorative magic arrows, or unsupported comparative result.
