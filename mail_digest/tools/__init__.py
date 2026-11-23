"""Tools the bot can call (O1–O6). Each tool takes an argument dict and returns text for the AI.

  ddl.py        O1 assignments / deadlines  ddl_*        (deadlines.json, shared with ILIAS and mail scripts, locked)
  todo.py       O2 miscellaneous to-dos     todo_*       (todos.json)
  mail.py       O3 email, read-only         mail_*       (last 7 days; never sends, deletes or marks as read)
  settings.py   O4 settings                 settings_*   (AI only proposes; applied after the user confirms, backed up)
                language                    language_set (zh / de, applies at once)
  timetable.py  O5 timetable / schedule     timetable_*, schedule
  forum.py      O6 ILIAS forums, read-only  forum_*
  base.py       registry, data paths, CFG, PENDING, small parsers

Test a single tool: python3 bot.py --tool NAME '{"arg": "value"}'
"""
# Import order = order of the tools shown to the AI; keep it stable.
from . import base, ddl, todo, mail, settings, timetable, forum  # noqa: F401
from .base import CFG, PENDING, TOOLS  # noqa: F401
from .settings import apply_pending, set_language  # noqa: F401

__all__ = ["base", "ddl", "todo", "mail", "settings", "timetable", "forum",
           "CFG", "PENDING", "TOOLS", "apply_pending", "set_language"]
