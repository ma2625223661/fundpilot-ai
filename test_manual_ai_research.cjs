'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const flush=()=>new Promise(resolve=>setImmediate(resolve));

function setup({effort='medium',balance=4,jobs=[],config={}}={}){
  const nodes=new Map(),calls=[],timers=new Map(),events={};let timerId=0;
  class Element{
    constructor(tag){this.tag=tag;this.children=[];this.attributes={};this.dataset={};this.disabled=false;this.textContent='';}
    set id(value){this._id=value;nodes.set(value,this);}get id(){return this._id;}
    get firstChild(){return this.children[0];}get lastChild(){return this.children.at(-1);}
    detach(){if(this.parentElement){const rows=this.parentElement.children;rows.splice(rows.indexOf(this),1);this.parentElement=null;}}
    append(...items){for(const item of items){item.detach();item.parentElement=this;this.children.push(item);}}
    replaceChildren(...items){for(const item of this.children)item.parentElement=null;this.children=[];this.append(...items);}
    after(...items){if(!this.parentElement)return;let index=this.parentElement.children.indexOf(this)+1;for(const item of items){item.detach();item.parentElement=this.parentElement;this.parentElement.children.splice(index++,0,item);}}
    setAttribute(key,value){this.attributes[key]=value;}addEventListener(){}
  }
  const dash=new Element('section');dash.id='dash';const watch=new Element('section');watch.id='cloudWatchlist';dash.append(watch);
  const state={effort,balance,jobs,config:{configured:true,verification:'verified',enabled:true,effective_enabled:true,reasoning_effort:'xhigh',...config},polls:[],postCount:0,historyReads:0,opens:[],sector:{id:'chips',title:'芯片',status:'ok',ai_research_status:'',ai_access:{status:'not_ready',preferred_reasoning_effort:effort}}};
  const report={as_of:'2026-11-02T15:09:27+08:00',report_stale:false};
  const summary=()=>({status:state.balance>0?'active':'exhausted',credits_remaining:state.balance,preferred_reasoning_effort:state.effort,unlocked_count:0,can_unlock:state.balance>0});
  const root={FundPilotCloud:{role:'member',id:'user-a'},SectorWorkspace:{getAiRuntime:()=>({config:state.config,subscription:summary()}),applyUnlockedSector:(sector,id)=>{assert.equal(id,report.as_of);state.sector=sector;return true;},refreshPersonalReport:async()=>{},refreshResearchHistory:async()=>{state.historyReads++;},openSector:id=>state.opens.push(id),openSubscription:()=>{}}};
  const context=vm.createContext({window:root,document:{hidden:false,createElement:tag=>new Element(tag),getElementById:id=>nodes.get(id),addEventListener:(name,fn)=>events[name]=fn,dispatchEvent:()=>{}},CustomEvent:class{constructor(type){this.type=type;}},AbortSignal,Date,Set,Map,console,
    setTimeout:(fn,delay)=>{const id=++timerId;timers.set(id,{fn,delay});return id;},clearTimeout:id=>timers.delete(id),
    fetch:async(path,options)=>{
      calls.push({path,options});
      if(path==='/api/me/ai-subscription')return {ok:true,json:async()=>({subscription:summary(),items:[]})};
      if(path==='/api/me/ai-research'&&options?.method!=='POST')return {ok:true,json:async()=>({jobs:state.jobs})};
      if(path==='/api/me/ai-research'){
        state.postCount++;const body=JSON.parse(options.body);state.effort=body.reasoning_effort;
        return {ok:true,status:202,json:async()=>({job_id:'job-'+state.postCount,status:'running',phase:'connecting',...body,charged:false})};
      }
      if(path.startsWith('/api/me/ai-research?')){
        const next=state.polls.shift();if(next instanceof Error)throw next;
        return {ok:true,json:async()=>next};
      }
      if(path==='/api/me/ai-preference'){state.effort=JSON.parse(options.body).reasoning_effort;return {ok:true,json:async()=>({subscription:summary()})};}
      throw new Error('Unexpected endpoint: '+path);
    }
  });
  vm.runInContext(fs.readFileSync('dist/ai-subscription.js','utf8'),context);root.FundPilotSubscriptions.mountProfile();
  const all=n=>[n,...n.children.flatMap(all)],text=n=>[n.textContent,...n.children.map(text)].join(' '),control=()=>root.FundPilotSubscriptions.researchControl(state.sector,report),button=n=>all(n).find(row=>row.className==='btn primary cloud-watch-generate');
  async function poll(){const [id,timer]=timers.entries().next().value;timers.delete(id);assert.equal(timer.delay,1500);await timer.fn();await flush();}
  function completed({charged=true,reused=false,cost=effort==='xhigh'?1.5:1}={}){
    if(charged)state.balance-=cost;
    return {status:'completed',saved:true,report_id:report.as_of,sector:{...state.sector,ai_research_status:'completed',ai_analysis:'已核验的研究理由',ai_generated_at:'2026-11-02T18:06:22+08:00',ai_reasoning_effort:state.effort,evidence_ids:['history:chips'],ai_advice:{schema_version:2,scope:'reference',action:'reference',reason:'核验参考走势',watch_points:['关注新行情'],evidence_chain:[{fact:'近期行情已提供',interpretation:'仅支持参考观察',evidence_ids:['history:chips']}],action_plan:[{trigger:'新行情更新',step:'重新核验走势',evidence_ids:['history:chips']}],scenarios:[{condition:'走势转弱',response:'下调关注优先级',evidence_ids:['history:chips']}],review_conditions:['数据更新后复核']},ai_access:{status:'unlocked',reasoning_effort:state.effort,preferred_reasoning_effort:state.effort}},subscription:summary(),charged,charged_cost:charged?cost:0,reused};
  }
  return {root,state,report,calls,timers,control,button,text,poll,completed,all};
}

