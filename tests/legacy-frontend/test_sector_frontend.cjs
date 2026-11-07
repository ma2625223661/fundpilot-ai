const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const ui=require('../../dist/sector-research.js');

test('retained closed basket displays its original close date and recovery explanation',()=>{
  const s=ui.normalizeSector({id:'x',status:'ok',score:50,change_pct:1,as_of:'2026-10-30T15:00:00+08:00',
    quote:{data_frequency:'daily'},custom_index:{ready:true,data_recovery:'verified_close',data_note:'盘中报价未齐，使用最近收盘。'}});
  const view=ui.sectorDataPresentation(s);
  assert.equal(view.dataTimeText,'收盘数据 · 2026-10-30');
  assert.equal(view.recoveryNote,'盘中报价未齐，使用最近收盘。');
  assert.match(view.subtitle,/2026-10-30 收盘/);
});

test('legacy product reports are rejected instead of converted into sector analysis',()=>{
  assert.equal(ui.normalizeReport({sections:[{funds:[{code:'003121'}]}],snapshot:{funds:[{code:'003121'}]}}),null);
});
test('sector report uses a whitelist and drops old net value sources and product payloads',()=>{
  const report=ui.normalizeReport({research_scope:'sectors',as_of:'2026-10-30T15:00:00+08:00',
    sector_analysis:[{id:'sector_liquor',title:'白酒',status:'current',score:71,sources:[{id:'nav:003121',name:'基金 003121 净值'},{id:'sector_quotes',name:'板块行情'}]}],
    snapshot:{funds:[{code:'003121'}],sources:[{id:'nav:003121',name:'基金 003121 净值'},{id:'sector_quotes',name:'板块行情'}],news:[{source_id:'announcements_003121',title:'基金公告'},{source_id:'news_sina',title:'白酒板块上涨'}]},
    candidate_references:[{code:'003121'}],quant:[{code:'003121'}]});
  assert.equal(report.snapshot.funds,undefined);
  assert.equal(report.candidate_references,undefined);
  assert.equal(report.quant,undefined);
  assert.deepEqual(report.snapshot.sources.map(s=>s.id),['sector_quotes']);
  assert.deepEqual(report.sector_analysis[0].sources.map(s=>s.id),['sector_quotes']);
  assert.equal(report.snapshot.news.length,1);
});
test('unknown or expired sector evidence cannot receive a fabricated recommendation index',()=>{
  const unknown=ui.normalizeSector({id:'a',title:'AI应用',status:'unknown',score:91});
  const zero=ui.normalizeSector({id:'b',status:'current',score:0,change_pct:0});
  const stale=ui.normalizeSector({id:'c',status:'stale',score:80});
  assert.equal(unknown.score,null);assert.equal(stale.score,null);assert.equal(zero.score,0);assert.equal(ui.pct(null),'*****');assert.equal(ui.pct(0),'0.00%');
});
test('ranking keeps every sector including unknown rows after scored directions',()=>{
  const items=[{id:'a',title:'白酒',score:null},{id:'b',title:'半导体',score:75},{id:'c',title:'煤炭',score:29}];
  assert.deepEqual(ui.sortSectors(items).map(s=>s.id),['b','c','a']);assert.equal(items[0].id,'a');
  assert.notDeepEqual(ui.colorForScore(90),ui.colorForScore(10));
});
test('source acquisition time cannot silently become the underlying market data time',()=>{
  const report=ui.normalizeReport({research_scope:'sectors',sector_analysis:[],snapshot:{sources:[{id:'sector_quotes',fetched_at:'2026-10-30T20:00:00+08:00'}]}});
  assert.equal(report.snapshot.sources[0].as_of,'');assert.equal(report.snapshot.sources[0].fetched_at,'2026-10-30T20:00:00+08:00');
});
test('sector AI explanations are preserved without changing measured scores',()=>{
  const s=ui.normalizeSector({id:'x',status:'current',score:60,ai_reason:'板块弱于市场',ai_risks:['波动风险'],ai_invalidation:'行业指数转强'});
  assert.equal(s.score,60);assert.equal(s.ai_analysis,'板块弱于市场');assert.deepEqual(s.ai_risks,['波动风险']);assert.equal(s.ai_invalidation,'行业指数转强');
});
test('runtime page only loads the sector workspace and has no product research controls',()=>{
  const html=fs.readFileSync(path.join(__dirname,'../../dist/index.html'),'utf8');
  assert.match(html,/src="sector-research\.js(?:\?[^"<>]*)?"/);assert.doesNotMatch(html,/src="app\.js"/);
  assert.doesNotMatch(html,/id="(?:codes|analyzeForm|funds|quantRows|breadthChart|boardPendingDirections|prefsForm)"/);
  assert.doesNotMatch(html,/基金|净值|持仓/);
  assert.match(html,/id="aiScheduleInterval"[^>]*type="number"/);
  assert.match(html,/id="aiScheduleEndTime"/);
});


