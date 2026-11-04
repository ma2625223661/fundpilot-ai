'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {test} = require('node:test');
const opportunity = require('./dist/board-opportunity.js');
const source = fs.readFileSync(require.resolve('./dist/app.js'),'utf8');
class Element {
  constructor(tag,text='',cls='') { this.tag=tag;this.textContent=text ?? '';this.className=cls;this.children=[];this.dataset={};this.style={};this.attributes={}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children=[...nodes];this.textContent=''; }
  setAttribute(name,value) { this.attributes[name]=value; }
}
const elements = new Map();
const context = vm.createContext({...opportunity,
  $:id=>{if(!elements.has(id))elements.set(id,new Element('div'));return elements.get(id);},
  el:(tag,text,cls)=>new Element(tag,text,cls),
  array:value=>Array.isArray(value)?value:[], string:(value,fallback='')=>typeof value==='string'?value:fallback,
  stamp:value=>value || '时间未提供', number:value=>Number.isFinite(value)?value.toFixed(2):'—',
  percent:value=>Number.isFinite(value)?value.toFixed(2)+'%':'—',
  link:(text)=>new Element('a',text), renderFundBoards:()=>{},
  boardFilter:{group:'all',query:'',id:null}
});
vm.runInContext(source.slice(source.indexOf('function filterResearchBoards('),source.indexOf('function renderFundBoards(')),context);
vm.runInContext(source.slice(source.indexOf('function concise('),source.indexOf('function fundCategory(')),context);
vm.runInContext(source.slice(source.indexOf('function renderMarketOverview(')),context);
const text=node=>String(node.textContent || '')+node.children.map(text).join(' ');
const descendants=(node,cls)=>[...(node.className===cls?[node]:[]),...node.children.flatMap(child=>descendants(child,cls))];
const overview=()=>({as_of:'2026-10-30T14:00:00+08:00',
  indices:[{name:'上证指数',value:3200,change_pct:1,status:'ok',as_of:'2026-10-30T14:00:00+08:00'}],
  breadth:{status:'partial',scope:'公开基金样本，A/C按代码计数',scope_count:100,
    covered_count:4,total:4,up:2,down:1,flat:1,nav_date:'2026-10-29',
    date_range:{min:'2026-10-28',max:'2026-10-29'},
    reason:'只统计同一净值日的真实日收益。',
    buckets:[{label:'小于0',direction:'down',count:1},{label:'0',direction:'flat',count:1},{label:'大于0',direction:'up',count:2}]}});

