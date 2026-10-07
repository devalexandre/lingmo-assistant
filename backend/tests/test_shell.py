import pytest

from lingmo_assistant import paths, sandbox, shell


def which(name):
    return "/usr/bin/" + name


@pytest.fixture
def policy(home):
    return paths.PathPolicy([home / "Documents"])


@pytest.mark.parametrize("line", [
    "lscpu; rm -rf ~", "ls $(whoami)", "free -h | head", "df -h > /tmp/x", "uname `id`",
    "lsblk && reboot", "echo hi", "rm -rf /", "bash -c ls", "cat /etc/passwd", "sudo lsblk",
    "pacman -Syu", "pacman -S firefox", "pacman -Rns x", "systemctl restart sshd",
    "systemctl stop bluetooth", "journalctl --vacuum-size=1M", "ls -R ~/Documents",
    "nvidia-smi -r", "ps aux --sort=-%cpu\nreboot", "pacman -Qi -Syu", "du -sh /etc",
    "ls ~/.ssh", "lsblk -o NAME;id", "ip addr", "find / -name x", "lsusb -D /dev/x",
    "systemctl status --root=/x", "journalctl -n 99999",
])
def test_rejected(line, policy):
    with pytest.raises(shell.CommandError):
        shell.parse(line, policy, which=which)


@pytest.mark.parametrize("line,argv", [
    ("lscpu", ["/usr/bin/lscpu"]),
    ("free -h", ["/usr/bin/free", "-h"]),
    ("lsblk -o NAME,SIZE,TYPE,MOUNTPOINTS", ["/usr/bin/lsblk", "-o", "NAME,SIZE,TYPE,MOUNTPOINTS"]),
    ("pacman -Qi firefox", ["/usr/bin/pacman", "-Qi", "firefox"]),
    ("pacman -Ss editor", ["/usr/bin/pacman", "-Ss", "editor"]),
    ("systemctl status bluetooth", ["/usr/bin/systemctl", "--no-pager", "status", "bluetooth"]),
    ("systemctl --user list-units --type=service",
     ["/usr/bin/systemctl", "--no-pager", "--user", "list-units", "--type=service"]),
    ("journalctl --user -n 50", ["/usr/bin/journalctl", "--no-pager", "--user", "-n", "50"]),
    ("journalctl -b -p err", ["/usr/bin/journalctl", "--no-pager", "-b", "-p", "err", "-n", "100"]),
    ("nvidia-smi --query-gpu=name,memory.total --format=csv,noheader",
     ["/usr/bin/nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"]),
    ("ps aux --sort=-%cpu", ["/usr/bin/ps", "aux", "--sort=-%cpu"]),
    ("/usr/bin/uname -a", ["/usr/bin/uname", "-a"]),
])
def test_accepted(line, argv, policy):
    assert shell.parse(line, policy, which=which) == argv


def test_path_arguments_resolved_and_checked(home, policy):
    (home / "Documents" / "Área de Trabalho").mkdir()
    argv = shell.parse('du -sh "~/Documents/Área de Trabalho"', policy, which=which)
    assert argv == ["/usr/bin/du", "-sh", str(home / "Documents" / "Área de Trabalho")]
    argv = shell.parse("ls -la ~/Documents", policy, which=which)
    assert argv[-1] == str(home / "Documents")


def test_missing_program(policy):
    with pytest.raises(shell.CommandError, match="não está instalado"):
        shell.parse("sensors", policy, which=lambda n: None)


def test_bwrap_argv(home):
    (home / ".gnupg").mkdir()
    argv = sandbox.build_argv(["/usr/bin/lscpu"], home=home, bwrap="/usr/bin/bwrap")
    assert argv[0] == "/usr/bin/bwrap"
    assert argv[argv.index("--ro-bind") + 1:argv.index("--ro-bind") + 3] == ["/", "/"]
    for flag in ("--unshare-net", "--die-with-parent", "--new-session", "--clearenv"):
        assert flag in argv
    assert argv[-2:] == ["--", "/usr/bin/lscpu"]
    pairs = list(zip(argv, argv[1:]))
    assert ("--tmpfs", str(home / ".ssh")) in pairs
    assert ("--tmpfs", str(home / ".gnupg")) in pairs
    assert ("--dev", "/dev") in pairs
    i = argv.index(str(home / ".netrc"))
    assert argv[i - 2:i] == ["--ro-bind", "/dev/null"]
    # blocked paths that don't exist are not mounted
    assert str(home / ".aws") not in argv
    assert "sh" not in argv and "-c" not in argv
    gpu = sandbox.build_argv(["/usr/bin/nvidia-smi"], home=home, bwrap="/usr/bin/bwrap", devices=True)
    assert ("--dev-bind", "/dev") in list(zip(gpu, gpu[1:]))


def test_without_bwrap_refuses(home, monkeypatch):
    monkeypatch.setenv("LINGMO_ASSISTANT_BWRAP", str(home / "nope"))
    with pytest.raises(sandbox.SandboxError, match="bubblewrap"):
        sandbox.build_argv(["/usr/bin/lscpu"], home=home)


@pytest.mark.skipif(sandbox.bwrap_path() is None, reason="bwrap not installed")
def test_sandbox_hides_blocked_and_has_no_network(home, policy):
    res = sandbox.run(["/usr/bin/ls", "-A", str(home / ".ssh")])
    assert "id_ed25519" not in res.output
    res = sandbox.run(["/usr/bin/cat", str(home / ".netrc")])
    assert "password" not in res.output
    res = sandbox.run(["/usr/bin/cat", "/proc/net/dev"])
    lines = [l for l in res.output.splitlines() if ":" in l]
    assert [l.split(":")[0].strip() for l in lines] == ["lo"]
