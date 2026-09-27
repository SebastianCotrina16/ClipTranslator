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

- Windows 10 or 11 (64-bit) and an internet connection during setup.
- NVIDIA GPU recommended (driver 527.41 or newer). Works on CPU, but slower.
- [Ollama](https://ollama.com/download) for local translation, or an API key. The Settings window offers to install Ollama.

The installer adds everything else, including Python, the Microsoft Visual C++ runtime (only if missing) and the GPU libraries. Because it is not digitally signed, Windows may show a SmartScreen warning: click **More info** and then **Run anyway**.

## Installation

1. Download `ClipTranslator-Setup.exe` from the [latest release](https://github.com/SebastianCotrina16/ClipTranslator/releases/latest).
2. Run it. It needs no administrator rights and downloads the components that fit your computer (this can take several minutes).
3. When the app opens, the **Settings** window checks your hardware, recommends the best models and downloads them.

Open the app from the Start menu or the desktop shortcut. To change models or the translation engine later, click **Settings**. Uninstall it from Windows Settings like any other app.

### From the source code

Clone the repository and double-click `ClipTranslator.bat`. It installs everything and creates a desktop shortcut.

## Usage

1. Drop videos or a whole folder into the **Clips** list, or use **Add files** / **Add folder**.
2. Choose the source language (or leave it on automatic detection) and the target language.
3. Optionally add some context about the clip to improve the translation.
4. Click **Generate subtitles** for the selected clip, or **Process all** to subtitle and export every clip in the list.
5. Review the result: click a line to jump to that moment in the player. Double-click any text or time to edit it, move lines **Earlier** or **Later**, and undo with **Ctrl+Z**. Edits are saved automatically.
6. Click **Export subtitles**, or **Export video** to get a copy of the video with the subtitles burned in.

The app tells you when a new version is available.

### Command line (optional)

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

## Support

If ClipTranslator saves you time, you can support its development:

<a href="https://buymeacoffee.com/sebastiancotrina16"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me a Coffee" height="42"></a>

## License

ClipTranslator is released under the [MIT License](LICENSE). It uses third-party models and libraries under their own licenses, listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
