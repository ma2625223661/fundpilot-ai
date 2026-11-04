'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {test} = require('node:test');
const appSource = fs.readFileSync(require.resolve('./dist/app.js'), 'utf8');
// Execute the actual pure UI helpers without running browser initialization.
const helpers = appSource.slice(appSource.indexOf('function filterResearchBoards('), appSource.indexOf('function renderFundBoards('));
const context = vm.createContext({array:value=>Array.isArray(value)?value:[]});
vm.runInContext(helpers, context);
const filter = context.filterResearchBoards;
const state = context.fundResearchState;
const sectionContext=vm.createContext({...require('./dist/board-opportunity.js'),
  array:value=>Array.isArray(value)?value:[],string:(value,fallback='')=>typeof value==='string'?value:fallback});
vm.runInContext(appSource.slice(appSource.indexOf('function fundCategory('),appSource.indexOf('function addPlanDetails(')),sectionContext);
const boards = [
  {id:'liquor',label:'白酒',group:'industry',description:'白酒方向',aliases:['酿酒']},
  {id:'bank',label:'银行',group:'industry',family:'finance'},
  {id:'cpo',label:'CPO',group:'industry',aliases:['光通信']},
  {id:'hk',label:'港股互联',group:'overseas'},
  {id:'money',label:'货币基金',group:'defensive'}
];

test('showing all strategies keeps the selected group and search intersection', () => {
  assert.deepEqual(Array.from(filter(boards,'industry','酿酒'),board=>board.id),['liquor']);
  assert.deepEqual(Array.from(filter(boards,'finance',''),board=>board.id),['bank']);
  assert.deepEqual(Array.from(filter(boards,'overseas','白酒'),board=>board.id),[]);
  assert.deepEqual(Array.from(filter(boards,'all','cPo'),board=>board.id),['cpo']);
});
test('board filters preserve recommendation order and explicitly selected empty directions', () => {
  const ranked = [{...boards[2],displayed_count:2},{...boards[0],displayed_count:0},{...boards[1],displayed_count:1}];
  const result=filter(ranked,'industry','');
  assert.deepEqual(Array.from(result,board=>board.id),['cpo','liquor','bank']);
  assert.equal(result.find(board=>board.id==='liquor').displayed_count,0);
  assert.equal(ranked.length,3);
});
test('verified research candidate stays distinct from unverified execution permission', () => {
  const candidate=state({role:'candidate',action:'7 天以上研究候选',risk_flags:[],quality:'ok',risk_check_complete:true,execution_eligible:false},
    {new_position:'支付宝可购与交易条款未验证，暂不生成可执行买入指令。'});
  assert.equal(candidate.riskBlocked,false);
  assert.equal(candidate.executionUnverified,true);
  assert.equal(candidate.tone,'candidate');
  assert.equal(candidate.label,'研究候选 · 可买状态尚未确认');
});
test('actual risk limits, defensive actions and incomplete risk checks remain blocked', () => {
  for (const fund of [{action:'暂缓新增'},{action:'防御期暂停新增'},{action:'考虑减仓（如持有）'},
    {risk_flags:['波动超限']},{risk_check_complete:false},{quality:'stale'}]) {
    const result=state({role:'candidate',execution_eligible:false,...fund});
    assert.equal(result.riskBlocked,true);
    assert.equal(result.tone,'blocked');
    assert.match(result.label,/风险条件未通过/);
  }
});

test('current and legacy sections display at most three funds while retaining holdings gates',()=>{
  const funds=Array.from({length:5},(_,i)=>({code:'00000'+i,name:'测试指数基金'+i,
    board_match:{status:'matched',rule_version:'single_board_holdings_rank_v4',matched_disclosed_pct:60}}));
  const record={automatic:{per_board_display_limit:9},sections:[{id:'chip',requires_holdings_match:true,
    funds:[{code:'bad',name:'不匹配基金',board_match:{status:'mismatch'}},
      {code:'old',name:'旧50%规则基金',board_match:{status:'matched'}},
      {code:'equal75',name:'恰好75%基金',board_match:{status:'matched',rule_version:'disclosed_stock_gt75_v1',matched_disclosed_pct:75}},
      funds[0],funds[0],...funds.slice(1)]}]};
  const sections=sectionContext.reportSections(record);
  assert.deepEqual(Array.from(sections[0].funds,f=>f.code),['000000','000001','000002']);
  assert.equal(record.sections[0].funds.length,9,'display cap must preserve the source report');
  const legacy=sectionContext.reportSections({analysis:{funds}});
  assert.equal(legacy[0].funds.length,3);
  assert.ok(legacy[0].funds.every(f=>f.role==='observation' && f.can_trade===false));
});

