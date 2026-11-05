# 前端重写为 React：进度与交接

更新时间：2026-11-04。接手的开发者或 AI 代理先读本文件，再读根目录 `AGENTS.md`（UI 规范）。

## 已定方案

- 技术栈：React 19 + TypeScript + Vite + Tailwind CSS v4 + shadcn/ui（底层 Base UI）+ lucide-react + ECharts 6。
- 新前端在 `web/`，构建到 `web/dist-react/`。旧前端 `dist/` 迁移完成前照常运行，只修 bug。
- 后端 Python 不重写，前端只通过 `/api/*` 通信（约 35 个接口，见 `dist/*.js` 中的 fetch 调用）。
- 三条硬性红线：禁止渐变色、禁止 emoji（包括用 ↗ ↻ ⚙ ★ ◈ 等符号当图标）、强制使用 shadcn 组件。A 股红涨绿跌。

## 已完成

1. **基础工程**（`web/`）：package.json、vite.config.ts（多页面 index + login、扁平输出 `assetsDir: ''`、生成 manifest、开发代理到 8765）、tsconfig、主题令牌 `src/index.css`（暗色优先 + 亮色、`rise`/`fall`/`flat`/`warning`/`chart-1..5`）、`src/lib/api.ts`（与旧 `request()` 行为一致）、`src/lib/theme.ts`、占位页面。
2. **纯逻辑迁移**：`web/scripts/port-legacy.mjs` 把 6 个旧文件（sector-research、sector-scarcity、sector-history、ai-subscription、research-review、research-cycle）中纯逻辑部分逐字转成 ES 模块 `web/src/lib/legacy/*.js`，共 66 个导出函数。页面统一从 `@/lib/research` 导入。
3. **测试**：26 个旧前端测试复制到 `web/tests/legacy/` 并改为测试新模块，`npm test` 结果 165/165 通过，与旧代码上的结果一致。
4. **规范检查**：`npm run check:ui`，已用违规样例验证每条规则都会报错。
5. `AGENTS.md` / `CLAUDE.md` 已按新技术栈重写。

## 第 0 阶段已收尾（2026-11-04）

- 实测环境：Node 24.21、npm 11.19；装上的版本为 vite 7.3、shadcn CLI 4.23、@base-ui/react 1.9。`npm run typecheck`、`npm run build`、`npm test`（165/165）、`npm run check:ui` 全部通过。
- `shadcn init -b base -p nova`，`components.json` 的 style 为 `base-nova`。已添加：button input card tabs table dialog alert-dialog sonner skeleton badge tooltip collapsible sidebar select switch field separator scroll-area dropdown-menu（连带 label、sheet、`src/hooks/use-mobile.ts`）。
- `src/index.css` 合并方式：保留本项目全部令牌值和中文字体栈；只采纳 shadcn 新增的 `@import "shadcn/tailwind.css"`（data-open 等变体和手风琴动画）、`--font-heading`、`--radius-2xl..4xl`、`html { font-sans }`。**没有**采纳 Geist 字体（中文界面用不上，且 woff2 不在云端静态白名单里），已卸载 `@fontsource-variable/geist`。
- shadcn 把 `src/lib/utils.ts` 改成 `export { cn } from "cn"`（shadcn 官方包 shadcn-ui/cn，clsx + tailwind-merge 的替代品），组件也直接从 `"cn"` 导入，予以保留。
- 对生成组件的两处修改：`scroll-area.tsx` 删除未使用的 React 导入（tsc noUnusedLocals 报错）；`dropdown-menu.tsx` 快捷键去掉 `tracking-widest`（规范禁止改字间距）。以后 `shadcn add --overwrite` 会还原它们，需要重做。
- 第 3 阶段搭框架时记得在根组件包上 `TooltipProvider` 并放置 sonner 的 `Toaster`。
- `npm install` 提示 esbuild 的 postinstall 未经 allowScripts 批准，但平台二进制通过 optionalDependencies 已就位，构建正常。

## 第 2 阶段已完成（2026-11-04）

