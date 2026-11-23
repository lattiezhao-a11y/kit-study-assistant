"""
界面语言：中文 / 德语

  · 设置在 config.toml 的 [general] language = "zh" 或 "de"（不写就是中文）
  · 在 Telegram 里用 /start、/language 点按钮选，或者直接说"我要用德语版"，马上生效
  · 程序里写死、直接发到 Telegram 的文字都在下面的 TEXTS 里，每句都有中文和德语两个版本
  · AI 写的内容（聊天回答、邮件摘要、论坛总结）靠提示词里的「ai.*」那几句决定语言
  · 发给 AI 的提示词、工具结果保持中文（用户看不到，AI 回答时会翻译）

每个脚本读完 config 后调用 use(cfg)；之后 tr("键") 就会给出当前语言的文字。
"""
from __future__ import annotations

import datetime as dt

LANGS = {"zh": "中文", "de": "Deutsch"}
LANG = "zh"                     # 当前语言（use() 设置）

# 选语言时显示的那句话：还不知道用什么语言，所以两种都写
PICK = "请选择语言 / Bitte wähle eine Sprache:"

WEEKDAYS = {"zh": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"],
            "de": ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]}


def lang_of(cfg: dict) -> str:
    v = str(cfg.get("general", {}).get("language", "zh")).strip().lower()
    return v if v in LANGS else "zh"


def use(cfg: dict) -> str:
    """按 config 设置当前语言，返回语言代码。"""
    global LANG
    LANG = lang_of(cfg)
    return LANG


def tr(key: str, /, **kw) -> str:          # 「/」：文字里也可以有 {key}
    s = TEXTS[key][LANG]
    return s.format(**kw) if kw else s


# ---------------------------------------------------------------- 日期

def weekday(d: dt.date) -> str:
    return WEEKDAYS[LANG][d.weekday()]


def day_label(d: dt.date) -> str:
    """中文 11/30 周一；德语 Mo 30.11."""
    if LANG == "de":
        return f"{weekday(d)} {d.day}.{d.month}."
    return f"{d.month}/{d.day} {weekday(d)}"


def due_label(due: dt.datetime, time_known: bool) -> str:
    """中文 11/30 周一 13:15 / 11/30 周一（没写具体时间）；德语 Mo 30.11. 13:15 / Mo 30.11. (ohne Uhrzeit)"""
    return day_label(due) + (f" {due:%H:%M}" if time_known else tr("no_time"))


def date_text(iso: str, short: bool = False) -> str:
    """YYYY-MM-DD → 显示用。中文保持原样（short：MM-DD）；德语 01.12.2026（short：1.12.）。
    看不懂的（AI 偶尔写错格式）原样返回。"""
    if LANG == "zh":
        return iso[5:] if short else iso
    try:
        d = dt.date.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{d.day}.{d.month}." if short else f"{d.day:02d}.{d.month:02d}.{d.year}"


# ---------------------------------------------------------------- 设置说明（改设置时的预览里显示）
# 中文说明就是 tools.SETTINGS 里的那句，这里只放德语
SETTING_DESC_DE = {
    "always_ignore": "Mails, die immer ignoriert werden (eine Regel pro Zeile)",
    "always_important_senders": "Mails dieser Absender sind mindestens „Zu erledigen“",
    "about_me": "Selbstbeschreibung für die KI, eine Zeile pro Punkt: wer ich bin, was mich interessiert "
                "und was nicht (Mails zu „Kein Interesse: …“ werden ignoriert und nicht erinnert)",
    "job_search": "Suche ich gerade einen Job? (false = Stellenanzeigen werden ignoriert)",
    "quiet_hours": "Von wann bis wann keine dringenden Erinnerungen kommen, z. B. [0, 7]",
    "forum_hour": "Bei welchem Lauf die Forum-Zusammenfassung kommt (1, 7, 13 oder 19 Uhr)",
}


# ---------------------------------------------------------------- 文字

HELP_ZH = """我是你的学习助理 🤖
直接用中文跟我说话就行。

命令：
/language  切换语言（中文 / Deutsch）
/new  清空对话记忆（重新开始）
/usage  看今天和本月花了多少 token
/help  显示这条说明

你可以这样跟我说：
• 作业："还有哪些作业"、"BS 第三次作业交了"、"TGI 作业推迟到周五 12 点"
• 待办："记一下：周三去银行"、"我有哪些待办"
• 邮件（最近 7 天，只读）："今天 KIT 有什么邮件"、"那封 Tutorium 的邮件写了啥"
• 课表："明天有什么课"、"这周的安排"；加课："周一 9:45–11:15 BS 讲座 在 HS a.m. Fasanengarten"
• 论坛："GKI 论坛最近在讨论什么"
• 设置："以后 XX 的邮件都忽略"（我会先给你看改动，你回复「确认」才改）
• 不感兴趣："像 XX 这种我不感兴趣"（记进自我介绍，以后这类邮件不加提醒）"""

