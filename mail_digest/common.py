"""Shared helpers used by every script: data directory, secrets, time, JSON files, Telegram push.

Keep this module small and free of feature logic, so any script can import it cheaply.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

from i18n import tr

HERE = Path(__file__).resolve().parent
# Data directory for config.toml, .env, and all JSON files.
# By default it is the source directory; Docker uses DATA_DIR=/data to separate data from code.
DATA = Path(os.environ.get("DATA_DIR") or HERE).resolve()
TZ = ZoneInfo("Europe/Berlin")


def now() -> dt.datetime:
    return dt.datetime.now(TZ)


# ---------------------------------------------------------------- Secrets

def load_env(path: Path) -> None:
    """Load KEY=VALUE entries from .env without overriding existing environment variables."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def secret(name: str) -> str:
    val = os.environ.get(name, "")
    if not val:
        raise RuntimeError(tr("env.missing", name=name))
    return val


# ---------------------------------------------------------------- JSON files

def load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save_json(path: Path, data) -> None:
    """Write via a temporary file so a crash never leaves a half-written file behind."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------- Text

def strip_tags(fragment: str) -> str:
    """Plain text of an HTML fragment on one line (for short page snippets, not whole emails)."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


# ---------------------------------------------------------------- Telegram

def send_telegram(text: str, cfg: dict, reply_markup: dict | None = None) -> None:
    """Push an HTML message to the owner's chat; cfg is the [telegram] section.
    reply_markup (buttons) is attached to the last part of a long message."""
    token = secret(cfg["bot_token_env"])
    chat_id = secret(cfg["chat_id_env"])
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    chunks, cur = [], ""
    for line in text.split("\n"):           # Telegram limits a single message to 4096 characters.
        if len(cur) + len(line) + 1 > 3800:
            chunks.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        chunks.append(cur)
    for i, chunk in enumerate(chunks):
        payload = {"chat_id": chat_id, "text": chunk, "parse_mode": "HTML",
                   "disable_web_page_preview": True}
        if reply_markup and i == len(chunks) - 1:
            payload["reply_markup"] = reply_markup
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            if not json.load(r).get("ok"):
                raise RuntimeError("Telegram 推送失败")
