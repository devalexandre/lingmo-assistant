"""Path policy: which files the assistant may read or write.

Every path is resolved (symlinks followed) before checking, must be inside one
of the folders from Settings › AI (assistant_folders), and must not touch the
always-blocked areas of docs/assistant-contract.md, even inside those folders.
"""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path

from . import config

# Relative to $HOME
BLOCKED_DIRS = [
    ".ssh", ".gnupg", ".password-store", ".local/share/keyrings",
    ".config/lingmo-online-accounts", ".pki", ".mozilla", ".thunderbird",
    ".config/google-chrome", ".config/chromium", ".config/BraveSoftware",
    ".aws", ".kube",
]
BLOCKED_FILES = [".netrc", ".docker/config.json"]
# File names blocked anywhere (keys, password databases, secrets)
BLOCKED_NAME_PATTERNS = ["*.kdbx", ".env", ".env.*", "id_*", "*.pem", "*.key"]

# Files the assistant may create or append to: plain text formats only
WRITABLE_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".yaml", ".yml",
    ".html", ".htm", ".xml", ".org", ".rst", ".tex", ".log",
}


class PolicyError(Exception):
    """Refusal whose (pt-BR) message is shown to the model and the user."""


def blocked_paths(home: Path | None = None) -> list[Path]:
    """Absolute blocked locations (dirs and files), as written and resolved."""
    home = home or config.home()
    out: list[Path] = []
    for rel in BLOCKED_DIRS + BLOCKED_FILES:
        p = home / rel
        for candidate in (p, Path(os.path.realpath(p))):
            if candidate not in out:
                out.append(candidate)
    return out


def name_blocked(name: str) -> bool:
    return any(fnmatch.fnmatchcase(name, pat) for pat in BLOCKED_NAME_PATTERNS)


def _inside(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def is_blocked(path: Path, home: Path | None = None) -> bool:
    """True when the (already resolved) path is or lies under a blocked area."""
    for blocked in blocked_paths(home):
        if _inside(path, blocked):
            return True
    return any(name_blocked(part) for part in path.parts[1:])


class PathPolicy:
    def __init__(self, folders: list[Path], home: Path | None = None):
        self.home = home or config.home()
        # Resolved roots; a root that is itself blocked is ignored
        self.roots: list[Path] = []
        for f in folders:
            r = Path(os.path.realpath(f))
            if r.is_dir() and not is_blocked(r, self.home) and r not in self.roots:
                self.roots.append(r)

    def describe_roots(self) -> str:
        return ", ".join(str(r) for r in self.roots) or "(nenhuma)"

    def _expand(self, raw: str) -> Path:
        if not isinstance(raw, str) or not raw.strip():
            raise PolicyError("Caminho vazio.")
        if "\0" in raw:
            raise PolicyError("Caminho inválido.")
        p = Path(os.path.expanduser(raw.strip()))
        if not p.is_absolute():
            # "Documentos/x.pdf": relative to the home folder
            p = self.home / p
        return p

    def _check(self, raw: str) -> Path:
        p = self._expand(raw)
        # The path as written must not name a blocked area either
        if is_blocked(Path(os.path.normpath(p)), self.home):
            raise PolicyError("Este local é protegido e o assistente nunca o acessa.")
        resolved = Path(os.path.realpath(p))
        if is_blocked(resolved, self.home):
            raise PolicyError("Este local é protegido e o assistente nunca o acessa.")
        if not any(_inside(resolved, root) for root in self.roots):
            raise PolicyError(
                "Fora das pastas permitidas. Pastas liberadas em Configurações › IA: "
                + self.describe_roots())
        return resolved

    def check_read(self, raw: str) -> Path:
        resolved = self._check(raw)
        if not resolved.exists():
            raise PolicyError("Arquivo ou pasta não encontrado: " + str(resolved))
        return resolved

    def check_write(self, raw: str) -> Path:
        """Target for creating/appending a file. The file may not exist yet."""
        resolved = self._check(raw)
        if resolved.is_dir():
            raise PolicyError("O caminho é uma pasta, não um arquivo.")
        if resolved.name.startswith("."):
            raise PolicyError("O assistente não cria arquivos ocultos.")
        if resolved.suffix.lower() not in WRITABLE_EXTENSIONS:
            raise PolicyError("O assistente só escreve arquivos de texto ("
                              + ", ".join(sorted(WRITABLE_EXTENSIONS)) + ").")
        return resolved

    def check_folder(self, raw: str) -> Path:
        """A folder inside the allowed ones where new files may be saved (attachments,
        screenshots). It may not exist yet; hidden folders are refused."""
        resolved = self._check(raw)
        if resolved.exists() and not resolved.is_dir():
            raise PolicyError("O caminho não é uma pasta.")
        home_rel = [part for part in resolved.parts if part.startswith(".")]
        if home_rel:
            raise PolicyError("O assistente não grava em pastas ocultas.")
        return resolved

    def check_inside(self, raw: str) -> Path:
        """Any path (file or folder) inside the allowed folders, outside the blocked areas."""
        return self._check(raw)

    def allowed_child(self, path: Path) -> bool:
        """For directory walks: skip blocked entries and symlinks leaving the roots."""
        if name_blocked(path.name):
            return False
        resolved = Path(os.path.realpath(path))
        if is_blocked(resolved, self.home):
            return False
        return any(_inside(resolved, root) for root in self.roots)
