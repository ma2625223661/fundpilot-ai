'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const ui=require('../../src/lib/legacy/sector-research.js');
test('explicit withheld score and partial prerequisites cannot reveal raw technical score',()=>{
 assert.equal(ui.normalizeSector({id:'x',status:'ok',score:91,recommendation_index:null}).score,null);
 assert.equal(ui.normalizeSector({id:'x',status:'ok',score:91,requirements:[{id:'data',status:'ok'}]}).score,null);
 const requirements=['data','mapping','model'].map(id=>({id,status:'ok'}));assert.equal(ui.normalizeSector({id:'x',status:'ok',recommendation_index:0,requirements}).score,0);
});
test('finance currency is independent of quote currency and unknown overseas currency stays unknown',()=>{
 const rows=ui.normalizeCompanyEvidence({sector_leaders:{x:[{ts_code:'00700.HK',quote:{currency:'HKD'},financials:{currency:'CNY',eps:4}},{ts_code:'MSFT.US',financials:{eps:3,currency_note:'未核验'}},{ts_code:'600000.SH',financials:{eps:1}}]}}).sector_leaders.x;
 assert.equal(rows[0].financials.currency,'CNY');assert.equal(rows[0].quote.currency,'HKD');assert.equal(rows[1].financials.currency,null);assert.equal(rows[1].financials.currency_note,'未核验');assert.equal(rows[2].financials.currency,'CNY');
});
test('event schedule wording reflects persisted actual configuration',()=>{
 assert.match(ui.eventScheduleText({mode:'market_sessions'}),/09:20 \/ 14:50/);assert.match(ui.eventScheduleText({mode:'interval',interval_minutes:17}),/17.*休市日/);assert.match(ui.eventScheduleText({mode:'daily',daily_time:'11:23'}),/每天 11:23/);assert.match(ui.eventScheduleText({mode:'scheduled_interval',daily_time:'09:00',end_time:'16:00',interval_minutes:45}),/09:00 至 16:00.*45/);
});
test('convertible bonds show asset-specific evidence without fictional company finance',()=>{
 const s=ui.normalizeSector({id:'convertible_bond',quote:{asset_type:'convertible_bond'},asset_research:{financial_applicability:'发行人财务尚未核验',coverage_note:'评级、转股溢价和强赎条款未知',secret:'x'}}),panels=ui.researchPanels(s);
 assert.equal(panels.length,5);assert.equal(panels[0].title,'可转债走势');assert.equal(panels[1].title,'信用与估值依据');assert.match(panels[1].lines.join(' '),/强赎条款未知/);assert.equal(s.asset_research.secret,undefined);
});
test('brain-computer research associations cannot become verified business leadership or segment revenue',()=>{
 const s=ui.normalizeSector({id:'sector_brain_computer',custom_index:{constituents:[]}}),panels=ui.researchPanels(s);
 assert.equal(panels[0].title,'关联样本走势');assert.match(panels[0].lines.join(' '),/非脑机业务收入/);
});
test('historical summary counts follow audited eligible scores and bond evidence has no company-finance gap',()=>{
 const r=ui.normalizeReport({research_scope:'sectors',summary:'2个方向可评分',coverage:{scored_sector_count:2},sector_analysis:[{id:'x',score:80,requirements:[{id:'data',status:'partial'}]},{id:'bond',status:'ok',score:60,quote:{asset_type:'bond'}}]});
 assert.equal(r.summary,'1个方向可评分');assert.equal(r.coverage.scored_sector_count,1);const panels=ui.researchPanels(r.sector_analysis[1]);assert.equal(panels[1].title,'利率与久期依据');assert.equal(panels[1].value,'公司财务不适用');
});
function pollContext(){
 const source=fs.readFileSync('./dist/sector-research.js','utf8'),nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,{hidden:true,textContent:'',disabled:false});return nodes.get(id);};
 const ctx=vm.createContext({$,personalProjectionRevision:0,polling:false,timer:null,state:{status:'ready'},report:{as_of:'old'},reportVersion:'v1',reportNeedsRefresh:false,viewingHistory:false,request:async()=>{},render:()=>{},renderPublicRefresh:()=>{},applyConfig:()=>{},updateSchedule:()=>{},txt:(value,fallback='')=>typeof value==='string'?value:fallback,stamp:value=>value,renderAi:()=>{ctx.lastAiCost=ui.costPresentation(ctx.state.ai_cost,ctx.report?.ai_research||ctx.state.ai_research||{});},normalizeReport:r=>r,acceptReport:r=>{ctx.report=r;return true;},clearTimeout(){},setTimeout(){return 1;},setText:(id,text)=>$('#'+id).textContent=text});
 vm.runInContext(source.slice(source.indexOf('  function renderState(s)'),source.indexOf('  async function refresh()')),ctx);return ctx;
}
test('same-version report reloads after connection recovery and clears stale state',async()=>{
 const ctx=pollContext();ctx.request=async()=>{throw new Error('offline');};await ctx.poll();assert.equal(ctx.report.report_stale,true);assert.equal(ctx.reportNeedsRefresh,true);
 let calls=0;ctx.request=async path=>{calls++;return path.includes('status')?{has_report:true,report_version:'v1'}:{report:{as_of:'current',report_stale:false},report_version:'v1'};};await ctx.poll();assert.equal(calls,2);assert.equal(ctx.report.as_of,'current');assert.equal(ctx.reportNeedsRefresh,false);assert.equal(ctx.$('#reportNotice').hidden,true);
});
test('poll leaves selected history intact including a report response already in flight',async()=>{
 const ctx=pollContext();ctx.viewingHistory=true;let calls=0;ctx.request=async()=>{calls++;return {has_report:true,report_version:'v2'};};await ctx.poll();assert.equal(calls,1);assert.equal(ctx.report.as_of,'old');
 ctx.viewingHistory=false;let complete;ctx.request=async path=>path.includes('status')?{has_report:true,report_version:'v2'}:new Promise(resolve=>{complete=resolve;});const pending=ctx.poll();await new Promise(resolve=>setImmediate(resolve));ctx.viewingHistory=true;ctx.report={as_of:'history'};complete({report:{as_of:'latest'},report_version:'v2'});await pending;assert.equal(ctx.report.as_of,'history');
});

test('same-version status polls refresh the daily AI cost view without fetching the report',async()=>{
 const ctx=pollContext();let calls=0,requests=14;
 ctx.request=async path=>{calls++;assert.match(path,/\/status/);return {status:'ready',has_report:true,report_version:'v1',ai_cost:{requests,tokens_reserved:2000000}};};
 await ctx.poll();assert.equal(calls,1);assert.equal(ctx.report.as_of,'old');assert.equal(ctx.lastAiCost.requests,'14 次（计费 14.00 / 28）');
 requests=28;await ctx.poll();assert.equal(calls,2);assert.equal(ctx.lastAiCost.requests,'28 次（计费 28.00 / 28）');assert.equal(ctx.lastAiCost.status,'limited');
});
