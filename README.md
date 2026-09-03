# Textbook Desk

Textbook Desk is a private, page-aware RAG application for the four semester textbooks in this repository. It runs on Titan, retrieves and cites the original PDF pages, and generates answers through NVIDIA or Ollama on Research. Tailscale Serve makes it available to the tailnet at `/textbooks`; nothing is exposed with Funnel.

## Runtime map

| Surface | Address | Purpose |
| --- | --- | --- |
| Textbook Desk | `http://127.0.0.1:8766/textbooks` | Loopback-only FastAPI and built UI |
| Ollama tunnel | `http://127.0.0.1:11435` | Titan forward to `research:127.0.0.1:11434` |
| Existing dashboard | `http://127.0.0.1:8787` | Existing Tailscale Serve root; do not replace |
| Tailnet app | `https://titan.takaya-lionfish.ts.net/textbooks/` | Private phone and desktop access |

## Prerequisites

- Python 3.12 and Node.js/npm on Titan.
- Tailscale signed in on Titan and the client device.
- Windows OpenSSH with a working `research` host alias.
- Ollama on Research. `qwen3.5:9b` and `qwen3-embedding:4b` were installed and smoke-tested during initial setup.
- An NVIDIA API key in `NVIDIA_API_KEY` or the existing ignored `C:\dev\experiments\free-nvidia-ai\nv.env` file.

The earlier unused `qwen3-coder-agent:latest` and `qwen3-coder:30b` models were intentionally deleted from Research to reclaim storage. Restore them only by pulling them again; Textbook Desk does not require them.

## First setup

From an ordinary PowerShell prompt in the repository:

```powershell
Copy-Item -LiteralPath .env.example -Destination .env
.\scripts\Setup-TextbookRag.ps1 -IncludeDevDependencies
```

`.env` is ignored by Git. Leave `NVIDIA_API_KEY` out of source-controlled files. The checked-in defaults already point at the existing ignored NVIDIA dotenv path; change `NVIDIA_DOTENV_PATH` in `.env` only if that file moves.

Preview setup without writing anything:

```powershell
.\scripts\Setup-TextbookRag.ps1 -IncludeDevDependencies -WhatIf
```

Verify the Research models without changing them:

```powershell
ssh research "/Applications/Ollama.app/Contents/Resources/ollama list"
```

If either required model is missing, install only that model on Research:

```powershell
ssh research "/Applications/Ollama.app/Contents/Resources/ollama pull qwen3.5:9b"
ssh research "/Applications/Ollama.app/Contents/Resources/ollama pull qwen3-embedding:4b"
```

## Ingest the textbooks

Start the tunnel in one PowerShell window:

```powershell
.\scripts\Start-ResearchOllamaTunnel.ps1
```

Then ingest in another window. Ingestion reads only the four allowlisted entries in `config/sources.json`, keeps physical page provenance, and writes the local database/report under ignored paths.

```powershell
.\scripts\Invoke-Ingestion.ps1
```

Re-running ingestion is idempotent. Use `-Rebuild` only after an intentional embedding or chunking change:

```powershell
.\scripts\Invoke-Ingestion.ps1 -Rebuild
```

Run the checked-in answerable and unsupported retrieval cases after ingestion. This invokes no generation provider and writes reproducible JSON and Markdown results under `reports/generated/`:

```powershell
.\scripts\Invoke-RetrievalEvaluation.ps1
```

## Development

Backend:

```powershell
.\scripts\Start-TextbookRag.ps1 -Reload
```

Frontend hot reload:

```powershell
Set-Location frontend
npm run dev
```

Validation:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m textbook_rag.evaluate --json reports/generated/retrieval-evaluation.json --markdown reports/generated/retrieval-evaluation.md
npm --prefix frontend run typecheck
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix frontend run test:e2e
```

The product route is `http://127.0.0.1:8766/textbooks/`. `Auto` tries NVIDIA first and falls back to Ollama only for a provider failure. Explicit NVIDIA and Ollama selections never switch generation providers. Queries normally use local `qwen3-embedding:4b` through the SSH tunnel; NVIDIA and Auto can use SQLite FTS-only retrieval when that embedding request is unavailable, with the degraded mode shown in the answer. Before submitting, the composer can mark a question `Select all that apply`; that mode is passed to the grounded provider prompt and restored when the historical question is reopened.

