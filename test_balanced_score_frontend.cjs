const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const ui=require('./dist/sector-research.js');

function sample(changes={}){return {id:'x',title:'公司样本',status:'ok',score:65.25,score_scope:'company_composite',score_model:'company_research_v2',score_label:'板块研究分',score_status:'complete',score_maximum:100,score_coverage_pct:100,
 research_tier:{id:'optimistic',label:'乐观看待',reason:'全部门槛满足',conditions:{total_at_least_65:true,fundamentals_at_least_28:true,trend_at_least_18_or_positive_catalyst:true,evidence_complete:true}},
 score_breakdown:{fundamentals:{points:30,maximum:40,coverage_pct:100,scope:'真实公司财务',details:[{field:'tr_yoy',score:60,count:4,sample_count:4,coverage_pct:100,secret:'hidden'}]},trend:{points:20,maximum:30,coverage_pct:100},catalysts:{points:15.25,observed_adjustment:15.25,maximum:30,status:'assessed',source_ids:['official_cninfo']}},
 market_risk:{score:72,profile:'科技敏感',status:'complete',level:'高风险',coverage_pct:100,components:{market:70,liquidity:80,macro:50},weights:{market:.35,liquidity:.5,macro:.15},source_ids:['macro:nbs_pmi']},...changes};}

test('new score keeps two decimals, all three weights, signed catalysts and independent risk',()=>{
 const s=ui.normalizeSector(sample()),data=ui.sectorDataPresentation(s),panels=ui.researchPanels(s);
 assert.equal(data.scoreText,'65.25');assert.equal(data.scoreUnit,'研究 / 100');
 assert.equal(s.score,65.25);assert.equal(s.market_risk.score,72);
 assert.match(panels[4].lines.join(' '),/基本面 30.00\/40；走势 20.00\/30；事件催化 \+15.25/);
 assert.match(panels[4].lines.join(' '),/不截断/);assert.match(panels[3].lines.join(' '),/流动性风险 80.00/);
 assert.match(panels[1].lines.join(' '),/营收增长：中位映射 60.00\/100；有效 4\/4 家/);
 assert.ok(panels[3].source_ids.includes('macro:nbs_pmi'));assert.doesNotMatch(JSON.stringify(s),/hidden/);
});

test('unassessed events show stage over70 with pending tier and no neutral claim',()=>{
 const s=ui.normalizeSector(sample({score:60,score_status:'provisional',score_maximum:70,score_possible_range:[30,90],score_breakdown:{fundamentals:{points:35},trend:{points:25},catalysts:{points:null,observed_adjustment:null,status:'unassessed'}}}));
 assert.equal(s.research_tier.id,'pending');assert.equal(s.research_tier.label,'待完成评估');
 assert.equal(ui.sectorDataPresentation(s).scoreUnit,'基础 / 70');
 assert.match(ui.researchPanels(s)[4].lines.join(' '),/阶段分不进入完整档位/);
 assert.match(ui.researchPanels(s)[2].lines.join(' '),/催化调整：待评估/);
});

test('phase ranking does not compare incomplete stage70 as if a complete100 score',()=>{
 const partial=ui.normalizeSector(sample({id:'partial',score:70,score_status:'provisional',score_maximum:70}));
 const complete=ui.normalizeSector(sample({id:'complete',score:50}));
 const unknown=ui.normalizeSector({id:'unknown',status:'missing',score:null});
 assert.deepEqual(ui.sortSectors([partial,unknown,complete]).map(s=>s.id),['complete','partial','unknown']);
});

test('score colors follow the gated tier rather than ungated raw points',()=>{
 assert.deepEqual(ui.colorForScore(90,{id:'neutral'}),ui.colorForScore(60));
 assert.deepEqual(ui.colorForScore(65,{id:'optimistic'}),ui.colorForScore(85));
 assert.deepEqual(ui.colorForScore(70,{id:'pending'}),ui.colorForScore(null));
});

test('four colour intervals use exact 30, 50 and 65 boundaries',()=>{
 const bands=[[0,29.99],[30,49.99],[50,64.99],[65,100]].map(([lo,hi])=>{
   const a=ui.colorForScore(lo),b=ui.colorForScore(hi);assert.deepEqual(a,b);return a.color;
 });
 assert.equal(new Set(bands).size,4);
 assert.notEqual(ui.colorForScore(null).color,bands[0]);
 for(const score of [49.99,50,64.99,65]){
   const s=ui.normalizeSector(sample({score,score_status:'provisional',score_maximum:70}));
   assert.deepEqual(ui.colorForSector(s),ui.colorForScore(score));
   assert.equal(s.research_tier.id,'pending');assert.equal(s.score,score);
   assert.deepEqual(ui.colorForSector(s,true),ui.colorForScore(null));
 }
});