test('sector data gap diagnostics preserve only explicit messages and traceable source ids',()=>{
 const s=ui.normalizeSector({id:'x',status:'missing',score:98,data_status_summary:'参考行情没有返回此板块报价',reference_expected:'精确匹配的板块价格指数',data_gaps:[{code:'quote_not_returned',message:'来源正常，但没有对应报价',source_ids:['quote_source',null,42],token:'private'},null],token:'private'});
 assert.equal(s.score,null);assert.equal(s.data_status_summary,'参考行情没有返回此板块报价');assert.equal(s.reference_expected,'精确匹配的板块价格指数');
 assert.deepEqual(s.data_gaps,[{code:'quote_not_returned',message:'来源正常，但没有对应报价',source_ids:['quote_source']}]);assert.doesNotMatch(JSON.stringify(s),/private/);
});

test('missing quote rows distinguish failure, missing mapping, no result and stale evidence without faking numbers',()=>{
 const gap=code=>ui.normalizeSector({id:code,status:'missing',risk:'资料不足',data_gaps:[{code,source_ids:[]}]});
 const missing=ui.sectorDataPresentation(gap('quote_mapping_missing'));assert.equal(missing.scoreText,'未评分');assert.equal(missing.scoreUnit,'');assert.equal(missing.changeText,'行情未接入');assert.equal(missing.riskText,'未评估');assert.equal(missing.trendText,'未评估');assert.match(missing.subtitle,/准确对应/);
 assert.equal(ui.sectorDataPresentation(gap('quote_source_failed')).changeText,'采集失败');
 assert.equal(ui.sectorDataPresentation(gap('quote_not_returned')).changeText,'暂无有效行情');
 assert.equal(ui.sectorDataPresentation(gap('asset_source_missing')).changeText,'行情未接入');
 const stale=ui.normalizeSector({id:'old',status:'stale',change_pct:2.2,score:90,data_gaps:[{code:'quote_stale'}]});assert.equal(ui.sectorDataPresentation(stale).changeText,'行情已过期');assert.equal(ui.sectorDataPresentation(stale).scoreText,'未评分');
});

test('valid zero values, measured scores and historical labels survive the diagnostic presentation',()=>{
 const zero=ui.normalizeSector({id:'zero',status:'ok',score:0,change_pct:0,risk:'常规波动',trend:'日内持平'}),strong=ui.normalizeSector({id:'strong',status:'ok',score:88,change_pct:1.25,risk:'常规波动',trend:'趋势偏强'});
 assert.equal(ui.sectorDataPresentation(zero).scoreText,'0');assert.equal(ui.sectorDataPresentation(zero).changeText,'0.00%');assert.equal(ui.sectorDataPresentation(zero).riskText,'常规波动');
 assert.equal(ui.sectorDataPresentation(strong).scoreText,'88');assert.equal(ui.sectorDataPresentation(strong).changeText,'+1.25%');assert.equal(ui.colorForScore(strong.score).color,'#9ef1c2');
 const historical=ui.sectorDataPresentation(strong,{historical:true});assert.equal(historical.scoreText,'88');assert.equal(historical.scoreUnit,'历史 / 100');
 assert.equal(ui.pct(null),'*****');
});

test('company and assessed event evidence remain visible without inventing a sector quote or index',()=>{
 const s=ui.normalizeSector({id:'x',status:'missing',data_status_summary:'未找到精确参考指数',data_gaps:[{code:'quote_mapping_missing'}]});
 const data=ui.sectorDataPresentation(s,{companyCount:3,eventCount:2});
 assert.equal(data.hasQuote,false);assert.equal(data.scoreText,'未评分');assert.match(data.subtitle,/未找到精确参考指数/);assert.match(data.subtitle,/3 个公司样本、2 项重要事件/);assert.match(data.evidenceSummary,/可查看对应经营或事件证据/);
});

