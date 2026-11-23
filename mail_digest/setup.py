#!/usr/bin/env python3
"""
安装向导：一问一答，生成 config.toml 和 .env（密码只写进 .env，权限 600）

  python3 setup.py              第一次安装（已经有配置时，会问你：全部重来 / 只改课程 / 取消）
  python3 setup.py --courses    新学期：只重新选课程，别的设置不动
  python3 setup.py --no-check   不联网检查（测试用；课程和 chat ID 要手动输入）

Docker 里：docker compose run --rm assistant python3 setup.py

每填一项就马上检查（登录 KIT 邮箱和 ILIAS、检查 AI 的 key、找到你的 Telegram chat ID），
错了当场改。所有问题都答完才写文件；中途按 Ctrl+C 什么都不会改。
"""
from __future__ import annotations

import argparse
import datetime as dt
import getpass
import imaplib
import json
import os
import re
import shutil
import sys
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

from digest import DATA

HERE = Path(__file__).resolve().parent
CONFIG = DATA / "config.toml"
ENV = DATA / ".env"
BACKUP_DIR = DATA / "backup"
EXAMPLE = HERE / "config.example.toml"
LANGS = {"zh": "中文", "de": "Deutsch"}
LANG = "zh"

# ---------------------------------------------------------------- 文字
# 和 i18n.py 一样的格式：每句话 {"zh": ..., "de": ...}。德语还没写的，先显示中文。
TEXTS: dict[str, dict[str, str]] = {
    "hello": {"zh": "👋 KIT 学习助理 · 安装向导\n"
                    "大约 5 分钟。每一步都会马上检查，全部答完才会写文件；随时按 Ctrl+C 退出，什么都不会改。"},
    "de_soon": {"zh": "Die deutsche Version des Assistenten kommt bald – die Fragen sind vorerst auf Chinesisch.\n"
                      "Der Bot selbst antwortet danach auf Deutsch."},
    "exists": {"zh": "已经有一份设置了（{path}）。要做什么？"},
    "exists.all": {"zh": "全部重新设置（旧文件先备份）"},
    "exists.courses": {"zh": "只重新选课程（新学期）"},
    "exists.cancel": {"zh": "取消"},
    "cancelled": {"zh": "已取消，什么都没改。"},
    "default": {"zh": "（直接回车 = {d}）"},
    "required": {"zh": "这一项必须填。"},
    "yes_no": {"zh": "[Y/n]"},
    "no_yes": {"zh": "[y/N]"},
    "choose": {"zh": "请输入序号："},
    "bad_choice": {"zh": "没看懂，请输入列表里的序号。"},
    "check_ok": {"zh": "  ✅ {what}"},
    "check_fail": {"zh": "  ❌ {what}：{err}"},
    "retry": {"zh": "重新输入？（选 n 就先跳过，以后再改 {file}）"},
    "skip_check": {"zh": "  （--no-check：跳过联网检查）"},

    "s.kit": {"zh": "① KIT 账号"},
    "kit.user": {"zh": "KIT 账号（u 开头，比如 uabcd）："},
    "kit.pw": {"zh": "KIT 密码（输入时不显示）："},
    "kit.login": {"zh": "正在登录 ILIAS，读取你的课程…（大约 10~20 秒）"},
    "kit.ilias_ok": {"zh": "ILIAS 登录成功"},
    "kit.imap_ok": {"zh": "KIT 邮箱登录成功（只读）"},
    "kit.ilias": {"zh": "ILIAS 登录"},
    "kit.imap": {"zh": "KIT 邮箱"},

    "s.courses": {"zh": "② 选择要跟踪的课程"},
    "c.current": {"zh": "这学期（{sem}）："},
    "c.older": {"zh": "往届的课："},
    "c.show_older": {"zh": "往届的课还有 {n} 门，要显示吗？"},
    "c.none_current": {"zh": "没找到这学期的课。"},
    "c.pick": {"zh": "要跟踪哪几门？输入序号，用空格分开，比如 1 3 4。"},
    "c.pick_default": {"zh": "直接回车 = 选上面打了 ✓ 的（{list}）；输入 0 = 一门都不选"},
    "c.name": {"zh": "「{title}」的简称（机器人回答时用这个名字）"},
    "c.groups": {"zh": "    └ 你的 Tutorium：{g}"},
    "c.manual": {"zh": "手动输入课程：打开课程页面，网址里 goto.php/crs/ 后面的数字就是课程编号。\n"
                       "输入课程编号，用空格分开（直接回车 = 先不加课程）："},
    "c.manual_name": {"zh": "课程 {crs} 的简称："},
    "c.list_fail": {"zh": "读不到课程列表（{err}），改成手动输入。"},
    "c.chosen": {"zh": "选好了 {n} 门课。"},

    "s.ical": {"zh": "③ ILIAS 日历订阅链接（可以跳过）"},
    "ical.help": {"zh": "有了它，ILIAS 日历里的 Abgabetermin 会直接进提醒。\n"
                        "在 ILIAS：个人桌面 → 日历 → 右上角的「订阅」（Abonnieren）→ 复制链接。"},
    "ical.url": {"zh": "粘贴链接（直接回车 = 跳过）："},
    "ical.bad": {"zh": "这看起来不像 ILIAS 的日历链接（应该以 https:// 开头），已跳过。"},

    "s.gmail": {"zh": "④ Gmail（可以跳过）"},
    "gmail.want": {"zh": "也要整理 Gmail 的邮件吗？"},
    "gmail.help": {"zh": "Gmail 要用「应用专用密码」，不是登录密码：\n"
                         "先在 Google 账号里开两步验证，再打开 https://myaccount.google.com/apppasswords 生成一个。\n"
                         "（Hotmail/Outlook 不能用密码登录了，可以在 Outlook 设置里自动转发到 Gmail。）"},
    "gmail.addr": {"zh": "Gmail 地址："},
    "gmail.pw": {"zh": "应用专用密码（16 个字母，输入时不显示）："},
    "gmail.ok": {"zh": "Gmail 登录成功（只读）"},

    "s.llm": {"zh": "⑤ AI"},
    "llm.help": {"zh": "邮件分类、读 ILIAS 截止时间、聊天都要用 AI。默认用 DeepSeek（便宜），\n"
                       "任何兼容 OpenAI 接口的服务都可以。DeepSeek 的 key：https://platform.deepseek.com/api_keys"},
    "llm.url": {"zh": "接口地址"},
    "llm.model": {"zh": "模型"},
    "llm.key": {"zh": "API key（输入时不显示）："},
    "llm.ok": {"zh": "API key 可以用（检查不花 token）"},
    "llm.check": {"zh": "AI 接口"},

    "s.tg": {"zh": "⑥ Telegram 机器人"},
    "tg.help": {"zh": "在 Telegram 里找 @BotFather，发 /newbot，按提示起名字，最后它会给你一串 token。"},
    "tg.token": {"zh": "机器人 token（输入时不显示）："},
    "tg.ok": {"zh": "找到机器人 @{name}"},
    "tg.check": {"zh": "Telegram token"},
    "tg.send_now": {"zh": "现在打开 Telegram，给 @{name} 随便发一句话（比如「你好」）。我在等…（最多 2 分钟）"},
    "tg.got": {"zh": "收到了！你的 chat ID 是 {id}"},
    "tg.timeout": {"zh": "2 分钟内没收到消息。"},
    "tg.busy": {"zh": "这个机器人已经在别处运行（Telegram 不让两个程序同时收消息），没法自动找 chat ID。"},
    "tg.manual": {"zh": "手动输入 chat ID（给 @userinfobot 发消息可以查到；直接回车 = 先空着）："},

    "s.about": {"zh": "⑦ 介绍一下你自己（可以跳过）"},
    "about.help": {"zh": "一两句话告诉 AI 你关心什么，它分邮件时会参考。"},
    "about.q": {"zh": "你的介绍"},

    "s.write": {"zh": "⑧ 保存"},
    "w.backup": {"zh": "旧文件已备份到 {path}"},
    "w.done": {"zh": "✅ 已保存：\n   {config}\n   {env}（只有你自己能读）"},
    "w.test_msg": {"zh": "要不要现在往 Telegram 发一条测试消息？"},
    "w.test_text": {"zh": "✅ KIT 学习助理设置好了！以后摘要和提醒都会发到这里。"},
    "w.test_ok": {"zh": "  ✅ 发出去了，看看 Telegram"},
    "w.next_docker": {"zh": "下一步：\n"
                            "  docker compose run --rm assistant python3 digest.py --dry-run   试运行，不发任何消息\n"
                            "  docker compose up -d                                            正式启动"},
    "w.next_local": {"zh": "下一步：\n"
                           "  python3 digest.py --dry-run        试运行邮件分类，不发任何消息\n"
                           "  python3 ilias_sync.py --dry-run    试运行 ILIAS 截止时间\n"
                           "  然后按 README 安装 systemd 定时器"},
    "w.courses_done": {"zh": "✅ 课程已更新（{n} 门）。机器人要重启后才认识新课程：\n"
                             "  Docker：docker compose restart    树莓派：sudo systemctl restart bot.service"},
    "w.no_config": {"zh": "还没有 config.toml，请先运行 python3 setup.py 完成安装。"},
}


