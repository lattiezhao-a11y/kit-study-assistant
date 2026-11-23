#!/usr/bin/env python3
"""
安装向导 + 课程列表的测试：不联网、不需要账号、0 token（GitHub Actions 里也跑）

  python3 tests/test_setup.py

测试数据全是编的，不含真实课程编号和人名。
"""
from __future__ import annotations

import datetime as dt
import os
import re
import string
import subprocess
import sys
import tempfile
import tomllib
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import i18n  # noqa: E402
import ilias_courses as ic  # noqa: E402
import setup as wiz  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, info: str = "") -> None:
    results.append((name, bool(ok), info))
    print(f"{'✅' if ok else '❌'} {name}" + (f"  —  {info}" if info and not ok else ""))


# 编的「Meine Kurse und Gruppen」页面：结构和真实页面一样
PAGE = """<html><body><main>
<h2>Meine Kurse und Gruppen</h2>
<h3>1111 – Lineare Algebra</h3>
<h4><a href="https://ilias.example/goto.php/grp/900001">Tutorium 03 - Tutor A</a></h4>
<h3>SS 2026</h3>
<h4><a href="goto.php/crs/500001">1111 – Lineare Algebra I</a></h4>
<h4><a href="goto.php/crs/500002">Kryptographie (SS26)</a></h4>
<h3>Tutoriumsgruppen</h3>
<h4><a href="goto.php/grp/900002">Tutorium - Tutor B</a></h4>
<h3>WS 26/27</h3>
<h4><a href="goto.php/crs/600001">1111 – Lineare Algebra II - WS26/27</a></h4>
<h4><a href="goto.php/crs/600002">2222 – Programmieren WS 26/27</a></h4>
<h4><a href="goto.php/crs/600003">0124500 – Proseminar (Numerik)</a></h4>
<h2>Mehrere Mitgliedschaften beenden</h2>
<h4>1111 – Lineare Algebra II - WS26/27</h4>
</main></body></html>"""

GROUP_PAGES = {"900001": '<a href="goto.php/crs/600001">LA II</a>',
               "900002": '<a href="goto.php/crs/500002">Krypto</a>'}


class FakeIlias:
    base = "https://ilias.example"

    def __init__(self) -> None:
        self.opened: list[str] = []

    def get(self, url: str):
        return url, PAGE

    def page(self, kind: str, ref: str) -> str:
        self.opened.append(ref)
        return GROUP_PAGES.get(ref, "")


def run_wizard(data: Path, answers: list[str], *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(HERE / "setup.py"), "--no-check", *args],
                          input="\n".join(answers) + "\n", capture_output=True, text=True,
                          encoding="utf-8", env={**os.environ, "DATA_DIR": str(data)},
                          cwd=HERE, timeout=60)


