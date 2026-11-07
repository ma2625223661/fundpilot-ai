const test=require('node:test');
const assert=require('node:assert/strict');
const ui=require('../../dist/sector-research.js');

test('eight verified companies and constituents survive display normalization',()=>{
 const companies=Array.from({length:8},(_,i)=>({ts_code:String(600000+i)+'.SH',name:'公司'+i,selection_basis:'公开业务及财务核验'}));
 const evidence=ui.normalizeReport({research_scope:'sectors',sector_analysis:[],company_evidence:{sector_leaders:{x:companies},sample_selection:{x:{candidate_count:12,ready_count:8,selected_count:8,pending:[{name:'候选',ts_code:'000001.SZ',reason:'近期走势待补齐'}]}}}}).company_evidence;
 assert.equal(evidence.sector_leaders.x.length,8);assert.equal(evidence.sample_selection.x.pending[0].reason,'近期走势待补齐');
 const s=ui.normalizeSector({id:'x',custom_index:{constituents:companies.map(r=>({code:r.ts_code,name:r.name,weight_pct:12.5}))}});
 assert.equal(s.custom_index.constituents.length,8);assert.equal(s.custom_index.constituents.reduce((sum,r)=>sum+r.weight_pct,0),100);
});

test('pending financial evidence cannot display as verified solely from a future date',()=>{
 const report=ui.normalizeReport({research_scope:'sectors',as_of:'2026-10-31',sector_analysis:[{id:'x'}],company_evidence:{sector_leaders:{x:[{ts_code:'600000.SH',name:'候选',sample_checks:{'披露日财务':false},financials:{ann_date:'2099-01-01',end_date:'2026-09-30',eps:1}}]}}});
 const panel=ui.researchPanels(report.sector_analysis[0],report)[1];
 assert.match(panel.value,/0\/1/);assert.match(panel.lines[0],/核验未通过/);
});

test('reference scores retain limited scope and link their own measured evidence',()=>{
 const s=ui.normalizeSector({id:'x',status:'ok',score:59,score_scope:'reference_trend',score_label:'参考走势分数',sources:[{id:'reference:x',name:'参考指数'}]});
 const panel=ui.researchPanels(s)[4];
 assert.equal(panel.title,'参考走势分数');assert.match(panel.lines.join(' '),/公司财务.*没有计入/);assert.ok(panel.source_ids.includes('reference:x'));
 assert.equal(ui.sectorDataPresentation(s).scoreUnit,'参考走势 / 100');
});

test('money research shows annual rate and basis points without fictional stock returns',()=>{
 const s=ui.normalizeSector({id:'money',status:'ok',score:53,score_scope:'money_liquidity',score_label:'资金利率研究分数',quote:{asset_type:'money_rate',annual_rate_pct:1.289,change_bp:.7},metrics:{sample_count:121,annual_rate_pct:1.289,rate_change_5d_bp:-1,rate_change_20d_bp:2},sources:[{id:'rate:money',name:'隔夜Shibor'}]});
 const presentation=ui.sectorDataPresentation(s),panels=ui.researchPanels(s);
 assert.equal(presentation.changeLabel,'隔夜年化利率');assert.equal(presentation.changeText,'1.289%');assert.ok(presentation.hasQuote);
 assert.equal(presentation.scoreUnit,'资金利率 / 100');
 assert.match(panels[0].lines.join(' '),/-1.00 基点/);assert.equal(panels[1].title,'资金利率依据');assert.ok(panels[4].source_ids.includes('rate:money'));
});

