#!/usr/bin/env python3
"""
截止时间提醒（0 token，只看 deadlines.json）

两种模式：
  python3 remind.py --morning   每天 07:00：近 3 天的截止时间汇总（今天 / 明天 / 3 天内）
                                近 3 天什么都没有就不发
  python3 remind.py             白天每小时：还剩不到 3 小时的发一条紧急提醒
                                （同一个只提醒一次；没写具体时间的不发，只出现在早上的汇总里）
加 --dry-run 只打印，不推送、不保存。
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
import tomllib
from pathlib import Path

from digest import load_env, send_telegram
from ilias_sync import HERE, TZ, WEEKDAYS, locked_store, now, save_json, upcoming

TODO_FILE = HERE / "todos.json"      # 机器人记的杂事待办：写了日期的也一起提醒


def todo_items() -> list[dict]:
    """有日期、还没完成的待办，变成和截止时间一样的格式。"""
    todos = json.loads(TODO_FILE.read_text(encoding="utf-8")) if TODO_FILE.exists() else []
    out = []
    for t in todos:
        if t.get("done") or not t.get("date"):
            continue
        day = dt.date.fromisoformat(t["date"])
        hh, mm = map(int, t["time"].split(":")) if t.get("time") else (0, 0)
        out.append({"course": "📝 待办", "title": t["text"], "todo_id": t["id"],
                    "due": dt.datetime(day.year, day.month, day.day, hh, mm, tzinfo=TZ)
                    .isoformat(timespec="minutes"),
                    "time_known": bool(t.get("time")), "reminded": t.get("reminded", [])})
    return out


def save_todo_reminded(items: list[dict]) -> None:
    """把"已提醒"写回 todos.json（重新读一次再改，避免盖掉机器人刚写的）。"""
    done = {d["todo_id"]: d["reminded"] for d in items if "todo_id" in d}
    if not done or not TODO_FILE.exists():
        return
    todos = json.loads(TODO_FILE.read_text(encoding="utf-8"))
    for t in todos:
        if t["id"] in done:
            t["reminded"] = done[t["id"]]
    save_json(TODO_FILE, todos)


def line(d: dict, with_date: bool) -> str:
    due = dt.datetime.fromisoformat(d["due"])
    when = f"{due.month}/{due.day} 周{WEEKDAYS[due.weekday()]} " if with_date else ""
    when += f"{due:%H:%M}" if d.get("time_known") else "（没写具体时间）"
    return f" • [{html.escape(d['course'])}] {html.escape(d['title'])} — {when}"


def morning(store: list[dict]) -> str:
    today = now().date()
    groups = {"today": [], "tomorrow": [], "soon": []}
    for d in upcoming(store):
        days = (dt.datetime.fromisoformat(d["due"]).date() - today).days
        if days == 0:
            groups["today"].append(d)
        elif days == 1:
            groups["tomorrow"].append(d)
        elif days <= 3:
            groups["soon"].append(d)
    if not any(groups.values()):
        return ""
    out = ["☀️ <b>近 3 天要做的事</b>"]
    if groups["today"]:
        out += ["🔴 <b>今天截止</b>"] + [line(d, False) for d in groups["today"]]
    if groups["tomorrow"]:
        out += ["🟠 <b>明天截止</b>"] + [line(d, False) for d in groups["tomorrow"]]
    if groups["soon"]:
        out += ["🟡 <b>3 天内</b>"] + [line(d, True) for d in groups["soon"]]
    return "\n".join(out)


def urgent(store: list[dict], quiet: list[int]) -> str:
    t = now()
    a, b = quiet
    if (a <= t.hour < b) if a <= b else (t.hour >= a or t.hour < b):   # 23→7 这种跨午夜的也行
        return ""
    hits = []
    for d in upcoming(store):
        if not d.get("time_known") or "3h" in d.get("reminded", []):
            continue
        hours_left = (dt.datetime.fromisoformat(d["due"]) - t).total_seconds() / 3600
        if hours_left <= 3:
            hits.append(d)
            d["reminded"] = sorted(set(d.get("reminded", [])) | {"3h"})
    if not hits:
        return ""
    return "🚨 <b>3 小时内截止</b>\n" + "\n".join(line(d, False) for d in hits)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(HERE / "config.toml"))
    ap.add_argument("--morning", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    load_env(HERE / ".env")
    cfg = tomllib.loads(Path(args.config).read_text(encoding="utf-8"))
    quiet = cfg.get("ilias", {}).get("quiet_hours", [0, 7])

    with locked_store(save=not args.dry_run) as store:
        todos = todo_items()
        combined = store + todos               # 只是一起看；待办不会写进 deadlines.json
        combined.sort(key=lambda x: x["due"])
        text = morning(combined) if args.morning else urgent(combined, quiet)
        if text and not args.dry_run:
            send_telegram(text, cfg["telegram"])   # 发送失败就不保存"已提醒"，下次再试
            if not args.morning:
                save_todo_reminded(todos)

    if args.dry_run:
        print(re.sub(r"<[^>]+>", "", text) or "（现在没有要发的提醒）")
        print("\n[dry-run] 没有推送、没有保存")
    else:
        print("已发送提醒" if text else "现在没有要发的提醒")
    return 0


if __name__ == "__main__":
    sys.exit(main())