- 新增 `research_frontend.py`：`FUNDPILOT_FRONTEND` 为空或 `legacy` 时网站用旧版 `dist/`（现阶段默认），为 `react` 时用 `web/dist-react/`。新版的 `index.html` 原样返回，不做脚本注入；未登录可访问的文件按 `.vite/manifest.json` 计算（`login.html`、`ai-service.html` 两个入口及其全部 imports / dynamicImports / css，外加 `web/public/` 复制来的 `qq-support.png`、`favicon.svg`）。新版缺构建产物或清单时，启动会报错并提示运行 `npm run build`。
- `cloud_server.py`、`server.py`、`research_local_auth.py` 改为从 `server.frontend` 取网页目录、静态白名单和公开文件；`create_server` / `create_cloud_server` 新增可选参数 `frontend=`，方便测试注入。
- `launch.py`：环境检查按所选前端进行；热重载同时监视 `dist/` 和 `web/dist-react/`。新版重新构建会改变带哈希的文件名，所以会触发后端重启，使静态白名单随之更新。
- 新增 `test_frontend.py`（7 项）。与前端相关的 Python 测试共 142 项全部通过。全量 1211 项中有 11 项因本机缺 `xlrd` 包报错，改动前就是这样，与本次改动无关。
- 新版判断运行模式不靠注入：`/api/auth/me`（200 表示有账号，401 跳登录页，404 表示本地无账号模式；返回值含 `csrf_token`），再加 `/api/access` 的 `scope`（`cloud` / `account_local` / `same_network`）。

## 第 3 阶段已完成（2026-11-04）

- `src/lib/api.ts`：POST 自动带 `X-CSRF-Token`，非 `/api/auth/*` 接口返回 401 时跳回登录页（替代旧 `cloud-session.js` 对 fetch 的改写）。
- `src/lib/session.ts`：读取会话和访问权限；页面从后台恢复时重新校验账号，账号变了就刷新页面。
- 登录页 `src/app/LoginApp.tsx`：完整移植密码登录、短信登录、注册（服务器要求时验证手机）、首次设置（初始化口令）、六位图形验证码（每次提交或发短信后自动换一张）和局域网 HTTP 明文提示。短信倒计时逻辑在 `src/hooks/use-phone-verification.ts`。
- 框架 `src/app/AppShell.tsx`：shadcn Sidebar 管理 5 个视图（hash 路由，兼容旧书签 `#cycle`、`#mobileAccess` 等），顶栏显示北京时间，含主题切换和账号菜单（退出登录）。窄屏下导航变成抽屉。各视图暂时显示"正在迁移"。
- 主题改为可订阅的 store（`useTheme()`），sonner 改用它，已卸载 next-themes。`use-mobile.ts` 改用 `useSyncExternalStore`：原实现在首次渲染时的宽度判断不可靠，导致窄屏下抽屉打不开。
- 清理 shadcn 组件里违反红线的写法：去掉 backdrop-blur，shadow-md/lg 改为 shadow-sm，遮罩 `bg-black/10` 改为 `bg-background/70`，侧边栏 outline 变体的阴影描边改为 `ring-1`，英文无障碍文案改为中文。以后 `shadcn add --overwrite` 时要重新检查。
- `check:ui` 新增规则：Unicode 符号图标、backdrop-blur、大阴影、发光阴影、字间距、写死黑白。这些红线规则对 `components/ui/` 同样生效。
- 全局尊重 `prefers-reduced-motion`；新增 `safe-bottom` 工具类，让页面底部避开手机的 Home 指示条。
- 已在浏览器中实测（云端开发模式 + `FUNDPILOT_FRONTEND=react`）：登录页渲染正常，CSP 下无报错；登录后的导航、主题切换、375px 抽屉导航都可用，没有横向滚动。图形验证码这一步没有在浏览器里实际提交：测试时直接往账号库写入会话，没有走登录表单。表单提交逻辑与旧版逐行对应，HTTP 层已有 Python 测试覆盖。
- 未完成并移交第 5 阶段：修改密码、绑定手机号（旧 `phone-account.js` / `cloud-account.js` 的账号区块）。

## 第 4、5 阶段已完成（2026-11-04）

全部页面已迁移到 `web/src/app/`，与旧版逐项对应：

