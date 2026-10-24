"""Custom agents: a name, an emoji, instructions, a model, a subset of the
assistant's tools (always capped by Settings › IA), optional knowledge folders
(read-only search over allowed folders) and generation options.

Stored as JSON in ~/.local/share/lingmo/assistant/agents/<id>.json:

    {"format": "lingmo-assistant-agent", "format_version": 1, "id": "secretaria",
     "name": "Secretária de e-mail", "emoji": "📧", "description": "…",
     "instructions": "…", "model": "" (= the model chosen in Settings),
     "tools": ["mail_read", "mail_write"], "knowledge": ["~/Documentos/Empresa"],
     "temperature": 0.4, "think": null (= Settings) | true | false, "revision": 2}
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import replace
from typing import Optional

from . import config, store

FORMAT = "lingmo-assistant-agent"
FORMAT_VERSION = 1
DEFAULT_ID = "assistente"

STARTERS = [
    {"id": "secretaria-de-email", "name": "Secretária de e-mail", "emoji": "📧",
     "description": "Lê, resume e responde seus e-mails com rascunhos para você aprovar.",
     "instructions": "Você é a secretária de e-mail do usuário. Leia os e-mails com as ferramentas, "
                     "resuma o que importa (quem, o quê, prazo) e proponha respostas curtas, educadas e "
                     "no tom do usuário. Nunca envie nada sem que a ferramenta peça confirmação. "
                     "Prefira tópicos e destaque o que exige ação.",
     "tools": ["mail_read", "mail_write", "calendar_read", "notes_write"], "temperature": 0.4},
    {"id": "organizador-de-agenda", "name": "Organizador de agenda", "emoji": "🗓️",
     "description": "Planeja seu dia, cria eventos, tarefas e alarmes.",
     "instructions": "Você organiza a agenda do usuário. Consulte o calendário antes de sugerir horários, "
                     "evite conflitos, crie eventos, tarefas e alarmes com horários absolutos e explique o "
                     "plano em poucas linhas.",
     "tools": ["calendar_read", "calendar_write", "alarms_write", "notes_read"], "temperature": 0.3},
    {"id": "resumidor-de-documentos", "name": "Resumidor de documentos", "emoji": "📄",
     "description": "Resume PDFs, documentos e notas das pastas permitidas.",
     "instructions": "Você resume documentos. Leia o arquivo inteiro (use summarize_documents para os longos), "
                     "dê um resumo com os pontos principais, números e datas, e termine com as ações "
                     "sugeridas. Cite o nome do arquivo.",
     "tools": ["read_files", "search_files", "notes_read"], "temperature": 0.2},
    {"id": "redator", "name": "Redator", "emoji": "✍️",
     "description": "Escreve e revisa textos, e-mails e posts no tom que você pedir.",
     "instructions": "Você é um redator cuidadoso em português do Brasil. Escreva textos claros, com boa "
                     "gramática e no tom pedido (formal, amigável, persuasivo). Ofereça uma versão final "
                     "pronta para copiar e, se útil, uma alternativa mais curta.",
     "tools": ["notes_read", "notes_write", "files_write"], "temperature": 0.8},
]


def slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:48] or "agente"


def normalize(doc: dict) -> dict:
    if not isinstance(doc, dict) or doc.get("format", FORMAT) != FORMAT:
        raise ValueError("Arquivo de agente inválido.")
    name = " ".join(str(doc.get("name") or "").split())[:80]
    if not name:
        raise ValueError("Dê um nome ao agente.")
    aid = str(doc.get("id") or "") or slug(name)
    if not store.ID_RE.match(aid):
        aid = slug(name)
    tools = [t for t in (doc.get("tools") or []) if isinstance(t, str) and t in config.TOOLS]
    knowledge = [str(k)[:500] for k in (doc.get("knowledge") or []) if isinstance(k, str) and k.strip()][:10]
    try:
        temperature = float(doc.get("temperature") if doc.get("temperature") is not None else 0.7)
    except (TypeError, ValueError):
        temperature = 0.7
    think = doc.get("think")
    emoji = str(doc.get("emoji") or "🤖")[:8]
    return {"format": FORMAT, "format_version": FORMAT_VERSION, "id": aid, "name": name, "emoji": emoji,
            "avatar": str(doc.get("avatar") or "")[:200],
            "description": str(doc.get("description") or "")[:500],
            "instructions": str(doc.get("instructions") or "")[:8000],
            "model": str(doc.get("model") or "")[:200], "tools": tools, "knowledge": knowledge,
            "temperature": max(0.0, min(2.0, temperature)),
            "think": think if isinstance(think, bool) else None,
            "starter": bool(doc.get("starter", False)),
            "revision": int(doc.get("revision") or 0) if isinstance(doc.get("revision"), int) else 0,
            "created": doc.get("created") or 0, "updated": doc.get("updated") or 0}


STORE = store.DocumentStore("agents", normalize)


def seed() -> None:
    """Writes the built-in starters once (the user may then edit or remove them)."""
    marker = store.root() / "agents" / ".seeded"
    if marker.exists():
        return
    for s in STARTERS:
        if STORE.get(s["id"]) is None:
            STORE.save(dict(s, starter=True))
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("1\n")


def all_agents() -> list[dict]:
    seed()
    return sorted(STORE.list(), key=lambda a: (not a.get("starter"), a["name"].lower()))


def find(ref: str) -> Optional[dict]:
    """By id, or by name/slug as typed in Spotlight ("@secretaria")."""
    ref = (ref or "").strip().lstrip("@")
    if not ref:
        return None
    seed()
    if store.ID_RE.match(ref):
        a = STORE.get(ref)
        if a:
            return a
    key = slug(ref)
    agents = all_agents()
    for a in agents:
        if slug(a["name"]) == key or a["id"] == key:
            return a
    for a in agents:
        if slug(a["name"]).startswith(key) or a["id"].startswith(key):
            return a
    return None


def effective_config(cfg: config.Config, agent: Optional[dict]) -> config.Config:
    """The global config narrowed to the agent's tools and model; Settings still caps it
    (a tool off in Settings stays off; read/write switches stay as they are)."""
    if agent is None:
        return cfg
    tools = set(agent.get("tools") or []) & set(cfg.tools)
    out = replace(cfg, tools=tools)
    if agent.get("model"):
        out = replace(out, model=agent["model"])
    if isinstance(agent.get("think"), bool):
        out = replace(out, think=agent["think"])
    return out


def write_tools(agent: dict, cfg: config.Config) -> list[str]:
    eff = effective_config(cfg, agent)
    return [t for t in eff.enabled_tools() if config.TOOLS[t][0] == config.WRITE]
