"""Owner password recovery inside the hosting service shell (not HTTP)."""
import getpass
import os
from pathlib import Path
from research_accounts import AccountStore, AccountError, password_hash


def main(argv=None):
    argv = os.sys.argv[1:] if argv is None else argv
    # --local: the Windows package keeps accounts beside the program in data/.
    folder = str(Path(__file__).resolve().parent / 'data') if '--local' in argv else os.environ.get('FUNDPILOT_STATE_DIR')
    if not folder or not (Path(folder) / 'accounts.sqlite3').is_file():
        raise SystemExit('未找到账号数据库：本机请双击“重置密码.cmd”，云端请在已挂载网站持久卷的服务终端中运行。')
    store = AccountStore(Path(folder) / 'accounts.sqlite3')
    username = input('需要重置密码的用户名：').strip()
    new = getpass.getpass('新密码（8～128 个字符）：')
    if new != getpass.getpass('再次输入新密码：'):
        raise SystemExit('两次密码不一致，未修改。')
    try:
        encoded = password_hash(new)
        with store.connection() as db:
            row = db.execute('SELECT id FROM users WHERE username=? COLLATE NOCASE', (username,)).fetchone()
            if not row: raise SystemExit('账号不存在。')
            db.execute('UPDATE users SET password_hash=? WHERE id=?', (encoded, row['id']))
            db.execute('DELETE FROM sessions WHERE user_id=?', (row['id'],))
    except AccountError as error:
        raise SystemExit(str(error)) from None
    print('密码已重置，该账号所有旧登录已退出。')


if __name__ == '__main__': main()
