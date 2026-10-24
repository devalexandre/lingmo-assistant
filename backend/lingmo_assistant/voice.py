"""Voice, all local: record from the microphone (PipeWire/PulseAudio), speech to
text with whisper.cpp (`whisper-cli`), text to speech with piper (`piper-tts`)
or espeak-ng.

Recording reads 16 kHz mono PCM from `parecord`/`pw-record`/ffmpeg's pulse
input, reports the level ~12 times a second (for the listening animation) and
stops on silence after speech, on stop() or after MAX_SECONDS. The audio goes
to a private temporary file that is removed right after transcription.

The whisper model choice reuses Lingmo Studio's hardware-aware logic
(lingmo-studio/src/core/whisperhw.cpp: probe → recommended model → "too
heavy"), but prefers fast models: a voice command is a few seconds long.
"""
from __future__ import annotations

import array
import glob
import json
import locale
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unicodedata
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import config

log = logging.getLogger("lingmo_assistant.voice")

RATE = 16000
CHUNK_SECONDS = 0.08
MAX_SECONDS = 20
NO_SPEECH_SECONDS = 7
SILENCE_AFTER_SPEECH = 1.2
MIN_LEVEL = 0.045      # below this nothing counts as speech
SPEECH_LEVEL = 0.22    # at or above this it always does (speech from the first moment)


class VoiceError(Exception):
    pass


def language() -> str:
    """Whisper language from the system locale ("pt" for pt_BR)."""
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var)
        if value and value not in ("C", "POSIX", "C.UTF-8"):
            code = value.split(".")[0].split("_")[0].lower()
            if re.fullmatch(r"[a-z]{2,3}", code):
                return code
    return "auto"


def locale_name() -> str:
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var)
        if value and value not in ("C", "POSIX", "C.UTF-8"):
            return value.split(".")[0]
    return "pt_BR"


# ================================================================== whisper model choice

# name, memoryMb, speed (1-5), quality pt (1-4) — whisperhw.cpp's catalogue
CATALOGUE = [
    ("tiny", 273, 5, 1), ("base-q5_1", 300, 5, 1), ("base-q8_0", 320, 5, 1), ("base", 388, 5, 1),
    ("small-q5_1", 570, 4, 2), ("small-q8_0", 640, 4, 2), ("small", 852, 4, 2),
    ("medium-q5_0", 1100, 2, 3), ("medium-q8_0", 1400, 2, 3), ("medium", 2100, 2, 3),
    ("large-v3-turbo-q5_0", 1200, 3, 3), ("large-v3-turbo-q8_0", 1500, 3, 4), ("large-v3-turbo", 2200, 3, 4),
    ("large-v3-q5_0", 2100, 1, 4), ("large-v3", 3900, 1, 4),
]


@dataclass
class Hardware:
    ram: float = 0          # GiB
    cores: int = 0
    threads: int = 0
    avx2: bool = False
    avx512: bool = False
    gpu: str = ""           # nvidia, amd, intel
    vram: float = 0
    backends: list[str] = field(default_factory=list)