test('watching and loading only read state; explicit generation sends the disclosed level once',async()=>{
  const h=setup();await flush();
  assert.equal(h.calls.some(call=>call.options?.method==='POST'),false);
  const card=h.control(),button=h.button(card);assert.match(h.text(card),/中度推理 1 点/);assert.match(button.textContent,/生成 AI 研究.*中度推理 1 点/);
  await button.onclick();await button.onclick();
  assert.equal(h.state.postCount,1);assert.equal(h.button(h.control()).disabled,true);
  assert.deepEqual(JSON.parse(h.calls.find(call=>call.options?.method==='POST').options.body),{sector_id:'chips',report_id:h.report.as_of,reasoning_effort:'medium'});
  h.state.polls.push(h.completed());await h.poll();
  assert.match(h.text(h.control()),/本次扣除 1 点/);assert.equal(h.button(h.control()).disabled,false);
  assert.deepEqual(h.state.opens,['chips']);
  await h.button(h.control()).onclick();assert.deepEqual(h.state.opens,['chips','chips']);assert.equal(h.state.postCount,1);
});

test('xhigh discloses 1.5 points and a failed generation can be retried without a false charge',async()=>{
  const h=setup({effort:'xhigh'});await flush();assert.match(h.button(h.control()).textContent,/极高推理 1\.5 点/);
  await h.button(h.control()).onclick();h.state.polls.push({status:'failed',error:'公司证据不足',charged:false,charged_cost:0});await h.poll();
  assert.match(h.text(h.control()),/公司证据不足.*本次未扣点.*可重试/);assert.equal(h.state.balance,4);
  await h.button(h.control()).onclick();assert.equal(h.state.postCount,2);
  h.state.polls.push(h.completed({reused:true,cost:1.5}));await h.poll();assert.match(h.text(h.control()),/复用有效研究.*本次扣除 1\.5 点/);
});

test('uncertain polling retries query instead of submitting another AI request',async()=>{
  const h=setup();await flush();await h.button(h.control()).onclick();h.state.polls.push(new Error('network disconnected'));await h.poll();
  assert.equal(h.button(h.control()).textContent,'查询研究进度');assert.equal(h.button(h.control()).disabled,false);
  h.state.polls.push(h.completed({charged:false,reused:true}));await h.button(h.control()).onclick();
  assert.equal(h.state.postCount,1);assert.match(h.text(h.control()),/本次未扣点/);
});