HELP_DE = """Ich bin dein Lernassistent 🤖
Schreib mir einfach auf Deutsch.

Befehle:
/language  Sprache wechseln (中文 / Deutsch)
/new  Gesprächsverlauf löschen (neu anfangen)
/usage  Token-Verbrauch heute und in diesem Monat
/help  Diese Hilfe anzeigen

Du kannst mir zum Beispiel schreiben:
• Abgaben: „Welche Abgaben sind noch offen?“, „BS Blatt 3 ist abgegeben“, „TGI-Abgabe auf Freitag 12 Uhr verschieben“
• To-dos: „Merk dir: Mittwoch zur Bank“, „Was steht auf meiner To-do-Liste?“
• Mails (letzte 7 Tage, nur lesen): „Welche KIT-Mails kamen heute?“, „Was steht in der Tutorium-Mail?“
• Stundenplan: „Was habe ich morgen?“, „Was steht diese Woche an?“; Kurs eintragen: „Montag 9:45–11:15 BS Vorlesung im HS a.m. Fasanengarten“
• Forum: „Worüber wird im GKI-Forum gerade diskutiert?“
• Einstellungen: „Mails von XX künftig ignorieren“ (ich zeige dir erst die Änderung, sie gilt erst nach deinem „ja“)
• Kein Interesse: „So etwas wie XX interessiert mich nicht“ (kommt in dein Profil, solche Mails bekommen dann keine Erinnerung mehr)"""

