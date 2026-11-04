'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {test} = require('node:test');
const source = fs.readFileSync(require.resolve('./dist/app.js'),'utf8');
class Node {
  constructor(value=''){this.value=value;this.hidden=false;this.textContent='';this.listeners=[];this.dataset={};this.options=[{value:'deepseek-flash'}];this.validationMessage='';this.validityReports=0;}
  addEventListener(type,fn){this.listeners.push([type,fn]);}
  append(option){this.options.push(option);}
  setCustomValidity(message){this.validationMessage=message;}
  reportValidity(){
    this.validityReports++;
    const prefix=this.selector==='#apiForm'?'api':this.selector==='#aiScheduleForm'?'ai':null;
    return prefix?[...nodes].filter(([id])=>new RegExp('^#'+prefix+'Schedule(Interval|Time|EndTime)$').test(id))
      .every(([,node])=>node.disabled || !node.validationMessage):!this.validationMessage;
  }
  click(){this.onclick?.();}
}
const nodes = new Map();
const $ = selector => {if(!nodes.has(selector)){const node=new Node();node.selector=selector;nodes.set(selector,node);}return nodes.get(selector);};
const context = vm.createContext({$:value=>$(value),stamp:value=>String(value),aiConfig:null,latestAutoState:null,
  aiConfigBusy:false,aiConfigError:'', string:(v,f='')=>typeof v==='string'?v:f,readable:v=>String(v),
  el:(_,text)=>new Node(text)});
const start = source.indexOf('function aiVerification');
const end = source.indexOf('function aiMetadata');
vm.runInContext(source.slice(source.indexOf('const AI_SCHEDULE_DEFAULTS'),source.indexOf('let history')) + source.slice(start,end),context);
vm.runInContext(source.slice(source.indexOf('function renderAiConfig'),source.indexOf('async function loadAiConfig')),context);

