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

## 2026-09-03 responsive and accessibility pass

The existing concepts remain the visual reference, with the sans-serif requirement and new query mode treated as explicit product changes. Puppeteer acceptance ran against the real Vite-rendered UI with only the API boundary mocked. Artifacts are written outside the repository to `%TEMP%\\textbook-rag-puppeteer`.

### Above-the-fold copy diff

- Preserved: `Textbook Desk`, `History`, `Your semester library`, `Ask the page, not the whole internet.`, `Try asking`, and `Answers stay inside your textbooks`.
- Added by request: `Select all that apply`, `Allow more than one correct answer`, and the post-answer `Select all that apply mode` status note.
- Preserved historical list coverage: `What is virtual memory?`, `Why use semantic HTML?`, and `What distinguishes an estimate from a commitment?`.

### Responsive and interaction checks

- The history rail remains a persistent desktop pane and becomes a dismissible mobile drawer; search, reopen, selected-state marking, and drawer close were exercised.
- The composer keeps the query-mode checkbox before submission, preserves it after the response, and exposes the mode in the answer status and persisted API payload.
- Mobile evidence starts as a compact sheet and expands through a 44px control; desktop evidence remains a side panel with the PDF page-view path intact.
- All application copy and form controls use the IBM Plex Sans stack with visible focus styling; the six viewport checks found no horizontal overflow or undersized interactive control.
- Accepted profiles: Puppeteer’s iPhone 16 Pro preset `402x681 @3`, Galaxy S21 Ultra `384x854 @3.75`, PC `1280x960`, PC `3840x2160`, PC `1920x2160`, and an emulated M1 MacBook Air “more space” profile `1680x1050 @2`.

### Intentional deviations and gaps

- The serif typography in the original concept was intentionally replaced with sans-serif to satisfy the accessibility requirement.
- The MacBook Air profile is an emulated browser viewport and device pixel ratio, not physical Safari hardware; real-device behavior remains a separate gate.
- Puppeteer mocks textbook/API responses so the suite can deterministically verify UI behavior; deployment health and provider availability still require the live-service checks.
