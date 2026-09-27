# ClipTranslator

App for detecting and translating languages in video and audio clips. It transcribes the speech, translates it and exports ready-to-use subtitles (`.srt`).

## Features

- Automatic language detection.
- Accurate transcription with word-level timing (Whisper).
- Voice isolation to remove music and background noise.
- Context-aware translation with a local model (Ollama) or an API (Anthropic, OpenAI-compatible).
- Readable subtitles: line length, reading speed and timing are adjusted automatically.
- Runs on NVIDIA GPUs or CPU only.

## Requirements

- Windows 10 or 11.
- NVIDIA GPU recommended (driver 527.41 or newer). Works on CPU, but slower.
- [Ollama](https://ollama.com/download) for local translation, or an API key.

## Installation

1. Download or clone this repository.
2. Double-click `ClipTranslator.bat`.

The first run installs the dependencies and opens a setup wizard that checks your hardware and recommends the best models. Models are downloaded on first use.

To run the wizard again:

```bash
ClipTranslator.bat --setup
```

## Usage

Drag a video onto `ClipTranslator.bat`, or use the command line:

```bash
uv run python -m app.presentation.cli video.mp4 --to en
```

Useful options:

| Option | Description |
|---|---|
| `--to en` | Target language |
| `--language pt` | Source language (skips detection) |
| `-c "..."` | Context about the clip to improve the translation |
| `--vtt` | Also export `.vtt` |
| `--burn` | Create a video with burned-in subtitles |

Run `--help` to see every option.

## Output

Next to the video:

- `video.<target>.srt`: translated subtitles.
- `video.<source>.srt`: original subtitles.
- `video.bilingual.srt`: both languages.
- `video.transcript.txt`: easy-to-read transcript with timestamps.
