#!/usr/bin/env python3
"""
机器人自动测试（在树莓派上运行）：python3 tests/run_tests.py [--no-llm]

所有会写入的东西都用临时文件夹里的【副本】：deadlines.json、config.toml、todos、课表。
真实提醒和设置不会被改，也不发 Telegram。邮件、ILIAS 论坛只读。
  A 部分：直接调用每个工具（0 token）
  B 部分：用一串中文句子测 AI 有没有选对工具（花少量 token）
"""
from __future__ import annotations

import copy
import json
import re
import shutil
import sys
import tempfile
import tomllib
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import digest  # noqa: E402

digest.load_env(HERE / ".env")
import bot  # noqa: E402
import ilias_sync  # noqa: E402
import tools  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="bottest-"))
for f in ("deadlines.json", "config.toml", "ilias_state.json"):
    if (HERE / f).exists():
        shutil.copy2(HERE / f, TMP / f)
ilias_sync.DEADLINES_FILE = TMP / "deadlines.json"
ilias_sync.LOCK_FILE = TMP / "deadlines.lock"
ilias_sync.STATE_FILE = TMP / "ilias_state.json"
tools.TODO_FILE = TMP / "todos.json"
tools.TIMETABLE_FILE = TMP / "timetable.json"
tools.CONFIG_PATH = TMP / "config.toml"
tools.BACKUP_DIR = TMP / "backup"
CFG = tomllib.loads(tools.CONFIG_PATH.read_text(encoding="utf-8"))
tools.CFG.update(CFG)
ORIG_CONFIG = tools.CONFIG_PATH.read_text(encoding="utf-8")

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, info: str = "") -> None:
    results.append((name, bool(ok), info))
    print(f"{'✅' if ok else '❌'} {name}" + (f"  —  {info}" if info and not ok else ""))


def call(name: str, **args) -> str:
    return bot.run_tool(name, json.dumps(args, ensure_ascii=False))


def show(text: str, n: int = 600) -> None:
    print("   " + text[:n].replace("\n", "\n   ") + ("…" if len(text) > n else ""))


# ================================================================ 格式：Markdown → Telegram HTML
from html.parser import HTMLParser  # noqa: E402

ALLOWED = {"b", "i", "s", "code", "pre", "a"}


def valid_html(s: str) -> bool:
    """只用 Telegram 认识的标签，而且每个都正确闭合。"""
    class P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack, self.ok = [], True

        def handle_starttag(self, tag, attrs):
            self.ok &= tag in ALLOWED
            self.stack.append(tag)

        def handle_endtag(self, tag):
            self.ok &= bool(self.stack) and self.stack.pop() == tag
    p = P()
    p.feed(s)
    p.close()
    return p.ok and not p.stack and "<" not in re.sub(r"</?(b|i|s|code|pre|a)\b[^>]*>", "", s)


def part_format() -> None:
    print("\n========== 格式转换（0 token）==========")
    cases = [
        ("**粗体** 和 *斜体*", "<b>粗体</b> 和 <i>斜体</i>"),
        ("## 今天的作业", "<b>今天的作业</b>"),
        ("- 第一条\n* 第二条", "• 第一条\n• 第二条"),
        ("用 `ls -l` 看", "用 <code>ls -l</code> 看"),
        ("```\nif a < b and c > d:\n    **不转换**\n```", "<pre>if a &lt; b and c &gt; d:\n    **不转换**</pre>"),
        ("看 [ILIAS](https://ilias.studium.kit.edu/a?x=1&y=2)",
         '看 <a href="https://ilias.studium.kit.edu/a?x=1&amp;y=2">ILIAS</a>'),
        ("3 < 5 & 7 > 2", "3 &lt; 5 &amp; 7 &gt; 2"),
        ("| 课 | 时间 |\n|---|---|\n| BS | 9:45 |", "课 | 时间\nBS | 9:45"),
        ("2 * 3 * 4 = 24", "2 * 3 * 4 = 24"),
        ("~~取消~~", "<s>取消</s>"),
        ("> 引用的话", "▎ 引用的话"),
        ("1. 第一\n2) 第二\n  20. 二十\n21. 二一", "① 第一\n② 第二\n  ⑳ 二十\n21. 二一"),
        ("截止 11/30 周一 13:15，共 3. 5 分", "截止 11/30 周一 13:15，共 3. 5 分"),
    ]
    for md, want in cases:
        got = bot.md_to_html(md)
        check(f"格式：{md[:25]!r}", got == want and valid_html(got), f"得到 {got!r}，应该是 {want!r}")
    long = "\n".join(f"- 第 {i} 行 **粗体**" for i in range(600))
    parts = bot.split_text(long, 3000)
    check("长消息按行切开，每段都不超长、格式完整",
          len(parts) > 1 and all(len(bot.md_to_html(x)) < 4096 and valid_html(bot.md_to_html(x))
                                 for x in parts))


