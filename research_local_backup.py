"""Daily online backups of the local account database (Windows package).

The cloud deployment already backs up with cron (deploy/vps/backup_accounts.py);
the desktop package had none. One consistent SQLite copy per day is kept under
backups/accounts/, newest KEEP_DAYS only. Live sessions keep working: the
SQLite online-backup API copies committed pages without stopping the site.
"""
import sqlite3
import threading
from contextlib import closing
import time
from datetime import datetime
from pathlib import Path

KEEP_DAYS = 14
CHECK_SECONDS = 6 * 3600


def backup_accounts(root, *, keep=KEEP_DAYS, now=None):
    root = Path(root)
    source = root / 'data' / 'accounts.sqlite3'
    if not source.is_file():
        return None
    folder = root / 'backups' / 'accounts'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f'accounts-{(now or datetime.now()):%Y%m%d}.sqlite3'
    created = not target.exists()
    if created:
        partial = target.with_suffix('.partial')
        partial.unlink(missing_ok=True)
        # closing(): a sqlite3 connection used as a context manager only commits.
        # Both must be closed before the rename (Windows refuses to move open files).
        with closing(sqlite3.connect(f'file:{source.as_posix()}?mode=ro', uri=True)) as src, \
                closing(sqlite3.connect(partial)) as dst:
            src.backup(dst)
            dst.execute('PRAGMA journal_mode=DELETE')  # a single self-contained file, no -wal/-shm
            if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise sqlite3.DatabaseError('backup integrity check failed')
        partial.replace(target)
    for old in sorted(folder.glob('accounts-*.sqlite3'))[:-keep]:
        old.unlink(missing_ok=True)
    return target if created else None


def start_daily_backup(root, *, interval=CHECK_SECONDS, log=print):
    def loop():
        while True:
            try:
                path = backup_accounts(root)
                if path:  # only when today's copy was just made
                    log(f'账号数据库已备份：{path.relative_to(Path(root))}')
            except (OSError, sqlite3.Error) as error:
                log(f'账号数据库备份失败（{type(error).__name__}），网站继续运行；稍后自动重试。')
            time.sleep(interval)
    thread = threading.Thread(target=loop, name='fundpilot-account-backup', daemon=True)
    thread.start()
    return thread
