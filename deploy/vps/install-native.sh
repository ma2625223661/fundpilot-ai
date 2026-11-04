#!/usr/bin/env bash
set -euo pipefail
cd /opt/fundpilot
export DEBIAN_FRONTEND=noninteractive
apt-get install -y python3-venv
python3 -m venv /opt/fundpilot/.venv
/opt/fundpilot/.venv/bin/pip install --timeout 30 -r requirements-cloud.txt
getent group app >/dev/null || groupadd -g 10001 app
id app >/dev/null 2>&1 || useradd -r -u 10001 -g app -d /var/lib/fundpilot -s /usr/sbin/nologin app
install -d -o 10001 -g 10001 -m 0700 /var/lib/fundpilot/data/cloud
python3 - <<'PY'
from pathlib import Path
p=Path('deploy/vps/.env')
s=p.read_text().replace('FUNDPILOT_STATE_DIR=/app/data/cloud','FUNDPILOT_STATE_DIR=/var/lib/fundpilot/data/cloud')
s+='\nPORT=8080\nPYTHONDONTWRITEBYTECODE=1\nPYTHONUNBUFFERED=1\nTZ=Asia/Shanghai\n'
p.write_text(s)
p.chmod(0o600)
PY
cat > /etc/systemd/system/fundpilot.service <<'UNIT'
[Unit]
Description=FundPilot website
After=network-online.target
Wants=network-online.target
[Service]
User=app
Group=app
WorkingDirectory=/opt/fundpilot
EnvironmentFile=/opt/fundpilot/deploy/vps/.env
ExecStart=/opt/fundpilot/.venv/bin/python -B -u /opt/fundpilot/cloud_server.py
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/var/lib/fundpilot
UMask=0077
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now fundpilot
install -o root -g root -m 0755 deploy/vps/backup_accounts.py /usr/local/sbin/fundpilot-backup.py
install -o root -g root -m 0644 deploy/vps/fundpilot-backup.cron /etc/cron.d/fundpilot-backup
install -d -m 0700 /var/backups/fundpilot
systemctl enable --now cron
for i in $(seq 1 20); do
  if curl -fsS --max-time 3 http://127.0.0.1:8080/api/health; then
    /usr/bin/python3 /usr/local/sbin/fundpilot-backup.py
    echo BACKEND_READY
    exit 0
  fi
  sleep 2
done
systemctl status fundpilot --no-pager
exit 1
