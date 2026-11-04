'use strict';
const assert = require('node:assert/strict');
const {test} = require('node:test');
const {boardOpportunity, rankResearchBoards, boardFundHasCurrentHoldings} = require('./dist/board-opportunity.js');
const sample = overrides => ({name:'研究样本', quality:'ok', risk_check_complete:true, risk_flags:[], score:90, role:'candidate', action:'7 天以上研究候选', ...overrides});
const rate = (funds, mode='risk_on', board={status:'candidate'}, extra={}) => boardOpportunity({time:new Date().toISOString(), strategy:{regime:{mode}}, ...extra}, board, {funds});

test('five score bands, including boundary values, remain ordered', () => {
  for (const [score, level] of [[0,0],[39,0],[40,1],[59,1],[60,2],[71,2],[72,3],[84,3],[85,4],[100,4]]) {
    assert.equal(rate([sample({score})]).level,level);
  }
});
test('a high historical score does not promote an observation to green', () => {
  assert.equal(rate([sample({role:'observation'})]).level,2);
});
test('risk blockers and reduced positions override high scores', () => {
  assert.equal(rate([sample({risk_flags:['波动超限']})]).level,1);
  assert.equal(rate([sample({action:'暂缓新增'})]).level,1);
  assert.equal(rate([sample({action:'考虑减仓（如持有）'})]).level,0);
});
test('cautious and defensive market states cap attention', () => {
  assert.equal(rate([sample()],'cautious').level,2);
  assert.equal(rate([sample()],'defensive').level,0);
  assert.equal(rate([sample()],'unknown').level,'unknown');
});
test('stale reports and empty or unresearched boards remain gray', () => {
  assert.equal(rate([sample()],'risk_on',{status:'candidate'},{report_stale:true}).level,'unknown');
  assert.equal(rate([sample()],'risk_on',{status:'candidate'},{time:'2000-01-01T00:00:00Z'}).level,'unknown');
  assert.equal(rate([sample()],'risk_on',{status:'candidate'},{time:null}).level,'unknown');
  for (const status of ['unknown','no_match','excluded','not_researched','insufficient']) {
    assert.equal(rate([sample()],'risk_on',{status}).level,'unknown');
  }
  assert.equal(rate([]).level,'unknown');
});
test('bad, missing, or malformed scores and risk evidence are not colored as recommendations', () => {
  for (const values of [{score:null},{score:'90'},{score:NaN},{score:Infinity},{score:-1},{score:101},{quality:'stale'},{risk_check_complete:false},{risk_flags:undefined}]) {
    assert.equal(rate([sample(values)]).level,'unknown');
  }
});
test('selects the best attention tier, rather than the biggest blocked score', () => {
  const result=rate([sample({name:'受阻高分',score:99,risk_flags:['风险超限']}),sample({name:'有效候选',score:75})]);
  assert.equal(result.level,3);
  assert.equal(result.score,75);
  assert.match(result.reason,/有效候选/);
  assert.match(result.reason,/不是可执行买入指令/);
});
test('rating never mutates the saved research evidence', () => {
  const funds=[sample()];
  const before=JSON.stringify(funds);
  rate(funds,'cautious');
  assert.equal(JSON.stringify(funds),before);
});

test('numeric recommendation index retains the measured score and applies visible risk caps', () => {
  const blocked = rate([sample({score:99, action:'暂缓新增'})]);
  assert.equal(blocked.score,99);
  assert.equal(blocked.recommendation_index,59);
  assert.equal(blocked.recommended,false);
  assert.equal(rate([sample({score:90})],'cautious').recommendation_index,71);
  assert.equal(rate([sample({score:90})],'defensive').recommendation_index,39);
  assert.equal(rate([sample({score:90})]).recommendation_index,90);
});
test('theme board requires actual disclosed holdings match before any numeric recommendation', () => {
  const board={status:'candidate',requires_holdings_match:true};
  assert.equal(rate([sample()],'risk_on',board).recommendation_index,null);
  assert.equal(rate([sample({board_match:{status:'unknown'}})],'risk_on',board).recommendation_index,null);
  assert.equal(rate([sample({board_match:{status:'mismatch'}})],'risk_on',board).recommendation_index,null);
  const matched=rate([sample({board_match:{status:'matched',rule_version:'single_board_holdings_rank_v4',matched_disclosed_pct:60,weight_pct:19}})],'risk_on',board);
  assert.equal(matched.recommendation_index,90);
  assert.equal(matched.recommended,true);
});
test('current holdings majority accepts below 75 and rejects half or legacy evidence',()=>{
  const board={status:'candidate',requires_holdings_match:true};
  const current={status:'matched',rule_version:'single_board_holdings_rank_v4',matched_disclosed_pct:60};
  assert.equal(boardFundHasCurrentHoldings(sample({board_match:current})),true);
  for(const ratio of [50.00001,60,70,75,90,100]) assert.equal(boardFundHasCurrentHoldings(sample({board_match:{...current,matched_disclosed_pct:ratio}})),true);
  for(const match of [
    {...current,matched_disclosed_pct:50}, {...current,matched_disclosed_pct:49.99}, {...current,matched_disclosed_pct:0},
    {...current,matched_disclosed_pct:'90'}, {...current,matched_disclosed_pct:101},
    {...current,rule_version:'disclosed_stock_gt75_v1'}, {...current,rule_version:'disclosed_stock_majority_rank_v2'},
    {status:'matched'}, {status:'matched',matched_disclosed_pct:90}
  ]){
    const result=rate([sample({score:99,board_match:match})],'risk_on',board);
    assert.equal(result.recommendation_index,null);assert.equal(result.recommended,false);assert.equal(result.level,'unknown');
  }
});
test('recommended boards sort first, followed by effective score, and unknown boards last', () => {
  const record={time:new Date().toISOString(),strategy:{regime:{mode:'risk_on'}}};
  const boards=[{id:'empty',status:'no_match'},{id:'blocked',status:'observation'},{id:'good',status:'candidate'},{id:'watch',status:'observation'}];
  const sections=[{id:'blocked',funds:[sample({score:99,action:'暂缓新增'})]},
    {id:'good',funds:[sample({score:75})]},
    {id:'watch',funds:[sample({score:90,role:'observation'})]}];
  const before=JSON.stringify({boards,sections});
  const result=rankResearchBoards(record,boards,sections);
  assert.deepEqual(result.map(board=>board.id),['good','watch','blocked','empty']);
  assert.equal(JSON.stringify({boards,sections}),before);
  assert.equal(result[1].opportunity.recommendation_index,71);
});
