"""Model display names, registry IDs, and backend kinds used by the app."""

from __future__ import annotations

# Each selectable model maps to its Hugging Face repo id and the backend that
# knows how to run it:
#   - "cohere_ov"     : Cohere Transcribe OpenVINO IR (manual KV-cache decode)
#   - "whisper_genai" : Whisper via OpenVINO GenAI WhisperPipeline
MODELS = {
    # Cloud: nothing to download, and Whisper large-v3 is more accurate than
    # anything that fits comfortably on a laptop. Needs a Groq API key.
    "Groq Whisper Large v3": {
        "id": "whisper-large-v3",
        "backend": "groq_whisper",
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

DEFAULT_MODEL_DISPLAY = "Groq Whisper Large v3"

#: Backends that call a hosted API instead of loading a local model. They need
#: no download, but they do need a key and a network.
CLOUD_BACKENDS = frozenset({"groq_whisper"})


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
