"""O1 Assignments and deadlines: ddl_* (deadlines.json, shared with ilias_sync and digest, locked)."""
from __future__ import annotations

import datetime as dt
import re

import ilias_sync
from common import TZ, load_json, now
from i18n import tr

from .base import B, I, S, day_label, parse_date, parse_time, tool


def _ensure_ids(store: list[dict]) -> None:
    n = max((d.get("id", 0) for d in store), default=0)
    for d in store:
        if not d.get("id"):
            n += 1
            d["id"] = n


def _find(store: list[dict], id_) -> dict:
    d = next((x for x in store if x.get("id") == int(id_)), None)
    if not d:
        raise ValueError(f"没有编号 #{id_} 的作业（先用 ddl_list 查编号）")
    return d


def _due(date: str, time_: str) -> tuple[str, bool]:
    day, t = parse_date(date), parse_time(time_)
    hh, mm = map(int, t.split(":")) if t else (0, 0)
    return dt.datetime(day.year, day.month, day.day, hh, mm, tzinfo=TZ).isoformat(
        timespec="minutes"), bool(t)


def _ddl_line(d: dict) -> str:
    s = f"#{d['id']} [{d['course']}] {d['title']} — {ilias_sync.fmt_due(d)}"
    if d.get("deleted"):
        s += "（已删除）"
    elif d.get("replaced_by"):
        s += "（已推迟到别的日期）"
    elif d.get("done"):
        s += "（✅ 已交）"
    elif ilias_sync.is_future(d):
        s += f"，{ilias_sync.days_left(d)}"
    else:
        s += "（已过期）"
    return s


EXAM = re.compile(r"klausur|prüfung|pruefung|\bexam", re.I)


def released(d: dict, published: dict) -> bool:
    """Whether a sheet is already published (unpublished ones only appear in a schedule table).
    When unsure, count it as published so nothing is missed."""
    if d.get("source") in ("ical", "mail", "manual", "bot"):   # ILIAS exercises, mail, and user-added items count.
        return True
    if d.get("release"):                                         # The course page provides a release date.
        return d["release"] <= now().date().isoformat()
    nums = ilias_sync.SHEET_NO.findall(d["title"])
    pub = published.get(d["course"])
    if not nums or not pub:                                      # No number or no data for this course.
        return True
    return int(nums[0]) in pub                                   # A file or exercise with this number appears in ILIAS.


@tool("ddl_list", "列出作业/考试/截止时间（带编号）。默认只列已经发布的作业，"
      "还没发布的（只在日程表里写了日期）和考试只给个数。修改、标记之前先用它找到编号；"
      "要找的那个不在列表里就用 all=true，还找不到就用 include_done=true（可能已经标记过交了）。",
      {"this_week": B("只看这周的（到这周日）。我问「这周…」时用"),
       "days": I("只看今后多少天内的"),
       "course": S("只看某门课（课名的一部分即可）"),
       "all": B("全部都列，包括还没发布的作业和考试。只有我说「全部」「所有」「考试」时，或者找编号时才用"),
       "include_done": B("也列出已交、已删除和最近 14 天已过期的")})
def ddl_list(a: dict) -> str:
    with ilias_sync.locked_store() as store:
        _ensure_ids(store)
        items = list(store)
    published = load_json(ilias_sync.STATE_FILE, {}).get("published", {})
    t = now()
    cutoff = None
    if a.get("this_week"):
        cutoff = dt.datetime.combine(t.date() + dt.timedelta(days=6 - t.weekday()), dt.time(23, 59), TZ)
    elif a.get("days"):
        cutoff = t + dt.timedelta(days=int(a["days"]))
    show_all = a.get("all") or a.get("include_done")
    out, unreleased, exams = [], [], []
    for d in items:
        due = dt.datetime.fromisoformat(d["due"])
        if a.get("course") and a["course"].lower() not in d["course"].lower():
            continue
        active = ilias_sync.is_future(d) and not d.get("done")
        if not active and not (a.get("include_done") and due > t - dt.timedelta(days=14)):
            continue
        if cutoff and due > cutoff:
            continue
        if not show_all and active and EXAM.search(d["title"]):
            exams.append(d)
        elif not show_all and active and not released(d, published):
            unreleased.append(d)
        else:
            out.append(_ddl_line(d) + ("" if released(d, published) else "（还没发布）"))
    head = f"（这周，到 {day_label(cutoff.date())}）\n" if a.get("this_week") else ""
    text = head + ("\n".join(out) or "没有符合条件的作业。")
    extra = []
    if unreleased:
        extra.append(f"还没发布的作业 {len(unreleased)} 个（最早 {ilias_sync.fmt_due(unreleased[0])} 截止）")
    if exams:
        extra.append(f"考试 {len(exams)} 个（最早 {ilias_sync.fmt_due(exams[0])}）")
    if extra:
        text += "\n另外：" + "；".join(extra) + "。all=true 可以看全部"
    return text


