'use strict';
(() => {
  // This deferred script is placed after the research scripts in cloud HTML.
  const context = window.FundPilotCloud; if (!context) return;
  const admin = context.role === 'admin', $ = id => document.getElementById(id);
  const node = (tag, text, cls) => {const n=document.createElement(tag); if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  function adviceSources(ids,report){
    const sources=new Map([...(report.snapshot?.sources||[]),...(report.company_evidence?.sources||[])].filter(source=>source&&typeof source.id==='string').map(source=>[source.id,source])),references=node('div',undefined,'cloud-watch-advice-sources');
    references.append(node('small','依据：'));
    ids.forEach((id,index)=>{const source=sources.get(id),name=[source?.name,source?.title,source?.label].find(value=>typeof value==='string'&&value.trim()),label=name?name.trim().slice(0,80):'来源 '+(index+1);let href=null;try{const url=new URL(source?.url||source?.source_url);if(['http:','https:'].includes(url.protocol))href=url.href;}catch{}
      const item=node(href?'a':'span',label);if(href){item.href=href;item.target='_blank';item.rel='noopener noreferrer';}references.append(item);
    });return references;
  }
  function savedResearchNote(sector,report){
    const saved=window.SectorResearch?.researchSavedPresentation(sector,report);if(!saved?.saved)return null;
    const meta=node('div',undefined,'research-ai-save-meta'),time=node(saved.generatedAt?'time':'span',saved.label,'research-ai-saved-time');if(saved.generatedAt)time.dateTime=saved.generatedAt;
    meta.append(time,node('small',saved.note,'research-ai-save-note'),node('small',saved.dataLabel,'research-ai-data-time'));return meta;
  }
  async function api(path, body) {
    let response;
    try{response = await fetch(path, body === undefined ? {cache:'no-store',signal:AbortSignal.timeout(20000)} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body),signal:AbortSignal.timeout(20000)});}
    catch(error){throw new Error(error.name==='TimeoutError'?'请求超时，请重新加载确认结果':'无法连接账号服务，请检查连接后重试');}
    const data = await response.json(); if (!response.ok) throw new Error(data.error || '请求失败'); return data;
  }
  const identity = node('div', undefined, 'cloud-identity');
  identity.append(node('strong', context.username), node('span', admin ? '管理员 · 公共研究管理' : '个人账号 · 共用研究报告'));
  if (context.preview) identity.append(node('span', '本地预览，尚未云端上线', 'cloud-preview'));
  const logout = node('button', '退出登录', 'btn'); logout.id='cloudLogout';
  logout.onclick = async () => {logout.disabled=true;try{await api('/api/auth/logout', {});location.replace('/login.html');}catch(e){logout.disabled=false;status.textContent=e.message;}};
  identity.append(logout); document.querySelector('main').prepend(identity);
  // A disabled fieldset remains effective when research polling updates its buttons.
  if (!admin) {
    for (const id of ['autoRefresh','refreshSources']) {
      const button=$(id), fieldset=node('fieldset', undefined,'local-controls');fieldset.disabled=true;button.before(fieldset);fieldset.append(button);button.title='公共研究由后台自动更新';
    }
  }
  const watch = node('section', undefined, 'card cloud-personal'); watch.id='cloudWatchlist';
  const watchHeading=node('div',undefined,'cloud-watch-heading'),watchCount=node('span','加载中','pill');
  watchHeading.append(node('h2','我的关注'),watchCount);
  watch.append(watchHeading, node('p','关注重点，一眼看清研究分、走势与风险。名单随账号保存，数据随报告更新。','muted'));
  const reportNote=node('p','','cloud-watch-report muted');watch.append(reportNote);
  const chips=node('div',undefined,'cloud-watch-chips'), controls=node('div',undefined,'cloud-watch-controls'), select=node('select');select.id='cloudWatchSelect';select.setAttribute('aria-label','选择关注板块');
  const add=node('button','添加关注','btn'); add.id='cloudWatchAdd';const status=node('p','','cloud-status');status.setAttribute('role','status');status.setAttribute('aria-live','polite');
  const retry=node('button','重新加载关注','btn');retry.hidden=true;retry.onclick=()=>loadWatch();
  controls.append(select,add);watch.append(controls,status,retry,chips);$('marketQuotes').after(watch);
  let items=[], busy=false, loaded=false, loading=false;
  const study=window.SectorResearch;
  function reportTime(value){if(!value)return '时间待核验';const date=new Date(value);return Number.isNaN(date.getTime())?value:date.toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});}
  function openBoard(id) {
    if(!window.SectorWorkspace?.openSector(id))status.textContent='当前报告尚未包含该板块，请等待报告更新后重试。';
  }
  function draw() {
    const report=window.SectorWorkspace?.getReport(),boards=report?.sector_analysis||[],byId=new Map(boards.map(s=>[s.id,s]));
    watchCount.textContent=loaded?items.length+' 个板块':'加载中';
    reportNote.textContent=report?(report.report_stale?'历史报告 · ':'当前报告 · ')+reportTime(report.as_of)+'；历史或阶段分保留原有口径。':'研究报告加载后展示分数与依据。';
    chips.replaceChildren();
    items.forEach(id=>{
      const s=byId.get(id),title=s?.title||id,wrap=node('article',undefined,'cloud-watch-card'),head=node('div',undefined,'cloud-watch-card-head'),open=node('button',title,'cloud-watch-title'),remove=node('button','×','cloud-watch-remove');
      wrap.dataset.sector=id;open.type=remove.type='button';open.onclick=()=>openBoard(id);
      remove.setAttribute('aria-label','取消关注'+title);remove.title='取消关注';remove.disabled=busy||loading;remove.onclick=()=>change(id,'remove');head.append(open,remove);wrap.append(head);
      if(s){
        const scarcityBadge=window.FundPilotScarcity?.badge(s.scarcity);if(scarcityBadge)wrap.append(scarcityBadge);
        const data=study.sectorDataPresentation(s,{historical:report.report_stale}),tone=study.colorForSector(s,report.report_stale);
        wrap.style.setProperty('--watch-tone',tone.color);wrap.style.setProperty('--watch-border',tone.border);
        const state=node('span',report.report_stale?'历史快照':!data.hasScore?'待补数据':s.score_model==='company_research_v2'&&s.score_status!=='complete'?'阶段研究':'研究已更新','cloud-watch-state');state.dataset.state=report.report_stale?'historical':!data.hasScore?'pending':'ready';head.insertBefore(state,remove);
        const metrics=node('div',undefined,'cloud-watch-metrics');
        const score=node('div',undefined,'cloud-watch-score'),scoreValue=node('strong',data.hasScore?data.scoreText:'—');
        scoreValue.append(node('small',data.hasScore?data.scoreUnit:report.report_stale?'待更新':'待评估'));
        score.append(node('span',report.report_stale?'历史研究分':'研究分'),scoreValue);
        const change=node('div',undefined,'cloud-watch-change');change.dataset.direction=!report.report_stale&&data.hasQuote&&Number.isFinite(s.change_pct)?s.change_pct>0?'up':s.change_pct<0?'down':'flat':'flat';change.append(node('span',(report.report_stale?'历史':'')+data.changeLabel),node('strong',data.changeText));if(data.dataTimeText)change.append(node('small',data.dataTimeText,'cloud-watch-data-time'));if(data.recoveryNote)change.title=data.recoveryNote;metrics.append(score,change);wrap.append(metrics);
        const view=study.companyScoreView(s);
        if(view){
          const breakdown=node('section',undefined,'cloud-watch-breakdown'),parts=s.score_breakdown||{};
          breakdown.setAttribute('aria-label',(report.report_stale?'历史':'')+'研究分项');
          for(const [key,label,max] of [['fundamentals','基本面',40],['trend','走势',30],['catalysts','事件催化',30]]){
            const part=parts[key]||{},value=key==='catalysts'?part.observed_adjustment:part.points,row=node('div',undefined,'cloud-watch-part'),line=node('div'),meter=node('div',undefined,'cloud-watch-bar');
            const measured=Number.isFinite(value);let display=measured?(key==='catalysts'&&value>0?'+':'')+value.toFixed(2)+(key==='catalysts'?' / ±30':' / '+max):'待评估';
            if(key==='catalysts'&&measured&&!Number.isFinite(part.points))display+=' · 部分';
            line.append(node('span',label),node('b',display));row.append(line);
            meter.dataset.state=measured?'measured':'pending';meter.dataset.sign=measured&&value<0?'negative':'positive';meter.setAttribute('aria-hidden','true');
            const fill=node('i');fill.style.width=(measured?Math.min(100,Math.abs(value)/max*100):0)+'%';meter.append(fill);row.append(meter);breakdown.append(row);
          }
          if(report.report_stale)breakdown.append(node('small','历史分项仅供复盘，最新研究待更新。','cloud-watch-history-note'));wrap.append(breakdown);
        }
        const evidence=node('div',undefined,'cloud-watch-evidence'),risk=node('span',(report.report_stale?'历史行情风险 ':'行情风险 ')+data.riskText,'cloud-watch-risk');
        risk.dataset.level=/高|特大/.test(data.riskText)?'high':/中/.test(data.riskText)?'medium':'normal';evidence.append(risk);
        if(Number.isFinite(s.market_risk?.score)){const environment=node('span','环境风险 '+s.market_risk.score.toFixed(0)+'/100','cloud-watch-risk');environment.dataset.level=s.market_risk.score>=65?'high':s.market_risk.score>=40?'medium':'normal';environment.title=s.market_risk.level||'待核验';evidence.append(environment);}
        wrap.append(evidence);
        const advice=study.researchAdvicePresentation(s,report),runtime=window.SectorWorkspace?.getAiRuntime(),researchControl=window.FundPilotSubscriptions?.researchControl(s,report),ai=node('section',undefined,'cloud-watch-ai'),aiHead=node('div',undefined,'cloud-watch-ai-head');
        let serviceState=study.aiServicePresentation(s,report,runtime);
        const canConnect=runtime?.config?.configured&&runtime.config.enabled!==false,needsConnection=canConnect&&(runtime.config.verification!=='verified'||runtime.config.effective_enabled===false);
        if(researchControl&&canConnect&&!serviceState.completed&&!serviceState.unlockable&&!serviceState.subscribe&&serviceState.status!=='locked')serviceState={...serviceState,status:'manual',tag:needsConnection?'订阅专属 · 点击连接':'订阅专属 · 点击生成',title:needsConnection?'连接后开始本板块研究':'由您决定何时开始研究',detail:needsConnection?'点击下方“连接并生成研究”，系统会先核验服务，再梳理本板块证据与详细建议；连接或研究失败不扣点。':'关注板块和查看行情不会启动个人 AI 研究。选择推理深度后，点击下方按钮开始；完成后展示研究建议、风险与核验条件。'};
        ai.dataset.status=serviceState.status;
        aiHead.append(node('span','✦','cloud-watch-ai-icon'),node('h3','AI 板块研究'));ai.append(aiHead,node('span',serviceState.tag,'cloud-watch-ai-tag'));
        ai.append(node('strong',serviceState.title,'cloud-watch-advice'),node('p',serviceState.detail,'cloud-watch-ai-summary'));
        if(serviceState.completed){const saved=savedResearchNote(s,report);if(saved)ai.append(saved);}
        if(serviceState.completed&&serviceState.status!=='completed'){ai.append(node('strong',advice.label,'cloud-watch-advice'));if(advice.summary)ai.append(node('p',advice.summary,'cloud-watch-ai-summary'));}
        if(serviceState.nextText&&!serviceState.subscribe&&!researchControl){const plan=node('div',undefined,'cloud-watch-ai-plan'),time=node('time',serviceState.nextText);time.dateTime=serviceState.nextRunAt;plan.append(node('span','管理员公共研究计划'),time);ai.append(plan);}
        if(serviceState.eventNotice&&!serviceState.subscribe)ai.append(node('small',serviceState.eventNotice,'cloud-watch-ai-notice'));
        if(serviceState.completed){const more=node('details');more.append(node('summary','展开 AI 分析、风险与复核条件'),node('p',s.ai_analysis));
          if(advice.watchPoints.length){more.append(node('b','接下来关注'));const list=node('ul');advice.watchPoints.forEach(value=>list.append(node('li',value)));more.append(list);}
          const detailed=s.ai_advice||{};
          for(const [key,heading,fields] of [['evidence_chain','建议依据与推理',['fact','interpretation']],['action_plan','可执行的研究步骤',['trigger','step']],['scenarios','不同情景如何应对',['condition','response']]]){
            const rows=Array.isArray(detailed[key])?detailed[key].slice(0,3):[];if(!rows.length)continue;
            more.append(node('b',heading));const list=node('ol',undefined,'cloud-watch-advice-steps');
            for(const row of rows){const line=node('li'),primary=typeof row?.[fields[0]]==='string'?row[fields[0]]:'',secondary=typeof row?.[fields[1]]==='string'?row[fields[1]]:'';if(primary)line.append(node('strong',primary));if(secondary)line.append(node('p',secondary));const ids=Array.isArray(row?.evidence_ids)?row.evidence_ids.filter(id=>typeof id==='string').slice(0,4):[];if(ids.length)line.append(adviceSources(ids,report));list.append(line);}more.append(list);
          }
          if(Array.isArray(detailed.review_conditions)&&detailed.review_conditions.length){more.append(node('b','何时重新评估'));const list=node('ul');detailed.review_conditions.filter(value=>typeof value==='string').slice(0,3).forEach(value=>list.append(node('li',value)));more.append(list);}
          if(s.ai_risks.length){more.append(node('b','主要风险'));const list=node('ul');s.ai_risks.forEach(value=>list.append(node('li',value)));more.append(list);}
          if(s.ai_invalidation)more.append(node('p','判断失效条件：'+s.ai_invalidation));ai.append(more);
        }
        const serviceRow=node('div',undefined,'cloud-watch-subscribe-row');
        if(serviceState.unlockable&&window.FundPilotSubscriptions){const message=node('small','','cloud-status');message.setAttribute('role','status');serviceRow.append(node('small','解锁后可反复查看'),window.FundPilotSubscriptions.unlockButton(s,report,message));ai.append(message);}
        else if(serviceState.subscribe&&!admin&&!['active','exhausted'].includes(runtime?.subscription?.status)){const service=node('a','订阅查看 ↗','cloud-watch-service');service.href='ai-service.html#contactTitle';service.target='_blank';service.rel='noopener noreferrer';service.setAttribute('aria-label',title+'：了解 AI 板块研究，咨询 QQ 客服');serviceRow.append(node('small','了解服务 · QQ 客服咨询'),service);}
        else if(!researchControl){const action=node('button',serviceState.actionLabel+' →','cloud-watch-ai-action');action.type='button';action.onclick=()=>serviceState.personalPreference?window.SectorWorkspace?.openSubscription():window.SectorWorkspace?.openAiSettings();serviceRow.append(node('small','状态与报告自动同步'),action);}
        if(serviceRow.children.length)ai.append(serviceRow);if(researchControl)ai.append(researchControl);wrap.append(ai);
        const meta=node('details',undefined,'cloud-watch-meta');meta.append(node('summary','数据时间与研究摘要'),node('small','行情时间：'+reportTime(s.as_of)),node('p',s.summary||data.subtitle));wrap.append(meta);
      }else wrap.append(node('p','当前报告暂未包含此板块，已保留关注。','muted'));
      const detail=node('button','查看研究依据 ↗','cloud-watch-open');detail.type='button';detail.disabled=!s;detail.onclick=()=>openBoard(id);wrap.append(detail);chips.append(wrap);
    });
    if(!items.length)chips.append(node('p',loaded?'尚未关注板块。选择下方板块并点击“添加关注”，即可在这里查看研究概览。':'正在读取您的关注列表…','cloud-watch-empty muted'));
    const previous=select.value;select.replaceChildren();
    boards.filter(s=>!items.includes(s.id)).sort((a,b)=>a.title.localeCompare(b.title,'zh-CN')).forEach(s=>{const option=node('option',s.title);option.value=s.id;select.append(option);});
    if(!select.options.length){const option=node('option',boards.length?'当前报告的板块均已关注':'等待板块报告加载');option.value='';select.append(option);}
    if([...select.options].some(option=>option.value===previous))select.value=previous;
    select.disabled=busy||loading||!loaded||!select.value;add.disabled=busy||loading||!loaded||!select.value;
    add.textContent=busy?'正在保存…':'添加关注';watch.setAttribute('aria-busy',String(busy||loading));
  }
  async function change(id, action) {if(busy||loading||!loaded||!id)return;busy=true;retry.hidden=true;status.textContent='正在保存关注列表…';draw();try{items=(await api('/api/me/watchlist',{board_id:id,action})).items;status.textContent=action==='add'?'已保存关注，刷新或重新登录后保留。':'已取消关注';}catch(e){status.textContent='保存失败或状态未确认：'+e.message;retry.hidden=false;}finally{busy=false;draw();}}
  async function loadWatch(){if(loading||busy)return;loading=true;retry.hidden=true;draw();try{const data=await api('/api/me/watchlist');items=data.items;loaded=true;if(status.textContent.includes('失败')||status.textContent.includes('未确认'))status.textContent='关注列表已重新加载。';}catch(e){status.textContent='关注列表读取失败：'+e.message;retry.hidden=false;}finally{loading=false;draw();}}
  add.onclick=()=>change(select.value,'add');
  document.addEventListener('fundpilot:research-rendered',draw);
  document.addEventListener('fundpilot:ai-state-changed',draw);
  document.addEventListener('fundpilot:personal-research-changed',draw);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)loadWatch();});
  loadWatch();
  const grid=node('div',undefined,'cloud-account-grid');
  const account=node('section',undefined,'card cloud-personal');account.id='cloudAccount';
  const accountHead=node('div',undefined,'settings-card-head'),accountTitle=node('div',undefined,'settings-heading'),accountText=node('div');
  const accountIcon=node('span','◇','settings-icon secondary');accountIcon.setAttribute('aria-hidden','true');accountText.append(node('span','ACCOUNT & SECURITY','eyebrow'),node('h2','账号与密码'));accountTitle.append(accountIcon,accountText);accountHead.append(accountTitle,node('span','个人账号','settings-provider'));
  account.append(accountHead,node('p','修改密码后，所有设备上的旧登录都会失效。请妥善保存新密码。','muted'));
  const form=node('form',undefined,'cloud-password'), fields={};
  for(const [id,label,autocomplete] of [['old_password','原密码','current-password'],['new_password','新密码（8～128 个字符）','new-password'],['confirm_password','确认新密码','new-password']]) {
    const field=node('div',undefined,'cloud-password-field'),l=node('label',label),control=node('div',undefined,'cloud-password-control'),input=node('input');input.id=id;input.type='password';input.autocomplete=autocomplete;input.minLength=8;input.maxLength=128;input.required=true;l.htmlFor=id;fields[id]=input;
    const toggle=node('button','显示','cloud-password-toggle');toggle.type='button';toggle.setAttribute('aria-label','显示'+label);toggle.setAttribute('aria-controls',id);toggle.setAttribute('aria-pressed','false');toggle.onclick=()=>{const show=input.type==='password';input.type=show?'text':'password';toggle.textContent=show?'隐藏':'显示';toggle.setAttribute('aria-pressed',String(show));toggle.setAttribute('aria-label',(show?'隐藏':'显示')+label);};
    control.append(input,toggle);field.append(l,control);form.append(field);
  }
  const submit=node('button','更新密码','btn'), feedback=node('p','','cloud-status'),actions=node('div',undefined,'cloud-password-actions');submit.type='submit';feedback.setAttribute('role','status');feedback.setAttribute('aria-live','polite');actions.append(node('span','密码长度：8～128 个字符','muted'),submit);form.append(actions,feedback);account.append(form);grid.append(account);$('settings').append(grid);
  form.onsubmit=async event=>{event.preventDefault();if(fields.new_password.value!==fields.confirm_password.value){feedback.textContent='两次新密码不一致';return;}submit.disabled=true;try{await api('/api/auth/password',{old_password:fields.old_password.value,new_password:fields.new_password.value});form.reset();location.replace('/login.html');}catch(e){feedback.textContent=e.message;}finally{submit.disabled=false;}};
  window.FundPilotPhone?.mountAccount?.(grid,api);
  if(admin)window.FundPilotSubscriptions?.mountAdmin(grid);
  window.FundPilotSubscriptions?.mountProfile();
})();
