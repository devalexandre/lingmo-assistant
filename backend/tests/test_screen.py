"""ask_image: questions about an area of the screen (lingmo-screenshot)."""
import base64
from dataclasses import dataclass, field

import pytest

from fakemodel import FakeModel
from lingmo_assistant import engine as engine_mod, screen
from lingmo_assistant.agent import database
from test_engine import Capture

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
       b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82")


@dataclass
class SeeingModel(FakeModel):
    images: list = field(default_factory=list)
    system: list = field(default_factory=list)

    def invoke_stream(self, messages, assistant_message, **kwargs):
        for m in messages:
            if m.role == "user" and m.images:
                self.images.append([i.content for i in m.images])
            if m.role == "system":
                self.system.append(m.content)
        yield from super().invoke_stream(messages, assistant_message, **kwargs)


@pytest.fixture
def make_engine(home, conf, tmp_path):
    conf(think=True)
    db = database(str(tmp_path / "a.db"))

    def make(script, vision=True, tools=True):
        cap = Capture()
        models = []

        def factory(cfg):
            m = SeeingModel(id=cfg.model, script=list(script))
            m.think_setting = cfg.think
            models.append(m)
            return m
        eng = engine_mod.Engine(engine_mod.Output(cap), db=db, model_factory=factory,
                                tools_supported=lambda model: tools, vision_supported=lambda model: vision)
        return eng, cap, models
    return make


def ask(eng, **fields):
    request = {"type": "ask_image", "conversation_id": "tela1", "message": "Traduza para o português",
               "image": base64.b64encode(PNG).decode(), "ocr_text": "Hello world",
               "source": {"window": "Editor — notes.txt", "width": 300, "height": 80}}
    request.update(fields)
    eng.handle(request)


def test_vision_model_gets_the_picture(make_engine):
    eng, cap, models = make_engine([("text", "Olá mundo")])
    ask(eng)
    done = cap.wait_for("done")
    assert not done["stopped"]
    mode = cap.wait_for("image_mode")
    assert mode["mode"] == "vision" and mode["ocr_chars"] == len("Hello world")
    assert models[0].images == [[PNG]]
    assert models[0].think_setting is False          # always a direct answer
    system = models[0].system[0]
    assert "attached" in system and "Hello world" in system and "Editor — notes.txt" in system
    assert "UNTRUSTED CONTENT" in system
    assert "".join(e["text"] for e in cap.lines if e["type"] == "token").strip() == "Olá mundo"


def test_without_vision_uses_the_ocr_text(make_engine):
    eng, cap, models = make_engine([("text", "Olá mundo")], vision=False)
    ask(eng)
    cap.wait_for("done")
    assert cap.wait_for("image_mode")["mode"] == "ocr"
    assert models[0].images == []
    assert "only the text that OCR" in models[0].system[0]


def test_no_text_and_no_vision_is_an_error(make_engine):
    eng, cap, models = make_engine([], vision=False)
    ask(eng, ocr_text="")
    err = cap.wait_for("error")
    assert "não enxerga imagens" in err["message"] and "qwen2.5vl" in err["message"]
    assert models == []


def test_bad_requests(make_engine):
    eng, cap, _ = make_engine([])
    ask(eng, image="not base64!!")
    assert "não pôde ser lida" in cap.wait_for("error", 1)["message"]
    ask(eng, image=base64.b64encode(b"GIF89a....").decode())
    assert "PNG" in cap.wait_for("error", 2)["message"]
    ask(eng, image="", ocr_text="")
    assert "vazia" in cap.wait_for("error", 3)["message"]
    ask(eng, message="")
    assert cap.wait_for("error", 4)["message"] == "Mensagem vazia."


def test_history_marks_the_question_and_keeps_no_picture(make_engine, tmp_path):
    eng, cap, _ = make_engine([("text", "É um gráfico"), ("text", "Sobe 20%")])
    ask(eng, message="O que é isso?")
    cap.wait_for("done")
    # a follow-up in the Assistant (the app sends the picture again from memory)
    ask(eng, message="E a tendência?")
    cap.wait_for("done", 2)
    eng.handle({"type": "history", "conversation_id": "tela1"})
    hist = cap.wait_for("history")
    users = [m for m in hist["messages"] if m["role"] == "user"]
    assert [m["text"] for m in users] == ["O que é isso?", "E a tendência?"]
    assert all(m["screen"] == "vision" for m in users)
    assert hist["title"].startswith("Tela · O que é isso")
    # the picture was not written to the database
    data = (tmp_path / "a.db").read_bytes()
    assert PNG[8:30] not in data
    assert base64.b64encode(PNG).decode()[:40].encode() not in data


