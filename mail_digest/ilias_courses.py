#!/usr/bin/env python3
"""List all ILIAS courses and Tutorium groups joined by the user without using tokens.

The “Meine Kurse und Gruppen” page groups memberships by semester. Group pages are
opened to identify their parent courses. wizard.py (--courses), the bot's /courses menu and
ilias_sync.py's new-semester notice share the functions below.
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

import i18n
from common import strip_tags
from i18n import tr

MEMBERSHIP_URL = "/ilias.php?baseClass=ilmembershipoverviewgui"
HEADING = re.compile(r"<h[1-6][^>]*>(.*?)</h[1-6]>", re.S)
ITEM = re.compile(r'goto\.php/(crs|grp)/(\d+)')
# Semester-title examples: WS 26/27, WS 2026/27, SS 2026, SoSe 2026, WiSe 26/27.
SEMESTER = re.compile(r"^(WS|SS|WiSe|SoSe)\s*(\d{2}|\d{4})(?:\s*/\s*(\d{2}|\d{4}))?$", re.I)
MAX_GROUP_LOOKUPS = 20     # Maximum Tutorium pages opened to identify their parent courses.


def semester_key(label: str | None) -> tuple[int, int] | None:
    """Map a semester title to a comparable (year, 1=summer/2=winter) tuple."""
    m = SEMESTER.match((label or "").strip())
    if not m:
        return None
    year = int(m.group(2))
    year += 2000 if year < 100 else 0
    winter = m.group(1).upper() in ("WS", "WISE")
    return (year, 2 if winter else 1)


def current_semester(today: dt.date | None = None) -> tuple[int, int]:
    """At KIT, winter semester runs October–March and summer semester April–September."""
    d = today or dt.date.today()
    if d.month >= 10:
        return (d.year, 2)
    if d.month <= 3:
        return (d.year - 1, 2)
    return (d.year, 1)


def semester_label(key: tuple[int, int] | None) -> str:
    if not key:
        return "?"
    y, half = key
    return f"WS {y % 100:02d}/{(y + 1) % 100:02d}" if half == 2 else f"SS {y}"


def clean_title(title: str) -> str:
    """Remove leading course numbers and trailing semester labels from a title."""
    t = re.sub(r"^\d{4,8}\s*[–-]\s*", "", title.strip())
    t = re.sub(r"\s*[-–]?\s*\(?\b(WS|SS|WiSe|SoSe)\s*\d{2,4}(\s*/\s*\d{2,4})?\)?\s*$", "", t, flags=re.I)
    return t.strip() or title.strip()


def parse_memberships(page: str) -> list[dict]:
    """Parse the memberships page into de-duplicated {kind, ref, title, semester} items.

    Course and group headings are linked HTML headings, while semester headings are
    unlinked. Initial Tutorium items grouped by parent course have no semester.
    """
    items, seen, sem = [], set(), None
    for m in HEADING.finditer(page):
        inner = m.group(1)
        link = ITEM.search(inner)
        text = strip_tags(inner)
        if link:
            key = (link.group(1), link.group(2))
            if key not in seen and text:
                seen.add(key)
                items.append({"kind": key[0], "ref": int(key[1]), "title": text, "semester": sem})
        elif semester_key(text):
            sem = semester_key(text)
    return items


def course_of_group(il, ref: int, course_refs: set[int]) -> int | None:
    """Open a Tutorium page and find the linked parent course that the user also joined."""
    body = il.page("grp", str(ref))
    for c in re.findall(r"goto\.php/crs/(\d+)", body):
        if int(c) in course_refs:
            return int(c)
    return None


def my_courses(il, look_up_all_groups: bool = False, today: dt.date | None = None) -> list[dict]:
    """Return all courses and Tutorium groups from an authenticated Ilias object.

    By default, resolve parent courses only for current-semester and semesterless
    groups to avoid opening older group pages unnecessarily.
    """
    _, page = il.get(il.base + MEMBERSHIP_URL)
    items = parse_memberships(page)
    now = current_semester(today)
    courses = [i for i in items if i["kind"] == "crs"]
    for c in courses:
        c["name"] = clean_title(c["title"])
        c["current"] = c["semester"] == now
    course_refs = {c["ref"] for c in courses}
    lookups = 0
    for g in (i for i in items if i["kind"] == "grp"):
        g["course"] = None
        if not look_up_all_groups and g["semester"] not in (None, now):
            continue
        if lookups >= MAX_GROUP_LOOKUPS:
            continue
        lookups += 1
        try:
            g["course"] = course_of_group(il, g["ref"], course_refs)
        except Exception:
            pass
    return items


def groups_by_course(items: list[dict]) -> dict[int, list[int]]:
    out: dict[int, list[int]] = {}
    for g in items:
        if g["kind"] == "grp" and g.get("course"):
            out.setdefault(g["course"], []).append(g["ref"])
    return out


def format_courses(items: list[dict], tracked: set[int] = frozenset()) -> str:
    """Format courses by semester, newest first, with Tutorium groups below each course."""
    courses = [i for i in items if i["kind"] == "crs"]
    groups = {g["ref"]: g for g in items if g["kind"] == "grp"}
    by_course = groups_by_course(items)
    sems = sorted({c["semester"] for c in courses}, key=lambda k: k or (0, 0), reverse=True)
    lines = []
    for s in sems:
        cur = any(c.get("current") for c in courses if c["semester"] == s)
        lines.append(f"\n{semester_label(s)}{i18n.tr('ic.current') if cur else ''}")
        for c in (c for c in courses if c["semester"] == s):
            mark = "✓" if c["ref"] in tracked else " "
            lines.append(f"  {mark} {c['name']}   crs {c['ref']}")
            for g in by_course.get(c["ref"], []):
                lines.append(f"      └ {groups[g]['title']}   grp {g}")
    lost = [g for g in groups.values() if not g.get("course")]
    if lost:
        lines.append("\n" + i18n.tr("ic.lost"))
        lines += [f"    {g['title']}   grp {g['ref']}" for g in lost]
    return "\n".join(lines).lstrip("\n")

# ---------------------------------------------------------------- Tracked courses in config.toml

def toml_value(v) -> str:
    """Convert a Python value to TOML; TOML accepts JSON string notation."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(toml_value(x) for x in v) + "]"
    raise TypeError(type(v))


