import os

import pytest

from lingmo_assistant import paths


@pytest.fixture
def policy(home):
    return paths.PathPolicy([home / "Documents"])


def test_inside_allowed_folder(home, policy):
    f = home / "Documents" / "a.txt"
    f.write_text("x")
    assert policy.check_read(str(f)) == f
    assert policy.check_read("Documents/a.txt") == f          # relative to home
    assert policy.check_read("~/Documents/a.txt") == f


def test_outside_folders_refused(home, policy):
    (home / "Downloads" / "b.txt").write_text("x")
    with pytest.raises(paths.PolicyError, match="Fora das pastas"):
        policy.check_read(str(home / "Downloads" / "b.txt"))
    with pytest.raises(paths.PolicyError):
        policy.check_read("/etc/passwd")
    with pytest.raises(paths.PolicyError):
        policy.check_read(str(home / "Documents" / ".." / "Downloads" / "b.txt"))


def test_symlink_escape_refused(home, policy):
    os.symlink(home / ".ssh" / "id_ed25519", home / "Documents" / "innocent.txt")
    os.symlink("/etc", home / "Documents" / "etc")
    with pytest.raises(paths.PolicyError, match="protegido"):
        policy.check_read(str(home / "Documents" / "innocent.txt"))
    with pytest.raises(paths.PolicyError):
        policy.check_read(str(home / "Documents" / "etc" / "hostname"))


def test_blocked_even_inside_folder(home):
    pol = paths.PathPolicy([home])     # the whole home allowed
    for rel in (".ssh/id_ed25519", ".netrc", ".ssh"):
        with pytest.raises(paths.PolicyError, match="protegido"):
            pol.check_read(str(home / rel))
    for name in ("cofre.kdbx", ".env", "server.pem", "x.key", "id_rsa"):
        (home / "Documents" / name).write_text("s")
        with pytest.raises(paths.PolicyError):
            pol.check_read(str(home / "Documents" / name))
    assert not pol.allowed_child(home / ".mozilla")


def test_blocked_root_is_dropped(home):
    pol = paths.PathPolicy([home / ".ssh", home / "Documents"])
    assert pol.roots == [home / "Documents"]


def test_check_write_rules(home, policy):
    target = policy.check_write(str(home / "Documents" / "new" / "nota.md"))
    assert target == home / "Documents" / "new" / "nota.md"
    with pytest.raises(paths.PolicyError, match="texto"):
        policy.check_write(str(home / "Documents" / "run.sh"))
    with pytest.raises(paths.PolicyError, match="ocultos"):
        policy.check_write(str(home / "Documents" / ".bashrc.txt"))
    with pytest.raises(paths.PolicyError):
        policy.check_write(str(home / "Downloads" / "x.txt"))
