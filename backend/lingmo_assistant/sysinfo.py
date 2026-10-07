"""Structured hardware/system summary for the system_info tool.

Read from /proc, /sys and /etc/os-release; GPU names come from lspci and
nvidia-smi, run inside the same sandbox as shell_read.
"""
from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path

from . import sandbox

REAL_FS = {"ext2", "ext3", "ext4", "btrfs", "xfs", "f2fs", "vfat", "exfat", "ntfs", "ntfs3",
           "fuseblk", "zfs", "bcachefs", "jfs", "reiserfs"}


def _read(path: str, limit: int = 1 << 20) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return ""


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(n) < 1024 or unit == "PB":
            return ("%.1f %s" % (n, unit)).replace(".0 ", " ")
        n /= 1024
    return str(n)


def cpu() -> dict:
    model = ""
    threads = 0
    cores: set[tuple[str, str]] = set()
    physical = ""
    for line in _read("/proc/cpuinfo").splitlines():
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if key == "model name" and not model:
            model = value
        elif key == "processor":
            threads += 1
        elif key == "physical id":
            physical = value
        elif key == "core id":
            cores.add((physical, value))
    info = {"model": model or platform.processor() or platform.machine(),
            "threads": threads or os.cpu_count() or 0}
    info["cores"] = len(cores) or info["threads"]
    max_khz = _read("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq").strip()
    if max_khz.isdigit():
        info["max_ghz"] = round(int(max_khz) / 1e6, 2)
    return info


def memory() -> dict:
    values = {}
    for line in _read("/proc/meminfo").splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            values[key] = int(parts[0]) * 1024
    total = values.get("MemTotal", 0)
    avail = values.get("MemAvailable", 0)
    return {"total": human(total), "used": human(total - avail), "available": human(avail),
            "swap_total": human(values.get("SwapTotal", 0)),
            "swap_used": human(values.get("SwapTotal", 0) - values.get("SwapFree", 0))}


def disks() -> list[dict]:
    out, seen = [], set()
    for line in _read("/proc/self/mounts").splitlines():
        parts = line.split()
        if len(parts) < 3 or parts[2] not in REAL_FS:
            continue
        device, mount = parts[0], parts[1].replace("\\040", " ")
        if device in seen and parts[2] == "btrfs":
            continue
        seen.add(device)
        try:
            st = os.statvfs(mount)
        except OSError:
            continue
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        if total <= 0:
            continue
        out.append({"mount": mount, "device": device, "fs": parts[2], "size": human(total),
                    "used": human(total - st.f_bfree * st.f_frsize), "free": human(free),
                    "use_percent": round(100 * (total - st.f_bfree * st.f_frsize) / total)})
    return out[:12]


def gpus() -> list[str]:
    names = []
    lspci = shutil.which("lspci", path="/usr/bin:/bin")
    if lspci:
        try:
            res = sandbox.run([lspci], timeout=8)
            for line in res.output.splitlines():
                if any(k in line for k in ("VGA compatible controller", "3D controller", "Display controller")):
                    names.append(line.split(": ", 1)[-1].strip())
        except sandbox.SandboxError:
            pass
    smi = shutil.which("nvidia-smi", path="/usr/bin:/bin")
    if smi:
        try:
            res = sandbox.run([smi, "--query-gpu=name,memory.total,driver_version",
                               "--format=csv,noheader"], timeout=8, devices=True)
            if res.returncode == 0:
                names += ["NVIDIA " + l.strip() if not l.startswith("NVIDIA") else l.strip()
                          for l in res.output.splitlines() if l.strip()]
        except sandbox.SandboxError:
            pass
    return names


def os_info() -> dict:
    rel = {}
    for line in _read("/etc/os-release").splitlines():
        k, _, v = line.partition("=")
        rel[k] = v.strip().strip('"')
    u = os.uname()
    return {"name": rel.get("PRETTY_NAME") or rel.get("NAME", "Linux"), "kernel": u.release,
            "arch": u.machine, "hostname": u.nodename,
            "desktop": os.environ.get("XDG_CURRENT_DESKTOP", ""),
            "session": os.environ.get("XDG_SESSION_TYPE", "")}


