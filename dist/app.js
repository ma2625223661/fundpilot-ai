'use strict';

const $ = selector => document.querySelector(selector);
const defaults = {risk: '稳健增强', pos: 25, min: 72};
const array = value => Array.isArray(value) ? value : [];
const string = (value, fallback = '') => typeof value === 'string' ? value : fallback;
const UNKNOWN_MASK = '*****';
const unknownMask = value => value === undefined || value === null || value === '' ? UNKNOWN_MASK : value;
const read = (key, fallback) => {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
};
const store = (key, value) => {
  try { localStorage.setItem(key, JSON.stringify(value)); return true; }
  catch { toast('浏览器存储空间不足，本次报告仍可查看和导出'); return false; }
};
let prefs = {...defaults, ...read('fundpilot_prefs', {})};
if (!['稳健增强', '均衡配置', '积极成长'].includes(prefs.risk)
    || !Number.isFinite(+prefs.pos) || +prefs.pos < 1 || +prefs.pos > 100
    || !Number.isFinite(+prefs.min) || +prefs.min < 0 || +prefs.min > 100) prefs = {...defaults};
prefs.pos = +prefs.pos;
prefs.min = +prefs.min;
let connected = false, running = false, current = null, currentSnapshot = null;
let modalFocus, toastTimer, elapsedTimer, configuredDefaults = [], previewMode = false;
let aiConfig = null, aiConfigBusy = false, aiConfigError = '', aiConfigCheckedAt = 0;
let autoTimer, autoPollBusy = false, displayedAutoId = '', latestAutoState = null, manualReportActive = false;
let autoReportBusy = false, loadedAutoReportVersion = '', loadedAutoReport = null;
let boardFilter = {group:'all', query:'', id:null, pendingCategory:'all', pendingId:null};
const AI_SCHEDULE_DEFAULTS = Object.freeze({mode:'interval', interval_minutes:30, daily_time:'15:30', end_time:null, timezone:'Asia/Shanghai'});
const aiFormDirty = {ai:false, api:false};
let history = read('fundpilot_history_v3', read('fundpilot_history_v2', []));
history = array(history).filter(r => r && r.analysis && typeof r.analysis.summary === 'string').slice(0, 20);
try { localStorage.removeItem('fundpilot_ds'); } catch {}

function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
function toast(message) {
  $('#toast').textContent = message;
  $('#toast').classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $('#toast').classList.remove('show'), 4500);
}
function stamp(value, fallback = '时间未提供') {
  if (!value) return fallback;
  if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)) return value + '（未提供时刻）';
  const date = new Date(value);
  return Number.isFinite(date.getTime())
    ? date.toLocaleString('zh-CN', {timeZone: 'Asia/Shanghai', hour12: false}) : string(value, fallback);
}
function dataDate(value) {
  if (typeof value !== 'string' || !value.trim()) return UNKNOWN_MASK;
  const parsed = new Date(value);
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0,10)===value ? value : UNKNOWN_MASK;
  return Number.isFinite(parsed.getTime()) ? stamp(value, UNKNOWN_MASK) : UNKNOWN_MASK;
}
function safeUrl(value) {
  if (typeof value !== 'string') return null;
  try {
    const url = new URL(value);
    return ['https:', 'http:'].includes(url.protocol) ? url.href : null;
  } catch { return null; }
}
function link(text, url, cls) {
  const href = safeUrl(url);
  if (!href) return el('span', text, cls);
  const node = el('a', text, cls);
  node.href = href;
  node.target = '_blank';
  node.rel = 'noopener noreferrer';
  return node;
}
function number(value, digits = 2) {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—';
}
function percent(value, signed = false) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return (signed && value > 0 ? '+' : '') + value.toFixed(2) + '%';
}
function lines(target, values, emptyText = '暂无内容') {
  const box = $(target);
  box.replaceChildren();
  array(values).filter(v => typeof v === 'string').slice(0, 30).forEach(text => box.append(el('li', text)));
  if (!box.children.length && emptyText) box.append(el('li', emptyText));
}
function view(id) {
  document.querySelectorAll('.view').forEach(v => v.classList.toggle('on', v.id === id));
  document.querySelectorAll('[data-view]').forEach(b => {
    const active = b.dataset.view === id;
    b.classList.toggle('active', active);
    b.setAttribute('aria-current', active ? 'page' : 'false');
  });
}
document.querySelectorAll('[data-view]').forEach(b => b.onclick = () => view(b.dataset.view));

function aiVerification(config = aiConfig) {
  const value = config?.verification;
  return typeof value === 'object' && value ? string(value.status, value.ok === true ? 'verified' : '') : string(value);
}
function automaticAiEnabled() {
  return aiConfig?.effective_enabled === true || (aiConfig?.effective_enabled === undefined
    && aiConfig?.configured === true && aiConfig?.enabled === true && aiVerification() === 'verified');
}
function normalizeAiSchedule(value) {
  const input = value && typeof value === 'object' ? value : {};
  const mode = ['interval','daily','scheduled_interval'].includes(input.mode) ? input.mode : AI_SCHEDULE_DEFAULTS.mode;
  const rawInterval = input.interval_minutes === undefined ? AI_SCHEDULE_DEFAULTS.interval_minutes : input.interval_minutes;
  const interval_minutes = typeof rawInterval === 'string' && !rawInterval.trim() ? rawInterval : Number(rawInterval);
  const daily_time = input.daily_time === undefined ? AI_SCHEDULE_DEFAULTS.daily_time : input.daily_time;
  const end_time = input.end_time == null || input.end_time === '' ? null : input.end_time;
  return {mode, interval_minutes, daily_time, end_time, timezone:'Asia/Shanghai'};
}
function scheduleFor(prefix) {
  return normalizeAiSchedule({mode:$('#'+prefix+'ScheduleMode').value,
    interval_minutes:$('#'+prefix+'ScheduleInterval').value, daily_time:$('#'+prefix+'ScheduleTime').value,
    end_time:$('#'+prefix+'ScheduleEndTime').value});
}
function scheduleModeLabel(mode) {
  return mode === 'daily' ? '每天固定时间' : mode === 'scheduled_interval' ? '每日时段内循环' : '按间隔运行';
}
function validateAiSchedule(prefix) {
  const value = scheduleFor(prefix);
  const interval = $('#'+prefix+'ScheduleInterval');
  const time = $('#'+prefix+'ScheduleTime');
  const end = $('#'+prefix+'ScheduleEndTime');
  const timed = value.mode !== 'interval';
  const validTime = input => typeof input === 'string' && /^([01]\d|2[0-3]):[0-5]\d$/.test(input);
  const validInterval = Number.isInteger(value.interval_minutes) && value.interval_minutes >= 1 && value.interval_minutes <= 1440;
  interval.setCustomValidity(validInterval ? '' : '请输入 1 到 1440 的整数分钟。');
  time.setCustomValidity(!timed || validTime(value.daily_time) ? '' : '请输入有效的启动时间。');
  end.setCustomValidity(!timed || !value.end_time ? '' : !validTime(value.end_time) ? '请输入有效的停止时间。'
    : value.end_time === value.daily_time ? '停止时间不能与启动时间相同。' : '');
  if (!validInterval) $('#'+prefix+'ScheduleIntervalField').hidden = false;
  return $('#'+(prefix === 'api' ? 'apiForm' : 'aiScheduleForm')).reportValidity();
}
function nextAiScheduleText(value) {
  if (aiConfig?.effective_enabled === false || aiConfig?.enabled === false) return '自动 AI 已关闭，暂无运行计划';
  return value ? '下一次 AI 研究：' + stamp(value) + '（北京时间）' : '下一次 AI 研究：等待后台计划';
}
function updateScheduleFields(prefix, schedule = aiConfig?.schedule, force = false) {
  const mode = $('#'+prefix+'ScheduleMode');
  const interval = $('#'+prefix+'ScheduleInterval');
  const time = $('#'+prefix+'ScheduleTime');
  const end = $('#'+prefix+'ScheduleEndTime');
  if (!mode || !interval || !time || !end) return;
  const value = aiFormDirty[prefix] && !force ? scheduleFor(prefix) : normalizeAiSchedule(schedule);
  if (!aiFormDirty[prefix] || force) {
    mode.value = value.mode; interval.value = String(value.interval_minutes); time.value = value.daily_time;
    end.value = value.end_time || '';
  }
  const intervalField = $('#'+prefix+'ScheduleIntervalField');
  const timeField = $('#'+prefix+'ScheduleTimeField');
  const endField = $('#'+prefix+'ScheduleEndTimeField');
  if (intervalField) intervalField.hidden = value.mode === 'daily';
  if (timeField) timeField.hidden = value.mode === 'interval';
  if (endField) endField.hidden = value.mode === 'interval';
  time.required = value.mode !== 'interval';
  time.disabled = end.disabled = aiConfigBusy || value.mode === 'interval';
  const endStatus = $('#'+prefix+'ScheduleEndStatus');
  if (endStatus) endStatus.textContent = !value.end_time ? '尚未设置停止时间'
    : value.daily_time === value.end_time ? '停止时间应与启动时间不同'
    : value.end_time < value.daily_time ? '跨午夜，次日到点停止新增请求' : '到点停止新增请求';
  const hint = $('#'+prefix+'ScheduleHint');
  if (hint) {
    const stopNote = '到点停止新增 AI 请求；已发出的请求需等当前请求返回。';
    hint.textContent = (value.mode === 'interval'
      ? '按填写的分钟间隔自动研究，不受启动或停止时段限制。'
      : value.mode === 'daily' ? '每天在启动时间研究一次。' + (value.end_time
        ? (value.end_time < value.daily_time ? '停止时间在次日，支持跨午夜。' : '') + stopNote
        : '尚未设置停止时间，本次研究按原计划完成。')
      : value.end_time ? '每天在启动至停止时段内按填写的分钟间隔研究' + (value.end_time < value.daily_time ? '（跨午夜，次日结束）' : '') + '。' + stopNote
        : '当前未设停止时间，仍按启动后持续循环；填写停止时间后改为每日时段内循环。')
      + '全部时间使用北京时间（Asia/Shanghai）。保存计划不会立即调用研究模型。';
  }
  const next = $('#'+prefix+'ScheduleNext');
  if (next) {
    const saved = nextAiScheduleText(latestAutoState?.ai_next_run_at || aiConfig?.ai_next_run_at);
    next.textContent = aiFormDirty[prefix]
      ? (saved.startsWith('下一次') ? '已保存计划的' + saved : '已保存计划状态：' + saved) + '；当前修改保存后生效'
      : saved;
  }
}
function editAiSchedule(prefix) {
  aiFormDirty[prefix] = true;
  ['ScheduleInterval','ScheduleTime','ScheduleEndTime'].forEach(suffix => $('#'+prefix+suffix)?.setCustomValidity(''));
  updateScheduleFields(prefix);
}
function configLabel() {
  if (!aiConfig) return aiConfigError ? 'AI 配置暂不可用' : '读取 AI 配置中';
  if (!aiConfig.configured) return '未配置 API Key';
  if (['failed', 'error', 'invalid'].includes(aiVerification())) return '密钥已保存 · 校验失败';
  if (aiVerification() !== 'verified') return '密钥已保存 · 等待校验';
  return automaticAiEnabled() ? '已验证 · 自动 AI 已启用' : '已验证 · 自动 AI 已关闭';
}
function aiMetadata(record) {
  return record?.ai_research && typeof record.ai_research === 'object' ? record.ai_research : null;
}
function reportHasAi(record) {
  const ai = aiMetadata(record);
  if (ai?.status === 'stale') return false;
  return record?.engine === 'ai' || ai?.status === 'success' || ai?.status === 'completed'
    || (['partial','window_closed'].includes(ai?.status) && Number(ai.analyzed_count) > 0);
}
function aiCoverageText(ai) {
  return ai && Number.isFinite(ai.analyzed_count) && Number.isFinite(ai.target_count)
    ? ai.analyzed_count + ' / ' + ai.target_count + ' 只' : '—';
}
function aiTokenCount(ai) {
  if (!ai) return null;
  const usage = ai.usage || ai;
  if (Number.isFinite(usage.total_tokens)) return usage.total_tokens;
  return Number.isFinite(usage.prompt_tokens) && Number.isFinite(usage.completion_tokens)
    ? usage.prompt_tokens + usage.completion_tokens : null;
}
function aiFailure(record) {
  const ai = aiMetadata(record);
  if (record?.ai_error) return readable(record.ai_error);
  if (!['error', 'failed', 'partial'].includes(ai?.status)) return '';
  return readable(ai.error) || array(ai.errors).slice(0, 3).map(readable).join('；');
}
function reportAiLabel(record) {
  const ai = aiMetadata(record);
  if (record.demo) return '历史示例 · 非真实行情';
  if (ai?.status === 'stale') return '自动量化研究 · 旧配置 AI 解读已失效，等待当前配置的新研究';
  if (ai?.status === 'partial') return '自动扫描 + 量化计算 · 部分 AI 深研（' + aiCoverageText(ai) + '）';
  if (ai?.status === 'window_closed') return '本次 AI 研究时段已结束 · 已研究 ' + aiCoverageText(ai);
  if (reportHasAi(record)) return (record.engine === 'automatic' ? '自动扫描 + 量化计算 + AI 深研' : '自动数据 + 量化计算 + AI 解读')
    + (ai ? '（' + aiCoverageText(ai) + '）' : '');
  if (['error', 'failed'].includes(ai?.status)) return '自动量化研究 · 本轮 AI 请求未成功';
  return '自动采集数据 + 量化规则判断 · 本报告不含 AI 解读';
}
function renderAiConfig() {
  const label = configLabel();
  $('#aiConfigBadge').textContent = label;
  $('#aiConfigBadge').dataset.state = automaticAiEnabled() ? 'enabled'
    : ['failed', 'error', 'invalid'].includes(aiVerification()) ? 'error' : 'idle';
  $('#apiState').textContent = label;
  $('#savedAiStatus').textContent = aiConfig?.configured
    ? label + ' · ' + string(aiConfig.key_hint, '已保存（密钥不回传）')
    : aiConfigError || '尚未保存密钥。配置一次后，后台可持续使用。';
  $('#aiConfigDetail').textContent = aiConfigError || (automaticAiEnabled()
    ? '后台已启用自动 AI，页面关闭后仍按服务扫描节奏运行。'
    : aiConfig?.configured && aiConfig?.error ? '配置校验未通过：' + readable(aiConfig.error)
    : aiConfig?.configured && aiConfig.enabled ? '密钥已加密保存，须先通过连接校验才会自动调用。'
    : aiConfig?.configured ? '密钥已加密保存，自动 AI 当前关闭；量化扫描继续运行。'
    : '配置并启用一次后，后台自动研究候选基金，无需手动提供分析。');
  $('#key').required = !aiConfig?.configured;
  $('#key').placeholder = aiConfig?.configured ? '留空保留已保存的密钥；输入可更换' : '输入 AI 服务商 API Key';
  $('#keyHelp').textContent = aiConfig?.configured
    ? '已保存 ' + string(aiConfig.key_hint, '密钥') + '。留空保留，输入新 Key 则替换；页面不读取密钥原文。'
    : '密钥由本机后台加密保存，页面不会读取已保存的密钥原文。';
  ['saveApi', 'saveAiSettings', 'testAi', 'forget'].forEach(id => {
    $('#' + id).disabled = aiConfigBusy || (['testAi', 'forget'].includes(id) && !aiConfig?.configured);
  });
  $('#saveApi').textContent = aiConfigBusy ? '正在保存 / 校验…' : '加密保存并校验';
  $('#saveAiSettings').textContent = aiConfigBusy ? '正在保存…' : '保存研究设置';
  ['ai','api'].forEach(prefix => ['ScheduleMode','ScheduleInterval','ScheduleTime','ScheduleEndTime'].forEach(suffix => {
    const field = $('#'+prefix+suffix); if (field) field.disabled = aiConfigBusy;
  }));
  updateScheduleFields('ai', aiConfig?.schedule);
  updateScheduleFields('api', aiConfig?.schedule);
}
function applyAiConfig(config, resetForms = []) {
  if (!config || typeof config !== 'object') return;
  aiConfig = config; aiConfigError = '';
  const model = string(config.model, 'gpt-6.1-sol');
  [['ai','model','autoAiEnabled'],['api','apiModel','apiEnabled']].forEach(([prefix,id,enabledId]) => {
    if (resetForms.includes(prefix)) aiFormDirty[prefix] = false;
    if (aiFormDirty[prefix]) return;
    const select = $('#' + id);
    if (![...select.options].some(option => option.value === model)) {
      const option = el('option', model); option.value = model; select.append(option);
    }
    select.value = model;
    $('#'+enabledId).checked = !config.configured || config.enabled !== false;
    updateScheduleFields(prefix, config.schedule, true);
  });
  renderAiConfig();
}
async function loadAiConfig() {
  aiConfigCheckedAt = Date.now();
  try {
    const response = await fetch('/api/ai/config', {cache: 'no-store', signal: AbortSignal.timeout(12000)});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '无法读取 AI 配置');
    applyAiConfig(data.config || data);
  } catch (error) {
    aiConfigError = error.name === 'TimeoutError' ? 'AI 配置读取超时，研究状态暂未确认。' : 'AI 配置读取失败：' + error.message;
    renderAiConfig();
  }
  renderAiResearch(latestAutoState); status();
}
function renderAiResearch(state = latestAutoState) {
  const record = state?.report || (state?.ai_research ? {ai_research:state.ai_research}
    : current?.engine === 'automatic' ? current : null);
  const ai = aiMetadata(record);
  const updating = state?.status === 'running' && automaticAiEnabled();
  const aiStage = /AI/i.test(readable(state?.stage) + ' ' + readable(state?.progress));
  let tone = 'idle', title = '配置一次，后台自动研究', detail = '启用自动 AI 后，系统自动研究候选基金的市场证据、新闻公告、量化结果与操作条件。';
  if (updating) {
    tone = 'running';
    const waitingForPlan = !aiStage && Date.parse(state?.ai_next_run_at || '') > Date.now();
    title = aiStage ? 'AI 正在研究候选基金' : waitingForPlan ? '公开量化扫描正在更新，AI 等待计划时间' : '自动研究已启动，正在准备证据';
    detail = (aiStage ? '后台正在请求 AI 并检查返回结论。' : waitingForPlan
      ? '后台正在更新公开数据和量化结果；AI 将在后台计划时间运行。' : '后台自动采集数据、计算指标并筛选候选，之后调用 AI。')
      + (ai ? ' 下方为最近完成一轮的实际记录，本轮用量将在完成后更新。' : '实际请求、覆盖和 Token 用量将在本轮完成后显示。');
  } else if (ai?.status === 'stale') {
    title = 'AI 配置已更新，当前结论待生成';
    detail = readable(ai.stale_reason) || '旧配置下的 AI 研究不作为当前结论，后台将按最新配置重新研究。';
    detail += ' 下方仅展示旧一轮的历史调用记录，当前配置尚无新的 AI 研究结果。';
  } else if (['success', 'completed'].includes(ai?.status)) {
    tone = 'success'; title = '本轮 AI 研究已完成';
    detail = 'AI 实际研究 / 本轮计划：' + aiCoverageText(ai) + '。已保留量化约束、操作条件与风险，AI 覆盖仅限本轮计划样本。';
  } else if (ai?.status === 'partial') {
    tone = 'partial'; title = '本轮 AI 研究部分完成';
    detail = 'AI 已研究 ' + aiCoverageText(ai) + '计划基金；其余保留量化判断。' + (aiFailure(record) ? '原因：' + aiFailure(record) : '未完成的样本不会标记为 AI 结论。');
  } else if (ai?.status === 'window_closed') {
    tone = Number(ai.analyzed_count) > 0 ? 'partial' : 'idle'; title = '本次研究时段已结束';
    detail = 'AI 已研究 / 本轮计划：' + aiCoverageText(ai) + '。'
      + string(ai.stopped_reason, '未发出的批次保持量化研究；下个时段重新采集证据。')
      + ' 到点停止新增 AI 请求，已发出的请求需等当前请求返回；实际请求和用量保留在下方。';
  } else if (ai?.status === 'scheduled') {
    tone = 'running'; title = '自动 AI 已启用，等待计划时间';
    detail = '公开量化扫描继续运行，AI 将按所选时间计划调用；当前轮尚未产生 AI 付费请求。';
  } else if (['error', 'failed'].includes(ai?.status)) {
    tone = 'error'; title = '本轮 AI 未完成，保留量化研究';
    detail = aiFailure(record) || '本轮 AI 请求或结果校验失败，基金策略保留原有量化判断。';
  } else if (ai?.status === 'no_evidence') {
    tone = 'partial'; title = '本轮证据不足，未调用 AI';
    detail = '本轮没有通过净值样本和数据质量检查的研究对象，系统保留数据缺口，等待下一轮自动扫描。';
  } else if (ai?.status === 'superseded') {
    title = 'AI 配置已更新，等待新一轮研究';
    detail = string(ai.error, '配置变更前的 AI 解读未采用，后台将按新配置重新研究。');
  } else if (automaticAiEnabled()) {
    title = '自动 AI 已就绪，等待本轮研究';
    detail = '后台将随市场扫描自动请求 AI 服务商。' + (record ? '当前显示的报告尚未包含成功的 AI 研究，新一轮完成后更新。' : '当前尚无已完成的 AI 调用记录。');
  } else if (aiConfig?.configured) {
    title = aiConfig.enabled ? 'AI 配置待验证，自动调用尚未启用' : '自动 AI 当前已关闭';
    detail = '当前量化扫描可继续运行。' + (aiConfig.error ? '配置原因：' + readable(aiConfig.error) : '连接验证通过并启用后，将自动研究候选基金。');
  }
  if (state?.report_stale) detail += ' 当前为历史快照，等待有效新报告。';
  const historical = ai?.status === 'stale' || Boolean(state?.report_stale) || (updating && Boolean(ai));
  $('#aiModelCaption').textContent = historical ? '上轮模型' : '本轮模型';
  $('#aiCallsCaption').textContent = historical ? '上轮 API 请求' : '本轮 API 请求';
  $('#aiCoverageCaption').textContent = historical ? '上轮已研究 / 计划基金' : 'AI 已研究 / 计划基金';
  $('#aiTokensCaption').textContent = historical ? '上轮已知 Token 用量' : '实际 Token 用量';
  $('#aiResearchPanel').dataset.state = tone;
  $('#aiResearchTitle').textContent = title;
  $('#aiResearchDetail').textContent = detail;
  $('#aiModel').textContent = string(ai?.model, '—');
  $('#aiCalls').textContent = Number.isFinite(ai?.request_count) ? ai.request_count.toLocaleString('zh-CN') + ' 次' : '—';
  $('#aiCoverage').textContent = aiCoverageText(ai);
  const tokens = aiTokenCount(ai);
  $('#aiTokens').textContent = tokens === null ? '—' : ai?.usage_complete === false && tokens === 0 ? '未完整返回'
    : (ai?.usage_complete === false ? '≥ ' : '') + tokens.toLocaleString('zh-CN');
  const usage = ai?.usage || ai || {};
  $('#aiTokens').title = tokens === null ? '尚无实际用量记录' : '输入 ' + (Number.isFinite(usage.prompt_tokens) ? usage.prompt_tokens : '—') + ' · 输出 ' + (Number.isFinite(usage.completion_tokens) ? usage.completion_tokens : '—')
    + (ai?.usage_complete === false ? ' · 部分请求未返回用量，仅列出已知 Token；实际账单以服务商账单为准' : '');
  $('#aiResearchTime').textContent = ai ? (historical ? '历史记录时间：' : '本轮记录时间：') + stamp(ai.completed_at || ai.finished_at || state?.completed_at || record?.time)
    : aiConfig?.last_verified_at ? '配置最近校验：' + stamp(aiConfig.last_verified_at) + ' · 校验不代表已调用研究模型' : '尚无已完成的 AI 研究记录';
  $('#aiNextResearchTime').textContent = nextAiScheduleText(state?.ai_next_run_at || ai?.next_run_at || aiConfig?.ai_next_run_at);
  updateScheduleFields('ai', aiConfig?.schedule);
  renderAiConfig();
}
function status() {
  const displayedPrefs = current?.prefs || prefs;
  $('#apiState').textContent = configLabel();
  $('#connection').textContent = connected ? '自动研究服务运行中' : '自动研究服务尚未连接';
  $('#style').textContent = displayedPrefs.risk;
  $('#position').textContent = '本报告单只基金上限 ' + displayedPrefs.pos + '% · 最低研究分 ' + displayedPrefs.min;
  $('#mode').textContent = current
    ? reportHasAi(current) ? 'AI + 量化研究' : current.engine === 'automatic' ? '自动扫描 + 量化研究' : current.demo ? '历史示例' : '自动量化研究'
    : running ? '正在获取数据' : '等待自动研究';
  $('#engineNote').textContent = reportHasAi(current) ? '实际 AI 证据解读 · 覆盖范围见报告'
    : current?.engine === 'automatic' ? '公开初筛 + 量化策略 · 本报告无 AI 解读' : '自动数据 + 数学计算 · 不含 AI 解读';
}
async function health() {
  try {
    const r = await fetch('/api/health', {signal: AbortSignal.timeout(8000)});
    const d = await r.json();
    connected = r.ok && d.version >= 3;
    if (Array.isArray(d.defaults)) configuredDefaults = d.defaults;
  } catch { connected = false; }
  status();
  return connected;
}
function parseCodes() {
  const text = $('#codes').value.trim();
  if (!text) return configuredDefaults.slice(0, 8);
  const codes = [...new Set(text.split(/[\s,，;；]+/).filter(Boolean))];
  if (codes.length > 8 || codes.some(code => !/^\d{6}$/.test(code))) {
    throw new Error('请填写最多 8 个六位基金代码，用逗号或空格分隔');
  }
  return codes;
}
function setBusy(busy, message) {
  running = busy;
  $('#run').disabled = busy;
  $('#refreshData').disabled = busy;
  $('#refreshSources').disabled = busy;
  $('#analyzeForm').setAttribute('aria-busy', String(busy));
  $('#run').textContent = busy ? '研究中…' : '研究指定基金';
  clearInterval(elapsedTimer);
  if (message) $('#progress').textContent = message;
  if (busy) {
    const started = Date.now();
    elapsedTimer = setInterval(() => {
      const elapsed = Math.floor((Date.now() - started) / 1000);
      $('#progress').textContent = message + ' 已等待 ' + elapsed + ' 秒。';
    }, 1000);
  }
  status();
}