@tool("ddl_done", "把一个作业标记为已交（之后不再提醒）。undo=true 表示撤销，恢复提醒。",
      {"id": I("作业编号"), "undo": B("撤销已交 / 已删除")}, ["id"])
def ddl_done(a: dict) -> str:
    with ilias_sync.locked_store() as store:
        _ensure_ids(store)
        d = _find(store, a["id"])
        if a.get("undo"):
            for k in ("done", "deleted", "done_at", "replaced_by"):
                d.pop(k, None)
            return "已恢复提醒：" + _ddl_line(d)
        d["done"], d["done_at"] = True, now().isoformat(timespec="minutes")
        return "已标记为交了：" + _ddl_line(d)


@tool("ddl_add", "新增一个截止时间（作业、考试、报名等），会参与提醒。",
      {"course": S("课名，尽量用课程列表里的名字；不是课就写个类别，比如「签证」"),
       "title": S("做什么，比如「Übungsblatt 04」"),
       "date": S("截止日期 YYYY-MM-DD"), "time": S("截止时间 HH:MM，不知道就不填")},
      ["course", "title", "date"])
def ddl_add(a: dict) -> str:
    due, known = _due(a["date"], a.get("time", ""))
    if due[:10] < now().date().isoformat():
        raise ValueError("这个日期已经过去了")
    title = a["title"].strip()[:100]
    if not title:
        raise ValueError("标题不能为空")
    d = {"course": a["course"].strip(), "title": title, "due": due,
         "time_known": known, "source": "bot"}
    with ilias_sync.locked_store() as store:
        _ensure_ids(store)
        added = ilias_sync.merge(store, [d])
        _ensure_ids(store)
        if not added:
            same = ilias_sync.find_deadline(store, d)
            return "已有这项截止时间，没有重复添加：" + _ddl_line(same)
        return "已添加：" + _ddl_line(d)


@tool("ddl_edit", "修改一个截止时间：推迟/改日期、改时间、改标题、改课名。只填要改的。",
      {"id": I("作业编号"), "date": S("新日期 YYYY-MM-DD"),
       "time": S("新时间 HH:MM；写 none 表示没有具体时间"),
       "title": S("新标题"), "course": S("新课名")}, ["id"])
def ddl_edit(a: dict) -> str:
    with ilias_sync.locked_store() as store:
        _ensure_ids(store)
        d = _find(store, a["id"])
        old = _ddl_line(d)
        if a.get("date") or a.get("time"):
            cur = dt.datetime.fromisoformat(d["due"])
            date = a.get("date") or cur.date().isoformat()
            t = a.get("time")
            t = "" if str(t).lower() in ("none", "null", "-") else (
                t or (f"{cur:%H:%M}" if d.get("time_known") else ""))
            due, known = _due(date, t)
            if due[:10] != d["due"][:10]:
                # Remember the old date so later ILIAS or email scans do not restore it.
                d.setdefault("aliases", []).append(d["due"][:10])
            d["due"], d["time_known"], d["reminded"] = due, known, []
        title = str(a.get("title") or "").strip()[:100]
        if title and title != d["title"]:
            d.setdefault("title_aliases", []).append(d["title"])
            d["title"] = title
        if a.get("course"):
            d["course"] = a["course"].strip()
        store.sort(key=lambda x: x["due"])
        return f"改好了。\n原来：{old}\n现在：{_ddl_line(d)}"


@tool("ddl_delete", "删除一个截止时间（不再提醒；可以用 ddl_done undo=true 恢复）。",
      {"id": I("作业编号")}, ["id"])
def ddl_delete(a: dict) -> str:
    with ilias_sync.locked_store() as store:
        _ensure_ids(store)
        d = _find(store, a["id"])
        d["done"] = d["deleted"] = True
        d["done_at"] = now().isoformat(timespec="minutes")
        out = "已删除：" + _ddl_line(d)
    if d.get("source") == "mail":
        # For mail-added items, learn whether this category should be ignored after the user confirms.
        out += ("\n（这一条是从邮件里自动加进提醒的。请接着调用 settings_change："
                f"key=about_me, action=add, value=「{tr('no_interest')}<把它概括成一类，不超过 20 字，"
                "比如「短期交流/跨校课程项目」，不要只写这一个项目的名字>」。"
                "程序会问我以后这类要不要都不加；回答里只要说已经删了。）")
    return out