def test_config_reports_vision(make_engine):
    eng, cap, _ = make_engine([], vision=True)
    eng.handle({"type": "status"})
    assert cap.wait_for("config")["vision"] is True


def test_parse_limits():
    with pytest.raises(screen.ScreenError):
        screen.parse({"image": "A" * (screen.MAX_IMAGE * 2)})
    req = screen.parse({"ocr_text": "x" * (screen.MAX_OCR + 50), "source": {"width": "-3"}})
    assert len(req.ocr_text) == screen.MAX_OCR and req.width == 0 and req.image is None


def test_screen_question_never_reopens_the_overlay(make_engine, home):
    """The screenshot app's screen.ask intent is a tool in chat, but not while
    answering a screen question (it would open another overlay)."""
    import shutil
    from pathlib import Path
    from lingmo_assistant import intents
    manifest = Path(__file__).resolve().parents[3] / "lingmo-screenshots" / "data" / "intents" / "lingmo-screenshot.json"
    if not manifest.exists():
        pytest.skip("lingmo-screenshots is not next to lingmo-assistant")
    shutil.copy(manifest, home / "intents" / "lingmo-screenshot.json")
    intents.reset()
    if not intents.available():
        pytest.skip("lingmo_intents is not installed")
    eng, cap, _ = make_engine([])

    def names(**kw):
        cfg, agent, _ = eng._setup("tela1", None, **kw)
        return {getattr(f, "name", "") for f in agent.tools}
    assert "intent_screen_ask" in names()
    assert "intent_screen_ask" not in names(exclude_functions=screen.EXCLUDED_FUNCTIONS)


# ---- OCR that can't be trusted (Hebrew read with por+eng once made the model
# "translate" a story about Docker that wasn't on the screen)

GARBAGE = "bR P 3993 20:30-5 (3w D1) am N0 SD PONN"


def test_unreliable_ocr_is_never_given_to_the_model(make_engine):
    eng, cap, models = make_engine([("text", "Não consegui ler o texto com segurança.")])
    ask(eng, ocr_text=GARBAGE, ocr_status="unreliable", ocr_script="", intent="translate")
    cap.wait_for("done")
    assert cap.wait_for("image_mode")["ocr_chars"] == 0
    system = models[0].system[0]
    assert GARBAGE not in system and "OCR text of the selected area" not in system
    assert "NO RELIABLE TEXT" in system and "never invent content" in system
    assert "nunca invente conteúdo" in system


def test_missing_pack_says_which_script(make_engine):
    eng, cap, models = make_engine([("text", "…")])
    ask(eng, ocr_text="", ocr_status="missing", ocr_script="Hebrew", intent="explain",
        message="Explique esta área.", language="português (Brasil)")
    cap.wait_for("done")
    system = models[0].system[0]
    assert "Hebrew script" in system and "reading pack" in system
    assert "do not transliterate" in system


def test_translate_chip_asks_for_the_translation_only(make_engine):
    eng, cap, models = make_engine([("text", "…")])
    ask(eng, ocr_text="Завтра", ocr_status="ok", ocr_script="Cyrillic", intent="translate",
        language="português (Brasil)")
    cap.wait_for("done")
    assert "TRANSLATE: reply with only the translation into português (Brasil)" in models[0].system[0]


def test_missing_pack_without_vision_explains_the_install(make_engine):
    eng, cap, models = make_engine([], vision=False)
    ask(eng, ocr_text="", ocr_status="missing", ocr_script="Hebrew", message="O que diz aqui?")
    err = cap.wait_for("error")
    assert "Para ler hebraico, instale o pacote de leitura" in err["message"]
    assert models == []
    ask(eng, ocr_text=GARBAGE, ocr_status="unreliable")
    assert "com segurança" in cap.wait_for("error", 2)["message"]