function openApi() {
  modalFocus = document.activeElement;
  aiFormDirty.api = false;
  $('#key').value = '';
  $('#apiModel').value = aiConfig?.model || $('#model').value;
  $('#apiEnabled').checked = !aiConfig?.configured || aiConfig?.enabled !== false;
  const modalSchedule = aiConfig?.configured ? aiConfig?.schedule : scheduleFor('ai');
  $('#apiModalStatus').textContent = '保存时检查官方接口的密钥与模型权限；验证通过后按所选设置启动自动研究。';
  renderAiConfig();
  updateScheduleFields('api', modalSchedule, true);
  $('#mb').showModal();
  $('#key').focus();
}
document.querySelectorAll('[data-api]').forEach(b => b.onclick = openApi);
['ai','api'].forEach(prefix => {
  ['ScheduleMode','ScheduleInterval','ScheduleTime','ScheduleEndTime'].forEach(suffix => {
    const field = $('#'+prefix+suffix);
    field?.addEventListener('change', () => editAiSchedule(prefix));
    if (suffix !== 'ScheduleMode') field?.addEventListener('input', () => editAiSchedule(prefix));
  });
  const model = $('#'+(prefix==='ai'?'model':'apiModel'));
  const enabled = $('#'+(prefix==='ai'?'autoAiEnabled':'apiEnabled'));
  [model,enabled].forEach(field => field?.addEventListener('change', () => { aiFormDirty[prefix] = true; }));
  if (prefix==='api') $('#key')?.addEventListener('input', () => { aiFormDirty.api = true; });
});
$('#cancel').onclick = () => $('#mb').close();
$('#mb').addEventListener('close', () => { $('#key').value = ''; modalFocus?.focus(); });
$('#mb').addEventListener('click', e => {
  if (e.target !== $('#mb')) return;
  const rect = $('#mb').getBoundingClientRect();
  if (e.clientX < rect.left || e.clientX > rect.right || e.clientY < rect.top || e.clientY > rect.bottom) $('#mb').close();
});
async function aiConfigRequest(path, body = {}) {
  const response = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body), signal: AbortSignal.timeout(45000)});
  const data = await response.json();
  if (data.config) applyAiConfig(data.config);
  if (!response.ok) throw new Error(data.error || 'AI 配置操作失败（' + response.status + '）');
  return data;
}
async function saveAiConfig(body, modal = false) {
  if (aiConfigBusy) return;
  const prefix = modal ? 'api' : 'ai';
  aiFormDirty[prefix] = true;
  aiConfigBusy = true; renderAiConfig();
  const output = modal ? $('#apiModalStatus') : $('#aiSettingsStatus');
  output.textContent = '正在加密保存并检查官方接口；请稍候…';
  try {
    const data = await aiConfigRequest('/api/ai/config', body);
    applyAiConfig(data.config || aiConfig, [prefix]);
    const skipped = data.connection?.skipped === true;
    const verified = skipped || !data.connection ? aiVerification() === 'verified' : data.connection.ok === true;
    const scheduleOnly = skipped && !body.key && Boolean(aiConfig?.configured);
    const message = scheduleOnly ? (automaticAiEnabled()
      ? '时间计划已保存；当前保持启用，后台将在下一次计划时间研究。本次未调用研究模型。'
      : '时间计划已保存；自动 AI 当前关闭，本次未调用研究模型。')
      : verified ? (automaticAiEnabled() ? '配置已保存并验证，后台将自动研究候选基金。' : '配置已保存并验证，自动 AI 当前关闭。')
      : skipped ? '配置已加密保存，自动 AI 当前关闭；连接校验尚未执行。'
      : '配置已加密保存，但连接校验未通过：' + readable(data.connection?.error || aiConfig?.error || '请检查密钥、模型或网络');
    output.textContent = message;
    $('#aiSettingsStatus').textContent = message;
    if (verified || skipped) {
      if (modal) $('#mb').close();
      if (automaticAiEnabled()) { manualReportActive = false; displayedAutoId = ''; }
      if (data.status) renderAutoState(data.status);
      pollAuto();
    }
    renderAiResearch(latestAutoState); status(); toast(message);
  } catch (error) {
    const message = error.name === 'TimeoutError' ? '保存或连接校验超时，请稍后检查后台配置状态。' : error.message;
    output.textContent = message; toast(message);
    await loadAiConfig();
  } finally { $('#key').value = ''; aiConfigBusy = false; renderAiConfig(); }
}
$('#apiForm').onsubmit = async e => {
  e.preventDefault();
  if (!validateAiSchedule('api')) return;
  const key = $('#key').value.trim();
  if ((!key && !aiConfig?.configured) || /\s/.test(key)) return toast('请输入有效 API Key，不要包含空白字符');
  await saveAiConfig({...(key ? {key} : {}), model: $('#apiModel').value, enabled: $('#apiEnabled').checked,
    schedule: scheduleFor('api')}, true);
};
$('#saveAiSettings').onclick = () => {
  if (!validateAiSchedule('ai')) return;
  if (!aiConfig?.configured) { openApi(); return; }
  saveAiConfig({model: $('#model').value, enabled: $('#autoAiEnabled').checked, schedule: scheduleFor('ai')});
};
$('#aiScheduleForm').onsubmit = e => { e.preventDefault(); $('#saveAiSettings').click(); };
$('#testAi').onclick = async () => {
  if (aiConfigBusy || !aiConfig?.configured) return;
  aiConfigBusy = true; renderAiConfig(); $('#aiSettingsStatus').textContent = '正在检查已保存密钥与模型权限…';
  try {
    const data = await aiConfigRequest('/api/ai/test');
    const ok = data.connection ? data.connection.ok === true : data.ok === true || aiVerification() === 'verified';
    const message = ok ? '连接与模型权限检查通过。此检查不调用研究模型，实际研究用量见首页。'
      : '连接检查未通过：' + readable(data.connection?.error || data.error || aiConfig?.error || '请检查配置');
    $('#aiSettingsStatus').textContent = message; toast(message);
    if (data.status) renderAutoState(data.status);
  } catch (error) { $('#aiSettingsStatus').textContent = error.message; toast(error.message); }
  finally { aiConfigBusy = false; renderAiResearch(latestAutoState); status(); }
};
$('#forget').onclick = async () => {
  if (aiConfigBusy || !aiConfig?.configured) return;
  aiConfigBusy = true; renderAiConfig();
  try {
    const data = await aiConfigRequest('/api/ai/clear');
    if (!data.config) await loadAiConfig();
    $('#key').value = ''; $('#aiSettingsStatus').textContent = '后台密钥已清除，后续自动扫描仅运行量化研究。';
    if (data.status) renderAutoState(data.status);
    toast('已清除后台保存的 API Key，后续自动 AI 已关闭');
  } catch (error) { $('#aiSettingsStatus').textContent = error.message; toast(error.message); }
  finally { aiConfigBusy = false; renderAiResearch(latestAutoState); status(); }
};
$('#risk').value = prefs.risk;
$('#pos').value = prefs.pos;
$('#min').value = prefs.min;
$('#prefsForm').onsubmit = e => {
  e.preventDefault();
  if (!$('#prefsForm').reportValidity()) return;
  prefs = {risk: $('#risk').value, pos: +$('#pos').value, min: +$('#min').value};
  store('fundpilot_prefs', prefs); status();
  toast('偏好已保存，用于指定基金补充研究；后台扫描采用独立的中高风险筛选规则');
};
const savedCodes = read('fundpilot_codes_v3', []);
if (Array.isArray(savedCodes)) $('#codes').value = savedCodes.filter(v => /^\d{6}$/.test(v)).slice(0, 8).join(', ');
$('#context').value = string(read('fundpilot_constraints_v3', ''));
function updateCount() { $('#count').textContent = $('#context').value.length + ' / 3,000 字符'; }
$('#context').addEventListener('input', updateCount); updateCount();