def part_courses() -> None:
    print("\n========== 课程列表（ilias_courses.py）==========")
    k = ic.semester_key
    check("学期标题 → 可比较的键",
          k("WS 26/27") == (2026, 2) and k("SS 2026") == (2026, 1) and k("WiSe 2026/27") == (2026, 2)
          and k("SoSe 26") == (2026, 1) and k("Tutoriumsgruppen") is None)
    cs = ic.current_semester
    check("当前学期：11 月 / 2 月是冬季，5 月是夏季",
          cs(dt.date(2026, 11, 23)) == (2026, 2) and cs(dt.date(2027, 2, 1)) == (2026, 2)
          and cs(dt.date(2026, 5, 4)) == (2026, 1) and cs(dt.date(2026, 10, 1)) == (2026, 2))
    check("学期显示", ic.semester_label((2026, 2)) == "WS 26/27" and ic.semester_label((2026, 1)) == "SS 2026")
    cases = {"2424502 – Rechnerorganisation": "Rechnerorganisation",
             "1111 – Lineare Algebra II - WS26/27": "Lineare Algebra II",
             "2222 – Programmieren WS 26/27": "Programmieren",
             "Kryptographie (SS26)": "Kryptographie",
             "0124500 – Proseminar (Numerik)": "Proseminar (Numerik)",
             "Robotics I - Introduction to Robotics": "Robotics I - Introduction to Robotics",
             "Informationssicherheit": "Informationssicherheit"}
    bad = {t: ic.clean_title(t) for t, want in cases.items() if ic.clean_title(t) != want}
    check("课程名去掉课程号和学期", not bad, str(bad))

    items = ic.parse_memberships(PAGE)
    got = [(i["kind"], i["ref"], i["semester"]) for i in items]
    want = [("grp", 900001, None), ("crs", 500001, (2026, 1)), ("crs", 500002, (2026, 1)),
            ("grp", 900002, (2026, 1)), ("crs", 600001, (2026, 2)), ("crs", 600002, (2026, 2)),
            ("crs", 600003, (2026, 2))]
    check("解析页面：按学期分组、不重复、没链接的标题不算", got == want, str(got))

    il = FakeIlias()
    items = ic.my_courses(il, today=dt.date(2026, 11, 23))
    by = {i["ref"]: i for i in items}
    check("这学期的课标出来", [i["ref"] for i in items if i.get("current")] == [600001, 600002, 600003])
    check("Tutorium 找到属于哪门课", by[900001]["course"] == 600001, str(by[900001]))
    check("往届的 Tutorium 默认不打开（省时间）", il.opened == ["900001"] and by[900002]["course"] is None,
          str(il.opened))
    items_all = ic.my_courses(FakeIlias(), look_up_all_groups=True, today=dt.date(2026, 11, 23))
    check("--all 时往届的也找", {i["ref"]: i.get("course") for i in items_all}[900002] == 500002)
    out = ic.format_courses(items, tracked={600001})
    check("列表显示：这学期在最前、✓、Tutorium 挂在课下面",
          out.startswith("WS 26/27（这学期）") and "✓ Lineare Algebra II   crs 600001" in out
          and "└ Tutorium 03 - Tutor A   grp 900001" in out and "Tutorium - Tutor B" in out, out)


