'use strict';

// The recommendation index is a documented rule score, never a return probability.
const BOARD_OPPORTUNITY_LEVELS = Object.freeze([
  {id: 0, label: '0–39 · 低关注', color: '#a8444e'},
  {id: 1, label: '40–59 · 谨慎', color: '#c27558'},
  {id: 2, label: '60–71 · 观察', color: '#c4aa63'},
  {id: 3, label: '72–84 · 较高', color: '#64aa83'},
  {id: 4, label: '85–100 · 优先', color: '#29946f'}
]);
const BOARD_RECOMMENDATION_CAPS = Object.freeze([39, 59, 71, 84, 100]);

function boardFundHoldings(fund) {
  const match = fund?.board_match || fund?.holdings_match || fund?.holdings_verification;
  return match && typeof match === 'object' ? match : null;
}
function boardFundHasCurrentHoldings(fund) {
  const match=boardFundHoldings(fund);
  return match?.status==='matched' && match.rule_version==='single_board_holdings_rank_v4'
    && typeof match.matched_disclosed_pct==='number' && Number.isFinite(match.matched_disclosed_pct)
    && match.matched_disclosed_pct>50 && match.matched_disclosed_pct<=100;
}

function boardOpportunity(record, board, section) {
  const unknown = reason => ({level: 'unknown', label: '待评估', score: null, recommendation_index: null,
    recommended: false, matched_count: 0, reason});
  const mode = record?.strategy?.regime?.mode;
  const timestamp = Date.parse(record?.time || record?.snapshot?.as_of || '');
  const age = Date.now() - timestamp;
  if (record?.report_stale || record?.demo || !Number.isFinite(age) || age > 3600000 || age < -300000 ||
      !['risk_on', 'cautious', 'defensive'].includes(mode)) {
    return unknown('市场状态缺失或报告过期，等待新一轮研究。');
  }
  if (['unknown', 'no_match', 'excluded', 'not_researched', 'insufficient'].includes(board?.status)) {
    return unknown(board.reason || '当前没有足够的有效研究样本。');
  }
  const scored = (Array.isArray(section?.funds) ? section.funds : []).filter(fund =>
    fund && fund.quality === 'ok' && fund.risk_check_complete === true &&
    Array.isArray(fund.risk_flags) && typeof fund.score === 'number' &&
    Number.isFinite(fund.score) && fund.score >= 0 && fund.score <= 100
    && (board?.requires_holdings_match !== true || boardFundHasCurrentHoldings(fund))
  );
  if (!scored.length) return unknown(board?.requires_holdings_match === true
    ? '尚无净值、风险及持仓匹配均通过的板块样本，等待自动核验。'
    : '净值、分数或风险条件不完整，不以缺失数据代替低推荐。');
  const ranked = scored.map(fund => {
    const score = fund.score;
    let level = score < 40 ? 0 : score < 60 ? 1 : score < 72 ? 2 : score < 85 ? 3 : 4;
    const limits = [];
    if (fund.role !== 'candidate') {
      level = Math.min(level, 2);
      limits.push('尚未进入研究候选');
    }
    if (fund.risk_flags.length || /暂缓|暂停|阻断|防御|风险超限/.test(String(fund.action || ''))) {
      level = Math.min(level, 1);
      limits.push('风险或新增条件未通过');
    }
    const holdings = boardFundHoldings(fund);
    if (board?.requires_holdings_match === true && !boardFundHasCurrentHoldings(fund)) {
      level = Math.min(level, 1);
      limits.push(holdings?.status === 'mismatch' ? '披露持仓与板块未匹配' : '披露持仓与板块匹配待核验');
    }
    if (/减仓|卖出|退出/.test(String(fund.action || ''))) {
      level = 0;
      limits.push('当前决策提示减仓或退出复核');
    }
    if (mode === 'cautious') {
      level = Math.min(level, 2);
      limits.push('市场谨慎，关注度最高为中性观察');
    } else if (mode === 'defensive') {
      level = 0;
      limits.push('市场防御，暂停新增风险关注');
    }
    const recommendation_index = Math.min(Math.round(score), BOARD_RECOMMENDATION_CAPS[level]);
    return {level, score, recommendation_index, name: fund.name || fund.code || '研究样本', limits,
      recommended: recommendation_index >= 72 && fund.role === 'candidate'
        && (board?.requires_holdings_match !== true || boardFundHasCurrentHoldings(fund))};
  }).sort((a, b) => Number(b.recommended) - Number(a.recommended)
    || b.recommendation_index - a.recommendation_index || b.score - a.score);
  const best = ranked[0];
  return {
    level: best.level,
    label: BOARD_OPPORTUNITY_LEVELS[best.level].label,
    score: best.score,
    recommendation_index: best.recommendation_index,
    recommended: best.recommended,
    matched_count: scored.filter(boardFundHasCurrentHoldings).length,
    reason: '本板块以已展示样本中有效推荐指数最高者为代表：' + best.name + '。推荐指数 ' +
      best.recommendation_index + '/100，原始历史研究分 ' + Math.round(best.score) + '/100。推荐指数取原始分与当前风险档位上限的较小值。' +
      (best.limits.length ? best.limits.join('；') + '。' : '已进入当前研究候选。') +
      '分值表示规则下的研究优先级，不是收益概率；可购资格与交易条款仍需核验，不是可执行买入指令。'
  };
}

function rankResearchBoards(record, boards, sections) {
  const byId = new Map((Array.isArray(sections) ? sections : []).map(section => [section.id, section]));
  return (Array.isArray(boards) ? boards : []).map((board, order) => ({
    ...board, opportunity: boardOpportunity(record, board, byId.get(board.id)), original_order: order
  })).sort((a, b) => Number(b.opportunity.recommended) - Number(a.opportunity.recommended)
    || Number(b.opportunity.recommendation_index !== null) - Number(a.opportunity.recommendation_index !== null)
    || (b.opportunity.recommendation_index ?? -1) - (a.opportunity.recommendation_index ?? -1)
    || b.opportunity.matched_count - a.opportunity.matched_count
    || (b.displayed_count || 0) - (a.displayed_count || 0)
    || (a.reference_order ?? a.original_order) - (b.reference_order ?? b.original_order));
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {BOARD_OPPORTUNITY_LEVELS, BOARD_RECOMMENDATION_CAPS, boardFundHoldings, boardFundHasCurrentHoldings, boardOpportunity, rankResearchBoards};
}
