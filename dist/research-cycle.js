(function(root){
  'use strict';
  const format=v=>Number.isFinite(v)?v.toLocaleString('zh-CN',{maximumFractionDigits:2}):'—';
  const visibleSectors=(theme,onlyWatched)=>theme.sectors.filter(s=>!onlyWatched||s.watched);
  const scenarioLabel=data=>data.scenarios?.find(s=>s.active)?.title||(data.current_scenario==='mixed'?'资金变化处于中间区间':'等待有效宏观证据');
  const signalReading=signal=>{
    if(signal.status!=='ready'||!Number.isFinite(signal.value))return {label:'等待有效数据',copy:'数据核验完成后再参与判断。',tone:'pending'};
    if(signal.id==='demand')return signal.value>=50?{label:'订单处于扩张区间',copy:'50是荣枯分界；仍需公司订单和利润验证。',tone:'positive'}:{label:'订单低于扩张线',copy:'低于50，需求恢复仍需更多证据。',tone:'caution'};
    if(signal.id==='funding'&&Number.isFinite(signal.change_bp))return signal.change_bp<=-5?{label:'短端资金趋宽',copy:'近20个有效发布日资金价格下降，留意能否传导至企业。',tone:'positive'}:signal.change_bp>=5?{label:'短端资金趋紧',copy:'近20个有效发布日资金价格上升，关注融资与估值压力。',tone:'caution'}:{label:'资金变化较小',copy:'近20个发布日变化处于−5至+5基点之间。',tone:'neutral'};
    return {label:'已有可核验数据',copy:signal.scope||'结合其他证据观察。',tone:'neutral'};
  };
  const scoreReading=item=>{
    if(Number.isFinite(item.score))return {label:'完整研究分',value:format(item.score),maximum:'/ 100',copy:item.tier||'已完成评估',state:'complete'};
    const missing=[['基本面',item.fundamentals],['走势',item.trend],['事件',item.catalysts]].filter(([,v])=>!Number.isFinite(v)).map(([label])=>label);
    return Number.isFinite(item.known_score)?{label:'阶段已确认分',value:format(item.known_score),maximum:'',copy:missing.length?'待补'+missing.join('、')+'，暂不划档':'综合评估待完成，暂不划档',state:'partial'}:{label:'研究分',value:'—',maximum:'',copy:'等待有效公司证据',state:'pending'};
  };
  if(typeof module!=='undefined'&&module.exports){module.exports={format,visibleSectors,scenarioLabel,signalReading,scoreReading};return;}
  const $=id=>document.getElementById(id),make=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  if(!$('cycleBody'))return;
  let data=null,busy=false,last=0,selected='digital',scenario='',scenarioChosen=false,onlyWatched=false,queued=false;
  const button=(text,cls,fn)=>{const b=make('button',text,cls);b.type='button';b.onclick=fn;return b;};
  function link(text,url,cls='cycle-link'){const a=make('a',text,cls);a.href=url;if(url.startsWith('https://')){a.target='_blank';a.rel='noopener noreferrer';}return a;}
  function message(title,copy){const box=make('div',undefined,'cycle-empty');box.append(make('h3',title),make('p',copy));return box;}
  function draw(value){
    data=value;const body=$('cycleBody');body.replaceChildren();
    if(!data.access){const locked=message('为订阅者建立长期机会观察框架','把宏观环境、产业方向与公司证据放在一起，了解机会成立的条件，也看清风险与数据缺口。订阅有效期内附带提供，本页不扣研究点数。');locked.append(link('了解订阅 · 联系客服 ↗','ai-service.html#contactTitle','btn primary'));body.append(locked);return;}
    const hero=make('section',undefined,'cycle-hero'),intro=make('div',undefined,'cycle-current');
    const active=data.scenarios.find(s=>s.active),meaning=active?.implication||(data.current_scenario==='mixed'?'资金变化暂不指向明显宽松或紧张，继续跟踪需求与公司兑现。':'宏观数据仍待补齐，暂不判断当前情景。');
    intro.append(make('span','当前环境 · 先看结论','cycle-kicker'),make('h2',scenarioLabel(data)),make('p',meaning),make('span','长期周期阶段仍待验证','cycle-boundary'));
    const coverage=make('div',undefined,'cycle-coverage');coverage.append(make('span','宏观证据覆盖'),make('strong',data.coverage+' / '+data.coverage_total, 'cycle-coverage-value'),make('p','组数据可核验'));
    const meter=make('div',undefined,'cycle-coverage-meter');meter.setAttribute('role','img');meter.setAttribute('aria-label','已有 '+data.coverage+' 组宏观证据，共 '+data.coverage_total+' 组');for(const s of data.signals){const dot=make('span');dot.dataset.ready=String(s.status==='ready');dot.title=s.title+(s.status==='ready'?' · 可核验':' · 待补齐');meter.append(dot);}coverage.append(meter,make('small','证据覆盖表示数据完整程度，不代表机会概率。'));
    const meta=make('div',undefined,'cycle-hero-meta');meta.append(make('span','先看环境 → 选择主题 → 核验公司'),make('span',data.as_of?'报告更新 '+data.as_of.replace('T',' ').slice(0,16):'等待报告更新'),make('b','订阅附带 · 刷新不扣点'));hero.append(intro,coverage,meta);body.append(hero);
    if(data.status==='awaiting_report')body.append(message('等待新鲜研究报告','后台正在核验报告，或报告缺失、过期、时间无法核验。旧数据不参与当前情景与板块判断。'));
    const evidence=make('section',undefined,'cycle-section'),eh=make('div',undefined,'cycle-section-heading');eh.append(make('h2','结论来自哪些数据'),make('span','月度需求 + 短端资金 · 来源可追溯'));evidence.append(eh);
    const grid=make('div',undefined,'cycle-signal-grid');for(const signal of data.signals.slice(0,2)){
      const card=make('article',undefined,'cycle-signal'),top=make('div',undefined,'cycle-signal-top');top.append(make('h3',signal.title),make('span',signal.status==='ready'?'可核验':'待补齐','cycle-tag'));card.append(top);
      const value=make('div',undefined,'cycle-signal-value');value.append(make('strong',format(signal.value)),make('span',signal.unit||''));const reading=signalReading(signal),explanation=make('div',undefined,'cycle-signal-reading');explanation.dataset.tone=reading.tone;explanation.append(make('b',reading.label),make('p',reading.copy));card.append(value,explanation,make('p',signal.detail,'cycle-signal-detail'));
      const source=make('div',undefined,'cycle-source');source.append(make('span',signal.as_of?signal.as_of.replace('T',' ').slice(0,16):'尚无有效日期'));if(signal.url)source.append(link('来源 ↗',signal.url));card.append(source,make('small',signal.scope));grid.append(card);
    }evidence.append(grid);const gaps=make('details',undefined,'cycle-gaps');gaps.append(make('summary','还有 '+data.signals.slice(2).filter(s=>s.status!=='ready').length+' 组长期数据待补齐 · 查看缺口'));const gapList=make('div',undefined,'cycle-gap-list');for(const s of data.signals.slice(2)){const item=make('div');item.append(make('b',s.title),make('p',s.detail));gapList.append(item);}gaps.append(gapList);evidence.append(gaps);body.append(evidence);
    const scenarios=make('details',undefined,'cycle-scenario-explorer'),sh=make('summary');sh.append(make('b','如果需求或资金改变，如何观察？'),make('span','展开四种情景'));scenarios.append(sh);const scenarioBody=make('div',undefined,'cycle-scenario-body');scenarioBody.append(make('p','点击情景查看对应条件与研究重点。情景用于交叉验证，不表示周期按此顺序轮转。','cycle-section-copy'));
    const tabs=make('div',undefined,'cycle-scenarios');scenario=scenarioChosen&&data.scenarios.some(s=>s.id===scenario)?scenario:(data.scenarios.find(s=>s.active)?.id||'repair');
    for(const s of data.scenarios){const b=button('', 'cycle-scenario',()=>{scenario=s.id;scenarioChosen=true;updateScenario();});b.dataset.scenario=s.id;b.setAttribute('aria-pressed',String(s.id===scenario));b.append(make('span',s.active?'● 当前观测':'条件情景'),make('b',s.title));tabs.append(b);}scenarioBody.append(tabs,make('div',undefined,'cycle-scenario-note'));scenarios.append(scenarioBody);body.append(scenarios);updateScenario();
    drawScarcity(body);
    const opportunity=make('section',undefined,'cycle-section'),oh=make('div',undefined,'cycle-section-heading');oh.append(make('h2','选择一个长期方向'),make('span','点击主题查看板块与验证条件'));opportunity.append(oh,make('p','主题提供研究线索，是否值得关注仍需公司数据支持。以下顺序不代表投资排名。','cycle-section-copy'));
    const themes=make('div',undefined,'cycle-themes');for(const theme of data.themes){const b=button('','cycle-theme',()=>{selected=theme.id;updateTheme();});b.dataset.theme=theme.id;b.setAttribute('aria-pressed',String(theme.id===selected));const h=make('div');h.append(make('small',theme.serial),make('b',theme.title),make('span','↗'));b.append(h,make('p',theme.subtitle),make('small',theme.evidence_count+'/'+theme.sectors.length+' 个方向有当前样本证据'+(theme.watch_count?' · 已关注 '+theme.watch_count+' 个':'')));themes.append(b);}opportunity.append(themes,make('div',undefined,'cycle-theme-detail'));body.append(opportunity);updateTheme();
    const method=make('details',undefined,'cycle-method');method.append(make('summary','了解康波周期、证据口径与使用边界'),make('p','“康博周期”通常指“康波周期”（Kondratieff long wave）。本页将长波作为长期研究框架，不按固定年份预测拐点，不预设当前处于某一轮底部或起飞阶段。'),make('p',data.method),make('p','情景规则：以新订单PMI的50分界与隔夜Shibor近20个有效发布日变化交叉观察；−5至+5基点之间（不含边界）保持中间情景。阈值为本站初始研究设计，未经策略回测。两项短期数据不足以验证几十年的周期。'),make('p','板块沿用基本面0–40、走势0–30、事件催化−30至+30的既有评分。只有完整评分进入研究档位；阶段分不能直接解释为“乐观看待”。环境风险独立显示，分数越高风险越大。公司样本不代表整个行业；估值、杠杆、现金流与主题收入需要额外核验。'),make('p','本页复用已有公开数据，不生成新的付费AI解读。板块AI解读沿用原订阅规则，解锁前显示实际所需点数。'));
    for(const ref of data.references){const p=make('p');p.append(ref.url?link(ref.title+' ↗',ref.url):make('b',ref.title),make('span',' · '+ref.scope));method.append(p);}body.append(method);
  }
  function updateScenario(){
    const area=$('cycleBody').querySelector('.cycle-scenario-note');if(!area)return;
    const s=data.scenarios.find(x=>x.id===scenario);area.replaceChildren(make('b',s.active?'当前情景核验':'情景演练'),make('span',s.condition+'。'+s.implication));
    for(const b of $('cycleBody').querySelectorAll('[data-scenario]'))b.setAttribute('aria-pressed',String(b.dataset.scenario===scenario));
  }
  function drawScarcity(body){
    const ui=root.FundPilotScarcity,items=Array.isArray(data.scarcity_sectors)?data.scarcity_sectors:[],summary=data.scarcity_summary||{};if(!ui)return;
    const section=make('section',undefined,'cycle-scarcity'),head=make('header');head.append(make('h2','稀缺性线索'),make('span','依据新闻与公告','cycle-scarcity-count'));section.append(head,make('p','看清“什么供给受限、证据是否可靠”，再判断是否值得持续研究。'));
    const progress=make('div',undefined,'cycle-scarcity-progress');for(const [label,value,copy] of [['本批候选',summary.candidate_count||0,'有效公告条数'],['已完成研判',summary.assessed_count||0,'完成证据分析'],['有效稀缺线索',items.filter(s=>ui.isMarked(s)).length,'获得来源支持']]){const cell=make('div');cell.append(make('span',label),make('strong',String(value)),make('small',copy));progress.append(cell);}section.append(progress);
    const coverage=make('div',undefined,'scarcity-news-coverage');coverage.append(make('span',summary.schedule||'A股交易日 09:20 / 14:50（北京时间）'),make('span','随定时研究更新'));section.append(coverage);
    if(!items.length)section.append(message(summary.status==='no_supported_clues'?'本批尚无充分稀缺证据':'等待定时证据研判',summary.status==='no_supported_clues'?'已评估内容暂不足以形成稀缺线索，保持待核验；未标注不等于不稀缺。':'将随下一次定时研究分析已采集公告，辨析支持与相反证据。证据不足时不沿用固定分数、不提前标为稀缺。'));
    const grid=make('div',undefined,'cycle-scarcity-grid');for(const item of items){
      const p=ui.normalize(item.scarcity);if(!p)continue;
      const card=make('article',undefined,'cycle-scarcity-card'),top=make('header'),open=button(item.title+' ↗','cycle-scarcity-open',()=>{if(root.SectorWorkspace?.openSector?.(item.id))window.history.replaceState(null,'','#dash');});
      card.dataset.sector=item.id;top.append(open,ui.badge(p));card.append(top,make('p',p.scope),make('small',p.verification.label+' · '+p.sources[0].published_at.slice(0,10),'scarcity-review'),ui.metrics(p),ui.detail(p,true,false));grid.append(card);
    }if(items.length)section.append(grid);const rules=make('details',undefined,'cycle-scarcity-rules');rules.append(make('summary','查看判断方式与数据口径'),make('p',data.scarcity_note),make('p',summary.note),make('p',summary.cost_note));section.append(rules);body.append(section);
  }
  function updateTheme(){
    const area=$('cycleBody').querySelector('.cycle-theme-detail'),theme=data.themes.find(t=>t.id===selected)||data.themes[0];selected=theme.id;area.replaceChildren();
    for(const b of $('cycleBody').querySelectorAll('[data-theme]'))b.setAttribute('aria-pressed',String(b.dataset.theme===selected));
    const left=make('div',undefined,'cycle-theme-evidence'),head=make('div',undefined,'cycle-detail-heading');head.append(make('h3',theme.title+' · 板块证据'));
    const label=make('label',undefined,'cycle-watch-filter'),input=make('input');input.type='checkbox';input.checked=onlyWatched;input.onchange=()=>{onlyWatched=input.checked;updateTheme();};label.append(input,make('span','只看我的关注'));head.append(label);left.append(head,make('p',theme.thesis),make('p','研究分越高，当前证据越强；环境风险越高，外部压力越大。','cycle-score-guide'));
    const items=visibleSectors(theme,onlyWatched);if(!items.length)left.append(message(onlyWatched?'此主题暂无关注板块':'等待板块数据',onlyWatched?'关闭筛选查看相关方向，再打开板块研究添加关注。':'研究报告更新后会展示对应公司样本证据。'));
    for(const item of items){const row=make('article',undefined,'cycle-sector'),top=make('div',undefined,'cycle-sector-heading'),open=button(item.title+' ↗','cycle-sector-link',()=>{if(root.SectorWorkspace?.openSector?.(item.id)){window.history.replaceState(null,'','#dash');}else{const note=make('p','当前报告暂未包含此方向，请等待报告更新后重试。','cycle-inline-note');row.append(note);}});top.append(open,make('span',item.watched?'已关注':'公司样本','cycle-tag'));row.append(top);
      const score=make('div',undefined,'cycle-sector-score'),reading=scoreReading(item),number=make('div');score.dataset.state=reading.state;number.append(make('small',reading.label),make('b',reading.value),make('span',reading.maximum));score.append(number,make('p',item.status!=='ready'?'数据待更新':reading.copy));row.append(score);
      const scarcityDetail=root.FundPilotScarcity?.detail(item.scarcity,true);if(scarcityDetail)row.append(scarcityDetail);
      const metrics=make('div',undefined,'cycle-sector-metrics');for(const [label,value,max] of [['基本面',item.fundamentals,40],['走势',item.trend,30],['事件',item.catalysts,30],['环境风险',item.risk_score,100]]){const cell=make('div');cell.append(make('span',label),make('b',value===null?'待评估':(label==='事件'&&value>0?'+':'')+format(value)+' / '+max));metrics.append(cell);}row.append(metrics);
      const checks=make('div',undefined,'cycle-checks');for(const check of item.checks){const chip=make('span',(check.state==='met'?'✓ ':check.state==='unmet'?'○ ':'· ')+check.label);chip.dataset.state=check.state;checks.append(chip);}row.append(checks,make('small',(item.as_of?'行情截至 '+item.as_of.slice(0,10):'等待新鲜行情')+(item.risk_status&&item.risk_status!=='complete'?' · 环境风险仅部分数据':'')));left.append(row);
    }
    const right=make('aside',undefined,'cycle-validation');right.append(make('span','RESEARCH CHECKLIST','cycle-kicker'),make('h3','机会成立，需要哪些证据？'));const checks=make('ol');for(const t of theme.next_checks)checks.append(make('li',t));right.append(checks,make('h4','哪些变化会削弱判断？'));const risks=make('ul');for(const t of theme.risks)risks.append(make('li',t));right.append(risks,make('p','先核验证据，再提高关注优先级。研究条件满足不代表价格便宜，也不保证收益。'),link('查看五日复盘 →','#history'));area.append(left,right);
  }
  async function load(force=false){
    if(!$('cycle')?.classList.contains('on'))return;if(busy){queued=queued||force;return;}if(!force&&Date.now()-last<20000)return;
    busy=true;$('refreshCycle').disabled=true;$('cycleStatus').textContent='正在读取最新证据…';
    try{const response=await fetch('/api/me/cycle',{cache:'no-store',signal:AbortSignal.timeout(20000)}),value=await response.json();if(!response.ok)throw new Error(value.error||'周期研究读取失败');draw(value);last=Date.now();$('cycleStatus').textContent=value.access?'订阅附带 · 刷新不扣点':'订阅专属研究功能';}
    catch(error){$('cycleBody').replaceChildren(message('周期研究暂未读取',error.message||'请稍后重试。'));$('cycleStatus').textContent='读取未完成，可重新刷新';}
    finally{busy=false;$('refreshCycle').disabled=false;if(queued){queued=false;load(true);}}
  }
  function navigate(hash){if(hash==='cycle')document.querySelector('[data-view="cycle"]')?.click();if(hash==='history')document.querySelector('[data-view="history"]')?.click();}
  $('refreshCycle').onclick=()=>load(true);
  document.addEventListener('click',e=>{if(e.target.closest('[data-view="cycle"]'))load();const a=e.target.closest('#cycle a[href="#history"]');if(a){e.preventDefault();navigate('history');window.history.replaceState(null,'','#history');}});
  window.addEventListener('hashchange',()=>{if(location.hash==='#cycle')navigate('cycle');load();});
  document.addEventListener('fundpilot:research-rendered',()=>load(true));document.addEventListener('fundpilot:ai-state-changed',()=>load());load();
})(typeof window!=='undefined'?window:globalThis);