test('reload resumes only this account running job through GET and blocks historical or unaffordable generation',async()=>{
  const h=setup({effort:'xhigh',balance:1,jobs:[{job_id:'existing-job',sector_id:'chips',report_id:'2026-11-02T15:09:27+08:00',reasoning_effort:'xhigh',status:'running'}]});await flush();
  assert.equal(h.state.postCount,0);assert.equal(h.button(h.control()).disabled,true);
  h.state.polls.push({status:'failed',error:'研究未完成',charged:false});await h.poll();
  assert.equal(h.button(h.control()).disabled,true);
  h.report.report_stale=true;assert.equal(h.button(h.control()).textContent,'历史报告仅供复盘');assert.equal(h.button(h.control()).disabled,true);
});

test('selected and generated efforts survive presentation without inventing unsupported levels',()=>{
  const ui=require('./dist/sector-research.js'),{manualResearchChoice}=require('./dist/ai-subscription.js');
  assert.equal(ui.normalizeSector({id:'chips',ai_reasoning_effort:'xhigh'}).ai_reasoning_effort,'xhigh');
  assert.equal(ui.normalizeSector({id:'chips',ai_reasoning_effort:'high'}).ai_reasoning_effort,null);
  assert.equal(manualResearchChoice({}, {}, {config:{reasoning_effort:'xhigh'}}).effort,'xhigh');
  assert.equal(manualResearchChoice({}, {preferred_reasoning_effort:'medium'}, {config:{reasoning_effort:'xhigh'}}).cost,1);
});

test('unconfigured or explicitly disabled AI blocks new generation with an actionable explanation',async()=>{
  for(const [config,reason] of [[{configured:false},/尚未配置/],[{enabled:false},/当前未启用/]]){
    const h=setup({config});await flush();const control=h.control();
    assert.equal(h.button(control).textContent,'AI 连接未就绪');assert.equal(h.button(control).disabled,true);assert.match(h.text(control),reason);assert.match(h.text(control),/不会发起新研究或扣点/);assert.equal(h.state.postCount,0);
  }
  const h=setup();await flush();h.state.config=null;const control=h.control();assert.equal(h.button(control).disabled,true);assert.match(h.text(control),/连接状态尚未确认/);assert.equal(h.state.postCount,0);
});

test('enabled configured service can connect after failed or missing verification and opens its completed report',async()=>{
  for(const config of [{verification:'unverified'},{verification:'failed',effective_enabled:false},{effective_enabled:false}]){
    const h=setup({effort:'xhigh',config});await flush();const button=h.button(h.control());
    assert.equal(button.disabled,false);assert.match(button.textContent,/连接并生成研究.*极高推理 1\.5 点/);assert.match(h.text(h.control()),/先连接并核验.*连接或研究失败不扣点/);
    await button.onclick();await button.onclick();assert.equal(h.state.postCount,1);assert.equal(h.button(h.control()).textContent,'正在连接 AI…');assert.match(h.text(h.control()),/连接成功后开始研究/);assert.equal(h.state.balance,4);
    h.state.polls.push({status:'running',phase:'researching'});await h.poll();assert.equal(h.button(h.control()).textContent,'正在生成 AI 研究…');assert.equal(h.button(h.control()).disabled,true);assert.equal(h.state.balance,4);
    h.state.polls.push(h.completed({cost:1.5}));await h.poll();assert.deepEqual(h.state.opens,['chips']);assert.equal(h.state.postCount,1);assert.equal(h.state.balance,2.5);assert.match(h.text(h.control()),/本次扣除 1\.5 点/);
  }
});

test('failed connection is not charged and can be retried with the same disclosed point cost',async()=>{
  const h=setup({config:{verification:'failed',effective_enabled:false}});await flush();await h.button(h.control()).onclick();
  h.state.polls.push({status:'failed',error:'服务暂时无法连接',charged:false,charged_cost:0});await h.poll();
  assert.match(h.text(h.control()),/服务暂时无法连接.*本次未扣点/);assert.match(h.button(h.control()).textContent,/连接并生成研究.*中度推理 1 点/);assert.equal(h.state.balance,4);assert.deepEqual(h.state.opens,[]);
  await h.button(h.control()).onclick();assert.equal(h.state.postCount,2);
});

test('restored research resumes progress without unexpectedly opening a report on completion',async()=>{
  const h=setup({jobs:[{job_id:'restored-job',sector_id:'chips',report_id:'2026-11-02T15:09:27+08:00',reasoning_effort:'medium',status:'running',phase:'researching'}]});await flush();
  assert.match(h.button(h.control()).textContent,/正在生成/);h.state.polls.push(h.completed());await h.poll();
  assert.deepEqual(h.state.opens,[]);assert.equal(h.state.postCount,0);assert.match(h.button(h.control()).textContent,/查看 AI 研究/);
});

