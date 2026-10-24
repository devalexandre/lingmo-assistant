"""Lingmo Mail through its own worker (backend.py: one JSON request on stdin,
one JSON line back).

Only an allowlist of operations is ever sent: reading (accounts, list, read
with "peek" so nothing is marked read), sending, moving/flagging, saving
attachments and creating contacts. Operations that delete or that run the
user's filter rules (which may delete) are never sent: `list` always goes with
checkNew=false.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from email.utils import parseaddr

CANDIDATES = ["/usr/libexec/lingmo-mail/backend.py", "/usr/lib/lingmo-mail/backend.py"]
TIMEOUT = 60
REPLY_LIMIT = 32 * 1024 * 1024
ALLOWED_OPS = {"accounts", "list", "read", "send", "act", "contacts", "saveContact", "saveAttachments"}
ALLOWED_ACTS = {"read", "unread", "star", "unstar", "move", "archive"}


class MailError(Exception):
    pass


def backend_path() -> str | None:
    override = os.environ.get("LINGMO_ASSISTANT_MAIL_BACKEND")
    if override:
        return override if os.path.isfile(override) else None
    for c in CANDIDATES:
        if os.path.isfile(c):
            return c
    return None


def call(request: dict) -> object:
    op = request.get("op")
    if op not in ALLOWED_OPS:
        raise MailError("Operação de e-mail não permitida.")
    if op == "act" and request.get("action") not in ALLOWED_ACTS:
        raise MailError("Fluxos e o assistente não apagam e-mails.")
    if op == "act" and request.get("permanent"):
        raise MailError("Fluxos e o assistente não apagam e-mails.")
    if op == "saveContact" and (request.get("contact") or {}).get("id"):
        raise MailError("O assistente só cria contatos novos.")
    if op == "list":
        request = dict(request, checkNew=False)
    path = backend_path()
    if not path:
        raise MailError("O Lingmo Mail não está instalado.")
    argv = [sys.executable or "/usr/bin/python3", "-I", path]
    try:
        proc = subprocess.run(argv, input=(json.dumps(request, ensure_ascii=False) + "\n").encode(),
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=TIMEOUT, close_fds=True)
    except subprocess.TimeoutExpired as exc:
        raise MailError("O servidor de e-mail demorou demais para responder.") from exc
    except OSError as exc:
        raise MailError("Não foi possível abrir o Lingmo Mail.") from exc
    line = proc.stdout[:REPLY_LIMIT].split(b"\n", 1)[0]
    try:
        reply = json.loads(line)
    except ValueError as exc:
        raise MailError("Resposta inválida do Lingmo Mail.") from exc
    if not isinstance(reply, dict):
        raise MailError("Resposta inválida do Lingmo Mail.")
    if not reply.get("ok"):
        raise MailError(str(reply.get("error") or "O Lingmo Mail recusou o pedido."))
    return reply.get("data")


def accounts() -> list[dict]:
    data = call({"op": "accounts"})
    out = []
    for a in data if isinstance(data, list) else []:
        if isinstance(a, dict) and a.get("id"):
            out.append({"id": str(a["id"]), "name": str(a.get("name") or ""), "email": str(a.get("email") or "")})
    return out


def account(ref: str = "") -> dict:
    """An account by id or address; "" = the first one."""
    items = accounts()
    if not items:
        raise MailError("Nenhuma conta de e-mail no Lingmo Mail.")
    ref = (ref or "").strip().lower()
    if not ref:
        return items[0]
    for a in items:
        if a["id"].lower() == ref or a["email"].lower() == ref:
            return a
    raise MailError("Conta de e-mail não encontrada: %s" % ref)


def address_of(sender: str) -> str:
    return parseaddr(sender or "")[1].lower()


def _uid(value) -> str:
    uid = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", uid):
        raise MailError("Mensagem inválida.")
    return uid


def list_messages(account_id: str, folder: str = "INBOX", unread_only: bool = False, limit: int = 30,
                  search_field: str = "", query: str = "") -> list[dict]:
    req = {"op": "list", "id": account_id, "folder": folder or "INBOX", "limit": max(1, min(int(limit), 200)),
           "filter": "unread" if unread_only else "all", "sort": "desc", "checkNew": False}
    if query:
        req["search"] = {"field": search_field or "text", "query": query}
    data = call(req)
    return list((data or {}).get("messages") or []) if isinstance(data, dict) else []


def read_message(account_id: str, uid, folder: str = "INBOX") -> dict:
    data = call({"op": "read", "id": account_id, "message": _uid(uid), "folder": folder or "INBOX", "peek": True})
    if not isinstance(data, dict):
        raise MailError("Resposta inválida do Lingmo Mail.")
    return data


def _check_addresses(value: str, required: bool) -> str:
    value = " ".join(str(value or "").split())
    if required and not value:
        raise MailError("Informe o destinatário.")
    for part in [p for p in value.split(",") if p.strip()]:
        if "@" not in parseaddr(part)[1]:
            raise MailError("Endereço de e-mail inválido: %s" % part.strip())
    return value


def build_draft(to: str, subject: str, body: str, cc: str = "", in_reply_to: str = "", references: str = "") -> dict:
    subject = " ".join(str(subject or "").split())[:300]
    if not subject:
        raise MailError("Informe o assunto.")
    body = str(body or "")
    if not body.strip():
        raise MailError("A mensagem está vazia.")
    if len(body) > 200_000:
        raise MailError("Mensagem longa demais.")
    draft = {"to": _check_addresses(to, True), "cc": _check_addresses(cc, False), "subject": subject, "body": body}
    if in_reply_to:
        draft["inReplyTo"] = in_reply_to
        draft["references"] = (references + " " + in_reply_to).strip() if references else in_reply_to
    return draft


def send(account_id: str, draft: dict) -> dict:
    data = call({"op": "send", "id": account_id, "draft": draft})
    return data if isinstance(data, dict) else {}


def reply_draft(original: dict, body: str) -> dict:
    subject = str(original.get("subject") or "")
    if not subject.lower().startswith(("re:", "res:")):
        subject = "Re: " + subject
    to = original.get("replyTo") or original.get("sender") or ""
    quoted = "\n".join("> " + line for line in str(original.get("body") or "").splitlines()[:200])
    text = body.rstrip() + "\n\n" + "Em %s, %s escreveu:\n%s" % (original.get("date") or "", original.get("sender") or "", quoted)
    return build_draft(to, subject, text, "", str(original.get("messageId") or ""), str(original.get("references") or ""))


def organize(account_id: str, uid, folder: str, action: str, target: str = "") -> None:
    if action not in ALLOWED_ACTS:
        raise MailError("Fluxos e o assistente não apagam e-mails.")
    req = {"op": "act", "id": account_id, "folder": folder or "INBOX", "uids": [_uid(uid)], "action": action}
    if action == "move":
        if not target.strip():
            raise MailError("Informe a pasta de destino.")
        req["target"] = target.strip()
    call(req)


def save_attachments(account_id: str, uid, folder: str, dest: str) -> list[str]:
    data = call({"op": "saveAttachments", "id": account_id, "message": _uid(uid), "folder": folder or "INBOX",
                 "dest": dest})
    return [str(x) for x in (data or {}).get("saved", [])] if isinstance(data, dict) else []


def add_contact(name: str, email: str, phone: str = "", notes: str = "") -> None:
    name = " ".join(str(name or "").split())[:200]
    if not name:
        raise MailError("Informe o nome do contato.")
    _check_addresses(email, True)
    call({"op": "saveContact", "contact": {"name": name, "emails": [email.strip()], "phone": str(phone or "")[:60],
                                           "notes": str(notes or "")[:4000]}})
