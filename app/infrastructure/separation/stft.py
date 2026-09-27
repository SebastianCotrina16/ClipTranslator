from __future__ import annotations

import numpy as np


def hann_window(n_fft: int) -> np.ndarray:
    return (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(n_fft) / n_fft)).astype(np.float32)


def stft(signal: np.ndarray, n_fft: int, hop: int) -> np.ndarray:
    pad = n_fft // 2
    padded = np.pad(signal, [(0, 0)] * (signal.ndim - 1) + [(pad, pad)], mode="reflect")
    frames = np.lib.stride_tricks.sliding_window_view(padded, n_fft, axis=-1)[..., ::hop, :]
    spectrum = np.fft.rfft(frames * hann_window(n_fft), axis=-1)
    return np.swapaxes(spectrum, -1, -2)


def istft(spectrum: np.ndarray, n_fft: int, hop: int) -> np.ndarray:
    window = hann_window(n_fft)
    frames = np.fft.irfft(np.swapaxes(spectrum, -1, -2), n=n_fft, axis=-1) * window
    frame_count = frames.shape[-2]
    length = n_fft + hop * (frame_count - 1)
    signal = np.zeros((*frames.shape[:-2], length), dtype=np.float32)
    envelope = np.zeros(length, dtype=np.float32)
    for index in range(frame_count):
        signal[..., index * hop : index * hop + n_fft] += frames[..., index, :]
        envelope[index * hop : index * hop + n_fft] += window**2
    envelope = np.where(envelope > 1e-8, envelope, 1.0)
    pad = n_fft // 2
    return (signal / envelope)[..., pad : length - pad]
