# Lingmo Assistente

A local AI assistant for the Lingmo desktop (Arch Linux, Qt 6). It answers with
the Ollama model chosen in Lingmo Settings › AI and, through tools, reads
documents, notes, e-mail, the calendar and system information; with the user's
permission it creates notes, events, tasks, alarms and text files and sends
e-mail. It never deletes anything, and every write asks for confirmation.

It has three sections:

- **Conversas** — chat with the assistant or with one of your **agents**, by
  typing or by voice (microphone button, or `Meta+Shift+I` anywhere).
- **Fluxos** — visual workflows: a node editor (pan/zoom canvas, palette,
  inspector, minimap, undo/redo, auto-layout) where a trigger (manual, schedule,
  new e-mail, calendar event, file change, shortcut, voice command, login/USB/
  battery) drives actions in the Lingmo apps (Mail, Calendar, Clock, Notes,
  files, notifications, speech, safe commands), AI blocks (ask an agent,
  summarise, classify, extract, translate) and logic (condition, switch, loop,
  wait, ask you, variables). Values flow with `{{block.output}}` templates.
  Five starter templates. Scheduled and event workflows run in the background
  (`lingmo-assistant-flows`, started at login).
- **Agentes** — custom agents: name and emoji, instructions, model (installed
  Ollama models with capability tags), a subset of the tools, read-only
  knowledge folders (local embeddings), creativity and reasoning. Also in
  Spotlight: `ai:@nome pergunta`.

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

## Workflow security

- No block deletes anything (validation refuses delete-like types and options;
  the mail layer only sends create/send/move/flag operations).
- Saving a workflow shows what it can do in plain words ("Este fluxo pode enviar
  e-mails como voce@…, criar alarmes"); it runs only after that set of
  capabilities is approved. The approval is stored outside the workflow file, so
  an imported file can't approve itself, and adding a block that does something
  new asks again.
- Sending e-mail asks on every run unless "não perguntar de novo para este
  fluxo" is ticked; "Testar" asks before every write and highlights each block.
- Settings › AI still caps everything: each block checks the read/write switches
  and its tool when it runs.
- Every run is logged step by step (`~/.local/share/lingmo/assistant/runs/`).

## Voice

Everything stays on the computer. Recording uses PipeWire/PulseAudio
(`parecord`, `pw-record` or ffmpeg), with a "mic on" indicator in the voice pill;
speech to text uses `whisper-cli` (whisper.cpp) with the models downloaded in
Settings › AI › Transcription, choosing a fast one that the hardware handles (the
same probe as Lingmo Studio's `whisperhw.cpp`); language from the system locale.
Text to speech uses `piper-tts` with a voice for the language, else `espeak-ng`.
Voice, speed and "answer out loud" are in the Assistant's "Voz e ajustes" and in
Settings › AI.

## Build

```
cmake -B build -G Ninja -DCMAKE_INSTALL_PREFIX=/usr
ninja -C build
```

Runtime: python, python-agno, python-ollama, python-openai (imported by agno's
Ollama module), python-sqlalchemy, python-greenlet, bubblewrap, poppler
(pdftotext), qt6-declarative, LingmoUI; glib2 (`gdbus`), python-dbus and
python-gobject (background service), libpulse (`parecord`), whisper-cpp and
espeak-ng (voice). Optional, from the AUR: `piper-tts-bin` and
`piper-voices-pt-br` (or other `piper-voices-*`) for natural voices — without
them espeak-ng speaks. Mail actions use Lingmo Mail's worker
(`/usr/libexec/lingmo-mail/backend.py`); alarms and timers Lingmo Clock's D-Bus
service `com.lingmo.Clock`. Calendar tools use Lingmo Mail's worker
(`/usr/libexec/lingmo-mail/calendar_backend.py`), notes tools write Lingmo
Notes' Markdown pages.

Tests: `python -m pytest backend/tests` (no network; the Notes test compiles
Notes' own `markdown.cpp` when the sources are next to this repo; the mail
end-to-end tests run Lingmo Mail's worker against a local fake IMAPS/SMTPS
server when `aiosmtpd` is installed; the speech round trip runs when piper, a
pt_BR voice, whisper-cli and a whisper model are present). App model tests:
`cmake -DBUILD_TESTING=ON` then `ctest` (`tst_flowdocument`).
