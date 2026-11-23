"""O5 Weekly timetable and day schedule: timetable_*, schedule (timetable.json + ILIAS calendar)."""
from __future__ import annotations

import datetime as dt
import re
import time
import urllib.request

import ilias_sync
from common import TZ, load_json, now, save_json, secret

from . import base
from .base import I, S, day_label, parse_date, parse_time, tool

WEEKDAYS = "一二三四五六日"     # Used in timetable tool results for the AI; user-facing dates use i18n.day_label.


_ical_cache: dict = {"at": 0.0, "events": []}


def _ical_events() -> list[dict]:
    """Course events from the ILIAS calendar (lectures, tutorials; deadlines come from deadlines.json).
    Cached for 30 minutes."""
    if time.time() - _ical_cache["at"] < 1800:
        return _ical_cache["events"]
    url = secret(base.CFG["ilias"]["ical_url_env"])
    req = urllib.request.Request(url, headers={"User-Agent": ilias_sync.UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        text = re.sub(r"\r?\n[ \t]", "", r.read().decode("utf-8", "replace"))
    events = []
    for ev in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S):
        def field(k):
            m = re.search(rf"^{k}([^:\n]*):(.*)$", ev, re.M)
            return (m.group(1), m.group(2).strip()) if m else ("", "")
        summary = field("SUMMARY")[1].replace("\\,", ",").replace("\\;", ";")
        if "Abgabetermin" in summary:
            continue
        def when(k):
            params, raw = field(k)
            if not raw:
                return None, False
            if "VALUE=DATE" in params:
                return dt.datetime.strptime(raw[:8], "%Y%m%d").replace(tzinfo=TZ), False
            if raw.endswith("Z"):
                return dt.datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(
                    tzinfo=dt.timezone.utc).astimezone(TZ), True
            return dt.datetime.strptime(raw[:15], "%Y%m%dT%H%M%S").replace(tzinfo=TZ), True
        start, timed = when("DTSTART")
        end, _ = when("DTEND")
        if start:
            loc = field("LOCATION")[1].replace("\\,", ",")
            events.append({"start": start, "end": end, "timed": timed, "title": summary,
                           "where": loc})
    _ical_cache.update(at=time.time(), events=events)
    return events


@tool("timetable_add", "往每周固定课表里加一节课（每周重复）。",
      {"weekday": I("星期几，1=周一 … 7=周日"), "start": S("开始 HH:MM"), "end": S("结束 HH:MM"),
       "course": S("课名"), "kind": S("类型：讲座 / 练习 / Tutorium …"), "room": S("教室")},
      ["weekday", "start", "end", "course"])
def timetable_add(a: dict) -> str:
    wd = int(a["weekday"])
    if not 1 <= wd <= 7:
        raise ValueError("weekday 要在 1~7 之间")
    tt = load_json(base.TIMETABLE_FILE, [])
    e = {"id": max((x["id"] for x in tt), default=0) + 1, "weekday": wd,
         "start": parse_time(a["start"]), "end": parse_time(a["end"]),
         "course": a["course"].strip(), "kind": str(a.get("kind") or "").strip(),
         "room": str(a.get("room") or "").strip()}
    if not e["start"] or not e["end"]:
        raise ValueError("开始和结束时间都要有")
    tt.append(e)
    tt.sort(key=lambda x: (x["weekday"], x["start"]))
    save_json(base.TIMETABLE_FILE, tt)
    return "已加入课表：" + _tt_line(e, True)


def _tt_line(e: dict, with_day: bool = False) -> str:
    s = f"课#{e['id']} " + (f"每周{WEEKDAYS[e['weekday'] - 1]} " if with_day else "")
    s += f"{e['start']}–{e['end']} {e['course']}"
    s += f" {e['kind']}" if e.get("kind") else ""
    return s + (f" @ {e['room']}" if e.get("room") else "")


@tool("timetable_remove", "从每周课表里删掉一节课（编号是 schedule 或 timetable_list 里的 课#N）。",
      {"id": I("课的编号 N")}, ["id"])
def timetable_remove(a: dict) -> str:
    tt = load_json(base.TIMETABLE_FILE, [])
    e = next((x for x in tt if x["id"] == int(a["id"])), None)
    if not e:
        raise ValueError(f"课表里没有 课#{a['id']}")
    tt.remove(e)
    save_json(base.TIMETABLE_FILE, tt)
    return "已从课表删除：" + _tt_line(e, True)


@tool("timetable_list", "列出每周固定课表（带编号）。")
def timetable_list(a: dict) -> str:
    tt = load_json(base.TIMETABLE_FILE, [])
    return "\n".join(_tt_line(e, True) for e in tt) or "课表还是空的（可以让我用 timetable_add 加）。"


@tool("schedule", "查某几天的安排：每周课表 + ILIAS 日历里的活动 + 当天截止的作业 + 当天的待办。",
      {"date": S("从哪天开始 YYYY-MM-DD，默认今天"), "days": I("看几天，1~14，默认 1")})
def schedule(a: dict) -> str:
    start = parse_date(a["date"]) if a.get("date") else now().date()
    days = max(1, min(int(a.get("days") or 1), 14))
    tt = load_json(base.TIMETABLE_FILE, [])
    todos = [t for t in load_json(base.TODO_FILE, []) if t.get("date") and not t.get("done")]
    with ilias_sync.locked_store(save=False) as store:
        ddls = [d for d in store if not d.get("done")]
    try:
        events, ical_err = _ical_events(), ""
    except Exception as e:
        events, ical_err = [], f"（ILIAS 日历读取失败：{e}）"
    out = []
    for i in range(days):
        day = start + dt.timedelta(days=i)
        lines = [f"  {_tt_line(e)}" for e in tt if e["weekday"] == day.isoweekday()]
        for ev in sorted((e for e in events if e["start"].date() == day), key=lambda e: e["start"]):
            t = f"{ev['start']:%H:%M}" + (f"–{ev['end']:%H:%M}" if ev["end"] and ev["timed"] else "") \
                if ev["timed"] else "全天"
            lines.append(f"  {t} {ev['title']}（ILIAS 日历）" + (f" @ {ev['where']}" if ev["where"] else ""))
        for d in ddls:
            if d["due"][:10] == day.isoformat():
                lines.append(f"  ⏰ 截止 #{d['id']} [{d['course']}] {d['title']} "
                             + (f"{d['due'][11:16]}" if d.get("time_known") else "（没写具体时间）"))
        for t in todos:
            if t["date"] == day.isoformat():
                lines.append(f"  📝 待办 #{t['id']} {t.get('time', '')} {t['text']}".replace("  ", " "))
        out.append(f"{day_label(day)}：" + ("\n" + "\n".join(lines) if lines else " 没有安排"))
    if not tt:
        out.append("（每周课表还是空的，所以上面只有 ILIAS 日历里的活动）")
    return "\n".join(out) + ("\n" + ical_err if ical_err else "")
