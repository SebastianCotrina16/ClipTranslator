from __future__ import annotations

import json
import os
import platform
import re
import sys
import time
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.config.settings import Settings, redacted
from app.domain.models import Cue
from app.domain.subtitle_formats import timestamp
from app.infrastructure.github_releases import installed_version
from app.infrastructure.gpu import detect_gpu, free_vram_mb
from app.infrastructure.system_probe import cpu_name, ollama_models, total_ram_gb

RECENT_RUNS = 20
MIN_USER_NAME_LENGTH = 3


def report_name() -> str:
    return f"ClipTranslator report {time.strftime('%Y-%m-%d %H%M')}.zip"


def install_log() -> Path:
    return Path(sys.prefix).parent / "install.log"


def anonymized(text: str) -> str:
    home = Path.home()
    for form in {str(home), home.as_posix(), str(home).replace("\\", "\\\\")}:
        text = re.sub(re.escape(form), "~", text, flags=re.IGNORECASE)
    user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    if len(user) >= MIN_USER_NAME_LENGTH:
        text = re.sub(rf"\b{re.escape(user)}\b", "<user>", text, flags=re.IGNORECASE)
    return text


def recent_runs(work_root: Path, limit: int = RECENT_RUNS) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for log_file in work_root.glob("*/run.log"):
        try:
            lines = log_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                runs.append(entry)
    runs.sort(key=lambda entry: str(entry.get("time", "")))
    return runs[-limit:]


def seconds_text(value: Any) -> str:
    return f"{value:.0f}s" if isinstance(value, int | float) else "?"


def did_work(entry: dict[str, Any]) -> bool:
    return any(not stage.get("cached") for stage in entry.get("stages", []))


def describe_run(entry: dict[str, Any]) -> str:
    stages = ", ".join(
        f"{stage.get('stage')} {stage.get('seconds', 0):.1f}s"
        + (" (cached)" if stage.get("cached") else "")
        for stage in entry.get("stages", [])
    )
    duration = entry.get("duration")
    total = entry.get("total_seconds")
    name = Path(str(entry.get("media", ""))).name
    lines = [
        f"{entry.get('time')}  {name}  clip {seconds_text(duration)}, "
        f"work {seconds_text(total)}, language {entry.get('language')}",
        f"  {stages}",
    ]
    for stage in entry.get("stages", []):
        if stage.get("stage") == "transcribe" and stage.get("detail"):
            lines.append(f"  whisper: {stage['detail']}")
        if stage.get("stage") in ("review", "translate") and '"model"' in stage.get("detail", ""):
            model = json.loads(stage["detail"]).get("model", {})
            lines.append(f"  {stage['stage']} model: {json.dumps(model)}")
    for warning in entry.get("warnings", []):
        lines.append(f"  warning: {warning}")
    return "\n".join(lines)


def system_summary(settings: Settings) -> str:
    gpu = detect_gpu()
    models = ollama_models(settings.translation.ollama_url)
    lines = [
        f"ClipTranslator {installed_version()}",
        f"Windows: {platform.platform()}",
        f"Python: {platform.python_version()}",
        f"CPU: {cpu_name()}",
        f"RAM: {total_ram_gb():.0f} GB",
        f"GPU: {json.dumps(asdict(gpu)) if gpu else 'none detected'}",
        f"Free VRAM now: {free_vram_mb()} MB",
        f"Ollama models: {', '.join(models) if models is not None else 'Ollama not reachable'}",
    ]
    return "\n".join(lines)


def subtitles_text(cues: list[Cue]) -> str:
    return "\n".join(
        f"{timestamp(cue.start)} --> {timestamp(cue.end)} [{','.join(cue.flags)}]\n"
        f"  {cue.original}\n  {cue.translation}"
        for cue in cues
    )


def create_report(
    target: Path,
    settings: Settings,
    log_folder: Path | None,
    work_root: Path,
    cues: list[Cue] | None = None,
) -> Path:
    runs = recent_runs(work_root)
    summary = [system_summary(settings), "", "Recent clips:"]
    summary += [describe_run(entry) for entry in runs if did_work(entry)] or ["  none yet"]
    files: dict[str, str] = {
        "summary.txt": "\n".join(summary),
        "settings.json": json.dumps(redacted(settings), indent=2, ensure_ascii=False),
        "runs.jsonl": "\n".join(json.dumps(entry, ensure_ascii=False) for entry in runs),
    }
    logs = sorted(log_folder.glob("*.log*")) if log_folder and log_folder.is_dir() else []
    for log_file in [*logs, install_log()]:
        if log_file.is_file():
            files[f"logs/{log_file.name}"] = log_file.read_text(encoding="utf-8", errors="replace")
    if cues:
        files["subtitles.txt"] = subtitles_text(cues)
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, anonymized(content))
    return target