def part_pieces() -> None:
    print("\n========== 向导的零件（setup.py）==========")
    check("输入序号", wiz.parse_numbers("1 3, 4，2", 5) == [1, 3, 4, 2]
          and wiz.parse_numbers("1 1", 3) == [1] and wiz.parse_numbers("6", 5) is None
          and wiz.parse_numbers("a", 5) is None)
    upd = {"ok": True, "result": [
        {"update_id": 1, "message": {"chat": {"id": -100, "type": "group"}}},
        {"update_id": 2, "message": {"chat": {"id": 4242, "type": "private"}}},
        {"update_id": 3, "my_chat_member": {}}]}
    check("从 Telegram 回复里找 chat ID（只认私聊）",
          wiz.extract_chat_id(upd) == 4242 and wiz.extract_chat_id({"result": []}) is None)

    example = tomllib.loads(wiz.EXAMPLE.read_text(encoding="utf-8"))
    a = {"language": "de", "kit_user": "uabcd", "gmail": "me@gmail.com",
         "llm_url": "https://api.deepseek.com", "llm_model": "deepseek-flash",
         "llm_key_env": "DEEPSEEK_API_KEY", "about_me": 'Ich mag "Mathe" \\ und 中文',
         "courses": [{"name": "LA II", "crs": 600001, "groups": [900001]},
                     {"name": "Seminar", "crs": 600003, "read_pages": False}]}
    text = wiz.render_config(a, example)
    try:
        cfg = tomllib.loads(text)
        ok = (cfg["general"]["language"] == "de" and cfg["ilias"]["user"] == "uabcd"
              and [x["name"] for x in cfg["accounts"]] == ["KIT", "Gmail"]
              and cfg["accounts"][1]["user"] == "me@gmail.com"
              and cfg["llm"]["about_me"] == a["about_me"]
              and cfg["llm"]["always_ignore"] == example["llm"]["always_ignore"]
              and cfg["ilias"]["skip_folders"] == example["ilias"]["skip_folders"]
              and cfg["ilias"]["courses"] == a["courses"]
              and cfg["telegram"]["chat_id_env"] == "TELEGRAM_CHAT_ID")
        info = ""
    except Exception as e:
        ok, info = False, f"{e}\n{text}"
    check("生成的 config.toml 能读、内容对（引号、反斜杠、中文都没问题）", ok, info)
    a2 = {**a, "gmail": None, "courses": []}
    cfg2 = tomllib.loads(wiz.render_config(a2, example))
    check("不要 Gmail、没有课程也能生成",
          [x["name"] for x in cfg2["accounts"]] == ["KIT"] and "courses" not in cfg2["ilias"])

    env = wiz.render_env({"KIT_PASSWORD": "p", "_llm_key_env": "DEEPSEEK_API_KEY",
                          "DEEPSEEK_API_KEY": "k", "TELEGRAM_BOT_TOKEN": "t"})
    check(".env：填了的写上，没填的留空行，没选 Gmail 就不写",
          "KIT_PASSWORD=p\n" in env and "TELEGRAM_CHAT_ID=\n" in env and "ILIAS_ICAL_URL=\n" in env
          and "GMAIL" not in env and "_llm" not in env, env)

    src = wiz.EXAMPLE.read_text(encoding="utf-8")
    old = tomllib.loads(src)
    new_courses = [{"name": "Neu", "crs": 777}, {"name": "Seminar", "crs": 2345678, "read_pages": False}]
    new = wiz.replace_courses(src, new_courses)
    cfg = tomllib.loads(new)
    same_rest = ({k: v for k, v in cfg.items() if k != "ilias"} == {k: v for k, v in old.items() if k != "ilias"}
                 and {k: v for k, v in cfg["ilias"].items() if k != "courses"}
                 == {k: v for k, v in old["ilias"].items() if k != "courses"})
    check("只换课程：课程换掉，其他设置和手动截止时间一个不变",
          cfg["ilias"]["courses"] == new_courses and same_rest, new)
    headers = [ln for ln in new.splitlines() if ln.strip() == "[[ilias.courses]]"]
    check("只换课程：注释也留着", "# 手动添加的截止时间" in new and "# 这学期的课，每门课一段" in new
          and len(headers) == 2, new)
    empty = tomllib.loads(wiz.replace_courses(src, []))
    check("只换课程：可以清空", "courses" not in empty["ilias"] and empty["ilias"]["manual"] == old["ilias"]["manual"])
    # 选课：用编的回答代替键盘输入
    import builtins
    items = ic.my_courses(FakeIlias(), today=dt.date(2026, 11, 23))
    existing = {600003: {"name": "Seminar", "crs": 600003, "read_pages": False},
                600001: {"name": "LA II", "crs": 600001}}
    answers = iter(["n", "", "", ""])          # 不看往届；回车 = 默认（原来的两门）；简称都用原来的
    real_input, builtins.input = builtins.input, lambda *_: next(answers)
    try:
        chosen = wiz.choose_courses(items, existing)
        answers = iter(["n", "1 2", "", "Prog"])  # 新加一门 600002
        chosen2 = wiz.choose_courses(items, existing)
    finally:
        builtins.input = real_input
    check("选课：直接回车 = 原来那几门，顺序、简称、Tutorium、read_pages 都不变",
          chosen == [{"name": "Seminar", "crs": 600003, "read_pages": False},
                     {"name": "LA II", "crs": 600001, "groups": [900001]}], str(chosen))
    check("选课：新加的课排在原来的后面",
          [c["crs"] for c in chosen2] == [600001, 600002] and chosen2[1]["name"] == "Prog", str(chosen2))

    no_courses = "[ilias]\nuser = \"u\"\n\n[[ilias.manual]]\ncourse = \"X\"\ntitle = \"t\"\ndate = \"2026-12-01\"\ntime = \"\""
    cfg = tomllib.loads(wiz.replace_courses(no_courses, [{"name": "A", "crs": 1}]))
    check("只换课程：原来没有课程也能加", cfg["ilias"]["courses"] == [{"name": "A", "crs": 1}]
          and len(cfg["ilias"]["manual"]) == 1)