def probe() -> Hardware:
    """Same probe as whisperhw.cpp (LINGMO_WHISPER_HW overrides it)."""
    hw = Hardware()
    override = os.environ.get("LINGMO_WHISPER_HW")
    if override:
        kv = dict(p.split("=", 1) for p in override.split(",") if "=" in p)
        hw.ram = float(kv.get("ram", 0) or 0)
        hw.cores = int(kv.get("cores", 0) or 0)
        hw.threads = int(kv.get("threads", 0) or 0)
        hw.avx2 = kv.get("avx2") == "1"
        hw.avx512 = kv.get("avx512") == "1"
        hw.gpu = kv.get("gpu", "")
        hw.vram = float(kv.get("vram", 0) or 0)
        hw.backends = [b for b in kv.get("backends", "").split("+") if b]
        return hw
    try:
        info = Path("/proc/cpuinfo").read_text(errors="replace")
        hw.threads = info.count("\nprocessor") + (1 if info.startswith("processor") else 0)
        pairs = set(re.findall(r"physical id\s*:\s*(\d+)[\s\S]*?core id\s*:\s*(\d+)", info))
        hw.cores = len(pairs) or max(1, hw.threads // 2)
        flags = re.search(r"^flags\s*:(.*)$", info, re.M)
        fl = flags[1].split() if flags else []
        hw.avx2, hw.avx512 = "avx2" in fl, "avx512f" in fl
    except OSError:
        pass
    try:
        m = re.search(r"MemTotal:\s*(\d+)", Path("/proc/meminfo").read_text())
        hw.ram = int(m[1]) / 1024 / 1024 if m else 0
    except OSError:
        pass
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            out = subprocess.run([smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                                 capture_output=True, timeout=5, text=True).stdout
            best = 0.0
            for line in out.splitlines():
                parts = line.rsplit(",", 1)
                if len(parts) == 2 and parts[1].strip().isdigit():
                    best = max(best, int(parts[1]) / 1024)
            if best:
                hw.gpu, hw.vram = "nvidia", best
        except (OSError, subprocess.TimeoutExpired):
            pass
    if not hw.gpu:
        for card in sorted(glob.glob("/sys/class/drm/card*")):
            if "-" in os.path.basename(card):
                continue
            try:
                vendor = Path(card, "device/vendor").read_text().strip()
            except OSError:
                continue
            if vendor == "0x10de":
                hw.gpu = "nvidia"
            elif vendor == "0x1002":
                hw.gpu = "amd"
                try:
                    hw.vram = int(Path(card, "device/mem_info_vram_total").read_text()) / 1024 ** 3
                except (OSError, ValueError):
                    pass
            elif vendor == "0x8086" and not hw.gpu:
                hw.gpu = "intel"
            if hw.gpu in ("nvidia", "amd"):
                break
    found = set()
    for d in ("/usr/lib/ggml", "/usr/local/lib/ggml", "/usr/lib", "/usr/local/lib"):
        for p in glob.glob(os.path.join(d, "libggml-*.so*")):
            m = re.match(r"^libggml-([a-z]+)\.so(\.[0-9.]+)?$", os.path.basename(p))
            if m and m[1] in ("cuda", "hip", "vulkan", "sycl"):
                found.add(m[1])
    hw.backends = sorted(found)
    return hw


def _gpu_backend(hw: Hardware) -> str:
    order = {"nvidia": ["cuda", "vulkan"], "amd": ["hip", "vulkan"], "intel": ["sycl", "vulkan"]}.get(hw.gpu, [])
    return next((b for b in order if b in hw.backends), "")


def recommend(hw: Hardware) -> tuple[str, bool]:
    """(model, on GPU) — whisperhw.cpp's recommend()."""
    strong = bool(hw.gpu) and (hw.vram >= 1.5 if hw.vram > 0 else hw.gpu == "nvidia")
    if _gpu_backend(hw) and strong:
        vram = hw.vram if hw.vram > 0 else 4
        if vram >= 3.8 and (hw.ram <= 0 or hw.ram >= 7):
            return "large-v3-turbo", True
        return ("medium" if vram >= 2.8 else "medium-q5_0"), True
    cores = hw.cores if hw.cores > 0 else max(1, hw.threads // 2)
    ram = hw.ram if hw.ram > 0 else 4
    if ram < 3 or cores < 2:
        return "tiny", False
    if not hw.avx2 or cores < 4 or ram < 6:
        return "base-q8_0", False
    if ram >= 16 and (cores >= 16 or (cores >= 12 and hw.avx512)):
        return "medium-q8_0", False
    return "small-q8_0", False


def family_rank(name: str) -> int:
    base = re.sub(r"-q\d_\d$", "", name)
    return {"tiny": 0, "base": 1, "small": 2, "medium": 3, "large-v3-turbo": 4}.get(base, 5)


def models_dir() -> Path:
    override = os.environ.get("LINGMO_WHISPER_MODELS")
    if override:
        return Path(override)
    return config.data_home() / "lingmo" / "whisper-models"


def installed_models() -> list[str]:
    d = models_dir()
    out = []
    for p in sorted(d.glob("ggml-*.bin")) if d.is_dir() else []:
        out.append(p.name[len("ggml-"):-len(".bin")])
    return out


# Fast first: a voice command is short, latency matters more than nuance
VOICE_PREFERENCE_CPU = ["small-q8_0", "small-q5_1", "base-q8_0", "small", "base-q5_1", "base",
                        "large-v3-turbo-q5_0", "medium-q5_0", "large-v3-turbo-q8_0", "medium-q8_0", "tiny",
                        "large-v3-turbo", "medium", "large-v3-q5_0", "large-v3"]
VOICE_PREFERENCE_GPU = ["large-v3-turbo-q5_0", "large-v3-turbo-q8_0", "large-v3-turbo", "small-q8_0", "small",
                        "medium-q5_0", "medium-q8_0", "medium", "base-q8_0", "base", "small-q5_1", "tiny",
                        "large-v3-q5_0", "large-v3"]


def choose_model(cfg: config.Config, hw: Optional[Hardware] = None) -> tuple[str, bool]:
    """(model name, use GPU) for voice commands, among the downloaded ones."""
    installed = installed_models()
    if not installed:
        raise VoiceError("Nenhum modelo de transcrição baixado. Baixe um em Configurações › IA › Transcrição.")
    hw = hw or probe()
    rec, gpu = recommend(hw)
    if cfg.stt_model and cfg.stt_model in installed:
        return cfg.stt_model, gpu
    limit = family_rank(rec)
    prefs = VOICE_PREFERENCE_GPU if gpu else VOICE_PREFERENCE_CPU
    for name in prefs:
        if name in installed and family_rank(name) <= limit:
            return name, gpu
    # Everything downloaded is heavier than this computer's recommendation: the lightest one
    return min(installed, key=lambda n: (family_rank(n), n)), gpu


def whisper_binary() -> str | None:
    for name in ("whisper-cli", "whisper-cpp"):
        found = shutil.which(name) or (shutil.which(name, path=str(Path.home() / ".local/bin")))
        if found:
            return found
    return None


def transcribe(wav: Path, cfg: config.Config, lang: str | None = None) -> str:
    binary = whisper_binary()
    if not binary:
        raise VoiceError("O whisper.cpp (whisper-cli) não está instalado.")
    model, gpu = choose_model(cfg)
    threads = os.cpu_count() or 4
    threads = max(1, min(threads, 4 if gpu else 8))
    argv = [binary, "-m", str(models_dir() / ("ggml-%s.bin" % model)), "-f", str(wav), "-l", lang or language(),
            "-nt", "-np", "-t", str(threads), "-bs", "1", "-bo", "1", "-fa"]
    if not gpu:
        argv.append("-ng")
    try:
        proc = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=120, close_fds=True)
    except subprocess.TimeoutExpired as exc:
        raise VoiceError("A transcrição demorou demais.") from exc
    except OSError as exc:
        raise VoiceError("Não foi possível rodar o whisper-cli.") from exc
    if proc.returncode != 0:
        raise VoiceError("A transcrição falhou.")
    text = proc.stdout.decode("utf-8", "replace")
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", text)     # [Música], (risos), [BLANK_AUDIO]
    return " ".join(text.split()).strip()


# ================================================================== recording

def recorder_argv() -> list[str]:
    """Raw 16 kHz mono s16le on stdout."""
    if shutil.which("parecord"):
        return ["parecord", "--raw", "--format=s16le", "--rate=%d" % RATE, "--channels=1",
                "--latency-msec=50", "--client-name=Assistente"]
    if shutil.which("pw-record"):
        return ["pw-record", "--rate", str(RATE), "--channels", "1", "--format", "s16", "-"]
    if shutil.which("ffmpeg"):
        return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "pulse", "-i", "default",
                "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"]
    raise VoiceError("Nenhum gravador de áudio (parecord, pw-record ou ffmpeg) encontrado.")


def level_of(chunk: bytes) -> float:
    samples = array.array("h")
    samples.frombytes(chunk[: len(chunk) - len(chunk) % 2])
    if not samples:
        return 0.0
    rms = math.sqrt(sum(s * s for s in samples) / len(samples)) / 32768.0
    # perceptual-ish 0..1 for the animation
    return max(0.0, min(1.0, math.sqrt(rms) * 1.6))


def _file_source(path: str):
    """Tests and demos: a WAV file instead of the microphone (LINGMO_ASSISTANT_VOICE_INPUT)."""
    src = Path(path)
    tmp = None
    try:
        with wave.open(str(src)) as w:
            ok = w.getframerate() == RATE and w.getnchannels() == 1 and w.getsampwidth() == 2
    except (wave.Error, OSError):
        ok = False
    if not ok:
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-ac", "1",
                        "-ar", str(RATE), "-c:a", "pcm_s16le", tmp.name], check=True, timeout=60)
        src = Path(tmp.name)
    with wave.open(str(src)) as w:
        data = w.readframes(w.getnframes())
    if tmp:
        os.unlink(tmp.name)
    # a second of silence after the speech, like a person who stopped talking
    return data + b"\0" * int(RATE * 2 * 2.0)