def test_reliable_ocr_is_the_primary_source_for_text_chips(make_engine):
    eng, cap, models = make_engine([("text", "Amanhã às 20:30")])
    ask(eng, ocr_text="מחר ב-20:30", ocr_status="ok", ocr_script="Hebrew", ocr_confidence=91,
        intent="translate", language="português (Brasil)")
    cap.wait_for("done")
    system = models[0].system[0]
    # translating reliable text: the text goes in the message, no picture
    assert models[0].images == [] and "isn't needed" in system
    assert "NO RELIABLE TEXT" not in system and "in português (Brasil) unless" in system
    # explaining: the picture too, with the OCR text as the primary source
    eng2, cap2, models2 = make_engine([("text", "Explicação")])
    ask(eng2, ocr_text="מחר ב-20:30", ocr_status="ok", ocr_script="Hebrew", ocr_confidence=91,
        intent="explain", conversation_id="tela3")
    cap2.wait_for("done")
    system2 = models2[0].system[0]
    assert "primary source for the words" in system2 and "confidence 91%" in system2 and "מחר ב-20:30" in system2
    assert models2[0].images == [[PNG]]


def test_prompt_building():
    req = screen.parse({"ocr_text": GARBAGE, "ocr_status": "unreliable", "intent": "explain",
                        "image": base64.b64encode(PNG).decode()})
    assert req.ocr_text == "" and not req.ocr_reliable
    assert GARBAGE not in screen.context(req, vision=True)
    # an older client (no ocr_status): the text is taken, as a hint
    old = screen.parse({"ocr_text": "Hello"})
    assert old.ocr_reliable and "Hello" in screen.context(old, vision=False)
    # junk in the new fields is ignored
    odd = screen.parse({"ocr_text": "Hi", "ocr_status": "maybe", "intent": "rm -rf", "ocr_script": "He brew",
                        "ocr_confidence": "x", "language": 5})
    assert (odd.ocr_status, odd.intent, odd.ocr_script, odd.ocr_confidence, odd.language) == ("", "", "", -1, "")
    # without a language from the client: the system's
    assert screen.system_language() in screen.context(old, vision=False)


def test_unreadable_script_without_its_pack_is_not_guessed(make_engine):
    """A small vision model "translated" Hebrew it couldn't read: for translate
    and copy without the pack, the answer says so and the model isn't asked."""
    eng, cap, models = make_engine([("text", "invented")])
    ask(eng, ocr_text="", ocr_status="missing", ocr_script="Hebrew", intent="translate")
    text = cap.wait_for("error")["message"]
    assert "hebraico" in text and "Instalar" in text and "inventada" in text
    assert models == []
    # a typed "traduz isso" counts as translating
    ask(eng, ocr_text="", ocr_status="missing", ocr_script="Arabic", message="traduz isso pra mim")
    assert "árabe" in cap.wait_for("error", 2)["message"] and models == []
    # a free question still goes to the model, with the warning in the prompt
    eng2, cap2, models2 = make_engine([("text", "É uma mensagem em hebraico.")])
    ask(eng2, ocr_text="", ocr_status="missing", ocr_script="Hebrew", intent="", conversation_id="tela2",
        message="O que é isso?")
    cap2.wait_for("done")
    assert "cannot read Hebrew script" in models2[0].system[0]
    # Chinese: the vision model reads it, so it is asked
    assert screen.cannot_read_message(screen.parse({"ocr_status": "missing", "ocr_script": "Han",
                                                    "intent": "translate", "image": base64.b64encode(PNG).decode()})) == ""


def test_translate_reliable_text_goes_in_the_message_without_the_picture(make_engine):
    eng, cap, models = make_engine([("text", "Amanhã")])
    ask(eng, ocr_text="מחר", ocr_status="ok", ocr_script="Hebrew", intent="translate")
    cap.wait_for("done")
    assert cap.wait_for("image_mode")["mode"] == "ocr"
    assert models[0].images == []
    eng.handle({"type": "history", "conversation_id": "tela1"})
    users = [m for m in cap.wait_for("history")["messages"] if m["role"] == "user"]
    assert users[0]["text"] == "Traduza para o português"     # the question, not the screen text
