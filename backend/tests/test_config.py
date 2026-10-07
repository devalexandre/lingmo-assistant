from pathlib import Path

from conftest import write_conf
from lingmo_assistant import config


def test_missing_file_gives_contract_defaults(home):
    (home / "Pictures").mkdir()
    cfg = config.load()
    assert cfg.read is True and cfg.write is False and cfg.think is False
    assert cfg.tools == set(config.DEFAULT_TOOLS)
    assert "web" not in cfg.tools
    assert cfg.folders == [home / "Documents", home / "Downloads", home / "Pictures"]
    # write group starts off: write tools never run by default
    assert not cfg.tool_enabled("notes_write")
    assert cfg.tool_enabled("system_info")


def test_invalid_means_empty_list_not_defaults(home):
    write_conf(home, "[General]\nassistant_tools=@Invalid()\nassistant_folders=@Invalid()\n")
    cfg = config.load()
    assert cfg.tools == set()
    assert cfg.folders == []
    assert cfg.enabled_tools() == []


def test_lists_quotes_escapes_and_utf8(home):
    write_conf(home, '[General]\n'
                     'assistant_tools=system_info, web, notes_write, bogus\n'
                     'assistant_folders="/home/u/a, b", /home/u/Área de Trabalho, "/x/q\\"t\\\\z"\n'
                     'assistant_read=false\nassistant_write=true\nthink=true\nmodel=qwen3.5:4b\n')
    cfg = config.load()
    assert cfg.tools == {"system_info", "web", "notes_write"}
    assert cfg.folders == [Path("/home/u/a, b"), Path("/home/u/Área de Trabalho"), Path('/x/q"t\\z')]
    assert cfg.read is False and cfg.write is True and cfg.think is True
    assert cfg.model == "qwen3.5:4b"
    # read off: read tools refuse even when checked
    assert not cfg.tool_enabled("system_info")
    assert cfg.tool_enabled("notes_write")
    assert "leitura" in cfg.denial("system_info")


def test_single_item_list_and_legacy_group(home):
    write_conf(home, "[ai]\nmodel=llama3.1:8b\nprovider=ollama\n\n[General]\nassistant_tools=web\n")
    cfg = config.load()
    assert cfg.model == "llama3.1:8b"
    assert cfg.tools == {"web"}


def test_unescape_primitives():
    assert config._unescape_ini('"a, b"') == "a, b"
    assert config._unescape_ini("a, b") == ["a", "b"]
    assert config._unescape_ini("@Invalid()") == []
    assert config._unescape_ini('"\\x00e1"') == "á"
    assert config._unescape_ini("  plain  ") == "plain"
