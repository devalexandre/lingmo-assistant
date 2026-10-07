# Lingmo Assistente

A local AI assistant for the Lingmo desktop (Arch Linux, Qt 6). It answers with
the Ollama model chosen in Lingmo Settings › AI and, through tools, reads
documents, notes, the calendar and system information; with the user's
permission it creates notes, events, tasks and text files. It never deletes
anything, and every write asks for confirmation.

- `backend/` — the engine, Python package `lingmo_assistant` built on
  [agno](https://github.com/agno-agi/agno) 3.x. `lingmo-assistant-engine` is a
  long-running NDJSON worker (see [docs/protocol.md](docs/protocol.md)).
- `app/` — the "Assistente" app (Qt 6 / QML, LingmoUI). It runs the engine with
  `QProcess` and is single-instance on D-Bus as `com.lingmo.Assistant`
  (`open(conversationId)`, `ask(text)`), which Lingmo Spotlight uses to hand a
  conversation over.

Permissions, tool ids and blocked paths follow the workspace contract
(`docs/assistant-contract.md` in the Lingmo workspace).

## Security

- `shell_read`: a fixed allowlist of read-only commands with validated
  arguments (`lingmo-assistant-engine --list-commands`), argv only, run with
  bubblewrap: read-only root, blocked areas hidden, no network, own session,
  10 s timeout, 32 KB output. Without `bwrap` commands are refused.
- Files: paths are resolved (symlinks) and must be inside the allowed folders
  and outside the blocked areas; writes create or append text files, overwrite
  only after showing a diff; `O_NOFOLLOW`, atomic replace.
- PDFs are converted by `pdftotext` inside the same sandbox.
- Tool output is labelled as untrusted data for the model; injected
  instructions can't write anything without the user's confirmation.
- Only the local Ollama is used (`OLLAMA_HOST` honoured, `OLLAMA_API_KEY`
  ignored); agno telemetry is off. Logs never contain conversation text.

## Build

```
cmake -B build -G Ninja -DCMAKE_INSTALL_PREFIX=/usr
ninja -C build
```

Runtime: python, python-agno, python-ollama, python-openai (imported by agno's
Ollama module), python-sqlalchemy, python-greenlet, bubblewrap, poppler
(pdftotext), qt6-declarative, LingmoUI. Calendar tools use Lingmo Mail's worker
(`/usr/libexec/lingmo-mail/calendar_backend.py`), notes tools write Lingmo
Notes' Markdown pages.

Tests: `python -m pytest backend/tests` (no network; the Notes test compiles
Notes' own `markdown.cpp` when the sources are next to this repo).
