const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const ui=require('../../src/lib/legacy/sector-research.js');
const event=(id,score,direction='positive',extra={})=>({id,title:'有效事件 '+id,reason:'具体经营或政策影响',published_at:'2026-10-30T19:00:00+08:00',impact_score:score,direction,url:'https://www.sse.com.cn/disclosure/',source_ids:['official'],...extra});

test('important events rank by absolute impact and exclude weak news',()=>{
 const result=ui.normalizeEvents({threshold:40,status:'completed',events:[event('weak',39),event('good',58),event('bad',-91,'negative'),event('boundary',40)]});
 assert.deepEqual(result.events.map(x=>x.id),['bad','good','boundary']);
 assert.equal(result.events[0].impact_level,'high');
 assert.equal(result.events[1].impact_level,'medium');
});
test('event sign and colour follow favourable and adverse impact, independently of market quote colours',()=>{
 const good=event('good',80), bad=event('bad',-90,'negative'), mixed=event('mixed',65,'mixed');
 assert.equal(ui.eventTone(good),'positive');assert.equal(ui.eventScore(good),'+80');
 assert.equal(ui.eventTone(bad),'negative');assert.equal(ui.eventScore(bad),'-90');
 assert.equal(ui.eventTone(mixed),'mixed');assert.equal(ui.eventScore(mixed),'65');
 const css=fs.readFileSync('./dist/sector-research.css','utf8');
 assert.match(css,/event-positive \.event-impact strong\{color:#70e0aa/);
 assert.match(css,/event-negative \.event-impact strong\{color:#ff8b96/);
});
test('unknown, unreferenced and conflicting event scores cannot become visible recommendations',()=>{
 const result=ui.normalizeEvents({threshold:0,events:[event('weak',20),event('infinite',Infinity),event('oversized',101),event('wrongsign',-60),event('wrongnegative',60,'negative'),event('unknown',80,'unknown'),event('missingtime',80,'positive',{published_at:''}),event('invalidtime',80,'positive',{published_at:'yesterday'}),event('unreferenced',80,'positive',{url:'javascript:alert(1)',source_ids:[]}),event('good',55),event('good',99)]});
 assert.deepEqual(result.events.map(x=>x.id),['good']);assert.equal(result.events[0].impact_score,55);
});
test('report histories preserve evaluated events without carrying data credentials',()=>{
 const r=ui.normalizeReport({research_scope:'sectors',sector_analysis:[],snapshot:{news:[{title:'原始弱消息'}]},event_analysis:{events:[event('e',60)],token:'should-not-be-retained'},data_config:{token:'should-not-be-retained'}});
 assert.equal(r.event_analysis.events[0].impact_score,60);
 assert.equal(r.event_analysis.token,undefined);assert.equal(r.data_config,undefined);
 assert.equal(JSON.stringify(r).includes('should-not-be-retained'),false);
});
test('runtime exposes no-token free data settings and twice-per-trading-day schedule controls',()=>{
 const html=fs.readFileSync('./dist/index.html','utf8'), js=fs.readFileSync('./dist/sector-research.js','utf8');
 assert.doesNotMatch(html,/id="dataToken"/);assert.match(html,/BaoStock 数据连接/);assert.match(html,/id="dataSettingsForm"/);assert.match(html,/value="market_sessions"/);assert.match(html,/09:20/);assert.match(html,/14:50/);assert.match(html,/id="eventList"/);
 assert.match(js,/request\('\/api\/data\/config'\)/);assert.match(js,/dataAction\('\/api\/data\/config'/);
 assert.doesNotMatch(js,/setItem\([^\n]*(?:token|dataConfig|dataToken)/i);
 assert.doesNotMatch(js,/report\.snapshot\.news\.slice/);
});


test('company evidence retains additional unique industry samples and never turns missing finance into zero',()=>{
 const sample=(n,extra={})=>({ts_code:'60000'+n+'.SH',name:'样本'+n,industry:'保险',leader_verified:false,role:'业务龙头',quote:{trade_date:'20261030',close:12,pct_chg:-1.2,data_kind:'daily_close',is_intraday:false},market_metrics:{total_mv:500,turnover_rate:null},financials:null,membership_evidence:{l1_name:'非银金融',l3_name:'保险'},source_ids:['tushare:daily'],...extra});
 const result=ui.normalizeCompanyEvidence({status:'partial',sector_leaders:{sector_insurance:[sample(0),sample(1),sample(1),sample(2),sample(3),{ts_code:'bad'}]},token:'private'});
 assert.equal(result.sector_leaders.sector_insurance.length,4);
 const row=result.sector_leaders.sector_insurance[0];assert.equal(row.leader_verified,false);assert.equal(row.financials,null);assert.equal(row.market_metrics.turnover_rate,null);assert.equal(row.quote.is_intraday,false);assert.equal(row.quote.trade_date,'20261030');assert.equal(result.token,undefined);
});
test('financial report dates and factual event excerpts survive report normalization',()=>{
 const report=ui.normalizeReport({research_scope:'sectors',sector_analysis:[],company_evidence:{sector_leaders:{sector_insurance:[{ts_code:'600000.SH',quote:{trade_date:'20261030'},financials:{ann_date:'20261029',end_date:'20260930',roe:0,tr_yoy:null}}]}},event_analysis:{events:[event('fact',70,'positive',{facts:'来自官方披露的具体连续事实摘录',dimensions:{materiality:4,breadth:2,evil:5}})]}});
 const row=report.company_evidence.sector_leaders.sector_insurance[0];assert.equal(row.financials.roe,0);assert.equal(row.financials.tr_yoy,null);assert.equal(row.financials.ann_date,'20261029');assert.equal(row.financials.end_date,'20260930');
 assert.deepEqual(report.event_analysis.events[0].facts,['来自官方披露的具体连续事实摘录']);assert.deepEqual(report.event_analysis.events[0].dimensions,{materiality:4,breadth:2});
});


test('critical risk and excellent trend symbols require explicit backend fields',()=>{
 assert.equal(ui.sectorIndicator({risk:'高风险',trend:'趋势偏强',score:99}),null);
 assert.equal(ui.eventIndicator(event('large',-99,'negative')),null);
 const critical=ui.sectorIndicator({severity:'critical',indicator_reason:'有效板块当日跌幅不高于 -5%'});
 assert.equal(critical.symbol,'!');assert.equal(critical.className,'risk-critical');assert.match(critical.reason,/-5%/);
 const excellent=ui.eventIndicator({signal:'trend_excellent',indicator_reason:'利好且关联板块趋势优'});
 assert.equal(excellent.symbol,'★');assert.equal(excellent.className,'trend-strong');
 const normalized=ui.normalizeEvents({events:[event('explicit',-95,'negative',{severity:'critical',signal:'neutral',indicator_reason:'经营影响与确定性均达标'})]}).events[0];
 assert.equal(normalized.severity,'critical');assert.equal(normalized.indicator_reason,'经营影响与确定性均达标');
 assert.equal(ui.normalizeSector({id:'x',severity:'critical',signal:'neutral',indicator_reason:'规则依据'}).indicator_reason,'规则依据');
 const css=fs.readFileSync('./dist/sector-research.css','utf8'),js=fs.readFileSync('./dist/sector-research.js','utf8');
 assert.match(css,/risk-critical\{color:#9d1d37/);assert.match(css,/trend-strong\{color:#238c58/);
 assert.match(js,/function indicatorNode/);assert.match(js,/setAttribute\('aria-label',indicator.label/);assert.match(js,/const indicator=eventIndicator\(event\)/);
});

test('free data setup reports actual installation and capability verification independently',()=>{
 const normalize=ui.normalizeDataConfig,presentation=value=>ui.dataStatusPresentation(normalize(value));
 assert.equal(presentation({installed:false,verification:'not_installed'}).badge,'未安装 BaoStock');
 assert.equal(presentation({installed:true,verification:'unverified'}).badge,'已安装 · 待检查');
 assert.equal(presentation({installed:true,verification:'checking'}).badge,'连接检查中');
 assert.equal(presentation({installed:true,verification:'timeout',error:'服务端未及时响应'}).message,'服务端未及时响应');
 assert.equal(presentation({installed:true,verification:'failed',error:'网络连接被拒绝'}).message,'网络连接被拒绝');
 assert.doesNotMatch(presentation({installed:true,verification:'failed',error:'网络连接被拒绝'}).message,/安装/);
 assert.equal(presentation({installed:true,verification:'verified'}).badge,'连接已核验');
 const partial=presentation({installed:true,configured:true,verification:'partial',capabilities:[{id:'stock_industry',status:'available',count:5200},{id:'daily',status:'unverified'},{id:'financials',status:'unverified'}]});
 assert.equal(partial.badge,'部分数据可用');assert.match(partial.description,/行业成分\/行业标签：已取得/);assert.match(partial.description,/财务数据：尚未核验/);assert.doesNotMatch(partial.description,/财务数据已连接/);
 const config=normalize({installed:true,verification:'partial',capabilities:[{id:'industry',status:'available'},{id:'daily',status:'empty'},{id:'financial',status:'timeout'}]});
 assert.deepEqual(config.capabilities.map(x=>[x.id,x.status]),[['industry','available'],['daily','empty'],['financial','timeout']]);
 assert.match(ui.dataStatusPresentation(config).description,/代表公司日线：未返回有效数据/);
 assert.equal(presentation({installed:true,verification:'available'}).badge,'已安装 · 待检查');
});

test('asynchronous data checks poll while settings are visible and avoid overlapping requests',async()=>{
 const vm=require('node:vm'),js=fs.readFileSync('./dist/sector-research.js','utf8'),nodes=new Map(),timers=new Map();let timerId=0,visible=true,requests=0,resolveRequest;
 const node=()=>({textContent:'',disabled:false,dataset:{},children:[],classList:{contains:()=>visible},replaceChildren(){this.children=[];},append(...items){this.children.push(...items);}});
 const $=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);};
 const ctx=vm.createContext({$,dataConfig:null,dataLoading:false,dataBusy:false,dataTimer:null,dataPollDelay:1500,report:null,
  normalizeDataConfig:ui.normalizeDataConfig,dataStatusPresentation:ui.dataStatusPresentation,finite:Number.isFinite,
  capabilityStatusLabels:{available:'已取得',unverified:'尚未核验'},el:()=>node(),txt:v=>typeof v==='string'?v:'',stamp:v=>v,setText:(id,text)=>$('#'+id).textContent=text,
  setTimeout:(callback,delay)=>{const id=++timerId;timers.set(id,{callback,delay});return id;},clearTimeout:id=>timers.delete(id),toast:()=>{},
  request:()=>{requests++;return new Promise(resolve=>{resolveRequest=resolve;});}});
 const from=js.indexOf('  function settingsVisible()'),to=js.indexOf("  $('#dataSettingsForm').onsubmit",from);vm.runInContext(js.slice(from,to),ctx);
 const first=ctx.loadDataConfig();await ctx.loadDataConfig();assert.equal(requests,1);
 resolveRequest({config:{installed:true,verification:'checking',capabilities:[]}});await first;
 assert.equal(timers.size,1);assert.equal([...timers.values()][0].delay,1500);assert.equal($('#testData').disabled,true);
 const next=[...timers.values()][0];timers.clear();next.callback();assert.equal(requests,2);
 resolveRequest({config:{installed:true,verification:'partial',capabilities:[{id:'industry',status:'available'}]}});await new Promise(resolve=>setImmediate(resolve));
 assert.equal(timers.size,0);assert.equal($('#testData').disabled,false);assert.match($('#savedDataStatus').textContent,/财务数据：尚未核验/);
 visible=false;ctx.dataConfig={installed:true,verification:'checking',capabilities:[]};ctx.scheduleDataCheck();assert.equal(timers.size,0);
});


test('historical reports and stale event assessments cannot carry current risk or trend signals',()=>{
 const raw={research_scope:'sectors',as_of:'2026-10-30T14:50:00+08:00',sector_analysis:[{id:'x',status:'ok',score:90,severity:'critical',signal:'trend_excellent',indicator_reason:'当时信号'}],event_analysis:{status:'completed',events:[event('hist',-95,'negative',{severity:'critical',signal:'neutral',indicator_reason:'当时信号'})]}};
 const current=ui.normalizeReport(raw);assert.equal(ui.sectorIndicator(current.sector_analysis[0]).label,'特大风险');
 const history=ui.normalizeReport({...raw,report_stale:true});
 assert.equal(ui.sectorIndicator(history.sector_analysis[0]),null);assert.equal(ui.eventIndicator(history.event_analysis.events[0]),null);
 assert.equal(history.sector_analysis[0].indicator_reason,'');assert.equal(history.event_analysis.events[0].indicator_reason,'');
 for(const status of ['stale','expired'])assert.equal(ui.eventIndicator(ui.normalizeEvents({...raw.event_analysis,status}).events[0]),null);
 assert.equal(ui.sectorIndicator(ui.normalizeSector({...raw.sector_analysis[0],status:'stale'})),null);
 assert.equal(current.sector_analysis[0].severity,'critical');
});

test('opening browser history clears live markers and detail explicitly identifies historical analysis',()=>{
 const vm=require('node:vm'),js=fs.readFileSync('./dist/sector-research.js','utf8'),nodes=new Map();
 class Element {constructor(text=''){this.textContent=text||'';this.children=[];this.hidden=false;}append(...children){this.children.push(...children);}replaceChildren(){this.children=[];}setAttribute(){}get childNodes(){return this.children;}}
 const $=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
 const hist=ui.normalizeReport({research_scope:'sectors',as_of:'2026-10-30T14:50:00+08:00',sector_analysis:[{id:'x',title:'测试板块',status:'ok',score:90,severity:'critical',signal:'neutral',indicator_reason:'旧规则',trend:'趋势偏强',risk:'高风险',ai_reason:'旧时点的 AI 理由',ai_research_status:'completed'}],ai_research:{status:'completed'},event_analysis:{events:[]}});
 const ctx=vm.createContext({$,scarcityUI:null,histories:[hist],report:null,selected:'x',normalizeReport:ui.normalizeReport,sectorDataPresentation:ui.sectorDataPresentation,sourceStatusLabel:ui.sourceStatusLabel,el:(tag,text)=>new Element(text),stamp:v=>v,
  setText:(id,text)=>$('#'+id).textContent=text,render:()=>{},view:()=>{},groups:{other:'其他'},applyTone:()=>{},num:()=>'',UNKNOWN:'*****',pct:ui.pct,
  sectorIndicator:ui.sectorIndicator,indicatorNode:()=>new Element('CURRENT SIGNAL'),list:(title)=>new Element(title),renderCompanyEvidence:()=>{},link:(title)=>new Element(title),document:{createTextNode:text=>new Element(text)}});
 const from=js.indexOf('  function renderHistory()'),to=js.indexOf("  $('#clearHistory').onclick",from);vm.runInContext(js.slice(from,to),ctx);ctx.renderHistory();$('#historyList').children[0].onclick();
 assert.equal(ctx.report.report_stale,true);assert.equal(ui.sectorIndicator(ctx.report.sector_analysis[0]),null);
 ctx.researchPanels=ui.researchPanels;ctx.researchAdvicePresentation=ui.researchAdvicePresentation;ctx.researchHistoricalAdvicePresentation=ui.researchHistoricalAdvicePresentation;ctx.researchSavedPresentation=ui.researchSavedPresentation;
 const detailFrom=js.indexOf('  function renderIndependentIndex('),detailTo=js.indexOf('  function renderBoards()',detailFrom);vm.runInContext(js.slice(detailFrom,detailTo),ctx);ctx.renderDetail();
 const text=n=>[n.textContent,...n.children.map(text)].join(' '),detail=text($('#sectorDetail'));
 assert.match(detail,/历史板块分析/);assert.match(detail,/历史分析理由/);assert.match(detail,/历史 AI 板块解读/);assert.doesNotMatch(detail,/CURRENT SIGNAL/);
});

test('important events show a persistent plain-language score and marker legend',()=>{
 const html=fs.readFileSync('./dist/index.html','utf8');
 assert.match(html,/class="event-legend"/);assert.match(html,/利好 \+分（绿）/);assert.match(html,/利空 -分（红）/);assert.match(html,/特大风险（深红）/);assert.match(html,/趋势优（深绿）/);
});

test('unconfigured event research says how many items await AI and that scores are stage scores',()=>{
  const analysis=ui.normalizeEvents({status:'not_configured',candidate_count:10,events:[]});
  assert.equal(analysis.candidate_count,10);
  const notice=ui.eventSetupNotice(analysis);
  assert.match(notice,/已采集 10 条公告或政策/);assert.match(notice,/开启并验证 AI/);assert.match(notice,/满分 70/);
  assert.doesNotMatch(ui.eventSetupNotice(ui.normalizeEvents({status:'not_configured'})),/已采集/);
});
