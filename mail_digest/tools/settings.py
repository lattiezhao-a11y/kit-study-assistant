"""O4 Settings: settings_* (the AI only proposes; the program applies after the user confirms,
backing up config.toml first) and language_set (applies at once, no confirmation)."""
from __future__ import annotations

import json
import re
import shutil
import time
import tomllib
from pathlib import Path

import i18n
from common import now
from i18n import tr

from . import base
from .base import S, tool


# Mutable settings: key → (containing section, type, description)
SETTINGS = {
    "always_ignore": ("llm", "list", "一律忽略的邮件（规则，一条一句话）"),
    "always_important_senders": ("safety_net", "list", "这些发件人的邮件至少是「必须处理」"),
    "about_me": ("llm", "text", "给 AI 看的自我介绍，一行一条：我是谁、关心什么、不感兴趣什么"
                 "（「不感兴趣：…」那几行说的邮件会被忽略、不加提醒）"),
    "job_search": ("job", "bool", "是否在找工作（false = 招聘邮件全部忽略）"),
    "quiet_hours": ("ilias", "hours", "几点到几点之间不发紧急提醒，比如 [0, 7]"),
    "forum_hour": ("ilias", "int", "每天几点那次检查顺便发论坛总结（1/7/13/19 之一）"),
}


def _lines(text) -> list[str]:
    return [ln.strip() for ln in str(text).splitlines() if ln.strip()]


def _get_setting(cfg: dict, key: str):
    sec, kind, _ = SETTINGS[key]
    default = {"list": [], "text": "", "bool": False, "hours": [0, 7], "int": 19}[kind]
    return cfg.get(sec, {}).get(key, default)


@tool("settings_show", "查看现在能通过聊天修改的设置和它们的值。")
def settings_show(a: dict) -> str:
    cfg = tomllib.loads(base.CONFIG_PATH.read_text(encoding="utf-8"))
    out = []
    for key, (sec, kind, desc) in SETTINGS.items():
        val = _get_setting(cfg, key)
        if kind in ("list", "text"):
            rows = val if kind == "list" else _lines(val)
            out.append(f"{key}：{desc}\n" + ("\n".join(f"  {i}. {v}" for i, v in enumerate(rows, 1))
                                             or "  （空）"))
        else:
            out.append(f"{key}：{desc}\n  现在：{json.dumps(val, ensure_ascii=False)}")
    out.append(f"language：语言（用 language_set 改，马上生效）\n  现在：{i18n.lang_of(cfg)}")
    out.append("（邮件检查和早上汇总的时间由系统定时器控制，聊天里改不了）")
    return "\n".join(out)


@tool("settings_change", "提议修改一项设置。不会马上生效：程序会把改动发给我，我回复「确认」才改。"
      "always_ignore、always_important_senders、about_me 用 add（加一条）/ remove（删一条，"
      "value 可以写序号）；about_me 也可以 set 整段重写；其它用 set。"
      "我说对某类东西不感兴趣时：key=about_me, action=add, value=「不感兴趣：<那一类>」。",
      {"key": {"type": "string", "enum": list(SETTINGS), "description": "设置名"},
       "action": {"type": "string", "enum": ["add", "remove", "set"]},
       "value": S("新值 / 要加或删的那一条。quiet_hours 写成 0,7；job_search 写 true/false")},
      ["key", "action", "value"])