test('fund breadth never falls back to index moves or historical interval returns',()=>{
  const result=context.marketOverviewModel({snapshot:{market:[{name:'指数',last:100,change_pct:2}],
    funds:[{return_1w:9,history:[{return_pct:2}]}]}});
  assert.equal(result.indices.length,1);
  assert.equal(result.indices[0].value,100);
  assert.equal(result.usable,false);
  assert.equal(result.buckets.length,0);
});
test('breadth requires consistent same-day counts and explicit chart directions',()=>{
  const record={market_overview:overview()};
  assert.equal(context.marketOverviewModel(record).usable,true);
  for(const mutate of [b=>b.up=3,b=>b.nav_date=null,b=>b.buckets[0].count=2,b=>delete b.buckets[0].direction]) {
    const invalid=structuredClone(record);mutate(invalid.market_overview.breadth);
    assert.equal(context.marketOverviewModel(invalid).usable,false);
  }
});
test('stale overview preserves actual snapshot dates and clearly marks old data',()=>{
  context.renderMarketOverview({market_overview:overview(),report_stale:true});
  assert.match(text(elements.get('#overviewAsOf')),/上次数据.*等待更新/);
  assert.match(text(elements.get('#overviewIndices')),/2026-10-30/);
  assert.match(text(elements.get('#breadthScope')),/统计净值日 2026-10-29/);
  assert.match(text(elements.get('#breadthScope')),/2026-10-28 至 2026-10-29/);
  assert.match(text(elements.get('#breadthNote')),/红涨绿跌.*红低绿高/);
});
test('unconnected sources are disclosed without contributing invented chart samples',()=>{
  context.renderMarketOverview({market_overview:overview(),source_connections:[{
    label:'养基宝',status:'unavailable',checked_at:'2026-10-30T13:50:00+08:00',
    reason:'需要登录授权与签名接口，当前未接通。',url:'https://example.test/source'
  }]});
  assert.match(text(elements.get('#overviewSources')),/养基宝 · 尚未接通/);
  assert.match(text(elements.get('#overviewSources')),/2026-10-30T13:50:00/);
  assert.match(text(elements.get('#breadthSampleCount')),/有效样本 4 只/);
  assert.equal(elements.get('#breadthChart').children.length,3);
});
test('pending research is grouped by evidence gaps, preserves historical counts, and remains searchable',()=>{
  const coverage=[
    {id:'chip',label:'半导体',group:'industry',status:'candidate',requires_holdings_match:true,deep_count:4},
    {id:'liquor',label:'白酒',group:'industry',status:'holdings_pending',deep_count:1,reason:'未取得有效的持仓报告。'},
    {id:'bank',label:'银行',group:'industry',status:'not_researched',deep_count:0}
  ];
  const fund={name:'持仓测试基金',quality:'ok',score:90,role:'candidate',action:'7 天以上研究候选',risk_check_complete:true,risk_flags:[],
    board_match:{status:'matched',rule_version:'single_board_holdings_rank_v4',matched_disclosed_pct:60}};
  const sections=[{id:'chip',funds:[fund]}];
  const record={time:new Date().toISOString(),strategy:{regime:{mode:'risk_on'}},market_overview:overview()};
  Object.assign(context.boardFilter,{group:'all',query:'',id:null,pendingCategory:'all',pendingId:null});
  context.renderBoardExplorer(record,coverage,sections);
  assert.equal(elements.get('#boardDirectory').children.length,1);
  assert.match(text(elements.get('#boardDirectory')),/半导体.*90/);
  assert.match(text(elements.get('#boardDirectory')),/历史已深研 4 只 · 当前上限 3/);
  assert.match(text(elements.get('#boardDirectory')),/优选 1 \/ 最多 3/);
  const pending=elements.get('#boardPendingDirections').children[0];
  assert.match(text(pending.children[0]),/待完善研究.*2 个方向/);
  assert.equal(descendants(pending,'research-gap-group').length,2);
  assert.ok(descendants(pending,'research-gap-group').every(group=>group.open===false));
  assert.doesNotMatch(text(pending),/推荐指数 \/ 100|—/);
  Object.assign(context.boardFilter,{query:'白酒',id:null,pendingCategory:'all'});
  context.renderBoardExplorer(record,coverage,sections);
  assert.equal(descendants(elements.get('#boardPendingDirections'),'research-gap-group')[0].open,true);
  assert.match(text(elements.get('#boardPendingDirections')),/白酒.*缺少持仓资料/);
  assert.doesNotMatch(text(elements.get('#boardPendingDirections')),/银行/);
});
test('no scored boards produces one explanation and categorized pending research without invented scores',()=>{
  Object.assign(context.boardFilter,{group:'all',query:'',id:null,pendingCategory:'all',pendingId:null});
  context.renderBoardExplorer({market_overview:overview()},[
    {id:'bank',label:'银行',group:'industry',status:'not_researched',deep_count:0}
  ],[]);
  const directory=elements.get('#boardDirectory');
  assert.equal(directory.children.length,1);
  assert.equal(directory.children[0].tag,'p');
  assert.equal(descendants(elements.get('#boardPendingDirections'),'research-gap-group')[0].open,false);
  assert.equal(context.boardFilter.id,null);
  assert.match(text(elements.get('#boardPendingDirections')),/已归类 \*{5}/);
  const progress=descendants(elements.get('#boardPendingDirections'),'research-gap-progress')[0];
  assert.doesNotMatch(text(progress),/已归类 0/);
  assert.doesNotMatch(text(elements.get('#boardPendingDirections')),/推荐指数 \/ 100/);
});