def uptime() -> str:
    try:
        seconds = int(float(_read("/proc/uptime").split()[0]))
    except (IndexError, ValueError):
        return ""
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    return ("%dd " % d if d else "") + "%dh %02dmin" % (h, m)


def _ipv4_by_interface() -> dict[str, list[str]]:
    """Local IPv4 addresses from /proc/net/fib_trie (no command, no network access)."""
    routes = {}
    for line in _read("/proc/net/route").splitlines()[1:]:
        parts = line.split()
        if len(parts) > 7:
            dest, mask = int(parts[1], 16), int(parts[7], 16)
            routes[(dest, mask)] = parts[0]
    out: dict[str, list[str]] = {}
    last_ip = None
    for line in _read("/proc/net/fib_trie").splitlines():
        s = line.strip()
        if s.startswith("|--"):
            last_ip = s[3:].strip()
        elif s == "/32 host LOCAL" and last_ip:
            octets = [int(x) for x in last_ip.split(".")]
            value = octets[0] | octets[1] << 8 | octets[2] << 16 | octets[3] << 24
            iface = next((name for (dest, mask), name in routes.items()
                          if mask and value & mask == dest), None)
            if last_ip.startswith("127."):
                iface = "lo"
            if iface and last_ip not in out.setdefault(iface, []):
                out[iface].append(last_ip)
    return out


def network() -> list[dict]:
    out = []
    base = Path("/sys/class/net")
    if not base.is_dir():
        return out
    v4 = _ipv4_by_interface()
    v6: dict[str, list[str]] = {}
    for line in _read("/proc/net/if_inet6").splitlines():
        parts = line.split()
        if len(parts) >= 6 and not parts[0].startswith("fe80"):
            addr = ":".join(parts[0][i:i + 4] for i in range(0, 32, 4))
            v6.setdefault(parts[5], []).append(addr)
    for dev in sorted(base.iterdir()):
        if dev.name == "lo":
            continue
        kind = "wifi" if (dev / "wireless").exists() else (
            "virtual" if "virtual" in os.path.realpath(dev) else "ethernet")
        out.append({"name": dev.name, "type": kind, "state": _read(str(dev / "operstate")).strip(),
                    "mac": _read(str(dev / "address")).strip(),
                    "ipv4": v4.get(dev.name, []), "ipv6": v6.get(dev.name, [])[:2]})
    return out[:16]


def batteries() -> list[dict]:
    out = []
    base = Path("/sys/class/power_supply")
    if not base.is_dir():
        return out
    for dev in sorted(base.iterdir()):
        if _read(str(dev / "type")).strip() != "Battery":
            continue
        cap = _read(str(dev / "capacity")).strip()
        out.append({"name": dev.name, "capacity_percent": int(cap) if cap.isdigit() else None,
                    "status": _read(str(dev / "status")).strip()})
    return out


def summary() -> str:
    c, m, o = cpu(), memory(), os_info()
    lines = [
        "Sistema: %s (kernel %s, %s)" % (o["name"], o["kernel"], o["arch"]),
        "Desktop: %s %s" % (o["desktop"] or "?", o["session"]),
        "Host: %s · ligado há %s" % (o["hostname"], uptime()),
        "CPU: %s · %s núcleos / %s threads%s" % (
            c["model"], c.get("cores", "?"), c["threads"],
            (" · até %.2f GHz" % c["max_ghz"]) if "max_ghz" in c else ""),
        "Memória: %s total · %s em uso · %s disponível · swap %s (%s em uso)" % (
            m["total"], m["used"], m["available"], m["swap_total"], m["swap_used"]),
    ]
    g = gpus()
    lines.append("GPU: " + ("; ".join(g) if g else "não identificada"))
    for d in disks():
        lines.append("Disco %s (%s, %s): %s · %s usados (%d%%) · %s livres" % (
            d["mount"], d["device"], d["fs"], d["size"], d["used"], d["use_percent"], d["free"]))
    for n in network():
        if n["type"] == "virtual" and n["state"] != "up":
            continue
        addrs = ", ".join(n["ipv4"] + n["ipv6"]) or "sem endereço"
        lines.append("Rede %s (%s, %s): %s" % (n["name"], n["type"], n["state"], addrs))
    for b in batteries():
        lines.append("Bateria %s: %s%% · %s" % (b["name"], b["capacity_percent"], b["status"]))
    return "\n".join(lines)