def settings_change(a: dict) -> str:
    key, action, value = a["key"], a["action"], str(a["value"]).strip()
    if key not in SETTINGS:
        raise ValueError("不能改这个设置")
    sec, kind, desc = SETTINGS[key]
    cfg = tomllib.loads(base.CONFIG_PATH.read_text(encoding="utf-8"))
    old = _get_setting(cfg, key)
    if kind == "list" or (kind == "text" and action != "set"):
        rows = list(old) if kind == "list" else _lines(old)    # Self-description values are added and removed line by line.
        if action == "add":
            value = " ".join(value.split()) if kind == "text" else value
            if not value or value in rows:
                raise ValueError("这一条是空的，或者已经有了")
            rows.append(value[:300])
        elif action == "remove":
            if value.isdigit() and 1 <= int(value) <= len(rows):
                rows.pop(int(value) - 1)
            else:
                hits = [v for v in rows if value.lower() in v.lower()]
                if len(hits) != 1:
                    raise ValueError(f"找到 {len(hits)} 条匹配的，请用序号（settings_show 里看）")
                rows.remove(hits[0])
        else:
            raise ValueError("列表类设置只能 add 或 remove")
        new = rows if kind == "list" else "\n".join(rows)
    else:
        if action != "set":
            raise ValueError("这个设置只能 set")
        if kind == "text":
            new = "\n".join(_lines(value))[:3000]
        elif kind == "bool":
            if value.lower() not in ("true", "false"):
                raise ValueError("只能是 true 或 false")
            new = value.lower() == "true"
        elif kind == "int":
            new = int(value)
            if new not in (1, 7, 13, 19):
                raise ValueError("论坛总结只能跟着检查时间：1、7、13、19 点之一")
        else:
            nums = [int(x) for x in re.findall(r"\d+", value)]
            if len(nums) != 2 or not all(0 <= x <= 23 for x in nums):
                raise ValueError("要写两个 0~23 的小时，比如 0,7")
            new = nums
    if new == old:
        return "和现在的值一样，不用改。"
    def fmt(v) -> str:
        if kind not in ("list", "text"):
            return " " + json.dumps(v, ensure_ascii=False)
        rows = v if kind == "list" else _lines(v)
        return "".join(f"\n  {i}. {x}" for i, x in enumerate(rows, 1)) or tr("set.empty")
    # The program sends this preview directly, so use the current language.
    shown = i18n.SETTING_DESC_DE[key] if i18n.LANG == "de" else desc
    preview = tr("set.preview", key=key, desc=shown, old=fmt(old), new=fmt(new))
    if kind == "text" and action == "add" and value.startswith(("不感兴趣", "Kein Interesse")):
        preview += tr("set.no_interest_note")
    base.PENDING["settings"] = {"key": key, "new": new, "preview": preview, "at": time.time(),
                           "fresh": True}
    return ("改动已准备好，但还没生效。程序会把改动内容发给我，我回复「确认」才会改。"
            "你在回答里不要说已经改好了。")


def _toml_value(v, comments: list[str] = ()) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if all(isinstance(x, int) and not isinstance(x, bool) for x in v) and v:
        return "[" + ", ".join(map(str, v)) + "]"
    body = "".join(f"  {json.dumps(x, ensure_ascii=False)},\n" for x in v)
    return "[\n" + body + "".join(c + "\n" for c in comments) + "]"


def _array_end(text: str, i: int) -> int:
    depth, q, j = 0, None, i
    while j < len(text):
        c = text[j]
        if q:
            if c == "\\" and q == '"':
                j += 2
                continue
            if c == q:
                q = None
        elif c in "\"'":
            q = c
        elif c == "#":
            j = text.find("\n", j)
            if j == -1:
                break
            continue
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    raise ValueError("config.toml 里的列表没有正常结束")


def set_toml(text: str, section: str, key: str, value) -> str:
    """Change only this one value in config.toml; every other line, comments included, stays as is."""
    m = re.search(rf"^\[{re.escape(section)}\][ \t]*(#.*)?$", text, re.M)
    if not m:
        return text.rstrip("\n") + f"\n\n[{section}]\n{key} = {_toml_value(value)}\n"
    nxt = re.search(r"^\[", text[m.end():], re.M)
    end = m.end() + nxt.start() if nxt else len(text)
    k = re.compile(rf"^{re.escape(key)}[ \t]*=[ \t]*", re.M).search(text, m.end(), end)
    if not k:
        return text[:m.end()] + f"\n{key} = {_toml_value(value)}" + text[m.end():]
    vs = k.end()
    if text[vs] == "[":
        ve = _array_end(text, vs)
        comments = [ln.rstrip() for ln in text[vs:ve].split("\n") if ln.strip().startswith("#")]
    else:
        line_end = text.find("\n", vs)
        line_end = len(text) if line_end == -1 else line_end
        cm = re.search(r"[ \t]+#[^\"']*$", text[vs:line_end])        # Preserve trailing comments.
        ve = vs + cm.start() if cm else line_end
        comments = []
    return text[:vs] + _toml_value(value, comments) + text[ve:]


