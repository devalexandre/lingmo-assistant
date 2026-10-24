"""Starter workflows offered in "Novo fluxo › Modelos"."""
from __future__ import annotations

import copy

X = 245


def _n(id_, type_, col, row=0, label="", **params):
    return {"id": id_, "type": type_, "label": label, "x": 60 + col * X, "y": 80 + row * 170, "params": params}


def _e(a, b, port="out"):
    return {"from": a, "port": port, "to": b}


TEMPLATES = [
    {"template": "reply-boss", "name": "Responder e-mails do chefe com rascunho",
     "description": "Quando chega um e-mail do seu chefe, a IA escreve a resposta e você aprova antes de enviar.",
     "icon": "mail-reply-sender",
     "nodes": [_n("trigger", "trigger.email", 0, label="E-mail do chefe", from_contains="chefe@empresa.com"),
               _n("resposta", "action.mail.reply", 1, label="Rascunho e resposta", ai_draft=True,
                  instructions="Responda de forma educada e objetiva, confirmando que vou verificar o assunto "
                               "hoje. Assine apenas com meu primeiro nome."),
               _n("aviso", "action.system.notify", 2, label="Avisar", title="Resposta enviada",
                  body="{{trigger.subject}} → {{resposta.to}}")],
     "edges": [_e("trigger", "resposta"), _e("resposta", "aviso")]},
    {"template": "meeting-reminder", "name": "Lembrete de reunião 10 min antes",
     "description": "Avisa e fala em voz alta 10 minutos antes de cada reunião do calendário.",
     "icon": "appointment-soon",
     "nodes": [_n("trigger", "trigger.calendar", 0, label="Reunião em 10 min", minutes_before=10,
                  title_contains="reunião"),
               _n("aviso", "action.system.notify", 1, label="Notificar", title="Reunião em 10 minutos",
                  body="{{trigger.title}} às {{trigger.start}} {{trigger.location}}"),
               _n("falar", "action.system.speak", 2, label="Falar",
                  text="Sua reunião {{trigger.title}} começa em 10 minutos.")],
     "edges": [_e("trigger", "aviso"), _e("aviso", "falar")]},
    {"template": "daily-mail-summary", "name": "Resumo diário dos e-mails às 9h",
     "description": "Nos dias úteis às 9h, a Secretária de e-mail resume os não lidos numa página do Notas.",
     "icon": "view-list-text",
     "nodes": [_n("trigger", "trigger.schedule", 0, label="Dias úteis às 9h",
                  schedule={"kind": "weekdays", "time": "09:00", "days": [0, 1, 2, 3, 4]}),
               _n("resumo", "ai.agent", 1, label="Resumir e-mails", agent="secretaria-de-email",
                  prompt="Liste meus e-mails não lidos e faça um resumo curto em tópicos: remetente, assunto e o "
                         "que preciso fazer. Destaque o que for urgente."),
               _n("nota", "action.notes.write", 2, label="Guardar no Notas", mode="append",
                  title="Resumo dos e-mails", content="## {{now.date}}\n\n{{resumo.output}}"),
               _n("aviso", "action.system.notify", 3, label="Avisar", title="Resumo dos e-mails pronto",
                  body="Está no Notas, na página «Resumo dos e-mails».")],
     "edges": [_e("trigger", "resumo"), _e("resumo", "nota"), _e("nota", "aviso")]},
    {"template": "save-attachments", "name": "Salvar anexos em Documentos",
     "description": "Guarda os anexos dos e-mails recebidos em ~/Documentos/Anexos.",
     "icon": "mail-attachment",
     "nodes": [_n("trigger", "trigger.email", 0, label="E-mail com anexo", has_attachment=True),
               _n("salvar", "action.mail.attachments", 1, label="Salvar anexos", dest="~/Documentos/Anexos"),
               _n("aviso", "action.system.notify", 2, label="Avisar", title="Anexos salvos",
                  body="{{salvar.output}}")],
     "edges": [_e("trigger", "salvar"), _e("salvar", "aviso")]},
    {"template": "voice-alarm", "name": "Alarme pelo comando de voz",
     "description": "Diga \"me acorde às sete\": a IA entende a hora e cria o alarme no Relógio.",
     "icon": "audio-input-microphone",
     "nodes": [_n("trigger", "trigger.voice", 0, label="\"Me acorde às…\"",
                  phrases=["me acorde às sete", "criar alarme para as oito", "alarme às seis e meia"], match="keywords"),
               _n("hora", "ai.extract", 1, label="Entender a hora", text="{{trigger.text}}", fields=["hora"]),
               _n("alarme", "action.clock.alarm", 2, label="Criar alarme", time="{{hora.hora}}", label_="",
                  ),
               _n("falar", "action.system.speak", 3, label="Confirmar", text="Pronto, alarme criado para {{hora.hora}}.")],
     "edges": [_e("trigger", "hora"), _e("hora", "alarme"), _e("alarme", "falar")]},
]

# The voice-alarm node's own "label" param (the alarm name)
for t in TEMPLATES:
    for n in t["nodes"]:
        if "label_" in n["params"]:
            n["params"].pop("label_")
            n["params"]["label"] = "Acordar"


def list_templates() -> list[dict]:
    return [{"template": t["template"], "name": t["name"], "description": t["description"], "icon": t["icon"]}
            for t in TEMPLATES]


def instantiate(template_id: str) -> dict | None:
    for t in TEMPLATES:
        if t["template"] == template_id:
            doc = copy.deepcopy(t)
            doc.pop("template")
            doc.pop("icon")
            doc["format"] = "lingmo-assistant-flow"
            doc["format_version"] = 1
            doc["enabled"] = True
            return doc
    return None