function isFundAnnouncementEvidence(item) {
  return [item?.source_id, item?.id].some(id => typeof id === 'string'
    && /^(?:announcements_\d{6}|fund:\d{6}:announcements)$/.test(id));
}
function renderSnapshot(snapshot, quant) {
  currentSnapshot = snapshot || {};
  const sources = array(snapshot?.sources);
  const ok = sources.filter(s => s && s.status === 'ok').length;
  const partial = sources.filter(s => s && s.status === 'partial').length;
  $('#coverage').textContent = sources.length ? ok + ' / ' + sources.length + ' 可用' : '暂无可用来源';
  $('#snapshotTime').textContent = '采集于 ' + stamp(snapshot?.as_of);
  $('#dataAsOf').textContent = '采集时间 ' + stamp(snapshot?.as_of);
  $('#researchStatus').textContent = sources.length
    ? partial || ok < sources.length ? '自动采集完成 · 部分来源需注意' : '自动采集完成 · 研究依据已更新'
    : '尚未取得有效数据';
  $('#researchStatusDetail').textContent = sources.length
    ? '已返回 ' + array(snapshot?.funds).length + ' 只基金、' + array(snapshot?.market).length + ' 项市场指标和 ' + array(snapshot?.news).length + ' 条新闻公告。具体数据时间与失败原因见“数据与依据”。'
    : '可点击刷新重试；数据暂缺时，系统不会填入模拟行情。';

  const quoteBox = $('#marketQuotes');
  quoteBox.replaceChildren();
  array(snapshot?.market).slice(0, 8).forEach(q => {
    if (!q) return;
    const tile = el('article', undefined, 'market-quote');
    tile.append(el('span', string(q.name, q.code), 'label'));
    const values = el('div', undefined, 'quote-values');
    values.append(el('b', number(q.last)), el('span', percent(q.change_pct, true), q.change_pct >= 0 ? 'up' : 'down'));
    tile.append(values, el('small', stamp(q.as_of)), link('行情来源 ↗', q.source_url, 'quote-source'));
    quoteBox.append(tile);
  });

  const sentiment = snapshot?.sentiment;
  $('#sentimentLabel').textContent = sentiment ? string(sentiment.label, '待核验') : '样本不足';
  $('#sentimentNote').textContent = sentiment && Number.isFinite(sentiment.score)
    ? '代理分 ' + number(sentiment.score, 0) + ' · 非收益预测' : '可用样本不足时不作判断';
  const headlineScore = sentiment && Number.isFinite(sentiment.headline_score)
    ? '新闻标题情绪代理分 ' + number(sentiment.headline_score, 0) + '（仅限已采集标题）' : '';
  const positiveRatio = sentiment && Number.isFinite(sentiment.index_positive_ratio_pct)
    ? '指数样本上涨占比 ' + number(sentiment.index_positive_ratio_pct, 1) + '%（不代表全市场个股）' : '';
  const sampleChange = sentiment && Number.isFinite(sentiment.index_mean_change_pct)
    ? '指数样本平均涨跌 ' + percent(sentiment.index_mean_change_pct, true) : '';
  const coverageText = sentiment?.coverage && typeof sentiment.coverage === 'object'
    ? '纳入指数 ' + (sentiment.coverage.indices ?? 0) + ' 个；近3天新闻/公告 ' + (sentiment.coverage.recent_headlines ?? 0) + ' 条；未计入的时间不明条目 ' + (sentiment.coverage.unknown_date_headlines ?? 0) + ' 条' : '';
  const basis = sentiment ? [sentiment.method, sentiment.basis, coverageText, headlineScore, positiveRatio, sampleChange]
    .flatMap(v => Array.isArray(v) ? v : v == null ? [] : [v])
    .map(v => typeof v === 'object' ? JSON.stringify(v) : String(v)).join('；') : '没有足够数据生成情绪代理。';
  $('#sentimentBasis').textContent = basis || '未返回情绪计算依据。';

  const sourceBox = $('#sourceList');
  sourceBox.replaceChildren();
  const visibleSources = sources.filter(s => s && !isFundAnnouncementEvidence(s));
  visibleSources.forEach(s => {
    if (!s) return;
    const row = el('div', undefined, 'source-row source-detail');
    const detail = el('div');
    detail.append(link(string(s.name, s.id || '数据来源'), s.url));
    detail.append(el('small', '数据时间：' + stamp(s.as_of)));
    if (s.fetched_at) detail.append(el('small', '本次获取：' + stamp(s.fetched_at)));
    if (s.error) detail.append(el('p', string(s.error), 'source-error'));
    if (s.id) detail.append(el('small', '证据编号：' + s.id, 'evidence-id'));
    const names = {ok: '已获取', partial: '部分可用', error: '获取失败'};
    row.append(detail, el('span', names[s.status] || '状态待核验', 'pill ' + (s.status === 'ok' ? 'green' : '')));
    sourceBox.append(row);
  });
  if (!visibleSources.length) sourceBox.append(el('p', '尚未取得来源状态。请刷新重试。', 'muted'));
  lines('#dataWarnings', snapshot?.warnings, '');

  const rows = $('#quantRows');
  rows.replaceChildren();
  array(quant).forEach(q => {
    if (!q) return;
    const row = el('tr');
    const title = el('td');
    title.append(el('strong', string(q.name, q.code)), el('small', string(q.code) + ' · ' + string(q.nav_date, '日期未知')));
    row.append(title);
    const m = q.metrics || {};
    [percent(m.return_20d, true), percent(m.return_60d, true), percent(m.volatility_annual), percent(m.max_drawdown), number(m.rsi14, 1)].forEach(v => row.append(el('td', v)));
    row.append(el('td', ({ok: '可计算', stale: '数据过时', insufficient: '样本不足'})[q.quality] || '待核验'));
    rows.append(row);
  });
  if (!rows.children.length) {
    const td = el('td', '尚无足够历史数据计算指标。');
    td.colSpan = 7; const tr = el('tr'); tr.append(td); rows.append(tr);
  }

  const newsBox = $('#newsList');
  newsBox.replaceChildren();
  const news = array(snapshot?.news).filter(n => n && !isFundAnnouncementEvidence(n));
  $('#newsCount').textContent = news.length + ' 条 · 当前快照';
  news.slice(0, 40).forEach(n => {
    if (!n) return;
    const article = el('article', undefined, 'news-item');
    const meta = el('div', undefined, 'news-meta');
    meta.append(el('span', string(n.category, '新闻 / 公告'), 'pill'),
      el('span', string(n.source, '来源未标注')),
      el('time', stamp(n.published_at, '发布时间未提供')));
    article.append(meta, link(string(n.title, '未命名条目'), n.url, 'news-title'));
    if (n.summary) article.append(el('p', string(n.summary), 'muted'));
    newsBox.append(article);
  });
  if (!news.length) newsBox.append(el('p', '本次未获取到可用新闻公告；决策报告会保留这个数据缺口。', 'muted'));
}

function metric(label, value) {
  const box = el('div', undefined, 'metric');
  box.append(el('span', label), el('b', value));
  return box;
}
function render(record, isPreview = false) {
  current = record; previewMode = isPreview;
  const a = record.analysis;
  $('#empty').hidden = true; $('#result').hidden = false;
  $('#summary').textContent = string(a.summary);
  $('#market').textContent = string(a.market_view);
  $('#last').textContent = (isPreview ? '自动预览 · ' : '报告生成于 ') + stamp(record.time) + ' · ' + string(record.model, '量化规则引擎');
  $('#resultTag').textContent = reportAiLabel(record);
  const aiError = aiFailure(record);
  $('#aiError').hidden = !aiError;
  $('#aiError').textContent = aiError ? 'AI 研究说明：' + aiError + '。本报告中未完成 AI 研究的样本保留量化判断。' : '';
  lines('#risks', a.risks, '未返回风险说明，请核验数据完整性。');
  lines('#steps', a.next_steps, '待进一步核验。');
  renderSnapshot(record.snapshot || {sources: [], warnings: ['此记录来自旧版，未保存当时的数据快照；不与当前行情混合展示。']}, record.quant);
  if (record.strategy) renderAutoSummary(record);
  renderFundBoards(record);
  $('#export').disabled = false;
  renderAiResearch(latestAutoState);
  status();
}
function compactRecord(record) {
  const snapshot = record.snapshot || {};
  return {...record, snapshot: {...snapshot,
    funds: array(snapshot.funds).map(({history, ...fund}) => fund),
    news: array(snapshot.news).slice(0, 80).map(({content, ...item}) => ({...item, summary: string(item.summary).slice(0, 1200)})),
    sources: array(snapshot.sources)
  }};
}
function persistHistory() {
  history=history.slice(0,20);
  // localStorage counts UTF-16 code units on common browsers. Keep evidence
  // intact and retain fewer complete recent reports when snapshots grow.
  while(history.length>1 && JSON.stringify(history).length*2>3600000) history.pop();
  try { localStorage.setItem('fundpilot_history_v3',JSON.stringify(history)); }
  catch { toast('当前报告可查看和导出；浏览器空间不足，历史保存未完成。'); }
}
function renderHistory() {
  const box = $('#historyList'); box.replaceChildren();
  $('#historyCount').textContent = history.length + ' / 20 条';
  if (!history.length) box.append(el('p', '还没有保存的报告。自动扫描完成后会自动保留，也可保存指定基金的补充研究。', 'muted'));
  history.forEach(record => {
    const button = el('button', undefined, 'history-item');
    button.append(el('strong', (record.engine === 'automatic' ? (reportHasAi(record) ? '自动 AI 市场研究' : '自动量化扫描') : record.engine === 'ai' ? 'AI + 量化' : record.demo ? '历史示例' : '量化研究') + ' · ' + stamp(record.time)),
      el('span', record.analysis.summary.slice(0, 170)));
    button.onclick = () => { manualReportActive = true; render(record); view('dash'); $('#result').scrollIntoView({behavior: 'smooth'}); };
    box.append(button);
  });
}
function validateResponse(data) {
  if (!data?.analysis || typeof data.analysis.summary !== 'string' || typeof data.analysis.market_view !== 'string'
      || !Array.isArray(data.analysis.funds) || !Array.isArray(data.analysis.risks) || !Array.isArray(data.analysis.next_steps)) {
    throw new Error('服务未返回完整研究报告，请稍后重试');
  }
}
async function requestResearch(save = true, refresh = true) {
  if (running) return;
  let codes;
  try { codes = parseCodes(); } catch (e) { toast(e.message); $('#codes').focus(); return; }
  const submittedPrefs = {...prefs};
  const context = $('#context').value.trim();
  const message = save
    ? automaticAiEnabled() ? '正在自动采集数据、计算指标，并使用后台已保存配置请求 AI 解读。' : '正在自动采集市场、净值和新闻公告，计算决策指标。'
    : '正在自动获取市场与基金数据，生成量化预览。';
  setBusy(true, message);
  $('#progress').setAttribute('role', 'status');
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 180000);
  try {
    let response;
    if (save) {
      response = await fetch('/api/analyze', {
        method: 'POST', signal: controller.signal, headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({codes, use_saved_key: true, model: aiConfig?.model || $('#model').value, prefs: submittedPrefs, context, refresh})
      });
    } else {
      const params = new URLSearchParams({codes: codes.join(','), refresh: refresh ? '1' : '0',
        risk: submittedPrefs.risk, pos: String(submittedPrefs.pos), min: String(submittedPrefs.min)});
      response = await fetch('/api/research?' + params, {signal: controller.signal});
    }
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '研究服务返回错误（' + response.status + '）');
    validateResponse(data); connected = true;
    if (Array.isArray(data.defaults)) {
      configuredDefaults = data.defaults.filter(v => /^\d{6}$/.test(v)).slice(0, 8);
      if (!$('#codes').value.trim()) $('#codes').value = configuredDefaults.join(', ');
    }
    if (!codes.length && Array.isArray(data.snapshot?.funds)) codes = data.snapshot.funds.map(f => f.code).filter(Boolean);
    $('#codes').placeholder = '例如：' + (configuredDefaults.length ? configuredDefaults.slice(0, 3).join(', ') : '填写六位基金代码');
    const record = {analysis: data.analysis, model: data.model || '量化规则引擎', engine: data.engine || 'quant',
      snapshot: data.snapshot, quant: data.quant, sections: data.sections, strategy: data.strategy, universe: data.universe,
      ai_error: data.ai_error, ai_research: data.ai_research,
      time: new Date().toISOString(), prefs: data.prefs || (save ? submittedPrefs : defaults)};
    render(record, !save);
    manualReportActive = true;
    if (save) {
      store('fundpilot_codes_v3', codes);
      store('fundpilot_constraints_v3', context);
      history.unshift(compactRecord(record)); history = history.slice(0, 20);
      persistHistory(); renderHistory();
    }
    setBusy(false, data.ai_error
      ? '自动数据和量化报告已生成；AI 解读失败的原因见报告。'
      : save ? '研究完成，已保留决策、数学指标与来源。可在下方查看理由和失效条件。'
      : '指定基金数据已更新。点击“研究指定基金”可按你的偏好生成并保存补充报告。');
    if (save) toast(data.engine === 'ai' ? 'AI 与量化研究报告已生成' : '自动量化研究报告已生成');
  } catch (error) {
    setBusy(false, error.name === 'AbortError'
      ? '研究请求超时。原报告已保留，可稍后重试。'
      : error.message + '。原报告已保留。');
    $('#progress').setAttribute('role', 'alert');
    if (!current) {
      $('#researchStatus').textContent = '自动研究暂未完成';
      $('#researchStatusDetail').textContent = '请确认研究服务已启动后重试。无需手动补写市场分析。';
    }
  } finally { clearTimeout(timeout); if (running) setBusy(false); }
}
$('#analyzeForm').onsubmit = e => { e.preventDefault(); if ($('#analyzeForm').reportValidity()) requestResearch(true, true); };
$('#refreshData').onclick = () => requestResearch(false, true);
$('#refreshSources').onclick = () => requestResearch(false, true);

