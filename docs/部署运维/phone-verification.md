# 注册手机号验证与短信登录

当前功能已实现，但默认不发送短信。没有短信配置时，注册和登录仍使用用户名与密码；页面显示“短信验证暂未开通”。管理员初始化不要求手机验证码，已有用户的密码、额度与研究记录不变。

## 开通步骤

1. 在阿里云短信服务申请可发送中国大陆验证码的短信签名、模板，等待审核通过。模板使用 `${code}` 作为验证码变量。
2. 本地安装 `python -m pip install -r requirements-sms.txt`。云端 Docker 镜像已包含该依赖；旧镜像需要重新构建。
3. 在运行后端的服务环境设置以下变量，随后重启服务。密钥不要写入前端文件、代码仓库或聊天。

| 环境变量 | 用途 |
| --- | --- |
| `FUNDPILOT_SMS_ENABLED=1` | 启用真实短信 |
| `FUNDPILOT_SMS_PROVIDER=aliyun` | 短信服务商 |
| `ALIBABA_CLOUD_ACCESS_KEY_ID` | 具有短信发送权限的 RAM 用户凭据 |
| `ALIBABA_CLOUD_ACCESS_KEY_SECRET` | 对应密钥 |
| `FUNDPILOT_SMS_SIGN_NAME` | 已审核通过的短信签名 |
| `FUNDPILOT_SMS_TEMPLATE_CODE` | 已审核通过的验证码模板，如 `SMS_...` |
| `FUNDPILOT_SMS_OTP_SECRET` | 至少 32 字节的独立随机密钥，持久保存；不要复用 API Key 或初始化口令 |
| `FUNDPILOT_PHONE_REGISTRATION_REQUIRED` | 默认随短信启用要求验证；`1` 强制要求，`0` 允许不带手机字段的旧注册 API |

随机密钥可在服务器本地用 `python -c "import secrets; print(secrets.token_urlsafe(48))"` 生成，保存到权限受限的环境文件。`FUNDPILOT_SMS_ENABLED=1` 但配置缺失或 SDK 不可用时，默认暂停新用户注册，防止绕过手机号验证；已有账号仍可使用账号密码登录。`registration_required=0` 是管理员主动放宽 API 的兼容开关，网页在短信可用时仍要求验证。

服务应通过现有 HTTPS 域名提供访问。短信只有在用户点击“获取验证码”后发送；页面加载、刷新、输入号码都不会发送。服务商权限、模板审核、余额及真实送达需要开通后实测，本次实现没有真实短信测试。

## 用户流程

- 新用户：注册 → 用户名、密码、手机号 → 获取验证码 → 输入 6 位验证码 → 注册并进入。验证与账号创建在同一个事务中完成。
- 已有账号：设置 → 手机号与验证码 → 验证手机号并输入当前密码 → 绑定。
- 短信登录：登录页切换“短信验证码”，使用已绑定手机号验证。未绑定的号码不会创建新账号。
- 同一手机号只能绑定一个账号。当前不提供自助换绑或解绑；忘记密码仍可由管理员通过现有重置功能处理。

## 验证码与限流

验证码由安全随机数生成，5 分钟有效，只能使用一次，最多尝试 5 次。重新发送会作废旧码；用途（注册、登录、绑定）、手机号和绑定账号均参与校验。数据库只存验证码 HMAC，不保存或返回验证码明文；绑定手机号存于账号库，对外仅向本人返回脱敏号码。

默认按手机号 60 秒 1 次、每小时 5 次、每天 10 次；按 IP 每小时 10 次、每天 30 次；全站每天 200 次。发送失败也计入限额，不自动重试付费发送。IP 使用现有可信代理配置后的客户端地址。验证码限流按服务端持久窗口统计，页面倒计时只提供操作提示。

新增 `user_phones`、`sms_challenges` 两张表，沿用现有 `accounts.sqlite3` 持久目录和备份。迁移可重复执行；重启不会清空绑定和限流。验证码挑战保存最多一天，发送新请求时清理。备份需包含账号库；随机密钥另行安全备份，变更密钥会使尚未使用的验证码失效。

## 接口

公开接口仍校验本站 Origin，认证写操作沿用会话和 CSRF 校验：

| 接口 | 用途 |
| --- | --- |
| `GET /api/auth/status` | `phone_auth` 返回可用状态，不含密钥 |
| `POST /api/auth/sms/send` | `{phone,purpose}`，用途仅 `register` 或 `login` |
| `POST /api/auth/register` | 短信启用后要求 `{username,password,phone,challenge_id,code}` |
| `POST /api/auth/sms/login` | `{phone,challenge_id,code}`，建立普通安全会话 |
| `GET /api/me/phone` | 本人绑定状态及脱敏手机号 |
| `POST /api/me/phone/send` | 已登录用户请求绑定验证码，`{phone}` |
| `POST /api/me/phone/bind` | `{phone,challenge_id,code,password}` |

测试使用临时数据库及注入的假发送器，只在测试中捕获验证码，不向真实号码发送。运行 `runtime\python.exe -B tests\run_backend.py test_phone_auth test_phone_http test_cloud_accounts test_local_accounts` 和 `node --test tests/legacy-frontend/test_phone_frontend.cjs`。
