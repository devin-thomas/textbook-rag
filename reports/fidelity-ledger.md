# Textbook Desk fidelity ledger

Validated on 2026-08-24 against the ImageGen concepts and Figma renders in `design/concepts/` and `design/figma/`.

## Browser evidence

- Desktop: `design/browser/textbook-desk-desktop-1440x1024.png`
- Mobile fallback: `design/browser/textbook-desk-mobile-390x844.png`
- Mobile expanded evidence: `design/browser/textbook-desk-mobile-evidence-390x844.png`

## Matches

- Desktop preserves the three-pane history, answer/composer, and evidence/PDF layout from Figma frame `7:3`.
- Mobile preserves the compact top bar, visible provider selector, dismissible fallback banner, scrollable answer, bottom evidence sheet, and fixed composer from frame `7:4`.
- Typography, navy/teal/coral palette, paper grid, strong rules, and restrained square controls remain faithful to the visual direction.
- Structured citations show the source title and printed page label; opening a citation navigates the PDF viewer with the separate physical page coordinate.
- Loading, answer, insufficient-evidence, fallback, history selection, clear-all confirmation, evidence expansion, and page-view states were exercised in the in-app browser.
- All rendered interactive controls at the 390x844 viewport meet the 44 CSS pixel target, focus is visible, and the browser console reported no warnings or errors.

## Deliberate differences

- The live application says `Research configured` rather than claiming `Research online`; `/health` reports configuration, not a live provider round trip.
- Evidence panels show the actual top eight retrieved chunks and ranking details instead of the two hand-edited excerpts in the concepts.
- The embedded browser PDF viewer supplies its native toolbar and pagination rather than the simplified illustrative controls in Figma.
- Live model answer length and line breaks vary from the static copy while retaining the same hierarchy and structured source/page controls.

## Remaining gaps

- A physical iPhone was not checked in this session; 390x844 browser acceptance is complete, but real-device Safari/Tailscale behavior remains separate.
- NVIDIA's hosted endpoint and the Research Ollama host remain operational dependencies; provider throttling or a sleeping Research host must stay visible to the user.
- Retrieved evidence is intentionally verbatim and can be substantially longer than the edited concept excerpts; the mobile sheet scrolls and wraps it without horizontal overflow.