test('custom index fields remain explicit and arbitrary provider fields are dropped',()=>{
 const s=ui.normalizeSector({id:'x',status:'ok',score:65,research_basis:'leader_sample',custom_index:{name:'独立指标',ready:true,value:108,sample_count:2,history_count:80,secret:'hidden',constituents:[{code:'600000.SH',name:'甲',weight_pct:50,secret:'hidden'}],history:[{date:'2026-10-30',value:108},{date:'bad',value:99}]}});
 assert.equal(s.custom_index.value,108);assert.equal(s.custom_index.constituents[0].weight_pct,50);assert.equal(s.custom_index.history.length,1);assert.doesNotMatch(JSON.stringify(s),/hidden/);
 assert.equal(ui.sectorDataPresentation(s).changeLabel,'龙头样本涨跌');
});
test('microcap saved reports use small cap sample wording without changing data',()=>{
 const input={id:'style_microcap',status:'ok',score:24.81,change_pct:-3.56,research_basis:'leader_sample',data_status_summary:'自建龙头样本指标 · 8只等权样本 · 121个共同历史点',summary:'龙头样本分析：样本走势偏弱',reasons:['本网站独立编制龙头样本指标'],custom_index:{name:'微盘股 · 小市值股票观察指标',method:'自建龙头样本指标 v1；不是历史龙头组合',scope:'国证A股池内按市值从小到大选样；不是官方微盘指数',sample_count:8,history_count:121,constituents:[]}};
 const s=ui.normalizeSector(input),panel=ui.researchPanels(s)[0],display=ui.sectorDataPresentation(s);
 assert.equal(s.custom_index.name,'微盘股 · 小市值样本指标');assert.match(s.custom_index.method,/自建小市值样本指标/);assert.match(s.custom_index.scope,/市值从小到大/);
 assert.match(display.subtitle,/自建小市值样本指标/);assert.equal(display.changeLabel,'小市值样本涨跌');assert.equal(panel.title,'小市值样本走势');assert.match(panel.lines[0],/非官方微盘指数/);
 assert.doesNotMatch([s.summary,...s.reasons,display.subtitle,s.custom_index.method].join(' '),/龙头/);
 assert.equal(s.score,24.81);assert.equal(s.change_pct,-3.56);assert.equal(s.custom_index.sample_count,8);assert.equal(s.custom_index.history_count,121);assert.match(input.data_status_summary,/龙头样本/);
});
test('all five evidence dimensions are available without inventing earnings or events',()=>{
 const s=ui.normalizeSector({id:'x',status:'partial',research_basis:'leader_sample',custom_index:{constituents:[]},metrics:{return_20d:2,sample_count:80},score:null});
 const panels=ui.researchPanels(s,{event_analysis:{status:'pending'}});
 assert.deepEqual(panels.map(p=>p.title),['龙头走势','业绩支撑','重要事件','大盘风险','综合研究分数']);
 assert.match(panels[1].lines[0],/不补造/);assert.match(panels[2].lines[0],/尚未完成/);assert.match(panels[4].lines[0],/保持未知/);
});
test('resource equity uses company stock scope across all five panels',()=>{
 const s=ui.normalizeSector({id:'commodities',status:'partial',custom_index:{constituents:[]},metrics:{sample_count:80},score:null});
 const panels=ui.researchPanels(s,{event_analysis:{status:'pending'}});
 assert.deepEqual(panels.map(p=>p.title),['资源企业股票走势','业绩支撑','重要事件','大盘风险','综合研究分数']);
 assert.match(panels[0].lines[0],/不是商品现货或期货价格/);
 assert.equal(ui.sectorDataPresentation(s).changeLabel,'资源股票样本涨跌');
});
test('important events and actual financial reporting dates remain traceable',()=>{
 const s=ui.normalizeSector({id:'x',status:'ok',score:59,score_cap:59,score_components:{financial_adjustment:3,event_adjustment:-8}});
 const event={id:'a',title:'官方公告',sector_ids:['x'],direction:'negative',impact_score:-80,reason:'经营影响',source_ids:['cninfo']};
 const p=ui.researchPanels(s,{company_evidence:{sector_leaders:{x:[{name:'甲',source_ids:['finance'],financials:{tr_yoy:10,netprofit_yoy:20,end_date:'2026-09-30',ann_date:'2026-10-30'}}]}},event_analysis:{status:'completed',events:[event]}});
 assert.match(p[1].lines[0],/披露日 2026-10-30/);assert.equal(p[2].events[0],event);assert.deepEqual(p[2].source_ids,['cninfo']);assert.match(p[4].lines.join(' '),/大盘风险约束：最高 59 分/);
});
