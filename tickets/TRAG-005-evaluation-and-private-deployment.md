# TRAG-005 - Evaluation, auto-start, and private deployment

## Goal

Prove retrieval/grounding quality, install reliable Titan startup behavior, and mount the application privately without disrupting the existing Serve root.

## Dependencies

TRAG-001 through TRAG-004.

## Acceptance Criteria

- Evaluation set includes all sources/courses plus deliberately unsupported questions; results are written to a reproducible report.
- Live smoke tests cover NVIDIA, Ollama, Auto success, and controlled Auto fallback.
- Windows scripts install/restart/inspect/remove the app and SSH-tunnel scheduled tasks idempotently.
- Tailscale Serve preserves `/ -> 127.0.0.1:8787` and adds `/textbooks -> 127.0.0.1:8766/textbooks`.
- Loopback, desktop, mobile viewport, and tailnet URL checks pass; real-device acceptance is stated separately if not physically performed.
- Browser screenshots are compared with the ImageGen concepts and Figma renders, and a fidelity ledger records matches, deliberate differences, and remaining gaps.
- `README.md` documents setup, ingestion, operation, deletion, failure recovery, and rollback without exposing secrets.