test('reference, bond and company scales rank in explicit groups instead of hiding company evidence',()=>{
 const base=ui.normalizeSector(sample({id:'base',score:49.08,score_status:'provisional',score_maximum:70}));
 const complete=ui.normalizeSector(sample({id:'complete',score:50}));
 const partial=ui.normalizeSector(sample({id:'partial',score:58,score_status:'provisional',score_maximum:100}));
 const reference=ui.normalizeSector({id:'ref',status:'ok',score:0,score_scope:'reference_trend'});
 const bond=ui.normalizeSector({id:'bond',status:'ok',score:90,quote:{asset_type:'bond'}});
 const missing=ui.normalizeSector({id:'missing',status:'missing'});
 assert.deepEqual(ui.sortSectors([reference,bond,base,complete,missing,partial]).map(s=>s.id),['complete','base','partial','ref','bond','missing']);
 assert.equal(ui.boardScoreGroup(reference).id,'reference');assert.equal(ui.boardScoreGroup(bond).id,'bond');
});

test('pending state names actual missing evidence and preserves signed partial catalysts',()=>{
 const s=ui.normalizeSector(sample({score_status:'provisional',score_breakdown:{fundamentals:{points:30,coverage_pct:100},trend:{points:15,coverage_pct:100},catalysts:{points:null,observed_adjustment:-12,status:'partially_assessed'}}}));
 const view=ui.companyScoreView(s);assert.equal(view.label,'事件部分评估');assert.equal(view.catalyst,'事件 -12.00（部分）');assert.equal(view.catalystTone,'negative');assert.match(view.gates,/基本面达28分 · 走势未达18分/);
 const pending=ui.companyScoreView(ui.normalizeSector(sample({score_status:'provisional',score_breakdown:{fundamentals:{points:30,coverage_pct:75},trend:{points:null},catalysts:{points:null}}})));
 assert.equal(pending.label,'财务待补齐 · 走势待补齐 · 事件待评估');
 const notice=ui.boardResearchNotice({event_analysis:{status:'scheduled'},ai_research:{next_run_at:'2026-11-02T09:25:00+08:00'}});
 assert.match(notice,/2026-11-02 09:25/);assert.match(notice,/70分制不放大/);assert.match(notice,/未评估事件不按0分/);
 assert.doesNotMatch(ui.boardResearchNotice({event_analysis:{status:'not_configured'}}),/下次/);
});

test('actual detail render exposes gates, negative catalyst color and risk independently',()=>{
 const source=fs.readFileSync('./dist/sector-research.js','utf8'),nodes=new Map();
 class Node{constructor(text=''){this.textContent=text||'';this.children=[];this.className='';}append(...items){this.children.push(...items);}replaceChildren(){this.children=[];}setAttribute(){}get childNodes(){return this.children;}}
 const $=id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);};
 const report=ui.normalizeReport({research_scope:'sectors',sector_analysis:[sample({score:45,score_status:'provisional',score_possible_range:[20,65],score_breakdown:{fundamentals:{points:35},trend:{points:25},catalysts:{points:null,observed_adjustment:-15,status:'partially_assessed'}}})],snapshot:{sources:[]},event_analysis:{events:[]}});
 const context=vm.createContext({$,report,selected:'x',scarcityUI:require('./dist/sector-scarcity.js'),sectorDataPresentation:ui.sectorDataPresentation,sourceStatusLabel:ui.sourceStatusLabel,researchPanels:ui.researchPanels,finite:Number.isFinite,txt:(s,d='')=>typeof s==='string'?s:d,el:(tag,text,c)=>{const n=new Node(text);n.className=c||'';return n;},applyTone:()=>{},groups:{other:'其他'},stamp:s=>s||'*****',num:(n,d=2)=>Number.isFinite(n)?n.toFixed(d):'*****',pct:ui.pct,UNKNOWN:'*****',sectorIndicator:ui.sectorIndicator,indicatorNode:()=>new Node('signal'),document:{createTextNode:s=>new Node(s)},list:s=>new Node(s),renderCompanyEvidence:()=>{},link:s=>new Node(s)});
 const from=source.indexOf('  function renderIndependentIndex('),to=source.indexOf('  function renderBoards()',from);
 vm.runInContext(source.slice(from,to),context);context.renderDetail();
 const visit=n=>[n,...n.children.flatMap(visit)],all=visit($('#sectorDetail')),text=all.map(n=>n.textContent).join(' ');
 assert.match(text,/基本面≥28\/40/);assert.match(text,/阶段研究分/);assert.match(text,/环境风险独立评分：72\/100/);
 assert.ok(all.some(n=>n.className==='catalyst-negative'&&n.textContent==='-15.00'));
 assert.doesNotMatch(text,/最高 59 分|大盘风险上限/);
});