def part_flow() -> None:
    print("\n========== 完整走一遍向导（--no-check，用编好的回答）==========")
    with tempfile.TemporaryDirectory() as d:
        data = Path(d)
        answers = ["1",                      # 语言：中文
                   "uabcd", "pw-SECRET-1",   # KIT 账号、密码
                   "600001 600002",          # 手动输入课程编号（--no-check 不读 ILIAS）
                   "LA II", "Prog",          # 简称
                   "",                       # iCal：跳过
                   "n",                      # 不要 Gmail
                   "", "", "sk-SECRET-2",    # AI：地址、模型用默认，key
                   "123:SECRET-3",           # Telegram token
                   "4242",                   # chat ID（--no-check 时手动输入）
                   ""]                       # 自我介绍：默认
        r = run_wizard(data, answers)
        cfg_path, env_path = data / "config.toml", data / ".env"
        ok = r.returncode == 0 and cfg_path.exists() and env_path.exists()
        check("向导跑完，生成 config.toml 和 .env", ok, r.stdout[-800:] + r.stderr[-800:])
        if not ok:
            return
        cfg = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
        env = env_path.read_text(encoding="utf-8")
        check("config.toml 内容对",
              cfg["general"]["language"] == "zh" and cfg["ilias"]["user"] == "uabcd"
              and cfg["ilias"]["courses"] == [{"name": "LA II", "crs": 600001}, {"name": "Prog", "crs": 600002}]
              and cfg["llm"]["model"] == "deepseek-flash" and [a["name"] for a in cfg["accounts"]] == ["KIT"],
              str(cfg.get("ilias")))
        check(".env 内容对", "KIT_PASSWORD=pw-SECRET-1" in env and "DEEPSEEK_API_KEY=sk-SECRET-2" in env
              and "TELEGRAM_BOT_TOKEN=123:SECRET-3" in env and "TELEGRAM_CHAT_ID=4242" in env)
        check("密码没有出现在屏幕上", "SECRET" not in r.stdout + r.stderr)
        if os.name == "posix":
            check(".env 和 config.toml 只有自己能读（600）",
                  (env_path.stat().st_mode & 0o777) == 0o600 and (cfg_path.stat().st_mode & 0o777) == 0o600)

        # 已经有配置：选 3 取消 → 什么都不变
        before = cfg_path.read_text(encoding="utf-8")
        r = run_wizard(data, ["3"])
        check("已有配置时可以取消，文件不变", r.returncode == 1 and cfg_path.read_text(encoding="utf-8") == before)

        # 新学期：--courses，保留旧的简称，加一门新课
        cfg_text = before.replace('name = "Prog"\ncrs = 600002', 'name = "Prog"\ncrs = 600002\nread_pages = false')
        cfg_path.write_text(cfg_text, encoding="utf-8")
        r = run_wizard(data, ["600002 700001", "", "Neu"], "--courses")
        cfg = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
        check("--courses：只换课程，旧课保留简称和 read_pages，其他不变",
              r.returncode == 0
              and cfg["ilias"]["courses"] == [{"name": "Prog", "crs": 600002, "read_pages": False},
                                              {"name": "Neu", "crs": 700001}]
              and cfg["ilias"]["user"] == "uabcd" and cfg["general"]["language"] == "zh",
              r.stdout[-600:] + r.stderr[-600:])
        backups = list((data / "backup").glob("config.toml.*"))
        check("改之前备份了旧的 config.toml", len(backups) >= 1)

        # Ctrl+C / 输入中断：什么都不写
        with tempfile.TemporaryDirectory() as d2:
            r = run_wizard(Path(d2), ["1", "uabcd"])          # 答到一半就没了
            check("中途退出，什么文件都不写", r.returncode == 1 and not list(Path(d2).iterdir()))


