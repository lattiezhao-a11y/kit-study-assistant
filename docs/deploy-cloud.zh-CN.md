# 用 Docker 部署到云服务器

[English](deploy-cloud.md) · **中文**

没有树莓派也可以：任何一台一直开着的小 Linux 服务器都行。跟着做大约 30 分钟，从一台空服务器到在 Telegram 里收到第一条消息。

## 1. 准备一台服务器

| 选择 | 花费 | 说明 |
|---|---|---|
| [Oracle Cloud 免费版](https://www.oracle.com/cloud/free/) | 免费 | 有"永久免费"的虚拟机。注册要绑信用卡；免费的 Arm 机器有时显示"没有空位"（out of capacity），可以过一会儿再试，或者改用小的免费 AMD 机器 |
| [Hetzner Cloud](https://www.hetzner.com/cloud) | 约 4~5 欧/月 | 服务器在德国，开通快，价格以官网为准 |
| 自己的 NAS、家里的服务器、旧笔记本 | 免费 | 能装 Docker、一直开着就行 |

系统选 **Ubuntu 24.04**（或者 Debian），配置选最小的就够（1 GB 内存足够），登录方式选 **SSH 密钥**。

> **你的 KIT 密码会存在这台服务器上。** 只用 SSH 密钥登录，记得更新系统，不要装来路不明的东西，只有你自己能登录。

如果服务器只给了 `root` 账号（Hetzner 就是这样），先建一个普通用户：

```bash
adduser student && usermod -aG sudo student
rsync -a ~/.ssh /home/student/ && chown -R student: /home/student/.ssh
# 退出，然后用新用户重新登录：ssh student@服务器IP
```

建议再开一个防火墙，只放行 SSH：

```bash
sudo apt update && sudo apt install -y ufw
sudo ufw allow OpenSSH && sudo ufw enable
```

机器人不需要开放任何端口，它会自己去 Telegram 取消息。

## 2. 安装 Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# 退出再重新登录，然后检查：
docker compose version
```

## 3. 下载代码，运行安装向导

先准备好：KIT 账号和密码、一个 AI 的 API key（[DeepSeek](https://platform.deepseek.com/api_keys) 很便宜）、
一个 Telegram 机器人的 token（在 Telegram 里找 [@BotFather](https://t.me/BotFather)，发 `/newbot`）。

```bash
git clone https://github.com/lattiezhao-a11y/kit-study-assistant.git
cd kit-study-assistant
mkdir data
docker compose build
docker compose run --rm assistant python3 setup.py
```

向导会登录 ILIAS 列出你的课程，这学期的已经勾好；每个密码填完马上检查；你给机器人发一句话，它就自动找到你的 chat ID。
大约 5 分钟，最后一个问题答完才保存。（想自己手动填：把 `mail_digest/config.example.toml` 复制成 `data/config.toml`，`mail_digest/.env.example` 复制成 `data/.env`。）

属于你自己的东西都在 `data/` 里：设置、密码，以及程序运行时生成的文件（`deadlines.json` 等）。代码文件夹不会被改动，所以更新代码很安全。

## 4. 先试运行（不发任何消息）

```bash
docker compose run --rm assistant python3 digest.py --dry-run --no-llm   # 能不能读到邮件
docker compose run --rm assistant python3 digest.py --dry-run            # 加上 AI 分类
docker compose run --rm assistant python3 ilias_sync.py --dry-run        # ILIAS 截止时间
```

`--dry-run` 只打印，不发 Telegram，也不保存。

## 5. 正式启动

```bash
docker compose up -d
docker compose logs -f      # 看它在做什么（按 Ctrl+C 退出查看，程序不会停）
```

这样就好了。服务器重启后，程序会自动再运行起来。在 Telegram 里给机器人发句话试试。时间表和树莓派版本一样（德国时间）：

| 做什么 | 什么时候 |
|---|---|
| 查邮件 + ILIAS | 01:30、07:30、13:30、19:30（关机错过的，启动后补一次） |
| 早上汇总 | 07:00 |
| 3 小时内截止的提醒 | 07:05~23:05 每小时 |
| 聊天机器人 | 一直在线 |

只想要提醒、不要聊天机器人：把 `docker-compose.yml` 里 `command:` 那一行前面的 `#` 去掉。

## 常用命令

```bash
docker compose logs -f --tail 100                     # 看最近的日志
docker compose restart                                # 改了 data/config.toml 或 data/.env 之后
docker compose run --rm assistant python3 setup.py --courses && docker compose restart   # 新学期：重新选课程
git pull && docker compose up -d --build              # 更新到最新版本
docker compose run --rm assistant python3 tests/run_tests.py --no-llm   # 自检，0 token
docker compose down                                   # 停止
```

备份的话，备份 `data/` 文件夹就够了。

## 常见问题

- **`data/` 里的文件提示 `Permission denied`**：程序在容器里以用户编号 1000 运行。如果你的用户编号不是 1000（用 `id -u` 查看），
  启动时写 `PUID=$(id -u) PGID=$(id -g) docker compose up -d`，或者把这两个值写进 `docker-compose.yml` 旁边的 `.env` 文件。
- **机器人回复两次，或者完全不回复**：同一个 Telegram token 只能有一个机器人在运行。检查它是不是同时还在别的地方（比如树莓派上）运行。
- **ILIAS 登录失败**：运行 `docker compose run --rm assistant python3 ilias_sync.py --dry-run`，看报错信息。如果 KIT 要求两步验证，脚本暂时登不进去。