class Recorder:
    """One listening session. on_level(level 0..1, seconds) is called from the reader thread."""

    def __init__(self, on_level: Callable[[float, float], None]):
        self.on_level = on_level
        self.stop_event = threading.Event()
        self.cancelled = False
        self.proc: Optional[subprocess.Popen] = None

    def stop(self) -> None:
        self.stop_event.set()

    def cancel(self) -> None:
        self.cancelled = True
        self.stop_event.set()

    def record(self) -> bytes:
        """Blocks until silence/stop/limit; returns PCM, or b"" when nothing was said."""
        chunk_bytes = int(RATE * CHUNK_SECONDS) * 2
        fake = os.environ.get("LINGMO_ASSISTANT_VOICE_INPUT")
        data = bytearray()
        speech = False
        silent_for = 0.0
        floor = None
        start = time.monotonic()
        source = None
        reader = None
        if fake:
            source = _file_source(fake)
        else:
            self.proc = subprocess.Popen(recorder_argv(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, close_fds=True)
            reader = self.proc.stdout
        pos = 0
        try:
            while not self.stop_event.is_set():
                if source is not None:
                    chunk = source[pos:pos + chunk_bytes]
                    pos += chunk_bytes
                    if not chunk:
                        break
                    # faster than real time, still animated (real time on request, for demos)
                    time.sleep(CHUNK_SECONDS if os.environ.get("LINGMO_ASSISTANT_VOICE_INPUT_REALTIME")
                               else CHUNK_SECONDS / 4)
                else:
                    chunk = reader.read(chunk_bytes)
                    if not chunk:
                        break
                data += chunk
                level = level_of(chunk)
                elapsed = len(data) / (RATE * 2)
                self.on_level(level, elapsed)
                # the quietest moment so far is the room's noise; speech is well above it
                floor = level if floor is None else min(floor, level)
                threshold = max(MIN_LEVEL, min(floor * 3, SPEECH_LEVEL))
                if level > threshold:
                    speech = True
                    silent_for = 0.0
                elif speech:
                    silent_for += CHUNK_SECONDS
                    if silent_for >= SILENCE_AFTER_SPEECH:
                        break
                if not speech and elapsed >= NO_SPEECH_SECONDS:
                    break
                if elapsed >= MAX_SECONDS or time.monotonic() - start > MAX_SECONDS + 5:
                    break
        finally:
            if self.proc is not None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
        if self.cancelled:
            return b""
        if not data and not fake:
            raise VoiceError("Não foi possível usar o microfone.")
        if not speech and not self.stop_event.is_set():
            return b""
        return bytes(data)


def write_wav(pcm: bytes, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=directory, prefix="voice-", suffix=".wav")
    os.close(fd)
    os.chmod(name, 0o600)
    with wave.open(name, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return Path(name)


# ================================================================== text to speech

PIPER_DIRS = ["/usr/share/piper-voices", "/usr/local/share/piper-voices"]


def piper_binary() -> str | None:
    return shutil.which("piper-tts") or shutil.which("piper")


def espeak_binary() -> str | None:
    return shutil.which("espeak-ng") or shutil.which("espeak")


def voices() -> list[dict]:
    """[{id, name, language, engine}] — piper voices first, then espeak-ng."""
    out = []
    if piper_binary():
        dirs = [str(config.data_home() / "piper-voices")] + PIPER_DIRS
        seen = set()
        for d in dirs:
            for model in sorted(glob.glob(os.path.join(d, "**", "*.onnx"), recursive=True)):
                stem = os.path.basename(model)[:-5]
                if stem in seen or not os.path.isfile(model + ".json"):
                    continue
                seen.add(stem)
                m = re.match(r"^([a-z]{2,3}_[A-Z]{2})-([^-]+)-(\w+)$", stem)
                lang, speaker, quality = (m[1], m[2], m[3]) if m else ("", stem, "")
                qual = {"x_low": "muito leve", "low": "leve", "medium": "média", "high": "alta"}.get(quality, quality)
                out.append({"id": "piper:" + stem, "name": "%s (%s, qualidade %s)" % (speaker.capitalize(), lang, qual),
                            "language": lang, "engine": "piper", "path": model})
    if espeak_binary():
        out.append({"id": "espeak:pt-br", "name": "eSpeak NG (pt-BR, robótica)", "language": "pt_BR",
                    "engine": "espeak", "path": ""})
        out.append({"id": "espeak:en-us", "name": "eSpeak NG (en-US, robótica)", "language": "en_US",
                    "engine": "espeak", "path": ""})
    return out


def pick_voice(voice_id: str = "") -> Optional[dict]:
    items = voices()
    if voice_id:
        for v in items:
            if v["id"] == voice_id:
                return v
    loc = locale_name()
    lang = loc.split("_")[0]
    ranked = sorted(items, key=lambda v: (v["language"] != loc, not v["language"].startswith(lang),
                                          v["engine"] != "piper", "medium" not in v["id"], v["id"]))
    return ranked[0] if ranked else None


def speech_text(markdown: str) -> str:
    """What to say for a Markdown answer: no code blocks, links or symbols."""
    text = re.sub(r"```.*?```", " (código) ", markdown, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", " link ", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.M)
    text = re.sub(r"[*_~>|#]", "", text)
    text = " ".join(text.split())
    return text[:4000]


def synthesize(text: str, cfg: config.Config, out_dir: Path) -> Path:
    """Writes a WAV with the chosen voice; returns its path."""
    voice = pick_voice(cfg.tts_voice)
    if voice is None:
        raise VoiceError("Nenhuma voz instalada (instale piper-tts e uma voz, ou espeak-ng).")
    text = speech_text(text)
    if not text:
        raise VoiceError("Nada para falar.")
    out_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=out_dir, prefix="speech-", suffix=".wav")
    os.close(fd)
    rate = cfg.tts_rate or 1.0
    try:
        if voice["engine"] == "piper":
            argv = [piper_binary(), "-m", voice["path"], "-c", voice["path"] + ".json", "-f", name, "-q",
                    "--length_scale", "%.2f" % (1.0 / rate)]
            proc = subprocess.run(argv, input=text.encode("utf-8"), stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, timeout=120, close_fds=True)
        else:
            argv = [espeak_binary(), "-v", voice["id"].split(":", 1)[1], "-s", str(int(165 * rate)), "-w", name,
                    "--stdin"]
            proc = subprocess.run(argv, input=text.encode("utf-8"), stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, timeout=120, close_fds=True)
    except (OSError, subprocess.TimeoutExpired) as exc:
        os.unlink(name)
        raise VoiceError("A síntese de voz falhou.") from exc
    if proc.returncode != 0 or os.path.getsize(name) < 100:
        os.unlink(name)
        raise VoiceError("A síntese de voz falhou.")
    return Path(name)


def player_argv(path: Path) -> list[str]:
    for argv in (["pw-play", str(path)], ["paplay", str(path)], ["aplay", "-q", str(path)],
                 ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)]):
        if shutil.which(argv[0]):
            return argv
    raise VoiceError("Nenhum programa para tocar áudio (pw-play, paplay ou aplay).")


