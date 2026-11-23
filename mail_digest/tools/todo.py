"""O2 Miscellaneous to-dos: todo_* (todos.json). Dated ones also appear in remind.py."""
from __future__ import annotations

import datetime as dt

from common import load_json, now, save_json

from . import base
from .base import B, I, S, day_label, parse_date, parse_time, tool


def _todo_line(t: dict) -> str:
    s = f"#{t['id']} {t['text']}"
    if t.get("date"):
        s += f"（{day_label(dt.date.fromisoformat(t['date']))}{' ' + t['time'] if t.get('time') else ''}）"
    return s + ("（✅ 已完成）" if t.get("done") else "")


@tool("todo_add", "记一件杂事待办（不是课程作业的事，比如买东西、去银行、交房租）。"
      "有日期的会出现在早上 7 点的汇总里，有具体时间的还会提前 3 小时提醒。",
      {"text": S("要做的事"), "date": S("哪天要做 YYYY-MM-DD，没说就不填"),
       "time": S("几点 HH:MM，没说就不填")}, ["text"])
def todo_add(a: dict) -> str:
    todos = load_json(base.TODO_FILE, [])
    t = {"id": max((x["id"] for x in todos), default=0) + 1, "text": a["text"].strip()[:200],
         "added": now().isoformat(timespec="minutes")}
    if a.get("date"):
        t["date"] = parse_date(a["date"]).isoformat()
        if parse_time(a.get("time", "")):
            t["time"] = parse_time(a["time"])
    todos.append(t)
    save_json(base.TODO_FILE, todos)
    return "已记下：" + _todo_line(t)


@tool("todo_list", "列出杂事待办（带编号）。",
      {"include_done": B("也列出已完成的（最近 30 天）")})
def todo_list(a: dict) -> str:
    todos = load_json(base.TODO_FILE, [])
    cutoff = (now() - dt.timedelta(days=30)).isoformat()
    show = [t for t in todos if not t.get("done")
            or (a.get("include_done") and t.get("done_at", "") >= cutoff)]
    show.sort(key=lambda t: (bool(t.get("done")), t.get("date") or "9999", t["id"]))
    return "\n".join(_todo_line(t) for t in show) or "没有待办。"


@tool("todo_done", "把待办标记为完成；undo=true 撤销。", {"id": I("待办编号"), "undo": B("撤销")}, ["id"])
def todo_done(a: dict) -> str:
    todos = load_json(base.TODO_FILE, [])
    t = next((x for x in todos if x["id"] == int(a["id"])), None)
    if not t:
        raise ValueError(f"没有编号 #{a['id']} 的待办（先用 todo_list 查编号）")
    if a.get("undo"):
        t.pop("done", None), t.pop("done_at", None)
    else:
        t["done"], t["done_at"] = True, now().isoformat(timespec="minutes")
    save_json(base.TODO_FILE, todos)
    return ("已恢复：" if a.get("undo") else "已完成：") + _todo_line(t)


@tool("todo_delete", "彻底删除一条待办（记错了的时候用）。", {"id": I("待办编号")}, ["id"])
def todo_delete(a: dict) -> str:
    todos = load_json(base.TODO_FILE, [])
    t = next((x for x in todos if x["id"] == int(a["id"])), None)
    if not t:
        raise ValueError(f"没有编号 #{a['id']} 的待办")
    todos.remove(t)
    save_json(base.TODO_FILE, todos)
    return "已删除：" + _todo_line(t)
