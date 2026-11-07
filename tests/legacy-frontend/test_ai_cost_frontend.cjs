const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const ui=require('../../dist/sector-research.js');
test('cost summary separates daily budget occupation, actual usage and current-round reuse',()=>{
 const view=ui.costPresentation({requests:14,tokens_reserved:2000000,unknown_requests:1,
   limits:{daily_request_limit:28,daily_token_limit:8000000},
   by_kind:{sector:{requests:13,usage:{prompt_tokens:1500000,completion_tokens:40000}},event:{requests:1,usage:{prompt_tokens:200000,completion_tokens:1000}}}},
   {reused_count:80});
 assert.equal(view.requests,'14 次（计费 14.00 / 28）');assert.equal(view.tokens,'2,000,000 / 8,000,000');assert.equal(view.reused,'80 个板块');
 assert.equal(view.kinds[0].label,'板块解读');assert.equal(view.kinds[1].label,'事件评估');assert.match(view.unknown,/1 笔用量待核验预留/);
 assert.match(view.note,/UTF-8 字节保守预留/);assert.match(view.note,/不是人民币账单/);assert.match(view.note,/待核验预留不代表已扣费/);
});

test('scheduled strengthening labels disclose the next actual call and retain higher priority states',()=>{
 const config={configured:true,enabled:true,effective_enabled:true,verification:'verified',schedule:{mode:'market_sessions'}},state={status:'ready',ai_calendar:{status:'verified'},ai_research:{status:'scheduled'}};
 let activity=ui.aiActivityPresentation(config,state);assert.equal(activity.title,'正在强化分析');assert.equal(activity.reinforcing,true);assert.match(activity.detail,/不会持续发起新的 AI 请求/);
 for(const status of ['running','error','budget_limited','input_too_large']){
  activity=ui.aiActivityPresentation(config,{...state,ai_research:{status}});assert.equal(activity.reinforcing,false);assert.notEqual(activity.title,'正在强化分析');
 }
 for(const status of ['completed','success','partial'])assert.equal(ui.aiActivityPresentation(config,{...state,ai_research:{status}}).reinforcing,true);
 assert.equal(ui.aiActivityPresentation(config,{...state,status:'running',stage:'正在采集公开行情'}).reinforcing,true);
 assert.equal(ui.aiActivityPresentation(config,{...state,status:'running',stage:'正在进行 AI 证据研究'}).reinforcing,false);
 assert.equal(ui.aiActivityPresentation({...config,enabled:false},state).reinforcing,false);
 const html=fs.readFileSync('dist/index.html','utf8');assert.match(html,/09:20 \/ 14:50/);assert.match(html,/开盘前 10 分钟/);assert.match(html,/收盘前 10 分钟/);assert.doesNotMatch(html,/09:10|14:30/);
});
test('missing daily ledger remains unknown and exhausted budgets are explicit',()=>{
 assert.match(ui.costPresentation(null).requests,/—/);assert.equal(ui.costPresentation(null).status,'loading');
 assert.equal(ui.costPresentation({requests:28,tokens_reserved:0,limits:{daily_request_limit:28,daily_token_limit:8000000}}).status,'limited');
 assert.equal(ui.costPresentation({}, {status:'budget_limited'}).status,'limited');
 for(const ledger of [{status:'blocked',error:'测试账本无法读取'},{blocked:true,error:'测试账本无法保存'}]){
  const view=ui.costPresentation(ledger);assert.equal(view.status,'blocked');assert.match(view.label,/账本不可用/);assert.match(view.unknown,/暂停新增 AI 请求/);assert.match(view.unknown,/测试账本/);
 }
});
test('budget and oversize protection are actionable statuses without subscription links',()=>{
 const board=ui.normalizeSector({id:'x',status:'ok',score:50}),config={configured:true,enabled:true,effective_enabled:true,verification:'verified'};
 for(const status of ['budget_limited','input_too_large']){
  const view=ui.aiServicePresentation(board,{}, {config,state:{ai_research:{status}}});assert.equal(view.status,status);assert.equal(view.subscribe,false);
 }
 const done=ui.normalizeSector({id:'x',status:'ok',score:50,ai_reason:'有效证据解读',ai_research_status:'completed',ai_reused:true,ai_generated_at:'2026-10-31T09:25:00+08:00'});
 const view=ui.aiServicePresentation(done,{}, {config,state:{}});assert.match(view.tag,/复用解读/);assert.match(view.detail,/原解读：10月31日 09:25/);
});
test('settings expose guarded budget fields and a compact responsive cost strip',()=>{
 const html=fs.readFileSync('dist/index.html','utf8'),js=fs.readFileSync('dist/sector-research.js','utf8'),css=fs.readFileSync('dist/sector-research.css','utf8');
 for(const id of ['aiReuseEnabled','aiDailyRequestLimit','aiDailyTokenLimit','aiCostRequests','aiCostTokens','aiCostReused','aiCostKinds'])assert.match(html,new RegExp('id="'+id+'"'));
 assert.match(js,/cost_controls:limits/);assert.match(js,/间隔短于30分钟/);assert.match(html,/中度按 1\.0 倍、极高按 1\.5 倍/);
 assert.match(css,/\.ai-cost-metrics\{grid-template-columns:1fr/);
});
