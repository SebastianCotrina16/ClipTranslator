from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf

from app.infrastructure.gpu import detect_gpu, expose_cuda_libraries
from app.infrastructure.separation.stft import istft, stft

MODEL_BASE_URL = "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/"
HOP = 1024
DOWNLOAD_CHUNK = 1 << 20


class ModelDownloadError(RuntimeError):
    pass


@dataclass(frozen=True)
class MdxModel:
    name: str
    n_fft: int
    compensate: float
    sha256: str

    @property
    def url(self) -> str:
        return f"{MODEL_BASE_URL}{self.name}.onnx"


KNOWN_MODELS = {
    "UVR-MDX-NET-Voc_FT": MdxModel(
        name="UVR-MDX-NET-Voc_FT",
        n_fft=7680,
        compensate=1.021,
        sha256="534b2070fcc7df514b13ef660dc8cbb328679c2374d04354a5c42bb14ecce111",
    ),
}


def model_spec(name: str) -> MdxModel:
    try:
        return KNOWN_MODELS[name]
    except KeyError:
        raise ValueError(f"Unknown separation model: {name}") from None


def model_file(name: str, models_dir: Path) -> Path:
    return models_dir / "separation" / f"{model_spec(name).name}.onnx"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(DOWNLOAD_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def _stream_to_file(url: str, target: Path, progress: Callable[[float], None] | None) -> None:
    with httpx.stream("GET", url, follow_redirects=True, timeout=60) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length", 0))
        received = 0
        with target.open("wb") as stream:
            for chunk in response.iter_bytes(DOWNLOAD_CHUNK):
                stream.write(chunk)
                received += len(chunk)
                if progress and total:
                    progress(received / total)


def download_model(
    name: str, models_dir: Path, progress: Callable[[float], None] | None = None
) -> Path:
    spec = model_spec(name)
    target = model_file(name, models_dir)
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")
    try:
        _stream_to_file(spec.url, partial, progress)
    except httpx.HTTPError as error:
        partial.unlink(missing_ok=True)
        raise ModelDownloadError(f"Could not download the {name} model: {error}") from error
    if _sha256(partial) != spec.sha256:
        partial.unlink(missing_ok=True)
        raise ModelDownloadError(
            f"The downloaded {name} model does not match the expected SHA-256."
        )
    partial.replace(target)
    return target


class MdxSeparator:
    def __init__(
        self,
        name: str,
        models_dir: Path,
        device: str = "auto",
        batch_size: int = 4,
        threads: int = 0,
    ) -> None:
        import onnxruntime as ort

        self.spec = model_spec(name)
        self.batch_size = batch_size
        options = ort.SessionOptions()
        options.log_severity_level = 3
        if threads > 0:
            options.intra_op_num_threads = threads
        self.session = ort.InferenceSession(
            str(model_file(name, models_dir)), options, providers=self._providers(device)
        )
        input_shape = self.session.get_inputs()[0].shape
        self.dim_f = int(input_shape[2])
        self.dim_t = int(input_shape[3])

    @staticmethod
    def _providers(device: str) -> list:
        import onnxruntime as ort

        providers: list = ["CPUExecutionProvider"]
        if device == "cpu" or detect_gpu() is None:
            return providers
        expose_cuda_libraries()
        if "CUDAExecutionProvider" in ort.get_available_providers():
            providers.insert(0, ("CUDAExecutionProvider", {"cudnn_conv_algo_search": "HEURISTIC"}))
        return providers

    @property
    def device(self) -> str:
        return "cuda" if "CUDAExecutionProvider" in self.session.get_providers() else "cpu"

    def separate(
        self, mix: np.ndarray, progress: Callable[[float], None] | None = None
    ) -> np.ndarray:
        chunk_size = HOP * (self.dim_t - 1)
        trim = self.spec.n_fft // 2
        step = chunk_size - 2 * trim
        samples = mix.shape[1]
        pad = step - samples % step
        padded = np.concatenate(
            [np.zeros((2, trim)), mix, np.zeros((2, pad)), np.zeros((2, trim))], axis=1
        ).astype(np.float32)
        starts = list(range(0, samples + pad, step))
        pieces: list[np.ndarray] = []
        for first in range(0, len(starts), self.batch_size):
            chunks = np.stack(
                [padded[:, s : s + chunk_size] for s in starts[first : first + self.batch_size]]
            )
            spectrum = self._to_model_input(chunks)
            denoised = (self._infer(spectrum) - self._infer(-spectrum)) * 0.5
            pieces.extend(self._to_waveform(denoised)[:, :, trim:-trim])
            if progress:
                progress(min((first + self.batch_size) / len(starts), 1.0))
        vocals = np.concatenate(pieces, axis=1)[:, :samples]
        return (vocals * self.spec.compensate).astype(np.float32)

    def _to_model_input(self, chunks: np.ndarray) -> np.ndarray:
        spectrum = stft(chunks, self.spec.n_fft, HOP)[:, :, : self.dim_f, :]
        stacked = np.stack([spectrum.real, spectrum.imag], axis=2)
        return stacked.reshape(chunks.shape[0], 4, self.dim_f, self.dim_t).astype(np.float32)

    def _to_waveform(self, output: np.ndarray) -> np.ndarray:
        bins = self.spec.n_fft // 2 + 1
        output = output.reshape(output.shape[0], 2, 2, self.dim_f, self.dim_t)
        spectrum = output[:, :, 0] + 1j * output[:, :, 1]
        full = np.zeros((*spectrum.shape[:2], bins, self.dim_t), dtype=np.complex64)
        full[:, :, : self.dim_f] = spectrum
        return istft(full, self.spec.n_fft, HOP)

    def _infer(self, batch: np.ndarray) -> np.ndarray:
        input_name = self.session.get_inputs()[0].name
        return self.session.run(None, {input_name: batch})[0]


def separate_file(
    source: Path,
    output: Path,
    separator: MdxSeparator,
    progress: Callable[[float], None] | None = None,
) -> Path:
    mix, sample_rate = sf.read(source, dtype="float32", always_2d=True)
    channels = mix.T
    if channels.shape[0] == 1:
        channels = np.repeat(channels, 2, axis=0)
    vocals = separator.separate(channels[:2], progress)
    sf.write(output, vocals.T, sample_rate, subtype="PCM_16")
    return output
