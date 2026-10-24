# Lingmo Assistente — engine protocol (version 2)

`lingmo-assistant-engine` (installed at `/usr/lib/lingmo-assistant/lingmo-assistant-engine`)
is a long-running worker. Clients (the Assistente app, Spotlight) start it with
`QProcess` (argv, no shell) and talk to it with **NDJSON**: one JSON object per
line, UTF-8, in both directions. Every object has a `"type"`.

- stdout carries protocol lines only. The engine moves fd 1 to stderr at
  start-up, so stray prints from libraries can't corrupt the stream.
- stderr carries logs. Logs never contain message text, document contents,
  tool arguments or secrets. `LINGMO_ASSISTANT_DEBUG=1` enables debug logs
  (including agno's, which *may* show tool arguments — for development only).
- Closing stdin ends the engine after the current answer; a confirmation still
  waiting stays paused in the database (see "Handoff").
- One answer runs at a time per engine process.
- User-facing messages (`error`, `notice`, confirmation `title`/`details`) are
  in Brazilian Portuguese. Clients translate everything else themselves (for
  example, they build "Executou: lscpu" from `tool_start`).

Other command-line forms: `--list-commands` prints the shell_read allowlist as a
JSON array and exits; `--version` prints the version; `--voice-status` prints what
the voice stack finds (JSON); `--flows-daemon`, `--run ID` and `--status` are the
background workflow service (installed as `lingmo-assistant-flows`, see below).

Version 2 only adds requests and events (agents, workflows, voice) and the
optional `agent` field of `chat`; version-1 clients keep working.

## Requests (client → engine)

| type | fields | meaning |
|---|---|---|
| `chat` | `conversation_id`, `message`, optional `agent` | Ask something. `conversation_id` is chosen by the client: 1–100 chars of `[A-Za-z0-9_-]` (a UUID is fine). History is kept per conversation. `agent` (an agent id, or a name as typed after `@`, e.g. `secretaria`) answers with that custom agent; it stays the agent of the conversation. |
| `ask_image` | `conversation_id`, `message`, `image` (base64 PNG/JPEG, ≤ 8 MiB decoded, optional), `ocr_text` (optional), `source` (`{window, app, width, height}`, optional), optional `agent` | A question about an area of the screen (lingmo-screenshot's "Perguntar sobre a tela"). See "Questions about the screen" below. |
| `confirm` | `request_id`, `allow` (bool) | Answer a `confirmation_required`. |
| `stop` | — | Stop the current answer. A pending confirmation is left unanswered (the run stays paused in the database). |
| `reload_config` | — | Re-read `ai.conf` and the model's capabilities; answered with `config`. (The engine also re-reads `ai.conf` for every message and every tool call.) |
| `status` | — | Answered with `config`. |
| `list_conversations` | — | Answered with `conversations`. |
| `history` | `conversation_id` | Answered with `history`. |
| `delete_conversation` | `conversation_id` | Deletes the engine's own chat history for that conversation (never user data); answered with `deleted`. |

## Events (engine → client)

| type | fields |
|---|---|
| `ready` / `config` | `version`, `protocol` (1), `provider`, `model`, `think`, `tools_supported` (true/false, or null when Ollama can't be asked), `vision` (the model reads images: true/false, or null), `read`, `write`, `tools` (enabled contract tool ids), `busy` |
| `image_mode` | `conversation_id`, `mode` (`vision` \| `ocr`), `model`, `ocr_chars` — sent before `started` for an `ask_image` |
| `started` | `conversation_id` — an answer (or a resumed run) began |
| `token` | `conversation_id`, `text` — a piece of the Markdown answer |
| `thinking` | `conversation_id`, `text` — a piece of the model's reasoning (show "Pensando…", not the text) |
| `tool_start` | `conversation_id`, `tool` (contract id, e.g. `shell_read`), `function` (e.g. `run_command`), `args_summary` (e.g. `lscpu`, `~/Documentos/a.pdf`) |
| `tool_end` | `conversation_id`, `tool`, `function`, `ok`, `summary`, `output` (what the tool returned, cut at 4000 chars, for a collapsible card) |
| `confirmation_required` | `conversation_id`, `request_id`, `tool`, `function`, `title` (e.g. "Criar página no Notas"), `details` (the exact path/content/event that will be written; for overwrites, a unified diff) |
| `confirmation_resolved` | `conversation_id`, `request_id`, `allow` |
| `notice` | `conversation_id`, `message` — one-line information (e.g. the model has no tool support) |
| `done` | `conversation_id`, `stopped` (bool), `stats`: `{seconds, tokens_per_s, tokens, model}` — `seconds` excludes the time spent waiting for the user |
| `error` | `message`, optional `conversation_id` |
| `conversations` | `items`: `[{id, title, updated (unix time)}]`, newest first |
| `history` | `conversation_id`, `title`, `agent` (id or ""), `messages`: `[{role: "user", text, screen?} \| {role: "assistant", text, tools: [{tool, function, args_summary, ok, summary, output}]}]` (`screen`: `vision` or `ocr` on questions sent with `ask_image`), `pending`: `[{request_id, tool, function, title, details}]` |
| `deleted` | `conversation_id` |

A normal answer: `started`, then any mix of `thinking`, `token`, `tool_start`/`tool_end`,
`confirmation_required` → (client sends `confirm`) → `confirmation_resolved`, and finally
`done` or `error`.

```
→ {"type":"chat","conversation_id":"5f0c…","message":"Crie uma nota com a lista: leite, pão"}
← {"type":"started","conversation_id":"5f0c…"}
← {"type":"confirmation_required","conversation_id":"5f0c…","request_id":"e56…","tool":"notes_write","function":"create_note","title":"Criar página no Notas","details":"Notas › nova página\nTítulo: Compras\n\n- leite\n- pão"}
→ {"type":"confirm","request_id":"e56…","allow":true}
← {"type":"confirmation_resolved","conversation_id":"5f0c…","request_id":"e56…","allow":true}
← {"type":"tool_start","conversation_id":"5f0c…","tool":"notes_write","function":"create_note","args_summary":"Compras"}
← {"type":"tool_end","conversation_id":"5f0c…","tool":"notes_write","function":"create_note","ok":true,"summary":"Compras","output":"Página «Compras» criada no Notas (id …)."}
← {"type":"token","conversation_id":"5f0c…","text":"Criei "}
← …
← {"type":"done","conversation_id":"5f0c…","stopped":false,"stats":{"seconds":4.9,"tokens_per_s":65.2,"tokens":77,"model":"qwen3.5:4b"}}
```

## Questions about the screen (`ask_image`)

lingmo-screenshot (`lingmo-screenshot ask`, Meta+S) runs its own engine and sends
the selected area as `ask_image`: the crop (scaled to at most 1280 px, PNG or
JPEG) in base64, the text tesseract read from it and the window title. The
engine answers like `chat` (same ai.conf model, agents, tool gate, confirmations
and history) with these differences:

- **Vision or text.** When the model has Ollama's `vision` capability (see
  `config.vision`) it gets the picture in the message's `images` and the OCR text
  as a hint; otherwise it gets the OCR text only (and is told it can't see the
  picture). No picture and no OCR text with a text-only model is an `error`
  suggesting a vision model (`qwen2.5vl:3b`, `gemma3:4b`). `image_mode` says
  which way was taken.
- **Direct answers.** Reasoning is off (`think: false`) whatever ai.conf says.
- **Context.** The OCR text and the window title go to the system prompt for
  this run, between untrusted-content markers; the user message stays the
  question, so the history reads naturally. The run is marked
  (`metadata.screen`), and `history` returns `screen` on those questions.
- **Privacy.** The picture is never written to the history database (agno
  `store_media=False`); follow-up questions must send it again. Lines may be up
  to 12 MiB for this request.
- **No recursion.** The `screen.ask` intent (open the selection overlay) is not
  offered as a tool during a screen question.

"Continuar no Assistente" hands the conversation over: lingmo-screenshot calls
`com.lingmo.Assistant /Assistant continueWithImage(s conversationId, ay image,
s ocrText, s window)`. The app keeps the picture in memory only, shows it in the
chat (`image://screen/<id>`) and sends the follow-up questions of that
conversation as `ask_image`.

## Confirmation and handoff

Every write tool is an agno tool with `requires_confirmation=True`: the agno run
pauses and is stored (status PAUSED) in the engine's SQLite database
(`$XDG_DATA_HOME/lingmo-assistant/assistant.db`). The engine validates the
pending call first (permissions, allowed folders, blocked paths, formats); an
invalid call is refused automatically and the model is told why, without asking
the user. A valid one becomes `confirmation_required`; nothing is written before
`confirm` with `allow: true`, and the tool re-checks everything when it runs.

Spotlight's "Abrir no Assistente" works across processes: Spotlight sends
`stop` (the run stays paused in the database) and calls
`com.lingmo.Assistant.open(conversationId)` over D-Bus. The app's engine
answers `history` with the paused request in `pending`, and a `confirm` with
that `request_id` resumes the stored run there.

## Tools (contract ids → functions)

| contract id | functions |
|---|---|
| `system_info` | `system_info` |
| `shell_read` | `run_command` |
| `read_files` | `list_folder`, `read_document`, `summarize_documents` |
| `search_files` | `search_files` |
| `notes_read` | `list_notes`, `read_note` |
| `calendar_read` | `calendar_agenda` |
| `web` | `web_search`, `read_web_page` |
| `mail_read` | `list_emails`, `read_email` |
| `mail_write` | `send_email`, `reply_email` |
| `alarms_write` | `create_alarm`, `start_timer` |
| `desktop_actions` | `open_app` |
| `notes_write` | `create_note`, `append_to_note` |
| `calendar_write` | `create_event`, `create_reminder`, `create_task` |
| `files_write` | `write_file` (modes `create`, `append`, `overwrite`) |

Nothing deletes, renames or moves anything.

### App actions (Lingmo Intents)

Every action an installed app declares (`/usr/share/lingmo/intents/*.json`,
see `docs/intents.md` in the workspace) is also a tool, generated at run time:
function `intent_<id>` (dots become `_`, e.g. `intent_clock_alarm_create`),
`tool` = the manifest's `assistantTool` (e.g. `alarms_write`) or `intents`.
`args_summary` is "App › summary" ("Relógio › Criar alarme às 07:00"). Only
the intents allowed by the gate are offered (read/write switches, the tool
checkbox, `intents_disabled_apps` / `intents_disabled`); every one that is not
read-only uses `confirmation_required` (`title` "Relógio › Criar alarme",
`details` the exact values). After "Permitir" the engine calls the app over
D-Bus with `{"caller": "assistant", "confirmed": true}`; the app checks
everything again. Results of read-only intents reach the model as untrusted
content. When an intent covers a hand-written tool, that tool is left out
(`create_alarm`, `start_timer`, `send_email`, `reply_email`, `list_emails`,
`read_email`, `create_note`, `append_to_note`, `create_event`, `create_task`).

In `flow_catalogue`, intents are node types `intent.<id>` (category `actions`,
`group` = the app's name, `intent` = the id, params generated from the schema,
outputs `output`, `result` and `result.<field>`); built-in types that do the
same are sent with `hidden: true` (kept for saved workflows, left out of the
palette).


## Protocol 2: agents, workflows, voice

User-facing texts in these events (node labels, capability summaries, errors) are
pt-BR, like the rest of the protocol. A failing request answers
`error {message, request: <request type>}`.

### Custom agents

Stored as JSON in `~/.local/share/lingmo/assistant/agents/<id>.json` (see
`agents.py`); four starters are written on first use and can be edited or
removed (removing moves the file to `agents/.trash`).

| request | fields | answer |
|---|---|---|
| `agents` | — | `agents {items, tools: [{id, group, enabled}], read, write, default_model}` — `enabled` is the global state in Settings › IA |
| `agent_save` | `agent` (without `id` = new) | `agent_saved {agent}` then `agents` |
| `agent_remove` | `id` | `agents` |
| `models` | — | `models {items: [{name, size, tools, thinking, embedding, tags: [{id, text}], in_use, recommended}]}` (installed Ollama models) |

An agent's tools are the intersection of its own list and the tools enabled in
Settings; the read/write switches still apply; every write still asks for
confirmation. Knowledge folders (read-only search) must be inside the allowed
folders.

### Workflows

Versioned JSON in `~/.local/share/lingmo/assistant/workflows/<id>.json`
(`format: "lingmo-assistant-flow"`, `format_version: 1`, `revision`); the last 10
revisions are kept in `workflows/.history/<id>/`. Run logs:
`runs/<flow id>/<run id>.json`. Capability approvals: `approvals.json` (never part
of a workflow file).

| request | fields | answer |
|---|---|---|
| `flow_catalogue` | — | `flow_catalogue {categories, types, templates, accounts, agents, folders, tools}` — `types` is the node catalogue: `{type, category, group, label, description, icon, params: [{name, label, kind, default, required, options, placeholder, help, template}], ports, port_labels, input, outputs, capability: {tools, verb, writes, external} \| null}` |
| `flows` | — | `flows {items: [info], running: [{run_id, flow_id, status}]}` |
| `flow_get` | `id` | `flow {flow, info}` |
| `flow_new` | optional `template` | `flow {flow, info, unsaved: true}` (not written) |
| `flow_validate` | `flow` | `flow_issues {id, issues, summary, capabilities, approved}` |
| `flow_save` | `flow` | `flow_saved {flow, info}` then `flows`. A workflow with errors is saved switched off. |
| `flow_approve` | `id`, `cap_hash` (from `info`), `dont_ask` | `flow_saved`. Refused when the capabilities changed since `info` was shown. |
| `flow_set_enabled` | `id`, `enabled` | `flow_saved` |
| `flow_remove` | `id` | `flows` (the file moves to `workflows/.trash`) |
| `flow_import` | `text` (JSON) | `flow_saved` — imported switched off, never approved, new id when taken |
| `flow_export` | `id` | `flow_export {id, text}` |
| `flow_run` | `flow_id`, `mode` (`run` \| `test`) | events below |
| `flow_answer` | `request_id`, `allow`, optional `dont_ask`, optional `text` | — |
| `flow_stop` | `run_id` | — |
| `flow_runs` | `flow_id` | `flow_runs {flow_id, items: [{id, status, mode, started, ended, trigger, error, source}]}` |
| `flow_run_log` | `flow_id`, `run_id` | `flow_run_log {run}` with `steps: [{node, type, label, status, started, ended, inputs, outputs, error}]` |

`info` = `{id, name, enabled, revision, trigger_type, trigger_text, capabilities:
[{tools, text, writes, external, nodes}], summary, cap_hash, approved, dont_ask,
issues: [{level, node, message}], blocked: [reasons from Settings], background,
spotlight}`.

Run events: `flow_run_started {run_id, flow_id, flow_name, mode}`, `flow_node
{run_id, flow_id, node, status: running|waiting|done|error|declined, output, error}`,
`flow_ask {run_id, flow_id, request_id, node, kind: confirm|input, title, details,
external}` (the run pauses until `flow_answer`), `flow_ask_resolved {run_id,
request_id}`, `flow_run_done {run_id, flow_id, status: done|failed|stopped|refused,
error}`.

The permission gate (`flows/permissions.py`): no node type deletes and validation
refuses any that would; a workflow runs only when its current capabilities were
approved; nodes marked `external` (sending or replying to e-mail) ask on every run
unless approved with `dont_ask`; `test` mode asks before every writing node;
Settings › IA (read/write switches and checked tools) is checked again for every
node when it runs; every run is logged.

### Voice

| request | fields | answer |
|---|---|---|
| `voice_status` | — | `voice_status {whisper, whisper_models, piper, espeak, voices: [{id, name, language, engine}], language}` |
| `voice_start` | optional `commands` (default true) | `voice_state {state: listening}`, `voice_level {level 0..1, seconds}` (~12/s), then `voice_state {transcribing}`, `voice_text {text, flow_id, flow_name}`, `voice_state {idle}` (or `{error, message}`). A `voice_start` while listening stops the recording (push-to-talk). When the text matches a workflow's "Comando de voz" trigger, that workflow runs (`flow_*` events) and `flow_id` is set; otherwise the client sends the text as a `chat`. |
| `voice_stop` / `voice_cancel` | — | stop listening now (transcribe) / discard |
| `voice_command` | `text` | as `voice_text` (match a voice trigger without the microphone) |
| `speak` | `text` (Markdown is cleaned) | `speak_state {speaking: true}` … `{speaking: false}` |
| `speak_stop` | — | — |

Recording: `parecord`/`pw-record`/ffmpeg's pulse input, 16 kHz mono, until ~1.2 s
of silence after speech (or 20 s); the audio is a private temporary file deleted
after `whisper-cli` transcribes it. Text to speech: `piper-tts` with the chosen (or
the locale's) voice, else `espeak-ng`.

## Background workflows: `lingmo-assistant-flows`

Started at login from `/etc/xdg/autostart/lingmo-assistant-flows.desktop`; one per
user (lock file in `$XDG_STATE_HOME/lingmo-assistant/`). It runs the enabled,
approved workflows whose trigger is a schedule, new e-mail, a calendar event, a
file change or a system event, sleeping until the next one is due. Questions and
per-run confirmations appear as notifications with Permitir/Recusar buttons.

D-Bus `com.lingmo.AssistantFlows /AssistantFlows`: `Run(s flow_id) → s run_id`,
`Running() → s` (JSON), `Reload()`, `Stop(s run_id)`. A workflow with a
"Atalho de teclado" trigger gets an entry in `~/.config/lingmoglobalshortcutsrc`
(lingmo-chotkeys) running `lingmo-assistant-flows --run <id>`; the service never
touches entries it didn't create.