def tr(key: str, **kw) -> str:
    d = TEXTS[key]
    s = d.get(LANG) or d["zh"]
    return s.format(**kw) if kw else s


# ---------------------------------------------------------------- 输入

def _clean(s: str) -> str:
    return "".join(ch for ch in s if ch >= " " and ch != "\x7f").strip()


def ask(prompt: str, default: str = "", required: bool = False) -> str:
    hint = f" {tr('default', d=default)}" if default else ""
    while True:
        v = _clean(input(f"{prompt}{hint} "))
        if v:
            return v
        if default:
            return default
        if not required:
            return ""
        print(tr("required"))


def ask_secret(prompt: str, required: bool = True) -> str:
    while True:
        # 有终端时不显示输入；没有终端（测试时用管道喂答案）就普通地读
        v = getpass.getpass(prompt + " ") if sys.stdin.isatty() else input(prompt + " ")
        v = _clean(v)
        if v or not required:
            return v
        print(tr("required"))


def yes(prompt: str, default: bool = True) -> bool:
    v = input(f"{prompt} {tr('yes_no' if default else 'no_yes')} ").strip().lower()
    if not v:
        return default
    return v[0] in "yj是好"


def menu(prompt: str, options: list[str]) -> int:
    print(prompt)
    for i, o in enumerate(options, 1):
        print(f"  {i}. {o}")
    while True:
        v = input(tr("choose") + " ").strip()
        if v.isdigit() and 1 <= int(v) <= len(options):
            return int(v) - 1
        print(tr("bad_choice"))


