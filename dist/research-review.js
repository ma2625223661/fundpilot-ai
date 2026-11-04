(function(root){
  'use strict';
  const actions={track:'重点跟踪',observe:'持续观察',cautious:'降低关注',avoid:'暂予规避',wait:'等待证据',reference:'参考观察'};
  const number=value=>Number.isFinite(value)?value.toLocaleString('zh-CN',{maximumFractionDigits:2}):'—';
  const percent=value=>Number.isFinite(value)?(value>0?'+':'')+number(value)+'%':'—';
  function summary(items){return {total:items.length,scored:items.filter(i=>Number.isFinite(i.score)).length,verified:items.filter(i=>i.validation?.status==='completed').length,ai:items.filter(i=>i.ai?.status==='completed').length};}
  function chartPoints(series){
    const values=series.map(s=>s.value).filter(Number.isFinite);if(values.length!==6)return '';
    const min=Math.min(...values),range=Math.max(...values)-min||1;
    return values.map((v,i)=>(8+i*56.8).toFixed(1)+','+(55-(v-min)/range*44).toFixed(1)).join(' ');
  }
  if(typeof module!=='undefined'&&module.exports){module.exports={number,percent,summary,chartPoints,actions};return;}
  const $=id=>document.getElementById(id), make=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  const body=$('reviewBody'), refresh=$('refreshReview');if(!body)return;
  let busy=false,lastLoad=0,queued=false,lastDraw='';
  function link(text,href,cls='review-link'){const n=make('a',text,cls);n.href=href;return n;}
  function stat(label,value,description,tone){const n=make('div',undefined,'review-stat');if(tone)n.dataset.tone=tone;n.append(make('span',label),make('strong',value));if(description)n.append(make('small',description));return n;}
  function hint(text){return make('p',text,'review-hint');}
  function empty(title,description,action){const n=make('div',undefined,'review-empty');n.append(make('strong',title),make('p',description));if(action)n.append(action);return n;}
  function draw(data){
    const selected=body.querySelector('select[aria-label="筛选复盘板块"]')?.value||'';
    const filter=data.items?.length>1&&data.items.some(item=>item.id===selected)?selected:'';
    const expanded=new Set(Array.from(body.querySelectorAll('.review-sector-card details[open]'),node=>node.closest('.review-sector-card').dataset.sectorId+'|'+node.className));
    const methodOpen=body.querySelector('.review-method')?.open===true;
    body.replaceChildren();
    if(!data.access){body.append(empty('订阅后，获得持续的研究复核','跟踪关注板块近五个交易日，查看量化复盘、原始结论对照与 AI 改进建议。订阅有效期内附带提供，不额外扣研究点数。',link('了解订阅服务 ↗','ai-service.html#contactTitle')));return;}
    if(data.status==='empty'){body.append(empty('先添加关注，建立自己的复盘清单','复盘围绕你的关注板块展开，与账号同步保存。',link('去选择关注板块 →','#dash')));return;}
    const stats=summary(data.items), overview=make('div',undefined,'review-overview');
    const intro=make('div',undefined,'review-overview-title');intro.append(make('span','最近五个收盘观测 · 按各市场口径'),make('strong',data.period_end?'数据核对至 '+data.period_end:'等待收盘数据'),make('small','订阅附带 · 本功能不扣研究点数'));
    overview.append(intro,stat('关注板块',stats.total+' 个'),stat('已形成复盘分',stats.scored+' 个'),stat('原始结论已核验',stats.verified+' 个'),stat('AI 解读已生成',stats.ai+' 份'));body.append(overview);
    const guide=make('div',undefined,'review-reading-guide');
    guide.append(make('b','怎么看复盘？'),make('span','先看推荐关注档位与操作参考，再核对五日表现和原始结论。规则指数即时计算，AI 解读按时段生成。'));body.append(guide);
    const toolbar=make('div',undefined,'review-toolbar');
    toolbar.append(hint('定时解读 '+data.schedule+' · '+(data.reasoning_effort==='xhigh'?'极高推理':'中度推理')));
    if(data.items.length>1){const label=make('label','查看板块 '),select=make('select');select.setAttribute('aria-label','筛选复盘板块');select.append(new Option('全部关注板块',''));
      for(const item of data.items)select.append(new Option(item.title,item.id));select.value=filter;
      select.onchange=()=>{for(const card of body.querySelectorAll('.review-sector-card'))card.hidden=!!select.value&&card.dataset.sectorId!==select.value;};label.append(select);toolbar.append(label);}
    body.append(toolbar);
    const grid=make('div',undefined,'review-cards');for(const item of data.items){const card=sectorCard(item);card.hidden=!!filter&&item.id!==filter;for(const details of card.querySelectorAll('details'))details.open=expanded.has(item.id+'|'+details.className);grid.append(card);}body.append(grid);
    const method=make('details',undefined,'review-method');method.open=methodOpen;method.append(make('summary','两种分数如何计算？查看口径与边界'),make('h4','五日复盘与观察分 · 看已经发生的表现'),make('p',data.method),make('h4','推荐关注指数 · 看接下来的研究优先级'),make('p',data.guidance_method||'推荐指数等待服务更新，不把缺失数据当作零分。'),make('p','A股公司以沪深300公司样本作参照（非官方指数）；港股、美股公司分别匹配恒生、标普500价格指数。参考指数与利率使用各自的观察模型，依据可在板块卡片中展开。公司样本回溯存在选样偏差；原始研究验证使用记录时冻结的全部样本。缺少数据不记零分。'),make('p',data.note),make('p','原始复核记录独立保存180天；清空个人历史报告不影响复核证据。为控制调用费用，每次定时研究最多生成一批8个复盘解读，其余排队等待。'));body.append(method);
  }
  function guidancePanel(value){
    const box=make('section',undefined,'review-guidance'),g=value||{};box.dataset.action=g.action||'wait';
    const head=make('div',undefined,'review-guidance-heading');head.append(make('b',g.name||'推荐关注指数'),make('span','规则计算 · 不调用 AI'));box.append(head);
    const lead=make('div',undefined,'review-recommendation-lead'),score=make('div',undefined,'review-recommendation-score');score.append(make('strong',number(g.recommendation_index)),make('small','/ 100'));
    lead.append(score,make('span',g.label||'待评估','review-recommendation-tier'));box.append(lead,make('h3',g.headline||'等待完整复盘证据'),make('p',g.reason||'推荐指数等待服务更新；缺失数据不记零分。','review-guidance-reason'));
    if(Number.isFinite(g.effective_cap))box.append(make('div','规则上限 '+number(g.effective_cap)+' · 与五日复盘分取较低值','review-cap-brief'));
    if(g.before_participation||g.if_holding){const cases=make('div',undefined,'review-action-cases');for(const [title,text]of [['尚未参与',g.before_participation],['已经持有时',g.if_holding]])if(text){const cell=make('div');cell.append(make('h4',title),make('p',text));cases.append(cell);}box.append(cases);}
    if(g.upgrade_condition){const rules=make('details',undefined,'review-plan-details');rules.append(make('summary','何时升级 / 何时警惕 · 查看核验清单'),make('h4','升级或维持条件'),make('p',g.upgrade_condition),make('h4','降级与风险条件'),make('p',g.risk_condition));
      const checks=make('div',undefined,'review-checks');for(const check of g.checks||[]){const row=make('div',undefined,'review-check'),top=make('div');row.dataset.met=check.met===true?'yes':check.met===false?'no':'unknown';top.append(make('b',check.label),make('span',check.met===true?'已满足':check.met===false?'未满足':'待补证据'));row.append(top,make('p',check.condition),make('small','当前：'+check.value));checks.append(row);}rules.append(checks);
      if(g.caps?.length){rules.append(make('h4','当前规则上限依据'));const list=make('ul');for(const limit of g.caps)list.append(make('li',limit.reason+' · 上限 '+number(limit.maximum)));rules.append(list);}
      if(g.basis?.length)rules.append(make('p',g.basis.join('；')));
      rules.append(make('small','走势截至 '+(g.period_end||'待确认')+' · 研究快照 '+String(g.research_as_of||'待确认').replace('T',' ').slice(0,16)),make('small',g.note||''));box.append(rules);}
    return box;
  }
  function aiActionPlan(plan){
    const box=make('div',undefined,'review-ai-action-plan');box.append(make('h4','AI 条件式操作思路'));
    for(const [title,text]of [['尚未参与',plan.before_participation],['已经持有时',plan.if_holding]]){const cell=make('div');cell.append(make('b',title),make('p',text));box.append(cell);}
    for(const [title,items]of [['提高关注的信号',plan.upgrade_signals],['需要重新评估的信号',plan.risk_signals]]){box.append(make('h4',title));const list=make('ul');for(const text of items||[])list.append(make('li',text));box.append(list);}
    box.append(make('small','依据本期五日证据给出的条件式思路，受上方最新推荐档位与风险限制约束。'));return box;
  }
  function sectorCard(item){
    const card=make('article',undefined,'review-sector-card');card.dataset.sectorId=item.id;
    const head=make('div',undefined,'review-sector-heading'),title=make('button',item.title,'review-sector-title');title.type='button';title.onclick=()=>root.SectorWorkspace?.openSector?.(item.id);
    card.dataset.status=item.status;head.append(title,make('span',item.score_label||(item.status==='unsupported'?'暂不支持':'等待数据'),'review-state'));card.append(head);
    card.append(guidancePanel(item.guidance),evidencePanel(item));
    if(item.status==='pending'||item.status==='unsupported'){card.append(empty('暂未形成复盘分',item.reason));card.append(validation(item.validation));return card;}
    if(item.review_kind==='rate'){card.append(ratePanel(item),validation(item.validation));return card;}
    const scoreArea=make('div',undefined,'review-score-area'),score=make('div',undefined,'review-score');score.dataset.tone=!Number.isFinite(item.score)?'unknown':item.score>=75?'strong':item.score>=50?'steady':'weak';
    score.append(make('span',item.score_name||'五日走势复盘分'),make('strong',number(item.score)),make('small','/ 100'));
    const plot=make('div',undefined,'review-plot'),ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 300 64');svg.setAttribute('role','img');svg.setAttribute('aria-label',item.title+'五个交易日归一化样本走势');
    const baseline=document.createElementNS(ns,'line');baseline.setAttribute('x1','8');baseline.setAttribute('x2','292');baseline.setAttribute('y1','60');baseline.setAttribute('y2','60');baseline.setAttribute('stroke','currentColor');baseline.setAttribute('opacity','.16');svg.append(baseline);
    const path=document.createElementNS(ns,'polyline');path.setAttribute('points',chartPoints(item.series));path.setAttribute('fill','none');path.setAttribute('stroke','currentColor');path.setAttribute('stroke-width','2.5');svg.append(path);plot.append(svg,make('small',item.period_start+' — '+item.period_end+' · '+(item.sample_count?item.sample_count+' 家公司样本':'来源价格指数')));
    scoreArea.append(score,plot);card.append(scoreArea);
    card.append(hint('衡量已发生的走势；分数越高表示本轮样本表现越强。'));
    const metrics=make('div',undefined,'review-metrics'),changeTone=value=>!Number.isFinite(value)?'unknown':value>0?'positive':value<0?'negative':'flat';
    metrics.append(stat('五次收盘涨跌',percent(item.return_pct),item.review_kind==='reference'?'来源价格口径':'本轮公司样本',changeTone(item.return_pct)));
    if(item.review_kind!=='reference')metrics.append(stat('相对参照',Number.isFinite(item.excess_pct)?(item.excess_pct>0?'+':'')+number(item.excess_pct)+' 百分点':'—',item.reference_label||'正值表示跑赢参考',changeTone(item.excess_pct)));
    metrics.append(stat('最大回撤',Number.isFinite(item.drawdown_pct)?number(item.drawdown_pct)+'%':'—','期间从高点最大跌幅'),stat('上涨次数',Number.isFinite(item.up_days)?item.up_days+' / 5 次':'—','五个收盘区间'));card.append(metrics);
    const partsBox=make('details',undefined,'review-parts-details');partsBox.append(make('summary','查看评分分项 · '+(item.review_kind==='reference'?'价格模型 40 / 35 / 25':'每项满分 25')));
    const parts=make('div',undefined,'review-components');for(const component of item.components){const max=component.maximum||25,row=make('div',undefined,'review-component'),top=make('div');top.append(make('span',component.label),make('b',Number.isFinite(component.points)?number(component.points)+' / '+max:'待补数据'));const track=make('div',undefined,'review-track'),fill=make('span');fill.style.width=(Number.isFinite(component.points)?component.points/max*100:0)+'%';track.append(fill);row.append(top,track);parts.append(row);}partsBox.append(parts,hint(item.model_method||''),hint('参照：'+(item.reference_label||'沪深300公司样本')+'。观察分与当前完整公司研究分分别计算。'));card.append(partsBox);
    if(item.reason)card.append(hint(item.reason));
    card.append(validation(item.validation));
    const ai=make('section',undefined,'review-ai'),aiHead=make('div',undefined,'review-ai-heading');aiHead.append(make('b','✧ AI 复盘解读'),make('span',item.ai?.status==='completed'?'已生成':'正在强化分析'));ai.append(aiHead);
    if(item.ai?.status==='completed'){
      if(item.ai.plan_reason)ai.append(hint(item.ai.plan_reason));
      ai.append(make('p',item.ai.summary));
      if(item.ai.action_plan)ai.append(aiActionPlan(item.ai.action_plan));
      if(item.ai.next_checks?.length){ai.append(make('h4','接下来核验什么'));const list=make('ul');for(const text of item.ai.next_checks)list.append(make('li',text));ai.append(list);}
      if(item.ai.lessons?.length){const reflection=make('details',undefined,'review-reflection');reflection.append(make('summary','展开本轮反思'));const list=make('ul');for(const text of item.ai.lessons)list.append(make('li',text));reflection.append(list);ai.append(reflection);}
      ai.append(make('small',(item.ai.reasoning_effort==='xhigh'?'极高推理':'中度推理')+' · '+String(item.ai.generated_at||'').replace('T',' ').slice(0,16)+' · 依据 '+(item.ai.evidence_ids||[]).join('、')));
    }else ai.append(make('p',item.ai?.reason||'等待数据补齐后定时生成解读。'),make('small','解读在研究时段按计划生成；刷新页面不触发 AI 调用，本功能不扣研究点数。'));
    card.append(ai);return card;
  }
  function evidencePanel(item){
    const e=item.evidence||{},box=make('details',undefined,'review-evidence');
    box.append(make('summary','复盘依据 · '+(item.review_kind==='company'?(e.members?.length||0)+' 家公司':item.review_kind==='rate'?'隔夜Shibor':'明确映射的价格指数')));
    box.append(make('p',item.calendar_label||'交易日期待核验'),make('p',item.adjustment_note||''));
    if(item.observation_only)box.append(hint('按来源最近五个已发布收盘观测计算；未核验当地完整休市日历，不宣称日期连续。'));
    if(e.members?.length){const names=make('div',undefined,'review-evidence-members');for(const m of e.members)names.append(make('span',m.name+' · '+m.code));box.append(names);}
    if(e.reference_sources?.length){box.append(make('p','同日期参照 · '+e.reference_label));const list=make('ul'),unique=new Map(e.reference_sources.filter(s=>/^https?:\/\//i.test(s.url||'')).map(s=>[s.url,s]));for(const source of unique.values()){const row=make('li'),a=link(source.name||'查看参照来源',source.url);a.target='_blank';a.rel='noopener noreferrer';row.append(a,make('small',source.as_of||'日期未提供'));list.append(row);}box.append(list);}
    const sources=make('ul');for(const source of (e.sources||[]).filter(s=>/^https?:\/\//i.test(s.url||'')).slice(0,10)){const row=make('li'),a=link(source.name||'查看来源',source.url);a.target='_blank';a.rel='noopener noreferrer';row.append(a,make('small',(source.as_of||'日期未提供')+' · '+(source.status==='ok'?'已取得':'待核验')));sources.append(row);}box.append(sources,hint(item.scope||''));return box;
  }
  function ratePanel(item){
    const m=item.rate_metrics||{},box=make('div',undefined,'review-rate-panel');box.append(make('h3','隔夜资金利率 · 五次发布对照'));
    const metrics=make('div',undefined,'review-metrics');metrics.append(stat('最新年化利率',number(m.annual_rate_pct)+'%','不是产品收益率'),stat('五次发布变化',number(m.rate_change_5d_bp)+' 基点','正值表示利率上升'),stat('20次发布变化',number(m.rate_change_20d_bp)+' 基点','同一隔夜期限'),stat('20次发布波动',number(m.rate_std_20d_bp)+' 基点','利率标准差'));box.append(metrics,hint(item.period_start+' — '+item.period_end));const details=make('details',undefined,'review-parts-details');details.append(make('summary','查看专用流动性模型'),make('p',item.model_method));box.append(details);return box;
  }
  function validation(value={}){
    const box=make('details',undefined,'review-validation'),heading=make('summary');heading.append(make('span','原始研究结论验证'),make('b',value.status==='completed'?'已完成五日核验':(value.completed_sessions||0)+'/5 交易日'));box.append(heading,make('p',value.reason||'等待原始研究记录。'));
    const original=value.original;if(original){box.append(make('p','记录于 '+original.observed_at.replace('T',' ').slice(0,16)+' · 当时结论：'+(actions[original.action]||'等待证据')+' · '+(original.tier||'待评估')));box.append(make('p','当时完整研究分：'+number(original.score)+'；已知分：'+number(original.confirmed_score)+'。仅完整评分才能用于对照完整研究档位。'));box.append(make('small','冻结样本：'+original.sample_names.join('、')));if(value.expected_end)box.append(make('p','五日核验收盘日：'+value.expected_end));}
    if(value.status==='completed'){box.append(make('p',Number.isFinite(value.rate_change_bp)?'原始同期限利率后续五次发布变化 '+number(value.rate_change_bp)+' 基点':'原始样本五日涨跌 '+percent(value.return_pct)+' · 最大回撤 '+number(value.drawdown_pct)+'%'));if(Number.isFinite(value.market_risk_change))box.append(make('p','环境风险较记录时变化 '+(value.market_risk_change>0?'+':'')+number(value.market_risk_change)+' 分（当前时点对照，非期末风险回测）'));}
    return box;
  }
  async function load(force=false){
    if(!$('history')?.classList.contains('on'))return;
    if(busy){queued=queued||force;return;}if(!force&&Date.now()-lastLoad<20000)return;
    busy=true;refresh.disabled=true;refresh.textContent='读取中…';
    try{if(!root.FundPilotCloud)throw new Error('请登录账号后查看订阅复盘。');const response=await fetch('/api/me/reviews',{cache:'no-store',signal:AbortSignal.timeout(20000)}),data=await response.json();if(!response.ok)throw new Error(data.error||'复盘读取失败');const signature=JSON.stringify(data);if(signature!==lastDraw){draw(data);lastDraw=signature;}lastLoad=Date.now();}
    catch(error){lastDraw='';body.replaceChildren(empty('复盘暂未读取',error.message||'请稍后重新读取。'));}
    finally{busy=false;refresh.disabled=false;refresh.textContent='刷新复盘 ↻';if(queued){queued=false;load(true);}}
  }
  refresh.onclick=()=>load(true);window.addEventListener('hashchange',()=>load());
  document.addEventListener('click',event=>{if(event.target.closest('[data-view="history"]'))load();});
  document.addEventListener('fundpilot:research-rendered',()=>load(true));document.addEventListener('fundpilot:ai-state-changed',()=>load(true));
  load();
})(typeof window!=='undefined'?window:globalThis);