TEXTS: dict[str, dict[str, str]] = {
    # ---- 通用
    "no_time": {"zh": "（没写具体时间）", "de": " (ohne Uhrzeit)"},
    "lang.done": {"zh": "✅ 语言：中文", "de": "✅ Sprache: Deutsch"},
    # 「不感兴趣」这一行的开头：写进 about_me，邮件分类时据此忽略
    "no_interest": {"zh": "不感兴趣：", "de": "Kein Interesse: "},

    # ---- 给 AI 的语言要求（提示词是中文的，只换这几句）
    "ai.reply_rule": {
        "zh": "用中文回答",
        "de": "一律用德语（Deutsch）回答，我用中文说话也用德语答。工具结果大多是中文，转述时翻译成德语；"
              "课程名、ILIAS 作业标题、邮件标题、人名保留原文，以前用中文记下的作业标题、待办内容翻译成德语。"
              "下面规则里的中文例句换成德语说法也一样适用（比如 „alle“ =「全部」，„diese Woche“ =「这周」，"
              "„abgegeben“ =「交了」）",
    },
    "ai.date_example": {"zh": "11/30 周一 13:15", "de": "Mo 30.11. 13:15"},
    "ai.mail_summary": {"zh": "一句中文摘要，不超过40字", "de": "一句德语（Deutsch）摘要，不超过25个词"},
    "ai.forum_summary": {"zh": "用一句中文概括（不超过 40 字）", "de": "用一句德语（Deutsch）概括（不超过 25 个词）"},

    # ---- bot.py
    "bot.help": {"zh": HELP_ZH, "de": HELP_DE},
    "bot.empty": {"zh": "（空回复）", "de": "(leere Antwort)"},
    "bot.today": {"zh": "今天", "de": "Heute"},
    "bot.month": {"zh": "本月", "de": "Dieser Monat"},
    "bot.usage_line": {"zh": "{label}：{tokens:,} token（{calls} 次调用），约 ${cost:.3f}",
                       "de": "{label}: {tokens:,} Token ({calls} Aufrufe), ca. ${cost:.3f}"},
    "bot.usage_note": {"zh": "（只算聊天机器人；邮件、ILIAS 脚本另算）",
                       "de": "(nur der Chatbot; Mail- und ILIAS-Skripte sind nicht mitgezählt)"},
    "bot.too_many_tools": {"zh": "这件事我调用了太多次工具还没弄完，先停下来了。换个说法再试试？",
                           "de": "Dafür habe ich zu viele Werkzeuge gebraucht und abgebrochen. "
                                 "Versuch es bitte anders formuliert."},
    "bot.text_only": {"zh": "目前我只看得懂文字消息。", "de": "Ich verstehe bisher nur Textnachrichten."},
    "bot.new": {"zh": "好，对话记忆清空了，我们重新开始。",
                "de": "Okay, Gesprächsverlauf gelöscht – wir fangen neu an."},
    "bot.not_changed": {"zh": "⚠️ 没改成：{err}（config.toml 没有变）",
                        "de": "⚠️ Nicht geändert: {err} (config.toml ist unverändert)"},
    "bot.pending_cancelled": {"zh": "（刚才那个设置改动已取消，没有修改）",
                              "de": "(Die vorgeschlagene Änderung wurde verworfen, nichts geändert.)"},
    "bot.ai_failed": {"zh": "⚠️ AI 调用失败（HTTP {code}），稍后再试。",
                      "de": "⚠️ KI-Anfrage fehlgeschlagen (HTTP {code}), bitte später nochmal."},
    "bot.error": {"zh": "⚠️ 出错了：{err}", "de": "⚠️ Fehler: {err}"},
    "bot.confirm_hint": {"zh": "回复「确认」生效；回复别的内容就取消（{minutes} 分钟内有效）。",
                         "de": "Antworte mit „ja“, um sie zu übernehmen; jede andere Antwort verwirft sie "
                               "(gültig {minutes} Minuten)."},
    # Telegram 输入框旁边「/」菜单里的命令说明
    "cmd.start": {"zh": "开始 / 选择语言", "de": "Start / Sprache wählen"},
    "cmd.language": {"zh": "切换语言（中文 / Deutsch）", "de": "Sprache wechseln (中文 / Deutsch)"},
    "cmd.new": {"zh": "清空对话记忆", "de": "Gesprächsverlauf löschen"},
    "cmd.usage": {"zh": "今天和本月的 token 用量", "de": "Token-Verbrauch heute / diesen Monat"},
    "cmd.help": {"zh": "使用说明", "de": "Hilfe"},

    # ---- tools.py（改设置：预览和结果由程序直接发出）
    "set.preview": {"zh": "要修改设置「{key}」（{desc}）\n原来：{old}\n改成：{new}",
                    "de": "Einstellung „{key}“ ändern ({desc})\nVorher:{old}\nNachher:{new}"},
    "set.empty": {"zh": " （空）", "de": " (leer)"},
    "set.no_interest_note": {
        "zh": "\n\n以后这类邮件会放进 ⚪ 忽略、不加提醒（摘要底部的「被忽略」列表里还能看到）。",
        "de": "\n\nSolche Mails landen künftig unter ⚪ Ignoriert und bekommen keine Erinnerung "
              "(unten in der Mail-Übersicht weiterhin sichtbar)."},
    "set.done": {"zh": "✅ 设置「{key}」改好了，下次脚本运行时生效。\n改之前的配置备份在 backup/{backup}",
                 "de": "✅ Einstellung „{key}“ geändert, gilt ab dem nächsten Skriptlauf.\n"
                       "Sicherung der alten Konfiguration: backup/{backup}"},
    "set.none_pending": {"zh": "没有等待确认的设置改动。", "de": "Es wartet keine Änderung auf Bestätigung."},
    "set.check_failed": {"zh": "改完检查没通过，没有修改 config.toml",
                         "de": "Prüfung nach der Änderung fehlgeschlagen, config.toml wurde nicht geändert"},

    # ---- digest.py（邮件摘要）
    "cat.must": {"zh": "🔴 必须处理", "de": "🔴 Zu erledigen"},
    "cat.job": {"zh": "💼 求职机会", "de": "💼 Jobangebote"},
    "cat.maybe": {"zh": "🟡 可以看看", "de": "🟡 Lesenswert"},
    "cat.ignore": {"zh": "⚪ 已忽略", "de": "⚪ Ignoriert"},
    "cat.unknown": {"zh": "❔ 未分类", "de": "❔ Nicht eingeordnet"},
    "dg.title": {"zh": "<b>📬 邮件摘要 {date}</b>（共 {n} 封新邮件）",
                 "de": "<b>📬 Mail-Übersicht {date}</b> ({n} neue Mails)"},
    "dg.group": {"zh": "\n<b>{cat}（{n}）</b>", "de": "\n<b>{cat} ({n})</b>"},
    "dg.added": {"zh": "（已加入提醒）", "de": " (zur Erinnerung hinzugefügt)"},
    "dg.dup": {"zh": "（提醒里已有）", "de": " (schon in den Erinnerungen)"},
    "dg.chance": {"zh": " ⏰可选，截止 {date}（没加提醒，想要就跟我说）",
                  "de": " ⏰ optional, Frist {date} (keine Erinnerung – sag Bescheid, wenn du eine willst)"},
    "dg.no_subject": {"zh": "（无标题）", "de": "(kein Betreff)"},
    "dg.ignored_head": {"zh": "\n<b>{cat}（{n}）</b> 邮件都还在邮箱里：",
                        "de": "\n<b>{cat} ({n})</b> – alle Mails sind noch im Postfach:"},
    "dg.ignored_line": {"zh": "· [{acc}] {sender}：{subj}", "de": "· [{acc}] {sender}: {subj}"},
    "dg.more": {"zh": "· ……还有 {n} 封", "de": "· … und {n} weitere"},
    "dg.tokens": {"zh": "\n<i>token 用量：{n:,}</i>", "de": "\n<i>Token-Verbrauch: {n:,}</i>"},
    "dg.read_failed": {"zh": "{acc} 读取失败：{err}", "de": "{acc}: Abruf fehlgeschlagen: {err}"},
    "dg.ai_failed": {"zh": "AI 分类失败：{err}", "de": "KI-Einordnung fehlgeschlagen: {err}"},
    "dg.ddl_failed": {"zh": "截止日期加入提醒失败：{err}",
                      "de": "Fristen konnten nicht in die Erinnerungen übernommen werden: {err}"},
    "dg.user_not_set": {"zh": "config.toml 里这个邮箱的 user 还没改成真实地址",
                        "de": "In config.toml ist für dieses Postfach noch keine echte Adresse (user) eingetragen"},
    "dg.folder": {"zh": "打不开文件夹 {folder}", "de": "Ordner {folder} lässt sich nicht öffnen"},
    "env.missing": {"zh": "缺少环境变量 {name}（写在 .env 里）",
                    "de": "Umgebungsvariable {name} fehlt (gehört in die .env)"},

    # ---- remind.py（早上汇总、3 小时提醒）
    "rm.todo": {"zh": "📝 待办", "de": "📝 To-do"},
    "rm.morning": {"zh": "☀️ <b>近 3 天要做的事</b>", "de": "☀️ <b>Die nächsten 3 Tage</b>"},
    "rm.today": {"zh": "🔴 <b>今天截止</b>", "de": "🔴 <b>Heute fällig</b>"},
    "rm.tomorrow": {"zh": "🟠 <b>明天截止</b>", "de": "🟠 <b>Morgen fällig</b>"},
    "rm.soon": {"zh": "🟡 <b>3 天内</b>", "de": "🟡 <b>In den nächsten 3 Tagen</b>"},
    "rm.urgent": {"zh": "🚨 <b>3 小时内截止</b>", "de": "🚨 <b>In weniger als 3 Stunden fällig</b>"},

    # ---- ilias_sync.py
    "il.passed": {"zh": "已过", "de": "vorbei"},
    "il.hours_left": {"zh": "还剩 {n} 小时", "de": "noch {n} Std."},
    "il.one_day_left": {"zh": "还剩 1 天", "de": "noch 1 Tag"},
    "il.days_left": {"zh": "还剩 {n} 天", "de": "noch {n} Tage"},
    "il.item": {"zh": "• [{course}] <b>{title}</b>\n   ⏰ {due}，{left}",
                "de": "• [{course}] <b>{title}</b>\n   ⏰ {due}, {left}"},
    "il.first": {"zh": "📚 <b>ILIAS 截止时间已开始跟踪</b>（共 {n} 个，请检查有没有漏）",
                 "de": "📚 <b>ILIAS-Fristen werden jetzt verfolgt</b> ({n} insgesamt – bitte prüfen, ob etwas fehlt)"},
    "il.new": {"zh": "📚 <b>ILIAS 新作业 / 截止时间</b>", "de": "📚 <b>Neue ILIAS-Aufgaben / Fristen</b>"},
    "il.footer": {"zh": "<i>截止前 3 天起每天 07:00 提醒，截止前 3 小时再提醒一次（{tokens} token）</i>",
                  "de": "<i>Ab 3 Tagen vor der Frist täglich um 07:00 eine Erinnerung, "
                        "3 Stunden vorher noch einmal ({tokens} Token)</i>"},
    "il.ical_failed": {"zh": "读 ILIAS 日历失败：{err}", "de": "ILIAS-Kalender konnte nicht gelesen werden: {err}"},
    "il.named_err": {"zh": "{name}：{err}", "de": "{name}: {err}"},
    "il.pdf_failed": {"zh": "读 PDF 失败（{where}）：{err}", "de": "PDF konnte nicht gelesen werden ({where}): {err}"},
    "il.forum_failed": {"zh": "论坛总结失败：{err}", "de": "Forum-Zusammenfassung fehlgeschlagen: {err}"},
    "il.ai_failed": {"zh": "AI 提取失败：{err}", "de": "KI-Auswertung fehlgeschlagen: {err}"},
    "il.login_2fa": {"zh": "KIT 登录要求两步验证了，脚本暂时登不进去",
                     "de": "Der KIT-Login verlangt jetzt Zwei-Faktor-Anmeldung, das Skript kommt nicht rein"},
    "il.login_consent": {"zh": "KIT 登录需要先在浏览器里登录一次 ILIAS，确认信息授权页面",
                         "de": "Bitte einmal im Browser bei ILIAS anmelden und die Datenfreigabe bestätigen"},
    "il.login_wrong": {"zh": "ILIAS 登录失败：KIT 用户名或密码不对（.env 里的 KIT_PASSWORD）",
                       "de": "ILIAS-Login fehlgeschlagen: KIT-Benutzername oder Passwort falsch "
                             "(KIT_PASSWORD in der .env)"},
    "il.login_no_saml": {"zh": "ILIAS 登录失败：没收到 KIT 的登录回复，可能登录页面改版了",
                         "de": "ILIAS-Login fehlgeschlagen: keine Antwort vom KIT-Login, "
                               "vielleicht hat sich die Login-Seite geändert"},
    "il.login_not_in": {"zh": "ILIAS 登录后没进到 ILIAS，可能登录流程改版了",
                        "de": "Nach dem Login nicht in ILIAS gelandet, vielleicht hat sich der Ablauf geändert"},
    "il.too_many_pages": {"zh": "一次打开超过 {n} 个页面，已停止（检查 config 里的课程设置）",
                          "de": "Mehr als {n} Seiten auf einmal geöffnet, abgebrochen "
                                "(Kurseinstellungen in der config prüfen)"},

    # ---- forums.py（论坛每日总结）
    "fo.title": {"zh": "💬 <b>ILIAS 论坛今日新帖</b>（{n} 个讨论串）",
                 "de": "💬 <b>Neue Beiträge im ILIAS-Forum heute</b> ({n} Threads)"},
    "fo.thread": {"zh": "• {title}（{n} 个新帖{tag}）", "de": "• {title} ({n} neue Beiträge{tag})"},
    "fo.teacher": {"zh": "，有老师回复", "de": ", mit Antwort von Lehrenden"},
    "fo.tokens": {"zh": "\n<i>论坛总结用了 {n} token</i>", "de": "\n<i>Forum-Zusammenfassung: {n} Token</i>"},
    "fo.forum_err": {"zh": "论坛 {course}：{err}", "de": "Forum {course}: {err}"},
    "fo.thread_err": {"zh": "讨论串「{title}」：{err}", "de": "Thread „{title}“: {err}"},
    "fo.too_many": {"zh": "有新帖的讨论串有 {n} 个，只总结了 {max} 个",
                    "de": "{n} Threads mit neuen Beiträgen, nur {max} davon zusammengefasst"},

    # ---- ilias_courses.py（列出我的课程）
    "ic.head": {"zh": "ILIAS 上你加入了 {n} 门课（✓ = config.toml 里已经在跟踪）：\n",
                "de": "Du bist in ILIAS in {n} Kursen (✓ = wird in config.toml schon verfolgt):\n"},
    "ic.current": {"zh": "（这学期）", "de": " (dieses Semester)"},
    "ic.lost": {"zh": "其他 Tutorium（没找到属于哪门课，或者是往届的）",
                "de": "Weitere Tutorien (Kurs nicht gefunden oder aus früheren Semestern)"},

    # ---- setup.py（安装向导）：在 setup.py 里用 tr("hello") 就是这里的 "su.hello"
    "su.hello": {"zh": "👋 KIT 学习助理 · 安装向导\n"
                       "大约 5 分钟。每一步都会马上检查，全部答完才会写文件；随时按 Ctrl+C 退出，什么都不会改。",
                 "de": "👋 KIT-Lernassistent · Einrichtung\n"
                       "Dauert etwa 5 Minuten. Jeder Schritt wird sofort geprüft, gespeichert wird erst ganz am Ende; "
                       "mit Strg+C kannst du jederzeit abbrechen, dann ändert sich nichts."},
    "su.exists": {"zh": "已经有一份设置了（{path}）。要做什么？",
                  "de": "Es gibt schon eine Einrichtung ({path}). Was möchtest du tun?"},
    "su.exists.all": {"zh": "全部重新设置（旧文件先备份）", "de": "Alles neu einrichten (alte Dateien werden vorher gesichert)"},
    "su.exists.courses": {"zh": "只重新选课程（新学期）", "de": "Nur die Kurse neu wählen (neues Semester)"},
    "su.exists.cancel": {"zh": "取消", "de": "Abbrechen"},
    "su.cancelled": {"zh": "已取消，什么都没改。", "de": "Abgebrochen, nichts wurde geändert."},
    "su.default": {"zh": "（直接回车 = {d}）", "de": "(Enter = {d})"},
    "su.required": {"zh": "这一项必须填。", "de": "Diese Angabe ist Pflicht."},
    "su.yes_no": {"zh": "[Y/n]", "de": "[J/n]"},
    "su.no_yes": {"zh": "[y/N]", "de": "[j/N]"},
    "su.choose": {"zh": "请输入序号：", "de": "Nummer eingeben:"},
    "su.bad_choice": {"zh": "没看懂，请输入列表里的序号。", "de": "Nicht verstanden, bitte eine Nummer aus der Liste eingeben."},
    "su.check_ok": {"zh": "  ✅ {what}", "de": "  ✅ {what}"},
    "su.check_fail": {"zh": "  ❌ {what}：{err}", "de": "  ❌ {what}: {err}"},
    "su.retry": {"zh": "重新输入？（选 n 就先跳过，以后再改 {file}）",
                 "de": "Nochmal eingeben? (n = erst mal überspringen und später in {file} ändern)"},
    "su.skip_check": {"zh": "  （--no-check：跳过联网检查）", "de": "  (--no-check: Online-Prüfung übersprungen)"},

    "su.s.kit": {"zh": "① KIT 账号", "de": "① KIT-Konto"},
    "su.kit.user": {"zh": "KIT 账号（u 开头，比如 uabcd）：", "de": "KIT-Benutzername (beginnt mit u, z. B. uabcd):"},
    "su.kit.pw": {"zh": "KIT 密码（输入时不显示）：", "de": "KIT-Passwort (wird beim Tippen nicht angezeigt):"},
    "su.kit.login": {"zh": "正在登录 ILIAS，读取你的课程…（大约 10~20 秒）",
                     "de": "Melde mich bei ILIAS an und lese deine Kurse … (ca. 10–20 Sekunden)"},
    "su.kit.ilias_ok": {"zh": "ILIAS 登录成功", "de": "ILIAS-Login erfolgreich"},
    "su.kit.imap_ok": {"zh": "KIT 邮箱登录成功（只读）", "de": "KIT-Postfach: Login erfolgreich (nur lesend)"},
    "su.kit.ilias": {"zh": "ILIAS 登录", "de": "ILIAS-Login"},
    "su.kit.imap": {"zh": "KIT 邮箱", "de": "KIT-Postfach"},

    "su.s.courses": {"zh": "② 选择要跟踪的课程", "de": "② Kurse auswählen, die verfolgt werden sollen"},
    "su.c.current": {"zh": "这学期（{sem}）：", "de": "Dieses Semester ({sem}):"},
    "su.c.older": {"zh": "往届的课：", "de": "Frühere Semester:"},
    "su.c.show_older": {"zh": "往届的课还有 {n} 门，要显示吗？",
                        "de": "Es gibt noch {n} Kurse aus früheren Semestern. Anzeigen?"},
    "su.c.none_current": {"zh": "没找到这学期的课。", "de": "Keine Kurse aus diesem Semester gefunden."},
    "su.c.pick": {"zh": "要跟踪哪几门？输入序号，用空格分开，比如 1 3 4。",
                  "de": "Welche Kurse? Nummern mit Leerzeichen getrennt eingeben, z. B. 1 3 4."},
    "su.c.pick_default": {"zh": "直接回车 = 选上面打了 ✓ 的（{list}）；输入 0 = 一门都不选",
                          "de": "Enter = die mit ✓ markierten ({list}); 0 = gar keinen Kurs"},
    "su.c.name": {"zh": "「{title}」的简称（机器人回答时用这个名字）",
                  "de": "Kurzname für „{title}“ (so nennt der Bot den Kurs)"},
    "su.c.groups": {"zh": "    └ 你的 Tutorium：{g}", "de": "    └ Dein Tutorium: {g}"},
    "su.c.sep": {"zh": "、", "de": ", "},
    "su.c.manual": {"zh": "手动输入课程：打开课程页面，网址里 goto.php/crs/ 后面的数字就是课程编号。\n"
                          "输入课程编号，用空格分开（直接回车 = 先不加课程）：",
                    "de": "Kurse von Hand eingeben: Öffne die Kursseite, die Zahl nach goto.php/crs/ in der Adresse "
                          "ist die Kursnummer.\nKursnummern mit Leerzeichen getrennt (Enter = vorerst keine Kurse):"},
    "su.c.manual_name": {"zh": "课程 {crs} 的简称：", "de": "Kurzname für Kurs {crs}:"},
    "su.c.list_fail": {"zh": "读不到课程列表（{err}），改成手动输入。",
                       "de": "Kursliste nicht lesbar ({err}), bitte von Hand eingeben."},
    "su.c.chosen": {"zh": "选好了 {n} 门课。", "de": "{n} Kurse ausgewählt."},

    "su.s.ical": {"zh": "③ ILIAS 日历订阅链接（可以跳过）", "de": "③ ILIAS-Kalender-Abo-Link (optional)"},
    "su.ical.help": {"zh": "有了它，ILIAS 日历里的 Abgabetermin 会直接进提醒。\n"
                           "不填也可以：程序还是会登录 ILIAS，从课程页面和 PDF 里找截止时间。\n"
                           "在 ILIAS：个人桌面 → 日历 → 右上角的「订阅」（Abonnieren）→ 复制链接。",
                     "de": "Damit landen Abgabetermine aus dem ILIAS-Kalender direkt in den Erinnerungen.\n"
                           "Es geht auch ohne: Fristen werden trotzdem nach dem ILIAS-Login aus Kursseiten und PDFs gelesen.\n"
                           "In ILIAS: Dashboard → Kalender → oben rechts „Abonnieren“ → Link kopieren."},
    "su.ical.url": {"zh": "粘贴链接（直接回车 = 跳过）：", "de": "Link einfügen (Enter = überspringen):"},
    "su.ical.bad": {"zh": "这看起来不像 ILIAS 的日历链接（应该以 https:// 开头），已跳过。",
                    "de": "Das sieht nicht nach einem ILIAS-Kalenderlink aus (sollte mit https:// beginnen), übersprungen."},

    "su.s.gmail": {"zh": "④ Gmail（可以跳过）", "de": "④ Gmail (optional)"},
    "su.gmail.want": {"zh": "也要整理 Gmail 的邮件吗？", "de": "Sollen auch Gmail-Mails sortiert werden?"},
    "su.gmail.help": {"zh": "Gmail 要用「应用专用密码」，不是登录密码：\n"
                            "先在 Google 账号里开两步验证，再打开 https://myaccount.google.com/apppasswords 生成一个。\n"
                            "（Hotmail/Outlook 不能用密码登录了，可以在 Outlook 设置里自动转发到 Gmail。）",
                      "de": "Gmail braucht ein App-Passwort, nicht dein normales Passwort:\n"
                            "erst die Bestätigung in zwei Schritten im Google-Konto einschalten, dann unter "
                            "https://myaccount.google.com/apppasswords eines erstellen.\n"
                            "(Hotmail/Outlook erlaubt keinen Passwort-Login mehr; dort in den Outlook-Einstellungen "
                            "eine automatische Weiterleitung an Gmail einrichten.)"},
    "su.gmail.addr": {"zh": "Gmail 地址：", "de": "Gmail-Adresse:"},
    "su.gmail.pw": {"zh": "应用专用密码（16 个字母，输入时不显示）：",
                    "de": "App-Passwort (16 Buchstaben, wird nicht angezeigt):"},
    "su.gmail.ok": {"zh": "Gmail 登录成功（只读）", "de": "Gmail: Login erfolgreich (nur lesend)"},

    "su.s.llm": {"zh": "⑤ AI", "de": "⑤ KI"},
    "su.llm.help": {"zh": "邮件分类、读 ILIAS 截止时间、聊天都要用 AI。默认用 DeepSeek（便宜），\n"
                          "任何兼容 OpenAI 接口的服务都可以。DeepSeek 的 key：https://platform.deepseek.com/api_keys",
                    "de": "Die KI sortiert Mails, liest Fristen aus ILIAS und beantwortet Chatnachrichten. "
                          "Standard ist DeepSeek (günstig),\njeder OpenAI-kompatible Dienst geht auch. "
                          "DeepSeek-Key: https://platform.deepseek.com/api_keys"},
    "su.llm.url": {"zh": "接口地址", "de": "API-Adresse"},
    "su.llm.model": {"zh": "模型", "de": "Modell"},
    "su.llm.key": {"zh": "API key（输入时不显示）：", "de": "API-Key (wird nicht angezeigt):"},
    "su.llm.ok": {"zh": "API key 可以用（检查不花 token）", "de": "API-Key funktioniert (die Prüfung kostet keine Token)"},
    "su.llm.check": {"zh": "AI 接口", "de": "KI-Schnittstelle"},
    "su.llm.bad_key": {"zh": "key 不对（401）", "de": "Key falsch (401)"},

    "su.s.tg": {"zh": "⑥ Telegram 机器人", "de": "⑥ Telegram-Bot"},
    "su.tg.help": {"zh": "在 Telegram 里找 @BotFather，发 /newbot，按提示起名字，最后它会给你一串 token。",
                   "de": "Such in Telegram nach @BotFather, schick /newbot und gib dem Bot einen Namen; "
                         "am Ende bekommst du einen Token."},
    "su.tg.token": {"zh": "机器人 token（输入时不显示）：", "de": "Bot-Token (wird nicht angezeigt):"},
    "su.tg.ok": {"zh": "找到机器人 @{name}", "de": "Bot @{name} gefunden"},
    "su.tg.check": {"zh": "Telegram token", "de": "Telegram-Token"},
    "su.tg.send_now": {"zh": "现在打开 Telegram，给 @{name} 随便发一句话（比如「你好」）。我在等…（最多 2 分钟）",
                       "de": "Öffne jetzt Telegram und schick @{name} irgendeine Nachricht (z. B. „Hallo“). "
                             "Ich warte … (höchstens 2 Minuten)"},
    "su.tg.got": {"zh": "收到了！你的 chat ID 是 {id}", "de": "Angekommen! Deine Chat-ID ist {id}"},
    "su.tg.timeout": {"zh": "2 分钟内没收到消息。", "de": "In 2 Minuten kam keine Nachricht an."},
    "su.tg.busy": {"zh": "这个机器人已经在别处运行（Telegram 不让两个程序同时收消息），没法自动找 chat ID。",
                   "de": "Dieser Bot läuft schon woanders (Telegram lässt nur ein Programm gleichzeitig Nachrichten "
                         "abholen), daher kann ich die Chat-ID nicht automatisch finden."},
    "su.tg.manual": {"zh": "手动输入 chat ID（给 @userinfobot 发消息可以查到；直接回车 = 先空着）：",
                     "de": "Chat-ID von Hand eingeben (verrät dir @userinfobot; Enter = erst mal leer lassen):"},

    "su.s.about": {"zh": "⑦ 介绍一下你自己（可以跳过）", "de": "⑦ Erzähl kurz etwas über dich (optional)"},
    "su.about.help": {"zh": "一两句话告诉 AI 你关心什么，它分邮件时会参考。",
                      "de": "Ein, zwei Sätze für die KI, was dir wichtig ist. Sie berücksichtigt das beim Sortieren der Mails."},
    "su.about.q": {"zh": "你的介绍", "de": "Über dich"},
    "su.about.default": {"zh": "我是 KIT（卡尔斯鲁厄理工学院）的学生。课程、考试、作业截止、注册缴费、签证居留、银行、住房相关的邮件对我重要。",
                         "de": "Ich studiere am KIT (Karlsruher Institut für Technologie). Wichtig sind mir Mails zu "
                               "Lehrveranstaltungen, Prüfungen, Abgabefristen, Rückmeldung und Gebühren, Visum und "
                               "Aufenthalt, Bank und Wohnung."},

    "su.s.write": {"zh": "⑧ 保存", "de": "⑧ Speichern"},
    "su.w.backup": {"zh": "旧文件已备份到 {path}", "de": "Alte Datei gesichert unter {path}"},
    "su.w.done": {"zh": "✅ 已保存：\n   {config}\n   {env}（只有你自己能读）",
                  "de": "✅ Gespeichert:\n   {config}\n   {env} (nur für dich lesbar)"},
    "su.w.test_msg": {"zh": "要不要现在往 Telegram 发一条测试消息？", "de": "Jetzt eine Testnachricht an Telegram schicken?"},
    "su.w.test_text": {"zh": "✅ KIT 学习助理设置好了！以后摘要和提醒都会发到这里。",
                       "de": "✅ Der KIT-Lernassistent ist eingerichtet! Zusammenfassungen und Erinnerungen kommen ab jetzt hierher."},
    "su.w.test_ok": {"zh": "  ✅ 发出去了，看看 Telegram", "de": "  ✅ Gesendet, schau in Telegram nach"},
    "su.w.next_docker": {"zh": "下一步：\n"
                               "  docker compose run --rm assistant python3 digest.py --dry-run   试运行，不发任何消息\n"
                               "  docker compose up -d                                            正式启动",
                         "de": "Nächste Schritte:\n"
                               "  docker compose run --rm assistant python3 digest.py --dry-run   Probelauf, sendet nichts\n"
                               "  docker compose up -d                                            richtig starten"},
    "su.w.next_local": {"zh": "下一步：\n"
                              "  python3 digest.py --dry-run        试运行邮件分类，不发任何消息\n"
                              "  python3 ilias_sync.py --dry-run    试运行 ILIAS 截止时间\n"
                              "  然后按 README 安装 systemd 定时器",
                        "de": "Nächste Schritte:\n"
                              "  python3 digest.py --dry-run        Probelauf Mail-Sortierung, sendet nichts\n"
                              "  python3 ilias_sync.py --dry-run    Probelauf ILIAS-Fristen\n"
                              "  danach die systemd-Timer wie im README beschrieben installieren"},
    "su.w.courses_done": {"zh": "✅ 课程已更新（{n} 门）。机器人要重启后才认识新课程：\n"
                                "  Docker：docker compose restart    树莓派：sudo systemctl restart bot.service",
                          "de": "✅ Kurse aktualisiert ({n}). Der Bot kennt die neuen Kurse erst nach einem Neustart:\n"
                                "  Docker: docker compose restart    Raspberry Pi: sudo systemctl restart bot.service"},
    "su.w.no_config": {"zh": "还没有 config.toml，请先运行 python3 setup.py 完成安装。",
                       "de": "Es gibt noch keine config.toml, bitte zuerst python3 setup.py ausführen."},

    # 向导生成的 config.toml / .env 里的注释
    "su.cfg.head": {"zh": "# 由安装向导 setup.py 生成（{time}）。可以直接改；密码不在这里，在 .env 里。\n"
                          "# 新学期重选课程：python3 setup.py --courses",
                    "de": "# Erstellt vom Einrichtungsassistenten setup.py ({time}). Darf direkt bearbeitet werden; "
                          "Passwörter stehen nicht hier, sondern in .env.\n"
                          "# Neues Semester, Kurse neu wählen: python3 setup.py --courses"},
    "su.cfg.language": {"zh": "# 界面语言：zh = 中文，de = 德语", "de": "# Sprache: zh = Chinesisch, de = Deutsch"},
    "su.cfg.since_days": {"zh": "# 第一次运行时回看几天", "de": "# Wie viele Tage beim ersten Lauf zurückgeschaut wird"},
    "su.cfg.snippet": {"zh": "# 每封邮件发给 AI 的正文字数上限", "de": "# Höchstens so viele Zeichen pro Mail gehen an die KI"},
    "su.cfg.acc_llm": {"zh": "# false = 这个邮箱的邮件不发给 AI", "de": "# false = Mails dieses Postfachs gehen nicht an die KI"},
    "su.cfg.ignore": {"zh": "# 这些邮件一律归为\"忽略\"（还是会列在摘要最后，邮件也还在邮箱里）",
                      "de": "# Diese Mails gelten immer als „Ignoriert“ (stehen trotzdem am Ende der "
                            "Zusammenfassung und bleiben im Postfach)"},
    "su.cfg.ignore_rules": {   # 一行一条，写进 always_ignore
        "zh": "账号安全提醒：新设备登录、密码修改、两步验证、安全警告等（Google、Microsoft 等任何服务）\n"
              "验证码、登录链接、邮箱地址验证（任何 App 或网站，例如 Typeless）\n"
              "订阅类：newsletter、营销订阅、订阅确认、订阅续费提醒。注意：课程、ILIAS、KIT 学校和院系的邮件列表不算订阅，照常判断",
        "de": "Konto-Sicherheitshinweise: Anmeldung auf neuem Gerät, Passwortänderung, Zwei-Faktor-Anmeldung, "
              "Sicherheitswarnungen usw. (Google, Microsoft und jeder andere Dienst)\n"
              "Bestätigungscodes, Login-Links, Bestätigung der E-Mail-Adresse (jede App oder Website, z. B. Typeless)\n"
              "Abos: Newsletter, Werbung, Abo-Bestätigungen, Verlängerungs-Erinnerungen. Achtung: Mailinglisten von "
              "Kursen, ILIAS, KIT und Fakultäten zählen nicht als Abo und werden normal eingeordnet"},
    "su.cfg.job": {"zh": "# 开始找工作时改成 true，并填写 profile",
                   "de": "# Auf true setzen, wenn du einen Job suchst, und profile ausfüllen"},
    "su.cfg.safety": {"zh": "# 这些发件人的邮件至少是\"必须处理\"（只会往上调）。按\"包含\"匹配，不区分大小写。",
                      "de": "# Mails dieser Absender sind mindestens „Zu erledigen“ (wird nur hochgestuft). "
                            "Teilstring-Vergleich, Groß-/Kleinschreibung egal."},
    "su.cfg.quiet": {"zh": "# 这段时间不发 3 天 / 1 天的提醒（3 小时的照发）",
                     "de": "# In dieser Zeit keine 3-Tage-/1-Tag-Erinnerungen (die 3-Stunden-Erinnerung kommt trotzdem)"},
    "su.cfg.courses": {"zh": "# 跟踪的课程。crs = 课程编号；groups = 你的 Tutorium；read_pages = false：只看新文件，不读页面文字",
                       "de": "# Verfolgte Kurse. crs = Kursnummer; groups = deine Tutorien; "
                             "read_pages = false: nur neue Dateien, Seitentext nicht lesen"},
    "su.env.head": {"zh": "# 由安装向导 setup.py 生成。全是密码：不要发给别人，不要上传。",
                    "de": "# Erstellt von setup.py. Alles Passwörter: nicht weitergeben, nicht hochladen."},
}