def write_config(sec: str, key: str, value) -> Path:
    """Change one config.toml item: verify, back up, then write. Returns the backup file; CFG is refreshed."""
    old_text = base.CONFIG_PATH.read_text(encoding="utf-8")
    new_text = set_toml(old_text, sec, key, value)
    expect = tomllib.loads(old_text)
    expect.setdefault(sec, {})[key] = value
    return write_config_text(new_text, expect)


def write_config_text(new_text: str, expect: dict) -> Path:
    """Replace config.toml with new_text only if it parses to exactly `expect`, after a backup.
    Returns the backup file; CFG is refreshed."""
    if tomllib.loads(new_text) != expect:            # Everything except the intended change must remain identical.
        raise RuntimeError(tr("set.check_failed"))
    base.BACKUP_DIR.mkdir(exist_ok=True)
    stamp = f"config.toml.{now():%Y%m%d-%H%M%S}"
    backup, n = base.BACKUP_DIR / stamp, 1
    while backup.exists():                           # Two changes within one second must not overwrite a backup.
        n += 1
        backup = base.BACKUP_DIR / f"{stamp}-{n}"
    shutil.copy2(base.CONFIG_PATH, backup)
    tmp = base.CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(new_text, encoding="utf-8")
    tmp.replace(base.CONFIG_PATH)
    base.CFG.clear()
    base.CFG.update(tomllib.loads(new_text))
    return backup


def apply_pending() -> str:
    """Called by bot.py after the user replies with a confirmation word; the AI cannot reach this.
    Backs up first and verifies the result, otherwise nothing changes."""
    p = base.PENDING.pop("settings", None)
    if not p:
        return tr("set.none_pending")
    backup = write_config(SETTINGS[p["key"]][0], p["key"], p["new"])
    return tr("set.done", key=p["key"], backup=backup.name)


# ---------------------------------------------------------------- Language (immediate, no confirmation)

def set_language(code: str) -> bool:
    """Switch language: write [general] language in config.toml and apply it at once.
    Returns whether anything changed. Used by the /start and /language buttons and by language_set."""
    code = str(code).strip().lower()
    if code not in i18n.LANGS:
        raise ValueError(f"只能是 {' / '.join(i18n.LANGS)}")
    cfg = tomllib.loads(base.CONFIG_PATH.read_text(encoding="utf-8"))
    changed = cfg.get("general", {}).get("language") != code      # Write it even if absent so it is visible in configuration.
    if changed:
        write_config("general", "language", code)
    else:
        base.CFG.clear()
        base.CFG.update(cfg)
    i18n.use(base.CFG)
    return changed


@tool("language_set", "切换语言：你的回答和所有推送（邮件摘要、提醒、ILIAS、论坛总结）都改用这个语言。"
      "马上生效，不用我确认。我说「我要用德语版」「换回中文」「Deutsch bitte」「auf Chinesisch」之类时用。",
      {"language": {"type": "string", "enum": list(i18n.LANGS), "description": "zh = 中文，de = 德语"}},
      ["language"])
def language_set(a: dict) -> str:
    code = str(a["language"]).strip().lower()
    name = {"zh": "中文", "de": "德语（Deutsch）"}.get(code, code)
    if not set_language(code):
        return f"现在已经是{name}了，不用改。用{name}回答我。"
    return (f"已切换为{name}，马上生效（邮件摘要、提醒、ILIAS、论坛总结也一样）。"
            f"从这条回答开始用{name}回答我，简短告诉我已经切换好了。")
