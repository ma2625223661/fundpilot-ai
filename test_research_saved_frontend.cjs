'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),ui=require('./dist/sector-research.js');
const generated='2026-11-02T15:05:48Z',report={as_of:'2026-11-02T15:09:27+08:00'},sector={id:'chips',ai_research_status:'completed',ai_analysis:'已核验研究',ai_generated_at:generated};

test('saved research displays its original AI generation time separately from report data time',()=>{
  const normalized=ui.normalizeSector(sector),view=ui.researchSavedPresentation(normalized,report);
  assert.equal(view.saved,true);assert.equal(view.label,'已保存 · 更新时间：2026/11/02 23:05（北京时间）');assert.equal(view.generatedAt,generated);assert.equal(view.dataLabel,'报告数据时间：2026/11/02 15:09（北京时间）');assert.match(view.note,/AI 生成时间.*查看和刷新不会改变/);assert.equal(normalized.ai_generated_at,generated);
  const midnight=ui.researchSavedPresentation({...sector,ai_generated_at:'2026-11-02T16:01:00Z'},report);assert.match(midnight.label,/2026\/11\/03 00:01/);
});

test('reused results and refreshed report data never replace the saved generation timestamp',()=>{
  const original=ui.researchSavedPresentation(sector,report),reused=ui.researchSavedPresentation({...sector,ai_reused:true},{as_of:'2026-11-03T15:00:00+08:00',updated:'2030-01-01T00:00:00Z'});
  assert.equal(reused.label,original.label);assert.equal(reused.generatedAt,generated);assert.match(reused.note,/原生成时间.*复用、查看和刷新均不改变/);assert.match(reused.dataLabel,/2026\/11\/03 15:00/);
});

test('old reports explicitly lack a recorded update time and failed or empty research is never saved',()=>{
  for(const ai_generated_at of ['',undefined,'invalid','2026-11-02','2026-11-02T23:05:00']){const view=ui.researchSavedPresentation({...sector,ai_generated_at},report);assert.equal(view.label,'已保存 · 更新时间：未记录（旧版报告）');assert.equal(view.generatedAt,'');assert.doesNotMatch(view.label,/15:09/);}
  for(const change of [{ai_research_status:'failed'},{ai_research_status:'running'},{ai_research_status:''},{ai_analysis:''}]){const view=ui.researchSavedPresentation({...sector,...change},report);assert.equal(view.saved,false);assert.equal(view.label,'');assert.equal(view.generatedAt,'');}
});

test('watchcard saved metadata uses a semantic time element and does not mark missing results saved',()=>{
  const root={FundPilotCloud:{role:'member'},SectorResearch:ui},source=fs.readFileSync('dist/cloud-account.js','utf8').replace('  const identity = node','  window.renderSavedNote=savedResearchNote; return;\n  const identity = node');
  vm.runInNewContext(source,{window:root,document:{getElementById(){},createElement:tag=>({tag,children:[],append(...rows){this.children.push(...rows);}})}});
  const note=root.renderSavedNote(sector,report);assert.equal(note.className,'research-ai-save-meta');assert.equal(note.children[0].tag,'time');assert.equal(note.children[0].dateTime,generated);assert.equal(note.children[0].textContent,'已保存 · 更新时间：2026/11/02 23:05（北京时间）');assert.equal(note.children[2].className,'research-ai-data-time');assert.equal(root.renderSavedNote({...sector,ai_research_status:'failed'},report),null);
});

test('manual completion reloads server history and uses its order without writing or generating',async()=>{
  const source=fs.readFileSync('dist/sector-research.js','utf8'),start=source.indexOf('  async function refreshResearchHistory(){'),end=source.indexOf('\n  let toastTimer;',start),items=[{as_of:'new-saved',cloud_record:true},{as_of:'old',cloud_record:true}];
  let loads=0;const context=vm.createContext({cloudMode:true,historyRevision:0,historyLoaded:Promise.resolve(),historyStore:{load:async()=>{loads++;return {items};},save:()=>{throw Error('refresh must not write');}},historyItem:row=>row,histories:[{as_of:'local-stale'}],historyCleared:true,cloudHistoryReady:false,renderHistory(){},setText:(id,text)=>context.message=text,Set});
  vm.runInContext(source.slice(start,end),context);assert.equal(await context.refreshResearchHistory(),true);assert.equal(loads,1);assert.deepEqual(Array.from(context.histories,row=>row.as_of),['new-saved','old']);assert.equal(context.historyCleared,false);assert.equal(context.cloudHistoryReady,true);assert.match(context.message,/已自动保存.*后台更新/);
});