| 旧版 | 新版 |
|---|---|
| `sector-research.js` 状态、轮询、历史 | `research/ResearchContext.tsx` |
| 市场压力 / 情绪 / 流动性 / 概览 / 指数行情 | `research/MarketOverview.tsx`（ECharts Gauge） |
| 重要事件 | `research/Events.tsx` |
| 板块总览、筛选、排序、分组 | `research/BoardExplorer.tsx` |
| 板块详情（样本指标走势、评分、维度、AI 解读、缺口） | `research/SectorDetail.tsx`、`research/CompanyEvidence.tsx` |
| AI 面板与费用保护 | `research/AiPanel.tsx` |
| `sector-scarcity.js` 的 DOM 部分 | `research/Scarcity.tsx` |
| `ai-subscription.js`（订阅、解锁、个人 AI 研究任务） | `research/SubscriptionContext.tsx`、`SubscriptionProfile.tsx`、`SectorAccess.tsx`、`ResearchControl.tsx` |
| `cloud-account.js` 我的关注 | `research/Watchlist.tsx` |
| `research-review.js` 五日复盘 | `research/FiveDayReview.tsx` |
| 数据依据 / 研究记录 / 康波周期 | `views/DataView.tsx`、`views/HistoryView.tsx`、`views/CycleView.tsx` |
| 设置、BaoStock 与多源数据、手机访问、密码、手机绑定、管理员订阅管理 | `views/SettingsView.tsx`、`settings/ResearchSettings.tsx`、`settings/AccountSettings.tsx` |
| `ai-service.html` | 第三个 Vite 入口 `ai-service.html` + `app/AiServiceApp.tsx`（公开页面） |

要点：
- 评分、档位、颜色带、涨跌幅、缺口文案全部调用 `@/lib/research` 中的旧函数。档位颜色通过 `colorForSector()` 的结果映射到新增令牌 `--tier-optimistic/neutral/cautious/avoid`（亮暗两套），没有在前端重新划分档位。
- `@/lib/research` 改为宽松类型导出：旧 JS 推断出的类型比实际数据窄。
- 旧模块 `sector-history.js` 在账号版里直接调用 `fetch`。`session.ts` 设置 `window.FundPilotCloud`，并为同源 `/api/` POST 补上 CSRF 头，作用等同旧 `cloud-session.js`，旧模块无需修改即可使用。
- 有意与旧版不同的两处：
  1. 事件影响分改为 A 股配色（利好红、利空绿）。旧版图例写的是"利好 +分（绿）/ 利空 -分（红）"，与本项目"红涨绿跌"的规范冲突。
  2. 旧版用作图标的符号（↗ ↻ ◇ ✓ ✦ ★ ! →）都换成了 lucide 图标；层级分隔箭头改为"/"。
- shadcn 没有 Base UI 版的 Number Field，因此用 Base UI 的 NumberField 原语封装了 `src/components/number-field.tsx`（放在 `components/` 而不是 `ui/`）。
- `AlertDialogAction` 只是一个普通 Button，点了不会关闭对话框，需要调用方用受控 `open` 关闭（见 `HistoryView`）。

## 第 6 阶段进度（2026-11-04）

已完成：
- 组件测试：`npm run test:components`（vitest + jsdom + Testing Library，`web/tests/components/`）。旧测试中针对 `dist/index.html` / `login.html` 结构和文案的断言已改写为新页面上的同等检查：交易时段 09:20 / 14:50、推理档位文案、预算字段、免费数据源且不索要 Token、只读权限、局域网地址过滤、无基金残留文案、红涨绿跌加正负号、缺失值不着色、"不代表收益概率"提示、复盘在记录之前、清空记录需二次确认、用户名格式、图形验证码、来源只允许 https。`npm test` 现在依次运行旧测试和组件测试。
- 浏览器实测（云端开发模式 + 真实报告数据）：5 个视图和登录页、公开页都能渲染；写操作（添加关注、保存历史记录）携带 CSRF 成功；回看和返回历史报告正常；未登录时公开页及其资源返回 200，主页面返回 302；亮色、暗色和 375px 宽度下均无横向溢出。
- Dockerfile：新增 Node 22 构建阶段，镜像里同时包含 `dist/` 和 `web/dist-react/`；`.dockerignore` 放行 `web/` 源码，排除 `node_modules` 和构建产物。
- 旧版 `dist/` 原样保留，作为备份和默认前端。