test('holdings summary labels the disclosed-stock ratio and never substitutes NAV weight',()=>{
  const disclosure=context.holdingsMatchSummary({status:'matched',matched_disclosed_pct:82.36,matched_weight_pct:19});
  assert.equal(disclosure.title,'已披露股票匹配 82.36%');
  assert.match(disclosure.note,/仅报告已披露部分，不代表全仓/);
  assert.equal(context.holdingsMatchSummary({status:'matched',matched_weight_pct:19}).title,'已披露股票匹配 *****');
  assert.equal(context.holdingsMatchSummary({status:'not_required'}).title,'按资产类型归类');
  const lower=context.holdingsMatchSummary({status:'matched',matched_disclosed_pct:200/3,ratio_is_lower_bound:true});
  assert.match(lower.title,/已确认至少 66\.66%/);
  assert.match(lower.note,/仍计入分母/);
});

test('one fund is shown only in its highest disclosed-stock exposure board and cards rank by that ratio',()=>{
  const fund=(code,ratio,comparison=[])=>({code,name:'名称仅展示 '+code,board_comparison:comparison,
    board_match:{status:'matched',rule_version:'single_board_holdings_rank_v4',matched_disclosed_pct:ratio}});
  const record={sections:[
    {id:'broad',requires_holdings_match:true,funds:[fund('same',65),fund('low',55),fund('high',90),fund('mid',70),fund('cut',51)]},
    {id:'narrow',requires_holdings_match:true,funds:[fund('same',86)]}
  ]};
  const original=JSON.stringify(record);
  const result=sectionContext.reportSections(record);
  assert.deepEqual(Array.from(result[0].funds,f=>f.code),['high','mid','low']);
  assert.deepEqual(Array.from(result[1].funds,f=>f.code),['same']);
  assert.equal(JSON.stringify(record),original);
  assert.equal(result.flatMap(section=>section.funds).filter(f=>f.code==='same').length,1);
});

test('equal exposure follows the server finer-board comparison and explicit hierarchy, never fund name',()=>{
  const match={status:'matched',rule_version:'single_board_holdings_rank_v4',matched_disclosed_pct:90};
  const fund={code:'tie',name:'任意基金名称',board_match:match,
    board_comparison:[{id:'narrow',matched_disclosed_pct:90},{id:'broad',matched_disclosed_pct:90}]};
  let result=sectionContext.reportSections({sections:[
    {id:'broad',requires_holdings_match:true,funds:[fund]},
    {id:'narrow',requires_holdings_match:true,funds:[fund]}
  ]});
  assert.equal(result[0].funds.length,0);assert.equal(result[1].funds.length,1);
  result=sectionContext.reportSections({sections:[
    {id:'broad',requires_holdings_match:true,hierarchy_depth:1,funds:[{...fund,board_comparison:[]}]},
    {id:'narrow',requires_holdings_match:true,hierarchy_depth:3,funds:[{...fund,board_comparison:[]}]}
  ]});
  assert.equal(result[0].funds.length,0);assert.equal(result[1].funds.length,1);
});

test('comparison is bounded to six validated ratios and retains confirmed lower bound labels',()=>{
  const rows=Array.from({length:8},(_,i)=>({id:'board'+i,label:'板块'+i,matched_disclosed_pct:95-i,ratio_is_lower_bound:i===0}));
  const result=context.holdingsBoardComparison({board_comparison:[...rows,{id:'bad',matched_disclosed_pct:101},rows[0]]},'board0');
  assert.equal(result.length,6);assert.equal(result[0].selected,true);assert.equal(result[0].ratio_is_lower_bound,true);
  assert.deepEqual(Array.from(result,item=>item.id),['board0','board1','board2','board3','board4','board5']);
  assert.deepEqual(Array.from(context.holdingsBoardComparison({board_comparison:[{id:'invalid',matched_disclosed_pct:'90'}]},'invalid')),[]);
});

test('holdings report date and current mapping dates stay distinct and missing dates stay unknown',()=>{
  const result=context.holdingsEvidenceDates({report_date:'2026-09-30',mapping_source_dates:['2026-10-30','2026-10-29','2026-10-30'],
    stock_evidence:[{membership_sources:[{source_date:'2026-10-29'},{source_date:'2026-99-01'}]}]});
  assert.equal(result.report_date,'2026-09-30');
  assert.deepEqual(Array.from(result.mapping_dates),['2026-10-29','2026-10-30']);
  const absent=context.holdingsEvidenceDates({report_date:'2026-02-30',fetched_at:'2026-10-30T16:00:00+08:00'});
  assert.equal(absent.report_date,null);assert.equal(absent.mapping_dates.length,0,'fetch time cannot stand in for source mapping date');
});
