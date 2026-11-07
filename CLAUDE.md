# FundPilot AI 前端规范（AI 编码代理必读）

本文件约束所有 AI 代理（Claude Code、Cursor、Codex 等）和开发者在本项目中编写的界面代码。
规则分三级：**必须（MUST）**、**建议（SHOULD）**、**禁止（NEVER）**。与其他文档冲突时，以本文件为准。

## 项目结构

- `dist/`：旧版前端（原生 HTML/CSS/JS），迁移完成前继续线上运行。**只修 bug，不加新功能。**
- `web/`：新版前端，技术栈为 React 19 + TypeScript + Vite + Tailwind CSS v4 + shadcn/ui（底层 Base UI）+ lucide-react + ECharts 6。
- 后端：Python（`server.py` 本地版、`cloud_server.py` 云端版），前端只通过 `/api/*` JSON 接口与它通信。

常用命令（在 `web/` 下执行）：

| 命令 | 作用 |
|---|---|
| `npm run dev` | 开发预览，接口代理到本地后端 8765 端口（云端预览设 `FUNDPILOT_BACKEND=http://127.0.0.1:8080`） |
| `npm run build` | 类型检查 + 构建到 `web/dist-react/` |
| `npm test` | 运行旧前端逻辑测试（已指向新模块）和组件测试 |
| `npm run test:components` | 只运行 `tests/components/` 下的组件测试（vitest） |
| `npm run check:ui` | 检查本文件的硬性规则，有违规即失败 |
| `npm run port:legacy` | 旧版逻辑有改动时，重新生成 `src/lib/legacy/` |

提交任何前端改动前，`npm test`、`npm run check:ui`、`npm run build` 必须全部通过。

---

## 0. 三条硬性红线

1. **禁止渐变色。** 任何形式都不允许：`bg-gradient-*`、`from-*` / `via-*` / `to-*`、`linear-gradient()`、`radial-gradient()`、`conic-gradient()`、渐变文字、渐变边框、渐变遮罩，图表里的渐变面积也不行。一律使用纯色设计令牌。
2. **禁止 emoji。** UI 文案、按钮、标题、提示、空状态、toast、日志、注释、提交信息里都不得出现 emoji，也不得用 emoji 或 Unicode 符号（如 ↗ ↻ ⚙ ★ ◈）充当图标。图标只用 `lucide-react`。
3. **强制使用组件库。** shadcn/ui 已提供的组件必须使用组件库版本，禁止手写替代品。

## 1. 金融数据规则（本项目特有）

- MUST 涨跌颜色遵循 A 股习惯：**红涨绿跌**，只用令牌 `text-rise` / `text-fall` / `text-flat`，不得写死红绿。
- MUST 正负号与颜色同时出现（如 `+1.23%`），不能只靠颜色表达涨跌，照顾色弱用户。
- MUST 缺失、过时、未评估的数据显示为"—"或明确的"待评估"，**绝不显示为 0**；排序时统一排在末尾。沿用旧版逻辑里的 `UNKNOWN` 与各 `*Presentation` 函数给出的文案。
- MUST 每个分数、指数旁边能看到数据时间或数据日期；获取时间不等于数据日期，二者不得混用。
- MUST 研究分、风险分、事件影响分的说明文字保留"不代表收益概率 / 不构成投资建议"这类提示，不得删减或弱化。
- MUST 数字、金额、百分比、表格数据使用 `tabular-nums`，同列右对齐。
- NEVER 在前端重新计算评分、档位、涨跌幅；一律使用 `@/lib/research` 导出的函数或接口返回值。

## 2. 研究逻辑（src/lib）

- `src/lib/legacy/*.js` 由 `scripts/port-legacy.mjs` 从旧版逐字生成，**禁止手改**。
- 页面只从 `@/lib/research` 导入逻辑，不直接导入 `./legacy`。
- 要改逻辑：迁移期间先改 `dist/` 中的旧文件并跑旧测试，再 `npm run port:legacy`；或者把该函数改写为带类型的 TypeScript 放进 `src/lib/`，并让对应旧测试继续通过。
- MUST 本地版研究记录沿用旧的 localStorage 键名和数据格式（如 `fundpilot_sector_history_v1`），保证用户升级后历史记录不丢。

## 3. 组件库使用

