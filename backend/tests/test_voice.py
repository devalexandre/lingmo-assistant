"""Voice: silence detection on recorded audio, the whisper model choice and
speech text cleaning. No microphone: a WAV plays the part of it."""
import math
import struct
import wave

import pytest

from lingmo_assistant import config, voice


def make_wav(path, parts, rate=16000):
    """parts: [(seconds, amplitude 0..1)] of a 220 Hz tone (0 = silence)."""
    frames = bytearray()
    for seconds, amp in parts:
        for i in range(int(seconds * rate)):
            frames += struct.pack("<h", int(amp * 20000 * math.sin(2 * math.pi * 220 * i / rate)))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return path


def record(monkeypatch, path):
    monkeypatch.setenv("LINGMO_ASSISTANT_VOICE_INPUT", str(path))
    levels = []
    pcm = voice.Recorder(lambda level, s: levels.append(level)).record()
    return pcm, levels


def test_speech_then_silence_is_kept(tmp_path, monkeypatch):
    pcm, levels = record(monkeypatch, make_wav(tmp_path / "a.wav", [(0.4, 0), (1.0, 0.6), (0.3, 0)]))
    assert pcm and max(levels) > 0.3
    # stops ~1.2 s after the speech, not at the end of the padded input
    assert len(pcm) / 32000 < 0.4 + 1.0 + 0.3 + 1.6


def test_speech_from_the_first_moment(tmp_path, monkeypatch):
    pcm, _ = record(monkeypatch, make_wav(tmp_path / "b.wav", [(1.2, 0.7)]))
    assert pcm


def test_silence_returns_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(voice, "NO_SPEECH_SECONDS", 1.5)
    pcm, _ = record(monkeypatch, make_wav(tmp_path / "c.wav", [(1.0, 0.0)]))
    assert pcm == b""


def test_model_choice_prefers_fast_and_respects_hardware(tmp_path, monkeypatch, home, conf):
    conf()
    d = tmp_path / "models"
    d.mkdir()
    monkeypatch.setenv("LINGMO_WHISPER_MODELS", str(d))
    with pytest.raises(voice.VoiceError):
        voice.choose_model(config.load())
    for name in ("large-v3-turbo", "small-q8_0", "tiny"):
        (d / ("ggml-%s.bin" % name)).write_bytes(b"x")
    cpu = voice.Hardware(ram=16, cores=8, threads=16, avx2=True)
    assert voice.recommend(cpu) == ("small-q8_0", False)
    assert voice.choose_model(config.load(), cpu) == ("small-q8_0", False)
    gpu = voice.Hardware(ram=32, cores=8, threads=16, avx2=True, gpu="nvidia", vram=8, backends=["cuda"])
    assert voice.choose_model(config.load(), gpu) == ("large-v3-turbo", True)
    weak = voice.Hardware(ram=2, cores=2, threads=2)
    assert voice.choose_model(config.load(), weak)[0] == "tiny"
    conf(assistant_stt_model="large-v3-turbo")
    assert voice.choose_model(config.load(), cpu)[0] == "large-v3-turbo"


def test_language_and_voice_pick(monkeypatch):
    monkeypatch.setenv("LANG", "pt_BR.UTF-8")
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    assert voice.language() == "pt"
    monkeypatch.setattr(voice, "voices", lambda: [
        {"id": "espeak:pt-br", "language": "pt_BR", "engine": "espeak"},
        {"id": "piper:en_US-amy-medium", "language": "en_US", "engine": "piper"},
        {"id": "piper:pt_BR-faber-medium", "language": "pt_BR", "engine": "piper"}])
    assert voice.pick_voice("")["id"] == "piper:pt_BR-faber-medium"
    assert voice.pick_voice("espeak:pt-br")["id"] == "espeak:pt-br"