def render_courses(courses: list[dict]) -> str:
    out = []
    for c in courses:
        lines = ["[[ilias.courses]]", f"name = {toml_value(c['name'])}", f"crs = {int(c['crs'])}"]
        if c.get("groups"):
            lines.append(f"groups = {toml_value([int(g) for g in c['groups']])}")
        for k, v in c.items():                         # Preserve other existing settings such as read_pages.
            if k not in ("name", "crs", "groups"):
                lines.append(f"{k} = {toml_value(v)}")
        out.append("\n".join(lines))
    return "\n\n".join(out) + ("\n" if out else "")


def replace_courses(text: str, courses: list[dict]) -> str:
    """Replace every [[ilias.courses]] block while preserving all other config text, including comments."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    block: list[str] | None = None        # Course block currently being skipped.
    insert_at: int | None = None

    def end_block() -> None:
        # Comments and blank lines after a course block belong to the following block, so preserve them.
        keep = []
        while block and (not block[-1].strip() or block[-1].lstrip().startswith("#")):
            keep.insert(0, block.pop())
        out.extend(keep)

    for line in lines:
        s = line.strip()
        if s.startswith("["):
            if block is not None:
                end_block()
                block = None
            if s.replace(" ", "") == "[[ilias.courses]]":
                if insert_at is None:
                    insert_at = len(out)
                block = []
                continue
        if block is not None:
            block.append(line)
        else:
            out.append(line)
    if block is not None:
        end_block()
    new = render_courses(courses)
    if insert_at is None:
        if out and not out[-1].endswith("\n"):
            out.append("\n")
        out.append("\n" + new)
    else:
        out.insert(insert_at, new + ("\n" if courses else ""))
    result = "".join(out)
    result = re.sub(r"\n{3,}", "\n\n", result)
    tomllib.loads(result)                  # Fail here for invalid output before saving it.
    return result


def merge_courses(items: list[dict], existing: dict[int, dict], picked: list[int],
                  names: dict[int, str] | None = None) -> list[dict]:
    """Build [[ilias.courses]] entries for the picked course refs.

    Existing entries keep their short name and other settings (read_pages, ...); Tutorium groups
    come from ILIAS when known. Existing courses keep their order, new ones are appended, so
    saving an unchanged selection leaves config.toml unchanged.
    """
    by_ref = {c["ref"]: c for c in items if c["kind"] == "crs"}
    groups = groups_by_course(items)
    chosen = []
    for ref in picked:
        old = dict(existing.get(ref, {}))
        name = (names or {}).get(ref) or old.get("name") or (by_ref[ref]["name"] if ref in by_ref else str(ref))
        entry = {**old, "name": name, "crs": ref}
        g = groups.get(ref) or old.get("groups") or []
        if g:
            entry["groups"] = g
        else:
            entry.pop("groups", None)
        chosen.append(entry)
    order = list(existing)
    chosen.sort(key=lambda e: order.index(e["crs"]) if e["crs"] in order else len(order))
    return chosen


# ---------------------------------------------------------------- Telegram course menu and notices

def menu_choices(items: list[dict], existing: dict[int, dict]) -> list[dict]:
    """Courses offered in the bot's menu: tracked ones first, then this semester's untracked ones,
    then tracked courses ILIAS no longer lists. Only courses the user joined in ILIAS appear."""
    courses = [c for c in items if c["kind"] == "crs"]
    out, seen = [], set()

    def add(ref: int, name: str, note: str = "") -> None:
        if ref not in seen:
            seen.add(ref)
            out.append({"ref": ref, "name": name, "note": note})
    for ref, e in existing.items():
        c = next((c for c in courses if c["ref"] == ref), None)
        if c:
            add(ref, e.get("name") or c["name"], "" if c.get("current") else semester_label(c["semester"]))
    for c in courses:
        if c.get("current"):
            add(c["ref"], c["name"])
    for ref, e in existing.items():
        add(ref, e.get("name") or str(ref), tr("cs.gone"))
    return out


def semester_news(items: list[dict], tracked: set[int], state: dict,
                  today: dt.date | None = None) -> dict | None:
    """Decide whether to announce a new semester and/or newly joined, untracked courses.

    Updates state in place. Each course is announced once. The first check after installing
    only records what exists, so courses the user deliberately left out are not announced.
    """
    sem = semester_label(current_semester(today))
    fresh = [c for c in items if c["kind"] == "crs" and c.get("current") and c["ref"] not in tracked]
    offered = state.get("courses_offered")
    if offered is None:
        state["courses_offered"] = sorted(c["ref"] for c in fresh)
        state["semester_announced"] = sem
        return None
    new = [c for c in fresh if c["ref"] not in offered]
    new_semester = state.get("semester_announced") != sem
    if not new and not new_semester:
        return None
    state["courses_offered"] = sorted(set(offered) | {c["ref"] for c in new})
    state["semester_announced"] = sem
    return {"semester": sem, "new_semester": new_semester, "courses": [c["name"] for c in new]}


def format_news(news: dict) -> str:
    """Telegram (HTML) text for semester_news(); sent together with open_button()."""
    lines = [tr("cs.new_sem", sem=news["semester"])] if news["new_semester"] else []
    if news["courses"]:
        key = "cs.found" if news["new_semester"] else "cs.found_more"
        lines.append(tr(key, n=len(news["courses"])))
        lines += [f"• {html.escape(n)}" for n in news["courses"]]
        lines.append(tr("cs.pick_hint"))
    else:
        lines.append(tr("cs.join_first"))
    return "\n".join(lines)


def open_button() -> dict:
    return {"inline_keyboard": [[{"text": tr("cs.open"), "callback_data": "crs:open"}]]}


def main() -> int:
    from common import DATA, load_env, secret
    from ilias_sync import Ilias

    ap = argparse.ArgumentParser(description="列出我在 ILIAS 加入的所有课程和 Tutorium（只读）/ "
                                             "alle meine ILIAS-Kurse und Tutorien auflisten (nur lesend)")
    ap.add_argument("--config", default=str(DATA / "config.toml"))
    ap.add_argument("--all", action="store_true",
                    help="往届的 Tutorium 也去找属于哪门课 / auch Tutorien früherer Semester zuordnen")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    load_env(DATA / ".env")
    cfg = tomllib.loads(Path(args.config).read_text(encoding="utf-8"))
    i18n.use(cfg)
    icfg = cfg["ilias"]
    il = Ilias(icfg["user"], secret(icfg["password_env"]))
    items = my_courses(il, look_up_all_groups=args.all)
    tracked = {int(c["crs"]) for c in icfg.get("courses", [])}
    n = sum(1 for i in items if i["kind"] == "crs")
    print(i18n.tr("ic.head", n=n))
    print(format_courses(items, tracked))
    return 0


if __name__ == "__main__":
    sys.exit(main())