切换方法（未执行，需要验收后由负责人决定）：
1. 云端：在托管平台或 `deploy/vps/.env` 里设置 `FUNDPILOT_FRONTEND=react`，然后重启。镜像已经包含新版，不用重新构建。
2. VPS 原生部署（`install-native.sh` 直接从代码目录运行）：先在 `web/` 下执行 `npm ci && npm run build`，或者把构建好的 `web/dist-react/` 拷贝到 `/opt/fundpilot/web/`，再设置环境变量并重启。
3. Windows 本地版：打包时把 `web/dist-react/` 一并放进安装包（最终用户不需要 Node），在启动环境里设置 `FUNDPILOT_FRONTEND=react`。仓库里没有 Windows 打包脚本，`BUILD-MANIFEST.json` 由打包流程生成，下次打包时要在 `included` 中加上 "React frontend build (web/dist-react)"。
4. 回退：去掉该环境变量即可，重启后回到旧版。

注意：每次 `npm run build` 都会改变带哈希的文件名，而后端的静态白名单在启动时生成，所以单独运行 `cloud_server.py` 时，构建完必须重启后端，否则页面白屏。通过 `launch.py` 运行时，热重载会检测到文件名变化并自动重启。

还需要人工完成：
- 新旧逐页对照数据：同一份报告分别在 `FUNDPILOT_FRONTEND=legacy` 和 `react` 下打开，逐页核对数字和文案。
- 键盘操作检查：Tab 顺序、折叠区、对话框、侧边栏快捷键 Ctrl/Cmd+B。
- 真实短信、真实 AI 连接、管理员订阅操作和个人 AI 研究生成：都依赖线上配置，本次没有实际执行。
- 主包约 850KB，主要来自 ECharts。可以按页面拆分（例如图表组件懒加载），不影响功能。

## 视觉重做（2026-11-04 起，逐页进行）

背景：第 4、5 阶段完成时，页面基本是 shadcn 默认样式，并排对比后不如旧版好看（数字层级弱、板块列表挤在半宽、字小且对比度低）。所以逐页重做视觉，只改展示层，逻辑和数据不动。

首页（已完成，待负责人对比确认）：
- 市场压力、情绪、流动性三张卡：5xl 大号数字，按状态着色的结论文字，0–100 刻度条带标记点，缺失时只画轨道、数字显示"—"（不再显示 `*****`）；1280 宽时 2×2 排列，2xl 宽时一行 4 张。
- 研究状态、行情刷新、AI 计划合并成一条三栏状态条。
- 板块列表改为全宽卡片：档位色左边框、2xl 分数、档位标签、涨跌、风险，以及基本面、走势、事件三根分项条；点击后在右侧宽抽屉打开详情（新增 Sheet 的 `size="wide"` 变体），打开时从顶部开始。
- 区块顺序恢复旧版：市场环境、指数行情、我的关注与订阅、重要事件、板块总览、AI 面板。
- 详情移入抽屉后，主页面上分数旁的"不代表收益概率，不构成投资建议"提示一度看不到了（组件测试发现），已在板块总览中补回。

其余页面（已完成第一轮，待负责人确认）：
- 新增 `components/page-header.tsx`（统一页面标题 PageHeader 与统计块 StatTile），数据依据、研究记录、康波周期、设置都已改用。
- 登录页：两栏布局，左侧是带图标的三项功能介绍卡，右侧是表单。
- 数据依据：概览数字按状态着色；来源记录行加了状态色左边框，名称、数据日期、状态排成一行。
- 研究记录：历史报告行改为大号日期、板块数、摘要和"回看"；五日复盘的汇总改用统计块。
- 设置：01 / 02 / 03 步骤改为编号圆标加分隔线；修复了"研究时间"标签被 fieldset 的 legend 顶到步骤上方的问题。
- 375px 宽度下各页都没有横向滚动。

配色重做（2026-11-04）：原主色是薄荷绿，和 A 股"绿跌"冲突；研究档位用的淡黄、淡橙、淡粉也不协调。现改为：
- 中性底色：深色模式用冷灰近黑，亮色模式用浅灰白；主色改为蓝色（亮 #2563eb，暗 #5b9bff）。
- 红绿只用于涨跌。
- 研究档位改为蓝（乐观）、灰（中性）、琥珀（谨慎）、紫（规避），避开红绿，免得被看成涨跌。
- 所有文字与背景的组合对比度都 ≥ 4.5（WCAG AA），亮暗两套都计算过。

