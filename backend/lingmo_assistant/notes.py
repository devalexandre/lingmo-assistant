"""Lingmo Notes pages: read, search, create and append.

Notes keeps one Markdown file per page, <uuid>.md, in its AppDataLocation
($XDG_DATA_HOME/lingmoos/lingmo-notes), with a small frontmatter:

    ---
    id: <uuid>
    parent: <uuid or empty>
    icon: <emoji or empty>
    favorite: false
    order: 3
    created: 2026-10-07T09:00:00
    updated: 2026-10-07T09:00:00
    ---
    # Title

    body in Notes' Markdown dialect

This module is a faithful port of lingmo-texteditor/notes/markdown.cpp
(parseBlocks / serializeBlocks / parsePage / serializePage), so bodies written
here are already in the canonical form the app writes back.

Notes has no file watcher: a page created while it runs shows up the next time
Notes opens. Appending to an existing page while Notes runs could be lost (the
open page is saved from memory), so append is refused while Notes is open.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import tempfile
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path

MAX_PAGE = 2 * 1024 * 1024


def notes_dir() -> Path:
    override = os.environ.get("LINGMO_ASSISTANT_NOTES_DIR")
    if override:
        return Path(override)
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / "lingmoos" / "lingmo-notes"


class NotesError(Exception):
    pass


# ------------------------------------------------------------------ Markdown dialect

FENCE = re.compile(r"^(`{3,}|~{3,})(.*)$")
HEADING = re.compile(r"^(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
DIVIDER = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})\s*$")
TODO = re.compile(r"^[-*+] \[([ xX])\](?: (.*))?$")
TOGGLE = re.compile(r"^[-*+] ([▶▼])(?: (.*))?$")
BULLET = re.compile(r"^[-*+](?: (.*))?$")
NUMBERED = re.compile(r"^(\d{1,9})[.)](?: (.*))?$")
CALLOUT = re.compile(r"^> ?\[!([^\]]+)\](?: (.*))?$")
QUOTE = re.compile(r"^> ?(.*)$")
PAGE = re.compile(r"^\[((?:[^\]\\]|\\.)*)\]\(([0-9a-fA-F-]{36})\.md\)\s*$")
UUID_CHARS = re.compile(r"^[0-9a-fA-F-]{36}$")


def _match(rx, s):
    # QRegularExpression::match finds a match anywhere unless anchored; all
    # patterns are anchored with ^...$, and $ must not accept a trailing \n
    return rx.match(s) if "\n" not in s else None


def is_valid_id(value: str) -> bool:
    if not isinstance(value, str) or len(value) != 36 or not UUID_CHARS.match(value):
        return False
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


@dataclass
class Block:
    type: str = "paragraph"
    text: str = ""
    indent: int = 0
    checked: bool = False
    collapsed: bool = False
    emoji: str = ""
    language: str = ""
    ref: str = ""


def _is_marker(s: str) -> bool:
    if not s:
        return False
    for rx in (FENCE, HEADING, DIVIDER, BULLET, NUMBERED, PAGE):
        if _match(rx, s):
            return True
    return s.startswith(">")


def _needs_escape(line: str) -> bool:
    return line == "" or line[0].isspace() or line.startswith("\\") or _is_marker(line)


def _escape_line(line: str) -> str:
    return "\\" + line if _needs_escape(line) else line


def _unescape_line(s: str) -> str:
    return s[1:] if s.startswith("\\") and _needs_escape(s[1:]) else s


def _item_needs_escape(t: str) -> bool:
    return t.startswith("\\") or bool(re.match(r"^\[[ xX]\](?: |$)", t)) \
        or bool(re.match(r"^[▶▼](?: |$)", t))


def _escape_item(t: str) -> str:
    return "\\" + t if _item_needs_escape(t) else t


def _unescape_item(t: str) -> str:
    return t[1:] if t.startswith("\\") and _item_needs_escape(t[1:]) else t


def _quote_needs_escape(t: str) -> bool:
    return t.startswith("\\") or t.startswith("[!")


def _escape_quote(t: str) -> str:
    return "\\" + t if _quote_needs_escape(t) else t


def _unescape_quote(t: str) -> str:
    return t[1:] if t.startswith("\\") and _quote_needs_escape(t[1:]) else t


def _leading(line: str) -> tuple[int, int]:
    width = i = 0
    while i < len(line):
        if line[i] == " ":
            width += 1
        elif line[i] == "\t":
            width += 4
        else:
            break
        i += 1
    return width, i


def _strip_indent(line: str, width: int) -> str:
    i = w = 0
    while i < len(line) and w < width and line[i] in " \t":
        w += 4 if line[i] == "\t" else 1
        i += 1
    return line[i:]


def _is_ascii_word(s: str) -> bool:
    return bool(s) and all(c.isalpha() and ord(c) < 128 for c in s)


def _cap(m, n):
    v = m.group(n)
    return v if v is not None else ""


def _qt_trimmed_empty(s: str) -> bool:
    return s.strip() == ""


def parse_blocks(markdown: str) -> list[Block]:
    lines = markdown.replace("\r\n", "\n").split("\n")
    blocks: list[Block] = []
    cont = None
    i = 0
    while i < len(lines):
        raw = lines[i]
        if _qt_trimmed_empty(raw):
            cont = None
            i += 1
            continue
        spaces, chars = _leading(raw)
        s = raw[chars:]
        if cont == "quote" and s.startswith(">"):
            rest = s[1:]
            if rest.startswith(" "):
                rest = rest[1:]
            blocks[-1].text += "\n" + _unescape_quote(rest)
            i += 1
            continue
        if cont in ("para", "item") and not _is_marker(s):
            blocks[-1].text += "\n" + _unescape_line(s)
            i += 1
            continue
        b = Block(indent=min(spaces // 2, 8))
        cont = None
        m = None
        if (m := _match(FENCE, s)):
            fence = m.group(1)
            b.type = "code"
            b.language = _cap(m, 2).strip()
            content = []
            j = i + 1
            while j < len(lines):
                t = lines[j].strip()
                if len(t) >= len(fence) and t.startswith(fence) and t.count(fence[0]) == len(t):
                    break
                content.append(_strip_indent(lines[j], spaces))
                j += 1
            b.text = "\n".join(content)
            i = j
        elif (m := _match(HEADING, s)):
            b.type = "h%d" % min(len(m.group(1)), 3)
            b.text = _cap(m, 2)
        elif _match(DIVIDER, s):
            b.type = "divider"
        elif (m := _match(PAGE, s)) and is_valid_id(m.group(2)):
            b.type = "page"
            b.text = m.group(1).replace("\\]", "]").replace("\\\\", "\\")
            b.ref = m.group(2).lower()
        elif (m := _match(TODO, s)):
            b.type = "todo"
            b.checked = m.group(1) != " "
            b.text = _unescape_item(_cap(m, 2))
            cont = "item"
        elif (m := _match(TOGGLE, s)):
            b.type = "toggle"
            b.collapsed = m.group(1) == "▶"
            b.text = _unescape_item(_cap(m, 2))
            cont = "item"
        elif (m := _match(BULLET, s)):
            b.type = "bullet"
            b.text = _unescape_item(_cap(m, 1))
            cont = "item"
        elif (m := _match(NUMBERED, s)):
            b.type = "numbered"
            b.text = _unescape_item(_cap(m, 2))
            cont = "item"
        elif (m := _match(CALLOUT, s)) and not _is_ascii_word(m.group(1)):
            b.type = "callout"
            b.emoji = m.group(1)
            b.text = _unescape_quote(_cap(m, 2))
            cont = "quote"
        elif (m := _match(QUOTE, s)):
            b.type = "quote"
            b.text = _unescape_quote(_cap(m, 1))
            cont = "quote"
        else:
            b.text = _unescape_line(s)
            cont = "para"
        blocks.append(b)
        i += 1
    return blocks


def _is_list_like(t: str) -> bool:
    return t in ("bullet", "numbered", "todo", "toggle")


def serialize_blocks(blocks: list[Block]) -> str:
    out = ""
    prev = None
    numbers: list[int] = []
    for b in blocks:
        indent = max(0, min(b.indent, 8))
        del numbers[indent + 1:]
        while len(numbers) < indent + 1:
            numbers.append(0)
        if b.type == "numbered":
            numbers[indent] += 1
        else:
            numbers[indent] = 0
        if b.type == "paragraph" and b.text == "":
            continue
        ind = " " * (indent * 2)
        lines = b.text.split("\n")
        chunk: list[str] = []
        t = b.type

        def item(marker):
            first = _escape_item(lines[0])
            chunk.append(ind + marker + ("" if first == "" else " " + first))
            for extra in lines[1:]:
                chunk.append(ind + "  " + _escape_line(extra))

        if t in ("h1", "h2", "h3"):
            chunk.append(ind + "#" * int(t[1:]) + " " + b.text.replace("\n", " "))
        elif t == "bullet":
            item("-")
        elif t == "numbered":
            item("%d." % numbers[indent])
        elif t == "todo":
            item("- [x]" if b.checked else "- [ ]")
        elif t == "toggle":
            item("- ▶" if b.collapsed else "- ▼")
        elif t in ("quote", "callout"):
            for n, line in enumerate(lines):
                line = _escape_quote(line)
                prefix = ">"
                if n == 0 and t == "callout":
                    emoji = b.emoji or "💡"
                    emoji = emoji.replace("]", "").replace("\n", "")
                    if _is_ascii_word(emoji):
                        emoji = "💡"
                    prefix += " [!" + emoji + "]"
                chunk.append(ind + prefix + ("" if line == "" else " " + line))
        elif t == "code":
            fence = "```"
            while fence in b.text:
                fence += "`"
            chunk.append(ind + fence + b.language.replace("\n", "").replace("`", ""))
            if b.text != "":
                for line in lines:
                    chunk.append("" if line == "" else ind + line)
            chunk.append(ind + fence)
        elif t == "divider":
            chunk.append(ind + "---")
        elif t == "page":
            if not is_valid_id(b.ref):
                continue
            label = b.text.replace("\n", " ").replace("\\", "\\\\").replace("]", "\\]")
            chunk.append(ind + "[" + label + "](" + b.ref + ".md)")
        else:
            for line in lines:
                chunk.append(ind + _escape_line(line))
        if prev is not None:
            out += "\n" if (_is_list_like(prev.type) and _is_list_like(b.type)) else "\n\n"
        out += "\n".join(chunk)
        prev = b
    if out:
        out += "\n"
    return out


def canonical_body(markdown: str) -> str:
    """Model-written Markdown in the exact form Notes stores."""
    return serialize_blocks(parse_blocks(markdown or ""))


@dataclass
class PageMeta:
    id: str = ""
    parent: str = ""
    icon: str = ""
    title: str = ""
    favorite: bool = False
    order: int = 0
    created: dt.datetime | None = None
    updated: dt.datetime | None = None


@dataclass
class PageFile:
    meta: PageMeta = field(default_factory=PageMeta)
    body: str = ""
    has_frontmatter: bool = False


def _iso(value: dt.datetime | None) -> str:
    # QDateTime(LocalTime).toString(Qt::ISODate): no fraction, no offset
    return value.strftime("%Y-%m-%dT%H:%M:%S") if value else ""


def _parse_iso(value: str) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo is None else parsed.astimezone().replace(tzinfo=None)


def parse_page(text: str) -> PageFile:
    page = PageFile()
    rest = text.replace("\r\n", "\n")
    if rest.startswith("---\n"):
        end = rest.find("\n---", 3)
        while end >= 0 and end + 4 < len(rest) and rest[end + 4] != "\n":
            end = rest.find("\n---", end + 4)
        if end >= 0:
            meta = PageMeta()
            has_id = False
            for line in rest[4:end + 1].split("\n"):
                colon = line.find(":")
                if colon <= 0:
                    continue
                key, value = line[:colon].strip(), line[colon + 1:].strip()
                if key == "id":
                    meta.id, has_id = value, True
                elif key == "parent":
                    meta.parent = value
                elif key == "icon":
                    meta.icon = value
                elif key == "favorite":
                    meta.favorite = value == "true"
                elif key == "order":
                    try:
                        meta.order = int(value)
                    except ValueError:
                        meta.order = 0
                elif key == "created":
                    meta.created = _parse_iso(value)
                elif key == "updated":
                    meta.updated = _parse_iso(value)
            if has_id:
                page.meta = meta
                page.has_frontmatter = True
                rest = rest[end + 4:]
                if rest.startswith("\n"):
                    rest = rest[1:]
    rest = rest.lstrip("\n")
    if rest.startswith("# ") or rest == "#" or rest.startswith("#\n"):
        newline = rest.find("\n")
        first = rest if newline < 0 else rest[:newline]
        page.meta.title = first[2:]
        rest = "" if newline < 0 else rest[newline + 1:]
        rest = rest.lstrip("\n")
    page.body = rest
    return page


def serialize_page(meta: PageMeta, body: str) -> str:
    def clean(s):
        return s.replace("\n", " ").replace("\r", " ")
    out = "---\n"
    out += "id: " + clean(meta.id) + "\n"
    out += "parent: " + clean(meta.parent) + "\n"
    out += "icon: " + clean(meta.icon) + "\n"
    out += "favorite: " + ("true" if meta.favorite else "false") + "\n"
    out += "order: " + str(meta.order) + "\n"
    out += "created: " + _iso(meta.created) + "\n"
    out += "updated: " + _iso(meta.updated) + "\n"
    out += "---\n# " + clean(meta.title) + "\n"
    if body.strip():
        out += "\n" + body
        if not body.endswith("\n"):
            out += "\n"
    return out


def plain_text(body: str) -> str:
    return "\n".join(b.text for b in parse_blocks(body) if b.type not in ("divider", "page") and b.text)


# ------------------------------------------------------------------ store

def _write_atomic(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as out:
            out.write(text)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class NotesStore:
    def __init__(self, directory: Path | None = None):
        self.dir = directory or notes_dir()

    def _path(self, page_id: str) -> Path:
        if not is_valid_id(page_id):
            raise NotesError("Id de página inválido.")
        return self.dir / (page_id.lower() + ".md")

    def notes_running(self) -> bool:
        """Notes holds a QLockFile (pid, app name, host) while open."""
        lock = self.dir / "notes.lock"
        try:
            first = lock.read_text(encoding="utf-8", errors="replace").split("\n")
            pid = int(first[0])
        except (OSError, ValueError, IndexError):
            return False
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def pages(self) -> list[PageFile]:
        out = []
        if not self.dir.is_dir():
            return out
        for entry in self.dir.glob("*.md"):
            page_id = entry.stem
            if not is_valid_id(page_id) or entry.is_symlink():
                continue
            try:
                if entry.stat().st_size > MAX_PAGE:
                    continue
                text = entry.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            page = parse_page(text)
            page.meta.id = page_id
            if page.meta.parent and not is_valid_id(page.meta.parent):
                page.meta.parent = ""
            if page.meta.updated is None:
                page.meta.updated = dt.datetime.fromtimestamp(entry.stat().st_mtime)
            out.append(page)
        out.sort(key=lambda p: p.meta.updated or dt.datetime.min, reverse=True)
        return out

    def get(self, page_id: str) -> PageFile:
        path = self._path(page_id)
        if not path.is_file() or path.is_symlink():
            raise NotesError("Página não encontrada.")
        page = parse_page(path.read_text(encoding="utf-8", errors="replace"))
        page.meta.id = page_id.lower()
        return page

    def search(self, query: str, limit: int = 20) -> list[PageFile]:
        q = (query or "").strip().lower()
        pages = self.pages()
        if not q:
            return pages[:limit]
        hits = [p for p in pages if q in p.meta.title.lower() or q in plain_text(p.body).lower()]
        return hits[:limit]

    def _next_order(self, parent: str) -> int:
        order = 0
        for p in self.pages():
            if (p.meta.parent or "") == (parent or ""):
                order = max(order, p.meta.order + 1)
        return order

    def prepare_create(self, title: str, content: str, parent_id: str = "", icon: str = "") -> tuple[PageMeta, str]:
        title = (title or "").replace("\n", " ").replace("\r", " ").strip()[:200]
        if not title:
            raise NotesError("Dê um título à página.")
        parent = (parent_id or "").strip().lower()
        if parent:
            self.get(parent)  # must exist
        icon = (icon or "").replace("\n", "").replace("\r", "").strip()[:16]
        now = dt.datetime.now().replace(microsecond=0)
        meta = PageMeta(id=str(uuid.uuid4()), parent=parent, icon=icon, title=title,
                        order=self._next_order(parent), created=now, updated=now)
        body = canonical_body(content)
        if len(body) > MAX_PAGE // 2:
            raise NotesError("Texto longo demais para uma página.")
        return meta, body

    def create(self, meta: PageMeta, body: str) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self._path(meta.id)
        if path.exists():
            raise NotesError("Já existe uma página com este id.")
        _write_atomic(path, serialize_page(meta, body))
        return path

    def prepare_append(self, page_id: str, text: str) -> tuple[PageFile, str]:
        page = self.get(page_id)
        addition = canonical_body(text)
        if not addition.strip():
            raise NotesError("Nada para acrescentar.")
        return page, addition

    def append(self, page_id: str, addition: str) -> Path:
        if self.notes_running():
            raise NotesError("O app Notas está aberto. Feche o Notas para eu acrescentar texto a uma "
                             "página existente (ele salvaria por cima). Criar páginas novas funciona "
                             "com ele aberto.")
        page = self.get(page_id)
        body = page.body
        if body and not body.endswith("\n"):
            body += "\n"
        new_body = (body + "\n" + addition) if body.strip() else addition
        meta = replace(page.meta, updated=dt.datetime.now().replace(microsecond=0))
        path = self._path(page_id)
        _write_atomic(path, serialize_page(meta, new_body))
        return path
