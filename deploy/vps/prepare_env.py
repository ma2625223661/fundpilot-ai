"""Generate a private VPS environment and public Caddy config, without secrets in stdout."""
import argparse
import os
from pathlib import Path
import re
import secrets


HERE = Path(__file__).resolve().parent


def prepare(domain, directory=HERE, *, reuse_existing=False):
    domain = domain.strip().lower()
    labels = domain.split('.')
    if (len(domain) > 253 or len(labels) < 2 or all(part.isdigit() for part in labels)
            or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', part) for part in labels)):
        raise ValueError('请提供正式域名，例如 research.your-domain.com；不要填写协议、IP 或路径')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / '.env'
    template = (HERE / 'Caddyfile').read_text(encoding='utf-8')
    generated = directory / 'Caddyfile.generated'
    if reuse_existing and target.exists():
        if target.is_symlink() or target.stat().st_size > 65536:
            raise ValueError('已有环境文件无效，请管理员检查 deploy/vps/.env')
        # Never source a user-editable environment file in a root shell.
        identity = {}
        for line in target.read_text(encoding='utf-8').splitlines():
            name, separator, value = line.strip().partition('=')
            if separator and name in ('FUNDPILOT_DOMAIN', 'FUNDPILOT_PUBLIC_URL'):
                if name in identity:
                    raise ValueError('已有环境文件的域名配置重复，请管理员检查')
                identity[name] = value.strip().strip('\"\'')
        if identity != {'FUNDPILOT_DOMAIN': domain, 'FUNDPILOT_PUBLIC_URL': 'https://' + domain}:
            raise ValueError('已有环境文件的域名与参数不一致；保留原设置，请按部署文档更新域名')
        os.chmod(target, 0o600)
        if not generated.exists():
            generated.write_text(template.replace('{$FUNDPILOT_DOMAIN}', domain), encoding='utf-8', newline='\n')
        return target
    content = '\n'.join([
        'FUNDPILOT_DOMAIN=' + domain,
        'FUNDPILOT_PUBLIC_URL=https://' + domain,
        'FUNDPILOT_STATE_DIR=/app/data/cloud',
        'FUNDPILOT_BIND_HOST=127.0.0.1',
        'FUNDPILOT_TRUSTED_PROXIES=127.0.0.1/32',
        'FUNDPILOT_SETUP_TOKEN=' + secrets.token_urlsafe(24),
        'FUNDPILOT_REGISTRATION_OPEN=1',
        'FUNDPILOT_AI_MODEL=gpt-6.1-sol',
        'FUNDPILOT_AI_REASONING_EFFORT=xhigh',
        'FUNDPILOT_AI_ENABLED=0',
        'FUNDPILOT_AI_BASE_URL=',
        'FUNDPILOT_AI_API_KEY=', '',
    ])
    # Existing environment/credentials must survive update and repeat execution.
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
        stream.write(content)
    generated.write_text(
        template.replace('{$FUNDPILOT_DOMAIN}', domain), encoding='utf-8', newline='\n')
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--domain', required=True)
    parser.add_argument('--directory', type=Path, default=HERE)
    parser.add_argument('--reuse-existing', action='store_true', help='同域名安装重试时保留已有环境与 Caddy 配置')
    args = parser.parse_args()
    try:
        target = prepare(args.domain, args.directory, reuse_existing=args.reuse_existing)
    except (ValueError, FileExistsError) as error:
        parser.error('环境文件已存在，保留已有设置；更新请运行 docker compose up -d --build'
                     if isinstance(error, FileExistsError) else str(error))
    print(f'环境已就绪：{target}；初始化口令仅保存在该私密环境文件中。')


if __name__ == '__main__':
    main()
