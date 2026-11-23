"""Shared state and helpers for the bot's tools: the tool registry, data paths, and the live config.

The paths, CFG and PENDING live only here. bot.py and the tests replace the paths
(tools.base.CONFIG_PATH = ...), so tool modules must read them as base.NAME at call time
and never copy them with `from .base import CONFIG_PATH`.
"""
from __future__ import annotations

import datetime as dt
import re

import i18n
from common import DATA

TODO_FILE = DATA / "todos.json"
TIMETABLE_FILE = DATA / "timetable.json"
CONFIG_PATH = DATA / "config.toml"
BACKUP_DIR = DATA / "backup"

CFG: dict = {}              # Populated at bot.py startup and reloaded after settings changes.
PENDING: dict = {}          # Settings changes awaiting user confirmation; only program code can apply them.
TOOLS: dict[str, dict] = {}


def tool(name: str, description: str, properties: dict | None = None,
         required: list[str] | None = None):
    """Register a function as a tool the AI can call. Registration order = order shown to the AI."""
    def wrap(fn):
        TOOLS[name] = {"fn": fn, "schema": {"type": "function", "function": {
            "name": name, "description": description,
            "parameters": {"type": "object", "properties": properties or {},
                           "required": required or []}}}}
        return fn
    return wrap


def S(desc: str) -> dict:
    return {"type": "string", "description": desc}


def I(desc: str) -> dict:  # noqa: E743
    return {"type": "integer", "description": desc}


def B(desc: str) -> dict:
    return {"type": "boolean", "description": desc}


def day_label(d: dt.date) -> str:
    return i18n.day_label(d)


def parse_date(s: str) -> dt.date:
    try:
        return dt.date.fromisoformat(str(s).strip()[:10])
    except ValueError:
        raise ValueError(f"日期要写成 YYYY-MM-DD，收到的是「{s}」")


def parse_time(s: str) -> str:
    s = str(s or "").strip()
    if not s:
        return ""
    m = re.fullmatch(r"(\d{1,2})[:.](\d{2})", s)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ValueError(f"时间要写成 HH:MM，收到的是「{s}」")
    return f"{int(m.group(1)):02d}:{m.group(2)}"
