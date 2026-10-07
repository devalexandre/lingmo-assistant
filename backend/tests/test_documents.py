import zipfile

import pytest

from lingmo_assistant import documents


def test_docx(tmp_path):
    p = tmp_path / "a.docx"
    xml = ('<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           '<w:body><w:p><w:r><w:t>Olá</w:t></w:r><w:r><w:t xml:space="preserve"> mundo</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>Linha 2</w:t></w:r></w:p></w:body></w:document>')
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", xml)
    assert documents.extract_text(p) == "Olá mundo\nLinha 2"


def test_odt(tmp_path):
    p = tmp_path / "a.odt"
    xml = ('<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
           'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body><office:text>'
           '<text:h>Título</text:h><text:p>Um<text:s text:c="2"/>dois <text:span>três</text:span></text:p>'
           '</office:text></office:body></office:document-content>')
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("content.xml", xml)
    assert documents.extract_text(p) == "Título\nUm  dois três"


def test_entities_refused(tmp_path):
    p = tmp_path / "bomb.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", '<!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>')
    with pytest.raises(documents.DocumentError):
        documents.extract_text(p)


def test_text_html_and_unsupported(tmp_path):
    (tmp_path / "a.md").write_text("# Oi\n")
    assert documents.extract_text(tmp_path / "a.md") == "# Oi\n"
    (tmp_path / "p.html").write_text("<html><head><script>x()</script></head><body><p>A</p><p>B &amp; C</p></body>")
    assert documents.extract_text(tmp_path / "p.html") == "A\n\nB & C"
    (tmp_path / "x.bin").write_bytes(b"\0\1")
    with pytest.raises(documents.DocumentError, match="não suportado"):
        documents.extract_text(tmp_path / "x.bin")
    (tmp_path / "bin.txt").write_bytes(b"\0\1\2")
    with pytest.raises(documents.DocumentError, match="binário"):
        documents.extract_text(tmp_path / "bin.txt")


@pytest.mark.skipif(not all(__import__("shutil").which(p) for p in ("ps2pdf", "pdftotext", "bwrap")),
                    reason="ghostscript, poppler or bwrap missing")
def test_pdf_in_sandbox(tmp_path):
    import subprocess
    ps = tmp_path / "t.ps"
    ps.write_text("%!PS\n/Helvetica findfont 14 scalefont setfont\n72 700 moveto (Vendas subiram 12) show\nshowpage\n")
    subprocess.run(["ps2pdf", str(ps), str(tmp_path / "t.pdf")], check=True)
    # tmp_path is under /tmp, which the sandbox hides: the file is exposed explicitly
    assert documents.extract_text(tmp_path / "t.pdf") == "Vendas subiram 12"
