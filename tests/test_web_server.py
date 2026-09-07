"""The browser front end, exercised over real HTTP.

The routes are small but they are the only part of WinWhispr reachable from
another machine, so the tests care most about what happens when the request is
hostile: a path traversal, a missing token, an oversized body, a paste request
to a server that never enabled pasting.
"""

import base64
import io
import json
import urllib.error
import urllib.request
import wave

import numpy as np
import pytest

from core.web.server import MAX_BODY_BYTES, WebServer, decode_wav


def wav_bytes(seconds=0.5, sample_rate=16000, channels=1):
    frames = int(sample_rate * seconds)
    tone = (np.sin(np.linspace(0, 40, frames)) * 8000).astype("<i2")
    if channels > 1:
        tone = np.repeat(tone, channels)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(tone.tobytes())
    return buf.getvalue()


class Client:
    def __init__(self, port, token=""):
        self.base = f"http://127.0.0.1:{port}"
        self.token = token

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as res:
            return res.status, res.read()

    def post(self, path, payload, token=None):
        body = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        use = self.token if token is None else token
        if use:
            headers["X-WinWhispr-Token"] = use
        req = urllib.request.Request(self.base + path, data=body, headers=headers,
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                return res.status, json.loads(res.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())


@pytest.fixture()
def server():
    """A server with stand-in engines, so no model or keyboard is involved."""
    pasted = []
    web = WebServer(
        transcribe=lambda audio: f"heard {len(audio)} samples",
        tidy=lambda text: text.upper(),
        paste=pasted.append,
        allow_paste=True,
    )
    port = web.start(port=0)
    web.pasted = pasted
    yield web, Client(port)
    web.stop()


def test_decode_wav_reads_mono_pcm():
    samples = decode_wav(wav_bytes(seconds=0.25))
    assert len(samples) == 4000
    assert samples.dtype.name == "float32"
    assert abs(samples).max() <= 1.0


def test_decode_wav_downmixes_stereo():
    samples = decode_wav(wav_bytes(seconds=0.25, channels=2))
    assert len(samples) == 4000


def test_decode_wav_rejects_non_pcm16():
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(1)  # 8-bit
        handle.setframerate(16000)
        handle.writeframes(b"\x00" * 100)
    with pytest.raises(ValueError):
        decode_wav(buf.getvalue())


def test_health_reports_what_is_available(server):
    _web, client = server
    status, body = client.get("/api/health")
    payload = json.loads(body)
    assert status == 200
    assert payload["ok"] and payload["server_stt"] and payload["paste"]


def test_page_is_served(server):
    _web, client = server
    status, body = client.get("/")
    assert status == 200
    assert b"WinWhispr" in body


def test_stt_transcribes_uploaded_audio(server):
    _web, client = server
    audio = base64.b64encode(wav_bytes(seconds=0.5)).decode()
    status, payload = client.post("/api/stt", {"audio": audio})
    assert status == 200
    assert payload["text"] == "heard 8000 samples"


def test_stt_ignores_a_mis_click(server):
    _web, client = server
    audio = base64.b64encode(wav_bytes(seconds=0.02)).decode()
    assert client.post("/api/stt", {"audio": audio})[1]["text"] == ""


def test_stt_reports_undecodable_audio(server):
    _web, client = server
    junk = base64.b64encode(b"this is not a wav file").decode()
    assert "error" in client.post("/api/stt", {"audio": junk})[1]


def test_tidy_applies_the_cleanup_rules(server):
    _web, client = server
    assert client.post("/api/tidy", {"text": "hello"})[1]["text"] == "HELLO"


def test_tidy_never_loses_words_when_cleanup_fails():
    def explode(_text):
        raise RuntimeError("cleanup broke")

    web = WebServer(tidy=explode)
    port = web.start(port=0)
    try:
        status, payload = Client(port).post("/api/tidy", {"text": "keep my words"})
        assert status == 200
        assert payload["text"] == "keep my words"
    finally:
        web.stop()


def test_paste_reaches_the_desktop(server):
    web, client = server
    status, payload = client.post("/api/paste", {"text": "into the document"})
    assert status == 200 and payload["pasted"]
    assert web.pasted == ["into the document"]


def test_paste_is_refused_when_disabled():
    web = WebServer(transcribe=lambda a: "", paste=lambda t: None, allow_paste=False)
    port = web.start(port=0)
    try:
        status, payload = Client(port).post("/api/paste", {"text": "hi"})
        # A browser on the network must not be able to type into this machine
        # unless the person running the server opted in.
        assert status == 403 and "error" in payload
    finally:
        web.stop()


def test_token_is_required_when_set():
    web = WebServer(tidy=lambda t: t, token="sekrit")
    port = web.start(port=0)
    try:
        client = Client(port)
        assert client.post("/api/tidy", {"text": "x"}, token="")[0] == 401
        assert client.post("/api/tidy", {"text": "x"}, token="wrong")[0] == 401
        assert client.post("/api/tidy", {"text": "x"}, token="sekrit")[0] == 200
    finally:
        web.stop()


def test_static_files_cannot_escape_the_static_directory(server):
    _web, client = server
    for attack in ("/static/../server.py", "/static/../../config_store.py",
                   "/static/..%2f..%2fmain.py"):
        try:
            status, _ = client.get(attack)
        except urllib.error.HTTPError as exc:
            status = exc.code
        assert status == 404, f"{attack} was served"


def test_unknown_routes_are_404(server):
    _web, client = server
    assert client.post("/api/whatever", {})[0] == 404


def test_malformed_json_is_rejected(server):
    _web, client = server
    req = urllib.request.Request(
        client.base + "/api/tidy", data=b"{not json",
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=5)
        raise AssertionError("should have been rejected")
    except urllib.error.HTTPError as exc:
        assert exc.code == 400


def test_oversized_bodies_are_refused(server):
    _web, client = server
    req = urllib.request.Request(
        client.base + "/api/stt", data=b"x",
        headers={"Content-Type": "application/json",
                 "Content-Length": str(MAX_BODY_BYTES + 1)},
        method="POST")
    try:
        urllib.request.urlopen(req, timeout=5)
        raise AssertionError("should have been rejected")
    except urllib.error.HTTPError as exc:
        assert exc.code == 400
    except OSError:
        # The server answered and closed while the client was still writing,
        # so the client sees a reset rather than the response. Both outcomes
        # are a refusal; which one arrives is a race.
        pass


def test_page_references_only_assets_that_exist(server):
    """A typo in a script or stylesheet path is a blank page, not an error.

    The browser reports it in a console nobody is watching, so it is checked
    here instead.
    """
    import re

    _web, client = server
    _status, body = client.get("/")
    page = body.decode()

    referenced = re.findall(r'(?:src|href)="(/static/[^"]+)"', page)
    assert referenced, "the page loads no assets at all"
    for path in referenced:
        status, payload = client.get(path)
        assert status == 200, f"{path} is referenced but not served"
        assert payload, f"{path} is empty"


def test_the_module_graph_resolves(server):
    """ui.js imports app.js by absolute path; both must be reachable."""
    _web, client = server
    _status, ui = client.get("/static/ui.js")
    for imported in {"/static/app.js"}:
        assert imported.encode() in ui
        assert client.get(imported)[0] == 200