test('schedule accepts arbitrary minute intervals and only fills genuinely missing fields',()=>{
  assert.deepEqual({...context.normalizeAiSchedule({mode:'scheduled_interval',interval_minutes:'45',daily_time:'08:05',end_time:'16:00'})},
    {mode:'scheduled_interval',interval_minutes:45,daily_time:'08:05',end_time:'16:00',timezone:'Asia/Shanghai'});
  for(const value of ['',1.5,0,1441]) assert.equal(context.normalizeAiSchedule({interval_minutes:value}).interval_minutes,value);
  assert.deepEqual({...context.normalizeAiSchedule({mode:'wrong'})},
    {mode:'interval',interval_minutes:30,daily_time:'15:30',end_time:null,timezone:'Asia/Shanghai'});
  assert.equal(context.normalizeAiSchedule({daily_time:''}).daily_time,'');
});
test('schedule visibility matches mode semantics',()=>{
  context.updateScheduleFields('ai',{mode:'interval',interval_minutes:60,daily_time:'15:30'});
  assert.equal($('#aiScheduleIntervalField').hidden,false);assert.equal($('#aiScheduleTimeField').hidden,true);
  assert.equal($('#aiScheduleEndTimeField').hidden,true);assert.equal($('#aiScheduleEndTime').disabled,true);
  assert.match($('#aiScheduleHint').textContent,/间隔自动研究/);
  context.updateScheduleFields('ai',{mode:'daily',interval_minutes:60,daily_time:'08:00'});
  assert.equal($('#aiScheduleIntervalField').hidden,true);assert.equal($('#aiScheduleTimeField').hidden,false);
  assert.equal($('#aiScheduleEndTimeField').hidden,false);
  assert.match($('#aiScheduleHint').textContent,/启动时间研究一次/);
  assert.match($('#aiScheduleEndStatus').textContent,/尚未设置停止时间/);
  context.updateScheduleFields('ai',{mode:'scheduled_interval',interval_minutes:15,daily_time:'07:30'});
  assert.equal($('#aiScheduleIntervalField').hidden,false);assert.equal($('#aiScheduleTimeField').hidden,false);
  assert.match($('#aiScheduleHint').textContent,/当前未设停止时间，仍按启动后持续循环/);
  context.updateScheduleFields('ai',{mode:'scheduled_interval',interval_minutes:45,daily_time:'22:00',end_time:'02:30'});
  assert.match($('#aiScheduleHint').textContent,/每天.*跨午夜.*到点停止新增 AI 请求.*当前请求返回/);
  assert.match($('#aiScheduleEndStatus').textContent,/跨午夜/);
});
test('next AI run is rendered from backend schedule timestamp',()=>{
  context.latestAutoState={ai_next_run_at:'2026-10-31T07:30:00+08:00'};
  context.updateScheduleFields('ai',{mode:'daily'});
  assert.match($('#aiScheduleNext').textContent,/2026-10-31T07:30:00\+08:00/);
  assert.match(context.nextAiScheduleText('2026-10-31T07:30:00+08:00'),/北京时间/);
});
test('HTML and save requests expose schedule without changing enabled semantics',()=>{
  const html=fs.readFileSync('dist/index.html','utf8');
  for(const prefix of ['ai']) {
    assert.match(html,new RegExp(prefix+'ScheduleMode'));
    assert.match(html,new RegExp(prefix+'ScheduleInterval'));
    assert.match(html,new RegExp(prefix+'ScheduleTime'));
    assert.match(html,new RegExp('<input id="'+prefix+'ScheduleInterval" type="number" min="1" max="1440" step="1"'));
    assert.doesNotMatch(html,new RegExp('<select id="'+prefix+'ScheduleInterval"'));
    assert.match(html,new RegExp('id="'+prefix+'ScheduleEndTime" type="time"'));
    assert.doesNotMatch(html,new RegExp('id="'+prefix+'ScheduleEndTime"[^>]*value='));
  }
  assert.match(source,/enabled: \$\('#autoAiEnabled'\)\.checked/);
  assert.match(source,/status === 'scheduled'/);
});
test('polling and busy renders preserve each form draft while refreshing actual next-run text',()=>{
  const config={configured:true,enabled:true,effective_enabled:true,verification:'verified',model:'deepseek-flash',
    schedule:{mode:'interval',interval_minutes:30,daily_time:'15:30'}};
  context.applyAiConfig(config,['ai','api']);
  $('#aiScheduleMode').value='scheduled_interval';$('#aiScheduleInterval').value='45';$('#aiScheduleTime').value='09:45';$('#aiScheduleEndTime').value='17:15';
  $('#model').value='draft-model';$('#autoAiEnabled').checked=false;
  context.editAiSchedule('ai');
  context.latestAutoState={ai_next_run_at:'2026-11-01T09:45:00+08:00'};
  context.applyAiConfig({...config,schedule:{mode:'daily',interval_minutes:120,daily_time:'17:10'}});
  context.aiConfigBusy=true;context.renderAiConfig();context.aiConfigBusy=false;
  assert.equal($('#aiScheduleMode').value,'scheduled_interval');assert.equal($('#aiScheduleInterval').value,'45');
  assert.equal($('#aiScheduleTime').value,'09:45');assert.equal($('#aiScheduleTimeField').hidden,false);
  assert.equal($('#aiScheduleEndTime').value,'17:15');assert.equal($('#aiScheduleEndTimeField').hidden,false);
  assert.equal($('#model').value,'draft-model');assert.equal($('#autoAiEnabled').checked,false);
  assert.match($('#aiScheduleNext').textContent,/2026-11-01T09:45:00/);
  assert.match($('#aiScheduleNext').textContent,/^已保存计划的下一次 AI 研究：.*当前修改保存后生效$/);
  assert.doesNotMatch($('#apiScheduleNext').textContent,/当前修改保存后生效/);
  assert.equal($('#apiScheduleMode').value,'daily');
  $('#apiScheduleMode').value='interval';$('#apiScheduleInterval').value='240';context.editAiSchedule('api');
  context.updateScheduleFields('api',config.schedule);
  assert.equal($('#apiScheduleInterval').value,'240');assert.equal($('#aiScheduleInterval').value,'45');
});
test('successful save explicitly synchronizes one form and preserves the other unsaved draft',()=>{
  const config={configured:true,enabled:true,effective_enabled:true,verification:'verified',model:'deepseek-flash',
    schedule:{mode:'scheduled_interval',interval_minutes:60,daily_time:'10:15',end_time:'16:30'}};
  context.applyAiConfig(config,['ai']);
  assert.equal($('#aiScheduleInterval').value,'60');assert.equal($('#aiScheduleTime').value,'10:15');
  assert.equal($('#aiScheduleEndTime').value,'16:30');
  assert.doesNotMatch($('#aiScheduleNext').textContent,/已保存计划的|当前修改保存后生效/);
  assert.equal($('#apiScheduleInterval').value,'240');
  context.updateScheduleFields('ai',{mode:'daily',interval_minutes:30,daily_time:'11:30'});
  assert.equal($('#aiScheduleMode').value,'daily');assert.equal($('#aiScheduleTime').value,'11:30');
});
test('disabled next run uses current configuration, never an old report or stale timestamp',()=>{
  context.aiConfig={enabled:false,effective_enabled:false};
  assert.match(context.nextAiScheduleText(null),/自动 AI 已关闭，暂无运行计划/);
  assert.match(context.nextAiScheduleText('2026-11-01T09:45:00+08:00'),/暂无运行计划/);
  context.aiConfig={enabled:true,effective_enabled:false};
  assert.match(context.nextAiScheduleText(null),/自动 AI 已关闭/);
  context.aiConfig={enabled:true,effective_enabled:true};
  assert.match(context.nextAiScheduleText(null),/等待后台计划/);
});
test('pure public scans waiting for a future AI schedule do not claim an immediate AI request',()=>{
  const render=source.slice(source.indexOf('function renderAiResearch('),source.indexOf('function status()'));
  vm.runInContext(render,context);
  Object.assign(context,{aiMetadata:r=>r?.ai_research || null,aiCoverageText:()=> '0 / 0 只',aiTokenCount:()=>0,
    aiFailure:()=>'',current:null,aiConfig:{configured:true,enabled:true,effective_enabled:true,verification:'verified'},
    array:v=>Array.isArray(v)?v:[]});
  context.renderAiResearch({status:'running',stage:'公开数据采集',ai_next_run_at:'2099-01-01T15:30:00+08:00',
    report:{ai_research:{status:'scheduled',request_count:0,usage:{total_tokens:0}}}});
  assert.match($('#aiResearchTitle').textContent,/公开量化扫描正在更新.*等待计划时间/);
  assert.doesNotMatch($('#aiResearchDetail').textContent,/之后调用 AI/);
  assert.match($('#aiNextResearchTime').textContent,/2099-01-01T15:30:00/);
});