## Titan auto-start

The task installer owns exactly two current-user scheduled tasks:

- `TextbookDesk-OllamaTunnel`
- `TextbookDesk-App`

Inspect proposed changes first, then install:

```powershell
.\scripts\Manage-StartupTasks.ps1 -Action Install -WhatIf
.\scripts\Manage-StartupTasks.ps1 -Action Install
```

Close any manually started `Start-ResearchOllamaTunnel.ps1` window before the first task start. The tunnel intentionally refuses to take over an already-listening port.

If the NVIDIA dotenv is in a different location, add `-NvidiaDotEnvPath 'C:\absolute\path\nv.env'`. The installer is idempotent and updates only those exact task names. Inspect or restart them with:

```powershell
.\scripts\Manage-StartupTasks.ps1 -Action Inspect
.\scripts\Manage-StartupTasks.ps1 -Action Restart
```

## Tailscale Serve

Inspect the current configuration before changing it:

```powershell
.\scripts\Manage-TailscaleServe.ps1 -Action Inspect
.\scripts\Manage-TailscaleServe.ps1 -Action Install -WhatIf
```

Installation refuses to proceed unless the exact existing `/ -> http://127.0.0.1:8787` mapping is present. It verifies the exact `/textbooks -> http://127.0.0.1:8766/textbooks` path-target pair rather than accepting the target URL elsewhere in Serve status:

```powershell
.\scripts\Manage-TailscaleServe.ps1 -Action Install
```

After the services are running, verify loopback and tailnet routes:

```powershell
.\scripts\Test-Deployment.ps1 -TailnetUrl 'https://titan.takaya-lionfish.ts.net'
```

## History and textbook data

Conversation history lives only in the local SQLite database on Titan. Delete a single conversation from its history action. `Clear all history` requires confirmation and removes conversation/message/evidence records without deleting source pages or the index.

The original PDF files, extracted pages, embeddings, database, logs, and secrets remain local and ignored by Git. Reproducible ingestion and retrieval evaluation reports are project deliverables and may be checked in after review. NVIDIA receives the question and selected excerpts only when NVIDIA actually handles a request.

For a full local reset, stop the app and move `data\textbook-desk.sqlite3` to a backup location before re-ingesting. Do not delete the source PDFs. Moving the database removes both history and the index, so ingestion must run again.

## Recovery

Inspect before restarting anything:

```powershell
.\scripts\Manage-StartupTasks.ps1 -Action Inspect
.\scripts\Manage-TailscaleServe.ps1 -Action Inspect
```

- If port `11435` is unavailable, identify the listener; do not kill an unrelated process. `Get-NetTCPConnection -LocalPort 11435 -State Listen` must show only loopback addresses (`127.0.0.1` and, if present, `::1`), never `0.0.0.0` or `::`. A healthy tunnel responds at `http://127.0.0.1:11435/api/tags`.
- If Research is asleep or offline, ingestion still requires the local embedding model. NVIDIA and Auto queries can use the indexed SQLite keyword search as a degraded retrieval path; explicit Ollama queries still surface the retrieval failure.
- If NVIDIA fails, confirm the key location without printing the key. Explicit NVIDIA surfaces the error; Auto may fall back to Ollama.
- If the app task repeatedly exits, run `Start-TextbookRag.ps1` interactively to see the actual error, fix it, then restart the scheduled tasks.
- If the phone cannot connect, confirm both devices are signed into the tailnet and verify Serve status. Do not enable Funnel.

## Rollback

Remove only the Textbook Desk Serve path while preserving the existing root:

```powershell
.\scripts\Manage-TailscaleServe.ps1 -Action Rollback -WhatIf
.\scripts\Manage-TailscaleServe.ps1 -Action Rollback
```

Remove only the two Textbook Desk scheduled tasks:

```powershell
.\scripts\Manage-StartupTasks.ps1 -Action Remove -WhatIf
.\scripts\Manage-StartupTasks.ps1 -Action Remove
```

These commands do not remove models, PDFs, the local database, or the existing Tailscale root application.