test('gap filters reveal actual progress, next steps and no more than three nonrecommended examples',()=>{
  const coverage=[
    {id:'memory',label:'存储芯片',group:'industry',status:'holdings_pending',requires_holdings_match:true,
      screened_count:20,eligible_count:8,deep_count:3,valid_quant_count:3,matched_holdings_count:0,
      research_gap:{category:'holdings',label:'缺少专属主题证据',summary:'已披露的持仓缺少存储芯片收入证据。',
        next_step:'保持空缺；取得可核验的业务资料后再判断。',automatic:false,
        counts:{screened_count:20,eligible_count:8,deep_count:3,valid_quant_count:3,matched_holdings_count:0},
        examples:Array.from({length:5},(_,i)=>({name:'研究样本'+i,code:'00000'+i,reason:'持仓证据不足'}))}},
    {id:'bank',label:'银行',group:'industry',status:'not_researched',screened_count:10,eligible_count:5,deep_count:0}
  ];
  Object.assign(context.boardFilter,{group:'all',query:'',id:null,pendingCategory:'all',pendingId:null});
  const record={market_overview:overview(),automatic:{per_board_deep_limit:4,per_board_display_limit:8}};
  context.renderBoardExplorer(record,coverage,[]);
  let pending=elements.get('#boardPendingDirections');
  const button=descendants(pending,'research-gap-filter').find(item=>item.dataset.category==='holdings');
  button.onclick();
  assert.equal(context.boardFilter.pendingCategory,'holdings');
  context.renderBoardExplorer(record,coverage,[]);pending=elements.get('#boardPendingDirections');
  const groups=descendants(pending,'research-gap-group');
  assert.equal(groups.length,1);assert.equal(groups[0].open,true);
  const rows=descendants(pending,'research-gap-row');assert.equal(rows.length,1);
  assert.match(text(rows[0]),/已归类 20.*深研 3.*持仓匹配 0/);
  assert.match(text(rows[0]),/持仓已归类.*通过产品初筛.*实际深研.*有效净值.*持仓匹配/);
  assert.match(text(rows[0]),/系统下一步.*取得可核验的业务资料/);
  assert.match(text(rows[0]),/当前仍需补充研究条件/);
  const examples=descendants(rows[0],'research-gap-examples')[0];
  assert.equal(examples.children.length,4);
  assert.match(text(examples),/本轮已研究样本 · 非推荐/);
  assert.doesNotMatch(text(examples),/研究样本3|研究样本4/);
  rows[0].open=true;rows[0].ontoggle();context.renderBoardExplorer(record,coverage,[]);
  assert.equal(descendants(elements.get('#boardPendingDirections'),'research-gap-row')[0].open,true);
  assert.match(text(elements.get('#boardCoverageSummary')),/深研、展示均最多 3 只/);
});

test('old report gaps preserve unknown counts and stale reports request current evidence',()=>{
  const gap=context.boardResearchGap({status:'unknown',catalog_counts_known:false,screened_count:0,eligible_count:0});
  assert.equal(gap.category,'insufficient');assert.equal(gap.counts.screened_count,null);assert.equal(gap.counts.deep_count,null);
  const stale=context.boardResearchGap({status:'holdings_pending',research_gap:{category:'holdings',summary:'旧依据',next_step:'旧下一步',automatic:true}},{report_stale:true});
  assert.equal(stale.category,'stale_data');assert.match(stale.summary,/报告已过期/);
  assert.match(stale.next_step,/重新获取净值/);assert.equal(stale.automatic,null);
});

test('internet discovery displays search provenance and candidate checks without becoming deep research or a recommendation',()=>{
  const board={id:'memory',label:'存储芯片',group:'industry',status:'holdings_pending',requires_holdings_match:true,deep_count:0,
    web_search:{status:'ok',query:'存储芯片 基金',searched_at:'2026-10-30T15:00:00+08:00',attempts:2,
      candidates:Array.from({length:4},(_,i)=>({code:'00000'+i,name:'搜索基金'+i,status:i?'discovery_only':'research_selected',
        source_url:'https://example.test/fund/'+i,screening_reason:i?'尚未核验净值与持仓':'只进入计划，尚未完成深研'}))}};
  Object.assign(context.boardFilter,{group:'all',query:'',id:null,pendingCategory:'all',pendingId:null});
  context.renderBoardExplorer({market_overview:overview()},[board],[]);
  const pending=elements.get('#boardPendingDirections');const discovery=descendants(pending,'research-gap-discovery')[0];
  assert.match(text(discovery),/互联网补充发现.*已完成搜索.*2026-10-30T15:00:00/);
  assert.match(text(discovery),/搜索词：存储芯片 基金.*尝试 2 次/);
  assert.match(text(discovery),/已进入深研计划.*尚未完成深研/);
  assert.equal(descendants(discovery,'research-gap-discovered-fund').length,3);
  assert.doesNotMatch(text(discovery),/搜索基金3/);
  assert.match(text(discovery),/搜索发现不计为推荐或已深研/);
  assert.match(text(descendants(pending,'research-gap-progress')[0]),/深研 0/);
  assert.equal(context.boardWebSearchModel(board).total,4);
  board.web_search={status:'failed',query:'存储芯片 基金',searched_at:'2026-10-30T16:00:00+08:00',error:'搜索源超时',candidates:[]};
  context.renderBoardExplorer({market_overview:overview()},[board],[]);
  const failed=descendants(elements.get('#boardPendingDirections'),'research-gap-discovery')[0];
  assert.match(text(failed),/搜索失败.*搜索源超时.*不据此判断该板块没有基金/);
});

