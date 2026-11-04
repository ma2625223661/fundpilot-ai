"""Online SQLite snapshots: include committed WAL changes without stopping the site."""
import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time


BACKUP_NAME = re.compile(r'accounts-\d{8}T\d{12}Z\.sqlite3\Z')


def backup_accounts(database, destination, keep_days=14):
    if not 1 <= keep_days <= 3650:
        raise ValueError('保留天数须为 1～3650')
    database = Path(database).resolve(strict=True)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    now = datetime.now(timezone.utc)
    target = destination / ('accounts-' + now.strftime('%Y%m%dT%H%M%S%fZ') + '.sqlite3')
    descriptor, partial = tempfile.mkstemp(prefix='.accounts-', suffix='.partial', dir=destination)
    os.close(descriptor)
    partial = Path(partial)
    deadline = time.monotonic() + 120

    def progress(status, remaining, total):
        if time.monotonic() > deadline:
            raise TimeoutError('在线备份超过两分钟，保留原有备份并等待下次执行')

    try:
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=5)) as source:
            output = sqlite3.connect(partial)
            try:
                source.backup(output, pages=256, progress=progress, sleep=.1)
                if output.execute('PRAGMA integrity_check').fetchone() != ('ok',):
                    raise RuntimeError('备份完整性检查失败')
                # A standalone snapshot never depends on the source WAL file.
                output.execute('PRAGMA journal_mode=DELETE')
                output.commit()
            finally:
                output.close()
        os.chmod(partial, 0o600)
        with partial.open('r+b') as stream:
            os.fsync(stream.fileno())
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    cutoff = now - timedelta(days=keep_days)
    for candidate in destination.iterdir():
        if (candidate == target or candidate.is_symlink() or not candidate.is_file()
                or not BACKUP_NAME.fullmatch(candidate.name)):
            continue
        try:
            timestamp = datetime.strptime(candidate.stem[9:], '%Y%m%dT%H%M%S%fZ').replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if timestamp < cutoff:
            candidate.unlink()
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=Path('/var/lib/fundpilot/data/cloud/accounts.sqlite3'))
    parser.add_argument('--destination', type=Path, default=Path('/var/backups/fundpilot'))
    parser.add_argument('--keep-days', type=int, default=14)
    args = parser.parse_args()
    target = backup_accounts(args.database, args.destination, args.keep_days)
    print(f'备份完成并已核验：{target.name}；保留最近 {args.keep_days} 天。')


if __name__ == '__main__':
    main()