test('connection changes preserve access to completed results and running-job status queries',async()=>{
  const h=setup();await flush();await h.button(h.control()).onclick();h.state.config.verification='failed';h.state.config.effective_enabled=false;
  assert.match(h.button(h.control()).textContent,/正在连接/);h.state.polls.push(new Error('status connection failed'));await h.poll();
  assert.equal(h.button(h.control()).textContent,'查询研究进度');assert.equal(h.button(h.control()).disabled,false);
  h.state.polls.push(h.completed({charged:false,reused:true}));await h.button(h.control()).onclick();
  assert.match(h.button(h.control()).textContent,/查看 AI 研究/);assert.equal(h.button(h.control()).disabled,false);
  assert.deepEqual(h.state.opens,['chips']);await h.button(h.control()).onclick();assert.deepEqual(h.state.opens,['chips','chips']);assert.equal(h.state.postCount,1);
});

test('a completed task invalidated by newer evidence preserves its charge fact without applying stale content',async()=>{
  const h=setup();await flush();await h.button(h.control()).onclick();
  h.state.polls.push({status:'completed',stale:true,applicable:false,stale_reason:'报告已更新',charged:true,charged_cost:1,subscription:{status:'active',credits_remaining:3,preferred_reasoning_effort:'medium'}});
  await h.poll();assert.equal(h.state.sector.ai_research_status,'');assert.match(h.text(h.control()),/报告已更新.*已扣除 1 点/);assert.doesNotMatch(h.text(h.control()),/该次未扣点/);assert.deepEqual(h.state.opens,[]);
  assert.equal(h.button(h.control()).disabled,false);assert.match(h.button(h.control()).textContent,/生成 AI 研究/);
});

test('an unlocked legacy summary remains viewable and offers explicitly priced detailed generation',async()=>{
  for(const effort of ['medium','xhigh']){
    const h=setup({effort});await flush();h.state.sector=h.completed({charged:false}).sector;h.state.sector.ai_advice={action:'reference',reason:'已有简版研究',watch_points:['核验下一期数据']};
    const card=h.control(),button=h.button(card),previous=h.all(card).find(row=>row.className==='cloud-watch-ai-action cloud-watch-previous-research'),cost=effort==='xhigh'?1.5:1;
    assert.match(button.textContent,new RegExp('生成详细 AI 建议.*'+cost+' 点'));assert.equal(button.disabled,false);assert.match(h.text(card),/已有研究可继续查看.*新的详细建议成功后.*失败不扣点/);assert.doesNotMatch(h.text(card),/失效|过期/);
    assert.ok(previous);await previous.onclick();assert.equal(h.state.postCount,0);assert.deepEqual(h.state.opens,['chips']);
    await button.onclick();await button.onclick();assert.equal(h.state.postCount,1);h.state.polls.push(h.completed({cost}));await h.poll();
    assert.match(h.button(h.control()).textContent,/查看 AI 研究 · 不重复扣点/);assert.equal(h.state.balance,4-cost);assert.equal(h.all(h.control()).some(row=>row.className==='cloud-watch-ai-action cloud-watch-previous-research'),false);
  }
});

test('incomplete v2 details cannot hide the new-generation action behind free viewing',async()=>{
  const {hasDetailedResearch}=require('./dist/ai-subscription.js');
  const h=setup();await flush();h.state.sector=h.completed({charged:false}).sector;assert.equal(hasDetailedResearch(h.state.sector),true);
  for(const change of [advice=>advice.action_plan=[],advice=>advice.scenarios[0].evidence_ids=['unrelated'],advice=>advice.evidence_chain[0].interpretation='',advice=>advice.review_conditions=[]]){
    h.state.sector=h.completed({charged:false}).sector;change(h.state.sector.ai_advice);assert.equal(hasDetailedResearch(h.state.sector),false);assert.match(h.button(h.control()).textContent,/生成详细 AI 建议.*1 点/);
  }
});

