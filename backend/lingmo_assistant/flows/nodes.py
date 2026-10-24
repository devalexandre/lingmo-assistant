"""The node types a workflow can use (the single source of truth: the app's
palette and inspector are built from `catalogue()`).

Every node that writes, sends or creates something declares it in
`capability`: the contract tool id that must be on in Settings (the global
caps), a verb for the plain-language summary, and whether it leaves the
computer or speaks for the user (`external`, asked again on every run unless
the user ticks "não perguntar de novo"). There is no node that deletes, and
`validate()` refuses any type or option that would.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

TRIGGER, ACTION, AI, LOGIC = "triggers", "actions", "ai", "logic"

CATEGORIES = [
    {"id": TRIGGER, "label": "Gatilhos"},
    {"id": ACTION, "label": "Ações"},
    {"id": AI, "label": "IA"},
    {"id": LOGIC, "label": "Lógica"},
]


@dataclass
class Param:
    name: str
    label: str
    kind: str = "text"          # text, textarea, number, bool, select, time, schedule, account,
                                # agent, folder, path, list, key, language
    default: object = ""
    required: bool = False
    options: list = field(default_factory=list)     # select: [{"value", "label"}]
    placeholder: str = ""
    help: str = ""
    template: bool = True       # accepts {{…}}

    def to_dict(self) -> dict:
        return {"name": self.name, "label": self.label, "kind": self.kind, "default": self.default,
                "required": self.required, "options": self.options, "placeholder": self.placeholder,
                "help": self.help, "template": self.template and self.kind in ("text", "textarea", "list")}


@dataclass
class Capability:
    tools: tuple[str, ...]      # contract tool ids that must be enabled (all of them)
    verb: str                   # pt-BR, for "Este fluxo pode …"
    writes: bool = True         # creates, sends or changes something
    external: bool = False      # leaves the computer / speaks for the user: asked on every run


@dataclass
class NodeType:
    type: str
    category: str
    label: str
    description: str
    icon: str
    params: list[Param] = field(default_factory=list)
    ports: list[str] = field(default_factory=lambda: ["out"])
    outputs: list[str] = field(default_factory=lambda: ["output"])
    capability: Optional[Capability] = None
    group: str = ""

    @property
    def has_input(self) -> bool:
        return self.category != TRIGGER

    def to_dict(self) -> dict:
        cap = None
        if self.capability:
            cap = {"tools": list(self.capability.tools), "verb": self.capability.verb,
                   "writes": self.capability.writes, "external": self.capability.external}
        return {"type": self.type, "category": self.category, "group": self.group, "label": self.label,
                "description": self.description, "icon": self.icon,
                "params": [p.to_dict() for p in self.params], "ports": self.ports,
                "port_labels": {p: PORT_LABELS.get(p, p) for p in self.ports},
                "input": self.has_input, "outputs": self.outputs, "capability": cap}


PORT_LABELS = {"out": "", "true": "Sim", "false": "Não", "each": "Para cada", "done": "Depois",
               "yes": "Sim", "no": "Não", "default": "Outro"}

SCHEDULE_HELP = "Diário, dias da semana, a cada N minutos, mensal ou cron (avançado)."
MAIL_ACTIONS = [{"value": "move", "label": "Mover para pasta"}, {"value": "read", "label": "Marcar como lida"},
                {"value": "unread", "label": "Marcar como não lida"}, {"value": "star", "label": "Marcar com estrela"},
                {"value": "unstar", "label": "Tirar a estrela"}, {"value": "archive", "label": "Arquivar"}]
COMPARE_OPS = [{"value": "contains", "label": "contém"}, {"value": "not_contains", "label": "não contém"},
               {"value": "equals", "label": "é igual a"}, {"value": "not_equals", "label": "é diferente de"},
               {"value": "starts", "label": "começa com"}, {"value": "empty", "label": "está vazio"},
               {"value": "not_empty", "label": "não está vazio"}, {"value": "gt", "label": "maior que"},
               {"value": "lt", "label": "menor que"}]

_MSG = "{{trigger.uid}}"

TYPES: list[NodeType] = [
    # ------------------------------------------------------------ triggers
    NodeType("trigger.manual", TRIGGER, "Manual", "Roda quando você clica em Executar (ou pelo Spotlight).",
             "media-playback-start", [Param("spotlight", "Mostrar no Spotlight", "bool", True, template=False)],
             outputs=["output"]),
    NodeType("trigger.schedule", TRIGGER, "Agendamento", "Roda em horários definidos.", "chronometer",
             [Param("schedule", "Quando", "schedule", {"kind": "daily", "time": "09:00", "days": [0, 1, 2, 3, 4]},
                    True, help=SCHEDULE_HELP, template=False)],
             outputs=["date", "time", "output"]),
    NodeType("trigger.email", TRIGGER, "Novo e-mail", "Roda quando chega um e-mail que combina com o filtro.",
             "mail-unread", [
                 Param("account", "Conta", "account", "", template=False),
                 Param("from_contains", "Remetente contém", placeholder="chefe@empresa.com", template=False),
                 Param("subject_contains", "Assunto contém", template=False),
                 Param("has_attachment", "Só com anexo", "bool", False, template=False),
             ], outputs=["subject", "sender", "from_address", "body", "date", "uid", "folder", "account",
                         "attachments", "output"], group="Mail",
             capability=Capability(("mail_read",), "ler seus e-mails", writes=False)),
    NodeType("trigger.calendar", TRIGGER, "Evento começando", "Roda alguns minutos antes de um evento do calendário.",
             "appointment-soon", [
                 Param("minutes_before", "Minutos antes", "number", 10, True, template=False),
                 Param("title_contains", "Título contém", template=False, placeholder="reunião"),
             ], outputs=["title", "start", "location", "minutes", "output"], group="Calendário",
             capability=Capability(("calendar_read",), "ler seu calendário", writes=False)),
    NodeType("trigger.file", TRIGGER, "Arquivo ou pasta mudou", "Roda quando um arquivo aparece ou muda numa pasta permitida.",
             "folder-sync", [
                 Param("folder", "Pasta", "folder", "~/Downloads", True, template=False),
                 Param("pattern", "Nomes", placeholder="*.pdf", default="*", template=False),
             ], outputs=["path", "name", "event", "output"], group="Arquivos",
             capability=Capability(("read_files",), "observar pastas permitidas", writes=False)),
    NodeType("trigger.shortcut", TRIGGER, "Atalho de teclado", "Roda com um atalho global.", "input-keyboard",
             [Param("key", "Atalho", "key", "Meta+Shift+F", True, template=False)], outputs=["output"]),
    NodeType("trigger.voice", TRIGGER, "Comando de voz", "Roda quando você diz uma das frases ao assistente.",
             "audio-input-microphone", [
                 Param("phrases", "Frases", "list", ["me acorde às sete"], True, template=False),
                 Param("match", "Reconhecer por", "select", "keywords", options=[
                     {"value": "keywords", "label": "Palavras-chave"}, {"value": "ai", "label": "IA (sentido parecido)"}],
                     template=False),
             ], outputs=["text", "output"]),
    NodeType("trigger.system", TRIGGER, "Evento do sistema", "Login, pendrive conectado ou bateria fraca.",
             "computer", [
                 Param("event", "Evento", "select", "login", True, options=[
                     {"value": "login", "label": "Ao entrar na sessão"},
                     {"value": "usb", "label": "Dispositivo USB conectado"},
                     {"value": "battery_low", "label": "Bateria fraca"}], template=False),
                 Param("threshold", "Bateria abaixo de (%)", "number", 15, template=False),
             ], outputs=["event", "detail", "output"]),

    # ------------------------------------------------------------ actions: mail
    NodeType("action.mail.send", ACTION, "Enviar e-mail", "Envia um e-mail pela sua conta do Lingmo Mail.",
             "mail-send", [
                 Param("account", "Conta", "account", "", template=False),
                 Param("to", "Para", required=True, placeholder="alguem@exemplo.com"),
                 Param("cc", "Cc"),
                 Param("subject", "Assunto", required=True),
                 Param("body", "Mensagem", "textarea", required=True),
             ], outputs=["output", "to"], group="Mail",
             capability=Capability(("mail_write",), "enviar e-mails como {account}", external=True)),
    NodeType("action.mail.reply", ACTION, "Responder e-mail", "Responde a um e-mail; a IA pode escrever o rascunho.",
             "mail-reply-sender", [
                 Param("account", "Conta", "account", "{{trigger.account}}"),
                 Param("message", "Mensagem (id)", default=_MSG, required=True),
                 Param("folder", "Pasta", default="{{trigger.folder}}"),
                 Param("ai_draft", "A IA escreve o rascunho", "bool", True, template=False),
                 Param("instructions", "Instruções para a IA", "textarea",
                       "Responda de forma educada e objetiva, confirmando o recebimento."),
                 Param("body", "Texto (sem IA)", "textarea"),
             ], outputs=["output", "draft", "to"], group="Mail",
             capability=Capability(("mail_write", "mail_read"), "responder e-mails como {account}", external=True)),
    NodeType("action.mail.organize", ACTION, "Mover ou marcar e-mail", "Move para uma pasta, arquiva ou marca (lida, estrela).",
             "mail-move", [
                 Param("account", "Conta", "account", "{{trigger.account}}"),
                 Param("message", "Mensagem (id)", default=_MSG, required=True),
                 Param("folder", "Pasta atual", default="{{trigger.folder}}"),
                 Param("action", "Ação", "select", "star", True, options=MAIL_ACTIONS, template=False),
                 Param("target", "Pasta de destino", placeholder="Trabalho"),
             ], group="Mail", capability=Capability(("mail_write",), "organizar e-mails (mover e marcar)")),
    NodeType("action.mail.attachments", ACTION, "Salvar anexos", "Salva os anexos de um e-mail numa pasta permitida.",
             "mail-attachment", [
                 Param("account", "Conta", "account", "{{trigger.account}}"),
                 Param("message", "Mensagem (id)", default=_MSG, required=True),
                 Param("folder", "Pasta do e-mail", default="{{trigger.folder}}"),
                 Param("dest", "Salvar em", "folder", "~/Documentos", True, template=False),
             ], outputs=["output", "files"], group="Mail",
             capability=Capability(("mail_read", "files_write"), "salvar anexos de e-mail em pastas permitidas")),
    NodeType("action.contacts.add", ACTION, "Adicionar contato", "Cria um contato no Lingmo Mail.",
             "contact-new", [Param("name", "Nome", required=True), Param("email", "E-mail", required=True),
                             Param("phone", "Telefone"), Param("notes", "Notas", "textarea")],
             group="Mail", capability=Capability(("mail_write",), "adicionar contatos")),
    # ------------------------------------------------------------ actions: calendar, clock, notes, files
    NodeType("action.calendar.event", ACTION, "Criar evento", "Cria um evento no calendário do Lingmo Mail.",
             "appointment-new", [
                 Param("title", "Título", required=True),
                 Param("start", "Início", required=True, placeholder="2026-10-25T14:00"),
                 Param("duration", "Duração (min)", "number", 60),
                 Param("location", "Local"), Param("notes", "Notas", "textarea"),
                 Param("reminder", "Alerta (min antes)", "number", 10),
             ], group="Calendário", capability=Capability(("calendar_write",), "criar eventos no calendário")),
    NodeType("action.calendar.task", ACTION, "Criar tarefa", "Cria uma tarefa no Lingmo Mail.", "view-task-add",
             [Param("title", "Título", required=True), Param("due", "Prazo", placeholder="2026-10-25"),
              Param("notes", "Notas", "textarea")],
             group="Calendário", capability=Capability(("calendar_write",), "criar tarefas")),
    NodeType("action.clock.alarm", ACTION, "Criar alarme", "Cria um alarme no Relógio.", "chronometer",
             [Param("time", "Hora", "text", "07:00", True, placeholder="07:00"), Param("label", "Nome", default="Alarme")],
             group="Relógio", capability=Capability(("alarms_write",), "criar alarmes")),
    NodeType("action.clock.timer", ACTION, "Criar timer", "Inicia um timer no Relógio.", "chronometer-start",
             [Param("minutes", "Minutos", "number", 5, True), Param("label", "Nome", default="Timer")],
             group="Relógio", capability=Capability(("alarms_write",), "criar timers")),
    NodeType("action.notes.write", ACTION, "Criar ou completar nota", "Cria uma página no Notas ou acrescenta texto a uma.",
             "document-edit", [
                 Param("mode", "Modo", "select", "create", options=[{"value": "create", "label": "Criar página"},
                                                                     {"value": "append", "label": "Acrescentar a uma página"}],
                       template=False),
                 Param("title", "Título (ou página)", required=True),
                 Param("content", "Conteúdo (Markdown)", "textarea", required=True),
             ], outputs=["output", "page_id"], group="Notas",
             capability=Capability(("notes_write",), "criar e completar notas")),
    NodeType("action.files.read", ACTION, "Ler arquivo", "Lê um documento de uma pasta permitida.", "document-open",
             [Param("path", "Arquivo", "path", required=True)], outputs=["output", "name"], group="Arquivos",
             capability=Capability(("read_files",), "ler arquivos das pastas permitidas", writes=False)),
    NodeType("action.files.write", ACTION, "Escrever arquivo", "Cria um arquivo de texto ou acrescenta ao fim (nunca apaga).",
             "document-save", [
                 Param("path", "Arquivo", "path", required=True, placeholder="~/Documentos/resumo.md"),
                 Param("content", "Conteúdo", "textarea", required=True),
                 Param("mode", "Modo", "select", "append", options=[{"value": "create", "label": "Criar novo"},
                                                                     {"value": "append", "label": "Acrescentar ao fim"}],
                       template=False),
             ], outputs=["output", "path"], group="Arquivos",
             capability=Capability(("files_write",), "criar arquivos nas pastas permitidas")),
    # ------------------------------------------------------------ actions: system
    NodeType("action.system.notify", ACTION, "Mostrar notificação", "Mostra uma notificação na área de trabalho.",
             "notifications", [Param("title", "Título", required=True), Param("body", "Texto", "textarea")],
             group="Sistema"),
    NodeType("action.system.speak", ACTION, "Falar texto", "Lê um texto em voz alta (voz local).", "audio-speakers",
             [Param("text", "Texto", "textarea", required=True)], group="Sistema"),
    NodeType("action.system.open", ACTION, "Abrir app ou site", "Abre um aplicativo instalado ou um endereço https.",
             "system-run", [Param("target", "App ou endereço", required=True, placeholder="lingmo-mail ou https://…")],
             group="Sistema", capability=Capability(("desktop_actions",), "abrir apps e sites")),
    NodeType("action.system.screenshot", ACTION, "Capturar a tela", "Salva uma captura da tela numa pasta permitida.",
             "camera-photo", [Param("folder", "Salvar em", "folder", "~/Imagens", True, template=False)],
             outputs=["output", "path"], group="Sistema",
             capability=Capability(("desktop_actions",), "capturar a tela")),
    NodeType("action.system.command", ACTION, "Comando seguro", "Roda um comando de leitura da lista permitida, em sandbox.",
             "utilities-terminal", [Param("command", "Comando", required=True, placeholder="df -h")],
             group="Sistema", capability=Capability(("shell_read",), "rodar comandos de leitura", writes=False)),

    # ------------------------------------------------------------ AI
    NodeType("ai.agent", AI, "Perguntar a um agente", "Envia um pedido a um dos seus agentes.", "internet-chat",
             [Param("agent", "Agente", "agent", "", template=False), Param("prompt", "Pedido", "textarea", required=True)]),
    NodeType("ai.summarize", AI, "Resumir", "Resume um texto.", "view-list-text",
             [Param("text", "Texto", "textarea", required=True),
              Param("style", "Formato", "select", "bullets", options=[
                  {"value": "bullets", "label": "Tópicos"}, {"value": "short", "label": "Um parágrafo"}], template=False)]),
    NodeType("ai.classify", AI, "Classificar", "Escolhe uma das categorias para o texto.", "tag",
             [Param("text", "Texto", "textarea", required=True),
              Param("categories", "Categorias", "list", ["urgente", "normal"], True, template=False)],
             outputs=["output", "category"]),
    NodeType("ai.extract", AI, "Extrair dados", "Extrai campos do texto para variáveis.", "view-form",
             [Param("text", "Texto", "textarea", required=True),
              Param("fields", "Campos", "list", ["data", "hora", "assunto"], True, template=False)],
             outputs=["output"]),
    NodeType("ai.translate", AI, "Traduzir", "Traduz um texto.", "preferences-desktop-locale",
             [Param("text", "Texto", "textarea", required=True), Param("language", "Para", "language", "inglês", True)]),

    # ------------------------------------------------------------ logic
    NodeType("logic.if", LOGIC, "Condição", "Segue por Sim ou Não.", "code-branch", [
        Param("value", "Valor", required=True, default="{{trigger.output}}"),
        Param("op", "Regra", "select", "contains", options=COMPARE_OPS, template=False),
        Param("compare", "Com"),
    ], ports=["true", "false"], outputs=["output"]),
    NodeType("logic.switch", LOGIC, "Escolha", "Segue pelo primeiro caso igual ao valor.", "code-class", [
        Param("value", "Valor", required=True), Param("cases", "Casos", "list", ["urgente", "normal"], True, template=False),
    ], ports=["case_0", "case_1", "default"], outputs=["output"]),
    NodeType("logic.loop", LOGIC, "Repetir para cada", "Roda o ramo \"Para cada\" para cada item de uma lista.",
             "view-refresh", [Param("items", "Lista", required=True, help="Uma lista ou um texto com um item por linha."),
                              Param("max", "Máximo de itens", "number", 50, template=False)],
             ports=["each", "done"], outputs=["output", "count"]),
    NodeType("logic.wait", LOGIC, "Esperar", "Espera um tempo antes de seguir.", "chronometer-pause",
             [Param("seconds", "Segundos", "number", 60, True)]),
    NodeType("logic.ask", LOGIC, "Perguntar a você", "Pede uma confirmação ou um texto antes de seguir.",
             "dialog-question", [
                 Param("mode", "Tipo", "select", "confirm", options=[{"value": "confirm", "label": "Sim ou não"},
                                                                     {"value": "input", "label": "Texto"}], template=False),
                 Param("question", "Pergunta", "textarea", required=True),
             ], ports=["yes", "no"], outputs=["output"]),
    NodeType("logic.set", LOGIC, "Definir variável", "Guarda um valor em {{var.nome}}.", "format-text-code",
             [Param("name", "Nome", required=True, template=False, placeholder="resumo"), Param("value", "Valor", "textarea")]),
]

BY_TYPE = {t.type: t for t in TYPES}
FORBIDDEN_WORDS = ("delete", "remove", "trash", "erase", "expunge", "wipe", "apagar", "excluir")


def get(type_: str) -> Optional[NodeType]:
    return BY_TYPE.get(type_)


def ports_for(node: dict) -> list[str]:
    """Output ports of a node; a switch has one port per case."""
    nt = BY_TYPE.get(node.get("type", ""))
    if nt is None:
        return []
    if nt.type == "logic.switch":
        cases = (node.get("params") or {}).get("cases") or []
        return ["case_%d" % i for i in range(len(cases) if isinstance(cases, list) else 0)] + ["default"]
    if nt.type == "logic.ask" and (node.get("params") or {}).get("mode") == "input":
        return ["yes"]
    return list(nt.ports)


def outputs_for(node: dict) -> list[str]:
    nt = BY_TYPE.get(node.get("type", ""))
    if nt is None:
        return []
    outs = list(nt.outputs)
    if nt.type == "ai.extract":
        fields = (node.get("params") or {}).get("fields") or []
        outs += [str(f) for f in fields if isinstance(f, str)]
    return outs


def catalogue() -> dict:
    return {"categories": CATEGORIES, "types": [t.to_dict() for t in TYPES]}
