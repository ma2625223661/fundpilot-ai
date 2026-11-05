const test=require('node:test'),assert=require('node:assert/strict');
const ui=require('../../src/lib/legacy/sector-research.js');
const sector=ui.normalizeSector({id:'x',status:'ok',score:50});
const config={configured:true,enabled:true,effective_enabled:true,verification:'verified',schedule:{mode:'market_sessions'}};
const state={status:'ready',ai_next_run_at:'2026-11-02T09:25:00+08:00',ai_calendar:{status:'verified'},ai_research:{status:'scheduled'}};
const present=(c=config,s=state,report={},board=sector)=>ui.aiServicePresentation(board,report,{config:c,state:s});
test('a verified key waiting for its schedule never displays a subscription wall',()=>{
 const result=present();assert.equal(result.status,'scheduled');assert.equal(result.subscribe,false);assert.match(result.tag,/已连接/);assert.match(result.nextText,/11月2日.*09:25/);assert.equal(result.nextRunAt,state.ai_next_run_at);assert.equal(result.title,'正在强化分析');assert.match(result.detail,/不会持续发起新的 AI 请求/);assert.match(result.detail,/下次实际 AI 调用/);
 assert.equal(present({...config,configured:false}).subscribe,true);
 assert.equal(present(null).status,'loading');
 assert.equal(present(null,{config_error:true}).status,'offline');
});
test('connection, disabled plan and calendar failures have their own actionable explanations',()=>{
 const failure=present({...config,verification:'failed',error:'模型权限检查失败'});assert.equal(failure.status,'error');assert.equal(failure.detail,'模型权限检查失败');assert.equal(failure.subscribe,false);
 assert.equal(present({...config,verification:'unverified'}).status,'unverified');
 assert.equal(present({...config,enabled:false,effective_enabled:false}).status,'disabled');
 assert.equal(present(config,{...state,ai_calendar:{status:'unavailable',reason:'交易日历暂未取得'}}).status,'blocked');
 assert.equal(present(config,{...state,connection_error:true}).status,'offline');
});
test('running, sector errors and missing evidence do not masquerade as completed research',()=>{
 assert.equal(present(config,{...state,status:'running',stage:'AI 正在研究 8 / 100 个板块'}).status,'running');
 const result=present(config,{...state,ai_research:{status:'partial',errors:[{sector_ids:['x'],message:'本批请求超时'}]}});
 assert.equal(result.status,'error');assert.equal(result.detail,'本批请求超时');
 assert.equal(present(config,{...state,ai_research:{status:'completed'}}).status,'pending');
 assert.equal(present(config,{...state,ai_research:{status:'no_evidence'}}).status,'no_evidence');
 assert.equal(present(config,state,{},ui.normalizeSector({id:'y',status:'missing'})).status,'no_evidence');
 assert.equal(present(config,{...state,ai_research:{status:'window_closed'}}).status,'scheduled');
});
test('only current source-validated sector output is presented as AI advice',()=>{
 const done=ui.normalizeSector({id:'x',status:'ok',score:60,ai_research_status:'completed',ai_reason:'真实证据支持与反对理由',ai_advice:{action:'reference',reason:'只观察参考走势',watch_points:['核验新财报']}});
 assert.equal(present(config,state,{},done).status,'completed');
 assert.match(present(config,state,{event_analysis:{status:'error'}},done).eventNotice,/事件评估本轮未完成/);
 assert.equal(present(config,state,{report_stale:true},done).status,'stale');
 assert.equal(present(config,{...state,ai_research:{status:'stale'}},{ai_research:{status:'stale'}},done).status,'scheduled');
 assert.equal(present(config,{...state,ai_research:{status:'stale'}},{},done).completed,false);
 assert.equal(present(config,{...state,ai_next_run_at:'invalid'}).nextText,'');
});
