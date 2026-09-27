from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

import httpx

from app.application.ports import LanguageModelError

LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
ERROR_BODY_PREVIEW = 300


def validated_base_url(url: str, require_tls_for_remote: bool) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise LanguageModelError(f"Invalid URL: {url!r}")
    if require_tls_for_remote and parsed.scheme != "https" and not is_loopback(parsed.hostname):
        raise LanguageModelError("For security, remote APIs must use https.")
    return url.strip().rstrip("/")


def is_loopback(hostname: str) -> bool:
    return hostname.lower() in LOOPBACK_HOSTS


def parse_json_object(text: str) -> dict[str, Any]:
    content = text.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        data = json.loads(content)
    except json.JSONDecodeError as error:
        raise LanguageModelError(f"Response is not valid JSON: {error}") from error
    if not isinstance(data, dict):
        raise LanguageModelError("The response is not a JSON object.")
    return data


def post_json(client: httpx.Client, url: str, payload: dict[str, Any], service: str) -> Any:
    try:
        response = client.post(url, json=payload)
    except httpx.HTTPError as error:
        raise LanguageModelError(f"{service}: {error}") from error
    if response.status_code >= 400:
        raise LanguageModelError(
            f"{service} {response.status_code}: {response.text[:ERROR_BODY_PREVIEW]}"
        )
    try:
        return response.json()
    except ValueError as error:
        raise LanguageModelError(f"{service}: unreadable response") from error
