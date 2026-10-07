import datetime as dt
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from lingmo_assistant import notes

SAMPLE = """# Reunião

Texto com **negrito** e uma linha
que continua.

- item um
- [ ] tarefa
- [x] feita
  1. sub numerado
> citação
> [!💡] não é callout dentro de citação

```python
print("oi")
```

---
\\- não é lista
"""


def test_roundtrip_is_stable():
    once = notes.canonical_body(SAMPLE)
    assert notes.canonical_body(once) == once
    types = [b.type for b in notes.parse_blocks(once)]
    assert types[:5] == ["h1", "paragraph", "bullet", "todo", "todo"]
    assert "code" in types and "divider" in types


def test_page_serialization_format():
    meta = notes.PageMeta(id="12345678-1234-4123-8123-123456789abc", title="Compras",
                          created=dt.datetime(2026, 10, 7, 9, 0, 0), updated=dt.datetime(2026, 10, 7, 9, 30, 5),
                          order=2, icon="🛒")
    text = notes.serialize_page(meta, "- leite\n")
    assert text == ("---\nid: 12345678-1234-4123-8123-123456789abc\nparent: \nicon: 🛒\nfavorite: false\n"
                    "order: 2\ncreated: 2026-10-07T09:00:00\nupdated: 2026-10-07T09:30:05\n---\n"
                    "# Compras\n\n- leite\n")
    page = notes.parse_page(text)
    assert page.has_frontmatter and page.meta.title == "Compras" and page.meta.order == 2
    assert page.body == "- leite\n"


def test_store_create_and_append(tmp_path):
    store = notes.NotesStore(tmp_path)
    meta, body = store.prepare_create("Ideias", "1. a\n2. b")
    path = store.create(meta, body)
    assert path.name == meta.id + ".md"
    meta2, body2 = store.prepare_create("Sub", "x", parent_id=meta.id)
    store.create(meta2, body2)
    assert meta2.parent == meta.id and meta2.order == 0
    meta3, _ = store.prepare_create("Outra", "")
    assert meta3.order == 1
    page, addition = store.prepare_append(meta.id, "- c")
    store.append(meta.id, addition)
    assert store.get(meta.id).body == "1. a\n2. b\n\n- c\n"
    assert [p.meta.title for p in store.search("ideias")] == ["Ideias"]
    with pytest.raises(notes.NotesError):
        store.prepare_create("x", "", parent_id="../../etc/passwd")
    with pytest.raises(notes.NotesError):
        store.get("../secret")


def test_append_refused_while_notes_runs(tmp_path):
    store = notes.NotesStore(tmp_path)
    meta, body = store.prepare_create("A", "x")
    store.create(meta, body)
    (tmp_path / "notes.lock").write_text("%d\nlingmo-notes\nhost\n" % os.getpid())
    assert store.notes_running()
    with pytest.raises(notes.NotesError, match="Feche o Notas"):
        store.append(meta.id, "y\n")
    (tmp_path / "notes.lock").write_text("999999999\nlingmo-notes\nhost\n")
    assert not store.notes_running()


# ------------------------------------------------------------------ against the real parser

NOTES_SRC = Path(os.environ.get("LINGMO_NOTES_SRC",
                                Path(__file__).resolve().parents[3] / "lingmo-texteditor" / "notes"))


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    if not (NOTES_SRC / "markdown.cpp").is_file() or not shutil.which("g++") or not shutil.which("pkg-config"):
        pytest.skip("Notes sources or a C++ toolchain not available")
    flags = subprocess.run(["pkg-config", "--cflags", "--libs", "Qt6Core"], capture_output=True, text=True)
    if flags.returncode != 0:
        pytest.skip("Qt6Core not available")
    exe = tmp_path_factory.mktemp("harness") / "harness"
    cmd = ["g++", "-std=c++20", "-fPIC", "-O0", "-I", str(NOTES_SRC),
           str(Path(__file__).parent / "notes_harness" / "harness.cpp"), str(NOTES_SRC / "markdown.cpp"),
           "-o", str(exe)] + flags.stdout.split()
    subprocess.run(cmd, check=True)
    return exe


def test_python_matches_notes_parser(harness, tmp_path):
    store = notes.NotesStore(tmp_path)
    meta, body = store.prepare_create("Página «teste»", SAMPLE, icon="📝")
    path = store.create(meta, body)
    out = subprocess.run([str(harness), "parse", str(path)], capture_output=True, text=True, check=True)
    parsed = json.loads(out.stdout)
    assert parsed["hasFrontmatter"] and parsed["id"] == meta.id
    assert parsed["title"] == "Página «teste»" and parsed["icon"] == "📝"
    assert parsed["created"] == meta.created.strftime("%Y-%m-%dT%H:%M:%S") and parsed["createdValid"]
    assert parsed["order"] == meta.order
    # Same blocks as the Python port, and Notes would write the body back unchanged
    py_blocks = [vars(b) for b in notes.parse_blocks(body)]
    assert parsed["blocks"] == py_blocks
    assert parsed["reserialized"] == body


def test_timestamp_format_matches_qt(harness):
    out = subprocess.run([str(harness), "now"], capture_output=True, text=True, check=True).stdout
    created = [l for l in out.splitlines() if l.startswith("created: ")][0][9:]
    assert notes._iso(dt.datetime.fromisoformat(created)) == created
