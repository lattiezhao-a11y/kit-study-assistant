#!/usr/bin/env python3
"""
列出我在 ILIAS 加入的所有课程和 Tutorium（只读，0 token）

  ILIAS 的「Meine Kurse und Gruppen」页面按学期分组列出所有课程和小组，包括往届的。
  Tutorium（grp）在那个页面上不写属于哪门课，所以打开它的页面，看里面链接到哪门课。

用法：
  python3 ilias_courses.py          按学期列出，标出这学期的课、config.toml 里已经在跟踪的课
  python3 ilias_courses.py --all    连往届的 Tutorium 也去找属于哪门课（多打开几个页面）

安装向导 setup.py 和"新学期重选课程"（setup.py --courses）都用这里的函数。
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

MEMBERSHIP_URL = "/ilias.php?baseClass=ilmembershipoverviewgui"
HEADING = re.compile(r"<h[1-6][^>]*>(.*?)</h[1-6]>", re.S)
ITEM = re.compile(r'goto\.php/(crs|grp)/(\d+)')
# 学期标题：WS 26/27、WS 2026/27、SS 2026、SoSe 2026、WiSe 26/27
SEMESTER = re.compile(r"^(WS|SS|WiSe|SoSe)\s*(\d{2}|\d{4})(?:\s*/\s*(\d{2}|\d{4}))?$", re.I)
MAX_GROUP_LOOKUPS = 20     # 最多打开几个 Tutorium 页面去找它属于哪门课


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def semester_key(label: str | None) -> tuple[int, int] | None:
    """学期标题 → (年份, 1=夏季/2=冬季)，可以比较先后。WS 26/27 → (2026, 2)；SS 2026 → (2026, 1)。"""
    m = SEMESTER.match((label or "").strip())
    if not m:
        return None
    year = int(m.group(2))
    year += 2000 if year < 100 else 0
    winter = m.group(1).upper() in ("WS", "WISE")
    return (year, 2 if winter else 1)


def current_semester(today: dt.date | None = None) -> tuple[int, int]:
    """KIT：冬季学期 10 月到 3 月，夏季学期 4 月到 9 月。"""
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
    """去掉前面的课程号（2424502 – ）和后面的学期（WS 26/27、- WS26/27、(SS26)）。"""
    t = re.sub(r"^\d{4,8}\s*[–-]\s*", "", title.strip())
    t = re.sub(r"\s*[-–]?\s*\(?\b(WS|SS|WiSe|SoSe)\s*\d{2,4}(\s*/\s*\d{2,4})?\)?\s*$", "", t, flags=re.I)
    return t.strip() or title.strip()


def parse_memberships(page: str) -> list[dict]:
    """「我的课程和小组」页面 → [{kind, ref, title, semester}]，按页面顺序，去掉重复。

    页面上每门课、每个小组的标题都是一个带链接的 <h…>；学期是不带链接的 <h…>（WS 26/27）。
    最上面一段是"按上级课程分组"的 Tutorium，那时还没出现学期标题，semester 就是 None。
    """
    items, seen, sem = [], set(), None
    for m in HEADING.finditer(page):
        inner = m.group(1)
        link = ITEM.search(inner)
        text = _text(inner)
        if link:
            key = (link.group(1), link.group(2))
            if key not in seen and text:
                seen.add(key)
                items.append({"kind": key[0], "ref": int(key[1]), "title": text, "semester": sem})
        elif semester_key(text):
            sem = semester_key(text)
    return items


def course_of_group(il, ref: int, course_refs: set[int]) -> int | None:
    """打开 Tutorium 的页面，找它链接到的（也是我加入的）课程。"""
    body = il.page("grp", str(ref))
    for c in re.findall(r"goto\.php/crs/(\d+)", body):
        if int(c) in course_refs:
            return int(c)
    return None


def my_courses(il, look_up_all_groups: bool = False, today: dt.date | None = None) -> list[dict]:
    """登录后的 Ilias 对象 → 所有课程和 Tutorium。

    课程：{kind: "crs", ref, title, name（去掉课程号和学期的简称）, semester, current（是不是这学期）}
    小组：{kind: "grp", ref, title, course（属于哪门课的 ref，找不到是 None）}
    默认只给"这学期的课"和"没写学期的"Tutorium 找上级课程，往届的不打开（省时间）。
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
    """按学期（新的在前）列出课程，每门课下面列出它的 Tutorium。"""
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


def main() -> int:
    from digest import DATA, load_env, secret
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