test('official daily references retain date precision and bonds explain the absent model',()=>{
 const s=ui.normalizeSector({id:'bond',status:'partial',change_pct:-.17,as_of:'2026-10-30',quote:{name:'中证全债',data_frequency:'daily',as_of_precision:'date',as_of:'2026-10-30'},data_gaps:[{code:'score_model_unavailable',message:'债券模型尚未建立'}]});
 const data=ui.sectorDataPresentation(s);assert.equal(s.quote.as_of_precision,'date');assert.equal(data.changeLabel,'最近交易日涨跌');assert.equal(data.changeText,'-0.17%');assert.match(data.subtitle,/2026-10-30 收盘/);assert.equal(data.scoreNote,'债券评分待建立');assert.equal(data.scoreText,'未评分');
});

test('sector requirements and independent bond methodology stay visible without inventing missing scores',()=>{
 const s=ui.normalizeSector({id:'bond',status:'ok',recommendation_index:59,score_method:'债券趋势模型 v1',score_components:{base:50,drawdown_penalty:-2},requirements:[{id:'data',label:'有效数据',status:'ok',note:'61个近期历史点'},{id:'mapping',status:'ok'},{id:'model',status:'ok'}],quote:{asset_type:'bond',as_of_precision:'date'}});
 assert.equal(s.score,59);assert.equal(s.score_method,'债券趋势模型 v1');assert.equal(s.score_components.drawdown_penalty,-2);assert.equal(s.requirements[0].status,'ok');
 const missing=ui.normalizeSector({id:'x',status:'missing',requirements:[{id:'data',status:'partial',note:'财务缺口'}]});assert.equal(missing.score,null);assert.equal(missing.requirements[0].note,'财务缺口');
});

test('additional data connection has independent actual-data check and never requests a paid token',()=>{
 const html=fs.readFileSync('./dist/index.html','utf8'),js=fs.readFileSync('./dist/sector-research.js','utf8');
 assert.match(html,/id="publicDataCapabilities"/);assert.match(html,/id="testPublicData"/);assert.match(js,/request\('\/api\/data\/public\/test'/);assert.match(js,/applyPublicData\(data.supplemental\)/);assert.match(html,/中证官方成分名单 \+ 腾讯公司行情 \+ 东方财富财务/);
});

test('sector detail renders concrete gaps and relevant failed source status beside available partial evidence',()=>{
 const vm=require('node:vm'),source=fs.readFileSync('./dist/sector-research.js','utf8'),nodes=new Map();
 class Node {constructor(text=''){this.textContent=text||'';this.children=[];this.style={setProperty(){}};}append(...items){this.children.push(...items);}replaceChildren(){this.children=[];}setAttribute(){}get childNodes(){return this.children;}}
 const $=id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);};
 const report=ui.normalizeReport({research_scope:'sectors',as_of:'2026-10-31T12:00:00+08:00',sector_analysis:[{id:'x',title:'测试方向',status:'missing',risk:'资料不足',data_status_summary:'关联行情请求失败',reference_expected:'测试行业指数',data_gaps:[{code:'quote_source_failed',message:'公开行情服务连接超时',source_ids:['quote_source']}]}],snapshot:{sources:[{id:'quote_source',name:'公开行业行情',status:'error',error:'上游服务连接超时',fetched_at:'2026-10-31T11:59:00+08:00'}]},company_evidence:{sector_leaders:{x:[{ts_code:'600000.SH',quote:{close:12}}]}},event_analysis:{events:[]}});
 const ctx=vm.createContext({$,report,selected:'x',sectorDataPresentation:ui.sectorDataPresentation,sourceStatusLabel:ui.sourceStatusLabel,el:(tag,text)=>new Node(text),applyTone:()=>{},groups:{other:'其他方向'},stamp:value=>value||'*****',num:value=>String(value),pct:ui.pct,UNKNOWN:'*****',sectorIndicator:ui.sectorIndicator,indicatorNode:()=>new Node('signal'),document:{createTextNode:text=>new Node(text)},list:(heading)=>new Node(heading),renderCompanyEvidence:()=>{},link:title=>new Node(title)});
 ctx.researchPanels=ui.researchPanels;
 ctx.scarcityUI=null;
 const from=source.indexOf('  function renderIndependentIndex('),to=source.indexOf('  function renderBoards()',from);vm.runInContext(source.slice(from,to),ctx);ctx.renderDetail();
 const text=node=>[node.textContent,...node.children.map(text)].join(' '),result=text($('#sectorDetail'));
 assert.match(result,/未评分/);assert.match(result,/采集失败/);assert.match(result,/未评估/);assert.match(result,/数据缺口与采集状态/);assert.match(result,/公开行情服务连接超时/);assert.match(result,/公开行业行情/);assert.match(result,/上游服务连接超时/);assert.match(result,/参考行情：测试行业指数/);assert.match(result,/已有 1 个公司样本/);assert.doesNotMatch(result,/推荐指数 \/ 100/);
});
