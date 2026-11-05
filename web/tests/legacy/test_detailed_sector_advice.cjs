const {test}=require('node:test');
const assert=require('node:assert/strict');
const ui=require('../../src/lib/legacy/sector-research.js');

function sample(changes={}){
  const ref='history:chips';
  return {id:'chips',status:'ok',score:60,ai_reason:'支持与反对证据均需核验。',ai_research_status:'completed',evidence_ids:[ref],
    ai_advice:{schema_version:2,scope:'reference',action:'reference',reason:'观察该参考指标。',watch_points:['下一交易日核验走势。'],
      evidence_chain:[{fact:'样本近20日收益3.4%。',interpretation:'仅支持观察参考走势。',evidence_ids:[ref]}],
      action_plan:[{trigger:'下一交易日数据更新。',step:'复核20日走势及样本覆盖。',evidence_ids:[ref]}],
      scenarios:[{condition:'走势转弱。',response:'降低关注并核验是否持续。',evidence_ids:[ref]}],
      review_conditions:['来源失效时暂停原判断。'],provider_secret:'must drop'},...changes};
}

test('detailed advice survives normalization as source-bound research sections',()=>{
  const sector=ui.normalizeSector(sample()),view=ui.researchAdvicePresentation(sector);
  assert.equal(sector.ai_advice.schema_version,2);assert.equal(view.detailed,true);
  assert.equal(view.scope,'reference');assert.equal(view.evidenceChain[0].fact,'样本近20日收益3.4%。');
  assert.equal(view.actionPlan[0].step,'复核20日走势及样本覆盖。');
  assert.equal(view.scenarios[0].response,'降低关注并核验是否持续。');
  assert.deepEqual(view.reviewConditions,['来源失效时暂停原判断。']);
  assert.doesNotMatch(JSON.stringify(sector),/must drop/);assert.equal(sector.score,60);
});

test('incomplete or wrongly cited detailed advice cannot expose partial sections',()=>{
  for(const change of ['source','missing','scope']){
    const value=sample();
    if(change==='source')value.ai_advice.scenarios[0].evidence_ids=['another-sector'];
    if(change==='missing')delete value.ai_advice.review_conditions;
    if(change==='scope')value.ai_advice.scope='company';
    const sector=ui.normalizeSector(value),view=ui.researchAdvicePresentation(sector);
    assert.equal(view.detailed,false);assert.deepEqual(view.evidenceChain,[]);
    assert.deepEqual(sector.ai_advice.action_plan,[]);
  }
});

test('legacy advice remains readable while stale or conflicting actions hide detailed plans',()=>{
  const legacy=ui.normalizeSector(sample({ai_advice:{action:'reference',reason:'旧版观察结论。',watch_points:['继续核验走势。']}}));
  assert.equal(ui.researchAdvicePresentation(legacy).summary,'旧版观察结论。');
  assert.equal(ui.researchAdvicePresentation(legacy).detailed,false);
  const sector=ui.normalizeSector(sample());
  for(const context of [{report_stale:true},{ai_research:{status:'stale'}}]){
    const view=ui.researchAdvicePresentation(sector,context);assert.equal(view.detailed,false);assert.deepEqual(view.actionPlan,[]);
  }
  const changed=sample();changed.ai_advice.action='track';
  assert.equal(ui.researchAdvicePresentation(ui.normalizeSector(changed)).detailed,false);
});

test('company partial research keeps its 70-point denominator and wait action',()=>{
  const value=sample({score_model:'company_research_v2',score_status:'provisional',score_maximum:70});
  value.ai_advice.action='wait';value.ai_advice.scope='company';
  const sector=ui.normalizeSector(value),view=ui.researchAdvicePresentation(sector);
  assert.equal(sector.score_maximum,70);assert.equal(view.action,'wait');assert.equal(view.scope,'company');
  assert.equal(view.detailed,true);assert.match(view.label,/等待证据/);
});

test('detailed renderer shows named sources and literal text without raw source ids',()=>{
  const fs=require('node:fs'),vm=require('node:vm'),source=fs.readFileSync('./dist/sector-research.js','utf8');
  class Element{constructor(text=''){this.textContent=text;this.children=[];}append(...items){this.children.push(...items);}setAttribute(){}}
  const raw=sample();raw.ai_advice.action_plan[0].step='<img src=x onerror=alert(1)> 作为待分析原文';
  const report=ui.normalizeReport({research_scope:'sectors',sector_analysis:[raw],snapshot:{sources:[{id:'history:chips',name:'行业历史行情',url:'https://example.com/evidence',status:'ok'}]}});
  const sector=report.sector_analysis[0],view=ui.researchAdvicePresentation(sector),panel=new Element();
  const context=vm.createContext({report,arr:v=>Array.isArray(v)?v:[],txt:(v,f='')=>typeof v==='string'?v:f,
    el:(tag,text)=>new Element(text),link:(name,url)=>{const el=new Element(name);el.href=url;return el;},
    list:(title,rows)=>{const el=new Element(title);rows.forEach(text=>el.append(new Element(text)));return el;}});
  const start=source.indexOf('  function renderDetailedAdvice('),end=source.indexOf('  function renderDetail()',start);
  vm.runInContext(source.slice(start,end),context);context.renderDetailedAdvice(panel,sector,view);
  const text=node=>[node.textContent,...node.children.map(text)].join(' '),rendered=text(panel);
  assert.match(rendered,/事实与解释/);assert.match(rendered,/下一步怎么核验/);assert.match(rendered,/不同情况如何调整关注/);
  assert.match(rendered,/行业历史行情/);assert.doesNotMatch(rendered,/history:chips/);
  assert.match(rendered,/<img src=x onerror=alert\(1\)>/);
});