class Speaker:
    """Speaks one text at a time; a new one interrupts the previous."""

    def __init__(self):
        self.lock = threading.Lock()
        self.proc: Optional[subprocess.Popen] = None

    def stop(self) -> None:
        with self.lock:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()

    def speak(self, text: str, cfg: config.Config, tmp_dir: Path) -> Path | None:
        """Blocks until done. With LINGMO_ASSISTANT_TTS_OUTPUT the WAV is kept there
        and nothing is played (tests)."""
        keep = os.environ.get("LINGMO_ASSISTANT_TTS_OUTPUT")
        wav = synthesize(text, cfg, Path(keep) if keep else tmp_dir)
        if keep:
            return wav
        try:
            self.stop()
            with self.lock:
                self.proc = subprocess.Popen(player_argv(wav), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL, close_fds=True)
                proc = self.proc
            proc.wait(timeout=600)
        finally:
            try:
                os.unlink(wav)
            except OSError:
                pass
        return None


# ================================================================== matching voice commands

STOPWORDS = {"o", "a", "os", "as", "um", "uma", "de", "do", "da", "dos", "das", "e", "em", "no", "na", "por",
             "para", "pra", "me", "meu", "minha", "por", "favor", "the", "to", "a", "please", "my", "of", "que"}


def normalize_words(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", str(text or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", text)


def keyword_score(utterance: str, phrase: str) -> float:
    """Share of the phrase's meaningful words found in what was said (0..1)."""
    said = set(normalize_words(utterance))
    words = [w for w in normalize_words(phrase) if w not in STOPWORDS] or normalize_words(phrase)
    if not words:
        return 0.0
    return sum(1 for w in words if w in said) / len(words)


def match_keywords(utterance: str, phrases: list[str], threshold: float = 0.75) -> float:
    return max([keyword_score(utterance, p) for p in phrases] or [0.0]) if phrases else 0.0


def wav_duration(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / float(w.getframerate())


def status() -> dict:
    """What the voice stack has on this computer (for Settings and the app)."""
    try:
        installed = installed_models()
    except OSError:
        installed = []
    return {"whisper": bool(whisper_binary()), "whisper_models": installed, "piper": bool(piper_binary()),
            "espeak": bool(espeak_binary()), "voices": [{k: v for k, v in x.items() if k != "path"} for x in voices()],
            "language": language()}


def dumps_status() -> str:
    return json.dumps(status(), ensure_ascii=False)
