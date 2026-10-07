"""Text extraction for the read_files / search_files tools.

Plain text and Markdown are decoded directly; PDF goes through pdftotext
(poppler) inside the bubblewrap sandbox, since PDFs are untrusted input; DOCX
and ODT are zip files whose XML is parsed with the standard library, with size
limits against zip bombs.
"""
from __future__ import annotations

import html
import re
import shutil
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

from . import sandbox

MAX_FILE = 50 * 1024 * 1024          # bytes of the file on disk
MAX_XML = 30 * 1024 * 1024           # uncompressed document XML
MAX_TEXT = 400_000                   # characters kept after extraction

TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".yaml", ".yml", ".xml", ".log",
    ".ini", ".conf", ".cfg", ".toml", ".org", ".rst", ".tex", ".py", ".js", ".ts", ".c", ".h",
    ".cpp", ".hpp", ".qml", ".sh", ".rs", ".go", ".java", ".kt", ".sql", ".srt", ".vtt", ".ics",
    ".vcf", ".rtf",
}
HTML_EXTENSIONS = {".html", ".htm", ".xhtml"}
SUPPORTED = TEXT_EXTENSIONS | HTML_EXTENSIONS | {".pdf", ".docx", ".odt"}


class DocumentError(Exception):
    pass


def kind(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext in TEXT_EXTENSIONS:
        return "text"
    if ext in HTML_EXTENSIONS:
        return "html"
    if ext in (".pdf", ".docx", ".odt"):
        return ext[1:]
    return None


def _read_limited(path: Path) -> bytes:
    size = path.stat().st_size
    if size > MAX_FILE:
        raise DocumentError("Arquivo grande demais (%d MB)." % (size // (1024 * 1024)))
    with open(path, "rb") as f:
        return f.read(MAX_FILE)


def _decode(data: bytes) -> str:
    if b"\0" in data[:8192]:
        raise DocumentError("Arquivo binário: não é texto.")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


class _HtmlText(HTMLParser):
    SKIP = {"script", "style", "noscript", "template", "svg", "head"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section",
             "article", "header", "footer", "pre", "blockquote", "table", "ul", "ol"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(markup: str) -> str:
    parser = _HtmlText()
    try:
        parser.feed(markup)
        parser.close()
    except Exception:  # malformed markup: keep what was parsed
        pass
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return html.unescape(text).strip()


def _zip_xml(path: Path, member: str) -> ElementTree.Element:
    try:
        with zipfile.ZipFile(path) as z:
            info = z.getinfo(member)
            if info.file_size > MAX_XML:
                raise DocumentError("Documento grande demais.")
            data = z.read(member)
    except KeyError as exc:
        raise DocumentError("Documento sem conteúdo de texto.") from exc
    except zipfile.BadZipFile as exc:
        raise DocumentError("Documento corrompido.") from exc
    if b"<!DOCTYPE" in data[:4096] or b"<!ENTITY" in data:
        raise DocumentError("Documento com estrutura não suportada.")
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise DocumentError("Documento corrompido.") from exc


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_text(path: Path) -> str:
    root = _zip_xml(path, "word/document.xml")
    paragraphs = []
    for p in root.iter(W + "p"):
        chunks = []
        for node in p.iter():
            if node.tag == W + "t" and node.text:
                chunks.append(node.text)
            elif node.tag == W + "tab":
                chunks.append("\t")
            elif node.tag in (W + "br", W + "cr"):
                chunks.append("\n")
        paragraphs.append("".join(chunks))
    return "\n".join(paragraphs).strip()


TEXT_NS = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"


def odt_text(path: Path) -> str:
    root = _zip_xml(path, "content.xml")
    lines = []

    def walk(node) -> str:
        out = [node.text or ""]
        for child in node:
            if child.tag == TEXT_NS + "s":
                out.append(" " * int(child.get(TEXT_NS + "c", "1") or 1))
            elif child.tag == TEXT_NS + "tab":
                out.append("\t")
            elif child.tag == TEXT_NS + "line-break":
                out.append("\n")
            elif child.tag not in (TEXT_NS + "p", TEXT_NS + "h"):
                out.append(walk(child))
            out.append(child.tail or "")
        return "".join(out)

    for node in root.iter():
        if node.tag in (TEXT_NS + "p", TEXT_NS + "h"):
            lines.append(walk(node))
    return "\n".join(lines).strip()


def pdf_text(path: Path) -> str:
    program = shutil.which("pdftotext", path="/usr/bin:/bin")
    if not program:
        raise DocumentError("Para ler PDF instale o pacote poppler (pdftotext).")
    try:
        result = sandbox.run([program, "-enc", "UTF-8", "-l", "300", "-nopgbrk", str(path), "-"],
                             timeout=30, limit=MAX_TEXT * 4)
    except sandbox.SandboxError as exc:
        raise DocumentError(str(exc)) from exc
    if result.timed_out:
        raise DocumentError("O PDF demorou demais para ser lido.")
    if result.returncode != 0:
        raise DocumentError("Não foi possível ler este PDF (protegido ou corrompido).")
    text = result.output.strip()
    if not text:
        raise DocumentError("O PDF não tem texto (talvez seja só imagem digitalizada).")
    return text


def extract_text(path: Path) -> str:
    """Full text of a supported document, capped at MAX_TEXT characters."""
    k = kind(path)
    if k is None:
        raise DocumentError("Tipo de arquivo não suportado: " + (path.suffix or "sem extensão")
                            + ". Leio texto, Markdown, PDF, DOCX e ODT.")
    if path.stat().st_size > MAX_FILE:
        raise DocumentError("Arquivo grande demais.")
    if k == "text":
        text = _decode(_read_limited(path))
    elif k == "html":
        text = html_to_text(_decode(_read_limited(path)))
    elif k == "pdf":
        text = pdf_text(path)
    elif k == "docx":
        text = docx_text(path)
    else:
        text = odt_text(path)
    return text[:MAX_TEXT]