function exportReport(record) {
  const a = record.analysis, s = record.snapshot || {};
  const strategy = record.strategy || {};
  const autoSummary = record.strategy ? [
    '', '## 自动扫描与市场模式',
    '恐慌指标：' + (Number.isFinite(strategy.panic?.score) ? strategy.panic.score + ' / 100（越高压力越大）' : '数据不足 / 时效待确认'),
    '市场模式：' + readable(strategy.regime?.label) + '；' + readable(strategy.regime?.reason),
    '指标依据：' + readable(strategy.panic?.method),
    '持有计划：' + readable(strategy.horizon?.label) + '；' + readable(strategy.horizon?.notice),
    '扫描覆盖：' + readable(record.universe?.coverage),
    ...array(record.universe?.warnings).map(v => '- ' + v),
    '', '### 按类筛选结果',
    '每个板块深研与展示均最多三只；当前展示 ' + selectedFunds(record).length + ' 只，其中 ' + selectedFunds(record).filter(f => f.role === 'candidate').length + ' 只为条件性研究候选。逐只理由与操作见下方板块明细。',
    '', '### 防守与备用方向',
    ...array(strategy.defensive_options).map(v => '- ' + readable(v)),
    '银行股票基金不是银行存款。7天是研究与复核下限，不代表保本、收益、锁定期或免费赎回。'
  ] : [];
  const text = [
    '# FundPilot 自动基金研究报告',
    '报告时间：' + stamp(record.time),
    '数据采集时间：' + stamp(s.as_of),
    '研究引擎：' + string(record.model, '量化规则引擎') + ' · ' + reportAiLabel(record),
    ...(aiMetadata(record) ? ['AI 研究状态：' + readable(aiMetadata(record).status),
      'AI 实际覆盖：' + aiCoverageText(aiMetadata(record)) + '；API 请求：' + (aiMetadata(record).request_count ?? '未记录'),
      'AI 实际 Token：' + (aiMetadata(record).usage_complete === false ? '至少 ' : '') + (aiTokenCount(aiMetadata(record)) ?? '未记录')
        + (aiMetadata(record).usage_complete === false ? '（部分请求未返回用量，实际账单以服务商账单为准）' : ''),
      ...(aiFailure(record) ? ['AI 研究说明：' + aiFailure(record)] : [])] : []),
    '风险风格：' + (record.prefs?.risk || defaults.risk) + '；单只基金仓位上限：' + (record.prefs?.pos ?? defaults.pos) + '%',
    '', '## 研究结论', string(a.summary), '', string(a.market_view), ...autoSummary,
    '', '## 逐只基金决策',
    ...selectedFunds(record).flatMap(f => {
      const q = array(record.quant).find(q => q?.code === f.code || q?.name === f.name);
      const m = q?.metrics || {};
      const plan = f.operation_plan || q?.operation_plan;
      const planText = plan && typeof plan === 'object' ? [
        '#### 详细操作计划', '尚未持有：' + string(plan.new_position), '已经持有：' + string(plan.existing_position),
        '进入条件：', ...array(plan.entry_conditions).map(v => '- ' + v),
        '执行步骤：', ...array(plan.steps).map((v, i) => (i + 1) + '. ' + v),
        '仓位边界：' + string(plan.position_limit, JSON.stringify(plan.position_limit)),
        '复核节奏：' + string(plan.review_schedule, JSON.stringify(plan.review_schedule)),
        '退出 / 失效条件：', ...array(plan.exit_conditions).map(v => '- ' + v),
        '费用与交易检查：', ...array(plan.fee_checks).map(v => '- ' + v),
        ...(array(plan.ai_observations).length ? ['AI 补充核验点：', ...array(plan.ai_observations).map(v => '- ' + v)] : []), ''
      ] : [];
      return [
        '### ' + string(f.board_label) + ' / ' + string(f.name) + ' ' + string(f.code),
        '板块角色：' + (f.role === 'candidate' ? '条件性研究候选' : '观察优选，非买入建议'),
        '推荐指数：' + (f.recommendation_index ?? '待评估') + ' / 100；原始历史研究分：' + (f.score ?? '—') + ' / 100（不是收益概率）',
        '行动：' + string(f.action, '待核验'),
        '理由：' + string(f.reason), '失效条件：' + string(f.invalidation),
        ...(boardFundHoldings(f) ? ['披露持仓匹配：' + readable(boardFundHoldings(f)), '持仓为报告期披露样本，不代表实时完整仓位。'] : []),
        ...(f.score_explanation ? ['历史趋势分说明：' + string(f.score_explanation)] : []),
        ...(f.allocation ? ['仓位边界：' + (typeof f.allocation === 'string' ? f.allocation : JSON.stringify(f.allocation))] : []),
        '20日收益 ' + percent(m.return_20d) + '；60日收益 ' + percent(m.return_60d) + '；年化波动 ' + percent(m.volatility_annual) + '；最大回撤 ' + percent(m.max_drawdown) + '；RSI14 ' + number(m.rsi14, 1),
        ...array(q?.reasons).map(r => '- ' + r),
        ...(q?.score_components && typeof q.score_components === 'object' ? ['固定启发式评分组成（分值，非收益概率）：', ...Object.entries(q.score_components).map(([key, value]) => '- ' + key + '：' + value)] : []),
        '', ...planText
      ];
    }),
    '## 风险与反对证据', ...array(a.risks).map(s => '- ' + s),
    '', '## 下一步', ...array(a.next_steps).map(s => '- ' + s),
    '', '## 数据来源', ...array(s.sources).filter(Boolean).map(source =>
      '- ' + string(source.name, source.id) + '；状态 ' + string(source.status) + '；数据时间 ' + stamp(source.as_of) + (source.fetched_at ? '；本次获取 ' + stamp(source.fetched_at) : '') + '；' + (safeUrl(source.url) || '未提供链接') + (source.error ? '；' + source.error : '')),
    '', '## 新闻与公告', ...array(s.news).filter(Boolean).map(n =>
      '- ' + string(n.title) + ' · ' + string(n.source) + ' · ' + stamp(n.published_at) + '\n  ' + (safeUrl(n.url) || '链接未提供')),
    '', '## 数据缺口', ...array(s.warnings).map(w => '- ' + w),
    ...(record.ai_error ? ['', 'AI 解读失败：' + record.ai_error] : []),
    '', '研究分数用于解释和排序，不是收益概率。输出依赖当时的数据质量与有效期。'
  ].join('\n');
  const url = URL.createObjectURL(new Blob([text], {type: 'text/markdown;charset=utf-8'}));
  const anchor = el('a'); anchor.href = url;
  anchor.download = 'FundPilot-' + (record.time || new Date().toISOString()).slice(0, 10) + '.md';
  anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$('#export').onclick = () => { if (current) exportReport(current); };
$('#clearHistory').onclick = () => {
  if (!history.length) return toast('暂无历史记录');
  if (!confirm('清空本机保存的全部研究记录？此操作无法撤销。')) return;
  history = []; store('fundpilot_history_v3', history);
  try { localStorage.removeItem('fundpilot_history_v2'); } catch {}
  renderHistory(); toast('研究记录已清空');
};
function tick() {
  $('#beijing').textContent = new Intl.DateTimeFormat('en-GB', {timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false}).format(new Date());
  $('#today').textContent = new Intl.DateTimeFormat('zh-CN', {timeZone: 'Asia/Shanghai', year: 'numeric', month: 'long', day: 'numeric'}).format(new Date());
}
renderHistory(); status(); tick(); setInterval(tick, 1000);
Promise.allSettled([health(), loadAiConfig()]).then(() => pollAuto());


function readable(value) {
  if (value == null) return '';
  if (typeof value === 'string' || typeof value === 'number') return String(value);
  if (Array.isArray(value)) return value.map(readable).filter(Boolean).join('；');
  if (typeof value === 'object') return Object.entries(value).map(([key, item]) => key + '：' + readable(item)).join('；');
  return '';
}
function pickCount(object, names) {
  for (const name of names) {
    if (typeof object?.[name] === 'number' && Number.isFinite(object[name])) return object[name];
  }
  return null;
}
function renderHoldingPlan(parent, value) {
  if (!value) return;
  const box = el('div', undefined, 'holding-plan');
  const labels = {minimum_days:'最短观察期',minimum_calendar_days:'计划研究下限（自然日）',suggested_days:'建议持有期',horizon:'持有计划',intended_holding:'意向持有计划',entry:'进入条件',entry_conditions:'进入条件',review:'复核节奏',review_schedule:'复核节奏',exit:'退出条件',exit_conditions:'退出条件',risk_exit:'风险退出与复核',position:'仓位边界',position_limit:'仓位边界',notice:'注意事项',new_position:'尚未持有',existing_position:'已经持有',steps:'操作步骤',verification_blockers:'尚未满足的执行条件'};
  if (typeof value === 'object' && !Array.isArray(value)) {
    const brief = value.intended_holding || value.horizon || value.notice;
    if (brief) box.append(el('p', readable(brief)));
    const details = el('details',undefined,'shortlist-plan');details.append(el('summary','查看持有计划与执行条件'));
    Object.entries(value).forEach(([key, item]) => {
      if (item == null || !labels[key]) return;
      const text = readable(item);
      if (text) details.append(el('p', labels[key] + '：' + text));
    });
    if (details.children.length>1)box.append(details);
  } else box.append(el('p', '持有与复核：' + readable(value)));
  if (box.children.length) parent.append(box);
}
function renderAutoSummary(report, state = {}) {
  const strategy = report?.strategy || {};
  const panic = strategy.panic || {};
  const regime = strategy.regime || {};
  const horizon = strategy.horizon || {};
  const universe = report?.universe || {};
  const cover = universe.coverage && typeof universe.coverage === 'object' ? universe.coverage : universe;
  const quality = String(panic.quality || panic.status || regime.mode || '').toLowerCase();
  const explicitlyInvalid = /insufficient|unknown|stale|unavailable|error/.test(quality);
  const score = !explicitlyInvalid && typeof panic.score === 'number' && Number.isFinite(panic.score)
    ? Math.round(Math.max(0,Math.min(100,panic.score))) : null;
  $('#panicValue').textContent = score == null ? '—' : String(score);
  $('#panicLabel').textContent = score == null ? '数据不足 / 时效待确认' : string(panic.label, '市场压力代理');
  const override=panic.stress_override || {};
  $('#panicSummary').textContent = (readable(panic.summary) || (score == null ? '当前可用数据不足，不把未知状态显示为低风险。' : '由当前可用样本计算；不等同于未来跌幅。')) + (score != null && override.active ? ' '+readable(override.reason) : score != null && panic.extreme_drop_override ? ' 已触发极端下跌保护。' : '');
  $('#panicBar').style.width = (score == null ? 0 : score) + '%';
  const panicCard = $('#panicValue').closest('.panic-card');
  if (panicCard) panicCard.dataset.level = score == null ? 'unknown' : regime.mode === 'defensive' || override.active || score >= 70 ? 'high' : score >= 40 ? 'medium' : 'low';
  $('#panicTime').textContent = '指标时间：' + stamp(panic.as_of || report?.snapshot?.as_of);
  const panicCoverage=panic.coverage || {};
  const coverageDescription=Number.isFinite(panicCoverage.fresh_indices) ? '有效指数 '+panicCoverage.fresh_indices+' / '+(panicCoverage.total_indices ?? '未知')+'；最低要求 '+(panicCoverage.minimum_indices ?? '未提供')+' 个；行情时效上限 '+(panicCoverage.freshness_limit_hours ?? '未提供')+' 小时。' : readable(panic.coverage);
  $('#panicMethod').textContent = [readable(panic.method), coverageDescription,score != null && override.active ? '独立防御保护：'+readable(override.rule):''].filter(Boolean).join('\n');
  const components = $('#panicComponents'); components.replaceChildren();
  const entries = Array.isArray(panic.components) ? panic.components.map((v,i)=>[v?.label || v?.name || '指标 '+(i+1),Number.isFinite(v?.points)?number(v.points,1)+' / '+number(v.max_points,0)+' 分':v?.value ?? v?.score ?? v]) : Object.entries(panic.components || {});
  entries.forEach(([name, value]) => {
    const item = el('div'); item.append(el('span', name), el('b', typeof value === 'number' ? number(value,1) : readable(value))); components.append(item);
  });
  $('#regimeLabel').textContent = string(regime.label, score == null ? '数据不足' : '等待策略判断');
  $('#marketBriefTitle').textContent = string(regime.label, '市场状态仍需确认');
  $('#marketBriefReason').textContent = string(regime.reason, string(report?.analysis?.summary, '等待自动研究结果。'));
  $('#horizonLabel').textContent = string(horizon.label, '研究持有期：至少 7 天');
  $('#horizonNotice').textContent = string(horizon.notice, '7 天是计划研究与复核下限，不是锁定期或免费赎回承诺，也不代表收益保证。实际确认日、赎回费和到账时间以产品规则为准。');
  const screened = pickCount(cover, ['screened_count','screened','public_screened_count','screened_funds','ranking_count','funds_screened']);
  const deep = pickCount(cover, ['deep_count','deeply_studied_count','deep_researched_count','deep_studied','deeply_analyzed_count','deep_funds']);
  const verified = pickCount(cover, ['alipay_verified_count','alipay_verified','verified_alipay_count']);
  const total = pickCount(cover, ['total_count','total','public_total_count','catalog_count','universe_size']);
  const holdingsChecked = pickCount(cover, ['holdings_checked_total']);
  const holdingsUnchecked = pickCount(cover, ['holdings_unchecked_total']);
  const grid = $('#universeCoverage'); grid.replaceChildren();
  const coverageTiles = [[screened,'公开初筛数量'],[deep,'深入研究数量'],[verified,'支付宝可买已核验']];
  if (holdingsChecked !== null) coverageTiles.push([holdingsChecked,'持仓已预检']);
  if (holdingsUnchecked !== null) coverageTiles.push([holdingsUnchecked,'持仓待采集']);
  coverageTiles.forEach(([value,label]) => {
    const tile = el('div', undefined, 'coverage-item'); tile.append(el('b',value == null ? '未知' : value.toLocaleString()),el('span',label));grid.append(tile);
  });
  const warnings = array(universe.warnings).filter(v=>typeof v==='string');
  $('#coverageNotice').textContent = (total != null ? '公开数据目录 ' + total.toLocaleString() + ' 只；' : '')
    + (holdingsChecked !== null ? '持仓已预检 ' + holdingsChecked.toLocaleString() + ' 只；' : '')
    + (holdingsUnchecked !== null ? '尚待采集 ' + holdingsUnchecked.toLocaleString() + ' 只，按轮次继续核验。' : '')
    + '已归类数量仅统计持仓证据已通过的基金；待采集不表示市场没有对应基金。支付宝可买与费率等信息尚需来源核验。'
    + (warnings[0] ? ' ' + warnings[0] : '');
  const boards = reportSections(report || {});
  const boardCount = boards.filter(board => board.funds.length).length;
  const selectedCandidateCount = boards.reduce((count, board) => count + board.funds.filter(f => f.role === 'candidate').length, 0);
  $('#autoCandidateCount').textContent = selectedCandidateCount ? '入选研究候选 ' + selectedCandidateCount + ' 只 · 每板块最多 3 只' : '本轮暂无可推进候选';
  const shortlist = $('#autoCandidates'); shortlist.replaceChildren();
  const copy = el('p', boardCount ? boardCount + ' 个方向已整理为简明策略卡；完整理由按需展开。' : '等待扫描结果，数据不足时保持空缺。');
  const jump = el('button', '查看板块策略 ↓', 'textbtn');
  jump.type = 'button';
  jump.onclick = () => $('#boardExplorer').scrollIntoView({behavior: 'smooth', block: 'start'});
  shortlist.append(copy, jump);
  const defensive = $('#defensiveOptions');defensive.replaceChildren();
  $('#defensiveMode').textContent = string(regime.label,'等待市场模式');
  array(strategy.defensive_options).slice(0,8).forEach(option=>{
    const card=el('article',undefined,'defensive-option');
    if(typeof option==='string'){card.append(el('h3',option));defensive.append(card);return;}
    if(!option)return;
    card.append(el('h3',string(option.label,string(option.name,string(option.category,'备用方向')))));
    if(option.priority)card.append(el('span',string(option.priority),'pill'));
    const primaryReason=readable(option.reason || option.description || option.suitability);
    if(primaryReason)card.append(el('p',primaryReason));
    const details=el('details',undefined,'defensive-details');details.append(el('summary','依据与适用条件'));
    ['risk','risks','limitations','note','notice','action','operation'].forEach(key=>{if(option[key])details.append(el('p',readable(option[key])));});
    if(array(option.examples).length)details.append(el('p','目录示例（可买资格未核验）：'+array(option.examples).slice(0,3).map(v=>string(v.name)+' '+string(v.code)).join('、')));
    if(option.holding_plan)renderHoldingPlan(details,option.holding_plan);
    if(details.children.length>1)card.append(details);
    defensive.append(card);
  });
  if(!defensive.children.length)defensive.append(el('p','等待防守方向评估；数据不足时保留现金与暂停新仓的选择。','muted'));
}
function renderAutoState(state) {
  latestAutoState=state;
  if (state.ai_config) applyAiConfig(state.ai_config);
  updateScheduleFields('ai', state.ai_schedule || state.ai_config?.schedule);
  updateScheduleFields('api', state.ai_schedule || state.ai_config?.schedule);
  const statusLabels={idle:'准备开始自动扫描',running:'正在自动扫描公开基金池',ready:'本轮自动研究已完成',error:'本轮扫描暂未完成'};
  $('#autoStatus').textContent=statusLabels[state.status] || '正在检查自动研究状态';
  const progress=state.progress;
  const progressNames={screened_count:'已初筛',deep_done:'已深研',deep_total:'计划深研',total_count:'目录总数',stage:'阶段'};
  const progressText=progress && typeof progress==='object' ? Object.entries(progress).map(([k,v])=>(progressNames[k]||k)+'：'+readable(v)).join(' · ') : readable(progress);
  $('#autoStatusDetail').textContent=state.error ? '扫描异常：'+readable(state.error)+'。已有报告会保留。' : [readable(state.stage),progressText].filter(Boolean).join(' · ') || '系统自动获取数据、筛选基金并形成操作计划，无需填写代码。';
  $('#autoSchedule').textContent=[state.completed_at?'最近完成 '+stamp(state.completed_at):'',state.next_run_at?'下次扫描 '+stamp(state.next_run_at):'扫描期间约每 5 秒检查进度'].filter(Boolean).join(' · ');
  $('#autoRefresh').disabled=state.status==='running';
  $('#autoRefresh').textContent=state.status==='running'?'正在扫描…':'重新扫描市场 ↻';
  if(state.report) {
    const id=state.completed_at || state.report.snapshot?.as_of || '';
    const displayKey=id+'|'+Boolean(state.report_stale)+'|'+String(state.report.strategy?.regime?.mode)
      +'|'+String(state.report.ai_research?.status)+'|'+String(state.report.ai_research?.analyzed_count)
      +'|'+String(state.report.board_schema_version)+'|'+String(state.report_version || '');
    if(id && displayKey!==displayedAutoId && !running && !manualReportActive){
      const report=state.report;
      validateResponse(report);
      const record={...report,report_stale:Boolean(state.report_stale),time:state.completed_at || new Date().toISOString(),auto_id:id,auto_scan:true,prefs:report.prefs || prefs};
      render(record,false);renderAutoSummary(report,state);displayedAutoId=displayKey;connected=true;
      if(!state.report_stale && !history.some(r=>r.auto_id===id)){history.unshift(compactRecord(record));persistHistory();renderHistory();}
      status();
    } else if (!manualReportActive) renderAutoSummary(state.report,state);
  }
  renderAiResearch(state);
}
async function loadAutoReport(state) {
  if (autoReportBusy || !state.has_report || state.report_version === loadedAutoReportVersion) return;
  autoReportBusy = true;
  const notice = $('#autoReportNotice');
  notice.hidden = false;
  notice.textContent = '正在加载最新研究报告，后台状态检查正常；已有报告会保留。';
  // A new version may represent expired evidence or a changed AI configuration.
  // Retain the old report for viewing, but suspend its current recommendations.
  if (!manualReportActive && current?.engine === 'automatic' && !current.report_stale) {
    current.report_stale = true;
    renderFundBoards(current);
    renderAutoSummary(null, state);
  }
  try {
    const response = await fetch('/api/auto/report', {signal:AbortSignal.timeout(60000)});
    const data = await response.json();
    if (!response.ok || !data.report) throw new Error('研究报告暂未加载完成');
    // A scan/config change during download must not overwrite newer status.
    if (!connected || latestAutoState?.report_version !== data.report_version) return;
    renderAutoState({...latestAutoState, report:data.report, report_stale:data.report_stale});
    loadedAutoReportVersion = data.report_version;
    loadedAutoReport = data.report;
    notice.hidden = true;
  } catch {
    notice.textContent = '后台状态检查正常，研究报告加载尚未完成，将自动重试；已有报告仅供回看。';
  } finally { autoReportBusy = false; }
}
async function pollAuto() {
  if(autoPollBusy)return;
  autoPollBusy=true;
  clearTimeout(autoTimer);
  let delay=30000;
  try {
    const response=await fetch('/api/auto/status?summary=1',{signal:AbortSignal.timeout(12000)});
    const data=await response.json();
    if(!response.ok)throw new Error(data.error || '自动研究服务暂不可用');
    renderAutoState(data.report_version === loadedAutoReportVersion && loadedAutoReport
      ? {...data, report:loadedAutoReport} : data);
    connected=true;status();
    loadAutoReport(data);
    if (!aiConfigBusy && Date.now() - aiConfigCheckedAt > 60000) loadAiConfig();
    delay=['idle','running'].includes(data.status)?5000:30000;
  } catch(error) {
    connected=false;status();
    $('#autoStatus').textContent='自动研究状态暂时不可用';
    const age=latestAutoState?.completed_at ? Date.now()-new Date(latestAutoState.completed_at).getTime() : Infinity;
    $('#autoStatusDetail').textContent=(error.name==='TimeoutError'?'状态检查超时，将自动重试。':error.message+'，将自动重试。')+' 当前显示的是上次成功报告，不能确认最新市场状态。';
    if(!manualReportActive && (!Number.isFinite(age) || age>3600000)) {
      if(current?.engine==='automatic') {
        current.report_stale=true;renderFundBoards(current);
      }
      $('#panicValue').textContent='—';$('#panicLabel').textContent='研究连接中断 · 数据待更新';
      $('#panicBar').style.width='0%';$('#panicValue').closest('.panic-card').dataset.level='unknown';
      $('#panicSummary').textContent='无法确认最新研究状态，已暂停展示当前恐慌分。历史报告仍可回看。';
      $('#regimeLabel').textContent='待更新，暂停新判断';
    } else if(!manualReportActive) {
      $('#panicLabel').textContent='缓存快照 · 最新状态未确认';
      $('#panicSummary').textContent='当前值来自上次成功报告；状态检查暂时失败，系统会自动重试。';
    }
    $('#autoRefresh').disabled=false;$('#autoRefresh').textContent='重试自动扫描 ↻';
  } finally{autoPollBusy=false;autoTimer=setTimeout(pollAuto,delay);}
}
$('#autoRefresh').onclick=async()=>{
  if(autoPollBusy || latestAutoState?.status==='running')return;
  $('#autoRefresh').disabled=true;
  try{
    const response=await fetch('/api/auto/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',signal:AbortSignal.timeout(12000)});
    const data=await response.json();if(!response.ok)throw new Error(data.error || '无法启动扫描');
    manualReportActive=false;displayedAutoId='';
    if(data.status)renderAutoState(data);
    loadAutoReport(data);
    toast('自动扫描已启动，将持续更新进度');pollAuto();
  }catch(error){toast(error.message);$('#autoRefresh').disabled=false;}
};