- MUST 先查 `src/components/ui/` 已有组件；没有时用 `npx shadcn@latest add <组件名>` 添加。
- MUST 以下交互一律用组件库：Button、Input、Textarea、Select、Checkbox、Radio Group、Switch、Dialog、Alert Dialog、Sheet、Popover、Tooltip、Dropdown Menu、Tabs、Table、Field / Form、Sonner、Skeleton、Badge、Card、Separator、Scroll Area、Command、Collapsible / Accordion（代替原生 `<details>`）、Number Field（金额与数量输入）。
- NEVER 用原生 `<button>`、`<input>`、`<select>`、`<textarea>`、`<dialog>` 或 `div` + `onClick` 拼装交互控件（`src/components/ui/` 内部除外）。
- NEVER 手写键盘导航、焦点管理、焦点陷阱、ESC 关闭等行为。
- NEVER 混用两套组件体系。
- NEVER 为改外观复制组件另起名字；新样式通过 `cva` 加 `variant`。
- MUST 使用 `cn()` 合并 className；只有图标的按钮必须加 `aria-label`。
- 组件库确实没有、组合也实现不了的，写在 `src/components/` 而非 `src/components/ui/`，并在提交说明里写明原因。

## 4. 颜色与视觉

- MUST 只使用 `src/index.css` 里定义的语义色：`bg-background`、`bg-card`、`bg-muted`、`text-foreground`、`text-muted-foreground`、`bg-primary`、`border-border`、`text-rise`、`text-fall`、`text-warning`、`bg-destructive` 等。新增颜色只能加在 `src/index.css`，并同时给出亮色和暗色两个值。
- NEVER 写死颜色值（`#xxxxxx`、`rgb()`、`oklch()`）或直接用 Tailwind 色板（如 `bg-purple-500`）。
- SHOULD 每个视图只用一个强调色。
- NEVER 用发光、霓虹、彩色阴影；阴影只用 `shadow-xs`、`shadow-sm`。
- NEVER 大面积 `backdrop-blur` 装饰。
- MUST 暗色优先，同时支持亮色；对比度符合 WCAG AA。

## 5. 图表（ECharts）

- MUST 按需引入（`echarts/core` + 用到的图表和组件），不得整包引入。
- MUST 图表颜色从 CSS 变量读取（`--chart-1`…`--chart-5`、`--rise`、`--fall`、`--border`、`--muted-foreground`），主题切换时同步更新。
- NEVER 使用渐变面积、阴影、3D、默认动画以外的特效；面积图用纯色加低透明度。
- MUST 坐标轴和提示框里的数字带单位和数据日期；缺失值断开显示，不连成 0。
- SHOULD 单个指标用 Gauge 或简单条形，不要为了好看换成复杂图表。

## 6. 排版、布局、交互、动画

- MUST 标题 `text-balance`，正文 `text-pretty`；字号、间距只用 Tailwind 默认刻度，不写 `text-[17px]`、`z-[999]` 这类任意值。
- NEVER 修改字间距（`tracking-*`）。
- NEVER 使用 `h-screen`，用 `h-dvh` / `min-h-dvh`；固定定位元素考虑 `safe-area-inset`；375px 宽度下无横向滚动。
- MUST 破坏性操作（清空记录、删除账号等）用 Alert Dialog 二次确认。
- MUST 加载用 Skeleton；错误显示在动作附近并说明怎么解决；空状态给一个明确的下一步。
- MUST 所有可交互元素有可见的 `focus-visible` 样式；不阻止粘贴；不禁用缩放。
- NEVER 主动加动画；需要时只动 `transform` / `opacity`，不超过 200ms，尊重 `prefers-reduced-motion`。
- NEVER 用 `useEffect` 处理能在渲染中直接算出的值。

## 7. 安全

- 后端 CSP 为 `script-src 'self'`：NEVER 引入 CDN 脚本、外部字体或内联脚本，所有资源随构建打包。
- NEVER 使用 `dangerouslySetInnerHTML`；来源链接只允许 `https:`，并带 `rel="noopener noreferrer"`。

## 8. 文案

- MUST 简洁、具体，按钮动词开头（"更新板块研究"、"清空记录"），不用"确定"、"好的"。
- NEVER 出现 emoji、感叹号堆砌、营销腔或收益承诺。
- MUST 中英文、中文与数字之间加空格。

---

## 审查模式

被要求"按规范审查"时，对每条违规输出：违规代码（引用原行）、违反的规则（一句话）、具体修改方案（代码级）。

参考来源：ibelick 的 baseline-ui 规范（MIT 协议，https://github.com/ibelick/ui-skills）、Vercel Web Interface Guidelines（https://vercel.com/design/guidelines）。

---

## 当前任务

前端正在重写为 React，进度、已定方案、下一步和后端耦合点见 `docs/react-migration.md`。开始工作前先读它。