参考东方财富、雪球行情页优化布局（2026-11-04）：只借鉴信息结构，不使用对方的品牌、配色或素材。
- 主要指数行情卡移到首页最上方（参考雪球行情首页）。
- 新增"板块排行"（`research/SectorRankings.tsx`）：涨幅榜、跌幅榜、研究分榜三栏，排序沿用旧 `sortSectors()`，点名称打开详情（参考雪球热股榜、分类排行榜）。
- 板块总览从 md 宽度起改为高密度表格，列头可排序（板块、涨跌幅、研究分），研究分分组以表格行标题显示；手机仍用卡片（参考东方财富板块列表）。
- 板块分类改为下划线标签页。
- 修复：`SidebarInset` 缺少 `min-w-0`，宽表格会把整个页面撑宽，出现横向滚动。
- 东方财富板块页会弹出滑块验证码，没有操作，只参考了弹窗背后可见的表格结构。

指标条与侧边栏（2026-11-04）：
- 市场压力、情绪、流动性和市场环境四张大卡压缩成一行指标条：每格显示分数、结论、刻度条和数据日期；口径、样本与来源放进每格"依据"打开的侧边面板。指标条下方一句话保留"不代表股票收益或买入信号"。
- 侧边栏参考 GitHub 上的开源 shadcn 后台模板 satnaing/shadcn-admin（分组小标题、数量徽标、账号放在底部），再加上金融产品常见的常驻自选列表：
  - 「研究」「系统」两组导航；板块研究显示已评分板块数，数据依据显示需要关注的来源数（琥珀色），研究记录显示份数。
  - 「我的关注」显示关注板块的研究分和涨跌，点一下跳到首页并打开详情。关注状态移到 `research/WatchlistContext.tsx`，首页关注卡和侧边栏共用。
  - 底部是研究服务状态、下次更新时间、免责提示和账号菜单（手机上在抽屉里）。
- 修复：在其他页面点开板块时，原先调用的是已卸载首页留下的旧处理函数。现在请求会排队，等首页挂载后再执行。

本地 Windows 版已默认使用新版（2026-11-05）：
- `start.cmd`、`启动网站.vbs`、`检查环境.cmd` 在没有设置 `FUNDPILOT_FRONTEND` 时自动设为 `react`；需要临时回到旧版，先 `set FUNDPILOT_FRONTEND=legacy` 再运行。
- 代码里的默认值（`research_frontend.py`）仍是 legacy，所以云端与 VPS 部署不受影响，Python 测试也照旧。
- 因此 Windows 安装包现在必须包含 `web/dist-react/`，否则启动会报"新版网页尚未构建"。打包前在 `web/` 下运行 `npm run build`。
- 测试时曾在临时目录起过一个独立的云端开发服务器（8877，独立账号库），容易和正式网站混淆，已停用。以后只用 8765 这一个后端、一份数据库。

侧边栏第二版（2026-11-05），参考 shadcn 官方 dashboard-01 示例区块：
- 改为 inset 布局：侧边栏和页面外框共用较深的底色，主内容是一块圆角面板。侧边栏加宽到 17rem。
- 顶部是品牌和"搜索板块"主按钮；搜索面板（`components/sector-search.tsx`，基于 shadcn Command / cmdk）按 Ctrl/Cmd+K 打开，按名称做子串匹配，结果显示研究分和涨跌，回车打开详情。全站只有一个搜索面板，侧边栏和手机顶栏的按钮都只负责打开它。
- 主导航条目加高到 40px、图标 20px，当前页图标高亮为主色；徽标沿用。
- 中部是"我的关注"（显示数量；没有关注时给出引导）。
- 底部固定"模型与数据设置""订阅与帮助"、研究状态卡（标注本地版或云端版）和带首字母头像的账号卡。
- 新增 shadcn 组件 command、avatar（连带 input-group、textarea）。command 里的 `tracking-widest` 已去掉，英文默认文案已改成中文；添加时没有覆盖已修改过的 dialog.tsx。