# ================================================================ A：直接调用工具
def part_a() -> None:
    print("\n========== A：直接调用工具（0 token）==========")
    # O1
    out = call("ddl_list")
    show(out, 400)
    check("ddl_list 列出编号", re.search(r"^#\d+ ", out, re.M))
    with ilias_sync.locked_store(save=False) as store:
        n_active = len(ilias_sync.upcoming(store))
    shown = len(re.findall(r"^#\d+ ", out, re.M))
    hidden = sum(int(n) for n in re.findall(r"(?:还没发布的作业|考试) (\d+) 个", out))
    full = call("ddl_list", all=True)
    check("默认只列已发布的作业，没发布的和考试只说个数",
          shown + hidden == n_active and len(re.findall(r"^#\d+ ", full, re.M)) == n_active, out[-300:])
    week = call("ddl_list", this_week=True)
    sunday = (tools.now().date() + __import__("datetime").timedelta(days=6 - tools.now().weekday()))
    days_in_week = [(int(m), int(d)) for m, d in re.findall(r"— (\d+)/(\d+) 周", week)]
    check("this_week 只到这周日", "这周，到" in week and all(
        (m, d) <= (sunday.month, sunday.day) for m, d in days_in_week), week[:300])
    pub = {"GKI": [1, 2]}
    check("发布判断：有发布日期看日期，没有看 ILIAS 里的编号",
          tools.released({"source": "ilias", "title": "Übung 4", "course": "GKI", "release": "2099-01-01"}, pub) is False
          and tools.released({"source": "ilias", "title": "Übung 3", "course": "GKI", "release": "2000-01-01"}, pub)
          and tools.released({"source": "ilias", "title": "Übung 2 Deadline", "course": "GKI"}, pub)
          and not tools.released({"source": "ilias", "title": "Übung 5 Deadline", "course": "GKI"}, pub)
          and tools.released({"source": "ilias", "title": "Übung 5", "course": "TGI"}, pub)
          and tools.released({"source": "manual", "title": "Blatt 9", "course": "GKI"}, pub))
    out = call("ddl_add", course="Robotics I", title="测试作业", date="2026-12-01", time="10:00")
    m = re.search(r"#(\d+)", out)
    check("ddl_add 新增", out.startswith("已添加") and m, out)
    tid = int(m.group(1)) if m else 0
    check("ddl_add 重复不加", "没有重复添加" in call("ddl_add", course="Robotics I", title="x",
                                                   date="2026-12-01"))
    out = call("ddl_edit", id=tid, date="2026-12-03")
    check("ddl_edit 推迟", "12/3" in out, out)
    with ilias_sync.locked_store() as store:
        again = ilias_sync.merge(store, [{"course": "Robotics I", "title": "测试作业",
                                          "due": "2026-12-01T10:00+01:00", "time_known": True}])
    check("推迟后旧日期不会被 ILIAS 再加回来", not again)
    check("ddl_done 标记交了", "已标记为交了" in call("ddl_done", id=tid))
    check("交了以后不在列表里", f"#{tid} " not in call("ddl_list"))
    check("ddl_done undo 恢复", "已恢复" in call("ddl_done", id=tid, undo=True)
          and f"#{tid} " in call("ddl_list"))
    check("ddl_delete 删除", "已删除" in call("ddl_delete", id=tid) and f"#{tid} " not in call("ddl_list"))
    check("错误编号给出提示", "没有编号" in call("ddl_done", id=99999))
    check("错误日期给出提示", "YYYY-MM-DD" in call("ddl_add", course="a", title="b", date="下周五"))

    # O2
    out = call("todo_add", text="去银行开户", date="2026-11-25", time="10:30")
    check("todo_add", out.startswith("已记下") and "10:30" in out, out)
    import remind
    remind.TODO_FILE = tools.TODO_FILE
    items = remind.todo_items()
    check("有日期的待办会进提醒", len(items) == 1 and items[0]["due"].startswith("2026-11-25T10:30")
          and items[0]["time_known"], str(items))
    check("todo_list", "去银行开户" in call("todo_list"))
    check("todo_done", "已完成" in call("todo_done", id=1) and "去银行" not in call("todo_list"))
    check("todo_delete", "已删除" in call("todo_delete", id=1))

    # O5
    out = call("timetable_add", weekday=1, start="9:45", end="11:15", course="Betriebssysteme",
               kind="讲座", room="HS a.m. Fasanengarten")
    check("timetable_add", "每周一 09:45–11:15" in out, out)
    out = call("schedule", date="2026-11-30", days=2)
    show(out, 500)
    check("schedule 有课表和日期", "11/30 周一" in out and "Betriebssysteme" in out, out)
    check("timetable_list / remove", "课#1" in call("timetable_list")
          and "已从课表删除" in call("timetable_remove", id=1))
    tools.save_json(tools.TODO_FILE, [])
    out = call("schedule")
    check("schedule 今天（读 ILIAS 日历）", "失败" not in out, out)

    # O4
    out = call("settings_show")
    check("settings_show", "always_ignore" in out and "quiet_hours" in out, out)
    n_comments = ORIG_CONFIG.count("#")
    steps = [dict(key="always_ignore", action="add", value="测试规则：所有来自 example.com 的邮件"),
             dict(key="always_important_senders", action="add", value="tutor@kit.edu"),
             dict(key="quiet_hours", action="set", value="23,7"),
             dict(key="forum_hour", action="set", value="7"),
             dict(key="job_search", action="set", value="true")]
    for st in steps:
        out = call("settings_change", **st)
        ok_pending = "还没生效" in out and tools.PENDING.get("settings")
        unchanged = tools.CONFIG_PATH.read_text(encoding="utf-8") == ORIG_CONFIG \
            if st is steps[0] else True
        check(f"settings_change {st['key']} 只是提议", ok_pending and unchanged, out)
        try:
            msg = tools.apply_pending()
            check(f"确认后改好 {st['key']}", msg.startswith("✅"), msg)
        except Exception as e:
            check(f"确认后改好 {st['key']}", False, repr(e))
    new = tomllib.loads(tools.CONFIG_PATH.read_text(encoding="utf-8"))
    exp = copy.deepcopy(CFG)
    exp["llm"]["always_ignore"] = CFG["llm"]["always_ignore"] + ["测试规则：所有来自 example.com 的邮件"]
    exp.setdefault("safety_net", {})["always_important_senders"] = \
        CFG.get("safety_net", {}).get("always_important_senders", []) + ["tutor@kit.edu"]
    exp["ilias"]["quiet_hours"], exp["ilias"]["forum_hour"] = [23, 7], 7
    exp.setdefault("job", {})["job_search"] = True
    check("config.toml 只改了这 5 项", new == exp)
    check("注释都还在", tools.CONFIG_PATH.read_text(encoding="utf-8").count("#") >= n_comments)
    check("每次改动前都有备份", len(list(tools.BACKUP_DIR.glob("config.toml.*"))) >= 1)
    # 再改回去
    for st in [dict(key="always_ignore", action="remove", value=str(len(exp["llm"]["always_ignore"]))),
               dict(key="always_important_senders", action="remove", value="tutor@kit.edu"),
               dict(key="quiet_hours", action="set", value="0,7"),
               dict(key="forum_hour", action="set", value=str(CFG["ilias"].get("forum_hour", 19))),
               dict(key="job_search", action="set", value="false")]:
        call("settings_change", **st)
        if tools.PENDING.get("settings"):
            tools.apply_pending()
    back = tomllib.loads(tools.CONFIG_PATH.read_text(encoding="utf-8"))
    check("改回去以后和原来的设置一样", all(
        back.get(s, {}).get(k) == CFG.get(s, {}).get(k)
        for k, (s, *_) in tools.SETTINGS.items() if k in CFG.get(s, {})))
    check("不能改的设置被拒绝", "工具出错" in call("settings_change", key="password", action="set", value="x"))
    tools.CONFIG_PATH.write_text(ORIG_CONFIG, encoding="utf-8")
    tools.CFG.clear(), tools.CFG.update(CFG)

    # about_me：一行一行加 / 删（「不感兴趣：…」就是从这里学进去的）
    old_me = CFG["llm"].get("about_me", "")
    out = call("settings_change", key="about_me", action="add", value="不感兴趣：测试用的一类东西")
    pv = tools.PENDING.get("settings", {}).get("preview", "")
    check("about_me add 只是提议，预览里有新的一行和说明",
          "还没生效" in out and "不感兴趣：测试用的一类东西" in pv and "⚪ 忽略" in pv, pv)
    tools.apply_pending()
    me = tomllib.loads(tools.CONFIG_PATH.read_text(encoding="utf-8"))["llm"]["about_me"]
    check("about_me 加在最后一行，原来的内容都还在",
          me.splitlines()[-1] == "不感兴趣：测试用的一类东西" and all(
              ln.strip() in me for ln in old_me.splitlines() if ln.strip()), me)
    check("settings_show 逐行编号显示 about_me", "不感兴趣：测试用的一类东西" in call("settings_show"))
    check("about_me 重复的一行不加", "已经有了" in call(
        "settings_change", key="about_me", action="add", value="不感兴趣：测试用的一类东西"))
    call("settings_change", key="about_me", action="remove", value="测试用的一类")
    tools.apply_pending()
    me = tomllib.loads(tools.CONFIG_PATH.read_text(encoding="utf-8"))["llm"].get("about_me", "")
    check("about_me 按内容删掉一行后和原来一样", tools._lines(me) == tools._lines(old_me), me)
    tools.CONFIG_PATH.write_text(ORIG_CONFIG, encoding="utf-8")
    tools.CFG.clear(), tools.CFG.update(CFG)

    # 删掉从邮件来的提醒 → 提示 AI 提议「不感兴趣」；手动加的不提示
    with ilias_sync.locked_store() as store:
        tools._ensure_ids(store)
        store.append({"course": "📧 测试项目", "title": "测试：跨校短期课程申请",
                      "due": "2099-01-05T00:00+01:00", "time_known": False, "source": "mail"})
        tools._ensure_ids(store)
        mid_ = store[-1]["id"]
    out = call("ddl_delete", id=mid_)
    check("删除邮件来的提醒时提示 AI 学「不感兴趣」", "已删除" in out and "key=about_me" in out, out)
    out = call("ddl_add", course="Robotics I", title="测试作业2", date="2099-01-06")
    out = call("ddl_delete", id=int(re.search(r"#(\d+)", out).group(1)))
    check("删除手动加的不提示", "已删除" in out and "about_me" not in out, out)

    # 邮件分类：义务加提醒，机会不加，about_me 里的「不感兴趣」进提示词
    prompt, _ = digest.build_prompt({"about_me": "我是学生\n不感兴趣：短期交流项目"}, {})
    check("分类提示词里有 about_me 的每一行、不感兴趣规则和 kind",
          "不感兴趣：短期交流项目" in prompt and "一律归为 ignore" in prompt
          and '"kind":"duty|chance"' in prompt, prompt[:300])

    def mk(subject, kind):
        return digest.Mail("KIT", "Test <t@kit.edu>", subject, "", False, True, cat="must",
                           summary=subject, deadline="2099-02-01", kind=kind)
    duty, chance = mk("测试：考试报名", "duty"), mk("测试：交流项目申请", "chance")
    digest.add_mail_deadlines([duty, chance], save=False)
    check("义务的截止日期加进提醒，机会的不加", duty.reminder == "added" and chance.reminder == "chance",
          f"{duty.reminder} / {chance.reminder}")
    text = digest.build_digest([duty, chance], [], 0)
    check("摘要里机会显示「可选，没加提醒」", "已加入提醒" in text and "可选，截止 02-01（没加提醒" in text, text)
    with ilias_sync.locked_store(save=False) as store:
        check("save=False 时没写进 deadlines.json", not any("测试：" in d["title"] and d.get("source") == "mail"
                                                           and not d.get("done") for d in store))

    # O3
    out = call("mail_list", days=2)
    show(out, 700)
    check("mail_list", "最近 2 天" in out and "连接失败" not in out, out)
    mid = re.search(r"^(\w+:\d+) \|", out, re.M)
    if mid:
        out = call("mail_read", id=mid.group(1))
        show(out, 500)
        check("mail_read", out.startswith("发件人："), out)
    else:
        check("mail_read（最近 2 天没有邮件，跳过）", True)
    check("mail_read 格式错误给提示", "格式" in call("mail_read", id="abc"))

    # O6：先在副本里生成论坛列表（真实的会在下次 ILIAS 检查时自动生成）
    state = tools.load_json(ilias_sync.STATE_FILE, {})
    if not state.get("forums"):
        il = tools._ilias()
        il.pages = -400                    # 测试时多给一些页面额度
        fs: dict = {}
        skip = re.compile(CFG["ilias"]["skip_folders"], re.I) if CFG["ilias"].get("skip_folders") else None
        for c in CFG["ilias"]["courses"]:
            ilias_sync.crawl(il, c, copy.deepcopy(state.get("seen", {})), skip, {}, fs)
        state["forums"] = fs
        tools.save_json(ilias_sync.STATE_FILE, state)
        print(f"   （副本里生成了论坛列表：{len(fs)} 个论坛）")
    out = call("forum_recent", days=14)
    show(out, 600)
    check("forum_recent", "工具出错" not in out, out)
    tid = re.search(r"^(\d+/\d+) \|", out, re.M)
    if tid:
        out = call("forum_read", thread=tid.group(1))
        show(out, 500)
        check("forum_read", out.startswith("（以下是论坛原文"), out)


