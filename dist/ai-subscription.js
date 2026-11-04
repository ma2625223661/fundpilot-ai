(function(root){
  'use strict';
  const labels={active:'服务已开通',unsubscribed:'尚未订阅',expired:'订阅已到期',exhausted:'研究额度不足',paused:'服务已暂停',admin:'管理员'};
  const creditRates={medium:1,xhigh:1.5};
  function creditPlan(balance,cost){
    if(!Number.isFinite(balance)||balance<0||!Number.isInteger(balance*2)||!Object.values(creditRates).includes(cost))return null;
    const units=balance*2,rate=cost*2,count=Math.floor(units/rate);
    return {count,remainder:(units-count*rate)/2};
  }
  function creditText(value){return Number.isFinite(value)?value.toLocaleString('zh-CN',{maximumFractionDigits:1}):'—';}
  function accessPrice(sector){const cost=sector?.ai_access?.cost;return cost===1.5?1.5:1;}
  function reasoningChoice(value){const effort=value?.preferred_reasoning_effort;return creditRates[effort]?{effort,label:effort==='medium'?'中度推理':'极高推理',cost:creditRates[effort]}:null;}
  function manualResearchChoice(sector={},subscription={},runtime={}){
    const effort=[subscription.preferred_reasoning_effort,sector.ai_access?.preferred_reasoning_effort,runtime.config?.reasoning_effort,'medium'].find(value=>creditRates[value]);
    return {effort,label:effort==='medium'?'中度推理':'极高推理',cost:creditRates[effort]};
  }
  function hasDetailedResearch(sector={}){
    const advice=sector.ai_advice,nonempty=value=>typeof value==='string'&&Boolean(value.trim()),refs=new Set(Array.isArray(sector.evidence_ids)?sector.evidence_ids:[]);
    if(!advice||advice.schema_version!==2||advice.scope!==(sector.score_model==='company_research_v2'?'company':'reference')||!['track','observe','cautious','avoid','wait','reference'].includes(advice.action)||!nonempty(advice.reason)||!Array.isArray(advice.watch_points)||!advice.watch_points.length||!advice.watch_points.every(nonempty))return false;
    for(const [key,fields] of [['evidence_chain',['fact','interpretation']],['action_plan',['trigger','step']],['scenarios',['condition','response']]]){
      const rows=advice[key];if(!Array.isArray(rows)||rows.length<1||rows.length>3||!rows.every(row=>row&&fields.every(field=>nonempty(row[field]))&&Array.isArray(row.evidence_ids)&&row.evidence_ids.length>=1&&row.evidence_ids.length<=5&&row.evidence_ids.every(id=>typeof id==='string'&&refs.has(id))))return false;
    }
    return Array.isArray(advice.review_conditions)&&advice.review_conditions.length>=1&&advice.review_conditions.length<=3&&advice.review_conditions.every(nonempty);
  }
  function presentation(value={}){
    const status=labels[value.status]?value.status:'unsubscribed',admin=status==='admin';
    return {status,label:labels[status],credits:admin?'统一管理':creditText(Number.isFinite(value.credits_remaining)?value.credits_remaining:0),
      count:Number.isInteger(value.unlocked_count)?value.unlocked_count:0,canUnlock:value.can_unlock===true,
      expiry:value.expires_at?new Date(value.expires_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'尚未开通'};
  }
  if(typeof module!=='undefined'&&module.exports){module.exports={presentation,creditPlan,accessPrice,reasoningChoice,manualResearchChoice,hasDetailedResearch};return;}
  const context=root.FundPilotCloud;if(!context)return;
  const $=id=>document.getElementById(id),node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  let current=null,profile=null,ledger=null,feedback=null,profileLoading=false,policy=null,preferenceSaving=false;
  const inFlight=new Set();
  const researchJobs=new Map();
  let researchJobsLoading=false;
  async function api(path,body){
    let response;try{response=await fetch(path,body===undefined?{cache:'no-store',signal:AbortSignal.timeout(20000)}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(20000)});}
    catch{throw new Error('结果暂未确认，请重新读取状态；重试同一操作不会重复扣减或增加额度。');}
    const data=await response.json();if(!response.ok){const error=new Error(data.error||'订阅服务暂时不可用');error.status=response.status;throw error;}return data;
  }
  function notifyResearch(){if(typeof CustomEvent==='function'&&document.dispatchEvent)document.dispatchEvent(new CustomEvent('fundpilot:personal-research-changed'));}
  const researchKey=(sectorId,reportId,effort)=>JSON.stringify([sectorId,reportId,effort]);
  function jobBusy(job){return ['submitting','running','query_error'].includes(job.status);}
  function researchProgress(job,value={}){
    job.phase=value.phase==='connecting'?'connecting':value.phase==='researching'?'researching':job.phase||'researching';
    job.message=job.phase==='connecting'?'正在连接并核验 AI 服务；连接成功后开始研究，连接失败不扣研究点数。生成成功后自动保存至研究记录，刷新后可恢复任务。':'AI 正在梳理本板块证据与详细建议。'+(job.reasoning_effort==='xhigh'?'极高推理可能需要数分钟。':'')+'可保持页面或稍后回来查询，刷新后可恢复任务；请勿重复提交。生成成功后自动保存至研究记录。';
  }
  function scheduleResearchPoll(job){clearTimeout(job.timer);job.timer=setTimeout(()=>pollResearch(job),1500);}
  async function finishResearch(job,result){
    clearTimeout(job.timer);job.status=result.status;
    if(result.subscription)accept(result.subscription);
    if(result.status==='completed'){
      if(result.saved===true){try{Promise.resolve(root.SectorWorkspace?.refreshResearchHistory?.()).catch(()=>{});}catch{}}
      if(result.stale===true||result.applicable===false){
        job.message='该次研究已完成，但结果已不适用于当前证据：'+(result.stale_reason||'报告或配置已更新')+'。'+(result.charged?'该次已扣除 '+creditText(result.charged_cost)+' 点。':'该次未扣点。')+' 请刷新最新报告后再决定是否生成。';
        if(result.saved===true)job.message+=' 结果已自动保存至研究记录。';loadProfile();notifyResearch();return;
      }
      job.message=result.charged?(result.reused?'已复用有效研究并解锁':'AI 研究已生成并解锁')+' · 本次扣除 '+creditText(result.charged_cost)+' 点。':'AI 研究已可查看 · 本次未扣点，同一份重复查看不重复扣点。';
      if(result.saved===true)job.message+=' 已自动保存至研究记录。';
      const applied=root.SectorWorkspace?.applyUnlockedSector(result.sector,result.report_id);
      if(!applied)job.message+=' 最新结果已保存，可刷新报告后查看。';
      else if(job.openOnComplete)root.SectorWorkspace?.openSector(job.sector_id);
      loadProfile();
    }else{
      const reason=String(result.error||'未取得有效解读').trim().replace(/[。.!！?？；;\s]+$/u,'');
      job.message=/相同证据.*(?:30\s*分钟|暂缓重发)|30\s*分钟.*(?:暂缓|重发)/.test(reason)?'相同证据近期已发送，为避免重复调用，请等待上次发送满 30 分钟后再生成；本次未扣点。':/今日.*请求数.*(?:上限|保护)|每日.*请求.*上限|request_limit|daily.*request.*limit/i.test(reason)?'今日 AI 请求数已达到保护上限，请等待北京时间次日 00:00 额度恢复，或联系管理员调整；本次未扣点。':/预算|budget/i.test(reason)?'今日 API 预算不足，请等待预算恢复或联系管理员调整；本次未扣点。':'生成未完成：'+reason+'。本次未扣点，可重试。';
    }
    notifyResearch();
  }
  async function pollResearch(job){
    if(job.querying||!job.job_id)return;
    job.querying=true;job.status='running';researchProgress(job);notifyResearch();
    try{
      const result=await api('/api/me/ai-research?job_id='+encodeURIComponent(job.job_id));
      if(result.status==='completed'||result.status==='failed')await finishResearch(job,result);
      else if(result.status==='running'||result.status==='queued'){researchProgress(job,result);scheduleResearchPoll(job);notifyResearch();}
      else throw new Error('研究状态暂未确认');
    }catch(error){job.status='query_error';job.message='暂时无法确认研究进度：'+error.message+' 可点击“查询研究进度”，不会重新提交生成。';notifyResearch();}
    finally{job.querying=false;}
  }
  async function startResearch(sector,report,choice){
    const key=researchKey(sector.id,report.as_of,choice.effort),existing=researchJobs.get(key);
    if(existing?.status==='query_error'){await pollResearch(existing);return;}
    if([...researchJobs.values()].some(jobBusy))return;
    const job={sector_id:sector.id,report_id:report.as_of,reasoning_effort:choice.effort,status:'submitting',openOnComplete:true,message:'正在提交研究请求…'};
    researchJobs.set(key,job);notifyResearch();
    try{
      const result=await api('/api/me/ai-research',{sector_id:sector.id,report_id:report.as_of,reasoning_effort:choice.effort});
      if(result.status==='completed'||result.status==='failed')await finishResearch(job,result);
      else if((result.status==='running'||result.status==='queued')&&typeof result.job_id==='string'){
        job.job_id=result.job_id;job.status='running';researchProgress(job,result);scheduleResearchPoll(job);notifyResearch();
      }else throw new Error('研究请求状态暂未确认，请重试查询');
    }catch(error){job.status='failed';job.message='请求未确认：'+error.message+' 重试会先核对已有任务与结果，避免重复扣点。';notifyResearch();}
  }
  async function resumeResearchJobs(){
    if(researchJobsLoading)return;researchJobsLoading=true;
    try{
      const data=await api('/api/me/ai-research');
      for(const value of Array.isArray(data.jobs)?data.jobs:[]){
        if(!value||typeof value.job_id!=='string'||typeof value.sector_id!=='string'||typeof value.report_id!=='string'||!creditRates[value.reasoning_effort])continue;
        const key=researchKey(value.sector_id,value.report_id,value.reasoning_effort),existing=researchJobs.get(key);
        if(existing&&jobBusy(existing))continue;
        const job={...value,status:'running',openOnComplete:false};researchProgress(job,value);
        researchJobs.set(key,job);scheduleResearchPoll(job);
      }
      notifyResearch();
    }catch{}finally{researchJobsLoading=false;}
  }
  function researchControl(sector,report){
    const runtime=root.SectorWorkspace?.getAiRuntime()||{},subscription=current||runtime.subscription||(context.role==='admin'?{status:'admin'}:{}),choice=manualResearchChoice(sector,subscription,runtime),key=researchKey(sector.id,report.as_of,choice.effort),job=researchJobs.get(key),active=[...researchJobs.values()].find(jobBusy),card=node('section',undefined,'cloud-watch-research-control');
    const isAdmin=subscription.status==='admin',existingEffort=sector.ai_reasoning_effort||sector.ai_access?.reasoning_effort,viewable=sector.ai_research_status==='completed'&&Boolean(sector.ai_analysis)&&(isAdmin||sector.ai_access?.status==='unlocked')&&subscription.status!=='paused',detailed=hasDetailedResearch(sector),legacyViewable=viewable&&!detailed,reusable=viewable&&existingEffort===choice.effort&&detailed,enough=Number.isFinite(subscription.credits_remaining)&&subscription.credits_remaining>=choice.cost,allowed=isAdmin||subscription.status==='active'&&enough||(reusable&&['active','expired','exhausted'].includes(subscription.status)),historical=report.report_stale===true;
    const config=runtime.config,serviceIssue=!config?'AI 连接状态尚未确认，读取成功后可开始研究。':!config.configured?'AI 服务尚未配置，请联系管理员完成连接配置。':config.enabled===false?'AI 服务当前未启用，请联系管理员启用服务后再生成。':'',needsConnection=!serviceIssue&&(config.verification!=='verified'||config.effective_enabled===false);
    card.append(node('small','中度推理 1 点 / 份 · 极高推理 1.5 点 / 份','cloud-watch-research-prices'));
    const actions=node('div',undefined,'cloud-watch-research-actions'),button=node('button',historical?'历史报告仅供复盘':job?.status==='query_error'?'查询研究进度':jobBusy(job||{})?job.phase==='connecting'?'正在连接 AI…':'正在生成 AI 研究…':reusable?'查看 AI 研究 · 不重复扣点':serviceIssue?'AI 连接未就绪':(legacyViewable?'生成详细 AI 建议':needsConnection?'连接并生成研究':job?.status==='failed'?'重试生成 AI 研究':'生成 AI 研究')+' · '+choice.label+(isAdmin?'':' '+creditText(choice.cost)+' 点'),'btn primary cloud-watch-generate');
    button.type='button';button.disabled=historical||(!allowed&&job?.status!=='query_error')||Boolean(serviceIssue&&!reusable&&!jobBusy(job||{}))||Boolean(active&&active!==job)||Boolean(job&&['submitting','running'].includes(job.status));button.setAttribute('aria-label',sector.title+'：'+button.textContent);
    button.onclick=()=>job?.status==='query_error'?pollResearch(job):reusable?root.SectorWorkspace?.openSector(sector.id):startResearch(sector,report,choice);
    const adjust=node('button','调整推理深度','cloud-watch-ai-action');adjust.type='button';adjust.onclick=()=>root.SectorWorkspace?.openSubscription();actions.append(button,adjust);card.append(actions);
    if(legacyViewable){const previous=node('button','查看已有 AI 研究 · 不重复扣点','cloud-watch-ai-action cloud-watch-previous-research');previous.type='button';previous.onclick=()=>root.SectorWorkspace?.openSector(sector.id);actions.append(previous);}
    let message=historical?'请返回最新报告后生成个人 AI 研究。':job?.message||(!allowed?(subscription.status==='active'&&!enough?'当前余额不足 '+creditText(choice.cost)+' 点':subscription.status?labels[subscription.status]||'请先开通订阅':'正在确认订阅状态')+'；开通有效订阅并有足够额度后可生成。':reusable?'已有所选档位的有效解读，重复查看不扣点。':isAdmin?'点击后才生成个人板块研究，管理员不扣个人研究额度。':'点击后才生成；本次'+choice.label+'成功后扣 '+creditText(choice.cost)+' 点，失败不扣点。同一份已解锁结果重复查看不扣点。');
    if(needsConnection&&!historical&&!reusable&&!jobBusy(job||{})&&!job?.message&&allowed)message='点击后先连接并核验 AI 服务，通过后生成详细建议。'+(isAdmin?'管理员不扣个人研究额度。':'本次'+choice.label+'生成有效解读后扣 '+creditText(choice.cost)+' 点；连接或研究失败不扣点，同一份已解锁结果重复查看免费。');
    if(legacyViewable&&!historical&&!job?.message&&allowed)message='已有研究可继续查看。点击后'+(needsConnection?'先连接并核验服务，再':'')+'生成包含依据、研究步骤和情景分析的详细建议；'+(isAdmin?'管理员不扣个人研究额度。':'新的详细建议成功后按'+choice.label+'扣 '+creditText(choice.cost)+' 点，连接或研究失败不扣点。');
    if(!viewable&&!job?.message&&!historical&&!serviceIssue&&allowed)message+=' 生成成功后自动保存至研究记录，刷新后可恢复任务。';
    if(serviceIssue&&!historical&&!reusable&&!jobBusy(job||{}))message=serviceIssue+' 当前不会发起新研究或扣点。';
    if(active&&active!==job)message='另一份个人 AI 研究正在处理，请等待完成后再开始本板块。';
    const status=node('p',message,'cloud-status cloud-watch-generation-status');status.setAttribute('role','status');status.setAttribute('aria-live','polite');card.append(status);return card;
  }
  function serviceLink(text='联系客服订阅 ↗'){
    const a=node('a',text,'cloud-watch-service');a.href='ai-service.html#contactTitle';a.target='_blank';a.rel='noopener noreferrer';return a;
  }
  function drawProfile(){
    if(!profile||!current)return;
    const p=presentation(current);profile.dataset.status=p.status;
    $('subscriptionBadge').textContent=p.label;$('subscriptionCredits').textContent=p.credits+(p.status==='admin'?'':' 点');
    $('subscriptionExpiry').textContent=p.expiry;$('subscriptionUnlocked').textContent=p.count+' 份';
    const used=current.status==='admin';$('subscriptionExpiryBlock').hidden=used;$('subscriptionBalanceLabel').textContent=used?'全站 AI 服务':'剩余研究额度（点）';
    drawCreditPolicy();
  }
  function drawCreditPolicy(){
    if(!policy||!current)return;
    policy.replaceChildren();
    const choice=reasoningChoice(current);
    const controlSummary=$('subscriptionChoiceSummary');if(controlSummary)controlSummary.textContent=choice?'我的推理深度：'+choice.label+' · '+creditText(choice.cost)+' 点 / 份 · 点击调整':'选择推理深度 · 中度 1 点 / 极高 1.5 点';
    const title=node('div',undefined,'research-credit-heading');title.append(node('b','选择我的推理深度'),node('span','1 份 = 1 个板块的 1 期 AI 解读'));policy.append(title);
    const rates=node('div',undefined,'research-credit-rates');
    rates.setAttribute('role','group');rates.setAttribute('aria-label','个人推理深度');
    for(const [effort,label,description] of [['medium','中度推理','日常跟踪'],['xhigh','极高推理','复杂证据梳理']]){
      const card=node('button',undefined,'research-credit-rate'),cost=creditRates[effort],plan=creditPlan(current.credits_remaining,cost),selected=choice?.effort===effort;
      card.type='button';card.dataset.effort=effort;card.setAttribute('aria-pressed',String(selected));card.disabled=preferenceSaving;
      card.setAttribute('aria-label','选择'+label+'，每份 '+creditText(cost)+' 点');
      const top=node('span',undefined,'research-credit-rate-top');top.append(node('b',label),node('span',selected?'✓ 已选择':'选择此档','research-credit-selected'));
      card.append(top,node('strong',creditText(cost)+' 点 / 份'),node('small',description));
      card.append(node('span',current.status==='admin'?'管理员查看不扣个人额度':plan?'当前余额可解锁 '+plan.count+' 份'+(plan.remainder?' · 余 '+creditText(plan.remainder)+' 点':''):'余额读取后显示可用份数','research-credit-estimate'));
      card.onclick=()=>savePreference(effort);
      rates.append(card);
    }
    policy.append(rates,node('p',preferenceSaving?'正在保存个人选择…':choice?'我的选择：'+choice.label+' · '+creditText(choice.cost)+' 点 / 份，已随账号保存。':'请选择适合自己的推理深度；尚未选择时展示已有共享解读的实际档位。','research-credit-current'));
    policy.append(node('p','个人研究由您在关注卡片点击“生成 AI 研究”后开始。关注板块、查看行情或切换深度都不调用 AI、不扣点；生成有效解读后按所选档位扣点并解锁，同一份重复查看免费。管理员公共研究计划独立运行。','research-credit-note'));
    const summary=$('reasoningCreditSummary');
    if(summary){const effort=choice?.effort,cost=creditRates[effort],plan=creditPlan(current.credits_remaining,cost);
      summary.textContent=current.status==='admin'?'订阅用户专享 AI 解读，由管理员选择共享研究强度。中度每份 1 点、极高每份 1.5 点；个人偏好独立保存，管理员查看不扣个人额度。':choice?'我的'+choice.label+'每份 '+creditText(cost)+' 点；当前余额 '+creditText(current.credits_remaining)+' 点'+(plan?'，可解锁 '+plan.count+' 份'+(plan.remainder?'，余 '+creditText(plan.remainder)+' 点':''):'')+'。请到首页“我的 AI 订阅”切换个人档位。':'请到首页“我的 AI 订阅”选择个人推理深度。中度每份 1 点，极高每份 1.5 点；切换不扣点。';
    }
  }
  async function savePreference(effort){
    if(preferenceSaving||reasoningChoice(current)?.effort===effort)return;
    preferenceSaving=true;drawCreditPolicy();
    try{const data=await api('/api/me/ai-preference',{reasoning_effort:effort});accept(data.subscription);
      feedback.textContent='已保存'+(effort==='medium'?'中度':'极高')+'推理，切换未扣点。请在关注卡片点击“生成 AI 研究”开始。';
      await root.SectorWorkspace?.refreshPersonalReport();
    }catch(error){feedback.textContent=error.message;}
    finally{preferenceSaving=false;drawCreditPolicy();}
  }
  function accept(value){if(value){current=value;drawProfile();notifyResearch();}}
  async function loadProfile(){
    if(profileLoading)return;profileLoading=true;
    try{const data=await api('/api/me/ai-subscription');accept(data.subscription);drawLedger(data.items);if(feedback)feedback.textContent='';}
    catch(e){if(feedback)feedback.textContent=e.message;}finally{profileLoading=false;}
  }
  function drawLedger(items){
    if(!ledger)return;ledger.replaceChildren();
    const names={grant:'管理员开通 / 续订',pause:'管理员暂停服务',resume:'管理员恢复服务',unlock:'解锁板块解读'};
    if(!items.length)ledger.append(node('p','暂无额度变动记录。','muted'));
    for(const item of items){const row=node('div',undefined,'subscription-ledger-row'),info=node('div');
      info.append(node('b',names[item.kind]||'额度变动'),node('small',new Date(item.created_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})),node('small',item.note||'账号研究服务'));
      row.append(info,node('strong',(item.delta>0?'+':'')+creditText(item.delta)+' 点'),node('span','余额 '+creditText(item.balance)+' 点'));ledger.append(row);
    }
  }
  function mountProfile(){
    if(profile)return;profile=node('section',undefined,'card subscription-profile');profile.id='aiSubscription';
    const head=node('div',undefined,'subscription-heading');head.append(node('div',undefined,'subscription-title'),node('span','读取订阅中','pill'));head.firstChild.append(node('span','AI RESEARCH ACCESS','eyebrow'),node('h2','我的 AI 订阅'));head.lastChild.id='subscriptionBadge';
    const metrics=node('div',undefined,'subscription-metrics');
    for(const [id,label,value] of [['subscriptionCredits','剩余研究额度（点）','—'],['subscriptionExpiry','有效期至','读取中'],['subscriptionUnlocked','已解锁解读','—']]){
      const block=node('div'),caption=node('span',label),strong=node('strong',value);strong.id=id;
      if(id==='subscriptionCredits')caption.id='subscriptionBalanceLabel';if(id==='subscriptionExpiry')block.id='subscriptionExpiryBlock';block.append(caption,strong);metrics.append(block);
    }
    const detail=node('details',undefined,'subscription-ledger');detail.append(node('summary','查看最近 30 条额度记录'));ledger=node('div');detail.append(ledger);detail.addEventListener('toggle',()=>{if(detail.open)loadProfile();});
    feedback=node('p','','cloud-status');feedback.setAttribute('role','status');
    const actions=node('div',undefined,'subscription-actions'),refresh=node('button','刷新订阅状态','btn');refresh.type='button';refresh.onclick=loadProfile;
    actions.append(node('p',context.role==='admin'?'为用户分配研究额度（点）与有效期。服务商实际调用费用由后台统一承担。':'点击生成后才开始个人 AI 研究，成功后扣点并解锁。同一份解读反复查看不重复扣点。','muted'),refresh);
    if(context.role!=='admin')actions.append(serviceLink('订阅 / 续订 ↗'));
    policy=node('section',undefined,'research-credit-policy');policy.setAttribute('aria-label','研究额度使用规则');
    const controls=node('details',undefined,'subscription-choice-details');controls.id='subscriptionChoiceDetails';const controlsTitle=node('summary','选择推理深度 · 中度 1 点 / 极高 1.5 点');controlsTitle.id='subscriptionChoiceSummary';controls.append(controlsTitle,policy,node('p','未生成有效解读时不扣点。旧报告未记录推理强度时按 1 点 / 份。额度不足或到期后，已解锁内容仍可复盘；服务暂停期间不可查看。','subscription-note'));
    profile.append(head,metrics,controls,actions,detail,feedback);
    const target=$('cloudWatchlist');if(target)target.after(profile);else $('dash').append(profile);
    loadProfile();resumeResearchJobs();document.addEventListener('fundpilot:ai-state-changed',()=>accept(root.SectorWorkspace?.getAiRuntime()?.subscription));
    $('reasoningEffort')?.addEventListener('change',drawCreditPolicy);
    document.addEventListener('visibilitychange',()=>{if(!document.hidden){loadProfile();resumeResearchJobs();}});
  }
  async function unlock(sector,report,button,status){
    const key=sector.ai_access?.content_id;if(!key||inFlight.has(key))return;
    inFlight.add(key);button.disabled=true;button.textContent='正在解锁…';
    try{const result=await api('/api/me/ai-unlock',{sector_id:sector.id,content_id:key,report_id:report.as_of});accept(result.subscription);
      const applied=root.SectorWorkspace?.applyUnlockedSector(result.sector,result.report_id);
      status.textContent=result.charged?'已解锁，消耗 '+creditText(result.charged_cost??accessPrice(sector))+' 点研究额度。':'已解锁，本次未重复扣点。';
      if(!applied)status.textContent+=' 请打开对应历史报告查看。';loadProfile();
    }catch(e){status.textContent=e.message;}finally{inFlight.delete(key);button.disabled=false;button.textContent=(report.report_stale?'解锁历史':'解锁本期')+' · '+creditText(accessPrice(sector))+' 点';}
  }
  function unlockButton(sector,report,status){const b=node('button',(report.report_stale?'解锁历史':'解锁本期')+' · '+creditText(accessPrice(sector))+' 点','btn subscription-unlock');b.type='button';b.disabled=inFlight.has(sector.ai_access?.content_id);b.onclick=()=>unlock(sector,report,b,status);return b;}
  function accessCard(sector,report){const card=node('section',undefined,'subscription-access'),status=node('p','','cloud-status');status.setAttribute('role','status');
    card.append(node('span','✦ AI 自动化研究','eyebrow'),node('h3',report.report_stale?'历史板块 AI 解读':'本期板块 AI 解读'),node('p',report.report_stale?'历史解读仅供复盘，不代表当前市场判断。':'结合已取得的业务、财务、走势与事件证据，查看研究理由、主要风险及后续复核条件。'));
    card.append(sector.ai_access.can_unlock?unlockButton(sector,report,status):serviceLink(),node('small','本份解读 '+creditText(accessPrice(sector))+' 点 · '+(sector.ai_access.pricing_legacy?'旧报告按原标准':sector.ai_access.reasoning_effort==='medium'?'中度推理':'极高推理')+' · 重复查看不扣点'),status);return card;
  }
  function mountAdmin(grid){
    const card=node('section',undefined,'card subscription-admin');card.id='aiSubscriptionAdmin';
    const head=node('div',undefined,'subscription-heading');head.append(node('h2','用户订阅与额度'),node('span','管理员控制','pill'));card.append(head,node('p','为用户开通研究额度（点）与有效期。中度每份 1 点，极高每份 1.5 点；增加额度、续期或暂停均会记录。','muted'));
    const adminBox=node('details',undefined,'admin-account-box');adminBox.append(node('summary','管理管理员账号（最多 2 个）'),node('p','可创建第 2 个管理员。密码只用于创建或重置，系统只保存加密校验值，任何管理员都不能查看明文密码。','muted'));
    const adminForm=node('form',undefined,'admin-account-form'),adminFields={};
    for(const [id,label,autocomplete] of [['username','新管理员用户名','username'],['password','初始密码（8～128 个字符）','new-password'],['confirm','确认初始密码','new-password']]){const field=node('div',undefined,'admin-account-field'),l=node('label',label),input=node('input');input.id='admin-'+id;input.autocomplete=autocomplete;input.type=id==='username'?'text':'password';input.required=true;input.minLength=id==='username'?3:8;input.maxLength=id==='username'?64:128;l.htmlFor=input.id;adminFields[id]=input;field.append(l);const control=node('div',undefined,'admin-account-control');control.append(input);if(id!=='username'){const toggle=node('button','显示密码','password-toggle');toggle.type='button';toggle.setAttribute('aria-controls',input.id);toggle.setAttribute('aria-pressed','false');toggle.onclick=()=>{const visible=input.type==='text';input.type=visible?'password':'text';toggle.textContent=visible?'显示密码':'隐藏密码';toggle.setAttribute('aria-pressed',String(!visible));};control.append(toggle);}field.append(control);adminForm.append(field);}
    const adminSubmit=node('button','创建第 2 个管理员','btn');adminSubmit.type='submit';const adminFeedback=node('p','','cloud-status');adminFeedback.setAttribute('role','status');adminForm.append(adminSubmit,adminFeedback);adminBox.append(adminForm);card.append(adminBox);
    const form=node('form',undefined,'subscription-form'),fieldset=node('fieldset'),select=node('select');select.id='subscriptionUser';
    const choose=node('label','选择用户');choose.htmlFor=select.id;fieldset.append(choose,select);
    const fields={};
    for(const [id,label,type,min,max,value] of [['credits','新增研究额度（点）','number',0,100000,100],['days','延长有效期（天）','number',0,3660,30],['note','备注（用户可见）','text',null,null,'']]){
      const l=node('label',label),input=node('input');input.id='subscription-'+id;input.type=type;input.value=value;l.htmlFor=input.id;
      if(type==='number'){input.min=min;input.max=max;input.step=id==='credits'?0.5:1;input.required=true;}else input.maxLength=200;fields[id]=input;fieldset.append(l,input);
    }
    const button=node('button','开通 / 续订并增加额度','btn');button.type='submit';fieldset.append(button);form.append(fieldset);
    const feedback=node('p','','cloud-status');feedback.setAttribute('role','status');
    const rows=node('div',undefined,'subscription-user-list');card.append(form,node('p','续订从尚未到期的截止时间继续延长；已到期则从现在开始。填写 0 表示该项不增加。','subscription-note'),feedback,rows);grid.append(card);
    let users=[],busy=false,pending=null;
    const id=()=>crypto.randomUUID().replaceAll('-','');
    async function mutate(body){
      if(busy)return;busy=true;fieldset.disabled=true;rows.querySelectorAll('button').forEach(b=>b.disabled=true);
      const signature=JSON.stringify(body);if(!pending||pending.signature!==signature)pending={signature,request_id:id()};
      try{await api('/api/admin/ai-subscription',{...body,request_id:pending.request_id});pending=null;feedback.textContent='订阅设置已保存。';await load();}
      catch(e){feedback.textContent=e.message;}finally{busy=false;fieldset.disabled=false;rows.querySelectorAll('button').forEach(b=>b.disabled=false);}
    }
    function resetPasswordForm(user,trigger){
      const reset=node('form',undefined,'subscription-reset-form');reset.hidden=true;
      reset.setAttribute('aria-label','重置 '+user.username+' 的密码');
      reset.append(node('h3','重置 '+user.username+' 的密码'),node('p','设置新密码后，该用户所有设备上的旧登录立即失效。关注、记录和研究额度保留。','muted'));
      const inputGrid=node('div',undefined,'subscription-reset-fields'),inputs=[];
      for(const [suffix,label] of [['new','新密码（8～128 个字符）'],['confirm','确认新密码']]){
        const field=node('div',undefined,'admin-account-field'),caption=node('label',label),control=node('div',undefined,'admin-account-control'),input=node('input'),toggle=node('button','显示','password-toggle');
        input.id='reset-'+suffix+'-'+user.id;input.type='password';input.autocomplete='new-password';input.minLength=8;input.maxLength=128;input.required=true;caption.htmlFor=input.id;
        toggle.type='button';toggle.setAttribute('aria-label','显示'+label);toggle.setAttribute('aria-controls',input.id);toggle.setAttribute('aria-pressed','false');
        toggle.onclick=()=>{const show=input.type==='password';input.type=show?'text':'password';toggle.textContent=show?'隐藏':'显示';toggle.setAttribute('aria-pressed',String(show));toggle.setAttribute('aria-label',(show?'隐藏':'显示')+label);};
        control.append(input,toggle);field.append(caption,control);inputGrid.append(field);inputs.push(input);
      }
      const actions=node('div',undefined,'subscription-reset-actions'),submit=node('button','确认重置密码','btn'),cancel=node('button','取消','btn'),message=node('p','','cloud-status');message.setAttribute('role','status');submit.type='submit';cancel.type='button';
      const clear=()=>{reset.reset();inputs.forEach(input=>input.type='password');reset.querySelectorAll('.password-toggle').forEach(toggle=>{toggle.textContent='显示';toggle.setAttribute('aria-pressed','false');toggle.setAttribute('aria-label',toggle.getAttribute('aria-label').replace(/^(?:显示|隐藏)/,'显示'));});message.textContent='';};
      cancel.onclick=()=>{clear();reset.hidden=true;trigger.setAttribute('aria-expanded','false');trigger.focus();};
      trigger.onclick=()=>{if(busy)return;const open=reset.hidden;clear();reset.hidden=!open;trigger.setAttribute('aria-expanded',String(open));if(open)inputs[0].focus();};trigger.setAttribute('aria-expanded','false');
      reset.onsubmit=async e=>{e.preventDefault();if(busy||!reset.reportValidity())return;if(inputs[0].value!==inputs[1].value){message.textContent='两次密码不一致，请检查。';inputs[1].focus();return;}
        busy=true;submit.disabled=cancel.disabled=true;reset.querySelectorAll('input,.password-toggle').forEach(control=>control.disabled=true);message.textContent='正在重置密码…';
        try{await api('/api/admin/reset-password',{user_id:user.id,new_password:inputs[0].value});clear();reset.hidden=true;trigger.setAttribute('aria-expanded','false');feedback.textContent=user.username+' 的密码已重置，旧登录已失效。请将新密码安全告知用户。';trigger.focus();}
        catch(error){message.textContent=error.message;}finally{busy=false;submit.disabled=cancel.disabled=false;reset.querySelectorAll('input,.password-toggle').forEach(control=>control.disabled=false);}
      };
      actions.append(submit,cancel);reset.append(inputGrid,actions,message);return reset;
    }
    async function load(){
      try{users=(await api('/api/admin/users')).items;const previous=select.value;select.replaceChildren();rows.replaceChildren();
        const members=users.filter(u=>u.role==='member');
        if(!members.length){const o=node('option','暂无普通用户，请让用户先注册');o.value='';select.append(o);button.disabled=true;}
        else button.disabled=false;
        for(const user of members){const option=node('option',user.username+(user.disabled?' · 账号已停用':''));option.value=user.id;select.append(option);}
        if([...select.options].some(o=>o.value===previous))select.value=previous;
        for(const user of users){
          const row=node('article',undefined,'subscription-user-row'),summary=presentation(user.ai_subscription),info=node('div',undefined,'subscription-user-info');row.dataset.user=user.id;
          const created=user.created_at?new Date(user.created_at*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'未知';
          info.append(node('strong',user.username),node('span',user.role==='admin'?'管理员':user.disabled?'账号已停用':summary.label),node('small',user.role==='admin'?'统一管理服务商凭证与全站计划':'余额 '+summary.credits+' 点 · 已解锁 '+summary.count+' 份'),node('small','创建于 '+created),node('small',user.password_status||'密码状态未知'));row.append(info);
          if(user.role==='member'){
            const actions=node('div',undefined,'subscription-user-actions'),edit=node('button','分配额度','btn');edit.type='button';edit.onclick=()=>{select.value=user.id;fields.credits.focus();};actions.append(edit);
            const reset=node('button','重置密码','btn');reset.type='button';actions.append(reset);const resetForm=resetPasswordForm(user,reset);
            if(summary.status!=='unsubscribed'){const paused=summary.status==='paused',toggle=node('button',paused?'恢复 AI 服务':'暂停 AI 服务','btn');toggle.type='button';toggle.onclick=()=>mutate({user_id:user.id,action:paused?'resume':'pause'});actions.append(toggle);}
            const disable=node('button',user.disabled?'恢复账号':'停用账号','btn');disable.type='button';disable.onclick=async()=>{if(busy)return;busy=true;disable.disabled=true;try{await api('/api/admin/user-state',{user_id:user.id,disabled:!user.disabled});await load();}catch(e){feedback.textContent=e.message;}finally{busy=false;disable.disabled=false;}};actions.append(disable);row.append(actions,resetForm);
          }rows.append(row);
        }
      }catch(e){feedback.textContent=e.message;}
    }
    form.onsubmit=e=>{e.preventDefault();if(!form.reportValidity()||!select.value)return;mutate({user_id:select.value,action:'grant',credits:Number(fields.credits.value),days:Number(fields.days.value),note:fields.note.value.trim()});};
    adminForm.onsubmit=async e=>{e.preventDefault();if(adminFields.password.value!==adminFields.confirm.value){adminFeedback.textContent='两次密码不一致';return;}adminSubmit.disabled=true;try{await api('/api/admin/create-admin',{username:adminFields.username.value.trim(),password:adminFields.password.value});adminFeedback.textContent='第 2 个管理员已创建。初始密码只在创建时使用，之后不会显示。';adminForm.reset();await load();}catch(error){adminFeedback.textContent=error.message;}finally{adminSubmit.disabled=false;}};
    load();
  }
  root.FundPilotSubscriptions={presentation,mountProfile,mountAdmin,accessCard,unlockButton,loadProfile,researchControl,resumeResearchJobs};
})(typeof window==='undefined'?globalThis:window);
