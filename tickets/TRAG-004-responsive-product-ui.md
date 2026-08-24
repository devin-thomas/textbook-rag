# TRAG-004 - Responsive Textbook Desk UI

**Status:** Complete

## Goal

Implement the React product experience from the validated ImageGen and Figma concepts.

## Dependencies

TRAG-003 API contract; mocked API responses may be used while the backend lands.

## Acceptance Criteria

- Desktop matches the history/answer/evidence three-pane Figma frame `7:3`.
- Mobile matches the compact answer/fallback/evidence-sheet Figma frame `7:4` at 390px.
- Provider and course/source scope controls are available for each query.
- Answer citations open an in-app PDF viewer at the exact page.
- Evidence is expandable and shows source title, page, excerpt, and ranking detail.
- Loading, provider fallback, insufficient evidence, provider error, empty history, delete-one, and confirmed clear-all states are complete.
- Keyboard navigation, visible focus, semantic labels, and 44px touch targets are verified.
- Typecheck, production build, component tests, and browser interaction checks pass.

## Execution result

Thirteen frontend tests, TypeScript, and the production build pass. In-app browser acceptance passed at 1440x1024 and 390x844 with loading, answer, fallback dismissal, abstention, history, confirmation, evidence, exact-page PDF, 44px controls, and a clean console; screenshots and the fidelity ledger are checked in.
