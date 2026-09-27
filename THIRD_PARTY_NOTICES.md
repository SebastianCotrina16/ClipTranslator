# Third-Party Notices

ClipTranslator uses the following third-party models and software. Each one is distributed under its own license, listed below. Models are downloaded from their original sources the first time they are used and are not included in this repository.

## Models

| Model | Author | License | Source |
|---|---|---|---|
| Whisper large-v3, large-v2, medium (CTranslate2 conversion) | OpenAI, converted by SYSTRAN | MIT | https://huggingface.co/Systran |
| Whisper large-v3-turbo (CTranslate2 conversion) | OpenAI, converted by Mobius Labs | MIT | https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo |
| Qwen 3.5 (4B, 9B, 27B) | Alibaba Cloud, Qwen Team | Apache-2.0 | https://huggingface.co/Qwen |
| UVR-MDX-NET-Voc_FT | Ultimate Vocal Remover project | MIT | https://github.com/Anjok07/ultimatevocalremovergui |
| Silero VAD | Silero Team | MIT | https://github.com/snakers4/silero-vad |

## Included in the Windows installer

| Component | License | Source |
|---|---|---|
| uv | MIT or Apache-2.0 | https://github.com/astral-sh/uv |
| Microsoft Visual C++ Redistributable | Microsoft Software License Terms | https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist |

## Installed as dependencies

| Component | License | Source |
|---|---|---|
| faster-whisper | MIT | https://github.com/SYSTRAN/faster-whisper |
| CTranslate2 | MIT | https://github.com/OpenNMT/CTranslate2 |
| ONNX Runtime | MIT | https://github.com/microsoft/onnxruntime |
| Qt for Python (PySide6) | LGPL-3.0 | https://www.qt.io/qt-for-python |
| FFmpeg (through imageio-ffmpeg) | GPL-3.0 | https://ffmpeg.org |
| imageio-ffmpeg | BSD-2-Clause | https://github.com/imageio/imageio-ffmpeg |
| Hugging Face Hub | Apache-2.0 | https://github.com/huggingface/huggingface_hub |
| NumPy | BSD-3-Clause | https://numpy.org |
| soundfile | BSD-3-Clause | https://github.com/bastibe/python-soundfile |
| HTTPX | BSD-3-Clause | https://github.com/encode/httpx |
| platformdirs | MIT | https://github.com/tox-dev/platformdirs |
| tomli-w | MIT | https://github.com/hukkin/tomli-w |
| NVIDIA CUDA libraries (GPU version only) | NVIDIA Software License Agreement | https://developer.nvidia.com/cuda-toolkit |

Qt for Python and FFmpeg are used without modifications, as separate libraries and programs. Their source code is available from the links above.

## Optional external software

| Component | License | Source |
|---|---|---|
| Ollama | MIT | https://github.com/ollama/ollama |

## uv license notice

uv is bundled with the installer under the MIT License:

```
Copyright (c) 2025 Astral Software Inc.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