function concise(value, maximum = 86, fallback = '') {
  const text = string(value, fallback).replace(/\s+/g, ' ').trim();
  return text.length > maximum ? text.slice(0, maximum - 1) + '…' : text;
}
function fundCategory(fund, record) {
  const q = array(record.quant).find(item => item?.code === fund.code);
  const basic = array(record.snapshot?.funds).find(item => item?.code === fund.code);
  const value = string(fund.asset_class, string(q?.asset_class, string(basic?.asset_class, string(basic?.fund_type))));
  if (/货币|money_market/i.test(value)) return ['money_market', '货币与现金管理'];
  if (/黄金|gold/i.test(value)) return ['gold', '黄金与商品'];
  if (/债|bond|fixed_income/i.test(value)) return ['bond', '债券与稳健方向'];
  if (/QDII|海外|纳斯达克|标普|恒生|港股|overseas|global/i.test(value)) return ['overseas', '海外与跨境'];
  if (/银行|证券|半导体|芯片|医药|新能源|科技|军工|消费|行业|sector/i.test(value)) return ['sector', '行业与主题'];
  if (/指数|沪深|中证|创业板|宽基|equity|stock|index/i.test(value)) return ['equity', '权益与指数'];
  if (/混合|mixed|hybrid/i.test(value)) return ['mixed', '混合与主动管理'];
  return ['other', '其他研究方向'];
}
function reportSections(record) {
  const referencedBoards=array(record.board_coverage).filter(board=>array(board?.reference_candidates).some(reference=>
    reference?.direct_selection!==false && /^\d{6}$/.test(reference?.code)
    && ['yangjibao','user_reference','web_discovery'].includes(reference?.source_kind)));
  if (Array.isArray(record.sections) || referencedBoards.length) {
    // Older cached reports may omit pending members. Membership is enough for
    // display; quantitative and holdings evidence remain explicitly unknown.
    const sourceSections=array(record.sections).map(section=>({...section,funds:[...array(section?.funds)]}));
    referencedBoards.forEach(board=>{
      let section=sourceSections.find(item=>item.id===board.id);
      if (!section) { section={...board,funds:[]};sourceSections.push(section); }
      array(board.reference_candidates).forEach(reference=>{
        if (reference?.direct_selection===false || !/^\d{6}$/.test(reference?.code)
          || !['yangjibao','user_reference','web_discovery'].includes(reference?.source_kind)
          || section.funds.some(fund=>fund?.code===reference.code)) return;
        const match={status:'unknown',matched_disclosed_pct:reference.matched_disclosed_pct,
          matched_weight_pct:reference.matched_weight_pct,disclosed_weight_pct:reference.disclosed_weight_pct,
          report_date:reference.report_date,ratio_is_lower_bound:reference.ratio_is_lower_bound,
          reason:'已按来源纳入本板块；真实持仓与量化资料继续独立核验。'};
        section.funds.push({code:reference.code,name:reference.name && reference.name!==reference.code?reference.name:'*****',
          reference_candidate:{...reference,requested_board_id:board.id},direct_selection:true,board_label:board.label,
          board_match:match,role:'observation',score:null,recommendation_index:null,metrics:{},
          action:'已强制纳入板块 · 数据核验中',execution_eligible:false,verified_buyable:false,
          brief:{headline:'已纳入本板块，等待自动研究',reason:'来源分类已收录；未知字段统一显示为 *****。',risk:'推荐指数、风险与可购条件继续核验。'},
          operation_plan:{new_position:'操作条件：*****；资料核验完成后更新。',existing_position:'结合实际仓位复核，资料补齐后更新策略。',review_schedule:'后续自动研究继续核验。'},
          source_url:reference.source_url});
      });
    });
    const referencePriority=(fund,boardId)=>{
      const reference=fund.reference_candidate || array(record.snapshot?.funds).find(item=>item?.code===fund.code)?.reference_candidate;
      if (reference?.direct_selection === false || reference?.requested_board_id !== boardId) return 0;
      if (reference?.forced_selection === true || reference?.source_kind === 'web_discovery') return 2;
      return ['yangjibao','user_reference'].includes(reference?.source_kind) ? 1 : 0;
    };
    const winners = new Map();
    const prepared = sourceSections.filter(s => s && typeof s === 'object').map(section => {
    const seen = new Set();
    const coverage = array(record.board_coverage).find(board => board.id === section.id);
    const requiresMatch = section.requires_holdings_match === true || coverage?.requires_holdings_match === true;
    const result = {...coverage, ...section, requires_holdings_match: requiresMatch, funds: array(section.funds).filter(f => {
      if (!f || typeof f.name !== 'string') return false;
      if (requiresMatch && !boardFundHasCurrentHoldings(f) && !referencePriority(f,section.id)) return false;
      const key = f.code || f.name;
      if (seen.has(key)) return false; seen.add(key); return true;
    })};
    result.funds.forEach(fund => {
      const key = fund.code || fund.name;
      const match = boardFundHoldings(fund);
      const ratio = Number.isFinite(match?.matched_disclosed_pct) ? match.matched_disclosed_pct : -1;
      const reference=referencePriority(fund,section.id);
      // Server comparisons are already ordered by exact exposure then specificity.
      const primary = array(fund.board_comparison)[0]?.id;
      const preferred = primary === section.id;
      const depth = Number(result.hierarchy_depth || result.specificity || 0);
      const previous = winners.get(key);
      if (!previous || reference > previous.reference || (reference === previous.reference &&
          (ratio > previous.ratio || (ratio === previous.ratio &&
          (Number(preferred) > Number(previous.preferred) || (preferred === previous.preferred && depth > previous.depth)))))) {
        winners.set(key, {section:result, fund, ratio, preferred, depth, reference});
      }
    });
    return result;
  });
    return prepared.map(section => ({...section, funds:section.funds
      .filter(fund => referencePriority(fund,section.id)>0 || winners.get(fund.code || fund.name)?.section === section)
      .sort((a,b) => referencePriority(b,section.id)-referencePriority(a,section.id)
        || (boardFundHoldings(b)?.matched_disclosed_pct ?? -1) - (boardFundHoldings(a)?.matched_disclosed_pct ?? -1))
      .slice(0,3)}));
  }
  const groups = new Map();
  array(record.analysis?.funds).filter(f => f && typeof f.name === 'string').forEach(fund => {
    const [id, label] = fundCategory(fund, record);
    if (!groups.has(id)) groups.set(id, {id, label, description: '旧报告按资产类别归组，仅保留原报告顺序中的前三只观察样本。', status: 'observation', selection_method: '旧报告未保存同类优选规则；不重新比较不同类别分数。', funds: []});
    const section = groups.get(id);
    if (section.funds.length < 3 && !section.funds.some(f => f.code === fund.code && f.name === fund.name)) section.funds.push({
      ...fund,
      role: 'observation',
      action: '历史观察记录 · 不沿用旧交易指令',
      execution_eligible: false,
      can_trade: false,
      brief: {
        headline: '保留历史观察，等待最新研究',
        reason: '旧报告未保存同类筛选结果，当前仅供复盘，不构成新的买入或卖出判断。',
        risk: '旧报告的行情、资格和操作条件可能已经变化，不沿用原建仓或加减仓步骤。',
        score_label: '历史趋势分'
      },
      operation_plan: {
        new_position: '保持观察，不依据旧报告建立或增加仓位。',
        existing_position: '结合最新数据和实际仓位重新评估，不沿用旧报告的买卖或分批指令。',
        entry_conditions: [],
        steps: ['等待当前时点的新研究报告。', '重新核对数据时间、风险状态和交易条件后再评估。'],
        exit_conditions: ['旧报告的退出条件仅作复盘，不直接作为当前交易指令。'],
        review_schedule: '新的研究快照生成后重新复核。',
        fee_checks: ['原记录不能证明当前可买资格、费率或赎回条件。']
      }
    });
  });
  return [...groups.values()];
}
function selectedFunds(record) {
  return reportSections(record).flatMap(section => {
    const board = array(record.board_coverage).find(item=>item.id===section.id) || section;
    return section.funds.map(fund => ({...fund, board_label: section.label,
      recommendation_index: boardOpportunity(record, {...board, status:fund.role==='candidate'?'candidate':'observation'}, {funds:[fund]}).recommendation_index}));
  });
}
function addPlanDetails(parent, plan) {
  if (!plan || typeof plan !== 'object') return;
  const content = el('div', undefined, 'operation-content');
  [['未持有', plan.new_position], ['已持有', plan.existing_position], ['持有期', plan.holding_horizon || plan.intended_holding], ['仓位边界', plan.position_limit], ['复核节奏', plan.review_schedule]].forEach(([label, value]) => {
    if (value) content.append(el('h4', label), el('p', readable(value)));
  });
  [['进入条件', plan.entry_conditions], ['执行步骤', plan.steps], ['退出 / 失效条件', plan.exit_conditions || plan.risk_exit], ['费用与交易检查', plan.fee_checks], ['AI 补充核验点', plan.ai_observations]].forEach(([label, values]) => {
    if (!array(values).length) return;
    content.append(el('h4', label));
    const list = el(label === '执行步骤' ? 'ol' : 'ul');
    array(values).slice(0, 12).forEach(value => list.append(el('li', readable(value))));
    content.append(list);
  });
  parent.append(content);
}
function filterResearchBoards(boards, group = 'all', query = '') {
  const needle = typeof query === 'string' ? query.toLocaleLowerCase() : '';
  return (Array.isArray(boards) ? boards : []).filter(board => {
    if (!board || (group !== 'all' && (group === 'finance' ? board.family !== 'finance' : board.group !== group))) return false;
    const text = [board.label, board.description, ...(Array.isArray(board.aliases) ? board.aliases : [])]
      .filter(value => typeof value === 'string').join(' ').toLocaleLowerCase();
    return !needle || text.includes(needle);
  });
}
function partitionResearchBoards(boards) {
  const evaluated = [], pending = [];
  (Array.isArray(boards) ? boards : []).forEach(board => {
    const scored=Number.isFinite(board?.opportunity?.recommendation_index);
    const included=board?.displayed_count>0 && array(board?.reference_candidates).some(item=>item?.direct_selection!==false
      && ['yangjibao','user_reference','web_discovery'].includes(item?.source_kind));
    if (scored || included) evaluated.push(board);
    if (!scored) pending.push(board);
  });
  return {evaluated, pending};
}
function boardPendingReason(board, opportunity = {}, record = {}) {
  if (record.report_stale) return '上次报告已过期，正在等待新数据';
  const reasons = {
    holdings_pending: '缺少持仓资料，暂时无法确认基金投向',
    holdings_mismatch: '已披露的持仓与这个方向不符',
    no_match: '本轮已采集持仓尚无基金归入此方向，未采集部分仍在核验队列',
    source_unavailable: '该方向的专属证据来源尚未接入，当前无法确认归属',
    excluded: '相关基金未通过数据或产品初筛',
    not_researched: '已找到相关基金，尚未完成深入研究',
    insufficient: '最新净值不足或过期，暂时无法评分',
    unknown: '本次研究尚未形成结论'
  };
  if (reasons[board?.status]) return reasons[board.status];
  const reason = typeof opportunity.reason === 'string' ? opportunity.reason : '';
  if (/市场状态|报告过期/.test(reason)) return '行情数据需要更新，暂时无法评分';
  if (/持仓/.test(reason)) return '持仓与风险资料尚不完整';
  if (/风险/.test(reason)) return '风险指标尚不完整，暂时无法评分';
  return '可用研究资料不足，暂时无法评分';
}
function boardResearchGap(board, record = {}) {
  const saved = board?.research_gap && typeof board.research_gap === 'object' ? board.research_gap : {};
  const definitions = {
    holdings: {label:'持仓与投向', next:'后续研究继续核对已接入的披露持仓；缺少主题证据来源时，保持空缺。'},
    stale_data: {label:'数据需更新', next:'后续扫描重新获取净值与行情，待样本及数据时效通过检查后再评估。'},
    screening: {label:'初筛受限', next:'后续扫描重新检查公开样本的产品类型、数据与限制，未通过条件的基金继续排除。'},
    not_researched: {label:'尚未深研', next:'后续扫描按研究范围与预算继续筛选；有可用证据时再研究，每板块最多三只。'},
    no_match: {label:'尚无已归类样本', next:'继续轮换采集公开持仓，按各板块匹配比例计算归属；当前为零不代表市场没有此类基金。'},
    insufficient: {label:'资料不足', next:'等待有效净值、风险资料或分类证据；尚未接入的来源不能保证下轮自动补齐。'}
  };
  const aliases = {holdings_pending:'holdings',holdings_mismatch:'holdings',data_quality:'stale_data',coverage:'not_researched',no_sample:'no_match',unknown:'insufficient'};
  const statuses = {holdings_pending:'holdings',holdings_mismatch:'holdings',source_unavailable:'holdings',excluded:'screening',not_researched:'not_researched',no_match:'no_match',insufficient:'stale_data'};
  const raw = saved.category || statuses[board?.status]
    || (board?.requires_holdings_match===true && /持仓/.test(board?.opportunity?.reason || '')?'holdings':'insufficient');
  const category = record.report_stale ? 'stale_data' : definitions[raw] ? raw : aliases[raw] || 'insufficient';
  const counts = saved.counts && typeof saved.counts === 'object' ? saved.counts : {};
  const count = (key, alias) => {
    if (board?.catalog_counts_known === false && ['screened_count','eligible_count'].includes(key)) return null;
    for (const value of [counts[key],counts[alias],board?.[key]]) if (Number.isInteger(value) && value >= 0) return value;
    return null;
  };
  const queue = board?.id === 'holdings_unclassified';
  const forced = array(board?.reference_candidates).some(item => item?.forced_selection === true || item?.source_kind === 'web_discovery')
    || array(board?.web_search?.candidates).some(item => item?.forced_selection === true);
  const forcedNext = '已强制纳入该板块；未知数据统一标记为 *****。系统会继续自动核验产品身份、净值、风险、披露持仓、板块匹配比例与可购资格。';
  return {category, group_label:definitions[category].label,
    label:typeof saved.label === 'string' ? saved.label : definitions[category].label,
    summary:record.report_stale ? '上次报告已过期，当前结论等待新数据。'
      : queue ? '这是持仓采集与归类队列：尚未采集、资料无效或尚无多数持仓匹配的基金等待核验；它不是投资板块。'
      : typeof saved.summary === 'string' && saved.summary ? saved.summary : boardPendingReason(board,board?.opportunity,record),
    next_step:forced ? forcedNext + (record.report_stale ? ' 当前报告已过期，正在等待更新。' : '')
      : record.report_stale ? definitions.stale_data.next
      : typeof saved.next_step === 'string' && saved.next_step ? saved.next_step : definitions[category].next,
    automatic:!record.report_stale && typeof saved.automatic === 'boolean' ? saved.automatic : null,
    counts:{screened_count:count('screened_count','screened'),eligible_count:count('eligible_count','eligible'),
      deep_count:count('deep_count','deep'),valid_quant_count:count('valid_quant_count','valid_quant'),matched_holdings_count:count('matched_holdings_count','matched_holdings')},
    examples:(Array.isArray(saved.examples) ? saved.examples : []).filter(item=>item && typeof item==='object').slice(0,3)};
}
function boardDeepCountText(board) {
  const count = Number.isInteger(board?.deep_count) && board.deep_count >= 0 ? board.deep_count : null;
  return count === null ? '深研数量 ***** · 当前上限 3 只'
    : count > 3 ? '历史已深研 '+count+' 只 · 当前上限 3 只' : '已深研 '+count+' / 最多 3 只';
}
function holdingsMatchSummary(match) {
  if (match?.status==='not_required') return {title:'按资产类型归类',note:'此方向不以股票主题持仓归类。'};
  const ratio=match?.matched_disclosed_pct;
  return {title:Number.isFinite(ratio)?'已披露股票匹配 '+(match.ratio_is_lower_bound?'已确认至少 ':'')+holdingsRatioText(ratio,match.ratio_is_lower_bound):'已披露股票匹配 *****',
    note:'各板块分别计算，唯一归入最高匹配方向；同比例优先细分板块。大部分符合即可（超过一半），比例越高越优先；仅报告已披露部分，不代表全仓或实时仓位，名称只作展示。'+(match.ratio_is_lower_bound?' 分类待核验部分仍计入分母。':'')};
}
function holdingsRatioText(value, lowerBound=false) {
  if (!Number.isFinite(value)) return '*****';
  // Lower bounds round down: never claim ≥66.67 when confirmed is 66.666… .
  return (lowerBound?Math.floor(value*100)/100:value).toFixed(2)+'%';
}
function holdingsBoardComparison(fund, currentBoardId) {
  const seen = new Set();
  return array(fund?.board_comparison).filter(item => {
    const ratio = item?.matched_disclosed_pct;
    if (!item || typeof item.id !== 'string' || seen.has(item.id) ||
        !Number.isFinite(ratio) || ratio < 0 || ratio > 100) return false;
    seen.add(item.id); return true;
  }).map((item,index) => ({...item, order:index, selected:item.id===currentBoardId}))
    .sort((a,b) => b.matched_disclosed_pct-a.matched_disclosed_pct || Number(b.selected)-Number(a.selected) || a.order-b.order)
    .slice(0,6);
}
function holdingsEvidenceDates(match) {
  const valid = value => typeof value==='string' && /^\d{4}-\d{2}-\d{2}$/.test(value)
    && Number.isFinite(Date.parse(value+'T00:00:00Z')) && new Date(value+'T00:00:00Z').toISOString().slice(0,10)===value;
  const observed = [match?.mapping_date, ...array(match?.mapping_source_dates), ...array(match?.source_dates),
    ...array(match?.classification_dates), ...array(match?.mapping_dates)];
  array(match?.stock_evidence).forEach(stock => {
    observed.push(stock.mapping_date, stock.tag_source_date);
    array(stock.membership_sources || stock.mapping_sources).forEach(source => observed.push(source?.source_date));
  });
  return {report_date:valid(match?.report_date)?match.report_date:null,
    mapping_dates:[...new Set(observed.filter(valid))].sort()};
}
function holdingsCoverageModel(record, boards = []) {
  const coverage = record?.universe?.coverage || record?.universe || {};
  const count = value => Number.isInteger(value) && value>=0 ? value : null;
  const investmentBoards = array(boards).filter(board=>board?.id!=='holdings_unclassified');
  return {checked:count(coverage.holdings_checked_total),unchecked:count(coverage.holdings_unchecked_total),
    directions:investmentBoards.length,dynamic:investmentBoards.filter(board=>board.dynamic===true).length};
}
function boardWebSearchModel(board) {
  const search=board?.web_search;
  if (!search || typeof search!=='object' || Array.isArray(search)) return null;
  const candidates=(Array.isArray(search.candidates)?search.candidates:[]).filter(item=>item && typeof item==='object');
  const labels={ok:'已完成搜索',success:'已完成搜索',completed:'已完成搜索',found:'已完成搜索',partial:'搜索部分完成',
    error:'搜索失败',failed:'搜索失败',no_results:'未找到有效候选',empty:'未找到有效候选',no_match:'未找到有效候选',
    pending:'等待搜索',not_searched:'尚未搜索',not_attempted:'尚未搜索',skipped:'本轮未执行搜索',disabled:'搜索尚未启用'};
  const statuses={discovery_only:'已强制纳入板块 · 待核验',forced_selection:'已强制纳入板块 · 待核验',screened:'已完成初筛',research_selected:'已进入深研计划',
    excluded:'未通过初筛',not_in_current_ranking:'未进入本轮公开排行',identity_conflict:'产品身份待复核'};
  const forced=search.status==='discovery_only' || candidates.some(item=>item?.forced_selection === true || item?.status === 'discovery_only');
  return {label:forced?'已强制纳入 · 待核验（'+(labels[search.status] || '*****')+'）':labels[search.status] || '*****',status:search.status,query:typeof search.query==='string'?search.query:'',
    searched_at:search.searched_at,reason:[search.error,search.reason,search.message].filter(value=>typeof value==='string' && value).join('；'),
    record_label:search.from_previous_run===true?'上次搜索记录':search.cache_hit===true?'复用搜索记录':'搜索记录',
    attempts:Number.isInteger(search.attempts)?search.attempts:Array.isArray(search.attempts)?search.attempts.length:null,
    total:candidates.length,candidates:candidates.slice(0,3).map(item=>({...item,state_label:statuses[item.status] || '*****'}))};
}
function marketOverviewModel(record = {}) {
  const saved = record.market_overview && typeof record.market_overview === 'object' ? record.market_overview : null;
  const snapshot = record.snapshot || {};
  const overview = saved || {as_of:snapshot.as_of,
    indices:(Array.isArray(snapshot.market) ? snapshot.market : []).map(item => ({...item,value:item.last,status:'unknown'})),
    breadth:{status:'insufficient',reason:'这份报告没有保存可用的基金单日涨跌样本，分布将在数据更新后显示。'}};
  const indices = (Array.isArray(overview.indices) ? overview.indices : []).filter(item => item && typeof item === 'object').slice(0,3);
  const breadth = overview.breadth && typeof overview.breadth === 'object' ? overview.breadth : {};
  const validCount = value => typeof value === 'number' && Number.isInteger(value) && value >= 0;
  const total = breadth.covered_count ?? breadth.total;
  const countsValid = [total,breadth.up,breadth.down,breadth.flat].every(validCount)
    && total > 0 && breadth.up + breadth.down + breadth.flat === total;
  const buckets = (Array.isArray(breadth.buckets) ? breadth.buckets : []).filter(item => item && typeof item === 'object');
  const bucketsValid = buckets.length > 0 && buckets.every(item => validCount(item.count)
    && ['up','down','flat'].includes(item.direction)) && buckets.reduce((n,item)=>n+item.count,0) === total;
  const usable = ['ok','partial'].includes(breadth.status) && countsValid && bucketsValid
    && typeof breadth.nav_date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(breadth.nav_date);
  return {as_of:overview.as_of, indices, breadth, buckets, total, usable, stale:record.report_stale === true};
}
function fundResearchState(fund, plan = {}) {
  const action = typeof fund?.action === 'string' ? fund.action : '';
  const riskBlocked = (Array.isArray(fund?.risk_flags) && fund.risk_flags.length > 0)
    || fund?.risk_check_complete === false || (typeof fund?.quality === 'string' && fund.quality !== 'ok')
    || /阻断|暂停|暂缓|数据不足|防御|风险超限|减仓|卖出|退出/.test(action);
  const executionUnverified = fund?.execution_eligible === false || fund?.can_trade === false
    || fund?.verified_buyable === false || fund?.alipay_available === 'unverified'
    || fund?.platform_eligibility === 'unknown'
    || /待核验|待产品核验/.test(action)
    || /未核验|未完成|待核验/.test(typeof plan.new_position === 'string' ? plan.new_position : '');
  const candidate = fund?.role === 'candidate';
  return {riskBlocked, executionUnverified, candidate,
    tone: riskBlocked ? 'blocked' : candidate ? 'candidate' : 'observation',
    label: riskBlocked ? '本轮暂缓 · 风险条件未通过'
      : fund?.direct_selection === true && !fund?.quality ? '已纳入板块 · 数据核验中'
      : candidate ? executionUnverified ? '研究候选 · 可买状态尚未确认' : '条件性研究候选'
      : executionUnverified ? '观察优选 · 可买状态尚未确认' : '观察优选 · 非买入建议'};
}
function isYangjibaoBoardReference(reference) {
  return ['yangjibao','user_reference'].includes(reference?.source_kind);
}
function boardClassificationCopy(record={}) {
  const hasReferences=[...array(record.candidate_references),
    ...array(record.board_coverage).flatMap(board=>array(board?.reference_candidates)),
    ...array(record.sections).flatMap(board=>array(board?.funds).map(fund=>fund?.reference_candidate))]
    .some(isYangjibaoBoardReference);
  const summary=hasReferences?'养基宝分类基金按指定板块展示；其余按持仓归类，真实比例独立计算':'每只基金仅归入最高匹配板块';
  const footer=hasReferences?'基金名称只用于展示。'+summary+'。报告期持仓存在滞后，基金表现不等于行业指数表现。'
    :'名称只用于展示。每只基金归入持仓匹配最高的一个板块，同比例细分优先；同板块比例越高越优先。报告期持仓存在滞后，基金表现不等于行业指数表现。';
  const method=(hasReferences?'基金名称只用于展示。养基宝分类基金按指定板块展示，并优先保留来源成员；其余基金按持仓匹配比例最高的板块归类，同比例优先更细分方向，再按匹配比例从高到低选择。真实比例独立计算，每板块最多3只。'
    :'基金名称只用于展示。按各板块分别计算持仓匹配比例，每只基金只归入比例最高的一个板块；同比例优先更细分的方向。已确认超过一半符合即可，同板块按匹配比例从高到低选取最多3只。')
    +'匹配比例＝符合本板块的股票权重÷已披露股票总权重。分类资料不完整时标注“已确认至少”，未分类股票仍计入分母。卡片显示两种比例、持仓报告日与成分分类映射日；最新指数成分不表示报告日成分。披露可能只覆盖前十大股票，不能视为实时完整仓位；匹配比例不等于推荐指数或收益概率。';
  return {summary,footer,method};
}
function boardReferenceCandidatesModel(board) {
  const labels={displayed:'已纳入本板块展示',forced_displayed:'已强制纳入本板块展示',forced_pending:'已强制纳入板块 · 待核验',researched:'已完成净值研究',holdings_verified:'持仓已核验',
    reclassified:'按持仓归入其他板块',holdings_pending:'持仓资料待完善',excluded:'本轮初筛未通过',
    not_in_catalog:'本轮基金目录未覆盖',board_missing:'板块证据待补充'};
  const seen=new Set();
  return array(board?.reference_candidates).filter(item=>{
    if (!item || typeof item!=='object' || !/^\d{6}$/.test(item.code) || seen.has(item.code)) return false;
    seen.add(item.code);return true;
  }).map(item=>{
    const ratio=typeof item.matched_disclosed_pct==='number' && Number.isFinite(item.matched_disclosed_pct)
      && item.matched_disclosed_pct>=0 && item.matched_disclosed_pct<=100 ? item.matched_disclosed_pct : null;
    const lower=item.ratio_is_lower_bound===true;
    const changed=item.status==='reclassified' && typeof item.actual_board_label==='string' && item.actual_board_label;
    return {...item,ratio_text:ratio===null?'*****':(lower?'已确认至少 ':'')+holdingsRatioText(ratio,lower),
      state_label:labels[item.status] || '*****',
      assignment_text:changed?'实际归属：'+item.actual_board_label:'',
      source_label:typeof item.source_label==='string' && item.source_label?item.source_label:'养基宝板块分类（用户提供）',
      name:typeof item.name==='string' && item.name?item.name:item.code};
  });
}
function renderBoardReferenceCandidates(parent, board) {
  const candidates=boardReferenceCandidatesModel(board);
  if (!candidates.length) return;
  const details=el('details',undefined,'board-reference-candidates');
  const summary=el('summary');
  const hasForced=candidates.some(item=>item.forced_selection===true || item.source_kind==='web_discovery');
  const hasYangjibao=candidates.some(item=>['yangjibao','user_reference'].includes(item.source_kind));
  summary.append(el('span',hasForced?'板块来源基金 · 强制纳入优先':hasYangjibao?'养基宝板块基金':'板块来源基金'),el('b',candidates.length+' 只'),el('small','查看持仓匹配与归属'));
  details.append(summary);
  const rows=el('div',undefined,'board-reference-list');
  candidates.forEach(item=>{
    const row=el('article',undefined,'board-reference-row');row.dataset.status=item.status;
    const identity=el('div',undefined,'board-reference-identity');
    identity.append(el('b',item.name),el('span',item.code+' · '+item.source_label));
    const ratio=el('div',undefined,'board-reference-ratio');
    ratio.append(el('strong',item.ratio_text,item.ratio_text==='*****'?'unknown-mask':undefined),el('small','本板块 / 已披露股票'));
    const state=el('div',undefined,'board-reference-state');
    state.append(el('span',item.state_label));
    if (item.assignment_text) state.append(el('b',item.assignment_text));
    if (typeof item.reason==='string' && item.reason) state.append(el('p',item.reason));
    const footer=el('div',undefined,'board-reference-footer');
    const reportDate = typeof item.report_date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(item.report_date)
      ? item.report_date : '*****';
    footer.append(el('span','持仓报告日：'+reportDate));
    if (item.source_url) footer.append(link('基金公开资料 ↗',item.source_url));
    row.append(identity,ratio,state,footer);rows.append(row);
  });
  details.append(rows,el('p',hasYangjibao
    ? '按养基宝板块分类收录；持仓占比来自公开报告。比例仅代表已披露部分。'
    : hasForced
      ? '已强制纳入该板块；持仓占比来自公开报告，未知字段统一标记为 *****。'
      : '来源板块只决定先放入观察清单；持仓占比来自公开报告，比例仅代表已披露部分。','board-reference-note'));
  parent.append(details);
}
function renderFundBoards(record) {
  const box = $('#funds'); box.replaceChildren();
  const classificationCopy=boardClassificationCopy(record);
  const classificationNote=$('#boardClassificationNote');
  const classificationMethod=$('#boardClassificationMethod');
  if (classificationNote) classificationNote.textContent=classificationCopy.footer;
  if (classificationMethod) classificationMethod.textContent=classificationCopy.method;
  const sourceSections = reportSections(record);
  const coverage = array(record.board_coverage).length ? record.board_coverage.map(board=>({...board,
    displayed_count:array(sourceSections.find(section=>section.id===board.id)?.funds).length}))
    : sourceSections.map(s => ({...s, displayed_count:s.funds.length, deep_count:Number.isInteger(s.deep_count)?s.deep_count:null, catalog_counts_known:false, status:s.status, group:s.group || 'other', reason:'此报告未保存全量板块覆盖状态。'}));
  const boardOrder = new Map(rankResearchBoards(record, coverage, sourceSections).map((board, index) => [board.id, index]));
  const allSections = [...sourceSections].sort((a,b) => (boardOrder.get(a.id) ?? 999) - (boardOrder.get(b.id) ?? 999));
  renderBoardExplorer(record, coverage, allSections);
  const matchingIds = new Set(filterResearchBoards(coverage, boardFilter.group, boardFilter.query).map(board => board.id));
  const matchingSections = allSections.filter(section => matchingIds.has(section.id));
  let sections = boardFilter.id === 'all' ? matchingSections : allSections.filter(s => s.id === boardFilter.id);
  if (!sections.length && boardFilter.id && boardFilter.id !== 'all') {
    const board = coverage.find(b => b.id === boardFilter.id);
    if (board) sections = [{...board, funds:[], empty_reason:board.reason}];
  }
  let shown = 0;
  sections.forEach((section, sectionIndex) => {
    const funds = section.funds;
    const board = el('section', undefined, 'fund-board');
    board.id = 'fund-board-' + sectionIndex;
    const header = el('div', undefined, 'board-heading');
    const intro = el('div');
    intro.append(el('span', 'RESEARCH BOARD / ' + String(sectionIndex + 1).padStart(2, '0'), 'eyebrow'),
      el('h3', string(section.label, '基金观察板块')));
    const description = concise(section.description, 100);
    if (description) intro.append(el('p', description));
    header.append(intro, el('span', (funds.length ? string(section.display_title, section.status === 'candidate' ? '研究候选' : '观察优选') : '本轮空缺') + ' · ' + funds.length + ' 只', 'board-count'));
    board.append(header);
    renderBoardReferenceCandidates(board,coverage.find(item=>item.id===section.id) || section);
    if (!funds.length) {
      board.append(el('div', string(section.empty_reason, '本轮暂无符合条件的观察样本，保持空缺。'), 'board-empty'));
      const detail = coverage.find(b => b.id === section.id);
      if (detail) array(detail.exclusion_reasons).forEach(item => board.append(el('p', string(item.reason) + ' · ' + item.count + ' 只', 'muted')));
      box.append(board); return;
    }
    const cards = el('div', undefined, 'fund-board-grid');
    funds.forEach((f, index) => {
      shown++;
      const q = array(record.quant).find(item => item?.code === f.code || item?.name === f.name) || {};
      const basic = array(record.snapshot?.funds).find(item => item?.code === f.code || item?.name === f.name) || {};
      const m = f.metrics || q.metrics || {};
      const plan = f.operation_plan || q.operation_plan || {};
      const researchState = fundResearchState(f, plan);
      const blocked = researchState.riskBlocked;
      const candidate = researchState.candidate;
      const tone = researchState.tone;
      const state = researchState.label;
      const card = el('article', undefined, 'strategy-card');
      card.dataset.tone = tone;
      const topline = el('div', undefined, 'strategy-topline');
      topline.append(el('span', String(index + 1).padStart(2, '0'), 'strategy-rank'),
        el('span', string(f.board_label, string(section.label, '研究样本')), 'asset-badge'),
        el('span', string(f.code), 'fund-code'));
      card.append(topline);
      const reference=f.reference_candidate || basic.reference_candidate;
      const yangjibaoReference=isYangjibaoBoardReference(reference);
      const forcedWebReference=reference?.source_kind==='web_discovery';
      if (yangjibaoReference) {
        const sourceBadge=el('span','养基宝分类 · '+string(section.label,'本板块'),'fund-reference-badge');
        sourceBadge.title=string(reference.source_label,'养基宝板块分类（用户提供）');card.append(sourceBadge);
      } else if (forcedWebReference) {
        const sourceBadge=el('span','互联网搜索 · 强制纳入','fund-reference-badge fund-reference-badge-web');
        sourceBadge.title='公开搜索候选已先纳入本板块，等待自动核验';card.append(sourceBadge);
      }
      const title = el('div', undefined, 'strategy-title');
      const name = el('h4', f.name); name.title = f.name;
      const boardMeta = coverage.find(item => item.id === section.id) || section;
      const fundOpportunity = boardOpportunity(record, {...boardMeta, status: candidate ? 'candidate' : 'observation'}, {funds:[f]});
      const scoreValue = fundOpportunity.recommendation_index;
      const score = el('div', undefined, 'trend-score');
      score.title = fundOpportunity.reason;
      score.append(el('strong', scoreValue == null ? UNKNOWN_MASK : String(scoreValue),scoreValue==null?'unknown-mask':undefined), el('small', '推荐指数 / 100'));
      title.append(name, score); card.append(title);
      card.append(el('span', state, 'strategy-state'));
      const brief = f.brief && typeof f.brief === 'object' ? f.brief : {};
      const headline = string(brief.headline) || (blocked ? '先等待条件改善，暂不新增' : candidate ? '保留研究资格，按条件跟踪' : '列入同类观察，不据评分直接买入');
      card.append(el('h5', concise(headline, 50), 'strategy-headline'));
      const reason = brief.reason || f.selection_reason || (f.role ? f.reason : '旧报告只保留观察顺序，完整判断与依据可展开查看。');
      card.append(el('p', concise(reason, 112, '当前资料不足以概括支持理由。'), 'strategy-support'));
      const holdingsMatch = boardFundHoldings(f);
      if (holdingsMatch) {
        const holdingsNote = el('div', undefined, 'fund-holdings-match');
        holdingsNote.dataset.status = holdingsMatch.status;
        const disclosure=holdingsMatchSummary(holdingsMatch);
        if (yangjibaoReference) disclosure.note='按养基宝板块分类归入本板块，持仓匹配比例独立核验。仅代表报告已披露部分，不代表全仓或实时仓位。'+(holdingsMatch.ratio_is_lower_bound?' 分类待核验部分仍计入分母，当前比例为已确认下限。':'');
        else if (forcedWebReference) disclosure.note='已按要求强制纳入本板块；匹配比例根据公开披露持仓独立计算，未知字段为 *****。';
        holdingsNote.append(el('span',disclosure.title),el('p',disclosure.note));
        if (holdingsMatch.status !== 'not_required') {
          const dates=holdingsEvidenceDates(holdingsMatch);
          const datesBox=el('div',undefined,'holdings-evidence-dates');
          [['持仓报告日',dataDate(dates.report_date)],
            ['成分 / 分类映射日',dates.mapping_dates.length?dates.mapping_dates.join('、'):UNKNOWN_MASK]].forEach(([label,value])=>{
              const item=el('div');item.append(el('small',label),el('span',value));datesBox.append(item);
            });
          holdingsNote.append(datesBox);
          const comparison=holdingsBoardComparison(f,section.id);
          if (comparison.length) {
            const assignment=el('div',undefined,'holdings-assignment');
            assignment.append(el('b',yangjibaoReference?'板块归属':'唯一归属'),el('span',string(section.label)+(yangjibaoReference?' · 按养基宝板块分类':' · 最高持仓匹配方向')));
            holdingsNote.append(assignment);
            const comparisonBox=el('div',undefined,'holdings-board-comparison');
            comparisonBox.setAttribute('aria-label','已核验板块持仓匹配比例对比');
            comparison.forEach(item=>{
              const row=el('div');row.dataset.selected=String(item.selected);
              const heading=el('div');heading.append(el('span',string(item.label,item.id)+(item.selected?' · 已归属':'')),
                el('b',(item.ratio_is_lower_bound?'≥ ':'')+holdingsRatioText(item.matched_disclosed_pct,item.ratio_is_lower_bound)));
              const track=el('div',undefined,'holdings-comparison-track');
              const fill=el('i');fill.style.width=item.matched_disclosed_pct+'%';track.append(fill);
              row.append(heading,track);comparisonBox.append(row);
            });
            holdingsNote.append(comparisonBox,el('p','占已披露股票的匹配比例 · 已核验方向最多展示 6 项 · '+(yangjibaoReference?'采用养基宝板块分类':'同比例优先更细分的板块'),'holdings-comparison-note'));
          }
        }
        if (holdingsMatch.status !== 'not_required') {
          const ratios=el('div',undefined,'holdings-ratio-grid');
          [['板块 / 已披露股票',holdingsMatch.matched_disclosed_pct],
            ['板块股票 / 基金净值',holdingsMatch.matched_weight_pct],
            ['已披露股票 / 基金净值',holdingsMatch.disclosed_weight_pct]].forEach(([label,value])=>{
              const lower=label!=='已披露股票 / 基金净值' && holdingsMatch.ratio_is_lower_bound;
              const item=el('div');item.append(el('small',label+(lower?'（已确认）':'')),el('strong',(lower && Number.isFinite(value)?'≥ ':'')+holdingsRatioText(value,lower),Number.isFinite(value)?undefined:'unknown-mask'));ratios.append(item);
            });
          holdingsNote.append(ratios);
          if (Number.isFinite(holdingsMatch.matched_weight_pct) && Number.isFinite(holdingsMatch.disclosed_weight_pct)) holdingsNote.append(el('p','板块股票 '+holdingsMatch.matched_weight_pct.toFixed(2)+'% ÷ 已披露股票 '+holdingsMatch.disclosed_weight_pct.toFixed(2)+'%（均占基金净值）'));
          if (holdingsMatch.ratio_is_lower_bound) holdingsNote.append(el('p','尚有 '+holdingsRatioText(holdingsMatch.unclassified_disclosed_pct)+' 的已披露股票分类待核验；当前匹配比例为已确认下限。'));
        }
        if (f.research_origin==='retained') holdingsNote.append(el('p','沿用有效原始数据，已重算本轮结论 · 原采集 '+stamp(f.evidence_collected_at)));
        card.append(holdingsNote);
      }
      if (f.ai_research_status === 'completed' && f.ai_reason) {
        const narrative = el('div', undefined, 'ai-fund-note');
        narrative.append(el('span', 'AI 证据解读'), el('p', concise(f.ai_reason, 136)));
        card.append(narrative);
      }
      const metrics = el('div', undefined, 'strategy-metrics');
      const metricPercent=(value,signed=false)=>Number.isFinite(value)?percent(value,signed):UNKNOWN_MASK;
      metrics.append(metric('20 日收益', metricPercent(m.return_20d, true)), metric('区间最大回撤', metricPercent(m.max_drawdown)), metric('年化波动', metricPercent(m.volatility_annual)));
      card.append(metrics);
      const strips = el('div', undefined, 'strategy-strips');
      [
        ['未持有', blocked ? '暂缓新增，等待风险条件改善' : candidate && researchState.executionUnverified ? '进入研究清单；支付宝可买状态及费用尚未确认，当前不执行买入。' : candidate ? concise(plan.new_position, 54, '条件核验后，再评估分批计划') : '先观察，不因历史分数建立新仓'],
        ['已持有', concise(plan.existing_position, 54, '结合实际仓位与风险变化复核')],
        ['复核', concise(plan.review_schedule, 54, '新的独立净值或重要公告出现时')]
      ].forEach(([label, text]) => {
        const strip = el('div'); strip.append(el('span', label), el('p', text)); strips.append(strip);
      });
      card.append(strips);
      const risk = string(brief.risk) || (blocked ? '可买资格、数据质量或交易条件尚未通过。' : '历史表现不代表未来收益，具体费用与可买资格需有来源证明。');
      const riskLine = el('p', undefined, 'strategy-risk');
      riskLine.append(el('span', '注意'), el('span', concise(risk, 94)));
      card.append(riskLine);
      const details = el('details', undefined, 'strategy-details');
      details.append(el('summary', '完整理由、操作计划与数据来源'));
      const content = el('div', undefined, 'strategy-detail-body');
      content.append(el('h5', '报告原始判断'), el('p', string(f.action, '观察')), el('p', string(f.reason, '未返回完整理由。')));
      if (f.ai_reason && !string(f.reason).includes(readable(f.ai_reason))) content.append(el('h5', 'AI 证据解读'), el('p', readable(f.ai_reason)));
      if (f.selection_reason) content.append(el('h5', '同类选择依据'), el('p', string(f.selection_reason)));
      if (section.selection_method) content.append(el('p', readable(section.selection_method), 'muted'));
      if (f.classification_basis) content.append(el('h5', '板块分类依据'), el('p', string(f.classification_basis)));
      if (holdingsMatch) {
        content.append(el('h5', '披露持仓与板块匹配'), el('p', string(holdingsMatch.reason, '持仓核验说明未提供。')));
        const weight = holdingsMatch.matched_weight_pct ?? holdingsMatch.weight_pct;
        if (Number.isFinite(holdingsMatch.matched_disclosed_pct)) content.append(el('p','主题股票占已披露股票权重 '+(holdingsMatch.ratio_is_lower_bound?'已确认至少 ':'')+holdingsRatioText(holdingsMatch.matched_disclosed_pct,holdingsMatch.ratio_is_lower_bound)+'；仅指已披露部分，不代表全仓。','muted'));
        if (Number.isFinite(weight)) content.append(el('p', '已确认主题股票占基金净值 ' + number(weight) + '%；这是披露持仓中的已知部分，不代表实时完整仓位。', 'muted'));
        if (Number.isFinite(holdingsMatch.disclosed_weight_pct)) content.append(el('p', '已披露股票合计占净值 ' + number(holdingsMatch.disclosed_weight_pct) + '% · 报告期 ' + dataDate(holdingsMatch.report_date), 'muted'));
        if (array(holdingsMatch.matched_names).length) content.append(el('p', '匹配股票：' + array(holdingsMatch.matched_names).map(name => string(name)).filter(Boolean).join('、')));
        if (array(holdingsMatch.stock_evidence).length) {
          const holdingsRows=el('div',undefined,'holdings-stock-evidence');
          array(holdingsMatch.stock_evidence).forEach(stock=>{
            const row=el('div');row.append(el('b',string(stock.name)+' '+string(stock.code)),
              el('span','占净值 '+percent(stock.nav_weight_pct)+' · 占已披露股票 '+percent(stock.disclosed_stock_weight_pct)),
              el('small',stock.matched?'符合本板块：'+array(stock.matched_tags).join('、'):stock.tag_status==='ok'?'未匹配本板块':'*****（仍计入分母）'));
            if(stock.tag_source_url)row.append(link('股票分类来源 ↗',stock.tag_source_url));
            array(stock.membership_sources || stock.mapping_sources).filter(source=>source?.matched===true).forEach(source=>{
              row.append(el('small',string(source.index_name,'官方成分')+' · 映射日 '+dataDate(source.source_date)
                +(source.complete?' · 完整成分':' · 官方前十，部分证据')));
              if(source.source_url)row.append(link('官方成分来源 ↗',source.source_url));
            });
            holdingsRows.append(row);
          });
          content.append(el('h5','已披露股票逐项权重'),holdingsRows);
        }
        if (holdingsMatch.rule && holdingsMatch.status !== 'not_required') content.append(el('p', string(holdingsMatch.rule), 'muted'));
        if (holdingsMatch.limitations && holdingsMatch.status !== 'not_required') content.append(el('p', string(holdingsMatch.limitations), 'muted'));
        if (holdingsMatch.source_url) content.append(link('基金持仓披露来源 ↗', holdingsMatch.source_url));
      }
      if (f.score_explanation) content.append(el('h5', '历史趋势分说明'), el('p', string(f.score_explanation)));
      content.append(el('p', '推荐指数 ' + (scoreValue == null ? UNKNOWN_MASK : scoreValue + '/100') + '；原始历史研究分 ' + (Number.isFinite(f.score) ? Math.round(f.score) + '/100' : UNKNOWN_MASK) + '。推荐指数取历史研究分与风险档位上限的较小值；不是收益预测或成功概率。', 'muted'));
      if (array(q.reasons).length) {
        const reasons = el('ul'); array(q.reasons).forEach(reason => reasons.append(el('li', string(reason)))); content.append(reasons);
      }
      if (q.score_components && typeof q.score_components === 'object') {
        const labels = {base:'基础分',momentum_20d:'20日动量',momentum_60d:'60日动量',trend_20d:'20日趋势',trend_60d:'60日趋势',volatility_penalty:'波动扣分',drawdown_penalty:'回撤扣分',rsi_penalty:'RSI扣分'};
        const components = el('div', undefined, 'score-components');
        Object.entries(q.score_components).forEach(([key, value]) => {
          if (typeof value !== 'number' || !Number.isFinite(value)) return;
          const component = el('div'); component.append(el('span', labels[key] || key), el('b', (value > 0 ? '+' : '') + number(value)));
          components.append(component);
        });
        content.append(el('p', '固定启发式评分组成；非回测优化权重。', 'muted'), components);
      }
      content.append(el('h5', '风险与失效条件'), el('p', string(f.invalidation, '未提供，暂不据此行动。')));
      if (brief.risk) content.append(el('p', string(brief.risk)));
      addPlanDetails(content, plan);
      const links = el('div', undefined, 'evidence-links');
      if (basic.source_url) links.append(link('基金净值原始来源 ↗', basic.source_url));
      array(f.evidence_ids).slice(0, 8).forEach(id => {
        const source = array(record.snapshot?.sources).find(s => s?.id === id);
        if (source) links.append(link(string(source.name, String(id)) + ' ↗', source.url));
      });
      content.append(el('p', '净值日期：' + dataDate(f.nav_date || q.nav_date || basic.nav_date) + ' · 样本数：' + unknownMask(m.observations), 'muted'));
      content.append(links); details.append(content); card.append(details);
      cards.append(card);
    });
    board.append(cards); box.append(board);
  });
  const distinctFundCount = new Set(matchingSections.flatMap(s=>s.funds.map(f=>f.code))).size;
  $('#boardSummary').textContent = matchingSections.length + ' 个板块有结果 · '+distinctFundCount+' 只不同基金 · 当前显示 ' + shown + ' 个板块策略（'+classificationCopy.summary+'）';
  if (!sections.length) box.append(el('div', boardFilter.query ? '没有匹配的板块，请调整搜索条件。' : '当前没有足够样本形成板块观察清单，保持空缺。', 'board-empty'));
}

