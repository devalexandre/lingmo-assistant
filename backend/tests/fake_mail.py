"""A tiny local IMAPS + SMTPS pair for end-to-end tests of the mail nodes:
just enough IMAP4rev1 for Lingmo Mail's worker (LOGIN, LIST, SELECT/EXAMINE,
STATUS, UID SEARCH/FETCH/STORE/MOVE), and aiosmtpd for SMTP. Both use a
throw-away self-signed certificate; nothing leaves 127.0.0.1."""
from __future__ import annotations

import email
import email.policy
import re
import shutil
import socket
import socketserver
import ssl
import subprocess
import threading
from pathlib import Path


def make_cert(directory: Path) -> tuple[Path, Path]:
    if not shutil.which("openssl"):
        raise RuntimeError("openssl missing")
    cert, key = directory / "cert.pem", directory / "key.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-subj",
                    "/CN=localhost", "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
                    "-addext", "basicConstraints=critical,CA:TRUE",
                    "-keyout", str(key), "-out", str(cert)], check=True, capture_output=True)
    return cert, key


class Mailbox:
    def __init__(self):
        self.folders = {"INBOX": [], "Trabalho": [], "Archive": [], "Trash": []}
        self.next_uid = 1
        self.lock = threading.Lock()
        self.log: list[str] = []

    def add(self, folder: str, raw: bytes, flags=()):
        with self.lock:
            uid = self.next_uid
            self.next_uid += 1
            self.folders[folder].append({"uid": uid, "raw": raw, "flags": set(flags)})
            return uid

    def find(self, folder, uid):
        return next((m for m in self.folders[folder] if m["uid"] == uid), None)


def _uids(spec: str, msgs) -> list[int]:
    out = []
    for part in spec.split(","):
        if ":" in part:
            a, b = part.split(":")
            hi = max([m["uid"] for m in msgs] or [0])
            a = int(a)
            b = hi if b == "*" else int(b)
            out += [m["uid"] for m in msgs if a <= m["uid"] <= b]
        elif part.isdigit():
            out.append(int(part))
    return out