def parse_numbers(text: str, n: int) -> list[int] | None:
    """"1 3, 4" → [1, 3, 4]（从 1 数）；有不在 1..n 里的就返回 None。"""
    parts = [p for p in re.split(r"[\s,，、;]+", text.strip()) if p]
    if not all(p.isdigit() and 1 <= int(p) <= n for p in parts):
        return None
    return list(dict.fromkeys(int(p) for p in parts))


def title(key: str) -> None:
    print(f"\n━━━━ {tr(key)} ━━━━")


# ---------------------------------------------------------------- 联网检查（--no-check 时都不调用）

def check_imap(host: str, user: str, password: str, port: int = 993) -> None:
    conn = imaplib.IMAP4_SSL(host, port, timeout=30)
    try:
        conn.login(user, password)
        typ, _ = conn.select("INBOX", readonly=True)
        if typ != "OK":
            raise RuntimeError("INBOX")
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def check_llm(base_url: str, key: str) -> None:
    """GET /models：只检查 key 对不对，不花 token。"""
    req = urllib.request.Request(base_url.rstrip("/") + "/models",
                                 headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError("key 不对（401）" if e.code == 401 else f"HTTP {e.code}") from None


def tg_call(token: str, method: str, **params) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(params).encode() if params else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
        except Exception:
            body = {}
        return {"ok": False, "error_code": e.code, "description": body.get("description", str(e))}


def extract_chat_id(updates: dict) -> int | None:
    """getUpdates 的结果 → 最近一个私聊消息的 chat ID。"""
    for u in reversed(updates.get("result", [])):
        msg = u.get("message") or u.get("edited_message") or {}
        chat = msg.get("chat") or {}
        if chat.get("type") == "private" and "id" in chat:
            return int(chat["id"])
    return None


def wait_for_chat(token: str, seconds: int = 120) -> int | None:
    """等用户给机器人发消息，返回 chat ID。机器人已经在别处运行时抛 RuntimeError("busy")。"""
    end = time.time() + seconds
    offset = None
    while time.time() < end:
        params = {"timeout": 20, "allowed_updates": ["message"]}
        if offset:
            params["offset"] = offset
        r = tg_call(token, "getUpdates", **params)
        if not r.get("ok"):
            if r.get("error_code") == 409:
                raise RuntimeError("busy")
            raise RuntimeError(r.get("description", "getUpdates"))
        cid = extract_chat_id(r)
        if cid:
            return cid
        if r.get("result"):
            offset = r["result"][-1]["update_id"] + 1
    return None


# ---------------------------------------------------------------- 写配置

def q(v) -> str:
    """Python 值 → TOML 值（JSON 的字符串写法 TOML 也认）。"""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(q(x) for x in v) + "]"
    raise TypeError(type(v))


def render_courses(courses: list[dict]) -> str:
    out = []
    for c in courses:
        lines = ["[[ilias.courses]]", f"name = {q(c['name'])}", f"crs = {int(c['crs'])}"]
        if c.get("groups"):
            lines.append(f"groups = {q([int(g) for g in c['groups']])}")
        for k, v in c.items():                         # 保留旧配置里的其他设置，比如 read_pages
            if k not in ("name", "crs", "groups"):
                lines.append(f"{k} = {q(v)}")
        out.append("\n".join(lines))
    return "\n\n".join(out) + ("\n" if out else "")


def render_config(a: dict, example: dict) -> str:
    """把向导的回答变成 config.toml。没问到的设置用 config.example.toml 里的默认值。"""
    g, llm, ilias = example["general"], example["llm"], example["ilias"]
    accounts = [{"name": "KIT", "host": "imap.kit.edu", "user": a["kit_user"],
                 "password_env": "KIT_PASSWORD"}]
    if a.get("gmail"):
        accounts.append({"name": "Gmail", "host": "imap.gmail.com", "user": a["gmail"],
                         "password_env": "GMAIL_APP_PASSWORD"})
    acc_text = "\n\n".join(
        f"[[accounts]]\nname = {q(x['name'])}\nhost = {q(x['host'])}\nport = 993\n"
        f"user = {q(x['user'])}\npassword_env = {q(x['password_env'])}\nfolder = \"INBOX\"\n"
        f"llm = true                   # false = 这个邮箱的邮件不发给 AI" for x in accounts)
    return f"""# 由安装向导 setup.py 生成（{dt.datetime.now():%Y-%m-%d %H:%M}）。可以直接改；密码不在这里，在 .env 里。
# 新学期重选课程：python3 setup.py --courses

[general]
language = {q(a['language'])}            # 界面语言：zh = 中文，de = 德语
since_days = {q(g.get('since_days', 1))}           # 第一次运行时回看几天
max_per_account = {q(g.get('max_per_account', 100))}
snippet_chars = {q(g.get('snippet_chars', 300))}       # 每封邮件发给 AI 的正文字数上限
send_when_empty = {q(g.get('send_when_empty', False))}

[llm]
enabled = true
base_url = {q(a['llm_url'])}
model = {q(a['llm_model'])}
api_key_env = {q(a['llm_key_env'])}
batch_size = {q(llm.get('batch_size', 40))}
about_me = {q(a['about_me'])}
# 这些邮件一律归为"忽略"（还是会列在摘要最后，邮件也还在邮箱里）
always_ignore = [
{"".join(f"  {q(x)},{chr(10)}" for x in llm.get('always_ignore', []))}]

[job]
job_search = false        # 开始找工作时改成 true，并填写 profile
profile = {q(example.get('job', {}).get('profile', 'Werkstudent'))}

[safety_net]
# 这些发件人的邮件至少是"必须处理"（只会往上调）。按"包含"匹配，不区分大小写。
always_important_senders = []

[telegram]
bot_token_env = "TELEGRAM_BOT_TOKEN"
chat_id_env = "TELEGRAM_CHAT_ID"

{acc_text}

[ilias]
user = {q(a['kit_user'])}
password_env = "KIT_PASSWORD"
ical_url_env = "ILIAS_ICAL_URL"
quiet_hours = {q(ilias.get('quiet_hours', [0, 7]))}       # 这段时间不发 3 天 / 1 天的提醒（3 小时的照发）
skip_folders = {q(ilias.get('skip_folders', ''))}

# 跟踪的课程。crs = 课程编号；groups = 你的 Tutorium；read_pages = false：只看新文件，不读页面文字
{render_courses(a['courses'])}"""


def render_env(v: dict) -> str:
    """没填的也写一行空的（Gmail 除外），以后打开 .env 就知道还差什么。"""
    lines = ["# 由安装向导 setup.py 生成。全是密码：不要发给别人，不要上传。"]
    for k in ("KIT_PASSWORD", "GMAIL_APP_PASSWORD", v.get("_llm_key_env", "DEEPSEEK_API_KEY"),
              "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "ILIAS_ICAL_URL"):
        if k in v or k != "GMAIL_APP_PASSWORD":
            lines.append(f"{k}={v.get(k, '')}")
    return "\n".join(lines) + "\n"


def replace_courses(text: str, courses: list[dict]) -> str:
    """把 config.toml 里所有 [[ilias.courses]] 换成新的，其他内容（包括注释）一字不动。"""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    block: list[str] | None = None        # 正在跳过的课程段
    insert_at: int | None = None

    def end_block() -> None:
        # 课程段末尾的注释和空行，其实是写给下一段的，留下来
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
    tomllib.loads(result)                  # 写坏了就在这里报错，不会保存
    return result


def backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    dst = BACKUP_DIR / f"{path.name}.{dt.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(path, dst)
    return dst


def write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(tmp, 0o600)
    tmp.replace(path)


# ---------------------------------------------------------------- 选课程

def choose_courses(items: list[dict], existing: dict[int, dict]) -> list[dict]:
    """ILIAS 上的课程列表 → 用户选的课程。existing：旧配置里的课（按编号），保留它们的简称和其他设置。"""
    from ilias_courses import groups_by_course, semester_label
    courses = [i for i in items if i["kind"] == "crs"]
    current = [c for c in courses if c.get("current")]
    older = sorted((c for c in courses if not c.get("current")),
                   key=lambda c: c["semester"] or (0, 0), reverse=True)
    shown = list(current)
    if current:
        print(tr("c.current", sem=semester_label(current[0]["semester"])))
    else:
        print(tr("c.none_current"))
    if older and (not current or yes(tr("c.show_older", n=len(older)), default=False)):
        shown += older
    defaults = [i + 1 for i, c in enumerate(shown)
                if (c["ref"] in existing) or (not existing and c.get("current"))]
    for i, c in enumerate(shown, 1):
        if current and i == len(current) + 1:        # 这学期的列完了，下面是往届的
            print(tr("c.older"))
        mark = "✓" if i in defaults else " "
        sem = "" if c.get("current") else f"  [{semester_label(c['semester'])}]"
        print(f"  {i:2}. {mark} {c['name']}{sem}")
    print(tr("c.pick"))
    print(tr("c.pick_default", list=" ".join(map(str, defaults)) or "-"))
    while True:
        v = input("> ").strip()
        if not v:
            picked = defaults
            break
        if v == "0":
            picked = []
            break
        picked = parse_numbers(v, len(shown))
        if picked is not None:
            break
        print(tr("bad_choice"))
    groups = groups_by_course(items)
    group_titles = {g["ref"]: g["title"] for g in items if g["kind"] == "grp"}
    chosen = []
    for i in picked:
        c = shown[i - 1]
        old = dict(existing.get(c["ref"], {}))
        name = ask(tr("c.name", title=c["title"]), default=old.get("name") or c["name"])
        entry = {**old, "name": name, "crs": c["ref"]}
        g = groups.get(c["ref"]) or old.get("groups") or []
        if g:
            entry["groups"] = g
            print(tr("c.groups", g="、".join(group_titles.get(x, str(x)) for x in g)))
        else:
            entry.pop("groups", None)
        chosen.append(entry)
    # 原来就有的课保持原来的顺序，新加的排在后面（什么都没改时文件也不变）
    order = list(existing)
    chosen.sort(key=lambda e: order.index(e["crs"]) if e["crs"] in order else len(order))
    print(tr("c.chosen", n=len(chosen)))
    return chosen


def manual_courses(existing: dict[int, dict]) -> list[dict]:
    v = input(tr("c.manual") + " ").strip()
    out = []
    for p in re.split(r"[\s,，、;]+", v):
        if p.isdigit():
            old = dict(existing.get(int(p), {}))
            name = ask(tr("c.manual_name", crs=p), default=old.get("name", ""), required=True)
            out.append({**old, "name": name, "crs": int(p)})
    return out


def fetch_courses(user: str, password: str) -> list[dict]:
    from ilias_courses import my_courses
    from ilias_sync import Ilias
    return my_courses(Ilias(user, password))


# ---------------------------------------------------------------- 流程

def step_kit(a: dict, env: dict, check: bool) -> list[dict] | None:
    """返回 ILIAS 课程列表（检查失败或 --no-check 时是 None）。"""
    title("s.kit")
    while True:
        a["kit_user"] = ask(tr("kit.user"), default=a.get("kit_user", ""), required=True)
        env["KIT_PASSWORD"] = ask_secret(tr("kit.pw"))
        if not check:
            print(tr("skip_check"))
            return None
        print(tr("kit.login"))
        items, ok = None, True
        try:
            items = fetch_courses(a["kit_user"], env["KIT_PASSWORD"])
            print(tr("check_ok", what=tr("kit.ilias_ok")))
        except Exception as e:
            ok = False
            print(tr("check_fail", what=tr("kit.ilias"), err=e))
        try:
            check_imap("imap.kit.edu", a["kit_user"], env["KIT_PASSWORD"])
            print(tr("check_ok", what=tr("kit.imap_ok")))
        except Exception as e:
            ok = False
            print(tr("check_fail", what=tr("kit.imap"), err=e))
        if ok or not yes(tr("retry", file=".env"), default=True):
            return items


def step_courses(items: list[dict] | None, existing: dict[int, dict]) -> list[dict]:
    title("s.courses")
    if items:
        return choose_courses(items, existing)
    return manual_courses(existing)


def step_ical(env: dict) -> None:
    title("s.ical")
    print(tr("ical.help"))
    url = ask(tr("ical.url"))
    if url and not url.startswith("https://"):
        print(tr("ical.bad"))
        url = ""
    if url:
        env["ILIAS_ICAL_URL"] = url


def step_gmail(a: dict, env: dict, check: bool) -> None:
    title("s.gmail")
    if not yes(tr("gmail.want"), default=False):
        return
    print(tr("gmail.help"))
    while True:
        a["gmail"] = ask(tr("gmail.addr"), default=a.get("gmail", ""), required=True)
        env["GMAIL_APP_PASSWORD"] = ask_secret(tr("gmail.pw")).replace(" ", "")
        if not check:
            print(tr("skip_check"))
            return
        try:
            check_imap("imap.gmail.com", a["gmail"], env["GMAIL_APP_PASSWORD"])
            print(tr("check_ok", what=tr("gmail.ok")))
            return
        except Exception as e:
            print(tr("check_fail", what="Gmail", err=e))
            if not yes(tr("retry", file=".env"), default=True):
                return


def step_llm(a: dict, env: dict, example: dict, check: bool) -> None:
    title("s.llm")
    print(tr("llm.help"))
    a["llm_url"] = ask(tr("llm.url"), default=example["llm"].get("base_url", "https://api.deepseek.com"))
    a["llm_model"] = ask(tr("llm.model"), default=example["llm"].get("model", "deepseek-flash"))
    a["llm_key_env"] = "DEEPSEEK_API_KEY" if "deepseek" in a["llm_url"] else "LLM_API_KEY"
    env["_llm_key_env"] = a["llm_key_env"]
    while True:
        env[a["llm_key_env"]] = ask_secret(tr("llm.key"))
        if not check:
            print(tr("skip_check"))
            return
        try:
            check_llm(a["llm_url"], env[a["llm_key_env"]])
            print(tr("check_ok", what=tr("llm.ok")))
            return
        except Exception as e:
            print(tr("check_fail", what=tr("llm.check"), err=e))
            if not yes(tr("retry", file=".env"), default=True):
                return


def step_telegram(env: dict, check: bool) -> None:
    title("s.tg")
    print(tr("tg.help"))
    while True:
        env["TELEGRAM_BOT_TOKEN"] = ask_secret(tr("tg.token"))
        if not check:
            print(tr("skip_check"))
            break
        r = tg_call(env["TELEGRAM_BOT_TOKEN"], "getMe")
        if r.get("ok"):
            name = r["result"].get("username", "?")
            print(tr("check_ok", what=tr("tg.ok", name=name)))
            print(tr("tg.send_now", name=name))
            try:
                cid = wait_for_chat(env["TELEGRAM_BOT_TOKEN"])
            except RuntimeError as e:
                cid = None
                print(tr("tg.busy") if str(e) == "busy" else tr("check_fail", what="Telegram", err=e))
            if cid:
                print(tr("check_ok", what=tr("tg.got", id=cid)))
                env["TELEGRAM_CHAT_ID"] = str(cid)
                return
            print(tr("tg.timeout"))
            break
        print(tr("check_fail", what=tr("tg.check"), err=r.get("description", "?")))
        if not yes(tr("retry", file=".env"), default=True):
            break
    cid = ask(tr("tg.manual"))
    if cid:
        env["TELEGRAM_CHAT_ID"] = cid


def pick_language() -> str:
    global LANG
    print("请选择语言 / Bitte wähle eine Sprache:")
    codes = list(LANGS)
    for i, c in enumerate(codes, 1):
        print(f"  {i}. {LANGS[c]}")
    while True:
        v = input("> ").strip() or "1"
        if v.isdigit() and 1 <= int(v) <= len(codes):
            lang = codes[int(v) - 1]
            break
    LANG = "zh"          # 向导的德语文字还没写，先用中文；写进 config 的 language 照样是用户选的
    if lang == "de":
        print(tr("de_soon"))
    return lang


def run_full(check: bool) -> int:
    example = tomllib.loads(EXAMPLE.read_text(encoding="utf-8"))
    old = tomllib.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
    existing = {int(c["crs"]): c for c in old.get("ilias", {}).get("courses", [])}
    a: dict = {"language": pick_language(),
               "kit_user": old.get("ilias", {}).get("user", "")}
    env: dict = {}
    print("\n" + tr("hello"))
    items = step_kit(a, env, check)
    a["courses"] = step_courses(items, existing)
    step_ical(env)
    step_gmail(a, env, check)
    step_llm(a, env, example, check)
    step_telegram(env, check)
    title("s.about")
    print(tr("about.help"))
    a["about_me"] = ask(tr("about.q"), default=example["llm"].get("about_me", ""))

    title("s.write")
    text = render_config(a, example)
    tomllib.loads(text)                                      # 生成的文件一定要能读
    for p in (CONFIG, ENV):
        b = backup(p)
        if b:
            print(tr("w.backup", path=b))
    write_private(CONFIG, text)
    write_private(ENV, render_env(env))
    print(tr("w.done", config=CONFIG, env=ENV))
    if check and env.get("TELEGRAM_CHAT_ID") and yes(tr("w.test_msg"), default=True):
        r = tg_call(env["TELEGRAM_BOT_TOKEN"], "sendMessage",
                    chat_id=env["TELEGRAM_CHAT_ID"], text=tr("w.test_text"))
        print(tr("w.test_ok") if r.get("ok") else tr("check_fail", what="Telegram",
                                                      err=r.get("description")))
    print("\n" + tr("w.next_docker" if Path("/.dockerenv").exists() else "w.next_local"))
    return 0


def run_courses(check: bool) -> int:
    global LANG
    if not CONFIG.exists():
        print(tr("w.no_config"))
        return 1
    from digest import load_env, secret
    text = CONFIG.read_text(encoding="utf-8")
    cfg = tomllib.loads(text)
    LANG = "zh"
    load_env(ENV)
    icfg = cfg.get("ilias", {})
    existing = {int(c["crs"]): c for c in icfg.get("courses", [])}
    items = None
    if check:
        print(tr("kit.login"))
        try:
            items = fetch_courses(icfg["user"], secret(icfg.get("password_env", "KIT_PASSWORD")))
        except Exception as e:
            print(tr("c.list_fail", err=e))
    courses = step_courses(items, existing)
    new = replace_courses(text, courses)
    b = backup(CONFIG)
    if b:
        print(tr("w.backup", path=b))
    write_private(CONFIG, new)
    print(tr("w.courses_done", n=len(courses)))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="安装向导：生成 config.toml 和 .env")
    ap.add_argument("--courses", action="store_true", help="新学期：只重新选课程")
    ap.add_argument("--no-check", action="store_true", help="不联网检查（测试用）")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    check = not args.no_check
    try:
        if args.courses:
            return run_courses(check)
        if CONFIG.exists():
            choice = menu(tr("exists", path=CONFIG),
                          [tr("exists.all"), tr("exists.courses"), tr("exists.cancel")])
            if choice == 1:
                return run_courses(check)
            if choice == 2:
                print(tr("cancelled"))
                return 1
        return run_full(check)
    except (KeyboardInterrupt, EOFError):
        print("\n" + tr("cancelled"))
        return 1


if __name__ == "__main__":
    sys.exit(main())
