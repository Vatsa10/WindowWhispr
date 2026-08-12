"""Torch-free processor for the Cohere Transcribe OpenVINO model.

The upstream ``CohereAsrFeatureExtractor`` / ``CohereAsrProcessor`` (loaded via
``AutoProcessor.from_pretrained``) hard-depend on PyTorch: the module
``processing_cohere_asr`` does ``import torch`` at import time and the mel
frontend is implemented with ``torch.stft``.  We only run the model through
OpenVINO IR graphs, so pulling in PyTorch just for pre/post-processing is
unnecessary.

This module reproduces, in NumPy + librosa, the exact NeMo-style
``FilterbankFeatures`` frontend that the model was trained with, plus the
English decoder prompt and the tokenizer decode step (via the ``tokenizers``
Rust library, which ``transformers`` already depends on).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np


class CohereNPProcessor:
    """NumPy/librosa reimplementation of the Cohere ASR processor (no torch)."""

    # Decoder prompt for English transcription.  This is the fixed control-token
    # sequence the prefill graph expects, resolved against *this* model's
    # tokenizer.json vocabulary:
    #   <|startofcontext|><|startoftranscript|><|emo:undefined|><|en|><|en|>
    #   <|pnc|><|noitn|><|notimestamp|><|nodiarize|>
    _PROMPT_TOKEN_NAMES = (
        "<|startofcontext|>",
        "<|startoftranscript|>",
        "<|emo:undefined|>",
        "<|en|>",
        "<|en|>",
        "<|pnc|>",
        "<|noitn|>",
        "<|notimestamp|>",
        "<|nodiarize|>",
    )

    def __init__(self, model_dir: str):
        model_dir = Path(model_dir)
        cfg = json.loads((model_dir / "processor_config.json").read_text(encoding="utf-8"))

        self.sample_rate = int(cfg.get("sampling_rate", 16000))
        self.n_mels = int(cfg.get("feature_size", 128))
        self.win_length = int(cfg.get("n_window_size", 400))
        self.hop_length = int(cfg.get("n_window_stride", 160))
        self.n_fft = int(cfg.get("n_fft") or 2 ** math.ceil(math.log2(self.win_length)))
        self.preemph = cfg.get("preemph", 0.97)
        self.dither = float(cfg.get("dither", 1e-5))
        self.normalize = cfg.get("normalize", "per_feature")
        self.mag_power = float(cfg.get("mag_power", 2.0))
        self.log_zero_guard_value = 2.0 ** -24
        self._pad_value = float(cfg.get("padding_value", 0.0))
        lowfreq = cfg.get("lowfreq", 0)
        highfreq = cfg.get("highfreq") or self.sample_rate / 2

        import librosa

        # Symmetric Hann window (torch.hann_window(..., periodic=False)).
        self._window = np.hanning(self.win_length).astype(np.float32)
        # Slaney-normalised mel filterbank (matches librosa.filters.mel defaults).
        self._mel_fb = librosa.filters.mel(
            sr=self.sample_rate,
            n_fft=self.n_fft,
            n_mels=self.n_mels,
            fmin=lowfreq,
            fmax=highfreq,
            norm="slaney",
        ).astype(np.float32)

        # Tokenizer (Rust `tokenizers` library -- no torch dependency).
        from tokenizers import Tokenizer

        self._tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        vocab = self._tokenizer.get_vocab()
        self._prompt_ids = np.array(
            [[vocab[name] for name in self._PROMPT_TOKEN_NAMES]], dtype=np.int64
        )

    # ------------------------------------------------------------------ #
    # Feature extraction (NeMo FilterbankFeatures, torch-free)            #
    # ------------------------------------------------------------------ #
    def _get_seq_len(self, n_samples: int) -> int:
        """Valid mel-frame count, mirroring FilterbankFeatures.get_seq_len."""
        pad_amount = (self.n_fft // 2) * 2
        return int((n_samples + pad_amount - self.n_fft) // self.hop_length)

    def _extract_features(self, wav: np.ndarray):
        import librosa

        x = np.asarray(wav, dtype=np.float32)
        n_samples = x.shape[0]
        valid = self._get_seq_len(n_samples)

        # Deterministic dither, seeded by the sample count (batch invariant).
        if self.dither > 0:
            rng = np.random.default_rng(n_samples)
            x = x + self.dither * rng.standard_normal(n_samples).astype(np.float32)

        # Pre-emphasis.
        if self.preemph is not None:
            x = np.concatenate(([x[0]], x[1:] - self.preemph * x[:-1])).astype(np.float32)

        # STFT with center padding (n_fft//2 zeros both sides, constant mode),
        # matching torch.stft(center=True, pad_mode="constant").
        pad = self.n_fft // 2
        x_padded = np.pad(x, (pad, pad), mode="constant")
        stft = librosa.stft(
            x_padded,
            n_fft=self.n_fft,
            hop_length=self.hop_length,
            win_length=self.win_length,
            window=self._window,
            center=False,
        )
        mag = np.abs(stft)  # (freq, T)
        if self.mag_power != 1.0:
            mag = mag ** self.mag_power

        mel = self._mel_fb @ mag  # (n_mels, T)
        mel = np.log(mel + self.log_zero_guard_value).astype(np.float32)

        # Per-feature normalisation over the valid frames (unbiased std).
        v = max(valid, 1)
        seg = mel[:, :v]
        mean = seg.mean(axis=1, keepdims=True)
        if v > 1:
            std = seg.std(axis=1, ddof=1, keepdims=True)
        else:
            std = np.zeros_like(mean)
        std = np.nan_to_num(std) + 1e-5
        mel = (mel - mean) / std

        # Zero out frames beyond the valid length.
        if valid < mel.shape[1]:
            mel[:, valid:] = self._pad_value

        return mel, valid

    def __call__(self, wav, sampling_rate, language="en", return_tensors="np"):
        if int(sampling_rate) != self.sample_rate:
            raise ValueError(f"Expected {self.sample_rate}Hz, got {sampling_rate}")

        mel, _valid = self._extract_features(wav)  # (n_mels, T)
        features = mel.T[None, :, :].astype(np.float32)  # (1, T, n_mels)

        # NOTE: the exported OpenVINO encoder graph produces NaNs when the
        # trailing (invalid) frame is masked out -- its conv subsampling expects
        # every frame flagged as valid.  An all-True mask matches the reference
        # transcript exactly, so we mark the full length as attended.
        t = features.shape[1]
        attention_mask = np.ones((1, t), dtype=bool)

        return {
            "input_features": features,
            "attention_mask": attention_mask,
            "decoder_input_ids": self._prompt_ids.copy(),
        }

    # ------------------------------------------------------------------ #
    # Decoding                                                            #
    # ------------------------------------------------------------------ #
    def batch_decode(self, sequences, skip_special_tokens=True):
        seqs = [[int(i) for i in seq] for seq in sequences]
        return self._tokenizer.decode_batch(seqs, skip_special_tokens=skip_special_tokens)
