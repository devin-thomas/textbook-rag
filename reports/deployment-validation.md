# Textbook Desk deployment validation

- Date/time: 2026-08-24 12:34:55 -05:00
- Git commit: `80fd741`
- Operator: current Titan user
- Titan hostname: `Titan`
- Research hostname: `research`
- Tailnet URL: `https://titan.takaya-lionfish.ts.net/textbooks/`

## Configuration evidence

- [x] Both `TextbookDesk-OllamaTunnel` and `TextbookDesk-App` are installed and `Running`.
- [x] The existing `/ -> http://127.0.0.1:8787` Serve mapping is unchanged.
- [x] Serve has the exact `/textbooks -> http://127.0.0.1:8766/textbooks` mapping.
- [x] The final deployment gate reports both task and both exact Serve checks as `PASS`.
- [x] Ports `8766` and `11435` listen only on `127.0.0.1`; no wildcard or LAN binding is present.
- [x] No API keys, dotenv contents, full answers, or textbook excerpts are included in this report.

## Reproducible smoke check

Command:

```powershell
.\scripts\Test-Deployment.ps1 -TailnetUrl 'https://titan.takaya-lionfish.ts.net'
```

Result:

```text
PASS  Loopback listener policy: 127.0.0.1:11435, 127.0.0.1:8766
PASS  Scheduled task TextbookDesk-OllamaTunnel: Running
PASS  Scheduled task TextbookDesk-App: Running
PASS  Tailscale Serve root mapping
PASS  Tailscale Serve textbook mapping
PASS  Existing root app: HTTP 200
PASS  Textbook Desk health: HTTP 200
PASS  Textbook Desk UI: HTTP 200
PASS  Ollama tunnel: HTTP 200
PASS  Tailnet root: HTTP 200
PASS  Tailnet Textbook Desk: HTTP 200
```

## Query scenarios

| Scenario | Result | Evidence |
| --- | --- | --- |
| NVIDIA explicit succeeds without switching | Pass | `actual_provider=nvidia`, `fallback_used=false`, two citations |
| Ollama explicit succeeds without switching | Pass | `actual_provider=ollama`, `fallback_used=false`, two citations |
| Auto uses NVIDIA when NVIDIA succeeds | Pass | `actual_provider=nvidia`, `fallback_used=false` |
| Auto falls back only after a controlled NVIDIA provider failure | Pass | invalid loopback NVIDIA endpoint produced `initial_failure_kind=connection`; Ollama answered with structured citations and no raw chunk IDs |
| Unsupported textbook question abstains before generation | Pass | `insufficient_evidence`, no provider, citations, or evidence |
| Citation opens the allowlisted PDF at the exact physical page | Pass | printed page `138` opened The Clean Coder physical PDF page `171`; printed page `61` opened The Missing Link physical page `75` |

## Client acceptance

| Client | Result | Notes |
| --- | --- | --- |
| Titan loopback | Pass | API, UI, PDF range, history detail/delete-one, and confirmation boundary checked |
| Desktop tailnet browser | Pass | Live tailnet UI rendered; root still rendered `Model Dialogue Lab` |
| 390x844 emulated viewport | Pass | Fallback dismissal, evidence sheet, page navigation, touch targets, and console checked |
| Physical phone over tailnet | Not run | Real-device Safari/Tailscale acceptance remains separate from emulation. |

## Rollback rehearsal

- [x] `Manage-TailscaleServe.ps1 -Action Rollback -WhatIf` targets only `/textbooks`.
- [x] `Manage-StartupTasks.ps1 -Action Remove -WhatIf` targets only the two Textbook Desk tasks.
- [x] The existing root dashboard remained HTTP 200 after installation; no real rollback was needed.

## Open risks

- NVIDIA's hosted prototyping endpoint can throttle or change independently of the app.
- Research must be awake and reachable for local embeddings and Ollama generation.
- Physical iPhone acceptance was not performed in this session.
