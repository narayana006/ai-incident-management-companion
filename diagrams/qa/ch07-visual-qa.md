Hand-recorded render review, not generated output.

# Chapter 7 Figure Visual QA

**Rendered:** 2026-08-18 with `rsvg-convert` at each SVG's native view-box
dimensions.

| Figure | Render | Typography | Clipping/overlap | Reading order | Result |
|---|---|---|---|---|---|
| Figure 7.1 — governed agent plane | 1600 × 920 PNG | Clear at full-page and reduced preview | None observed | Evidence → model → deterministic decision → narrow execution; communication and audit remain visibly separate | PASS |
| Figure 7.2 — trust-zone/tool-scope matrix | 1600 × 930 PNG | Headers, negative cells, and two exceptional scopes remain legible | None observed | Rows scan consistently; mutation and egress exceptions are visually distinct | PASS |
| Figure 7.3 — provenance chain | 1600 × 900 PNG | Seven records, checkpoint contract, and limitation text remain legible | None observed | Sequential chain reads left to right; conditional reconstruction and non-claims are separated below | PASS |

All three sources include a non-empty `<title>`, a long `<desc>`, `role="img"`,
and `aria-labelledby="title desc"`. They contain no `foreignObject` or Mermaid
source. Visual review found no cropped text, collision, misleading arrow, or
unexplained production-performance claim.