CJK = re.compile(r"[一-鿿　-〿！-～]")    # 汉字和中文标点


def part_german() -> None:
    print("\n========== 德语版（每句话都有中文和德语；德语向导里没有中文）==========")
    fields = lambda s: sorted(f for _, f, _, _ in string.Formatter().parse(s) if f)  # noqa: E731
    bad = [k for k, v in i18n.TEXTS.items() if set(v) != {"zh", "de"} or fields(v["zh"]) != fields(v["de"])]
    check("每句话都有中文和德语，占位符一样", not bad, str(bad))
    bad = [k for k, v in i18n.TEXTS.items() if not k.startswith("ai.") and CJK.search(v["de"].replace("中文", ""))]
    check("德语文字里没有中文", not bad, str(bad))
    check("向导和课程列表的文字都在 i18n 里", any(k.startswith("su.") for k in i18n.TEXTS)
          and all(f"ic.{k}" in i18n.TEXTS for k in ("head", "current", "lost")))

    i18n.LANG = "de"
    try:
        items = ic.my_courses(FakeIlias(), look_up_all_groups=True, today=dt.date(2026, 11, 23))
        out = ic.format_courses(items, {600001})
        check("课程列表（德语）", out.startswith("WS 26/27 (dieses Semester)") and not CJK.search(out), out[:200])
    finally:
        i18n.LANG = "zh"

    with tempfile.TemporaryDirectory() as d:
        data = Path(d)
        answers = ["2",                      # 语言：Deutsch
                   "uabcd", "pw-SECRET-1", "600001", "LA II", "", "n",
                   "", "", "sk-SECRET-2", "123:SECRET-3", "4242", ""]
        r = run_wizard(data, answers)
        cfg_path = data / "config.toml"
        ok = r.returncode == 0 and cfg_path.exists()
        check("德语向导跑完", ok, r.stdout[-800:] + r.stderr[-800:])
        if not ok:
            return
        # 选语言那两行本来就是两种语言（"请选择语言 / …"、"1. 中文"），不算
        shown = "\n".join(l for l in r.stdout.splitlines() if i18n.PICK not in l and "中文" not in l)
        check("德语向导：问题都是德语，没有中文", "KIT-Konto" in shown and not CJK.search(shown),
              str(CJK.findall(shown)[:10]) + shown[:300])
        text = cfg_path.read_text(encoding="utf-8")
        cfg = tomllib.loads(text)
        check("德语向导：language = de，config.toml 里的注释、默认介绍、忽略规则都是德语",
              cfg["general"]["language"] == "de" and "# Sprache:" in text and not CJK.search(text)
              and cfg["llm"]["about_me"].startswith("Ich studiere") and len(cfg["llm"]["always_ignore"]) == 3,
              str(CJK.findall(text)[:10]))
        check("德语向导：.env 的说明也是德语", not CJK.search((data / ".env").read_text(encoding="utf-8")))
        r = run_wizard(data, ["600001", ""], "--courses")
        check("--courses：按 config 里的语言（德语）问", r.returncode == 0 and "Kurse aktualisiert" in r.stdout
              and not CJK.search(r.stdout), r.stdout[-400:] + r.stderr[-400:])
        r = run_wizard(data, ["3"])
        check("已有德语配置：菜单也是德语", "Abbrechen" in r.stdout and r.returncode == 1, r.stdout[-300:])


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    for part in (part_courses, part_pieces, part_flow, part_german):
        try:
            part()
        except Exception:
            check(f"{part.__name__} 没崩溃", False, traceback.format_exc())
    bad = [r for r in results if not r[1]]
    print(f"\n========== 结果：{len(results) - len(bad)}/{len(results)} 通过 ==========")
    for name, _, info in bad:
        print(f"❌ {name}\n   {info[:600]}")
    sys.exit(1 if bad else 0)