function historicalSector(){return ui.normalizeSector({...sector,status:'ok',score:65,score_model:'company_research_v2',score_status:'complete',score_breakdown:{fundamentals:{points:28},trend:{points:18},catalysts:{points:0}},evidence_ids:['company:report'],ai_advice:{schema_version:2,scope:'company',action:'track',reason:'生成时的经营与走势证据支持跟踪',watch_points:['生成时关注下一次财报'],evidence_chain:[{fact:'生成时已有财报披露',interpretation:'当时增长有经营数据支持',evidence_ids:['company:report']}],action_plan:[{trigger:'下一次财报披露',step:'核验增长能否延续',evidence_ids:['company:report']}],scenarios:[{condition:'经营增长转弱',response:'重新评估关注优先级',evidence_ids:['company:report']}],review_conditions:['经营数据发生重大变化']}});}

test('historical v2 advice keeps all saved details without promoting them to a current conclusion',()=>{
  const saved=historicalSector(),context={report_stale:true,ai_research:{status:'stale'}},view=ui.researchHistoricalAdvicePresentation(saved,context),current=ui.researchAdvicePresentation(saved,context);
  assert.equal(view.historical,true);assert.equal(view.label,'历史建议 · 仅供复盘');assert.match(view.notice,/生成时保存的历史建议.*不作为当前操作依据/);assert.equal(view.evidenceChain[0].fact,'生成时已有财报披露');assert.equal(view.actionPlan[0].step,'核验增长能否延续');assert.equal(view.scenarios[0].response,'重新评估关注优先级');assert.deepEqual(view.reviewConditions,['经营数据发生重大变化']);
  assert.equal(current.completed,false);assert.equal(current.detailed,false);assert.equal(current.action,'wait');assert.doesNotMatch(current.label,/重点跟踪/);assert.equal(ui.researchHistoricalAdvicePresentation(saved,{}),null);assert.equal(ui.researchHistoricalAdvicePresentation({...saved,ai_research_status:'failed'},context),null);
});

test('historical detail rendering exposes full saved sections behind an explicit review notice',()=>{
  const saved=historicalSector(),advice=ui.researchHistoricalAdvicePresentation(saved,{report_stale:true}),source=fs.readFileSync('dist/sector-research.js','utf8'),start=source.indexOf('  function renderDetailedAdvice('),end=source.indexOf('  function renderDetail()',start),node=(tag,text,cls)=>({tag,textContent:text||'',className:cls||'',children:[],setAttribute(){},append(...rows){this.children.push(...rows);}}),panel=node('section');
  const context=vm.createContext({el:node,report:{snapshot:{sources:[{id:'company:report',name:'公司财报'}]},company_evidence:{sources:[]}},txt:(value,fallback='')=>typeof value==='string'?value:fallback,arr:value=>Array.isArray(value)?value:[],link:label=>node('a',label),list:(title,items)=>{const box=node('section',title);items.forEach(text=>box.append(node('li',text)));return box;},Map});
  vm.runInContext(source.slice(start,end),context);context.renderDetailedAdvice(panel,saved,advice);const all=box=>[box,...box.children.flatMap(all)],nodes=all(panel),text=nodes.map(row=>row.textContent).join(' ');
  assert.match(text,/历史建议 · 仅供复盘.*不作为当前操作依据/);assert.match(text,/生成时已有财报披露/);assert.match(text,/核验增长能否延续/);assert.match(text,/经营增长转弱/);assert.match(text,/经营数据发生重大变化/);assert.equal(nodes.some(row=>row.className==='sector-history-notice'),true);assert.doesNotMatch(text,/按当前完整研究分|AI 研究建议：重点跟踪/);
});