function renderMarketOverview(record) {
  const model = marketOverviewModel(record);
  $('#overviewAsOf').textContent = (model.stale ? '上次数据 · 等待更新' : '采集于 ' + stamp(model.as_of));
  const indices = $('#overviewIndices'); indices.replaceChildren();
  model.indices.forEach(item => {
    const card = el('article', undefined, 'overview-index');
    const stale = model.stale || item.status === 'stale';
    const known = item.status === 'ok' && !model.stale;
    card.dataset.direction = Number.isFinite(item.change_pct) ? item.change_pct > 0 ? 'up' : item.change_pct < 0 ? 'down' : 'flat' : 'unknown';
    const heading = el('div', undefined, 'overview-index-name');
    heading.append(el('span', string(item.name, string(item.code, '市场指数'))));
    if (stale || !known) heading.append(el('small', stale ? '上次快照' : '已披露快照'));
    card.append(heading, el('strong', Number.isFinite(item.value) ? number(item.value) : '暂无报价', 'overview-index-value'),
      el('b', Number.isFinite(item.change_pct) ? percent(item.change_pct,true) : '涨跌幅未提供', 'overview-index-change'),
      el('small', stamp(item.as_of), 'overview-index-time'));
    if (item.source_url) card.append(link('行情来源 ↗', item.source_url, 'overview-index-source'));
    indices.append(card);
  });
  if (!indices.children.length) indices.append(el('p','尚未取得可用指数快照，等待行情更新。','overview-no-data'));
  const breadth = model.breadth;
  const range = breadth.date_range || {};
  const dates = breadth.nav_date ? '统计净值日 ' + breadth.nav_date : '统计净值日尚未取得';
  const rangeText = range.min && range.max && range.min !== range.max ? '；候选样本日期 ' + range.min + ' 至 ' + range.max : '';
  $('#breadthScope').textContent = [string(breadth.scope,'仅统计已取得真实单日净值涨跌幅的基金样本'), dates + rangeText].join(' · ');
  const scopeCount = breadth.scope_count;
  $('#breadthSampleCount').textContent = model.usable ? '有效样本 ' + model.total.toLocaleString() + ' 只'
    + (Number.isFinite(scopeCount) ? ' / 范围 ' + scopeCount.toLocaleString() + ' 只' : '') : '日收益样本不足';
  const chart = $('#breadthChart'); chart.replaceChildren();
  const counts = $('#breadthCounts'); counts.replaceChildren();
  const bar = $('#breadthBar'); bar.replaceChildren();
  bar.hidden = !model.usable;
  if (model.usable) {
    const max = Math.max(...model.buckets.map(item=>item.count),1);
    model.buckets.forEach(item => {
      const column = el('div',undefined,'breadth-column');
      column.dataset.direction = item.direction;
      column.title = string(item.label) + '：' + item.count.toLocaleString() + ' 只基金';
      const track = el('div',undefined,'breadth-column-track');
      const fill = el('i'); fill.style.height = Math.max(item.count > 0 ? 2 : 0, item.count / max * 100) + '%';
      track.append(el('span',item.count.toLocaleString(),'breadth-column-count'),fill);
      column.append(track,el('small',string(item.label))); chart.append(column);
    });
    [['up','上涨',breadth.up],['flat','持平',breadth.flat],['down','下跌',breadth.down]].forEach(([direction,label,count])=>{
      const item = el('span',undefined,'breadth-count'); item.dataset.direction = direction;
      item.append(el('i'),el('span',label),el('b',count.toLocaleString() + ' 只')); counts.append(item);
      const segment = el('span'); segment.dataset.direction = direction;
      segment.style.width = count / model.total * 100 + '%'; bar.append(segment);
    });
  } else chart.append(el('div','暂无可展示的基金涨跌分布','breadth-empty'));
  $('#breadthNote').textContent = [model.stale ? '这是上次保存的数据，正在等待更新。' : '',
    string(breadth.reason,model.usable ? '基金净值存在披露滞后，样本分布不能代表全部基金。' : '尚未取得同一净值日的有效基金收益，数据齐全后自动展示。'),
    '行情颜色：红涨绿跌；下方推荐指数：红低绿高。'].filter(Boolean).join(' ');
  const sources=$('#overviewSources');sources.replaceChildren();
  model.indices.forEach(item=>{
    const row=el('p');row.append(el('span',string(item.name,string(item.code,'指数'))+' · '+stamp(item.as_of)+' '));
    if(item.source_url)row.append(link('行情来源 ↗',item.source_url));
    if(item.reason)row.append(el('span',' · '+string(item.reason)));sources.append(row);
  });
  const fundSource=el('p');fundSource.append(el('span','基金分布：'+dates+'。'));
  if(breadth.source_url)fundSource.append(link('日收益来源 ↗',breadth.source_url));sources.append(fundSource);
  array(record.source_connections).forEach(connection=>{
    if(!connection || typeof connection!=='object')return;
    const row=el('div',undefined,'overview-source-connection');
    row.append(el('b',string(connection.label,'外部数据来源')+' · '+(['ok','connected'].includes(connection.status)?'已接通':'尚未接通')),
      el('p',string(connection.reason,'来源状态尚未确认。')),
      el('small','检查时间：'+stamp(connection.checked_at)));
    if(connection.url)row.append(link('来源页面 ↗',connection.url));sources.append(row);
  });
}
function renderResearchGaps(record, pending) {
  const box=$('#boardPendingDirections');box.replaceChildren();
  if (!pending.length) return;
  const items=pending.map(board=>({board,gap:boardResearchGap(board,record)}));
  const order=['holdings','stale_data','screening','not_researched','no_match','insufficient'];
  const categories=order.map(id=>({id,items:items.filter(item=>item.gap.category===id)})).filter(group=>group.items.length);
  if (!categories.some(group=>group.id===boardFilter.pendingCategory)) boardFilter.pendingCategory='all';
  const area=el('section',undefined,'research-gaps');area.setAttribute('aria-label','待完善研究');
  const heading=el('div',undefined,'research-gaps-heading');
  const title=el('div');title.append(el('span','RESEARCH IN PROGRESS','research-gap-kicker'),el('h4','待完善研究'));
  const directionCount=pending.filter(board=>board.id!=='holdings_unclassified').length;
  const hasQueue=pending.some(board=>board.id==='holdings_unclassified');
  heading.append(title,el('span',directionCount+' 个方向'+(hasQueue?' · 1 项归类队列':''),'research-gap-total'));
  const scan=holdingsCoverageModel(record);
  const scanNote=['已预检 '+(scan.checked===null?'*****':scan.checked.toLocaleString())+' 只',
    '待采集 '+(scan.unchecked===null?'*****':scan.unchecked.toLocaleString())+' 只'].join(' · ');
  area.append(heading,el('p',(scanNote?scanNote+'。':'')+'“已归类 0”表示当前证据尚未确认该方向；待采集队列按轮次继续核验。点选原因查看进展。','research-gaps-note'));
  const filters=el('div',undefined,'research-gap-filters');filters.setAttribute('aria-label','按研究缺口筛选');
  [['all','全部',items.length],...categories.map(group=>[group.id,group.items[0].gap.group_label,group.items.length])].forEach(([id,label,count])=>{
    const button=el('button',undefined,'research-gap-filter');button.type='button';button.dataset.category=id;
    button.setAttribute('aria-pressed',String(boardFilter.pendingCategory===id));button.append(el('span',label),el('b',String(count)));
    button.onclick=()=>{boardFilter.pendingCategory=id;boardFilter.pendingId=null;renderFundBoards(record);};filters.append(button);
  });
  area.append(filters);
  const selected=categories.filter(group=>boardFilter.pendingCategory==='all' || boardFilter.pendingCategory===group.id);
  selected.forEach(group=>{
    const category=el('details',undefined,'research-gap-group');category.dataset.category=group.id;
    category.open=boardFilter.pendingCategory===group.id || Boolean(boardFilter.query) || group.items.some(item=>item.board.id===boardFilter.pendingId);
    const summary=el('summary');summary.append(el('span',group.items[0].gap.group_label),el('b',String(group.items.length)),el('small','查看方向与缺口'),el('i','⌄'));
    category.append(summary);
    const rows=el('div',undefined,'research-gap-rows');
    group.items.forEach(({board,gap})=>{
      const row=el('details',undefined,'research-gap-row');row.dataset.boardId=String(board.id);row.open=boardFilter.pendingId===board.id;
      row.ontoggle=()=>{if(row.open)boardFilter.pendingId=board.id;else if(boardFilter.pendingId===board.id)boardFilter.pendingId=null;};
      const rowHeading=el('summary');
      const identity=el('span',undefined,'research-gap-identity');identity.append(el('b',string(board.label)),el('span',concise(gap.summary,95)));
      const progress=el('span',undefined,'research-gap-progress');
      const countText=value=>value===null?'*****':String(value);
      progress.append(el('span',(board.id==='holdings_unclassified'?'待归类 ':'已归类 ')+countText(gap.counts.screened_count)),el('span','深研 '+countText(gap.counts.deep_count)),
        el('span',board.requires_holdings_match===false?'按资产归类':'持仓匹配 '+countText(gap.counts.matched_holdings_count)));
      rowHeading.append(identity,progress,el('i','›'));row.append(rowHeading);
      const body=el('div',undefined,'research-gap-body');
      const metrics=el('div',undefined,'research-gap-metrics');
      [[board.id==='holdings_unclassified'?'归类队列':'持仓已归类',gap.counts.screened_count],['通过产品初筛',gap.counts.eligible_count],
        [gap.counts.deep_count>3?'历史深研':'实际深研',gap.counts.deep_count],['有效净值',gap.counts.valid_quant_count],
        ['持仓匹配',board.requires_holdings_match===false?'不适用':gap.counts.matched_holdings_count]].forEach(([label,count])=>{
        const metric=el('div');metric.append(el('b',countText(count)),el('span',label));metrics.append(metric);
      });
      body.append(metrics,el('p',boardDeepCountText({...board,deep_count:gap.counts.deep_count})+'。计数来自'+(record.report_stale?'上次报告':'本报告')+'；已归类数量不等于市场基金总量或支付宝可买数量。','research-gap-count-note'));
      const reason=el('div',undefined,'research-gap-reason');reason.append(el('h5','具体缺口 · '+gap.label),el('p',gap.summary));
      array(board.exclusion_reasons).slice(0,3).forEach(item=>reason.append(el('p',string(item.reason)+(Number.isInteger(item.count)?'（'+item.count+' 只）':''))));
      if(board.requires_holdings_match===true)reason.append(el('p','指定基金与搜索候选已纳入对应板块；持仓匹配、推荐指数和操作条件分别核验，未知字段为 *****。'));
      body.append(reason);
      const next=el('div',undefined,'research-gap-next');
      next.append(el('h5','系统下一步'),el('p',gap.next_step));
      if(gap.automatic!==null)next.append(el('small',gap.automatic?'可由后续自动研究继续检查，是否形成结论取决于新证据。':'当前仍需补充研究条件，不能保证下一轮补齐。'));
      body.append(next);
      if(gap.examples.length){
        const examples=el('div',undefined,'research-gap-examples');examples.append(el('h5',record.report_stale?'上次报告已研究样本 · 非推荐':'本轮已研究样本 · 非推荐'));
        gap.examples.forEach(item=>{
          const sample=el('div');sample.append(el('b',[string(item.name),string(item.code)].filter(Boolean).join(' ')),el('p',string(item.reason,'研究资料尚未满足展示条件。')));
          sample.append(el('small','净值日期 '+(typeof item.nav_date==='string' && item.nav_date ? item.nav_date : '*****')));
          if(item.source_url)sample.append(link('查看原始资料 ↗',item.source_url));examples.append(sample);
        });body.append(examples);
      }
      const search=boardWebSearchModel(board);
      if(search){
        const discovery=el('div',undefined,'research-gap-discovery');discovery.dataset.status=string(search.status);
        const discoveryHeading=el('div',undefined,'research-gap-discovery-heading');
        discoveryHeading.append(el('h5','互联网补充发现'),el('span',search.label));discovery.append(discoveryHeading);
        discovery.append(el('p',search.record_label+' · 查询时间 '+(search.searched_at?stamp(search.searched_at):'*****')));
        if(search.query)discovery.append(el('p','搜索词：'+search.query));
        if(search.attempts!==null)discovery.append(el('small','已记录尝试 '+search.attempts+' 次'));
        if(search.reason)discovery.append(el('p',search.reason));
        if(!search.total)discovery.append(el('p',['error','failed'].includes(search.status)
          ?'本次搜索未成功取得可核验候选，具体原因见上方；不据此判断该板块没有基金。'
          :'当前没有可展示的发现候选；这不代表全市场没有对应基金。'));
        if(search.status==='discovery_only' || search.candidates.some(item=>item?.forced_selection || item?.status==='discovery_only')){
          discovery.append(el('p','资料暂时不足时，系统已先把搜索到的基金强制纳入本板块；后续自动研究会依次核对产品身份、净值与风险、报告期披露持仓、板块匹配比例和可购资格。核验完成前不会生成推荐指数或买入指令。','research-gap-discovery-warning'));
        }
        search.candidates.forEach(item=>{
          const candidate=el('div',undefined,'research-gap-discovered-fund');
          const stateLabel=item.forced_selection?'已强制纳入板块 · 待核验':item.state_label;
          candidate.append(el('b',[string(item.name),string(item.code)].filter(Boolean).join(' ')),el('span',stateLabel));
          candidate.append(el('small','基金类型：'+string(item.fund_type,'*****')));
          const candidateMetrics=el('div',undefined,'research-gap-candidate-metrics');
          [['持仓匹配',holdingsRatioText(item.matched_disclosed_pct)],['推荐指数','*****'],['持仓报告日',string(item.report_date,'*****')]]
            .forEach(([label,value])=>candidateMetrics.append(el('span',label+'：'+value)));
          candidate.append(candidateMetrics);
          if(item.screening_reason || item.note)candidate.append(el('p',string(item.screening_reason,string(item.note))));
          if(item.source_url)candidate.append(link('查看基金来源 ↗',item.source_url));
          if(item.search_url && item.search_url!==item.source_url)candidate.append(link('查看搜索结果 ↗',item.search_url));
          discovery.append(candidate);
        });
        discovery.append(el('p','本区最多展示 3 个发现候选；搜索发现不计为推荐或已深研。强制纳入只代表先放入板块观察清单，仍须通过数据、持仓与风险核验。','research-gap-discovery-note'));
        body.append(discovery);
      }
      const oldFunds=board.requires_holdings_match===true?array(array(record.sections).find(section=>section.id===board.id)?.funds)
        .filter(fund=>fund && !boardFundHasCurrentHoldings(fund)).slice(0,3):[];
      if(oldFunds.length){
        const history=el('details',undefined,'research-gap-history');history.append(el('summary','旧报告原文 · 不作为当前合格策略'));
        history.append(el('p','以下记录尚未按当前“已确认大部分符合，匹配比例越高越优先”规则重新核验，保留原文供回看。'));
        oldFunds.forEach(fund=>{
          const original=el('div');original.append(el('b',[string(fund.name),string(fund.code)].filter(Boolean).join(' ')));
          if(fund.action)original.append(el('p','原文行动：'+string(fund.action)));
          if(fund.reason)original.append(el('p','原文理由：'+string(fund.reason)));
          const match=boardFundHoldings(fund);if(match?.rule)original.append(el('p','当时匹配规则：'+string(match.rule)));
          history.append(original);
        });body.append(history);
      }
      row.append(body);rows.append(row);
    });category.append(rows);area.append(category);
  });box.append(area);
}
function renderBoardExplorer(record, coverage, sections) {
  renderMarketOverview(record);
  const groups = [['all','全部方向'],['industry','行业主题'],['finance','金融细分'],['overseas','海外市场'],['broad','综合与宽基'],['style','风格与策略'],['commodity','黄金商品'],['defensive','固收与现金'],['other','待分类']];
  const groupBox = $('#boardGroups'); groupBox.replaceChildren();
  const inGroup=(board,id)=>id==='all' || (id==='finance' ? board.family==='finance' : board.group===id);
  if (!coverage.some(b=>inGroup(b,boardFilter.group))) boardFilter.group='all';
  const ranked = rankResearchBoards(record, coverage, sections);
  const visible = filterResearchBoards(ranked, boardFilter.group, boardFilter.query);
  const {evaluated,pending} = partitionResearchBoards(visible);
  if (boardFilter.id!=='all' && !evaluated.some(b=>b.id===boardFilter.id)) boardFilter.id = evaluated[0]?.id || null;
  groups.forEach(([id,label])=>{
    const count = coverage.filter(b=>inGroup(b,id)).length;
    if (!count) return;
    const button=el('button',label+' '+count,'board-group'); button.type='button'; button.setAttribute('aria-pressed',String(boardFilter.group===id));
    button.onclick=()=>{boardFilter.group=id;boardFilter.id=null;boardFilter.pendingCategory='all';boardFilter.pendingId=null;renderFundBoards(record);}; groupBox.append(button);
  });
  const recommended = ranked.filter(board=>board.opportunity.recommended).length;
  const evaluatedTotal=ranked.filter(board=>Number.isFinite(board.opportunity.recommendation_index)).length;
  const scan=holdingsCoverageModel(record,coverage);
  $('#boardCoverageSummary').textContent='覆盖 '+scan.directions+' 个方向'+(scan.dynamic?'（含 '+scan.dynamic+' 个按持仓发现的细分方向）':'')
    +' · '+evaluatedTotal+' 个有结论 · '+recommended+' 个优先关注 · 每板块深研、展示均最多 3 只';
  const legend=$('#boardOpportunityLegend');legend.replaceChildren();
  BOARD_OPPORTUNITY_LEVELS.forEach(level=>{
    const item=el('span',undefined,'opportunity-legend-item');
    const dot=el('i');dot.style.backgroundColor=level.color;
    item.append(dot,el('span',level.label));legend.append(item);
  });
  const mode=record.strategy?.regime?.mode;
  $('#boardOpportunityContext').textContent=record.report_stale || !['risk_on','cautious','defensive'].includes(mode)
    ? '正在等待有效市场数据；下方“待完善研究”按原因显示资料缺口。'
    : mode==='defensive' ? '当前为防御模式，权益推荐指数最高 39；风险提示保留。低风险备用方向见上方防守方案。'
    : mode==='cautious' ? '推荐指数由高到低排列。当前市场谨慎，最高 71；只有持仓匹配且条件通过的主题基金才进入展示。'
    : '优先关注的方向排在前面，其余按推荐指数排序。点选板块查看最多三只基金的理由与策略。';
  const directory=$('#boardDirectory');directory.replaceChildren();
  evaluated.forEach((board,index)=>{
    const button=el('button',undefined,'board-tile');button.type='button';button.dataset.status=board.status || 'unknown';
    const section=sections.find(section=>section.id===board.id);
    const opportunity=board.opportunity;
    button.dataset.opportunity=String(opportunity.level);
    button.setAttribute('aria-pressed',String(boardFilter.id===board.id));button.title=opportunity.reason;
    button.setAttribute('aria-description',opportunity.reason);
    const identity=el('span',undefined,'board-identity');
    const title=el('span',undefined,'board-name-line');
    title.append(el('span',String(index+1).padStart(2,'0'),'board-row-number'),el('b',string(board.label)));
    if (opportunity.recommended) title.append(el('em','优先关注','board-priority-tag'));
    const scored=Number.isFinite(opportunity.recommendation_index);
    identity.append(title,el('small',(!scored ? '已纳入板块 · 数据继续核验' : board.requires_holdings_match === true ? '披露持仓支持该方向' : '按基金资产类型归类')
      + ' · '+boardDeepCountText(board),'board-research-status'));
    const rating=el('span',undefined,'board-opportunity-rating');
    rating.append(el('strong',scored?String(opportunity.recommendation_index):'*****'),el('small','/ 100'));
    const count=el('span',undefined,'board-sample-count');
    count.append(el('b',(scored?'优选 ':'已纳入 ')+String(Math.min(array(section?.funds).length,3))+' / 最多 3 只'),
      el('small',boardFilter.id===board.id?'正在查看':'查看策略 ›'));
    button.append(identity,rating,count);
    button.onclick=()=>{boardFilter.id=board.id;renderFundBoards(record);};
    directory.append(button);
  });
  if (!evaluated.length) directory.append(el('p',visible.length ? '这个分组暂时没有可评估方向。下方可查看具体原因。' : '没有找到这个板块，试试其他名称或分组。','board-list-empty'));
  renderResearchGaps(record,pending);
  $('#boardSearch').oninput=e=>{boardFilter.query=e.target.value;boardFilter.id=null;boardFilter.pendingCategory='all';boardFilter.pendingId=null;renderFundBoards(record);};
  $('#showAllBoards').textContent=boardFilter.id==='all' ? '返回板块聚焦' : '查看全部策略';
  $('#showAllBoards').onclick=()=>{boardFilter.id=boardFilter.id==='all'?null:'all';renderFundBoards(record);};
}