test('legacy viewing remains free when subscription points cannot fund a detailed generation',async()=>{
  const h=setup({balance:0});await flush();h.state.sector=h.completed({charged:false}).sector;h.state.sector.ai_advice=null;
  const card=h.control();assert.equal(h.button(card).disabled,true);const previous=h.all(card).find(row=>row.className==='cloud-watch-ai-action cloud-watch-previous-research');assert.ok(previous);await previous.onclick();assert.deepEqual(h.state.opens,['chips']);assert.equal(h.state.postCount,0);
});

test('xhigh progress explains the possible wait and reload recovery without invented progress',async()=>{
  const h=setup({effort:'xhigh'});await flush();await h.button(h.control()).onclick();h.state.polls.push({status:'running',phase:'researching'});await h.poll();
  const message=h.text(h.control());assert.match(message,/极高推理可能需要数分钟.*保持页面或稍后回来查询.*刷新后可恢复任务/);assert.doesNotMatch(message,/%|自动打开/);assert.equal(h.state.postCount,1);assert.equal(h.button(h.control()).disabled,true);
});

test('a daily budget failure explains recovery without duplicate punctuation or suggesting immediate retry',async()=>{
  const h=setup({effort:'xhigh'});await flush();await h.button(h.control()).onclick();h.state.polls.push({status:'failed',error:'今日 AI Token 预算余量不足，已触发预算保护。。',charged:false,charged_cost:0});await h.poll();
  const message=h.all(h.control()).find(row=>row.className==='cloud-status cloud-watch-generation-status').textContent;
  assert.equal(message,'今日 API 预算不足，请等待预算恢复或联系管理员调整；本次未扣点。');assert.doesNotMatch(message,/。。|可重试/);assert.equal(h.state.postCount,1);assert.equal(h.state.balance,4);assert.equal(h.timers.size,0);assert.equal(h.button(h.control()).disabled,false);
});

test('successful generation confirms automatic saving and refreshes server history without another generation',async()=>{
  const h=setup();await flush();assert.match(h.text(h.control()),/生成成功后自动保存至研究记录.*刷新后可恢复任务/);assert.doesNotMatch(h.text(h.control()),/已保存/);
  await h.button(h.control()).onclick();assert.match(h.text(h.control()),/生成成功后自动保存至研究记录/);assert.equal(h.state.historyReads,0);
  h.state.polls.push(h.completed());await h.poll();assert.match(h.text(h.control()),/已自动保存至研究记录/);assert.equal(h.state.historyReads,1);assert.equal(h.state.postCount,1);assert.equal(h.state.sector.ai_generated_at,'2026-11-02T18:06:22+08:00');
  await h.button(h.control()).onclick();assert.equal(h.state.historyReads,1);assert.equal(h.state.postCount,1);assert.equal(h.state.sector.ai_generated_at,'2026-11-02T18:06:22+08:00');
});

test('failed generation never confirms saving or refreshes history',async()=>{
  const h=setup();await flush();await h.button(h.control()).onclick();h.state.polls.push({status:'failed',error:'服务暂不可用。',charged:false});await h.poll();assert.doesNotMatch(h.text(h.control()),/已保存|已自动保存/);assert.equal(h.state.historyReads,0);assert.equal(h.state.postCount,1);
});

test('daily request protection and evidence cooldown explain when to wait without automatic retries',async()=>{
  for(const [error,expected] of [
    ['今日 AI 请求数已达到保护上限，已停止新增调用，明日北京时间零点重新计数。','今日 AI 请求数已达到保护上限，请等待北京时间次日 00:00 额度恢复，或联系管理员调整；本次未扣点。'],
    ['相同证据近期已发送；为避免超时或无效响应重复计费，30分钟内暂缓重发。','相同证据近期已发送，为避免重复调用，请等待上次发送满 30 分钟后再生成；本次未扣点。']
  ]){
    const h=setup();await flush();await h.button(h.control()).onclick();h.state.polls.push({status:'failed',error,charged:false});await h.poll();const message=h.all(h.control()).find(row=>row.className==='cloud-status cloud-watch-generation-status').textContent;
    assert.equal(message,expected);assert.doesNotMatch(message,/可重试|。。/);assert.equal(h.state.postCount,1);assert.equal(h.timers.size,0);assert.equal(h.state.balance,4);assert.equal(h.state.historyReads,0);
  }
});
