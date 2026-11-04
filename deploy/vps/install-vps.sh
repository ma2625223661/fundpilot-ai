#!/usr/bin/env bash
# Fresh Ubuntu 24.04 VPS only. Run manually on the server after reviewing.
set -euo pipefail
if [[ ${EUID} -ne 0 || $# -ne 1 ]]; then
  echo '用法：sudo bash deploy/vps/install-vps.sh research.your-domain.com' >&2
  exit 1
fi
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
. /etc/os-release
if [[ ${ID} != ubuntu || ${VERSION_ID} != 24.04 ]]; then
  echo '此安装脚本仅适用于全新 Ubuntu 24.04 VPS；其他系统请按部署文档配置。' >&2
  exit 1
fi
apt-get update
apt-get install -y ca-certificates curl gnupg python3 cron util-linux debian-keyring debian-archive-keyring apt-transport-https
# A failed package install can be retried without rotating secrets or losing settings.
python3 "${script_dir}/prepare_env.py" --domain "$1" --reuse-existing
if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
  install -d -m 0755 /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  architecture=$(dpkg --print-architecture)
  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable\n' "$architecture" > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
if ! command -v caddy >/dev/null; then
  curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key -o /tmp/fundpilot-caddy.asc
  gpg --batch --yes --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg /tmp/fundpilot-caddy.asc
  curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt -o /etc/apt/sources.list.d/caddy-stable.list
  chmod a+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list
  apt-get update
  apt-get install -y caddy
fi
# Bind-mount ownership matters: image-layer chown alone cannot fix host files.
install -d -o 10001 -g 10001 -m 0700 /var/lib/fundpilot/data /var/lib/fundpilot/data/cloud
chown -R 10001:10001 /var/lib/fundpilot/data
install -d -m 0700 /var/backups/fundpilot
install -o root -g root -m 0755 "${script_dir}/backup_accounts.py" /usr/local/sbin/fundpilot-backup.py
install -o root -g root -m 0644 "${script_dir}/fundpilot-backup.cron" /etc/cron.d/fundpilot-backup
systemctl enable --now docker cron
cd -- "$script_dir"
docker compose config --quiet
if [[ -f /var/lib/fundpilot/data/cloud/accounts.sqlite3 ]]; then
  /usr/bin/python3 /usr/local/sbin/fundpilot-backup.py
fi
docker compose up -d --build
ready=0
for ((attempt=0; attempt<30; attempt++)); do
  if curl -fsS --max-time 3 http://127.0.0.1:8080/api/health >/dev/null; then
    ready=1
    break
  fi
  sleep 2
done
if [[ ${ready} -ne 1 ]]; then
  echo '后台尚未通过健康检查，请检查 docker compose logs；未替换 Caddy 配置。' >&2
  exit 1
fi
caddy validate --config "${script_dir}/Caddyfile.generated" --adapter caddyfile
if [[ -f /etc/caddy/Caddyfile ]]; then
  cp -p /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.before-fundpilot-$(date +%Y%m%d-%H%M%S)"
fi
install -o root -g caddy -m 0644 "${script_dir}/Caddyfile.generated" /etc/caddy/Caddyfile
systemctl enable --now caddy
systemctl reload caddy
/usr/bin/python3 /usr/local/sbin/fundpilot-backup.py
printf '后台、Caddy 和每日备份已配置。请核验 https://%s/login.html；域名解析与 80/443 端口需已就绪。\n' "$1"
