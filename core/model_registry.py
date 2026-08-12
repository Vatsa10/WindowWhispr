"""Model display names, registry IDs, and backend kinds used by the app."""

from __future__ import annotations

# Each selectable model maps to its Hugging Face repo id and the backend that
# knows how to run it:
#   - "cohere_ov"     : Cohere Transcribe OpenVINO IR (manual KV-cache decode)
#   - "whisper_genai" : Whisper via OpenVINO GenAI WhisperPipeline
MODELS = {
    # Cloud: nothing to download, and Whisper large-v3 is more accurate than
    # anything that fits comfortably on a laptop. Needs a Groq API key.
    # Measured on an 8s clip: turbo 466ms, large-v3 526ms, the local model
    # 1192ms on the iGPU and 3626ms on CPU. Turbo is the default because the
    # wait here is the wait between letting go of the key and seeing text.
    "Groq Whisper Turbo": {
        "id": "whisper-large-v3-turbo",
        "backend": "groq_whisper",
    },
    "Groq Whisper Large v3": {
        "id": "whisper-large-v3",
        "backend": "groq_whisper",
    },
    # Local, and faster than the cloud round trip. Measured on an 8s clip:
    # base.en 385ms, small.en 1125ms, tiny.en 233ms — all on CPU, no GPU
    # needed, a few hundred MB instead of gigabytes.
    "Whisper Base (local, fast)": {
        "id": "base.en",
        "backend": "faster_whisper",
    },
    "Whisper Small (local, accurate)": {
        "id": "small.en",
        "backend": "faster_whisper",
    },
    "Whisper Tiny (local, fastest)": {
        "id": "tiny.en",
        "backend": "faster_whisper",
    },
    "Cohere-transcribe": {
        # Owner prefix is required: a bare name resolves to no repo and Hugging
        # Face answers 401, which reads like an auth problem rather than a typo.
        "id": "Aditya02/cohere-transcribe-03-2026-ov-fp16",
        "backend": "cohere_ov",
    },
    "Whisper Large": {
        "id": "OpenVINO/whisper-large-v3-int4-ov",
        "backend": "whisper_genai",
    },
}

DEFAULT_MODEL_DISPLAY = "Groq Whisper Turbo"

#: Backends that call a hosted API instead of loading a local model. They need
#: no download, but they do need a key and a network.
CLOUD_BACKENDS = frozenset({"groq_whisper"})

#: Backends that fetch and manage their own weights, so the OpenVINO model
#: downloader has nothing to do for them.
SELF_MANAGED_BACKENDS = frozenset({"faster_whisper"})


def _entry(display_name: str) -> dict:
    return MODELS.get(display_name, MODELS[DEFAULT_MODEL_DISPLAY])


def resolve_model_id(display_name: str) -> str:
    """Map a GUI display name to the actual model registry ID."""
    return _entry(display_name)["id"]


def resolve_backend(display_name: str) -> str:
    """Return the backend kind ("cohere_ov", "whisper_genai", "groq_whisper")."""
    return _entry(display_name)["backend"]


def is_cloud_model(display_name: str) -> bool:
    """True when the model runs on a hosted API rather than on this machine."""
    return resolve_backend(display_name) in CLOUD_BACKENDS


def needs_openvino_download(display_name: str) -> bool:
    """True when first run must fetch OpenVINO IR weights for this model."""
    backend = resolve_backend(display_name)
    return backend not in CLOUD_BACKENDS and backend not in SELF_MANAGED_BACKENDS


def list_model_names() -> list[str]:
    """Return all selectable model names for the GUI."""
    return list(MODELS.keys())


# ---------------------------------------------------------------------------
# LLM models (OpenVINO GenAI) used by the clipboard reformatter feature.
# ---------------------------------------------------------------------------
LLM_MODELS = {
    "LFM2.5 350M": {
        "id": "OpenVINO/LFM2.5-350M-int8-ov",
    },
    "Qwen2.5-1.5B Instruct": {
        "id": "OpenVINO/Qwen2.5-1.5B-Instruct-int4-ov",
    },
    "TinyLlama 1.1B Chat": {
        "id": "OpenVINO/TinyLlama-1.1B-Chat-v1.0-int4-ov",
    },
    "Phi-3 Mini Instruct": {
        "id": "OpenVINO/Phi-3-mini-4k-instruct-int4-ov",
    },
}

DEFAULT_LLM_DISPLAY = "LFM2.5 350M"


def _llm_entry(display_name: str) -> dict:
    return LLM_MODELS.get(display_name, LLM_MODELS[DEFAULT_LLM_DISPLAY])


def resolve_llm_model_id(display_name: str) -> str:
    """Map an LLM display name to its Hugging Face repo id."""
    return _llm_entry(display_name)["id"]


def list_llm_model_names() -> list[str]:
    """Return all selectable LLM model names for the GUI."""
    return list(LLM_MODELS.keys())