class IMAPHandler(socketserver.StreamRequestHandler):
    box: Mailbox = None

    def send(self, text):
        data = text.encode() if isinstance(text, str) else text
        self.wfile.write(data)
        self.wfile.flush()

    def handle(self):
        selected = None
        self.send("* OK fake IMAP ready\r\n")
        while True:
            line = self.rfile.readline()
            if not line:
                return
            text = line.decode("utf-8", "replace").rstrip("\r\n")
            m = re.match(r"(\S+) (\S+)(?: (.*))?$", text)
            if not m:
                continue
            tag, cmd, rest = m[1], m[2].upper(), m[3] or ""
            self.box.log.append(cmd + " " + rest)
            if cmd == "CAPABILITY":
                self.send("* CAPABILITY IMAP4rev1 MOVE UIDPLUS\r\n%s OK done\r\n" % tag)
            elif cmd == "LOGIN":
                self.send("%s OK logged in\r\n" % tag)
            elif cmd == "LOGOUT":
                self.send("* BYE\r\n%s OK bye\r\n" % tag)
                return
            elif cmd == "NOOP":
                self.send("%s OK done\r\n" % tag)
            elif cmd == "LIST":
                out = ""
                for f in self.box.folders:
                    flag = {"Archive": "\\Archive", "Trash": "\\Trash"}.get(f, "")
                    out += '* LIST (\\HasNoChildren%s) "/" "%s"\r\n' % ((" " + flag) if flag else "", f)
                self.send(out + "%s OK done\r\n" % tag)
            elif cmd in ("SELECT", "EXAMINE"):
                selected = rest.strip('"')
                n = len(self.box.folders.get(selected, []))
                self.send("* %d EXISTS\r\n* OK [UIDVALIDITY 7]\r\n%s OK [READ-WRITE] done\r\n" % (n, tag))
            elif cmd == "STATUS":
                fm = re.match(r'"?([^"]+)"? ', rest)
                f = fm[1] if fm else "INBOX"
                unseen = sum(1 for x in self.box.folders.get(f, []) if "\\Seen" not in x["flags"])
                self.send('* STATUS "%s" (UNSEEN %d)\r\n%s OK done\r\n' % (f, unseen, tag))
            elif cmd == "UID":
                self.uid(tag, rest, selected)
            elif cmd == "EXPUNGE":
                self.send("%s OK done\r\n" % tag)
            else:
                self.send("%s BAD unknown\r\n" % tag)

    def uid(self, tag, rest, folder):
        sub, _, args = rest.partition(" ")
        sub = sub.upper()
        msgs = self.box.folders.get(folder, [])
        if sub == "SEARCH":
            if "UNSEEN" in args.upper():
                found = [m["uid"] for m in msgs if "\\Seen" not in m["flags"]]
            else:
                found = [m["uid"] for m in msgs]
            self.send("* SEARCH %s\r\n%s OK done\r\n" % (" ".join(map(str, found)), tag))
        elif sub == "FETCH":
            spec, _, items = args.partition(" ")
            out = b""
            for i, uid in enumerate(_uids(spec, msgs)):
                msg = self.box.find(folder, uid)
                if msg is None:
                    continue
                seq = msgs.index(msg) + 1
                flags = " ".join(sorted(msg["flags"]))
                if "RFC822.SIZE" in items:
                    out += b"* %d FETCH (UID %d RFC822.SIZE %d)\r\n" % (seq, uid, len(msg["raw"]))
                elif "BODY.PEEK[]" in items:
                    out += b"* %d FETCH (UID %d BODY[] {%d}\r\n" % (seq, uid, len(msg["raw"])) + msg["raw"] + b")\r\n"
                else:
                    parsed = email.message_from_bytes(msg["raw"], policy=email.policy.default)
                    header = "".join("%s: %s\r\n" % (k, parsed[k]) for k in ("From", "To", "Cc", "Subject", "Date")
                                     if parsed[k]).encode() + b"\r\n"
                    structure = b'("TEXT" "PLAIN" NIL NIL NIL "7BIT" 10 1)'
                    if any(True for _ in parsed.iter_attachments()):
                        structure = b'(("TEXT" "PLAIN" NIL NIL NIL "7BIT" 10 1)("APPLICATION" "PDF" ("NAME" "a.pdf") ' \
                                    b'NIL NIL "BASE64" 10 NIL ("ATTACHMENT" ("FILENAME" "a.pdf"))) "MIXED")'
                    out += (b"* %d FETCH (UID %d FLAGS (%s) BODYSTRUCTURE %s BODY[HEADER.FIELDS (FROM TO CC SUBJECT DATE)] {%d}\r\n"
                            % (seq, uid, flags.encode(), structure, len(header)) + header + b")\r\n")
            self.send(out + b"%s OK done\r\n" % tag.encode())
        elif sub == "STORE":
            spec, op, flags = args.split(" ", 2)
            flagset = set(flags.strip("()").split())
            for uid in _uids(spec, msgs):
                msg = self.box.find(folder, uid)
                if msg is None:
                    continue
                if op.startswith("+"):
                    msg["flags"] |= flagset
                else:
                    msg["flags"] -= flagset
            self.send("%s OK done\r\n" % tag)
        elif sub == "MOVE":
            spec, _, target = args.partition(" ")
            target = target.strip('"')
            for uid in _uids(spec, msgs):
                msg = self.box.find(folder, uid)
                if msg:
                    msgs.remove(msg)
                    self.box.folders[target].append(msg)
            self.send("%s OK done\r\n" % tag)
        else:
            self.send("%s BAD no\r\n" % tag)


class TLSServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, handler, context):
        super().__init__(("127.0.0.1", 0), handler)
        self.context = context

    def get_request(self):
        sock, addr = super().get_request()
        return self.context.wrap_socket(sock, server_side=True), addr


class FakeMail:
    def __init__(self, directory: Path):
        self.cert, self.key = make_cert(directory)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(self.cert, self.key)
        self.box = Mailbox()
        handler = type("H", (IMAPHandler,), {"box": self.box})
        self.imap = TLSServer(handler, ctx)
        threading.Thread(target=self.imap.serve_forever, daemon=True).start()
        self.sent: list[bytes] = []
        from aiosmtpd.controller import Controller
        from aiosmtpd.smtp import AuthResult

        sent = self.sent

        class Handler:
            async def handle_DATA(self, server, session, envelope):
                sent.append(envelope.content)
                return "250 OK"

        port = _free_port()
        self.smtp = Controller(Handler(), hostname="127.0.0.1", port=port, ssl_context=ctx,
                               authenticator=lambda *a: AuthResult(success=True), auth_require_tls=False)
        self.smtp.start()
        self.smtp_port = port

    @property
    def imap_port(self) -> int:
        return self.imap.server_address[1]

    def account(self, email_addr="eu@exemplo.com") -> dict:
        return {"id": "11111111-2222-4333-8444-555555555555", "name": "Eu", "email": email_addr, "protocol": "imap",
                "username": email_addr, "smtpUsername": email_addr, "incomingHost": "localhost",
                "incomingPort": self.imap_port, "incomingSecurity": "tls", "smtpHost": "localhost",
                "smtpPort": self.smtp_port, "smtpSecurity": "tls"}

    def close(self):
        self.imap.shutdown()
        self.smtp.stop()


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port