test('legacy matched evidence is kept as original text only and cannot create a current scored strategy',()=>{
  const board={id:'old',label:'旧主题',group:'industry',status:'observation',requires_holdings_match:true};
  const old={name:'历史基金',code:'000001',quality:'ok',score:99,role:'candidate',risk_flags:[],risk_check_complete:true,
    reason:'这是旧报告的原始理由',action:'原建仓计划',board_match:{status:'matched',rule:'当时按50%规则'}};
  const record={time:new Date().toISOString(),strategy:{regime:{mode:'risk_on'}},market_overview:overview(),sections:[{id:'old',funds:[old]}]};
  Object.assign(context.boardFilter,{group:'all',query:'',id:null,pendingCategory:'all',pendingId:null});
  context.renderBoardExplorer(record,[board],record.sections);
  assert.doesNotMatch(text(elements.get('#boardDirectory')),/99/);
  const history=descendants(elements.get('#boardPendingDirections'),'research-gap-history')[0];
  assert.match(text(history),/旧报告原文 · 不作为当前合格策略.*旧报告的原始理由.*当时按50%规则/);
});

test('uncollected holdings are a queue and dynamic direction counts come from actual board coverage',()=>{
  const coverage=[
    {id:'base',label:'银行',group:'industry',status:'no_match',screened_count:0},
    {id:'dynamic_a',label:'已发现细分',group:'industry',status:'no_match',dynamic:true,screened_count:0},
    {id:'holdings_unclassified',label:'持仓待归类',group:'other',status:'holdings_pending',screened_count:120}
  ];
  const record={market_overview:overview(),universe:{coverage:{holdings_checked_total:42,holdings_unchecked_total:120,dynamic_board_count:99}}};
  Object.assign(context.boardFilter,{group:'all',query:'',id:null,pendingCategory:'all',pendingId:null});
  context.renderBoardExplorer(record,coverage,[]);
  assert.match(text(elements.get('#boardCoverageSummary')),/覆盖 2 个方向（含 1 个按持仓发现的细分方向）/);
  const pending=elements.get('#boardPendingDirections');
  assert.match(text(pending),/2 个方向 · 1 项归类队列/);
  assert.match(text(pending),/已预检 42 只 · 待采集 120 只/);
  assert.match(text(pending),/它不是投资板块/);
  assert.match(text(pending),/已归类 0/);
  assert.doesNotMatch(text(pending),/未找到样本|未找到对应样本/);
});

test('forced members stay selectable before scoring and gaps explain their inclusion with masked unknowns',()=>{
  const ref={code:'022073',name:'公开搜索基金',requested_board_id:'overseas_hk_dividend',source_kind:'web_discovery',forced_selection:true};
  const board={id:'overseas_hk_dividend',label:'港股红利',group:'overseas',status:'observation',displayed_count:1,
    requires_holdings_match:true,reference_candidates:[ref],research_gap:{category:'holdings',next_step:'缺少证据时保持空缺。'},
    web_search:{status:'partial',candidates:[{...ref,status:'discovery_only'}]}};
  Object.assign(context.boardFilter,{group:'all',query:'',id:board.id,pendingCategory:'all',pendingId:null});
  const record={market_overview:overview()};
  context.renderBoardExplorer(record,[board],[{id:board.id,funds:[ref]}]);
  assert.equal(context.boardFilter.id,board.id);
  assert.match(text(elements.get('#boardDirectory')),/港股红利.*已纳入板块.*\*{5}.*已纳入 1/);
  const pending=elements.get('#boardPendingDirections');
  assert.match(text(pending),/系统下一步.*已强制纳入该板块；未知数据统一标记为 \*{5}/);
  assert.doesNotMatch(text(descendants(pending,'research-gap-next')[0]),/保持空缺/);
  assert.match(text(pending),/持仓匹配：\*{5}.*推荐指数：\*{5}.*持仓报告日：\*{5}/);
});