首页分区与详情标签（2026-11-05）：
- 首页页头缩成一行（"板块研究"、一句说明、刷新按钮），去掉和侧边栏重复的快捷导航。
- 指数行情、研究状态始终显示；其余内容分到五个标签：市场概览（指标条、板块排行）/ 板块总览（分数说明、板块表格）/ 重要事件 / 我的关注与订阅（仅账号版）/ AI 研究。面板都保持挂载（`keepMounted`），切换后筛选条件和滚动位置不丢；上次停留的标签存在本浏览器（`fundpilot_dash_tab_v1`，只是方便功能，读写失败也不影响使用）。首页总高度从约 18000px 降到约 1000px。
- 板块详情抽屉：标题和分数固定在上方，下面分为 概览 / 研究依据 / 公司样本（债券、可转债、资金利率不显示）/ 相关事件（带数量）/ AI 解读。概览里保留"研究分不代表收益概率，不构成投资建议"；AI 解读为空时说明怎么生成。
- 修复：横向滚动的标签栏会多出一个竖向滚动条，已改为 `overflow-y-hidden`。
- 新增组件测试：首页分区标签齐全，切换后其他面板仍在页面中。

第二批界面优化（2026-11-05）：
- 状态条压成一行：研究状态和下次更新、行情状态和刷新时间、AI 计划时段各占一项，较长的说明放进悬停提示（可用键盘聚焦）；出错时错误原因仍直接显示在下方。
- 板块表格：板块名按钮用伪元素铺满整行，点行内任意位置都打开详情；没有给 `<tr>` 加点击事件，键盘和读屏仍落在这一个按钮上。行内的风险标记提示单独抬高层级，仍可悬停。表格放进限高（`max-h-dvh`）的滚动容器，表头固定（`Table` 新增 `containerClassName` 参数）。
- 重要事件未启用时，三段文字合并成一条提示，管理员会看到"去开启 AI 研究"按钮，直接跳到 AI 设置。
- 设置页拆成标签：AI 研究 / 数据连接 / 账号与安全（账号版）/ 订阅帮助与手机访问 / 用户管理（管理员）。旧链接 `#researchSettings`、`#researchDataSettings`、`#aiSupport`、`#mobileAccess`，以及新增的 `#cloudAccount`、`#aiSubscriptionAdmin` 都会打开对应分区。
- 管理员的"我的 AI 订阅"改为一张说明卡，带"管理用户订阅与额度""调整推理强度"两个入口。
- 新增组件测试：旧链接打开对应设置分区；数据连接测试改为先点分区标签再检查。

按需加载与键盘操作（2026-11-05）：
- 首页以外的四个页面（数据、记录、周期、设置）改为 `React.lazy` 按需加载，加载时显示骨架屏。
- 走势图改由 `components/charts-lazy.tsx` 引入。ECharts（约 504 kB）只在第一次显示走势图时下载，加载时用同高度的骨架屏占位。没用到的 ScoreGauge 和仪表盘图表已删除。
- 首页入口文件从约 1065 kB 降到 437 kB（gzip 从约 355 kB 降到 141 kB）。各入口共用的组件包不变。
- 后端的公开文件白名单已经包含 `dynamicImports`，按需加载的文件可以正常访问。
- 键盘走查：
  - 新增"跳到主要内容"链接，平时隐藏，按 Tab 时出现。
  - 标签面板获得焦点时显示焦点环。
  - 风险和强势标记不再单独获得焦点，原因在详情概览里直接写成文字。
  - 板块详情抽屉验证过：Tab 只在抽屉内循环，Esc 关闭后焦点回到打开它的按钮。
  - 注意：在后台标签页里测试时，浏览器会限制动画帧，Base UI 把焦点拉回抽屉的动作会延迟，看起来像焦点逃出了抽屉。这不是页面的问题。

## 必须遵守的约束

- 后端 CSP 是 `script-src 'self'`：不得使用 CDN、外部字体、内联脚本。
- 本地版研究记录存在 localStorage `fundpilot_sector_history_v1`，新版必须沿用键名和格式。
- 不在前端重算评分和档位；缺失数据显示"—"或"待评估"，不显示 0。
- `src/lib/legacy/` 禁止手改；旧逻辑有变化就改 `dist/` 再 `npm run port:legacy`。
- 每个阶段完成后再进入下一阶段；动后端前先列出改动清单。
- 构建后要重启后端（或通过 `launch.py` 热重载），否则静态白名单与新文件名不一致。