test('validation rejects invalid minutes and identical times, accepts overnight windows, and preserves input drafts',()=>{
  const config={configured:true,enabled:true,effective_enabled:true,verification:'verified',model:'deepseek-flash',
    schedule:{mode:'scheduled_interval',interval_minutes:45,daily_time:'22:00',end_time:'02:00'}};
  for(const prefix of ['ai','api']) {
    context.applyAiConfig(config,[prefix]);
    for(const minutes of ['', '1.5', '0', '1441']) {
      $('#'+prefix+'ScheduleInterval').value=minutes;context.editAiSchedule(prefix);
      context.applyAiConfig({...config,schedule:{...config.schedule,interval_minutes:30}});
      assert.equal($('#'+prefix+'ScheduleInterval').value,minutes);
      assert.equal(context.validateAiSchedule(prefix),false);
      assert.match($('#'+prefix+'ScheduleInterval').validationMessage,/整数分钟/);
    }
    $('#'+prefix+'ScheduleInterval').value='45';$('#'+prefix+'ScheduleEndTime').value='22:00';context.editAiSchedule(prefix);
    assert.equal(context.validateAiSchedule(prefix),false);
    assert.match($('#'+prefix+'ScheduleEndTime').validationMessage,/不能与启动时间相同/);
    $('#'+prefix+'ScheduleEndTime').value='02:00';context.editAiSchedule(prefix);
    assert.equal(context.validateAiSchedule(prefix),true);
    assert.equal(context.scheduleFor(prefix).interval_minutes,45);
    assert.equal(context.scheduleFor(prefix).end_time,'02:00');
    $('#'+prefix+'ScheduleEndTime').value='';context.editAiSchedule(prefix);
    assert.equal(context.validateAiSchedule(prefix),true);
    assert.equal(context.scheduleFor(prefix).end_time,null);
  }
});

