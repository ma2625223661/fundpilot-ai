# FundPilot AI 新版前端（web/）

React 19 + TypeScript + Vite + Tailwind CSS v4 + shadcn/ui + ECharts。开发规范见项目根目录的 `AGENTS.md`。
旧版前端 `dist/` 在迁移完成前照常运行，本目录的构建结果输出到 `web/dist-react/`，不会覆盖旧版。

## 第一次使用

需要 Node.js 22.12 或更高版本（只有开发电脑需要，最终用户不需要）。

```bash
cd web
npm install
npx shadcn@latest init      # 底层组件库选 Base UI（默认）；如提示覆盖 src/index.css，选择不覆盖
npm test                    # 165 个旧前端逻辑测试 + 组件测试，全部应通过
npm run check:ui            # UI 规范检查
```

## 日常开发

1. 先用 `start.cmd` 启动本地后端（8765 端口）。
2. 在 `web/` 下运行 `npm run dev`，打开 http://localhost:5173 。接口请求会自动转发到后端。
3. 提交前运行 `npm test`、`npm run check:ui`、`npm run build`。

## 目录

| 路径 | 内容 |
|---|---|
| `src/lib/legacy/` | 从旧版逐字迁移的研究逻辑，由 `npm run port:legacy` 生成，禁止手改 |
| `src/lib/research.ts` | 页面使用研究逻辑的唯一入口 |
| `src/lib/api.ts` | 接口请求，行为与旧版 `request()` 一致 |
| `src/components/ui/` | shadcn/ui 组件（由 `npx shadcn add` 生成） |
| `src/app/` | 页面 |
| `tests/legacy/` | 旧前端测试，已改为测试新模块 |
| `scripts/` | 逻辑迁移脚本、UI 规范检查脚本 |
