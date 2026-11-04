# Ubuntu VPS 部署与维护

本目录面向新购的 Ubuntu 24.04 VPS。部署结构为：用户通过 HTTPS 访问宿主机 Caddy，Caddy 连接 `127.0.0.1:8080` 的网站容器。Docker 使用 Linux host 网络，后台只监听回环地址；这保证后台实际看到的直连代理就是 `127.0.0.1`。

## 上线前准备

1. 准备自己的 VPS，以及解析到该 VPS 的正式域名。将下文的 `research.your-domain.com` 换成自己的域名。
2. 在云安全组和服务器防火墙允许 TCP 80、443，保留自己的 SSH 入口。无需开放后台 8080 端口。
3. 上传此云端源码包到服务器，例如 `/opt/fundpilot`。不要上传原电脑的整个项目、账号库、Windows 加密密钥或本地 `.env`。
4. 检查服务器时区：`timedatectl`。每日备份使用宿主机时区；如需北京时间，可执行 `sudo timedatectl set-timezone Asia/Shanghai`。研究计划自身按北京时间运行。

现有其他网站的服务器请先人工合并 Caddy 配置。本安装脚本面向新服务器，会备份并替换 `/etc/caddy/Caddyfile`。

## 安装

在解压后的源码根目录执行：

```bash
sudo bash deploy/vps/install-vps.sh research.your-domain.com
```

脚本安装 Docker、Compose、Caddy 和 cron；生成 32 个字符的随机初始化口令；创建持久目录；启动网站；验证并启用 HTTPS 反代；安装每日账号备份。安装中断后可使用相同域名重新执行，已有 `.env`、口令和 Caddy 生成配置会保留。不会自动购买服务器、域名，也不会代改安全组。

配置存于 `deploy/vps/.env`，权限为 `0600`。不要将此文件提交仓库或发到聊天。首次打开自己网站的 `/login.html`，从服务器私下读取初始化口令，创建管理员账号；之后可清空 `.env` 中的 `FUNDPILOT_SETUP_TOKEN` 并重建容器。

安装脚本只确认本机后台健康和 Caddy 配置有效；上线时仍需在外网验证 HTTPS 证书、登录、注册、研究数据来源及备份结果。

## 环境变量与持久数据

| 变量 | 此方案的设置 |
| --- | --- |
| `FUNDPILOT_PUBLIC_URL` | 自己的 HTTPS 域名，不带路径 |
| `FUNDPILOT_STATE_DIR` | 容器内 `/app/data/cloud` |
| `FUNDPILOT_BIND_HOST` | `127.0.0.1` |
| `FUNDPILOT_TRUSTED_PROXIES` | `127.0.0.1/32`；逗号或空白分隔的 IP/CIDR 列表 |
| `FUNDPILOT_SETUP_TOKEN` | 自动生成的独立随机口令，仅用于初始化管理员 |
| `FUNDPILOT_REGISTRATION_OPEN` | `1` 开放注册，`0` 暂停注册 |
| `FUNDPILOT_AI_API_KEY` | 服务商密钥；由服务器环境管理 |
| `FUNDPILOT_AI_BASE_URL` | 服务商确认可用的 HTTPS API 地址 |
| `FUNDPILOT_AI_MODEL` | `gpt-6.1-sol`，须由服务商实际支持 |
| `FUNDPILOT_AI_REASONING_EFFORT` | `medium` 或 `xhigh` |
| `FUNDPILOT_AI_ENABLED` | 初始为 `0`；管理员完成连接核验后再启用 |

宿主机 `/var/lib/fundpilot/data` 挂载到容器 `/app/data`，账号数据库位于 `/var/lib/fundpilot/data/cloud/accounts.sqlite3`。配置、公共报告及其他状态也保存在该持久目录中。容器使用 UID/GID `10001:10001`；安装脚本将宿主机目录及已有文件一并调整属主，避免卷挂载后覆盖镜像内的权限。

