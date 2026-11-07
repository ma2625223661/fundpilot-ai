# 当前云服务器原生部署运维

本说明适用于 2026 年 11 月 2 日部署的北京服务器 `123.57.33.239`，域名为 `xingyanlab.cn`。此实例实际使用 Python 虚拟环境与 systemd，网站由宿主机 Caddy 提供 HTTPS 反代。

**同目录 README 中的 Docker 更新、重建及恢复命令不适用于当前实例。不要将重新运行 `install-vps.sh` 或 `install-native.sh` 作为日常更新操作。**

## 部署位置

| 项目 | 当前路径或设置 |
| --- | --- |
| 程序源码 | `/opt/fundpilot` |
| Python 虚拟环境 | `/opt/fundpilot/.venv` |
| 网站服务 | `fundpilot.service`，以 `app` 用户运行，UID/GID 为 `10001:10001` |
| 私密环境配置 | `/opt/fundpilot/deploy/vps/.env`，不要打印、上传或纳入代码覆盖 |
| 持久数据 | `/var/lib/fundpilot/data/cloud` |
| 账号数据库 | `/var/lib/fundpilot/data/cloud/accounts.sqlite3` |
| 后台监听 | `127.0.0.1:8080` |
| Caddy 配置 | `/etc/caddy/Caddyfile` |
| 账号备份 | `/var/backups/fundpilot` |

## 2026-11-07 目录调整后第一次更新（只需做一次）

后端代码从项目根目录移到了 `backend/`。服务器上的 systemd 配置是安装时写入的，仍指向旧位置 `/opt/fundpilot/cloud_server.py`；只替换代码而不改这一行，网站会启动失败。更新这一版时：

1. 先按下面"日常更新"第 1 步备份账号数据库。
2. 上传新代码后，删除 `/opt/fundpilot` 根目录下旧的 `server.py`、`cloud_server.py`、`cloud_admin.py`、`launch.py` 和 `research_*.py`，避免新旧两份代码并存。
3. 把服务的启动路径改到 `backend/`，再重启：

   ```bash
   sudo sed -i 's#/opt/fundpilot/cloud_server.py#/opt/fundpilot/backend/cloud_server.py#' /etc/systemd/system/fundpilot.service
   sudo systemctl daemon-reload
   sudo systemctl restart fundpilot
   ```

4. 按"日常更新"最后一步检查服务状态和健康检查。新安装的服务器不需要这一节，`install-native.sh` 已使用新路径。

Docker / Railway 部署不需要手动操作：镜像的启动命令已改为 `backend/cloud_server.py`。

## 日常更新

1. 更新前先备份账号数据库，并保留当前程序版本。涉及数据库结构变化时，先在备份副本上验证迁移。

   ```bash
   sudo python3 /usr/local/sbin/fundpilot-backup.py
   ```

2. 增量替换本次修改的代码文件。保留服务器原有的 `deploy/vps/.env`，不要覆盖或清理 `/var/lib/fundpilot`。不要用本机账号库或 Windows 加密配置覆盖云端数据。

3. 只有 `requirements-cloud.txt` 依赖发生变化时，才更新当前虚拟环境：

   ```bash
   sudo /opt/fundpilot/.venv/bin/pip install -r /opt/fundpilot/requirements-cloud.txt
   ```

4. 原生部署默认仍是旧版页面 `dist/`（Docker 镜像已默认新版）。改用新版 React 界面时，在本机或服务器的 `web/` 目录运行 `npm ci && npm run build`，确认 `/opt/fundpilot/web/dist-react/` 存在后，在 `deploy/vps/.env` 中加一行 `FUNDPILOT_FRONTEND=react`。之后每次更新代码，都要重新构建并同步 `web/dist-react/`；构建产物缺失时网站会拒绝启动，并提示运行 `npm run build`。删除这一行即可回到旧版。

5. 重启网站，使代码或环境配置生效：

   ```bash
   sudo systemctl restart fundpilot
   ```

   只有修改了 systemd unit 文件时，才在重启前执行 `sudo systemctl daemon-reload`。普通网页、程序或 `.env` 更新不需要重装 Caddy、cron，也不需要重跑安装脚本。

6. 检查服务状态、日志及内部 HTTP 响应：

   ```bash
   sudo systemctl status fundpilot --no-pager
   sudo journalctl -u fundpilot -n 50 --no-pager
   curl -fsS -H 'Host: xingyanlab.cn' http://127.0.0.1:8080/api/health
   curl -sS -o /dev/null -w '%{http_code}\n' -H 'Host: xingyanlab.cn' http://127.0.0.1:8080/login.html
   ```

   健康检查应成功，登录页面应返回 `200`。上述检查只证明服务器内部程序可用；正式上线还必须从外网核验域名 HTTPS、登录和真实用户访问。

回滚前需检查旧程序是否兼容当前数据库。恢复数据库会回退备份之后的账号、订阅和额度变化，操作前应保留当前完整数据目录。

## 备份范围

服务器每天北京时间 **03:15** 通过 SQLite 在线备份接口备份账号数据库，保留最近 **14 天**，日志位于 `/var/log/fundpilot-backup.log`。

此备份只覆盖账号数据库中的账号、密码哈希、会话、关注、订阅及额度记录；不包含私密 `.env`、公共研究报告、其他状态文件或 Caddy 配置。它是服务器本地备份，不能代替独立存储上的整站备份。

本机原有账号数据库、订阅额度、研究记录及 AI 凭证尚未迁移到云端。云端 AI 尚未配置启用，部署完成不代表原有账号和 AI 服务已经恢复。

## 当前上线状态

截至 2026 年 11 月 2 日：

- `xingyanlab.cn` 的 DNS 已解析至 `123.57.33.239`。
- HTTPS 证书已签发，服务器内部 HTTPS 登录页面已核验返回 `200`。
- 公网访问仍被阿里云 ICP 备案页面拦截，**目前不能宣布网站已可供其他用户正常使用**。
- 用户已选择先不付款、保留当前部署。续费 3 个月的 **210 元**订单未提交并已取消，当前实例未续费，到期时间为 **2026 年 12 月 2 日 23:59:59**。

