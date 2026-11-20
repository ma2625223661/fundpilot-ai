# 文档索引

## 使用说明
- [手机使用说明](使用说明/手机使用说明.md)：手机访问网站。
- [AI 订阅与额度管理](使用说明/AI订阅与额度管理.md)：用户额度、解锁与管理员操作。

## 部署运维
- [云端多人版部署](部署运维/云端多人版部署.md)：Railway / Docker 部署、持久卷、环境变量。
- [手机号验证与短信登录](部署运维/phone-verification.md)：短信服务配置。
- [免费研究数据的持续更新与恢复](部署运维/data-resilience.md)
- [行情动态更新](部署运维/live-market-updates.md)：盘中 5 分钟刷新。
- 云服务器原生部署见 [`deploy/vps/README.md`](../deploy/vps/README.md) 和 [`deploy/vps/NATIVE-OPERATIONS.md`](../deploy/vps/NATIVE-OPERATIONS.md)。

## 研究方法
- [FactorLab v0.1 多因子风险归因与正交化](研究方法/factorlab-v0.1.md)：因子清洗、Barra 中性化、对称正交、IC/IR、回测、压力测试与期权对冲。
- [板块研究分 v2 与独立环境风险](研究方法/scoring-model-v2-20261031.md)
- [全站公司样本与证据口径](研究方法/company-sample-pools-20261031.md)
- [市场流动性指数](研究方法/market-liquidity-20261031.md)
- [市场情绪指数](研究方法/market-sentiment-20261031.md)
- [五个交易日复盘](研究方法/five-day-review.md)
- [复盘推荐关注指数](研究方法/复盘推荐关注指数.md)
- [康波周期研究](研究方法/long-wave-research.md)
- [稀缺性与证据研判](研究方法/sector-scarcity.md)
- [用户截图板块映射](研究方法/sector-reference.md)

## 开发记录
- [前端重写为 React：进度与交接](开发记录/react-migration.md)：新版界面的方案、各轮改动与人工验收清单，开发前先读。
- [网站检查与修复记录（2026-10-31）](开发记录/website-audit-20261031.md)
- [板块数据连接验证记录](开发记录/sector-connection-audit-20261031.md)
- [板块列表颜色与排序修复](开发记录/board-list-colours-20261031.md)
- [商品期货参考指数只读调查](开发记录/commodity-reference-readonly-20261031.md)
- [扩大公司业务样本核验记录](开发记录/expanded-business-samples-20261031.md)

## 关于旧文档里的测试命令

2026-11-07 起，后端代码在 `backend/`，测试在 `tests/`。较早的记录里写的命令按下面对照运行：

| 旧写法 | 现在 |
|---|---|
| `python -m unittest test_xxx test_yyy` | `runtime\python.exe -B tests\run_backend.py test_xxx test_yyy` |
| `python -m unittest discover` | `runtime\python.exe -B tests\run_backend.py` |
| `node --test test_xxx.cjs` | `node --test tests/legacy-frontend/test_xxx.cjs` |
| `python launch.py` / `python cloud_server.py` | `python backend/launch.py` / `python backend/cloud_server.py` |