更换机器或另建持久目录时，应先创建并设置属主，再启动容器：

```bash
sudo install -d -o 10001 -g 10001 -m 0700 /var/lib/fundpilot/data/cloud
sudo chown -R 10001:10001 /var/lib/fundpilot/data
```

修改 `.env` 后，在 `deploy/vps` 目录执行 `sudo docker compose up -d`，使新环境生效。不要使用 `docker compose config` 无参数输出全部配置，以免在屏幕或日志中展示密钥；检查格式可用 `sudo docker compose config --quiet`。

云端拒绝 HTTP AI 接口。不能仅把旧地址前面的 `http` 改成 `https`；请取得服务商提供的正式 HTTPS 接口并核验证书及模型权限。部署包不包含原电脑的密钥，也不自动进行付费 AI 调用。

## 真实 IP 与限流

- 仅当 TCP 直连来源位于 `FUNDPILOT_TRUSTED_PROXIES` 时，后台才读取唯一一条 `X-Forwarded-For` 请求头的最右一项。
- 客户端自己填写的左侧值全部忽略；末项无效、头部重复或过长时退回直连 IP。直连来源不可信时始终使用连接 IP。
- 未配置可信代理时，默认谁也不信任。不要填互联网全网网段，也不要为方便扩大到所有私网；只填写实际代理地址。
- Caddy 配置另行覆盖客户端传入的 XFF。当前链路只有一个可信代理跳；以后增加 CDN 时，还需要在 Caddy 中配置该 CDN 的可信代理、真实 IP 提取和访问来源限制。不能只添加一个宽泛网段后直接上线。
- 公共认证请求：每 IP 每 10 分钟最多 150 次；已有的用户名登录限流仍保留。
- 注册：每 IP 每小时最多 5 次，并保留全站每小时 200 次兜底。失败的注册尝试也计数；同一出口 IP 的用户共用该 IP 限额。

## 备份和恢复

`/etc/cron.d/fundpilot-backup` 每天宿主机时间 **03:15** 执行在线备份，保留最近 14 天。备份存于 `/var/backups/fundpilot`，日志为 `/var/log/fundpilot-backup.log`，使用 `flock` 防止重复执行。

脚本调用 SQLite 在线备份接口，包含已提交的 WAL 数据，并进行完整性检查；不会直接复制运行中的数据库。手动备份：

```bash
sudo python3 /usr/local/sbin/fundpilot-backup.py
```

账号备份包括数据库中的账号、密码哈希、会话、关注、订阅和额度等记录。它不等于整站备份：公共报告、AI 设置、`.env` 和 Caddy 配置还需另行妥善保存。服务器本地备份不能抵御整机丢失；上线后应再配置独立存储上的备份。

恢复账号库时：先在 `deploy/vps` 运行 `sudo docker compose stop web`，保留当前整个数据目录的副本；确认没有写库进程后，将选定的完整备份替换为 `accounts.sqlite3`，并将旧库对应的 `accounts.sqlite3-wal`、`accounts.sqlite3-shm` 移到留存副本中。设置数据库属主为 `10001:10001`、权限为 `0600`，再运行 `sudo docker compose up -d`。恢复会回退备份之后的账号及额度变化，须核验账号和订阅记录。

## 日常更新

1. 先执行一次在线备份，并保留旧版本源码或镜像。如涉及数据库结构调整，先在备份副本上验证迁移。
2. 更新程序文件，保留原 `deploy/vps/.env`，不要覆盖 `/var/lib/fundpilot/data`。
3. 在 `deploy/vps` 执行 `sudo docker compose up -d --build`。
4. 用 `sudo docker compose ps` 检查状态，核验网站登录、原账号与研究记录；必要时查看 `sudo docker compose logs --tail=100 web`。无需为每次页面更新重装 Caddy 或 cron。

如果更新改过数据库结构，回滚程序前也要评估数据库兼容性；不能仅恢复旧镜像就假定数据可兼容。任何恢复操作都先保留现场数据。
