#!/usr/bin/env python3
"""NEWAPI chat helper. curl + browser UA. Never prints secrets."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

USER_AGENT = "Mozilla/5.0 (compatible; algorithm-evolve-tryout/1.0)"
DEFAULT_TIMEOUT = 180


def base_url() -> str:
    raw = (os.environ.get("NEWAPI_BASE_URL") or "").rstrip("/")
    if not raw:
        raise RuntimeError("NEWAPI_BASE_URL missing")
    return raw


def api_key() -> str:
    key = os.environ.get("NEWAPI_API_KEY") or ""
    if not key:
        raise RuntimeError("NEWAPI_API_KEY missing")
    return key


def host_only() -> str:
    from urllib.parse import urlparse

    return urlparse(base_url()).hostname or "unknown"


def chat(
    model: str,
    messages: list[dict],
    *,
    temperature: float = 0.3,
    max_tokens: int = 8000,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    """POST /chat/completions via curl. Returns parsed JSON plus meta."""
    url = f"{base_url()}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(payload, handle)
        body_path = handle.name
    out_path = body_path + ".out"
    cmd = [
        "curl",
        "-sS",
        "-o",
        out_path,
        "-w",
        "%{http_code} %{time_total}",
        "-H",
        f"Authorization: Bearer {api_key()}",
        "-H",
        "Content-Type: application/json",
        "-H",
        f"User-Agent: {USER_AGENT}",
        "-H",
        "Accept: application/json",
        "-X",
        "POST",
        url,
        "--max-time",
        str(timeout),
        "--data-binary",
        f"@{body_path}",
    ]
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout + 15)
    finally:
        Path(body_path).unlink(missing_ok=True)
    trailer = (proc.stdout or "").strip().split()
    http_code = int(trailer[0]) if trailer else 0
    elapsed = float(trailer[1]) if len(trailer) > 1 else 0.0
    raw = Path(out_path).read_text(encoding="utf-8", errors="replace") if Path(out_path).exists() else ""
    Path(out_path).unlink(missing_ok=True)
    parsed = None
    try:
        parsed = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        parsed = None
    content = ""
    usage = {}
    response_model = model
    if isinstance(parsed, dict):
        choices = parsed.get("choices") or []
        if choices:
            msg = choices[0].get("message") or {}
            content = msg.get("content") or ""
        usage = parsed.get("usage") or {}
        response_model = parsed.get("model") or model
    return {
        "ok": proc.returncode == 0 and 200 <= http_code < 300 and bool(content.strip()),
        "http_code": http_code,
        "elapsed_sec": elapsed,
        "curl_rc": proc.returncode,
        "curl_stderr": (proc.stderr or "")[-300:],
        "requested_model": model,
        "response_model": response_model,
        "content": content,
        "usage": usage,
        "raw_len": len(raw),
        "content_len": len(content),
    }


def list_models(timeout: int = 30) -> dict:
    url = f"{base_url()}/models"
    out_path = tempfile.mktemp(suffix=".models.json")
    cmd = [
        "curl",
        "-sS",
        "-o",
        out_path,
        "-w",
        "%{http_code}",
        "-H",
        f"Authorization: Bearer {api_key()}",
        "-H",
        f"User-Agent: {USER_AGENT}",
        "-H",
        "Accept: application/json",
        url,
        "--max-time",
        str(timeout),
    ]
    proc = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout + 10)
    http_code = int((proc.stdout or "0").strip() or 0)
    raw = Path(out_path).read_text(encoding="utf-8", errors="replace") if Path(out_path).exists() else ""
    Path(out_path).unlink(missing_ok=True)
    ids = []
    try:
        data = json.loads(raw)
        ids = [item.get("id") for item in (data.get("data") or []) if item.get("id")]
    except json.JSONDecodeError:
        data = None
    return {"http_code": http_code, "ids": ids, "ok": http_code == 200}