test('both save entry points validate before sending and preserve optional stop times and enabled switches',async()=>{
  const saves=[];
  Object.assign(context,{saveAiConfig:async(body,modal)=>saves.push({body,modal}),openApi:()=>assert.fail('configured form must not request a new key'),toast:()=>{}});
  vm.runInContext(source.slice(source.indexOf("$('#apiForm').onsubmit"),source.indexOf("$('#testAi').onclick")),context);
  const config={configured:true,enabled:true,effective_enabled:true,verification:'verified',model:'deepseek-flash',
    schedule:{mode:'scheduled_interval',interval_minutes:45,daily_time:'09:30'}};
  for(const prefix of ['ai','api']) {
    context.applyAiConfig(config,[prefix]);
    const submit=()=>prefix==='api'?$('#apiForm').onsubmit({preventDefault(){}}):$('#saveAiSettings').onclick();
    const initial=saves.length;
    $('#'+prefix+'ScheduleInterval').value='';context.editAiSchedule(prefix);await submit();
    assert.equal(saves.length,initial);
    $('#'+prefix+'ScheduleInterval').value='45';$('#'+prefix+'ScheduleEndTime').value='09:30';context.editAiSchedule(prefix);await submit();
    assert.equal(saves.length,initial);
    $('#'+prefix+'ScheduleEndTime').value='';context.editAiSchedule(prefix);
    $('#'+(prefix==='api'?'apiEnabled':'autoAiEnabled')).checked=false;
    await submit();
    assert.equal(saves.length,initial+1);
    assert.equal(saves.at(-1).body.schedule.interval_minutes,45);
    assert.equal(saves.at(-1).body.schedule.end_time,null);
    assert.equal(saves.at(-1).body.enabled,false);
    assert.ok($('#'+(prefix==='api'?'apiForm':'aiScheduleForm')).validityReports>0);
  }
});

test('window closure preserves completed AI coverage, usage and backend next-run time without reporting a failure',()=>{
  vm.runInContext(source.slice(source.indexOf('function aiMetadata('),source.indexOf('function renderAiConfig(')),context);
  context.aiConfig={configured:true,enabled:true,effective_enabled:true,verification:'verified'};
  const ai={status:'window_closed',stopped_for_schedule:true,model:'deepseek-flash',analyzed_count:2,target_count:6,
    request_count:1,usage:{prompt_tokens:1000,completion_tokens:200,total_tokens:1200},
    stopped_reason:'本次时段已结束，未发出的批次保持量化研究；下个时段重新采集证据。'};
  const state={status:'ready',ai_next_run_at:'2026-11-01T09:30:00+08:00',report:{engine:'automatic',ai_research:ai}};
  context.renderAiResearch(state);
  assert.equal($('#aiResearchTitle').textContent,'本次研究时段已结束');
  assert.match($('#aiResearchDetail').textContent,/2 \/ 6.*未发出的批次.*当前请求返回/);
  assert.doesNotMatch($('#aiResearchDetail').textContent,/失败|配置已更新|撤回/);
  assert.equal($('#aiCalls').textContent,'1 次');assert.equal($('#aiCoverage').textContent,'2 / 6 只');
  assert.equal($('#aiTokens').textContent,'1,200');
  assert.match($('#aiNextResearchTime').textContent,/2026-11-01T09:30:00/);
  assert.equal(context.reportHasAi(state.report),true);
  assert.match(context.reportAiLabel(state.report),/时段已结束/);
});