# ================================================================ B：AI 选工具
CASES = [  # (你说的话, 必须用到的工具, 是否接着上一句的对话, 回答里必须有的字)
    ("还有哪些作业没交？", {"ddl_list"}, False, ""),
    ("BS 第三次作业交了", {"ddl_done"}, False, ""),
    ("撤销，刚才那个其实还没交", {"ddl_done"}, True, ""),
    ("TGI 的作业推迟到 12 月 2 号中午 12 点", {"ddl_edit"}, False, ""),
    ("加一个作业：Robotics 第 4 次作业，12 月 5 号 14:00 截止", {"ddl_add"}, False, ""),
    ("删掉刚才加的那个 Robotics 作业", {"ddl_delete"}, True, ""),
    ("这周有哪些作业要交？", {"ddl_list"}, False, ""),
    ("记一下：周三去银行开户", {"todo_add"}, False, ""),
    ("我有哪些待办？", {"todo_list"}, False, ""),
    ("银行那件事办完了", {"todo_done"}, True, ""),
    ("最近两天 KIT 邮箱有什么邮件？", {"mail_list"}, False, ""),
    ("第一封具体写了什么？", {"mail_read"}, True, ""),
    ("帮我回复这封邮件，说我收到了", set(), True, "不"),
    ("周一 9:45 到 11:15 有 BS 讲座，在 HS a.m. Fasanengarten", {"timetable_add"}, False, ""),
    ("下周一有什么安排？", {"schedule"}, False, ""),
    ("GKI 论坛最近在讨论什么？", {"forum_recent"}, False, ""),
    ("以后 Typeless 的邮件都忽略", {"settings_change"}, False, ""),
    ("删掉那个 Summer School 申请的提醒", {"ddl_delete", "settings_change"}, False, ""),
    ("像黑客松这种编程比赛我都不感兴趣，以后别提醒我", {"settings_change"}, False, ""),
    ("把不发提醒的时间改成晚上 23 点到早上 7 点", {"settings_change"}, False, ""),
    ("什么是页表？一句话回答", set(), False, ""),
    ("哪些作业没交", {"ddl_list"}, False, ""),
    ("把全部作业和考试都列出来", {"ddl_list"}, False, ""),
]


