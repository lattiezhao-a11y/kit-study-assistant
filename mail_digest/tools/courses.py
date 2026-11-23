"""Course menu: re-pick the tracked ILIAS courses from Telegram (new semester, a course added later).

Opened by /courses, by the button under ilias_sync's new-semester notice, or by the AI through
courses_menu. Only courses the user already joined in ILIAS are offered: joining happens in ILIAS.
The AI can only open the menu; config.toml changes only when the user presses Save.
"""
from __future__ import annotations

import time
import tomllib

from i18n import tr
from ilias_courses import menu_choices, merge_courses, my_courses, replace_courses

from . import base
from .base import tool
from .forum import _with_ilias
from .settings import write_config_text

MENU_MINUTES = 30           # A menu older than this no longer accepts button presses.
MENU: dict = {}             # The one live menu: message_id, items, choices, picked, at.


@tool("courses_menu", "打开选课列表：程序会把我在 ILIAS 上已经加入的课做成勾选按钮直接发给我，我自己点选、保存。"
      "我说「新学期了」「重新选课」「换一下跟踪的课」「加一门课」时用。你自己改不了跟踪的课，也不要自己列课程。")
def courses_menu(a: dict) -> str:
    base.PENDING["courses_menu"] = True
    return "选课列表会由程序在你这条回答之后直接发给我。你只要简短说一句列表马上就来，不要自己列课程。"


def _config() -> tuple[str, dict, dict[int, dict]]:
    text = base.CONFIG_PATH.read_text(encoding="utf-8")
    cfg = tomllib.loads(text)
    return text, cfg, {int(c["crs"]): c for c in cfg.get("ilias", {}).get("courses", [])}


def open_menu(items: list[dict] | None = None) -> tuple[str, dict]:
    """Read the joined courses from ILIAS (about 10 s) and start a fresh menu.
    Returns the message text and its keyboard; the caller stores MENU["message_id"]."""
    if items is None:
        items = _with_ilias(my_courses)
    _, _, existing = _config()
    MENU.clear()
    MENU.update(items=items, choices=menu_choices(items, existing), picked=set(existing),
                at=time.time(), message_id=None)
    return tr("cs.menu"), keyboard()


def keyboard() -> dict:
    rows = [[{"text": ("✅ " if c["ref"] in MENU["picked"] else "⬜ ") + c["name"]
              + (f"  [{c['note']}]" if c["note"] else ""),
              "callback_data": f"crs:t:{c['ref']}"}] for c in MENU["choices"]]
    rows.append([{"text": tr("cs.save"), "callback_data": "crs:save"},
                 {"text": tr("cs.cancel"), "callback_data": "crs:cancel"}])
    return {"inline_keyboard": rows}


def is_live(message_id) -> bool:
    return (bool(MENU) and MENU.get("message_id") == message_id
            and time.time() - MENU["at"] < MENU_MINUTES * 60)


def toggle(ref: int) -> None:
    if any(c["ref"] == ref for c in MENU["choices"]):
        MENU["picked"] ^= {ref}


def cancel() -> str:
    MENU.clear()
    return tr("cs.cancelled")


def save() -> str:
    """Write the picked courses to config.toml (verified, backed up). Raises ValueError if none is picked."""
    picked = [c["ref"] for c in MENU["choices"] if c["ref"] in MENU["picked"]]
    if not picked:
        raise ValueError(tr("cs.need_one"))
    text, cfg, existing = _config()
    if set(picked) == set(existing):
        MENU.clear()
        return tr("cs.unchanged", n=len(existing))
    courses = merge_courses(MENU["items"], existing, picked)
    cfg.setdefault("ilias", {})["courses"] = courses
    write_config_text(replace_courses(text, courses), cfg)
    MENU.clear()
    sep = tr("cs.sep")
    added = [c["name"] for c in courses if c["crs"] not in existing]
    removed = [e["name"] for ref, e in existing.items() if ref not in picked]
    changes = (tr("cs.added", names=sep.join(added)) if added else "") + \
              (tr("cs.removed", names=sep.join(removed)) if removed else "")
    return tr("cs.saved", n=len(courses), changes=changes)
