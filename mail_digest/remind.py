#!/usr/bin/env python3
"""Zero-token deadline reminders based only on deadlines.json.

--morning sends a 07:00 summary of upcoming three-day deadlines. The default mode
sends one urgent daytime reminder for deadlines less than three hours away. --dry-run
prints without sending or saving.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import re
import sys
import tomllib
from pathlib import Path

import i18n
from common import DATA, TZ, load_env, load_json, now, save_json, send_telegram
from i18n import tr
from ilias_sync import locked_store, upcoming

TODO_FILE = DATA / "todos.json"      # Dated miscellaneous to-dos recorded by the bot are also reminded.


def todo_items() -> list[dict]:
    """Convert unfinished dated to-dos to the same format as deadlines."""
    todos = load_json(TODO_FILE, [])
    out = []
    for t in todos:
        if t.get("done") or not t.get("date"):
            continue
        day = dt.date.fromisoformat(t["date"])
        hh, mm = map(int, t["time"].split(":")) if t.get("time") else (0, 0)
        out.append({"course": tr("rm.todo"), "title": t["text"], "todo_id": t["id"],
                    "due": dt.datetime(day.year, day.month, day.day, hh, mm, tzinfo=TZ)
                    .isoformat(timespec="minutes"),
                    "time_known": bool(t.get("time")), "reminded": t.get("reminded", [])})
    return out


def save_todo_reminded(items: list[dict]) -> None:
    """Persist the reminded flag after rereading todos.json to avoid overwriting bot changes."""
    done = {d["todo_id"]: d["reminded"] for d in items if "todo_id" in d}
    if not done or not TODO_FILE.exists():
        return
    todos = load_json(TODO_FILE, [])
    for t in todos:
        if t["id"] in done:
            t["reminded"] = done[t["id"]]
    save_json(TODO_FILE, todos)


def line(d: dict, with_date: bool) -> str:
    due = dt.datetime.fromisoformat(d["due"])
    if with_date:
        when = i18n.due_label(due, d.get("time_known"))
    else:
        when = f"{due:%H:%M}" if d.get("time_known") else tr("no_time").strip()
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
    out = [tr("rm.morning")]
    if groups["today"]:
        out += [tr("rm.today")] + [line(d, False) for d in groups["today"]]
    if groups["tomorrow"]:
        out += [tr("rm.tomorrow")] + [line(d, False) for d in groups["tomorrow"]]
    if groups["soon"]:
        out += [tr("rm.soon")] + [line(d, True) for d in groups["soon"]]
    return "\n".join(out)


def urgent(store: list[dict], quiet: list[int]) -> str:
    t = now()
    a, b = quiet
    if (a <= t.hour < b) if a <= b else (t.hour >= a or t.hour < b):   # Also supports ranges spanning midnight, e.g. 23→7.
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
    return tr("rm.urgent") + "\n" + "\n".join(line(d, False) for d in hits)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DATA / "config.toml"))
    ap.add_argument("--morning", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    load_env(DATA / ".env")
    cfg = tomllib.loads(Path(args.config).read_text(encoding="utf-8"))
    i18n.use(cfg)
    quiet = cfg.get("ilias", {}).get("quiet_hours", [0, 7])

    with locked_store(save=not args.dry_run) as store:
        todos = todo_items()
        combined = store + todos               # Read together only; to-dos are never written into deadlines.json.
        combined.sort(key=lambda x: x["due"])
        text = morning(combined) if args.morning else urgent(combined, quiet)
        if text and not args.dry_run:
            send_telegram(text, cfg["telegram"])   # Do not save “reminded” on delivery failure so it is retried.
            if not args.morning:
                save_todo_reminded(todos)

    if args.dry_run:
        print(re.sub(r"<[^>]+>", "", text) or "(no reminders to send right now)")
        print("\n[dry-run] nothing sent, nothing saved")
    else:
        print("Reminder sent" if text else "No reminders to send right now")
    return 0


if __name__ == "__main__":
    sys.exit(main())
