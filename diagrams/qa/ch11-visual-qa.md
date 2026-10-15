Hand-recorded render review, not generated output.

# Chapter 11 Figure Visual QA

**Artifact class:** illustrative template  
**Figures inspected:** Figure 11.1 and Figure 11.2

Both committed SVGs were rendered at their native 1,200-pixel width with
`rsvg-convert` and inspected in color and grayscale.

- Titles, phase labels, decision labels, and all body lines are legible.
- No text, arrows, borders, or captions clip or overlap.
- Reading order is unambiguous in the gated roadmap.
- The three planning windows remain distinct without relying on color.
- Continue, narrow, hold, and stop are written explicitly rather than encoded
  only by hue.
- The calendar and authority disclaimers remain visible at book-placement size.
- Accessible SVG titles and long descriptions match the visible mechanism.
- Neither figure displays a percentage, weighted readiness result, universal
  threshold, or action-authority recommendation.

Visual QA found no release-blocking issue in the source-size renders. Final
DOCX and PDF placement still require page-level inspection after typesetting.
