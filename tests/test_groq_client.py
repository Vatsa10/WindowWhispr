import io
import json
import urllib.error
import wave

import pytest

from core import diagnostics, groq_client
from core.groq_client import GroqError, build_multipart, transcribe, wav_bytes


def _http_error(status, payload=None):
    body = json.dumps(payload or {"error": {"message": "nope"}}).encode()
    return urllib.error.HTTPError("u", status, "err", {}, io.BytesIO(body))


def test_wav_bytes_is_16bit_mono_pcm():
    data = wav_bytes([0.0, 0.5, -0.5, 1.0], sample_rate=16000)
    with wave.open(io.BytesIO(data)) as handle:
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getframerate() == 16000
        assert handle.getnframes() == 4


def test_wav_bytes_clips_instead_of_wrapping():
    # A sample past 1.0 must saturate; wrapping turns a loud word into noise.
    data = wav_bytes([2.0, -2.0])
    with wave.open(io.BytesIO(data)) as handle:
        frames = handle.readframes(2)
    assert frames == b"\xff\x7f\x01\x80"


def test_multipart_carries_fields_and_file():
    body = build_multipart({"model": "whisper-large-v3"}, b"RIFFdata", "BOUND")
    assert b'name="model"' in body
    assert b"whisper-large-v3" in body
    assert b'name="file"; filename="audio.wav"' in body
    assert b"Content-Type: audio/wav" in body
    assert b"RIFFdata" in body
    assert body.startswith(b"--BOUND\r\n")
    assert body.endswith(b"--BOUND--\r\n")


def test_transcribe_without_a_key_is_a_typed_error():
    with pytest.raises(GroqError) as excinfo:
        transcribe([0.1, 0.2], api_key="")
    assert excinfo.value.kind == GroqError.NO_KEY


def test_transcribe_of_silence_makes_no_request(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("should not have called the API")

    monkeypatch.setattr(groq_client, "_post_multipart", boom)
    assert transcribe([], api_key="k") == ""


def test_long_audio_is_split_into_chunks(monkeypatch):
    calls = []

    def fake_post(_url, _key, _fields, wav):
        calls.append(len(wav))
        return {"text": f"part{len(calls)}"}

    monkeypatch.setattr(groq_client, "_post_multipart", fake_post)
    # Two and a bit chunks' worth of audio at the client's chunk length.
    samples = [0.1] * int(groq_client.MAX_CHUNK_SECONDS * 16000 * 2.5)
    assert transcribe(samples, api_key="k") == "part1 part2 part3"
    assert len(calls) == 3


@pytest.mark.parametrize(
    "status,kind",
    [
        (401, GroqError.AUTH),
        (403, GroqError.AUTH),
        (429, GroqError.RATE_LIMIT),
        (413, GroqError.TOO_LARGE),
        (500, GroqError.SERVER),
    ],
)
def test_http_status_maps_to_kind(status, kind):
    assert groq_client._http_error(_http_error(status)).kind == kind


def test_network_failure_maps_to_network(monkeypatch):
    def boom(_request, timeout=0):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(groq_client.urllib.request, "urlopen", boom)
    with pytest.raises(GroqError) as excinfo:
        groq_client._send(object())
    assert excinfo.value.kind == GroqError.NETWORK


def test_every_error_kind_has_user_facing_copy():
    for kind in (GroqError.NO_KEY, GroqError.AUTH, GroqError.RATE_LIMIT,
                 GroqError.TOO_LARGE, GroqError.SERVER, GroqError.NETWORK):
        diag = diagnostics.for_cloud_error(kind)
        assert diag.headline and diag.detail
        assert len(diag.headline) <= diagnostics.MAX_HEADLINE_CHARS


def test_unknown_error_kind_still_says_something():
    assert diagnostics.for_cloud_error("weird").headline