def part_b() -> None:
    print("\n========== B：AI 选工具（花 token）==========")
    state = {"usage": {}}
    history: list[dict] = []
    calls: list[tuple[str, dict]] = []          # 记下每次调用工具的参数
    real_run = bot.run_tool

    def traced(name, raw):
        calls.append((name, json.loads(raw or "{}")))
        return real_run(name, raw)
    bot.run_tool = traced
    # 测试从固定状态开始：BS 第三次作业设为"没交"（真实数据里可能已经标记过）
    with ilias_sync.locked_store() as store:
        for d in store:
            if d["course"] == "Betriebssysteme" and "03" in d["title"]:
                for k in ("done", "done_at", "deleted"):
                    d.pop(k, None)
        tools._ensure_ids(store)                # 一个从邮件自动加进来的「机会」，用来测删除时学习
        store.append({"course": "📧 KIT International", "title": "Summer School 2027 申请截止",
                      "due": "2099-03-01T00:00+01:00", "time_known": False, "source": "mail"})
        tools._ensure_ids(store)
    for text, need, keep, must in CASES:
        if not keep:
            history = []
        tools.PENDING.clear()
        used: list[str] = []
        try:
            calls.clear()
            reply = bot.answer(text, history, tools.CFG, state, trace=used)
        except Exception as e:
            traceback.print_exc()
            check(f"「{text}」", False, repr(e))
            continue
        ok = need <= set(used) and (need or not (set(used) - {"ddl_list", "todo_list", "mail_list"}))
        ok = ok and (must in reply)
        ok = ok and valid_html(bot.md_to_html(reply))
        lists = [c for n, c in calls if n == "ddl_list"]
        if text in ("还有哪些作业没交？", "哪些作业没交"):            # 普通问法：不列全部、不限这周
            ok = ok and lists and not any(c.get("all") or c.get("this_week") for c in lists)
        if text == "这周有哪些作业要交？":
            ok = ok and any(c.get("this_week") for c in lists) and not any(c.get("all") for c in lists)
        if text == "把全部作业和考试都列出来":
            ok = ok and any(c.get("all") for c in lists)
        ok = ok and not re.search(r"#\d|KIT:\d|Gmail:\d|\d{6,}/\d{5,}", reply)   # 不显示编号
        if "settings_change" in need:
            ok = ok and bool(tools.PENDING.get("settings")) and \
                tools.CONFIG_PATH.read_text(encoding="utf-8") == ORIG_CONFIG
        if "不感兴趣" in text or "Summer School" in text:   # 学到的东西写进 about_me 的「不感兴趣」
            p = tools.PENDING.get("settings") or {}
            row = (tools._lines(p.get("new", "")) or [""])[-1]
            ok = ok and p.get("key") == "about_me" and row.startswith("不感兴趣")
            show(f"提议加的一行：{row}", 120)
        check(f"「{text}」→ {used or '不用工具'}", ok, f"需要 {need or '不用工具'}；回答：{reply[:200]}")
        show("回答：" + reply, 220)
    u = state["usage"]
    tin = sum(d["in"] for d in u.values())
    tout = sum(d["out"] for d in u.values())
    calls = sum(d["calls"] for d in u.values())
    print(f"\nB 部分共 {calls} 次 AI 调用，{tin + tout:,} token，"
          f"约 ${(tin * bot.PRICE_IN + tout * bot.PRICE_OUT) / 1e6:.3f}")
    check("AI 没有自己改掉设置（真正修改要我回复「确认」）",
          tools.CONFIG_PATH.read_text(encoding="utf-8") == ORIG_CONFIG)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        part_format()
        if "--format-only" not in sys.argv:
            part_a()
            if "--no-llm" not in sys.argv:
                part_b()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    bad = [r for r in results if not r[1]]
    print(f"\n========== 结果：{len(results) - len(bad)}/{len(results)} 通过 ==========")
    for name, _, info in bad:
        print(f"❌ {name}\n   {info[:300]}")
    sys.exit(1 if bad else 0)
