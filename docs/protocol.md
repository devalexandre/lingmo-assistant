# Lingmo Assistente — engine protocol (version 1)

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
JSON array and exits; `--version` prints the version.

## Requests (client → engine)

| type | fields | meaning |
|---|---|---|
| `chat` | `conversation_id`, `message` | Ask something. `conversation_id` is chosen by the client: 1–100 chars of `[A-Za-z0-9_-]` (a UUID is fine). History is kept per conversation. |
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
| `ready` / `config` | `version`, `protocol` (1), `provider`, `model`, `think`, `tools_supported` (true/false, or null when Ollama can't be asked), `read`, `write`, `tools` (enabled contract tool ids), `busy` |
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
| `history` | `conversation_id`, `title`, `messages`: `[{role: "user", text} \| {role: "assistant", text, tools: [{tool, function, args_summary, ok, summary, output}]}]`, `pending`: `[{request_id, tool, function, title, details}]` |
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
| `notes_write` | `create_note`, `append_to_note` |
| `calendar_write` | `create_event`, `create_reminder`, `create_task` |
| `files_write` | `write_file` (modes `create`, `append`, `overwrite`) |

Nothing deletes, renames or moves anything.
