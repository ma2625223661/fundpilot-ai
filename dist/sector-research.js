'use strict';

(function (root) {
  const UNKNOWN = '*****';
  const MAX_COMPANY_SAMPLES = 8;
  const scarcityUI = typeof module !== 'undefined' && module.exports ? require('./sector-scarcity.js') : root.FundPilotScarcity;
  const arr = v => Array.isArray(v) ? v : [];
  const txt = (v, fallback = '') => typeof v === 'string' ? v : fallback;
  const sampleWording = (id,value) => id==='style_microcap' ? txt(value).replace(/龙头样本/g,'小市值样本').replace(/小市值股票观察指标/g,'小市值样本指标').replace(/不是历史龙头组合/g,'不是历史小市值组合') : txt(value);
  const finite = v => typeof v === 'number' && Number.isFinite(v);
  const num = (v, digits = 2) => finite(v) ? v.toFixed(digits) : UNKNOWN;
  const pct = v => finite(v) ? (v > 0 ? '+' : '') + v.toFixed(2) + '%' : UNKNOWN;
  const groups = {industry:'行业主题', broad:'宽基指数', overseas:'海外市场', style:'风格策略', defensive:'防守资产', commodity:'商品资产', other:'其他方向'};
  const safeUrl = v => { try { const u = new URL(v); return ['http:', 'https:'].includes(u.protocol) ? u.href : null; } catch { return null; } };
  const sectorEvidence = s => !/^(?:nav:|fund:|holdings[:_]|announcements_\d|fund[_:])/i.test(txt(s?.id || s?.source_id))
    && !/(?:基金.{0,8}(?:净值|持仓|公告)|(?:净值|持仓).{0,8}基金)/.test(txt(s?.name || s?.title));
  const cleanSource = s => ({id:txt(s?.id || s?.source_id), name:txt(s?.name || s?.label || s?.source), url:safeUrl(s?.url || s?.source_url), status:txt(s?.status), as_of:txt(s?.as_of || s?.data_time), fetched_at:txt(s?.fetched_at), error:txt(s?.error || s?.note)});
  function normalizeEvents(value) {
    const input=value && typeof value==='object'?value:{}, threshold=Math.max(40,finite(input.threshold)?input.threshold:40), seen=new Set(),historical=input.report_stale===true||['stale','expired'].includes(input.status);
    const events=arr(input.events).filter(e=>e&&typeof e==='object').map(e=>({id:txt(e.id),title:txt(e.title),direction:txt(e.direction),impact_score:finite(e.impact_score)?e.impact_score:null,severity:historical?'normal':txt(e.severity),signal:historical?'neutral':txt(e.signal),indicator_reason:historical?'':txt(e.indicator_reason),
      sector_ids:arr(e.sector_ids).filter(v=>typeof v==='string'),sector_labels:arr(e.sector_labels).filter(v=>typeof v==='string'),reason:txt(e.reason),published_at:txt(e.published_at),
      url:safeUrl(e.url),source_name:txt(e.source_name),source_ids:arr(e.source_ids).filter(v=>typeof v==='string'),verification:e.verification?scarcityUI?.verification(e.verification):null,evidence_usable:e.evidence_usable!==false,facts:typeof e.facts==='string'?[e.facts]:arr(e.facts).filter(v=>typeof v==='string'),dimensions:e.dimensions&&typeof e.dimensions==='object'?Object.fromEntries(['materiality','breadth','duration','certainty'].filter(k=>Number.isInteger(e.dimensions[k])&&e.dimensions[k]>=0&&e.dimensions[k]<=5).map(k=>[k,e.dimensions[k]])):{}}))
      .filter(e=>{if(!e.id||!e.title||!e.reason||!e.published_at||!Number.isFinite(new Date(e.published_at).getTime())||!finite(e.impact_score)||Math.abs(e.impact_score)<threshold||Math.abs(e.impact_score)>100||!['positive','negative','mixed'].includes(e.direction)||(!e.url&&!e.source_ids.length)||seen.has(e.id))return false;
        if(e.direction==='positive'&&e.impact_score<=0||e.direction==='negative'&&e.impact_score>=0)return false;seen.add(e.id);e.impact_level=Math.abs(e.impact_score)>=70?'high':'medium';return true;})
      .sort((a,b)=>Math.abs(b.impact_score)-Math.abs(a.impact_score)||b.published_at.localeCompare(a.published_at)||a.id.localeCompare(b.id));
    return {events,threshold,status:txt(input.status,'unavailable'),as_of:txt(input.as_of),hidden_weak_count:finite(input.hidden_weak_count)?Math.max(0,input.hidden_weak_count):0,coverage:input.coverage&&typeof input.coverage==='object'?input.coverage:{},summary:txt(input.summary),method:txt(input.method),error:txt(input.error),candidate_count:finite(input.candidate_count)?Math.max(0,Math.trunc(input.candidate_count)):0};
  }
  // Events are collected without AI, but only the AI assessment may score them.
  function eventSetupNotice(analysis) {
    const found=analysis.candidate_count>0?`已采集 ${analysis.candidate_count} 条公告或政策，`:'';
    return `事件研究尚未启用：${found}需在设置中开启并验证 AI 后才会评估影响。在此之前，公司研究分不含事件维度，只显示阶段分（满分 70），不进入完整档位。`;
  }
  function eventTone(event) {return event.direction==='positive'?'positive':event.direction==='negative'?'negative':'mixed';}
  function sectorIndicator(value) {if(value?.severity==='critical')return {symbol:'!',className:'risk-critical',label:'特大风险',reason:txt(value.indicator_reason)};if(value?.signal==='trend_excellent')return {symbol:'★',className:'trend-strong',label:'趋势优',reason:txt(value.indicator_reason)};return null;}
  const eventIndicator = sectorIndicator;
  function eventScore(event) {return finite(event.impact_score)?(event.direction==='positive'?'+':event.direction==='negative'?'-':'')+Math.abs(event.impact_score).toFixed(0):UNKNOWN;}
  function normalizeCompanyEvidence(value) {
    const input=value&&typeof value==='object'?value:{},leaders={};
    for(const [id,rows] of Object.entries(input.sector_leaders&&typeof input.sector_leaders==='object'?input.sector_leaders:{})){
      const seen=new Set();leaders[id]=arr(rows).filter(row=>row&&typeof row==='object'&&/^(?:\d{6}\.(?:SH|SZ|BJ)|\d{5}\.HK|[A-Z][A-Z0-9.-]{0,14}\.US)$/.test(row.ts_code)&&!seen.has(row.ts_code)&&(seen.add(row.ts_code),true)).slice(0,MAX_COMPANY_SAMPLES).map(row=>{
        const q=row.quote&&typeof row.quote==='object'?row.quote:{},m=row.market_metrics&&typeof row.market_metrics==='object'?row.market_metrics:{},f=row.financials&&typeof row.financials==='object'?row.financials:null,membership=row.membership_evidence&&typeof row.membership_evidence==='object'?row.membership_evidence:{};
        return {ts_code:row.ts_code,name:txt(row.name,row.ts_code),industry:txt(row.industry),leader_verified:row.leader_verified===true,sample_checks:row.sample_checks&&typeof row.sample_checks==='object'?Object.fromEntries(['业务或成分归属','有效报价','披露日财务','近期61日走势'].filter(k=>typeof row.sample_checks[k]==='boolean').map(k=>[k,row.sample_checks[k]])):{},role:txt(row.role),selection_basis:txt(row.selection_basis),as_of:txt(row.as_of),source_ids:arr(row.source_ids).filter(v=>typeof v==='string'),
          quote:{close_kind:txt(q.close_kind),currency:['CNY','HKD','USD'].includes(q.currency)?q.currency:/\.(?:SH|SZ|BJ)$/.test(row.ts_code)?'CNY':null,trade_date:txt(q.trade_date),data_kind:txt(q.data_kind),is_intraday:q.is_intraday===true,close:finite(q.close)?q.close:null,pct_chg:finite(q.pct_chg)?q.pct_chg:null,amount:finite(q.amount)?q.amount:null},
          market_metrics:Object.fromEntries(['total_mv','circ_mv','turnover_rate','volume_ratio','pe_ttm','pb'].map(k=>[k,finite(m[k])?m[k]:null])),
          financials:f?{currency:['CNY','HKD','USD'].includes(f.currency)?f.currency:/\.(?:SH|SZ|BJ)$/.test(row.ts_code)?'CNY':null,currency_note:txt(f.currency_note),ann_date:txt(f.ann_date),end_date:txt(f.end_date),...Object.fromEntries(['roe','eps','netprofit_yoy','tr_yoy','grossprofit_margin'].map(k=>[k,finite(f[k])?f[k]:null]))}:null,
          financials_note:txt(row.financials_note,f?.source_note),membership_evidence:Object.fromEntries(['l1_name','l2_name','l3_name','in_date','out_date','snapshot_date','published_date','evidence_type'].map(k=>[k,txt(membership[k])]))};});
    }
    const selections={};for(const [id,value] of Object.entries(input.sample_selection||{})){if(!value||typeof value!=='object')continue;selections[id]={membership_count:finite(value.membership_count)?value.membership_count:null,quoted_count:finite(value.quoted_count)?value.quoted_count:null,candidate_count:finite(value.candidate_count)?value.candidate_count:0,ready_count:finite(value.ready_count)?value.ready_count:0,selected_count:finite(value.selected_count)?value.selected_count:0,pending:arr(value.pending).map(r=>({name:txt(r.name),ts_code:txt(r.ts_code),reason:txt(r.reason)}))};}
    return {status:txt(input.status,'not_configured'),sector_leaders:leaders,sample_selection:selections,sources:arr(input.sources).filter(sectorEvidence).map(cleanSource),warnings:arr(input.warnings).filter(v=>typeof v==='string'),selection_method:txt(input.selection_method)};
  }
  function normalizeBreakdown(value) {
    const out={};for(const key of ['fundamentals','trend','catalysts']){const row=value?.[key];if(!row||typeof row!=='object')continue;
      out[key]={points:finite(row.points)?row.points:null,observed_adjustment:finite(row.observed_adjustment)?row.observed_adjustment:null,maximum:finite(row.maximum)?row.maximum:null,coverage_pct:finite(row.coverage_pct)?row.coverage_pct:null,status:txt(row.status),scope:txt(row.scope),note:txt(row.note),
        details:arr(row.details).map(d=>({field:txt(d.field),value:finite(d.value)?d.value:null,weight:finite(d.weight)?d.weight:null,score:finite(d.score)?d.score:null,count:finite(d.count)?d.count:null,sample_count:finite(d.sample_count)?d.sample_count:null,coverage_pct:finite(d.coverage_pct)?d.coverage_pct:null})),source_ids:arr(row.source_ids).filter(v=>typeof v==='string')};}
    return out;
  }
  function normalizeMarketRisk(value) {
    if(!value||typeof value!=='object')return {};
    const numbers=v=>Object.fromEntries(['market','liquidity','macro'].map(k=>[k,finite(v?.[k])?v[k]:null]));
    return {score:finite(value.score)?value.score:null,profile:txt(value.profile),level:txt(value.level),status:txt(value.status),coverage_pct:finite(value.coverage_pct)?value.coverage_pct:null,components:numbers(value.components),weights:numbers(value.weights),source_ids:arr(value.source_ids).filter(v=>typeof v==='string'),scope:txt(value.scope),note:txt(value.note)};
  }
  function normalizeMarketLiquidity(value, historical=false) {
    const input=value&&typeof value==='object'?value:{}, bounded=v=>finite(v)&&v>=0&&v<=100?v:null;
    const count=v=>Number.isInteger(v)&&v>=0?v:0, strings=v=>[...new Set(arr(v).filter(s=>typeof s==='string'&&s.trim()))];
    const status=historical||input.status==='stale'?'stale':input.status==='ok'?'ok':'unavailable';
    const score=status==='ok'?bounded(input.score):null;
    const risk_score=status==='ok'?bounded(input.risk_score):null;
    const label=status==='stale'?'待更新':score===null?'数据待补充':score<30?'偏紧':score<45?'略紧':score<60?'中性':score<75?'偏宽':'宽松';
    return {score,risk_score,status,label,as_of:txt(input.as_of),sample_count:count(input.sample_count),
      annual_rate_pct:bounded(input.annual_rate_pct),rate_change_1d_bp:finite(input.rate_change_1d_bp)?input.rate_change_1d_bp:null,
      rate_change_5d_bp:finite(input.rate_change_5d_bp)?input.rate_change_5d_bp:null,rate_change_20d_bp:finite(input.rate_change_20d_bp)?input.rate_change_20d_bp:null,
      rate_change_60d_bp:finite(input.rate_change_60d_bp)?input.rate_change_60d_bp:null,rate_std_20d_bp:finite(input.rate_std_20d_bp)?input.rate_std_20d_bp:null,
      trend:txt(input.trend),source_ids:strings(input.source_ids),missing:strings(input.missing),scope:txt(input.scope),method:txt(input.method),
      summary:status==='stale'?'历史快照，当前市场流动性等待最新数据。':txt(input.summary,'市场流动性数据待补充。')};
  }
  function liquidityPresentation(value) {
    const s=normalizeMarketLiquidity(value),tone=s.score===null?'unknown':s.score<30?'tight':s.score<45?'slightly-tight':s.score<60?'steady':s.score<75?'slightly-loose':'loose';
    return {...s,tone,scoreText:s.score===null?'—':s.score.toFixed(0),statusLabel:s.status==='stale'?'历史 / 待更新':s.status==='ok'?'Shibor模型':'数据待补充'};
  }
  function normalizeMarketSentiment(value, historical=false) {
    const input=value&&typeof value==='object'?value:{}, bounded=v=>finite(v)&&v>=0&&v<=100?v:null;
    const count=v=>Number.isInteger(v)&&v>=0?v:0, strings=v=>[...new Set(arr(v).filter(s=>typeof s==='string'&&s.trim()))];
    const weights={breadth:.4,index_strength:.3,ma20_participation:.3},seen=new Set();
    const status=historical||input.status==='stale'?'stale':['ok','partial'].includes(input.status)?input.status:'unavailable';
    const score=['ok','partial'].includes(status)&&bounded(input.coverage_pct)>=70?bounded(input.score):null;
    return {score,status,label:status==='stale'?'待更新':score===null?'数据待补充':score<20?'低迷':score<40?'偏冷':score<60?'平稳':score<80?'活跃':'过热',
      coverage_pct:bounded(input.coverage_pct),as_of:txt(input.as_of),sample_date:txt(input.sample_date),history_date:txt(input.history_date),
      sample_count:count(input.sample_count),candidate_count:count(input.candidate_count),index_count:Math.min(4,count(input.index_count)),
      components:arr(input.components).filter(c=>c&&Object.hasOwn(weights,c.id)&&!seen.has(c.id)&&(seen.add(c.id),true)).map(c=>({id:c.id,label:txt(c.label),weight:weights[c.id],score:status==='stale'?null:bounded(c.score),count:count(c.count),status:status==='stale'?'stale':txt(c.status,'unavailable'),note:txt(c.note),as_of:txt(c.as_of),source_ids:strings(c.source_ids)})),
      source_ids:strings(input.source_ids),missing:strings(input.missing),method:txt(input.method),scope:txt(input.scope),
      summary:status==='stale'?'历史快照，当前市场情绪等待最新数据。':txt(input.summary,'样本或有效分项不足，暂不生成市场情绪分。')};
  }
  function sentimentPresentation(value) {
    const s=normalizeMarketSentiment(value),tone=s.score===null?'unknown':s.score<20?'cold':s.score<40?'cool':s.score<60?'steady':s.score<80?'active':'hot';
    return {...s,tone,scoreText:s.score===null?'—':s.score.toFixed(2),statusLabel:s.status==='stale'?'历史 / 待更新':s.status==='ok'?'样本代理':s.status==='partial'?'部分数据 · 样本代理':'数据待补充'};
  }
  function normalizeAiAdvice(value,scope,evidenceIds) {
    if(!value||typeof value!=='object')return null;
    const textList=v=>arr(v).filter(s=>typeof s==='string'&&s.trim()).map(s=>s.trim().slice(0,400)).slice(0,3);
    const output={action:txt(value.action),reason:txt(value.reason),watch_points:textList(value.watch_points),schema_version:1,scope:'',evidence_chain:[],action_plan:[],scenarios:[],review_conditions:[]};
    if(value.schema_version!==2||value.scope!==scope)return output;
    const allowed=new Set(evidenceIds),sections={},definitions={evidence_chain:['fact','interpretation'],action_plan:['trigger','step'],scenarios:['condition','response']};
    for(const [name,fields] of Object.entries(definitions)){
      if(!Array.isArray(value[name])||value[name].length<1||value[name].length>3)return output;
      const rows=[];
      for(const row of value[name]){
        if(!row||fields.some(field=>typeof row[field]!=='string'||!row[field].trim())||!Array.isArray(row.evidence_ids)||!row.evidence_ids.length||row.evidence_ids.some(id=>typeof id!=='string'||!allowed.has(id)))return output;
        rows.push({...Object.fromEntries(fields.map(field=>[field,row[field].trim().slice(0,400)])),evidence_ids:[...new Set(row.evidence_ids)].slice(0,5)});
      }
      sections[name]=rows;
    }
    const review=textList(value.review_conditions);if(!review.length)return output;
    return {...output,...sections,schema_version:2,scope,review_conditions:review};
  }
  function normalizeSector(s) {
    if (!s || typeof s !== 'object' || !txt(s.id)) return null;
    const stale = ['stale', 'expired', 'insufficient', 'unavailable', 'unknown', 'missing'].includes(s.status);
    const raw = Object.prototype.hasOwnProperty.call(s,'recommendation_index') ? s.recommendation_index : s.score;
    const requirements=arr(s.requirements),eligible=!requirements.length||['data','mapping','model'].every(id=>requirements.some(r=>r?.id===id&&r.status==='ok'));
    const tierPending=stale||!eligible||(s.score_model==='company_research_v2'&&s.score_status!=='complete');
    return {id:s.id, title:txt(s.title || s.label, s.id), group:txt(s.group, 'other'), status:txt(s.status, 'unknown'),
      scarcity:s.scarcity?.sector_id===s.id?scarcityUI?.normalize(s.scarcity)||null:null,
      score:!stale && eligible && finite(raw) && raw >= 0 && raw <= 100 ? raw : null,
      change_pct:finite(s.change_pct) ? s.change_pct : null, trend:txt(s.trend, '数据待补充'), risk:txt(s.risk, UNKNOWN),severity:stale?'normal':txt(s.severity),signal:stale?'neutral':txt(s.signal),indicator_reason:stale?'':txt(s.indicator_reason),
      data_gaps:arr(s.data_gaps).filter(g=>g&&typeof g==='object').map(g=>({code:txt(g.code),message:txt(g.message),source_ids:arr(g.source_ids).filter(v=>typeof v==='string')})),data_status_summary:sampleWording(s.id,s.data_status_summary),reference_expected:txt(s.reference_expected),
      score_scope:txt(s.score_scope),score_label:txt(s.score_label),research_basis:txt(s.research_basis),custom_index:normalizeCustomIndex(s.custom_index,s.id),score_model:txt(s.score_model),score_cap:finite(s.score_cap)?s.score_cap:null,event_score_status:txt(s.event_score_status),technical_score:finite(s.technical_score)?s.technical_score:null,
      score_status:stale||!eligible?'unavailable':txt(s.score_status),score_maximum:s.score_maximum===70?70:100,score_coverage_pct:finite(s.score_coverage_pct)?s.score_coverage_pct:null,score_possible_range:arr(s.score_possible_range).filter(finite).slice(0,2),score_breakdown:normalizeBreakdown(s.score_breakdown),market_risk:normalizeMarketRisk(s.market_risk),
      research_tier:{id:tierPending?'pending':txt(s.research_tier?.id),label:tierPending?'待完成评估':txt(s.research_tier?.label),reason:txt(s.research_tier?.reason),conditions:Object.fromEntries(['total_at_least_65','fundamentals_at_least_28','trend_at_least_18_or_positive_catalyst','evidence_complete'].map(k=>[k,s.research_tier?.conditions?.[k]===true]))},
      asset_research:s.asset_research&&typeof s.asset_research==='object'?Object.fromEntries(['financial_applicability','credit_data_status','valuation_data_status','redemption_terms_status','coverage_note'].map(k=>[k,txt(s.asset_research[k])])):{},
      metrics:s.metrics&&typeof s.metrics==='object'?Object.fromEntries(['sample_count','return_5d','return_20d','return_60d','annual_volatility','max_drawdown','ma20_gap','annual_rate_pct','rate_change_1d_bp','rate_change_5d_bp','rate_change_20d_bp','rate_change_60d_bp','rate_std_20d_bp'].map(k=>[k,finite(s.metrics[k])?s.metrics[k]:null]).concat([['history_date',/^\d{4}-\d{2}-\d{2}$/.test(s.metrics.history_date)?s.metrics.history_date:null],['is_intraday',s.metrics.is_intraday===true]])):{},
      requirements:arr(s.requirements).filter(r=>r&&typeof r==='object').map(r=>({id:txt(r.id),label:txt(r.label),status:txt(r.status),note:txt(r.note)})),score_method:txt(s.score_method),score_components:s.score_components&&typeof s.score_components==='object'?s.score_components:{},summary:sampleWording(s.id,txt(s.summary, '该方向缺少可用板块行情，暂不生成结论。')), reasons:arr(s.reasons).filter(v=>typeof v==='string').map(v=>sampleWording(s.id,v)),
      risks:arr(s.risks).filter(v=>typeof v==='string'), next_steps:arr(s.next_steps).filter(v=>typeof v==='string'),
      as_of:txt(s.as_of || s.quote?.as_of || s.quote?.data_time), sources:arr(s.sources).filter(sectorEvidence).map(cleanSource),
      quote:s.quote && typeof s.quote === 'object' ? {name:txt(s.quote.name), code:txt(s.quote.code), price:finite(s.quote.price ?? s.quote.last)?(s.quote.price ?? s.quote.last):null,
        change_pct:finite(s.quote.change_pct)?s.quote.change_pct:null, as_of:txt(s.quote.as_of || s.quote.data_time),data_frequency:txt(s.quote.data_frequency),as_of_precision:txt(s.quote.as_of_precision),asset_type:txt(s.quote.asset_type),annual_rate_pct:finite(s.quote.annual_rate_pct)?s.quote.annual_rate_pct:null,change_bp:finite(s.quote.change_bp)?s.quote.change_bp:null,return_type:txt(s.quote.return_type)} : {},
      news:arr(s.news).map(n=>({title:txt(n.title), url:safeUrl(n.url), published_at:txt(n.published_at), source:txt(n.source)})),
      ai_access:s.ai_access&&typeof s.ai_access==='object'?{status:txt(s.ai_access.status),content_id:txt(s.ai_access.content_id),cost:[1,1.5].includes(s.ai_access.cost)?s.ai_access.cost:0,can_unlock:s.ai_access.can_unlock===true,subscription_status:txt(s.ai_access.subscription_status),reasoning_effort:['medium','xhigh'].includes(s.ai_access.reasoning_effort)?s.ai_access.reasoning_effort:null,pricing_legacy:s.ai_access.pricing_legacy===true,preferred_reasoning_effort:['medium','xhigh'].includes(s.ai_access.preferred_reasoning_effort)?s.ai_access.preferred_reasoning_effort:null,preference_pending:s.ai_access.preference_pending===true,available_efforts:arr(s.ai_access.available_efforts).filter(v=>['medium','xhigh'].includes(v))}:null,
      ai_analysis:txt(s.ai_reason,typeof s.ai_analysis==='string' ? s.ai_analysis : txt(s.ai_analysis?.summary)),
      ai_risks:arr(s.ai_risks).filter(v=>typeof v==='string'), ai_invalidation:txt(s.ai_invalidation), ai_research_status:txt(s.ai_research_status),ai_reasoning_effort:['medium','xhigh'].includes(s.ai_reasoning_effort)?s.ai_reasoning_effort:null,ai_reused:s.ai_reused===true,ai_live_retained:s.ai_live_retained===true,ai_generated_at:txt(s.ai_generated_at),
      evidence_ids:arr(s.evidence_ids).filter(v=>typeof v==='string'),
      ai_advice:normalizeAiAdvice(s.ai_advice,s.score_model==='company_research_v2'?'company':'reference',arr(s.evidence_ids).filter(v=>typeof v==='string'))};
  }
  function normalizeCustomIndex(value,sectorId) {
    if(!value||typeof value!=='object')return null;
    return {name:sampleWording(sectorId,value.name),scope:txt(value.scope),data_recovery:txt(value.data_recovery),data_note:txt(value.data_note),method:sampleWording(sectorId,value.method),weighting:txt(value.weighting),base_date:txt(value.base_date),history_end:txt(value.history_end),as_of:txt(value.as_of),
      live_point:value.live_point&&/^\d{4}-\d{2}-\d{2}$/.test(value.live_point.date)&&finite(value.live_point.value)&&value.live_point.value>0?{date:txt(value.live_point.date),value:value.live_point.value}:null,ready:value.ready===true,is_intraday:value.is_intraday===true,value:finite(value.value)?value.value:null,history_count:finite(value.history_count)?value.history_count:0,sample_count:finite(value.sample_count)?value.sample_count:0,
      constituents:arr(value.constituents).filter(r=>r&&/^(?:\d{6}\.(?:SH|SZ|BJ)|\d{5}\.HK|[A-Z][A-Z0-9.-]{0,14}\.US)$/.test(r.code)).slice(0,MAX_COMPANY_SAMPLES).map(r=>({code:r.code,name:txt(r.name,r.code),weight_pct:finite(r.weight_pct)?r.weight_pct:null,as_of:txt(r.as_of),membership_date:txt(r.membership_date),selection_basis:txt(r.selection_basis),source_ids:arr(r.source_ids).filter(v=>typeof v==='string')})),
      history:arr(value.history).filter(r=>r&&/^\d{4}-\d{2}-\d{2}$/.test(r.date)&&finite(r.value)&&r.value>0).slice(-121).map(r=>({date:r.date,value:r.value}))};
  }
  function researchPanels(sector,context={}) {
    const s=sector||{},custom=s.custom_index,rows=context.company_evidence?.sector_leaders?.[s.id]||[],m=s.metrics||{},historical=context.report_stale===true;
    const convertible=s.quote?.asset_type==='convertible_bond';
    const bond=s.quote?.asset_type==='bond',money=s.quote?.asset_type==='money_rate',reference=s.score_scope==='reference_trend';
    const events=arr(context.event_analysis?.events).filter(e=>arr(e.sector_ids).includes(s.id)),finance=rows.filter(r=>r.financials),regime=context.strategy?.regime||{},panic=context.strategy?.panic||{};
    const metric=(label,value)=>label+'：'+(finite(value)?pct(value):'尚缺数据');
    const researchLinked=s.id==='sector_brain_computer',resourceEquity=s.id==='commodities',microcap=s.id==='style_microcap';
    const trend=[custom?(researchLinked?'研究口径：设备及临床研究关联公司等权指标，非脑机业务收入指标。':resourceEquity?'研究口径：金属采矿与油气资源企业股票等权有限样本；不是商品现货或期货价格。':microcap?'研究口径：国证A股核验池内按市值从小到大筛选的小市值样本等权指标，非官方微盘指数或全市场微盘股涨跌。':'研究口径：自建龙头样本等权指标，非全板块涨跌。'):'研究口径：已接入的板块参考指数。',metric('近5日',m.return_5d),metric('近20日',m.return_20d),metric('窗口最大回撤',m.max_drawdown),'日线样本：'+(finite(m.sample_count)?m.sample_count:0)+' 个'];
    if(money){trend.splice(0,trend.length,'研究口径：人民币隔夜Shibor资金利率，非股票或产品收益。','当前年化利率：'+num(m.annual_rate_pct,3)+'%','近5日变化：'+num(m.rate_change_5d_bp)+' 基点','近20日变化：'+num(m.rate_change_20d_bp)+' 基点','利率历史：'+(m.sample_count||0)+' 个观测点');}
    const earnings=rows.map(r=>r.name+'：'+(r.sample_checks?.['披露日财务']===false?'财务核验未通过，未计入完整公司综合分；':'')+(r.financials?'营收同比 '+pct(r.financials.tr_yoy)+'；净利润同比 '+pct(r.financials.netprofit_yoy)+'；报告期 '+r.financials.end_date+'；披露日 '+(r.financials.ann_date||'尚未取得，业绩不计分'):'财务未取得，不计入业绩调整'));
    const news=events.map(e=>eventScore(e)+' 分 · '+e.title+'；'+e.reason);
    if(!news.length)news.push(context.event_analysis?.status==='completed'?'本轮已采集并评估的证据中，没有达到展示门槛的相关事件；不代表全网没有事件。':'重要事件尚未完成本轮评估，暂不计入综合分；不代表没有利好或利空。');
    const market=[txt(panic.summary,'市场风险证据待补充。'),'市场状态：'+txt(regime.label||regime.mode,'尚未确定'),'恐慌分：'+(finite(panic.score)?num(panic.score,0)+'/100':'尚缺数据')];
    if(s.group==='overseas')market.push('风险约束口径：全站采用A股四大指数；此处不代表港股或美股当地大盘风险。');
    const balanced=s.score_model==='company_research_v2',b=s.score_breakdown||{},r=s.market_risk||{};
    if(balanced){
      trend.push('走势得分：'+num(b.trend?.points)+' / 30；仅按20日、60日收益与20日均线差打分。');
      for(const d of arr(b.trend?.details))trend.push(({'return_20d':'20日收益','return_60d':'60日收益','ma20_gap':'20日均线差'}[d.field]||d.field)+' '+pct(d.value)+'；映射 '+num(d.score)+'/100，走势内部权重 '+num((d.weight||0)*100,0)+'%。');
      earnings.unshift('基本面得分：'+num(b.fundamentals?.points)+' / 40；指标覆盖 '+num(b.fundamentals?.coverage_pct)+'%。',txt(b.fundamentals?.scope));
      for(const d of arr(b.fundamentals?.details))earnings.push(({'tr_yoy':'营收增长','netprofit_yoy':'净利增长','profitability':'盈利状态'}[d.field]||d.field)+'：中位映射 '+num(d.score)+'/100；有效 '+(d.count||0)+'/'+(d.sample_count||0)+' 家；基本面内部权重 '+num((d.weight||0)*100,0)+'%。');
      news.unshift('催化调整：'+(finite(b.catalysts?.observed_adjustment)?(b.catalysts.observed_adjustment>0?'+':'')+num(b.catalysts.observed_adjustment):'待评估')+'（−30～+30）；'+(b.catalysts?.points===null?'本批尚未完整评估，阶段分不入完整档位。':'已完成本批证据评估。'));
    }
    if(finite(r.score)||r.status){market.push('环境风险：'+num(r.score,0)+'/100，分数越高风险越高；'+txt(r.profile)+'；覆盖 '+num(r.coverage_pct,0)+'%。');
      for(const [key,label] of [['market','大盘'],['liquidity','流动性'],['macro','宏观']])market.push(label+'风险 '+(finite(r.components?.[key])?num(r.components[key]):'尚缺数据')+' / 100；权重 '+num((r.weights?.[key]||0)*100,0)+'%。');
      market.push(txt(r.scope),txt(r.note));}
    const score=balanced?[historical?'当前展示历史报告，请结合最新数据复核。':finite(s.score)?(s.score_status==='complete'?'板块研究分：':'阶段分：')+num(s.score)+'/'+s.score_maximum:'数据尚未达到评分条件，综合分保持未知。',
      '档位：'+txt(s.research_tier?.label,'待完成评估')+'；'+txt(s.research_tier?.reason),
      '基本面 '+num(b.fundamentals?.points)+'/40；走势 '+num(b.trend?.points)+'/30；事件催化 '+(finite(b.catalysts?.observed_adjustment)?(b.catalysts.observed_adjustment>0?'+':'')+num(b.catalysts.observed_adjustment):'待评估')+'（±30）。',
      '乐观条件：总分≥65，基本面≥28/40，且走势≥18/30或催化>0；证据完整。',
      s.score_status!=='complete'?'阶段分不进入完整档位；补齐证据后的数学可能范围 '+s.score_possible_range.map(v=>num(v)).join('～')+' / 100。':'',
      '大盘、流动性和宏观风险独立评分，不截断板块研究分。',s.score_method].filter(Boolean):[reference?'评分范围：仅参考指数走势；公司财务、业务与事件没有计入此分。':'',historical?'当前展示历史报告，请结合最新数据复核。':finite(s.score)?'当前'+(s.score_label||'综合研究分数')+'：'+num(s.score,0)+'/100':'数据尚未达到评分条件，综合分保持未知。',
      custom&&finite(s.technical_score)?'趋势分项先相加并限制为0–100，得到趋势基础分 '+num(s.technical_score)+'；再加业绩与重要事件调整，最后执行大盘风险上限。':'',
      ...Object.entries(s.score_components||{}).filter(([,v])=>finite(v)).map(([k,v])=>componentLabel(k)+'：'+num(v)),
      custom&&s.event_score_status==='unassessed'?'重要事件尚未评估，事件调整不计入；零调整不表示消息中性。':'',
      finite(s.score_cap)?'大盘风险约束：最高 '+s.score_cap+' 分':'',s.score_method||'评分公式待接入。'].filter(Boolean);
    const ids=rows.flatMap(r=>r.source_ids||[]);
    return [
      {id:'trend',title:money?'资金利率走势':convertible?'可转债走势':bond?'债券走势':researchLinked?'关联样本走势':custom&&resourceEquity?'资源企业股票走势':custom&&microcap?'小市值样本走势':custom?'龙头走势':'走势依据',value:txt(s.trend,'等待数据'),lines:trend,source_ids:custom?.constituents.flatMap(r=>r.source_ids)||s.sources?.map(r=>r.id)||[]},
      {id:'earnings',title:money?'资金利率依据':convertible?'信用与估值依据':bond?'利率与久期依据':'业绩支撑',value:money?'年化利率及基点变化':convertible?'信用与估值数据尚未接入':bond?'公司财务不适用':finance.filter(r=>r.sample_checks?.['披露日财务']===true).length+'/'+rows.length+' 份通过披露日财务核验',lines:money?['使用人民币隔夜Shibor年化利率及其变化；不使用公司财务。','高分仅表示利率相对平稳或资金趋宽；不代表投资回报或信用安全。']:convertible?[txt(s.asset_research?.financial_applicability,'可转债按债券资产研究，不以公司财务冒充资产指标。'),txt(s.asset_research?.coverage_note,'尚未取得发行人财务、评级、转股溢价、到期收益率与强赎条款；均不计入评分。')]:bond?['本方向按明确期限范围的债券指数走势研究，不使用股票公司财务。','实际久期、到期收益率及利率曲线未接入；不将指数期限范围冒充实际久期或信用评级。']:earnings.length?earnings:['本方向尚无有效公司财务样本，不补造业绩结论。'],source_ids:money||convertible||bond?s.sources?.map(r=>r.id)||[]:ids},
      {id:'events',title:'重要事件',value:events.length?events.length+' 项中等以上影响':'等待评估 / 暂无展示',lines:news,source_ids:events.flatMap(e=>e.source_ids||[]),events},
      {id:'market',title:'大盘风险',value:finite(r.score)?num(r.score,0)+'/100 · '+r.level:txt(regime.label||regime.mode,'资料待补充'),lines:market.filter(Boolean),source_ids:[...arr(r.source_ids),...arr(context.snapshot?.market).map(r=>r.source_id).filter(Boolean)]},
      {id:'score',title:s.score_label||'综合研究分数',value:finite(s.score)?num(s.score,balanced?2:0)+'/'+(balanced?s.score_maximum:100)+(balanced?' · '+txt(s.research_tier?.label):''):'尚未评分',lines:score,source_ids:[...ids,...arr(s.sources).map(r=>r.id),...arr(context.snapshot?.market).map(r=>r.source_id).filter(Boolean)]}
    ];
  }
  function componentLabel(k){return ({fundamental_points:'基本面得分',trend_points:'走势得分',catalyst_points:'事件催化调整',base:'基准',daily_change:'日涨跌',breadth:'样本涨跌广度',momentum_5d:'5日趋势',momentum_20d:'20日趋势',momentum_60d:'60日趋势',trend_20d:'20日均线',volatility_penalty:'波动扣分',drawdown_penalty:'回撤扣分',financial_adjustment:'业绩调整',event_adjustment:'重要事件调整',easing_5d:'5日利率变化',easing_20d:'20日利率变化',easing_60d:'60日利率变化',rate_volatility_penalty:'利率波动扣分',daily_tightening_penalty:'当日资金收紧扣分'})[k]||k;}
  function eventScheduleText(schedule={}) {
    if(schedule.mode==='interval')return '北京时间 · 每 '+schedule.interval_minutes+' 分钟研究（含休市日）';
    if(schedule.mode==='daily')return '北京时间 · 每天 '+schedule.daily_time+' 研究'+(schedule.end_time?'，'+schedule.end_time+' 停止新增请求':'');
    if(schedule.mode==='scheduled_interval')return '北京时间 · 每天 '+schedule.daily_time+' 至 '+(schedule.end_time||'未设置停止时间')+'，间隔 '+schedule.interval_minutes+' 分钟';
    return 'A 股交易日 · 北京时间 09:20 / 14:50';
  }
  function normalizeReport(r) {
    if (!r || r.research_scope !== 'sectors' || !Array.isArray(r.sector_analysis)) return null;
    const sectors=r.sector_analysis.map(s=>normalizeSector(r.report_stale===true?{...s,scarcity:null,severity:'normal',signal:'neutral',indicator_reason:''}:s)).filter(Boolean),scored=sectors.filter(s=>finite(s.score)).length;
    return {research_scope:'sectors', as_of:txt(r.as_of || r.snapshot?.as_of), sector_analysis:sectors,
      scarcity_access:{allowed:r.scarcity_access?.allowed===true,historical:r.scarcity_access?.historical===true},
      snapshot:{as_of:txt(r.snapshot?.as_of), market:arr(r.snapshot?.market), news:arr(r.snapshot?.news).filter(sectorEvidence).map(n=>({title:txt(n.title),url:safeUrl(n.url),published_at:txt(n.published_at),source:txt(n.source)})),
        sources:arr(r.snapshot?.sources).filter(sectorEvidence).map(cleanSource), warnings:arr(r.snapshot?.warnings).filter(v=>typeof v==='string'&&!/基金|净值|持仓/.test(v))},
      strategy:{panic:r.strategy?.panic || {}, regime:r.strategy?.regime || {}, summary:txt(r.strategy?.summary),risk_overview:r.strategy?.risk_overview||{},macro_evidence:r.strategy?.macro_evidence||{}},
      ai_research:r.ai_research && typeof r.ai_research === 'object' ? r.ai_research : {},
      event_analysis:normalizeEvents({...r.event_analysis,...(r.report_stale===true?{report_stale:true}:{})}),
      market_sentiment:normalizeMarketSentiment(r.market_sentiment,r.report_stale===true),
      market_liquidity:normalizeMarketLiquidity(r.market_liquidity,r.report_stale===true),
      company_evidence:normalizeCompanyEvidence(r.company_evidence),
      coverage:{...(r.coverage && typeof r.coverage === 'object' ? r.coverage : {}),scored_sector_count:scored}, score_method:txt(r.score_method || r.methodology?.score),
      summary:txt(r.summary || r.analysis?.summary).replace(/\d+个方向可评分/g,scored+'个方向可评分'), report_stale:r.report_stale === true};
  }
  const gapMessages={quote_source_failed:'关联行情来源采集失败。',quote_mapping_missing:'尚未接入与此方向准确对应的参考行情。',quote_not_returned:'行情来源返回成功，但未取得此方向的有效报价。',quote_stale:'已取得的行情过期，不能用于当前判断。',history_missing:'历史序列不足，暂不具备评分依据。',history_source_failed:'历史行情采集失败。',company_evidence_unavailable:'暂未取得本方向的有效公司行业与财务证据。',asset_source_missing:'尚未接入与此资产方向匹配的参考行情。'};
  const sourceStatusLabel=status=>({ok:'已取得',available:'已取得',verified:'已核验',partial:'部分取得',error:'采集失败',failed:'采集失败',timeout:'请求超时',stale:'数据过期',expired:'数据过期',unavailable:'未取得',empty:'无有效记录',not_configured:'未连接',not_installed:'未安装',unverified:'待核验',checking:'采集中'})[status]||'状态待确认';
  function sectorDataPresentation(sector,options={}) {
    const s=sector||{},historical=options.historical===true,gaps=arr(s.data_gaps).map(g=>({...g,message:txt(g.message)||gapMessages[g.code]||'本项数据尚未取得有效结果。'})),sourceMap=new Map();
    arr(options.sources).concat(arr(s.sources)).forEach(source=>{if(source?.id)sourceMap.set(source.id,source);});
    const ids=new Set(arr(s.sources).map(source=>source.id));gaps.forEach(g=>arr(g.source_ids).forEach(id=>ids.add(id)));
    const sources=[...ids].map(id=>sourceMap.get(id)).filter(Boolean),codes=new Set(gaps.map(g=>g.code));
    const failed=codes.has('quote_source_failed')||(!gaps.length&&sources.some(source=>['error','failed','timeout'].includes(source.status)));
    const stale=!historical&&(codes.has('quote_stale')||['stale','expired'].includes(s.status));
    const money=s.quote?.asset_type==='money_rate';
    const hasQuote=(money?finite(s.quote?.annual_rate_pct):finite(s.change_pct))&&!stale,hasScore=finite(s.score),unknownText=value=>!txt(value)||['*****','资料不足','资料待补充','数据待补充','数据不足','待补充','未取得'].includes(value);
    const quoteState=stale?'行情已过期':failed?'采集失败':codes.has('quote_not_returned')?'暂无有效行情':'行情未接入';
    const companyCount=Number.isInteger(options.companyCount)?Math.max(0,options.companyCount):0,eventCount=Number.isInteger(options.eventCount)?Math.max(0,options.eventCount):0,evidence=[];
    if(companyCount)evidence.push(companyCount+' 个公司样本');if(eventCount)evidence.push(eventCount+' 项重要事件');
    const daily=s.quote?.data_frequency==='daily',balanced=s.score_model==='company_research_v2';
    const scoreUnit=balanced?(historical?'历史 ':'')+(s.score_status==='complete'?'研究 / 100':s.score_maximum===70?'基础 / 70':'阶段 / 100'):(historical?'历史 / 100':s.score_scope==='reference_trend'?'参考走势 / 100':money?'资金利率 / 100':'/ 100');
    return {hasQuote,hasScore,scoreText:hasScore?s.score.toFixed(balanced?2:0):'未评分',scoreUnit:hasScore?scoreUnit:'',scoreNote:codes.has('score_model_unavailable')?'债券评分待建立':'评分依据不足',changeText:hasQuote?(money?num(s.quote.annual_rate_pct,3)+'%':pct(s.change_pct)):quoteState,changeLabel:money?'隔夜年化利率':s.custom_index?(s.id==='sector_brain_computer'?'关联样本涨跌':s.id==='commodities'?'资源股票样本涨跌':s.id==='style_microcap'?'小市值样本涨跌':'龙头样本涨跌'):daily?'最近交易日涨跌':'当日涨跌',
      dataTimeText:hasQuote&&daily&&s.as_of?'收盘数据 · '+s.as_of.slice(0,10):'',recoveryNote:txt(s.custom_index?.data_note),
      riskText:(hasQuote||hasScore)&&!unknownText(s.risk)?s.risk:'未评估',trendText:hasQuote&&!unknownText(s.trend)?s.trend:'未评估',
      subtitle:(txt(s.data_status_summary)||(gaps[0]?.message)||(!hasQuote?'此方向尚无有效直接行情。':s.quote?.name||s.trend||'已取得直接行情'))+(daily&&s.as_of?' · '+s.as_of.slice(0,10)+(money?' 利率观测':' 收盘'):'')+(!hasQuote&&evidence.length?' · 已有 '+evidence.join('、'):''),
      gaps,sources,referenceExpected:txt(s.reference_expected),evidenceSummary:evidence.length?'已有 '+evidence.join('、')+(s.custom_index?'，样本独立评分仍需满足共同历史与样本要求。':'，可查看对应经营或事件证据；板块整体涨跌与评分仍以有效行情为准。'):''};
  }
  function boardScoreGroup(s) {
    if(!finite(s.score))return {id:'unavailable',order:9,label:'待补数据',note:'保留已取得证据，缺口未补齐前不评分。'};
    if(s.score_model==='company_research_v2'){
      if(s.score_status==='complete')return {id:'company-complete',order:0,label:'公司研究 · 完整分 /100',note:'基本面、走势与本批事件均已评估，按完整研究分排序。'};
      if(s.score_maximum===70)return {id:'company-base',order:1,label:'公司研究 · 基础分 /70',note:'只比较基本面40分＋走势30分；事件仍待评估，不折算为完整研究分。'};
      return {id:'company-stage',order:2,label:'公司研究 · 阶段分 /100',note:'包含已评估部分催化，仍有证据待补齐，不进入完整档位。'};
    }
    if(s.score_scope==='reference_trend')return {id:'reference',order:3,label:'指数参考 · 走势分 /100',note:'只反映参考指数走势，不与公司研究分混排。'};
    if(s.quote?.asset_type==='convertible_bond')return {id:'convertible',order:4,label:'可转债研究 /100',note:'采用可转债专用模型。'};
    if(s.quote?.asset_type==='bond')return {id:'bond',order:5,label:'债券研究 /100',note:'采用债券专用模型。'};
    if(s.quote?.asset_type==='money_rate'||s.score_scope==='money_liquidity')return {id:'money',order:6,label:'资金环境 · 利率分 /100',note:'反映资金利率环境，不代表公司投资价值。'};
    return {id:'other',order:7,label:'其他研究 /100',note:'保留本方向原有评分口径。'};
  }
  function companyScoreView(s) {
    if(s.score_model!=='company_research_v2')return null;
    const b=s.score_breakdown||{},f=b.fundamentals||{},t=b.trend||{},e=b.catalysts||{},pending=[];
    if(!finite(f.points)||(finite(f.coverage_pct)&&f.coverage_pct<99.999))pending.push('财务待补齐');
    if(!finite(t.points)||(finite(t.coverage_pct)&&t.coverage_pct<99.999))pending.push('走势待补齐');
    if(!finite(e.points))pending.push(finite(e.observed_adjustment)?'事件部分评估':'事件待评估');
    const catalyst=finite(e.observed_adjustment)?(e.observed_adjustment>0?'+':'')+num(e.observed_adjustment)+(finite(e.points)?'':'（部分）'):'待评估';
    const gates=[finite(f.points)?f.points>=28?'基本面达28分':'基本面未达28分':'',finite(t.points)?t.points>=18?'走势达18分':'走势未达18分':''].filter(Boolean).join(' · ');
    return {label:!finite(s.score)?'数据待补齐':s.score_status==='complete'?s.research_tier.label:pending.join(' · ')||'证据待补齐',
      fundamentals:'基本面 '+num(f.points)+'/40',trend:'走势 '+num(t.points)+'/30',catalyst:'事件 '+catalyst,catalystTone:finite(e.observed_adjustment)?e.observed_adjustment>0?'positive':e.observed_adjustment<0?'negative':'':'',gates};
  }
  function boardResearchNotice(r,mode='score') {
    if(r?.report_stale)return '当前为历史报告，颜色和分数仅反映当时证据。';
    const a=r?.event_analysis||{},ai=r?.ai_research||{},status=a.status;
    const state=status==='scheduled'?'事件等待计划评估':status==='not_configured'?'事件分析未配置':status==='partial'?'本批事件仅部分评估':status==='completed'||status==='no_evidence'?'本批事件已评估':'事件评估尚未完成';
    const next=status==='scheduled'&&txt(ai.next_run_at)?'；下次 '+ai.next_run_at.slice(0,16).replace('T',' ')+'（北京时间）':'';
    return (mode==='score'?'按相同评分口径分组排序。':'当前按'+(mode==='change'?'当日涨跌':'名称')+'排序，各行保留独立评分口径。')+'基础/阶段分按当前原始分区间着色，70分制不放大；完整公司分按核验后的档位着色。'+state+next+'，未评估事件不按0分处理。';
  }
  function sortSectors(items, mode = 'score') {
    return [...items].sort((a,b)=> mode === 'name' ? a.title.localeCompare(b.title,'zh-CN')
      : mode === 'change' ? (finite(b.change_pct)?b.change_pct:-Infinity)-(finite(a.change_pct)?a.change_pct:-Infinity) || a.title.localeCompare(b.title,'zh-CN')
      : boardScoreGroup(a).order-boardScoreGroup(b).order || (finite(b.score)?b.score:-Infinity)-(finite(a.score)?a.score:-Infinity) || a.title.localeCompare(b.title,'zh-CN'));
  }
  function colorForScore(score,tier) {
    if(tier){const tones={optimistic:65,neutral:50,cautious:30,avoid:0};score=Object.hasOwn(tones,tier.id)?tones[tier.id]:null;}
    if (!finite(score)) return {color:'#93a8b8', background:'#132535', border:'#2d4253'};
    const colors = score >= 65 ? ['#9ef1c2','#123d2e','#297452']
      : score >= 50 ? ['#dfdca3','#393923','#7b7547'] : score >= 30 ? ['#edc18e','#402f22','#855b38']
      : ['#ffb5b2','#481d26','#8e3448'];
    return {color:colors[0], background:colors[1], border:colors[2]};
  }
  function colorForSector(s,historical=false) {
    if(historical||!finite(s.score))return colorForScore(null);
    if(s.score_model!=='company_research_v2')return colorForScore(s.score);
    if(s.score_status==='complete')return colorForScore(s.score,s.research_tier);
    // A provisional score keeps its original points and pending tier.
    return colorForScore(s.score);
  }
  function capabilityRows(value) {if(Array.isArray(value))return value.map((row,i)=>typeof row==='object'&&row?{id:txt(row.id||row.api_name||row.name,String(i)),...row}:{id:String(i),status:txt(row)});return value&&typeof value==='object'?Object.entries(value).map(([id,row])=>typeof row==='object'&&row?{id,...row}:{id,status:typeof row==='boolean'?(row?'available':'unavailable'):txt(row)}):[];}
  function normalizeDataConfig(value) {
    const input=value&&typeof value==='object'?value:{},aliases={stock_industry:'industry',financials:'financial'},byId=new Map();
    capabilityRows(input.capabilities).forEach(row=>{const id=aliases[row.id]||row.id;if(['industry','daily','financial'].includes(id))byId.set(id,{...row,id,status:txt(row.status,'unverified')});});
    const capabilities=[['industry','行业成分/行业标签'],['daily','代表公司日线'],['financial','财务数据']].map(([id,label])=>({id,label,status:'unverified',...(byId.get(id)||{})}));
    const verification=txt(input.verification||input.status,'unverified');
    return {provider:txt(input.provider||input.data_provider,'baostock'),installed:input.installed===true?true:input.installed===false?false:null,configured:input.configured===true,verification,error:txt(input.error),last_verified_at:txt(input.last_verified_at),capabilities};
  }
  const capabilityStatusLabels={available:'已取得',verified:'已取得',ok:'已取得',unverified:'尚未核验',checking:'检查中',empty:'未返回有效数据',timeout:'请求超时',error:'获取失败',failed:'获取失败',partial:'部分取得',not_installed:'未安装',unavailable:'未取得'};
  function dataStatusPresentation(config) {
    const c=config||normalizeDataConfig(null),status=c.verification,summary=c.capabilities.map(row=>row.label+'：'+(capabilityStatusLabels[row.status]||'尚未核验')).join('；');
    if(status==='not_installed'||c.installed===false)return {badge:'未安装 BaoStock',description:'本机尚未安装 BaoStock 客户端。',message:'请先安装 BaoStock，再重新检查连接。'};
    if(status==='checking')return {badge:'连接检查中',description:'BaoStock 已安装，正在分别核验行业、日线和财务接口。'+summary+'。',message:'正在检查数据服务；页面会自动更新结果。'};
    if(status==='timeout')return {badge:'连接超时',description:'BaoStock 已安装，本次请求超时。'+summary+'。',message:c.error||'连接超时，请稍后重新检查。'};
    if(status==='failed')return {badge:'连接检查未通过',description:'BaoStock 已安装，数据服务检查未通过。'+summary+'。',message:c.error||'连接检查失败，请稍后重试。'};
    if(status==='verified')return {badge:'连接已核验',description:'BaoStock 数据连接已核验。'+summary+'。',message:c.error||'连接检查完成，各项数据取得情况见下方。'};
    if(status==='partial')return {badge:'部分数据可用',description:'BaoStock 数据已部分接通。'+summary+'。',message:c.error||'部分数据已取得，其余项目仍需核验。'};
    return {badge:c.installed===true?'已安装 · 待检查':'待检查',description:(c.installed===true?'本机已安装 BaoStock，尚未确认数据服务可用。':'尚未确认 BaoStock 安装及连接状态。')+summary+'。',message:c.error||'无需 Token；点击检查数据连接。'};
  }
  function reasoningLabel(value){return value==='medium'?'中度推理':value==='xhigh'?'极高推理':'未配置';}
  function modelLabel(value,effort){return value==='gpt-6.1-sol'?'gpt-6.1-sol · '+reasoningLabel(effort):'AI研究模型';}
  const defaultCostControls={reuse_enabled:true,daily_request_limit:28,daily_token_limit:8000000};
  function costPresentation(value,ai={}) {
    const input=value&&typeof value==='object'?value:null,limits={...defaultCostControls,...input?.limits},whole=v=>Number.isInteger(v)&&v>=0?v:null,format=v=>v===null?'—':v.toLocaleString('zh-CN');
    const requests=whole(input?.requests),requestUnits=finite(input?.request_units)?input.request_units:requests,tokens=whole(input?.tokens_reserved),unknown=whole(input?.unknown_requests),reused=whole(ai.reused_count),requestLimit=whole(limits.daily_request_limit),tokenLimit=whole(limits.daily_token_limit);
    const unavailable=input?.status==='blocked'||input?.blocked===true;
    const blocked=ai.status==='budget_limited'||requestUnits!==null&&requestLimit!==null&&requestUnits>=requestLimit||tokens!==null&&tokenLimit!==null&&tokens>=tokenLimit;
    const kinds=Object.entries(input?.by_kind&&typeof input.by_kind==='object'?input.by_kind:{}).map(([kind,row])=>{const usage=row?.usage||row||{};return {label:({sector:'板块解读',sectors:'板块解读',sector_ai:'板块解读',event:'事件评估',events:'事件评估',event_ai:'事件评估'})[kind]||'其他调用',requests:format(whole(row?.requests)),prompt:format(whole(usage.prompt_tokens)),completion:format(whole(usage.completion_tokens))};});
    const warnings=[unavailable?'费用账本不可用，已暂停新增 AI 请求。'+txt(input.error):'',unknown>0?unknown+' 笔用量待核验预留，保留预算占用；不代表已扣费。':''].filter(Boolean);
    const multiplier=finite(input?.reasoning_multiplier)?input.reasoning_multiplier:1;
    return {status:unavailable?'blocked':blocked?'limited':input?'active':'loading',label:unavailable?'账本不可用 · 暂停请求':blocked?'今日额度已达上限':input?'费用保护已启用':'正在读取今日用量',requests:format(requests)+' 次（计费 '+(requestUnits===null?'—':requestUnits.toFixed(2))+' / '+format(requestLimit)+'）',tokens:format(tokens)+' / '+format(tokenLimit),reused:format(reused??0)+' 个板块',unknown:warnings.join(' '),kinds,multiplier,
      note:'Token 预算按请求前 UTF-8 字节保守预留，并在收到用量后核对；这是预算占用，不是人民币账单。分类仅反映可核验记录，历史汇总不一定能完整拆分；待核验预留不代表已扣费。'};
  }
  function aiActivityPresentation(config,live={},reportAi={}) {
    const ai=live.ai_research||reportAi,enabled=config?.configured&&config?.enabled&&config?.verification==='verified'&&config?.effective_enabled!==false;
    if(!enabled)return {title:'全自动 AI 板块研究',reinforcing:false};
    if(live.connection_error)return {title:'AI 连接状态待确认',reinforcing:false};
    if(live.ai_cost?.status==='blocked'||live.ai_cost?.blocked===true)return {title:'费用账本不可用，暂停新增 AI 请求',reinforcing:false};
    if(config.schedule?.mode==='market_sessions'&&live.ai_calendar&&live.ai_calendar.status!=='verified')return {title:'交易日历待核验',reinforcing:false};
    if(ai.status==='running'||live.status==='running'&&/AI|评估.*公告/.test(txt(live.stage)))return {title:'AI 正在研究板块',reinforcing:false};
    if(live.status==='error'||ai.terminal_error)return {title:'本轮 AI 研究需要检查',reinforcing:false};
    if(costPresentation(live.ai_cost,ai).status==='limited')return {title:'今日 AI 额度保护已生效',reinforcing:false};
    const titles={budget_limited:'今日 AI 额度保护已生效',input_too_large:'AI 请求已因体积超限拦截',error:'本轮 AI 研究需要检查',no_evidence:'AI 研究等待有效证据',data_unavailable:'AI 研究等待有效证据'};
    if(titles[ai.status])return {title:titles[ai.status],reinforcing:false};
    const previous=['completed','success'].includes(ai.status)?'上轮 AI 研究已完成。':ai.status==='partial'?'上轮 AI 研究已完成部分解读。':'';
    return {title:'正在强化分析',reinforcing:true,detail:previous+'整理已有证据并等待计划，此状态不会持续发起新的 AI 请求。'};
  }
  function researchAdvicePresentation(s,context={}) {
    let action='wait';const b=s.score_breakdown||{};
    if(!context.report_stale&&finite(s.score)){
      if(s.score_model==='company_research_v2'&&s.score_status==='complete'){
        action=s.score>=65&&b.fundamentals?.points>=28&&(b.trend?.points>=18||b.catalysts?.points>0)?'track':s.score>=50?'observe':s.score>=30?'cautious':'avoid';
      }else if(s.score_model!=='company_research_v2')action='reference';
    }
    const labels={track:'重点跟踪，纳入重点观察池',observe:'持续观察，等待证据改善',cautious:'谨慎研究，降低关注优先级',avoid:'暂予规避，当前证据不支持重点研究',wait:'等待证据补齐后复核',reference:'观察参考指标，结合公司证据复核'};
    const completed=!context.report_stale&&context.ai_research?.status!=='stale'&&s.ai_research_status==='completed'&&Boolean(s.ai_analysis),advice=s.ai_advice;
    const verified=completed&&advice?.action===action&&advice.reason&&advice.watch_points?.length;
    const detailed=verified&&advice.schema_version===2;
    return {action,label:(verified?'AI 研究建议：':'研究分层建议：')+labels[action],completed,detailed,
      summary:verified?advice.reason:completed?'AI 已完成证据解读，展开查看支持与反对理由。':'',
      watchPoints:verified?advice.watch_points:arr(s.next_steps),
      scope:verified?advice.scope:'',evidenceChain:detailed?advice.evidence_chain:[],actionPlan:detailed?advice.action_plan:[],scenarios:detailed?advice.scenarios:[],reviewConditions:detailed?advice.review_conditions:[],
      statusText:context.report_stale?'历史证据，仅供复盘；等待本轮 AI 研究。':verified?'AI 基于本轮证据解释建议，档位受确定性规则约束。':completed?'档位由评分规则确定；AI 解读展示在下方。':s.ai_research_status==='stale'||context.ai_research?.status==='stale'?'AI 解读待更新，暂不显示为当前建议。':'本板块尚未完成 AI 研究，请检查 API Key、计划及研究状态。'};
  }
  function researchSavedPresentation(sector={},context={}){
    if(sector.ai_research_status!=='completed'||!txt(sector.ai_analysis||sector.ai_reason).trim())return {saved:false,label:'',generatedAt:'',note:'',dataLabel:''};
    const format=value=>{if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$/i.test(value)||!Number.isFinite(Date.parse(value)))return '';const parts=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(value)).map(part=>[part.type,part.value]));return parts.year+'/'+parts.month+'/'+parts.day+' '+parts.hour+':'+parts.minute;};
    const generatedText=format(sector.ai_generated_at),dataText=format(context.as_of),dataDate=typeof context.as_of==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(context.as_of)?context.as_of.replaceAll('-','/'):'';
    return {saved:true,label:generatedText?'已保存 · 更新时间：'+generatedText+'（北京时间）':'已保存 · 更新时间：未记录（旧版报告）',generatedAt:generatedText?sector.ai_generated_at:'',note:sector.ai_reused||sector.ai_live_retained?'更新时间为 AI 原生成时间，复用、查看和刷新均不改变。':'更新时间为 AI 生成时间，查看和刷新不会改变。',dataLabel:'报告数据时间：'+(dataText?dataText+'（北京时间）':dataDate?dataDate+'（仅记录日期）':'未记录')};
  }
  function researchHistoricalAdvicePresentation(sector={},context={}){
    if(!context.report_stale||sector.ai_research_status!=='completed'||!txt(sector.ai_analysis||sector.ai_reason).trim())return null;
    const advice=normalizeAiAdvice(sector.ai_advice,sector.score_model==='company_research_v2'?'company':'reference',arr(sector.evidence_ids));if(advice?.schema_version!==2)return null;
    return {historical:true,label:'历史建议 · 仅供复盘',notice:'以下为生成时保存的历史建议，用于核对当时的依据与条件，不作为当前操作依据。',scope:advice.scope,evidenceChain:advice.evidence_chain,actionPlan:advice.action_plan,scenarios:advice.scenarios,reviewConditions:advice.review_conditions};
  }
  function aiServicePresentation(s,context={},runtime={}) {
    const config=runtime.config,live=runtime.state||{},ai=live.ai_research||context.ai_research||{};
    const advice=researchAdvicePresentation(s,{...context,ai_research:ai.status==='stale'?ai:context.ai_research}),next=txt(live.ai_next_run_at||config?.ai_next_run_at||ai.next_run_at);
    const nextText=next&&Number.isFinite(Date.parse(next))?new Date(next).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'long',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false}):'';
    const generatedAt=txt(s.ai_generated_at),generatedText=generatedAt&&Number.isFinite(Date.parse(generatedAt))?new Date(generatedAt).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'long',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false}):'';
    const eventStatus=context.event_analysis?.status,eventNotice=eventStatus==='error'?'事件评估本轮未完成；当前解读不代表已完成事件核验。':eventStatus==='partial'?'事件仅完成部分评估，未评估的候选仍需补齐。':'';
    const result=(status,tag,title,detail,extra={})=>({status,tag,title,detail,nextRunAt:next,nextText,eventNotice,completed:advice.completed,subscribe:false,actionLabel:'查看研究计划',...extra});
    if(s.ai_access?.status==='locked'){const cost=s.ai_access.cost===1.5?1.5:1;return result('locked',s.ai_access.can_unlock?'订阅已开通':'订阅服务','本期 AI 解读待解锁',s.ai_access.can_unlock?'本份解读消耗 '+cost+' 点研究额度；重复查看本份解读不再扣点。':['active','exhausted'].includes(s.ai_access.subscription_status)?'本份解读需 '+cost+' 点，当前研究额度不足；请联系客服补充额度。':'请联系客服订阅或续订，由管理员为您的账号开通服务及额度。',{completed:false,subscribe:!s.ai_access.can_unlock,unlockable:s.ai_access.can_unlock});}
    if(s.ai_access?.status==='not_ready'){const effort=s.ai_access.preferred_reasoning_effort,label=effort==='medium'?'中度推理':effort==='xhigh'?'极高推理':'';return result('pending',label?'已选择 · '+label:'等待您开始研究',label?label+'解读待生成':'本期 AI 解读尚未生成','在关注卡片点击“生成 AI 研究”后才调用模型；生成成功后自动保存至研究记录，刷新后可恢复任务。关注板块、查看行情或切换深度都不触发个人 AI 研究。生成有效解读后按所选档位扣点。',{completed:false,nextRunAt:'',nextText:'',actionLabel:'选择我的推理深度',personalPreference:true});}
    if(!config)return live.config_error?result('offline','状态待确认','AI 配置暂未读取成功','恢复连接后会自动核验，请到 AI 设置查看连接状态。',{actionLabel:'查看 AI 设置'}):result('loading','连接确认中','正在读取 AI 服务状态','稍后自动更新连接与研究计划。',{actionLabel:'查看 AI 设置'});
    if(!config.configured)return result('unconfigured','尚未连接','连接 AI，解读关注板块','结合业务、财务、走势和事件证据，生成研究建议及风险条件。',{subscribe:true,actionLabel:'订阅查看 ↗'});
    if(config.verification==='failed')return result('error','连接需修复','API Key 校验未通过',txt(config.error,'请在 AI 设置中检查密钥、模型权限与账户余额。'),{actionLabel:'检查 AI 连接'});
    if(config.verification!=='verified')return result('unverified','等待校验','API Key 已保存，等待连接校验','连接检查通过后，才会按计划自动研究。',{actionLabel:'校验 AI 连接'});
    if(!config.enabled||config.effective_enabled===false)return result('disabled','已连接 · 未启用','自动研究当前关闭','在 AI 设置中启用自动研究并保存计划。',{actionLabel:'启用自动研究'});
    const calendar=live.ai_calendar||config.ai_calendar;
    if(config.schedule?.mode==='market_sessions'&&calendar&&calendar.status!=='verified')return result('blocked','已连接 · 计划暂停','交易日历待核验',txt(calendar.reason,'交易日历核验通过后恢复自动研究。'));
    if(live.connection_error)return result('offline','状态待确认','暂时无法取得后台状态','已保存的连接配置仍在；恢复连接后自动更新研究进度。');
    if(ai.status==='running'||live.status==='running'&&/AI|评估.*公告/.test(txt(live.stage)))return result('running','已连接 · 正在更新','AI 正在分析研究证据',txt(live.stage,'报告完成后自动展示解读、建议与风险。'));
    if(advice.completed&&s.ai_live_retained)return result('completed','沿用上次 AI 解读',advice.label,advice.summary+(generatedText?' 原解读：'+generatedText+'。':'')+' 行情与评分已独立更新，本次未重新调用 AI。',{actionLabel:'查看更新计划'});
    if(advice.completed)return result('completed',s.ai_reused?'证据未变 · 复用解读':'AI 解读已生成',advice.label,advice.summary+(s.ai_reused&&generatedText?' 原解读：'+generatedText+'。':''),{actionLabel:'查看更新计划'});
    if(ai.status==='budget_limited')return result('budget_limited','已连接 · 额度保护','今日 AI 额度已用完','暂停新增请求，行情与量化研究继续更新；次日恢复额度，已有解读仍可查看。',{actionLabel:'查看费用保护'});
    if(ai.status==='input_too_large')return result('input_too_large','已连接 · 请求已拦截','本批证据超出请求限额','尚未发送超限请求；请检查研究范围或请求体积，避免无效费用。',{actionLabel:'查看研究状态'});
    const ownError=arr(ai.errors).find(row=>arr(row?.sector_ids).includes(s.id));
    if(ownError||ai.status==='error'||ai.terminal_error)return result('error','已连接 · 研究异常','本板块 AI 解读未完成',txt(ownError?.message||ai.error,'本轮未返回可核验的解读，量化研究数据仍可查看。'),{actionLabel:ai.terminal_error?'检查 AI 连接':'查看研究状态'});
    if(context.report_stale)return result('stale','已连接 · 待更新','历史解读待更新',nextText?'按计划取得新证据后生成解读，历史结论仅供复盘。':'等待新一轮行情与公司证据。');
    if(ai.status==='no_evidence'||ai.status==='data_unavailable'||!['ok','partial'].includes(s.status))return result('no_evidence','已连接 · 等待证据','本板块证据待补齐','有效行情或公司证据补齐后再生成解读，避免无依据的建议。');
    if(ai.status==='window_closed')return result('scheduled','已连接 · 等待下轮','正在强化分析',txt(ai.stopped_reason,'整理已有证据并等待下一计划时段。')+' 此状态不会持续发起新的 AI 请求。'+(nextText?'下次实际 AI 调用：'+nextText+'。':''));
    if(['completed','success','partial'].includes(ai.status))return result('pending','已连接 · 等待解读','正在强化分析','本板块尚无有效 AI 解读；整理已有证据并等待下轮，不持续发起新的 AI 请求。'+(nextText?'下次实际 AI 调用：'+nextText+'。':''));
    return result('scheduled','已连接 · 等待计划','正在强化分析','整理已有证据并等待计划，此状态不会持续发起新的 AI 请求。'+(nextText?'下次实际 AI 调用：'+nextText+'。':'下次实际 AI 调用：等待后台计划。'));
  }
  // Source status describes retrieval only. Freshness remains visible as the original data date.
  function sourceRecordState(source) {
    return source?.status==='ok'?'ok':source?.status==='partial'?'partial':['error','missing','unavailable','stale'].includes(source?.status)?'attention':'unknown';
  }
  function sourceOverview(records) {
    const result={total:0,ok:0,partial:0,attention:0,unknown:0};
    for(const source of arr(records)){result.total++;result[sourceRecordState(source)]++;}return result;
  }
  function sourceIssueOverview(records) {
    const result={timeout:0,http:0,connection:0,coverage:0,other:0};
    for(const source of arr(records)){
      if(!['attention','partial'].includes(sourceRecordState(source)))continue;
      const error=txt(source.error);
      const kind=/超时|timeout|timed out|总时间超限/i.test(error)?'timeout':/HTTPError|HTTP\s*\d{3}|HTTP状态/i.test(error)?'http':/连接失败|连接中断|连接或格式|格式变化|返回格式|connection|disconnect/i.test(error)?'connection':source.status==='stale'||/收盘|日期|过期|历史|覆盖|序列不足/.test(error)?'coverage':'other';
      result[kind]++;
    }
    return result;
  }
  function selectSourceRecords(records,query='',filter='all') {
    const search=String(query).trim().toLocaleLowerCase('zh-CN');
    return arr(records).filter(source=>(filter==='all'||sourceRecordState(source)===filter)&&(!search||[source?.name,source?.id,source?.error].filter(Boolean).join(' ').toLocaleLowerCase('zh-CN').includes(search)));
  }
  const api = {sourceRecordState,sourceOverview,sourceIssueOverview,selectSourceRecords,costPresentation,aiActivityPresentation,aiServicePresentation,researchAdvicePresentation,researchSavedPresentation,researchHistoricalAdvicePresentation,modelLabel, normalizeSector, normalizeReport, normalizeEvents, eventSetupNotice, normalizeCompanyEvidence, normalizeCustomIndex, normalizeMarketSentiment, sentimentPresentation, normalizeMarketLiquidity, liquidityPresentation, researchPanels, eventScheduleText, eventTone, eventScore, eventIndicator, sectorIndicator, sectorDataPresentation, sourceStatusLabel, normalizeDataConfig, dataStatusPresentation, boardScoreGroup, companyScoreView, boardResearchNotice, sortSectors, colorForScore, colorForSector, pct, UNKNOWN};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.SectorResearch = api;
  if (typeof document === 'undefined') return;

  const $ = s => document.querySelector(s);
  const el = (tag, text, cls) => { const n=document.createElement(tag); if(text!==undefined)n.textContent=text; if(cls)n.className=cls; return n; };
  function indicatorNode(indicator){const icon=el('i',indicator.symbol,'sector-indicator '+indicator.className);icon.title=indicator.reason||indicator.label;icon.setAttribute('aria-label',indicator.label+(indicator.reason?'：'+indicator.reason:''));return icon;}
  const read = (key, fallback) => { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } };
  const write = (key,v) => { try { localStorage.setItem(key,JSON.stringify(v)); } catch {} };
  // The sector workspace never restores the former product watchlists or reports.
  ['fundpilot_history_v3','fundpilot_history_v2','fundpilot_codes_v3','fundpilot_constraints_v3','fundpilot_prefs','fundpilot_ds'].forEach(k=>{try{localStorage.removeItem(k);}catch{}});
  let report=null, state={}, config=null, selected=null, group='all', query='', sort='score', reportVersion='', polling=false, timer=null, settingsDirty=false, configBusy=false, dataConfig=null, dataBusy=false, dataLoading=false, dataTimer=null, dataPollDelay=1500, reportNeedsRefresh=false, viewingHistory=false, aiViewSignature='',personalProjectionRevision=0;
  let onlyScarcity=false;
  const cloudMode=Boolean(root.FundPilotCloud);
  const historyItem=value=>cloudMode&&value?.cloud_record?value:normalizeReport(value);
  let histories=cloudMode?[]:arr(read('fundpilot_sector_history_v1',[])).map(normalizeReport).filter(Boolean).slice(0,20);
  const historyStore=root.SectorHistory.createHistoryStore();
  let historyRevision=0,historyCleared=false,cloudHistoryReady=!cloudMode;
  const historyLoaded=historyStore.load().then(value=>{cloudHistoryReady=true;if(!historyCleared){const seen=new Set();histories=[...histories,...value.items.map(historyItem).filter(Boolean)].filter(r=>!seen.has(r.as_of)&&(seen.add(r.as_of),true)).sort((a,b)=>b.as_of.localeCompare(a.as_of)).slice(0,20);}renderHistory();if(cloudMode)setText('historyStorageStatus',root.FundPilotCloud?.mode==='local'?'个人记录已从后台加载，仅当前账号可见。':'个人记录已从云端加载，仅当前账号可见。');}).catch(()=>{if(cloudMode)setText('historyStorageStatus','个人记录加载失败，请刷新页面重试。');});
  async function saveHistory(){const revision=++historyRevision;try{await historyLoaded;if(!cloudHistoryReady)throw new Error('个人记录尚未从后台加载，请刷新页面后重试。');const result=await historyStore.save(histories);if(revision!==historyRevision)return;setText('historyStorageStatus',['cloud','account'].includes(result.backend)?'最近 '+result.saved_count+' 份记录已保存到您的'+(result.backend==='cloud'?'云端':'网站')+'账号。':result.backend==='memory'?'本机存储不可用，记录仅在本次打开期间保留。':result.limited?'本机存储空间不足：重开网页后可恢复最近 '+result.saved_count+' 份；其余仅在本次打开期间保留。':'最近 '+result.saved_count+' 份报告已保存到本机，最多保留 20 份。');return true;}catch(error){setText('historyStorageStatus','记录保存失败：'+error.message);return false;}}
  async function refreshResearchHistory(){
    if(!cloudMode)return true;const revision=++historyRevision;
    try{await historyLoaded;const value=await historyStore.load();if(revision!==historyRevision)return false;cloudHistoryReady=true;historyCleared=false;const seen=new Set();histories=value.items.map(historyItem).filter(Boolean).filter(row=>!seen.has(row.as_of)&&(seen.add(row.as_of),true)).slice(0,20);renderHistory();setText('historyStorageStatus','研究结果已自动保存，个人研究记录已从后台更新。');return true;}
    catch{if(revision===historyRevision)setText('historyStorageStatus','研究结果已保存，记录列表暂未同步；稍后可重新加载查看。');return false;}
  }

  let toastTimer;
  function toast(v) { $('#toast').textContent=v; $('#toast').classList.add('show'); clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('#toast').classList.remove('show'),4200); }
  function stamp(v) { if(!v)return UNKNOWN; const d=new Date(v); return Number.isFinite(d.getTime()) ? (/^\d{4}-\d{2}-\d{2}$/.test(v)?v:d.toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})) : UNKNOWN; }
  function compactDate(v) {return /^\d{8}$/.test(v)?v.slice(0,4)+'-'+v.slice(4,6)+'-'+v.slice(6):v?stamp(v):UNKNOWN;}
  function setText(id,v) { $('#'+id).textContent=v; }
  function link(label,url) { const href=safeUrl(url), n=el(href?'a':'span',label); if(href){n.href=href;n.target='_blank';n.rel='noopener noreferrer';} return n; }
  function view(id) { document.querySelectorAll('.view').forEach(v=>v.classList.toggle('on',v.id===id)); document.querySelectorAll('[data-view]').forEach(b=>{b.classList.toggle('active',b.dataset.view===id);b.setAttribute('aria-current',b.dataset.view===id?'page':'false');});if(typeof window!=='undefined')window.scrollTo({top:0,behavior:'instant'});if(id==='settings'){dataPollDelay=1500;loadDataConfig();}else clearTimeout(dataTimer); }
  document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>view(b.dataset.view));
  document.querySelectorAll('[data-go-settings]').forEach(b=>b.onclick=()=>view('settings'));
  function clock() { const now=new Date();setText('today',now.toLocaleDateString('zh-CN',{timeZone:'Asia/Shanghai',dateStyle:'full'}));setText('beijing',now.toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})); }
  clock();setInterval(clock,1000);
  function applyTone(node, sector) {const c=colorForSector(sector,report.report_stale);node.style.setProperty('--sector-tone',c.color);node.style.setProperty('--sector-bg',c.background);node.style.setProperty('--sector-border',c.border);}
  function list(title, items, fallback) { const section=el('div',undefined,'sector-detail-section');section.append(el('h4',title));const ul=el('ul');(items.length?items:[fallback]).forEach(t=>ul.append(el('li',t)));section.append(ul);return section; }
  function eventCard(event,index) {
    const card=el('article',undefined,'sector-event event-'+eventTone(event)),top=el('div',undefined,'sector-event-top'),heading=el('div',undefined,'sector-event-heading');
    heading.append(el('span',String(index+1).padStart(2,'0'),'event-rank'),link(event.title,event.url));
    const score=el('div',undefined,'event-impact');score.setAttribute('aria-label',({positive:'利好',negative:'利空',mixed:'双向影响'})[event.direction]+'，影响分 '+eventScore(event));score.append(el('strong',eventScore(event)),el('span',({positive:'利好',negative:'利空',mixed:'双向影响'})[event.direction]+' · '+(event.impact_level==='high'?'强影响':'中等影响')));const indicator=eventIndicator(event);if(indicator){const tag=el('b',undefined,'event-signal '+indicator.className);tag.title=indicator.reason||indicator.label;tag.append(indicatorNode(indicator),document.createTextNode(indicator.label));score.append(tag);}top.append(heading,score);card.append(top);
    if(event.sector_labels.length){const tags=el('div',undefined,'event-sectors');event.sector_labels.forEach(name=>tags.append(el('span',name)));card.append(tags);}
    card.append(el('p',event.reason,'event-reason'));
    if(event.verification&&scarcityUI?.verificationDetail){const verification=el('details',undefined,'event-facts');verification.append(el('summary','证据研判 · '+event.verification.label+(event.evidence_usable?'':' · 暂不计入事件催化')),scarcityUI.verificationDetail(event.verification));card.append(verification);}
    if(event.facts.length){const details=el('details',undefined,'event-facts');details.append(el('summary','查看事实依据与评分维度'));event.facts.forEach(f=>details.append(el('p',f)));const names={materiality:'经营影响',breadth:'覆盖范围',duration:'持续性',certainty:'证据明确程度'},dimensions=Object.entries(event.dimensions).map(([k,v])=>names[k]+' '+v+'/5');if(dimensions.length)details.append(el('p',dimensions.join(' · ')));card.append(details);}
    const meta=el('div',undefined,'event-meta');meta.append(el('span',event.source_name||'公开来源'),el('time','发布于 '+stamp(event.published_at)));if(report?.report_stale||report?.event_analysis.status==='stale'||report?.event_analysis.status==='expired')meta.append(el('span','历史评估','event-historical'));card.append(meta);return card;
  }
  function eventList(box,events,emptyText) {box.replaceChildren();events.forEach((event,index)=>box.append(eventCard(event,index)));if(!events.length)box.append(el('p',emptyText,'event-empty'));}
  function renderEvents() {
    const analysis=report?.event_analysis||normalizeEvents(null),events=analysis.events;
    setText('eventCount',events.length+' 项中等及以上事件');
    const coverage=$('#eventCoverage');if(coverage){coverage.hidden=!analysis.summary;coverage.textContent=analysis.summary;}
    setText('eventStatus',report?.report_stale||['stale','expired'].includes(analysis.status)?'正在展示历史事件评估，请按发布时间和报告时间复核。':analysis.status==='not_configured'?eventSetupNotice(analysis):analysis.status==='error'?'本轮事件评估未完成：'+(analysis.error||'等待下一次有效研究。'):analysis.status==='data_unavailable'?'本轮公开公告或官方政策采集未完成，尚不能确认重要事件。':analysis.status==='scheduled'?'事件研究等待下一次交易日时段，当前不补造事件影响分。':analysis.summary||'仅保留影响分绝对值 ≥ '+analysis.threshold+' 的事件；利好绿色正分，利空红色负分，双向影响单独标注。影响分不是涨跌概率。');
    eventList($('#eventList'),events,analysis.status==='completed'?'本轮没有达到中等影响标准的事件。':'暂无完成评估的重要事件；待按计划采集可靠公告、政策及公司证据后更新。');
    setText('eventAsOf',(['completed','stale','expired'].includes(analysis.status)?'事件报告时间：':'事件状态更新时间：')+stamp(analysis.as_of||report?.as_of)+' · '+eventScheduleText(config?.schedule||state.ai_schedule));
    setText('eventScheduleLabel',eventScheduleText(config?.schedule||state.ai_schedule)+'；只展示中等及以上影响事件。');
    const method=$('#eventMethod');if(method)method.textContent=analysis.method||'事件影响分用于比较事件对相关板块的影响强度；不代表上涨概率或收益预测。';
  }
  function renderCompanyEvidence(panel,sector) {
    const evidence=report.company_evidence,rows=evidence.sector_leaders[sector.id]||[],section=el('section',undefined,'sector-company-evidence');
    const microcap=sector.id==='style_microcap';
    const heading=el('div',undefined,'company-evidence-head'),title=el('div');title.append(el('span','COMPANY EVIDENCE','company-eyebrow'),el('h4',microcap?'小市值优选研究样本':'龙头与优选研究样本'));heading.append(title,el('span',rows.length?rows.length+' 家研究样本':'等待有效样本','company-count'));section.append(heading);
    section.append(el('p',microcap?'在国证A股核验池内按市值从小到大选样，再核对财务与近期走势。有限样本表现不等同全市场微盘股。':'核对归属、行情、财务与近期走势，再筛选研究对象。样本表现不等同整个板块。','company-section-intro'));
    const selection=evidence.sample_selection?.[sector.id];
    if(selection){
      const stages=el('div',undefined,'company-selection-stages');stages.setAttribute('aria-label','样本筛选概览');
      for(const [key,label] of [['membership_count','归属池'],['quoted_count','有效报价'],['candidate_count','本轮候选'],['ready_count','数据完整'],['selected_count','最终选入']]){
        const step=el('div',undefined,'company-selection-step'),value=selection[key],number=el('strong',finite(value)?String(value):'—');number.append(el('small','家'));step.append(el('span',label),number);stages.append(step);
      }section.append(stages);
      if(selection.pending.length){const pending=el('details',undefined,'company-pending');pending.append(el('summary',selection.pending.length+' 家候选待核验 · 查看缺口'));selection.pending.forEach(r=>pending.append(el('p',r.name+' '+r.ts_code+'：'+r.reason,'field-help')));section.append(pending);}
    }
    if(!rows.length){const unconfigured=evidence.status==='not_configured'&&!dataConfig?.configured;section.append(el('p',unconfigured?'等待连接 BaoStock 数据源，取得行业成分及财务数据后核对代表公司；当前不代表该板块没有龙头。':'本份报告尚未取得该板块的有效公司样本。需继续核对行业归属与经营证据，不能据此判断该板块没有龙头。','field-help'));if(unconfigured){const button=el('button','检查 BaoStock 连接 ↗','btn');button.type='button';button.onclick=()=>view('settings');section.append(button);}panel.append(section);return;}
    const selectionMethod=microcap?[sector.custom_index?.scope,sector.custom_index?.method].filter(Boolean).join(' '):evidence.selection_method;
    const method=el('details',undefined,'company-selection-method');method.append(el('summary','查看筛选方法 · 最多 '+MAX_COMPANY_SAMPLES+' 家'),el('p',selectionMethod||'按已取得的行业归属和交易数据选择代表样本；业务龙头身份须有经营证据支持。','field-help'));section.append(method);
    const grid=el('div',undefined,'company-sample-grid'),sourceMap=new Map([...report.snapshot.sources,...evidence.sources].map(s=>[s.id,s]));
    rows.forEach(row=>{
      const card=el('article',undefined,'company-sample'),header=el('div',undefined,'company-sample-header'),name=el('div'),role=el('span',microcap?'小市值代表样本':row.leader_verified?'已核验业务龙头':'行业代表样本','company-role');
      name.append(el('b',row.name),el('small',row.ts_code));role.dataset.verified=String(row.leader_verified);header.append(name,role);card.append(header);
      if(row.industry)card.append(el('p',row.industry,'company-industry'));
      const quoteLabel=row.quote.data_kind==='daily_close'||!row.quote.is_intraday?'收盘':'行情';card.append(el('p',(report.report_stale?'历史':'')+quoteLabel+' · '+compactDate(row.quote.trade_date||row.as_of),'company-quote-date'));
      const metrics=el('div',undefined,'company-metrics company-quote-metrics');
      const quoteFields=[[row.quote.close_kind==='forward_adjusted_close'?'前复权收盘参考值':'收盘价',finite(row.quote.close)?num(row.quote.close)+' '+({CNY:'元',HKD:'港元',USD:'美元'}[row.quote.currency]||'（币种未核验）'):'—'],['日涨跌',finite(row.quote.pct_chg)?pct(row.quote.pct_chg):'—'],['换手率',finite(row.market_metrics.turnover_rate)?num(row.market_metrics.turnover_rate)+'%':'—'],['量比',finite(row.market_metrics.volume_ratio)?num(row.market_metrics.volume_ratio):'—']];
      quoteFields.forEach(([label,value],index)=>{const cell=el('div');cell.append(el('span',label),el('b',value));if(index===1)cell.dataset.direction=report.report_stale?'historical':row.quote.pct_chg>0?'up':row.quote.pct_chg<0?'down':'flat';if(value==='—')cell.title='本项数据尚未取得';metrics.append(cell);});card.append(metrics);
      const checks=el('div',undefined,'company-checks');checks.setAttribute('aria-label','数据核验结果');
      for(const [key,label] of [['业务或成分归属','归属'],['有效报价','行情'],['披露日财务','财务'],['近期61日走势','61日走势']]){
        const passed=row.sample_checks[key]===true,known=typeof row.sample_checks[key]==='boolean',badge=el('span',(passed?'✓ ':'… ')+label,'company-check');badge.dataset.status=passed?'passed':'pending';badge.title=key+'：'+(passed?'已通过':known?'待补齐':'尚未核验');badge.setAttribute('aria-label',badge.title);checks.append(badge);
      }card.append(checks);
      if(!row.leader_verified)card.append(el('p',microcap?'有限小市值样本，不能代表全市场微盘股。':'行业代表样本，业务龙头身份尚未核验。','company-limitation'));
      const membership=Object.values(Object.fromEntries(Object.entries(row.membership_evidence).filter(([k])=>['l1_name','l2_name','l3_name'].includes(k)))).filter(Boolean),basis=el('details',undefined,'company-basis');
      basis.append(el('summary','归属与入选依据'),el('p','归属依据：'+(membership.length?membership.join(' → '):'尚未取得'),'company-membership'));if(row.role)basis.append(el('p',row.role,'field-help'));if(row.selection_basis)basis.append(el('p',row.selection_basis,'field-help'));card.append(basis);
      if(row.membership_evidence.snapshot_date)basis.append(el('p','归属名单日期：'+compactDate(row.membership_evidence.snapshot_date),'field-help'));
      if(row.membership_evidence.published_date)basis.append(el('p','归属证据发布：'+compactDate(row.membership_evidence.published_date),'field-help'));
      const details=el('details',undefined,'company-financials'),f=row.financials||{};
      details.append(el('summary',row.financials?row.sample_checks['披露日财务']===true?'已核验财务 · 查看报告期':'财务数据 · 待核验':'财务数据待取得'));
      details.append(el('p','报告期：'+compactDate(f.end_date)+' · 披露日期：'+compactDate(f.ann_date),'field-help'));
      if(row.financials&&row.sample_checks['披露日财务']!==true)details.append(el('p','财务核验尚未通过，不能视为已核验业绩依据。','company-limitation'));
      const financials=el('div',undefined,'company-metrics');[['营收同比',finite(f.tr_yoy)?pct(f.tr_yoy):'—'],['净利润同比',finite(f.netprofit_yoy)?pct(f.netprofit_yoy):'—'],['ROE',finite(f.roe)?num(f.roe)+'%':'—'],['每股收益',finite(f.eps)?num(f.eps)+' '+({CNY:'元',HKD:'港元',USD:'美元'}[f.currency]||'（币种未核验）'):'—']].forEach(([label,value])=>{const cell=el('div');cell.append(el('span',label),el('b',value));financials.append(cell);});details.append(financials);if(f.currency_note)details.append(el('p',f.currency_note,'field-help'));if(row.financials_note)details.append(el('p',row.financials_note,'field-help'));card.append(details);
      const refs=el('div',undefined,'company-sources');row.source_ids.forEach(id=>{const source=sourceMap.get(id);if(source)refs.append(link(source.name||id,source.url));});if(refs.childNodes.length){const sources=el('details',undefined,'company-source-details');sources.append(el('summary','查看数据来源 · '+refs.childNodes.length+' 项'),refs);card.append(sources);}grid.append(card);
    });section.append(grid);panel.append(section);
  }
  function renderIndependentIndex(panel,s) {
    const index=s.custom_index;if(!index)return;
    const section=el('section',undefined,'independent-index');
    const head=el('div',undefined,'independent-index-head');head.append(el('span',s.id==='sector_brain_computer'?'独立编制 · 研究关联样本分析':s.id==='commodities'?'独立编制 · 资源企业股票样本分析':s.id==='style_microcap'?'独立编制 · 小市值样本分析':'独立编制 · 龙头样本分析','independent-index-tag'),el('small',index.is_intraday?'盘中样本快照':'最近收盘样本'));section.append(head);
    const info=el('div',undefined,'independent-index-stats');[['样本指标点位',num(index.value)],['等权样本',index.sample_count+' 只'],['共同历史',index.history_count+' 日'],['历史起点',index.base_date||'等待日线']].forEach(([label,value])=>{const n=el('div');n.append(el('span',label),el('strong',value));info.append(n);});section.append(info);
    if(index.history.length>1){const points=index.live_point?[...index.history.filter(p=>p.date!==index.live_point.date),index.live_point]:index.history,values=points.map(r=>r.value),low=Math.min(...values),high=Math.max(...values),range=high-low||1;
      const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 600 110');svg.setAttribute('role','img');svg.setAttribute('aria-label','当前公司样本等权指标回溯走势，从'+index.base_date+'至'+(index.live_point?.date||index.history_end)+(index.live_point?'（末点为盘中估值）':'')+'；起点100，非官方指数或回测收益');svg.setAttribute('class','independent-index-chart');
      const line=document.createElementNS('http://www.w3.org/2000/svg','polyline');line.setAttribute('points',points.map((r,i)=>(10+i*580/(points.length-1)).toFixed(2)+','+(100-(r.value-low)/range*85).toFixed(2)).join(' '));line.setAttribute('fill','none');line.setAttribute('stroke','currentColor');line.setAttribute('stroke-width','2.5');svg.append(line);section.append(svg);}
    const samples=el('div',undefined,'independent-index-members');index.constituents.forEach(r=>{const n=el('div');n.append(el('b',r.name),el('small',r.code),el('strong',num(r.weight_pct)+'%'),el('small','归属核对日期 '+r.membership_date));samples.append(n);});section.append(samples,el('p',index.scope+' 历史起点100，采用当前样本回溯；换样后重算，不与旧组合拼接。','field-help'));panel.append(section);
  }
  function renderResearchPanels(panel,s) {
    const section=el('section',undefined,'research-dimensions');section.setAttribute('aria-label','研究结论与证据');
    const sourceMap=new Map([...report.snapshot.sources,...report.company_evidence.sources].map(r=>[r.id,r]));
    researchPanels(s,report).forEach((item,index)=>{const d=el('details',undefined,'research-dimension dimension-'+item.id),summary=el('summary');
      const title=el('span',undefined,'dimension-title');title.append(el('small','0'+(index+1)),el('b',item.title));summary.append(title,el('span',item.value,'dimension-value'),el('span','查看依据 +','dimension-action'));d.append(summary);
      const body=el('div',undefined,'dimension-body');if(item.events?.length){item.events.forEach((event,i)=>body.append(eventCard(event,i)));}else{const ul=el('ul');item.lines.forEach(line=>ul.append(el('li',line)));body.append(ul);}
      if(item.id==='trend')body.append(list(report.report_stale?'历史分析理由':'支持与反对证据',s.reasons.concat(s.risks),'当前证据不足。'));
      const refs=el('div',undefined,'dimension-sources');[...new Set(item.source_ids)].forEach(id=>{const source=sourceMap.get(id);if(source)refs.append(link(source.name||id,source.url));});if(refs.childNodes.length)body.append(refs);
      d.append(body);section.append(d);});panel.append(section);
  }
  function renderScoreSummary(panel,s) {
    if(s.score_model!=='company_research_v2')return;
    const section=el('section',undefined,'balanced-score'),b=s.score_breakdown||{},pending=s.score_status!=='complete';
    section.append(el('h3',(pending?'阶段研究分 · ':'板块研究分 · ')+txt(s.research_tier?.label,'待完成评估')),el('p',txt(s.research_tier?.reason),'field-help'));
    const grid=el('div',undefined,'balanced-score-grid');
    for(const [key,label,max] of [['fundamentals','基本面',40],['trend','走势',30],['catalysts','事件催化',30]]){
      const item=el('div',undefined,'balanced-score-item'),row=b[key]||{},value=key==='catalysts'?row.observed_adjustment:row.points;
      const text=finite(value)?(key==='catalysts'&&value>0?'+':'')+num(value):'待评估';
      item.append(el('span',label),el('strong',text,key==='catalysts'&&finite(value)?value<0?'catalyst-negative':value>0?'catalyst-positive':'' : ''),el('small',key==='catalysts'?'−30～+30': '0～'+max));grid.append(item);
    }section.append(grid);
    if(pending)section.append(el('p','事件或财务评分证据尚未齐全，阶段分不进入完整档位。可能范围 '+s.score_possible_range.map(v=>num(v)).join('～')+' / 100；范围为缺项上下界，不是预测区间。','score-pending-note'));
    const checks=el('div',undefined,'score-condition-list');for(const [key,label] of [['total_at_least_65','总分≥65'],['fundamentals_at_least_28','基本面≥28/40'],['trend_at_least_18_or_positive_catalyst','走势≥18/30或催化>0'],['evidence_complete','评分证据完整']])checks.append(el('span',(s.research_tier?.conditions?.[key]?'✓ ':'○ ')+label,s.research_tier?.conditions?.[key]?'condition-met':'condition-pending'));section.append(checks);
    const r=s.market_risk||{};section.append(el('p','环境风险独立评分：'+(finite(r.score)?num(r.score,0)+'/100 · '+r.level:'待核验')+' · '+txt(r.profile)+' · 证据覆盖 '+num(r.coverage_pct,0)+'%；分数越高风险越高。','independent-risk-note'));
    section.append(el('p','完整档位：≥65且附加条件满足为乐观；50～<65为中性；30～<50为谨慎；<30为规避。≥65但附加条件不足按中性观察。','field-help'));panel.append(section);
  }
  function renderDetailedAdvice(panel,s,advice) {
    const box=el('section',undefined,'sector-ai-detailed');box.setAttribute('aria-label',advice.historical?advice.label:'详细研究建议与核验计划');
    box.append(el('h4',advice.historical?advice.label:'详细研究建议与核验计划'));if(advice.historical)box.append(el('p',advice.notice,'sector-history-notice'));box.append(el('p',advice.historical?'范围：生成时保存的'+(advice.scope==='reference'?'参考指标研究':'公司研究')+'，请结合当时证据复盘。':advice.scope==='reference'?'范围：参考指标研究，观察其走势及覆盖市场。':s.score_status!=='complete'?'范围：公司基础/阶段研究，保留 '+s.score_maximum+' 分口径，先核验尚缺证据。':'范围：公司研究，按当前完整研究分及其证据形成条件判断。','field-help'));
    const sources=new Map([...report.snapshot.sources,...report.company_evidence.sources].map(row=>[row.id,row]));
    const section=(title,rows,fields)=>{
      if(!rows.length)return;const group=el('section',undefined,'sector-ai-detail-section'),items=el('ol');group.append(el('h4',title));
      rows.forEach(row=>{const item=el('li');fields.forEach(([key,label])=>item.append(el('p',label+'：'+txt(row[key]))));const refs=el('div',undefined,'dimension-sources');arr(row.evidence_ids).forEach((id,index)=>{const source=sources.get(id),name=txt(source?.name||source?.title||source?.label,'来源 '+(index+1));refs.append(source?link(name,source.url):el('span',name));});item.append(refs);items.append(item);});group.append(items);box.append(group);
    };
    section('判断依据：事实与解释',advice.evidenceChain,[['fact','证据事实'],['interpretation','研究解释']]);
    section('下一步怎么核验',advice.actionPlan,[['trigger','触发条件'],['step','核验步骤']]);
    section('不同情况如何调整关注',advice.scenarios,[['condition','观察到的变化'],['response','研究应对']]);
    if(advice.reviewConditions.length)box.append(list('暂停原结论并重新复核的条件',advice.reviewConditions,''));panel.append(box);
  }
  function renderDetail() {
    const box=$('#sectorDetail');box.replaceChildren();const s=report?.sector_analysis.find(s=>s.id===selected);if(!s)return;
    const data=sectorDataPresentation(s,{historical:report.report_stale,sources:report.snapshot.sources,companyCount:(report.company_evidence.sector_leaders[s.id]||[]).length,eventCount:report.event_analysis.events.filter(event=>event.sector_ids.includes(s.id)).length});const panel=el('article',undefined,'card sector-detail-card');applyTone(panel,s);
    const head=el('div',undefined,'sector-detail-head');const title=el('div');title.append(el('span',report.report_stale?'HISTORICAL SECTOR ANALYSIS':'SECTOR ANALYSIS','eyebrow'),el('h2',s.title),el('p',groups[s.group]||s.group,'muted'));
    const score=el('div',undefined,'sector-detail-score'+(!data.hasScore?' is-unscored':''));score.append(el('strong',data.scoreText),el('span',data.hasScore?(s.score_model==='company_research_v2'?data.scoreUnit:report.report_stale?'历史研究分数 / 100':s.score_label?s.score_label+' / 100':s.custom_index?'综合研究分数 / 100':'研究分数 / 100'):data.scoreNote));head.append(title,score);panel.append(head);
    if(report.report_stale)panel.append(el('p','历史板块分析 · 报告时间 '+stamp(report.as_of)+'；以下理由与风险反映当时数据，当前信号已清除。','sector-history-notice'));panel.append(el('p',s.summary,'sector-detail-summary'));
    const scarcityDetail=scarcityUI?.detail(s.scarcity);if(scarcityDetail)panel.append(scarcityDetail);
    renderIndependentIndex(panel,s);
    renderScoreSummary(panel,s);
    if(s.requirements?.length){const checks=el('div',undefined,'sector-requirements');s.requirements.forEach(r=>{const n=el('div',undefined,'sector-requirement requirement-'+r.status);n.append(el('b',r.label),el('span',({ok:'已满足',partial:'部分满足',missing:'数据缺失'})[r.status]||'待检查'),el('small',r.note));checks.append(n);});panel.append(checks);}
    const metrics=el('div',undefined,'sector-detail-metrics');[[data.changeLabel,data.changeText],['趋势判断',data.trendText],['风险程度',data.riskText],['行情时间',stamp(s.as_of)]].forEach(([label,value])=>{const n=el('div');n.append(el('span',report.report_stale&&label!=='行情时间'?'历史'+label:label));const indicator=report.report_stale?null:sectorIndicator(s);const b=el('b');if(indicator&&((label==='趋势判断'&&indicator.className==='trend-strong')||(label==='风险程度'&&indicator.className==='risk-critical')))b.append(indicatorNode(indicator),document.createTextNode(String(value)+' · '+indicator.label));else b.textContent=String(value);n.append(b);metrics.append(n);});panel.append(metrics);
    if(data.gaps.length||!data.hasQuote||!data.hasScore){const diagnostics=el('section',undefined,'sector-data-diagnostics');diagnostics.append(el('h4',report.report_stale?'历史数据缺口与采集状态':'数据缺口与采集状态'),el('p',data.subtitle,'data-gap-summary'));if(data.referenceExpected)diagnostics.append(el('p','参考行情：'+data.referenceExpected,'field-help'));if(data.evidenceSummary)diagnostics.append(el('p',data.evidenceSummary,'data-evidence-available'));if(data.gaps.length){const gaps=el('ul',undefined,'sector-gap-list');data.gaps.forEach(gap=>gaps.append(el('li',gap.message)));diagnostics.append(gaps);}const sources=el('div',undefined,'sector-gap-sources');data.sources.forEach(source=>{const item=el('div',undefined,'sector-gap-source');item.append(link(source.name||'相关数据来源',source.url),el('span',sourceStatusLabel(source.status),'pill'));if(source.error)item.append(el('p',source.error));const timing=[source.as_of?'数据时间 '+stamp(source.as_of):'',source.fetched_at?'采集时间 '+stamp(source.fetched_at):''].filter(Boolean).join(' · ');if(timing)item.append(el('small',timing));sources.append(item);});if(!data.sources.length)sources.append(el('p','本方向尚无可展示的行情来源记录。','field-help'));diagnostics.append(sources);panel.append(diagnostics);}
    renderResearchPanels(panel,s);panel.append(list(report.report_stale?'当时观察与条件':'后续观察与条件',s.next_steps,'等待有效公司样本与可靠来源，再复核研究结论。'));
    if(!['bond','convertible_bond','money_rate'].includes(s.quote.asset_type))renderCompanyEvidence(panel,s);
    if(s.ai_access?.status==='locked'&&root.FundPilotSubscriptions)panel.append(root.FundPilotSubscriptions.accessCard(s,report));
    if(s.ai_analysis&&s.ai_research_status==='completed'&&(report.report_stale||report.ai_research.status!=='stale')){const a=el('div',undefined,'sector-ai-analysis'),advice=researchAdvicePresentation(s,report),historicalAdvice=researchHistoricalAdvicePresentation(s,report),saved=researchSavedPresentation(s,report);a.append(el('h4',report.report_stale?'历史 AI 板块解读':'AI 板块解读'));if(saved.saved){const meta=el('div',undefined,'research-ai-save-meta'),time=el(saved.generatedAt?'time':'span',saved.label,'research-ai-saved-time');if(saved.generatedAt)time.dateTime=saved.generatedAt;meta.append(time,el('small',saved.note,'research-ai-save-note'),el('small',saved.dataLabel,'research-ai-data-time'));a.append(meta);}if(!report.report_stale){a.append(el('b',advice.label));if(advice.summary)a.append(el('p',advice.summary));if(advice.watchPoints.length)a.append(list('后续核验重点',advice.watchPoints,''));if(advice.detailed)renderDetailedAdvice(a,s,advice);}else if(historicalAdvice)renderDetailedAdvice(a,s,historicalAdvice);a.append(el('p',s.ai_analysis));if(s.ai_risks.length)a.append(list('AI 补充风险',s.ai_risks,''));if(s.ai_invalidation)a.append(el('p','失效条件：'+s.ai_invalidation));panel.append(a);}
    const evidence=el('div',undefined,'sector-evidence');evidence.append(el('b','行情依据'));if(s.quote.name)evidence.append(el('span',s.quote.name+(s.quote.code?' · '+s.quote.code:'')));if(s.sources.length)s.sources.forEach(source=>evidence.append(link(source.name||'查看来源',source.url)));else evidence.append(el('span','暂无可用来源记录'));panel.append(evidence);
    if(s.score_method){const model=el('details',undefined,'sector-model');model.append(el('summary','查看评分模型与计算依据'),el('p',s.score_method,'field-help'));const components=Object.entries(s.score_components).filter(([,v])=>finite(v));if(components.length)model.append(el('p','各项得分：'+components.map(([k,v])=>componentLabel(k)+' '+v.toFixed(2)).join('；'),'field-help'));panel.append(model);}
    const related=report.event_analysis.events.filter(event=>event.sector_ids.includes(s.id));
    if(related.length){const relatedSection=el('section',undefined,'sector-related-events');relatedSection.append(el('h4','相关重要事件'));const news=el('div',undefined,'sector-event-list');eventList(news,related,'');relatedSection.append(news);panel.append(relatedSection);}
    box.append(panel);
  }
  function renderBoards() {
    const allSectors=report?.sector_analysis||[],sectors=allSectors.filter(s=>finite(s.score));
    if(group!=='all'&&!sectors.some(s=>s.group===group))group='all';
    const groupBox=$('#boardGroups');groupBox.replaceChildren();[['all','全部方向'],...Object.entries(groups).filter(([id])=>sectors.some(s=>s.group===id))].forEach(([id,name])=>{const b=el('button',name+(id==='all'?' '+sectors.length:' '+sectors.filter(s=>s.group===id).length),'sector-group');b.type='button';b.setAttribute('aria-pressed',String(group===id));b.onclick=()=>{group=id;renderBoards();};groupBox.append(b);});
    const marked=sectors.filter(s=>scarcityUI?.isMarked(s));
    const scarcityFilter=$('#scarcityFilter');if(scarcityFilter){const allowed=report?.scarcity_access?.allowed===true&&!report.report_stale;if(!allowed)onlyScarcity=false;scarcityFilter.parentElement.hidden=!allowed;scarcityFilter.setAttribute('aria-pressed',String(onlyScarcity));scarcityFilter.textContent='◇ 只看稀缺性标注 · '+marked.length;scarcityFilter.onclick=()=>{onlyScarcity=!onlyScarcity;renderBoards();};}
    const visible=sortSectors(sectors.filter(s=>(!onlyScarcity||scarcityUI?.isMarked(s))&&(group==='all'||s.group===group)&&(!query||(s.title+' '+(groups[s.group]||'')+' '+txt(s.scarcity?.scope)+' '+txt(s.scarcity?.label)).toLowerCase().includes(query.toLowerCase()))),sort);
    const company=sectors.filter(s=>s.score_model==='company_research_v2'&&finite(s.score));
    setText('boardCoverageSummary','共 '+sectors.length+' 个方向 · 公司完整分 '+company.filter(s=>s.score_status==='complete').length+' 个 · 公司基础/阶段分 '+company.filter(s=>s.score_status!=='complete').length+' 个 · 其他指标 '+sectors.filter(s=>s.score_model!=='company_research_v2').length+' 个');
    setText('boardResearchNotice',boardResearchNotice(report,sort));
    const box=$('#boardDirectory');box.replaceChildren();$('#sectorEmpty').hidden=visible.length>0;
    // Unscored directions stay accessible through personal watchlist shortcuts.
    if(!visible.some(s=>s.id===selected)&&!allSectors.some(s=>s.id===selected&&!finite(s.score)))selected=visible[0]?.id||null;
    const counts=new Map();visible.forEach(s=>{const id=boardScoreGroup(s).id;counts.set(id,(counts.get(id)||0)+1);});let previousGroup=null;
    visible.forEach(s=>{
      const family=boardScoreGroup(s);
      if(sort==='score'&&family.id!==previousGroup){const heading=el('div',undefined,'sector-score-group');heading.setAttribute('role','heading');heading.setAttribute('aria-level','3');heading.append(el('b',family.label+' · '+counts.get(family.id)+' 个'),el('small',family.note));box.append(heading);previousGroup=family.id;}
      const row=el('button',undefined,'sector-row'+(s.score_model==='company_research_v2'&&s.score_status!=='complete'?' is-provisional':''));row.type='button';row.dataset.sector=s.id;row.setAttribute('aria-pressed',String(s.id===selected));applyTone(row,s);
      const data=sectorDataPresentation(s,{historical:report.report_stale,companyCount:(report.company_evidence.sector_leaders[s.id]||[]).length,eventCount:report.event_analysis.events.filter(event=>event.sector_ids.includes(s.id)).length});const name=el('div',undefined,'sector-row-title');name.append(el('b',s.title),el('small',data.subtitle));name.title=data.subtitle;const change=el('span',data.changeText,'sector-change '+(data.hasQuote?(s.change_pct>0?'up':s.change_pct<0?'down':''):'is-unavailable'));
      const scarcityBadge=scarcityUI?.badge(s.scarcity);if(scarcityBadge)name.append(scarcityBadge);
      const score=el('span',undefined,'sector-row-score'+(!data.hasScore?' is-unscored':'')),value=el('span',undefined,'sector-score-value');value.append(el('b',data.scoreText),el('small',data.scoreUnit));score.append(value);
      const view=companyScoreView(s);if(view)score.append(el('small',view.label,'research-tier tier-'+s.research_tier.id));
      const risk=el('span',undefined,'sector-row-risk');risk.title=txt(s.market_risk?.scope);const indicator=report.report_stale?null:sectorIndicator(s);if(indicator)risk.append(indicatorNode(indicator),el('span','行情 '+data.riskText+' · '+indicator.label));else risk.append(el('span','行情 '+data.riskText));
      if(finite(s.market_risk?.score))risk.append(el('small','环境 '+txt(s.market_risk.level)+' '+num(s.market_risk.score,0)+'/100'+(s.market_risk.status!=='complete'?'（部分）':'')));
      row.append(name,change,score,risk);
      if(view){const evidence=el('span',undefined,'sector-row-evidence');evidence.append(el('span',view.fundamentals),el('span',view.trend),el('span',view.catalyst,view.catalystTone?'catalyst-'+view.catalystTone:''));if(view.gates)evidence.append(el('small',view.gates));row.append(evidence);}
      row.onclick=()=>{selected=s.id;renderBoards();renderDetail();$('#sectorDetail').scrollIntoView({behavior:'smooth',block:'start'});};box.append(row);
    });renderDetail();
    document.dispatchEvent(new CustomEvent('fundpilot:research-rendered'));
  }
  // Personal shortcuts use the full report, regardless of directory filters.
  root.SectorWorkspace = {
    getReport: () => report,
    refreshResearchHistory,
    refreshPersonalReport: async () => {
      const revision=++personalProjectionRevision;
      if(viewingHistory&&report?.as_of){const reportId=report.as_of,data=await request('/api/me/history/report?as_of='+encodeURIComponent(reportId));if(viewingHistory&&report?.as_of===reportId&&revision===personalProjectionRevision)acceptReport(data.report,true);}
      else{reportNeedsRefresh=true;reportVersion='';await poll();}
    },
    openSubscription: () => {view('dash');const choices=document.getElementById('subscriptionChoiceDetails');if(choices)choices.open=true;document.getElementById('aiSubscription')?.scrollIntoView({behavior:'smooth',block:'start'});},
    getAiRuntime: () => ({subscription:state.ai_subscription,config:config?{configured:config.configured,enabled:config.enabled,effective_enabled:config.effective_enabled,verification:config.verification,error:config.error,reasoning_effort:config.reasoning_effort,schedule:config.schedule,cost_controls:config.cost_controls,ai_next_run_at:config.ai_next_run_at}:null,state:{status:state.status,stage:state.stage,ai_research:state.ai_research,ai_cost:state.ai_cost,ai_calendar:state.ai_calendar,ai_next_run_at:state.ai_next_run_at,connection_error:state.connection_error,config_error:state.config_error}}),
    applyUnlockedSector: (raw,reportId) => {
      if(report?.as_of!==reportId)return false;
      const value=normalizeSector(raw),index=report.sector_analysis.findIndex(s=>s.id===value?.id);
      if(index<0)return false;
      report.sector_analysis[index]=value;renderBoards();return true;
    },
    openAiSettings: () => {view('settings');$('#aiSettingsForm').scrollIntoView({behavior:'smooth',block:'start'});},
    openSector: id => {
      if(!report?.sector_analysis.some(s=>s.id===id))return false;
      selected=id;group='all';query='';onlyScarcity=false;$('#boardSearch').value='';
      view('dash');renderBoards();
      $('#sectorDetail').scrollIntoView({behavior:'smooth',block:'start'});
      return true;
    }
  };
  $('#boardSearch').oninput=e=>{query=e.target.value;renderBoards();};$('#sectorSort').onchange=e=>{sort=e.target.value;renderBoards();};
  function renderSentiment() {
    const s=sentimentPresentation(report?.market_sentiment),card=$('#sentimentCard');
    card.dataset.tone=s.tone;setText('sentimentValue',s.scoreText);setText('sentimentLabel',s.label);setText('sentimentStatus',s.statusLabel);
    setText('sentimentSummary',s.summary);setText('sentimentSamples',s.sample_count+' / '+s.candidate_count+' 家');setText('sentimentIndices',s.index_count+' / 4 个');
    setText('sentimentCoverage','可用分项权重 '+(finite(s.coverage_pct)?num(s.coverage_pct,0)+'%':'待核验')+' · 不代表全市场覆盖率');
    setText('sentimentTime','报价日：'+(s.sample_date||'待取得')+' · 趋势收盘日：'+(s.history_date||'待取得'));
    setText('sentimentDateBrief','报价日期：'+(s.sample_date||'待取得'));
    const meter=$('#sentimentMeter'),marker=$('#sentimentMarker');marker.hidden=s.score===null;marker.style.left=(s.score??0)+'%';
    if(s.score===null)meter.removeAttribute('aria-valuenow');else meter.setAttribute('aria-valuenow',String(s.score));
    meter.setAttribute('aria-valuetext',s.score===null?s.statusLabel:s.score.toFixed(2)+'分，'+s.label);
    const parts=$('#sentimentComponents');parts.replaceChildren();
    s.components.forEach(c=>{const row=el('div',undefined,'sentiment-component'),head=el('div');head.append(el('b',c.label),el('span',(finite(c.score)?num(c.score)+' / 100':'待补充')+' · 权重 '+num(c.weight*100,0)+'%'));row.append(head,el('p',c.note,'muted'),el('small','有效 '+c.count+' 项 · 数据时间：'+stamp(c.as_of),'muted'));parts.append(row);});
    if(!s.components.length)parts.append(el('p','等待有效行情与历史样本。','muted'));
    setText('sentimentMissing',s.missing.length?'缺失或限制：'+s.missing.join('；'):'');$('#sentimentMissing').hidden=!s.missing.length;
    setText('sentimentMethod',s.method||'上涨广度40% + 主要指数强弱30% + 20日均线参与度30%。至少两项有效、可用分项权重达到70%才计算；缺项按有效权重归一。');
    setText('sentimentScope',s.scope||'基于已接入且去重的A股公司样本，属于情绪代理指标。');
    setText('sentimentAsOf','评估时间：'+stamp(s.as_of));
    const sources=$('#sentimentSources');sources.replaceChildren();
    const known=new Map([...arr(report?.snapshot?.sources),...arr(report?.company_evidence?.sources)].map(v=>[v.id,v]));
    s.source_ids.forEach(id=>{const source=known.get(id);sources.append(link(source?.name||id,source?.url));});
    if(!s.source_ids.length)sources.append(el('span','暂无有效来源记录'));
  }
  function renderLiquidity() {
    const s=liquidityPresentation(report?.market_liquidity),card=$('#liquidityCard');
    card.dataset.tone=s.tone;setText('liquidityValue',s.scoreText);setText('liquidityLabel',s.label);setText('liquidityStatus',s.statusLabel);
    setText('liquiditySummary',s.summary);setText('liquidityRate',finite(s.annual_rate_pct)?num(s.annual_rate_pct,3)+'%':'待补充');
    setText('liquidityTrend',s.trend||'待补充');setText('liquiditySamples',s.sample_count+' 个观测点');
    setText('liquidityTime','数据时间：'+(s.as_of||'待取得'));
    const meter=$('#liquidityMeter'),marker=$('#liquidityMarker');marker.hidden=s.score===null;marker.style.left=(s.score??0)+'%';
    if(s.score===null)meter.removeAttribute('aria-valuenow');else meter.setAttribute('aria-valuenow',String(s.score));
    meter.setAttribute('aria-valuetext',s.score===null?s.statusLabel:s.score.toFixed(0)+'分，'+s.label);
    setText('liquidityChanges','1日 '+(finite(s.rate_change_1d_bp)?num(s.rate_change_1d_bp,2)+'bp':'—')+' · 5日 '+(finite(s.rate_change_5d_bp)?num(s.rate_change_5d_bp,2)+'bp':'—')+' · 20日 '+(finite(s.rate_change_20d_bp)?num(s.rate_change_20d_bp,2)+'bp':'—'));
    setText('liquidityCoverage','流动性风险 '+(finite(s.risk_score)?num(s.risk_score,0)+'/100':'待核验')+'；风险分越高代表资金环境风险越高。');
    setText('liquidityMethod',s.method||'沿用人民币隔夜Shibor专用流动性模型；分数越高表示资金利率相对平稳或趋宽。');
    setText('liquidityScope',s.scope||'仅观察人民币隔夜资金利率，不代表股票收益或存款安全。');
    setText('liquidityMissing',s.missing.length?'缺失或限制：'+s.missing.join('；'):'');$('#liquidityMissing').hidden=!s.missing.length;
    const sources=$('#liquiditySources');sources.replaceChildren();const known=new Map([...arr(report?.snapshot?.sources),...arr(report?.sector_analysis?.flatMap(x=>x.sources||[]))].map(v=>[v.id,v]));
    s.source_ids.forEach(id=>{const source=known.get(id);sources.append(link(source?.name||id,source?.url));});if(!s.source_ids.length)sources.append(el('span','暂无有效来源记录'));
  }
  function renderMarket() {
    if(!report)return;const panic=report.strategy.panic, regime=report.strategy.regime;
    renderSentiment();
    renderLiquidity();
    const score=!report.report_stale&&finite(panic.score)?panic.score:null;
    const pressureCard=$('#marketOverview .panic-card');if(pressureCard)pressureCard.dataset.tone=score===null?'unknown':score>=70?'high':score>=40?'medium':'low';
    setText('panicDateBrief','行情日期：'+(panic.quote_as_of||panic.data_time?String(panic.quote_as_of||panic.data_time).slice(0,10):'待取得'));
    setText('panicValue',num(score,0));setText('panicLabel',txt(panic.label,finite(score)?score>=70?'市场压力较高':score>=40?'市场压力中等':'市场压力较低':'数据待补充'));
    setText('panicSummary',txt(panic.summary || panic.reason,'市场样本不足，当前不生成恐慌分。'));setText('panicTime','评估时间：'+stamp(panic.calculated_at||panic.as_of||report.as_of)+' · 行情时间：'+stamp(panic.quote_as_of||panic.data_time));$('#panicBar').style.width=finite(score)?Math.max(0,Math.min(100,score))+'%':'0%';
    setText('regimeLabel',txt(regime.label || regime.name || regime.mode,'等待研究'));setText('marketTitle',txt(regime.title || regime.label,'板块行情与风险概览'));setText('marketSummary',report.summary || txt(regime.reason || regime.summary,'按板块的直接行情与新闻证据形成分析。'));
    const sectors=report.sector_analysis;const coverage=$('#sectorCoverage');coverage.replaceChildren();[['研究板块',sectors.length],['有效行情',sectors.filter(s=>['ok','partial'].includes(s.status)&&finite(s.change_pct)).length],['重要事件',report.event_analysis.events.length]].forEach(([label,value])=>{const d=el('div');d.append(el('strong',String(value)),el('span',label));coverage.append(d);});setText('reportTime','报告时间：'+stamp(report.as_of));
    const quotes=$('#marketQuotes');quotes.replaceChildren();report.snapshot.market.slice(0,8).forEach(q=>{const card=el('article',undefined,'sector-market-quote');card.append(el('span',txt(q.name || q.title || q.label,'市场指数')),el('strong',num(q.price ?? q.last ?? q.value)),el('b',pct(q.change_pct),'sector-change '+(q.change_pct>0?'up':q.change_pct<0?'down':'')),el('small',stamp(q.as_of || q.data_time || q.timestamp)));quotes.append(card);});
    if(report.score_method)setText('scoreMethod',report.score_method);
  }
  let sourcePageSize=12;
  function renderSourceRecords() {
    if(!report)return;
    const records=selectSourceRecords(report.snapshot.sources,$('#sourceSearch')?.value,$('#sourceStateFilter')?.value||'all'),box=$('#sourceList');box.replaceChildren();
    records.slice(0,sourcePageSize).forEach(s=>{
      const row=el('article',undefined,'sector-source'),info=el('div');row.dataset.state=sourceRecordState(s);
      info.append(link(s.name||s.id||'数据源',s.url),el('small','数据日期：'+(s.as_of?stamp(s.as_of):'未提供')));
      const statusLabel=({ok:'已获取',partial:'部分获取',error:'未取得',missing:'未取得',unavailable:'未取得',stale:'已过时',unknown:'待确认'})[s.status]||'待确认';
      row.append(info,el('span',statusLabel,'pill'));
      if(s.error||s.fetched_at){const detail=el('details',undefined,'source-record-detail');detail.append(el('summary',s.error?'查看说明与获取时间':'查看获取时间'));if(s.error)detail.append(el('p',s.error));if(s.fetched_at)detail.append(el('small','获取时间：'+stamp(s.fetched_at)));row.append(detail);}box.append(row);
    });
    if(!records.length)box.append(el('p','没有符合条件的来源记录，可更换搜索词或状态。','source-empty'));
    setText('sourceResultCount','符合条件 '+records.length+' 条 · 已展示 '+Math.min(sourcePageSize,records.length)+' 条');
    const more=$('#sourceShowMore');if(more){more.hidden=sourcePageSize>=records.length;more.textContent='再显示 '+Math.min(12,records.length-sourcePageSize)+' 条来源';}
  }
  $('#sourceSearch')?.addEventListener('input',()=>{sourcePageSize=12;renderSourceRecords();});
  $('#sourceStateFilter')?.addEventListener('change',()=>{sourcePageSize=12;renderSourceRecords();});
  $('#sourceShowMore')?.addEventListener('click',()=>{sourcePageSize+=12;renderSourceRecords();});
  function renderData() {
    if(!report)return;setText('dataAsOf','快照时间 '+stamp(report.snapshot.as_of || report.as_of));
    const stats=sourceOverview(report.snapshot.sources),summary=$('#sourceSummary');if(summary){summary.replaceChildren();for(const [key,label] of [['total','来源记录'],['ok','已获取'],['partial','部分获取'],['attention','未取得或过时'],['unknown','待确认']]){const item=el('div');item.dataset.state=key;item.append(el('strong',String(stats[key])),el('span',label));summary.append(item);}}
    const total=report.sector_analysis.length,scored=report.sector_analysis.filter(s=>finite(s.score)).length;
    setText('sourceSectorCoverage','本快照覆盖 '+total+' 个板块，其中 '+scored+' 个已有评分、'+(total-scored)+' 个暂未评分。来源记录数包含同一板块的多次请求与备用接口，不等于板块数量。');
    const issueLabels={timeout:'采集超时',http:'接口请求失败',connection:'连接或返回格式异常',coverage:'数据日期或历史覆盖不足',other:'其他不完整记录'},issues=Object.entries(sourceIssueOverview(report.snapshot.sources)).filter(([,count])=>count>0);
    setText('sourceIssueSummary',issues.length?'异常与不完整记录：'+issues.map(([key,count])=>issueLabels[key]+' '+count+' 条').join('；')+'。下方展开“查看说明与获取时间”可核对原始原因。':'本次来源记录没有未取得、过时或部分获取的记录。');
    renderSourceRecords();
    const warnings=$('#dataWarnings');warnings.replaceChildren();report.snapshot.warnings.forEach(w=>warnings.append(el('li',w)));const warningBox=$('#dataWarningDetails');if(warningBox){warningBox.hidden=!report.snapshot.warnings.length;setText('dataWarningCount','数据限制与采集说明 · '+report.snapshot.warnings.length+' 项');}
    const events=report.event_analysis.events;setText('newsCount',events.length+' 项');eventList($('#newsList'),events,'当前没有完成评估的中等及以上重要事件。');
  }
  function renderHistory() {setText('historyCount',histories.length+' 份');const box=$('#historyList');box.replaceChildren();histories.forEach(h=>{const b=el('button',undefined,'history-item');b.append(el('strong','报告数据时间 '+stamp(h.as_of)+' · '+(h.cloud_record?h.sector_count:h.sector_analysis.length)+' 个板块'),el('span',h.summary||'板块行情与风险报告'));b.onclick=async()=>{b.disabled=true;try{const raw=h.cloud_record?(await request('/api/me/history/report?as_of='+encodeURIComponent(h.as_of))).report:h;const next=normalizeReport({...raw,report_stale:true});if(!next)throw new Error('历史记录格式无效');viewingHistory=true;report=next;render();view('dash');$('#reportNotice').hidden=false;$('#returnLatestReport').hidden=false;setText('reportNotice','正在回看历史报告（'+stamp(h.as_of)+'），历史指数仅供复盘。');}catch(error){toast(error.message);}finally{b.disabled=false;}};box.append(b);});if(!histories.length)box.append(el('p','生成成功后自动保存至研究记录；刷新后可恢复进行中的任务。','muted'));}

  $('#clearHistory').onclick=async()=>{historyCleared=true;histories=[];renderHistory();if(await saveHistory())toast('板块研究记录已清空');};
  function render(){renderMarket();renderEvents();renderBoards();renderData();renderAi();}
  function acceptReport(raw, stale=false) {const next=normalizeReport({...raw,report_stale:stale||raw?.report_stale===true});if(!next)return false;report=next;viewingHistory=false;$('#returnLatestReport').hidden=true;render();if(!next.report_stale&&!histories.some(h=>h.as_of===next.as_of)){histories.unshift(next);histories=histories.slice(0,20);saveHistory();renderHistory();}return true;}
  function aiEnabled(){return config?.effective_enabled===true || (config?.configured&&config?.enabled&&config?.verification==='verified');}
  function renderAiCost(ai) {
    const value=costPresentation(state.ai_cost,ai);setText('aiCostStatus',value.label);$('#aiCostStatus').dataset.status=value.status;
    setText('aiCostRequests',value.requests);setText('aiCostTokens',value.tokens);setText('aiCostReused',value.reused);setText('aiCostUnknown',value.unknown);$('#aiCostUnknown').hidden=!value.unknown;setText('aiCostNote',value.note);
    const box=$('#aiCostKinds');box.replaceChildren();value.kinds.forEach(row=>{const item=el('div',undefined,'ai-cost-kind');item.append(el('b',row.label),el('span',row.requests+' 次请求'),el('small','实际输入 '+row.prompt+' · 输出 '+row.completion+' Token'));box.append(item);});if(!value.kinds.length)box.append(el('p','今日尚无可展示的分类用量记录。','field-help'));setText('aiCostNote',value.note+' 当前推理倍率：'+value.multiplier+'×；实际 Token 与计费折算分别展示。');
  }
  function renderAi() {const ai=report?.ai_research||state.ai_research||{}, usage=ai.usage||{},activity=aiActivityPresentation(config,state,ai);setText('aiModel',ai.model || config?.model ? modelLabel(ai.model || config.model, ai.reasoning_effort || config?.reasoning_effort) : UNKNOWN);setText('aiCalls',finite(ai.request_count)?String(ai.request_count):finite(ai.calls)?String(ai.calls):UNKNOWN);setText('aiCoverage',finite(ai.analyzed_count)&&finite(ai.target_count)?ai.analyzed_count+' / '+ai.target_count:UNKNOWN);setText('aiTokens',finite(usage.total_tokens)?String(usage.total_tokens):finite(ai.total_tokens)?String(ai.total_tokens):UNKNOWN);renderAiCost(ai);
    setText('aiResearchTitle',activity.title);setText('aiResearchDetail',activity.detail||txt(ai.summary || ai.error,aiEnabled()?'后台将按已保存的时间计划研究板块证据，并显示实际用量。':'启用 AI 后自动研究板块行情、市场新闻与风险理由；量化分析继续独立运行。'));setText('aiNext',nextAiText());setText('aiConfigBadge',!config?'配置读取中':!config.configured?'未配置 API Key':aiEnabled()?'已验证 · 自动 AI 已启用':config.verification==='failed'?'密钥校验失败':'自动 AI 当前关闭');const signature=JSON.stringify(root.SectorWorkspace.getAiRuntime());if(signature!==aiViewSignature){aiViewSignature=signature;document.dispatchEvent(new CustomEvent('fundpilot:ai-state-changed'));}}
  function nextAiText(){const calendar=state.ai_calendar||config?.ai_calendar;if(aiEnabled()&&config?.schedule?.mode==='market_sessions'&&calendar&&calendar.status!=='verified')return txt(calendar.reason,'交易日历尚未核验，暂停自动 AI 研究。');if(!aiEnabled())return '自动 AI 当前关闭';const next=(state.ai_next_run_at||config?.ai_next_run_at)?'下次实际 AI 调用：'+stamp(state.ai_next_run_at||config.ai_next_run_at):'下次实际 AI 调用：等待后台计划';return (aiActivityPresentation(config,state,report?.ai_research||{}).reinforcing?'正在强化分析 · 整理已有证据；':'')+next;}
  function costControls(){return {reuse_enabled:$('#aiReuseEnabled').checked,daily_request_limit:Number($('#aiDailyRequestLimit').value),daily_token_limit:Number($('#aiDailyTokenLimit').value)};}
  function schedule(){return {mode:'market_sessions',interval_minutes:30,daily_time:'09:20',end_time:null,timezone:'Asia/Shanghai'};}
  function updateSchedule(){const s=schedule(),market=s.mode==='market_sessions',timed=s.mode!=='interval'&&!market;$('#aiScheduleIntervalField').hidden=s.mode==='daily'||market;$('#aiScheduleTimeField').hidden=!timed;$('#aiScheduleEndTimeField').hidden=!timed;$('#aiScheduleTime').required=timed;$('#marketSessionTimes').hidden=!market;
    const calendar=state.ai_calendar||config?.ai_calendar,calendarText=market&&calendar?(calendar.status==='verified'?'交易日历已核验'+(calendar.year?'（'+calendar.year+' 年）':'')+(calendar.source?' · '+calendar.source:'')+'。':txt(calendar.reason,'交易日历尚未核验，暂停自动研究。')):'';
    setText('eventScheduleLabel',eventScheduleText(config?.schedule||state.ai_schedule)+'；只展示中等及以上影响事件。');
    setText('aiScheduleHint',(market?'每个 A 股交易日固定分析两次：09:20、14:50。休市日跳过；交易日历无法核验时暂停自动调用并提示。':s.mode==='interval'?'按输入的分钟间隔运行，不受每日时段限制。':s.mode==='daily'?'每天在启动时间运行一次；可设置停止新增请求的时间。':'每天在启动至停止时段内按间隔研究，支持跨午夜。停止时间只停止新增请求。')+(calendarText?' '+calendarText:''));setText('aiScheduleNext',nextAiText());
    const warnings=[];if(['interval','scheduled_interval'].includes(s.mode)&&s.interval_minutes<30)warnings.push('当前间隔短于30分钟，可能频繁重复研究；建议使用交易日固定时段。');setText('aiFrequencyHint',warnings.join(' '));$('#aiFrequencyHint').hidden=!warnings.length;}
  function updateProvider(){if($('#responsesProviderField'))$('#responsesProviderField').hidden=$('#model').value!=='gpt-6.1-sol';}
  ['model','reasoningEffort','autoAiEnabled','key','aiScheduleMode','aiScheduleInterval','aiScheduleTime','aiScheduleEndTime','aiReuseEnabled','aiDailyRequestLimit','aiDailyTokenLimit','responsesBaseUrl'].forEach(id=>$('#'+id).oninput=()=>{settingsDirty=true;updateSchedule();updateProvider();});$('#aiScheduleMode').onchange=()=>{settingsDirty=true;updateSchedule();};$('#model').onchange=()=>{settingsDirty=true;updateProvider();};$('#reasoningEffort').onchange=()=>{settingsDirty=true;};
  function applyConfig(value){if(!value||typeof value!=='object')return;config=value;if(!settingsDirty){const model='gpt-6.1-sol';$('#model').value=model;$('#aiScheduleMode').value='market_sessions';$('#reasoningEffort').value=value.reasoning_effort==='medium'?'medium':'xhigh';$('#autoAiEnabled').checked=value.enabled===true;const s=value.schedule||{};$('#aiScheduleMode').value='market_sessions';$('#aiScheduleInterval').value=s.interval_minutes||30;$('#aiScheduleTime').value=s.daily_time||'15:30';$('#aiScheduleEndTime').value=s.end_time||'';const limits={...defaultCostControls,...value.cost_controls};$('#aiReuseEnabled').checked=limits.reuse_enabled;$('#aiDailyRequestLimit').value=limits.daily_request_limit;$('#aiDailyTokenLimit').value=limits.daily_token_limit;}
    if(!settingsDirty)$('#responsesBaseUrl').value=txt(value.responses_base_url);
    updateProvider();setText('savedAiStatus',value.configured?'已保存 '+txt(value.key_hint,'密钥')+' · '+(value.verification==='verified'?'校验通过':txt(value.error,'等待校验'))+(value.model==='gpt-6.1-sol'?' · gpt-6.1-sol / '+reasoningLabel(value.reasoning_effort):''):'尚未配置 API Key，量化板块分析可独立运行。');$('#key').placeholder=value.configured?'留空保留已保存的密钥':'输入 AI API Key';$('#testAi').disabled=!value.configured||configBusy;updateSchedule();renderAi();}
  async function request(path, body, timeout=20000){const response=await fetch(path,{...(body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{}),cache:'no-store',signal:AbortSignal.timeout(timeout)});const data=await response.json();if(!response.ok)throw new Error(data.error||'请求失败（'+response.status+'）');return data;}
  async function loadConfig(){try{const data=await request('/api/ai/config');state.config_error=false;applyConfig(data.config||data);}catch(e){state.config_error=true;setText('savedAiStatus','AI 配置读取失败：'+e.message);renderAi();}}
  function settingsVisible(){return $('#settings')?.classList.contains('on')===true;}
  function scheduleDataCheck(){clearTimeout(dataTimer);if(dataConfig?.verification!=='checking'||!settingsVisible())return;dataTimer=setTimeout(()=>{dataPollDelay=Math.min(6000,dataPollDelay*2);loadDataConfig();},dataPollDelay);}
  function applyDataConfig(value) {dataConfig=normalizeDataConfig(value);const presentation=dataStatusPresentation(dataConfig);$('#dataConfigBadge').dataset.status=dataConfig.verification||'unverified';setText('dataConfigBadge',presentation.badge);setText('savedDataStatus',presentation.description+(dataConfig.last_verified_at?' 检查于 '+stamp(dataConfig.last_verified_at):''));$('#testData').disabled=dataBusy||dataConfig.verification==='checking';$('#saveDataSettings').disabled=dataBusy||dataConfig.verification==='checking';
    const box=$('#dataCapabilities');box.replaceChildren();dataConfig.capabilities.forEach(row=>{const item=el('div',undefined,'data-capability');item.dataset.status=row.status||'unverified';item.append(el('b',row.label),el('span',capabilityStatusLabels[row.status]||'尚未核验','pill'));if(finite(row.count))item.append(el('small','有效记录：'+row.count));if(row.error||row.note||row.message)item.append(el('small',txt(row.error||row.note||row.message)));if(row.checked_at)item.append(el('small','检查时间：'+stamp(row.checked_at)));box.append(item);});if(report)renderDetail();scheduleDataCheck();
  }
  async function loadDataConfig(){if(dataLoading||dataBusy)return;dataLoading=true;try{const data=await request('/api/data/config');applyDataConfig(data.config||data);applyPublicData(data.supplemental);if(dataConfig.verification!=='checking')setText('dataSettingsStatus',dataStatusPresentation(dataConfig).message);}catch(error){setText('savedDataStatus','数据连接状态读取失败：'+error.message);setText('dataConfigBadge',error.name==='TimeoutError'?'状态读取超时':'状态读取失败');if(dataConfig?.verification==='checking')scheduleDataCheck();}finally{dataLoading=false;}}
  async function dataAction(path,body,message) {if(dataBusy||dataConfig?.verification==='checking')return;dataBusy=true;clearTimeout(dataTimer);$('#saveDataSettings').disabled=true;$('#testData').disabled=true;setText('dataSettingsStatus',message);try{const data=await request(path,body,90000);dataPollDelay=1500;applyDataConfig(data.config||data);setText('dataSettingsStatus',dataStatusPresentation(dataConfig).message);toast(dataConfig.verification==='checking'?'已开始检查数据连接':'数据源状态已更新');}catch(error){const message=error.name==='TimeoutError'?'连接检查请求超时，请稍后重新检查。':error.message;setText('dataSettingsStatus',message);toast(message);}finally{dataBusy=false;$('#saveDataSettings').disabled=dataConfig?.verification==='checking';$('#testData').disabled=dataConfig?.verification==='checking';scheduleDataCheck();}}
  let publicDataTimer,publicDataBusy=false;
  function applyPublicData(value){if(!value||!$('#publicDataBadge'))return;const status=value.verification;$('#publicDataBadge').dataset.status=status||'unverified';setText('publicDataBadge',({checking:'正在取数',verified:'样本取数通过',partial:'部分取得',failed:'取数未通过',unverified:'自动研究已接入'})[status]||'等待检查');setText('publicDataStatus',(value.error||value.scope||'真实样本检查，不代表全板块覆盖')+(value.last_checked_at?' · 检查于 '+stamp(value.last_checked_at):''));const box=$('#publicDataCapabilities');box.replaceChildren();arr(value.capabilities).forEach(row=>{const n=el('div',undefined,'data-capability');n.dataset.status=row.status||'unverified';n.append(el('b',txt(row.label)),el('span',row.status==='available'?'已配置':capabilityStatusLabels[row.status]||'尚未核验','pill'),el('small','记录 / 配置数量：'+(finite(row.count)?row.count:0)));if(row.note)n.append(el('small',row.note));box.append(n);});$('#testPublicData').disabled=publicDataBusy||status==='checking';clearTimeout(publicDataTimer);if(status==='checking'&&settingsVisible())publicDataTimer=setTimeout(loadDataConfig,2500);}
  if($('#testPublicData'))$('#testPublicData').onclick=async()=>{if(publicDataBusy)return;publicDataBusy=true;$('#testPublicData').disabled=true;setText('publicDataStatus','正在请求真实官方成分、公司行情和已披露财务样本…');try{const data=await request('/api/data/public/test',{});applyPublicData(data.supplemental);}catch(e){setText('publicDataStatus','多源连接检查失败：'+e.message);}finally{publicDataBusy=false;loadDataConfig();}};
  $('#dataSettingsForm').onsubmit=event=>{event.preventDefault();dataAction('/api/data/config',{},'正在检查 BaoStock 数据连接…');};
  $('#testData').onclick=()=>dataAction('/api/data/test',{},'正在检查行业成分、行情和财务数据…');
  $('#aiSettingsForm').onsubmit=async e=>{e.preventDefault();if(configBusy)return;const s=schedule(),limits=costControls(),form=$('#aiSettingsForm');$('#aiDailyRequestLimit').setCustomValidity(Number.isInteger(limits.daily_request_limit)&&limits.daily_request_limit>=1&&limits.daily_request_limit<=10000?'':'请输入1至10000的每日请求上限。');$('#aiDailyTokenLimit').setCustomValidity(Number.isInteger(limits.daily_token_limit)&&limits.daily_token_limit>=1000&&limits.daily_token_limit<=1000000000?'':'请输入1000至1000000000的每日Token预算。');$('#aiScheduleInterval').setCustomValidity(Number.isInteger(s.interval_minutes)&&s.interval_minutes>=1&&s.interval_minutes<=1440?'':'请输入 1 到 1440 的整数分钟。');$('#aiScheduleEndTime').setCustomValidity(s.end_time&&s.end_time===s.daily_time?'停止时间不能与启动时间相同。':'');if(!form.reportValidity())return;const key=$('#key').value.trim();if((!cloudMode||root.FundPilotCloud?.mode==='local')&&!key&&!config?.configured){toast('请输入 AI API Key');const credentials=$('#key').closest('details');if(credentials)credentials.open=true;$('#key').focus();return;}if(/\s/.test(key)){toast('API Key 不能包含空白字符');return;}configBusy=true;$('#saveAiSettings').disabled=true;setText('aiSettingsStatus','正在保存设置并检查配置…');try{const data=await request('/api/ai/config',{...(key?{key}:{}),...($('#model').value==='gpt-6.1-sol'?{responses_base_url:$('#responsesBaseUrl').value.trim()}:{}),model:$('#model').value,reasoning_effort:$('#reasoningEffort').value,enabled:$('#autoAiEnabled').checked,schedule:s,cost_controls:limits},60000);settingsDirty=false;$('#key').value='';applyConfig(data.config||data);const message=data.connection?.ok===false&&!data.connection?.skipped?'设置已保存，连接校验未通过：'+txt(data.connection.error,'请检查密钥或模型'):'研究设置已保存，按北京时间计划运行。';setText('aiSettingsStatus',message);toast(message);poll();}catch(error){setText('aiSettingsStatus',error.message);toast(error.message);}finally{configBusy=false;$('#saveAiSettings').disabled=false;$('#testAi').disabled=!config?.configured;}};
  $('#testAi').onclick=async()=>{if(configBusy)return;configBusy=true;$('#testAi').disabled=true;setText('aiSettingsStatus','正在检查连接与模型权限…');try{const data=await request('/api/ai/test',{},60000);applyConfig(data.config||config);setText('aiSettingsStatus',data.connection?.ok===true?'连接与模型权限检查通过；实际研究用量见首页。':'连接检查未通过：'+txt(data.connection?.error||data.error,'请检查配置'));}catch(e){setText('aiSettingsStatus',e.message);}finally{configBusy=false;$('#testAi').disabled=!config?.configured;}};
  function renderPublicRefresh(s){
    const live=s.public_refresh,strip=document.querySelector('.public-live-strip');
    if(!strip||!live)return;
    strip.dataset.market=live.market_status||'closed';
    setText('publicLiveLabel',live.running?'正在更新行情与量化评分':txt(live.label,'等待最新行情'));
    setText('publicLiveTime',live.completed_at?'最近刷新 '+stamp(live.completed_at):'等待首次有效采集');
    setText('publicLiveNext',live.next_run_at?'下次采集 '+stamp(live.next_run_at):'交易日历核验后恢复');
  }
  function renderState(s){state=s;renderPublicRefresh(s);if(s.ai_config)applyConfig(s.ai_config);setText('autoStatus',({idle:'板块研究准备中',running:'正在更新板块行情与分析',ready:'本轮板块研究已完成',error:'本轮板块研究暂未完成'})[s.status]||'正在连接板块研究服务');setText('autoStatusDetail',s.error?'研究异常：'+txt(s.error):s.status==='ready'&&s.ai_research?.public_refresh?'行情、量化评分与市场指标已更新；本轮未发起新的 AI 研究。':txt(s.stage,'后台自动采集板块行情、市场新闻并生成分析。'));setText('autoSchedule',[s.completed_at?'最近完成 '+stamp(s.completed_at):'',s.next_run_at?'下次更新 '+stamp(s.next_run_at):''].filter(Boolean).join(' · '));$('#autoRefresh').disabled=s.status==='running';$('#autoRefresh').textContent=s.status==='running'?'正在更新…':'更新行情与评分 ↻';renderAi();updateSchedule();}
  async function poll(){
    if(polling)return;polling=true;clearTimeout(timer);
    const revision=personalProjectionRevision;
    try{
      const s=await request('/api/auto/status?summary=1');
      if(revision!==personalProjectionRevision)return;
      renderState(s);
      if(!viewingHistory&&s.has_report&&(s.report_version!==reportVersion||!report||reportNeedsRefresh)){
        const data=await request('/api/auto/report',undefined,60000);
        if(revision!==personalProjectionRevision)return;
        if(!viewingHistory&&acceptReport(data.report,Boolean(data.report_stale))){
          reportNeedsRefresh=false;reportVersion=data.report_version||s.report_version;
          $('#reportNotice').hidden=!data.report_stale;
          if(data.report_stale)setText('reportNotice','当前为历史快照，最新市场状态待更新；推荐指数暂不作为当前判断。');
        }else if(!viewingHistory){$('#reportNotice').hidden=false;setText('reportNotice','系统正在切换到板块专用研究，新报告完成后自动显示。');}
      }
    }catch(e){
      if(revision!==personalProjectionRevision)return;
      state.connection_error=true;reportNeedsRefresh=true;renderAi();setText('autoStatus','暂时无法连接板块研究服务');setText('autoStatusDetail',e.name==='TimeoutError'?'请求超时，将自动重试。':e.message);$('#autoRefresh').disabled=false;
      if(report&&!viewingHistory){report=normalizeReport({...report,report_stale:true});render();$('#reportNotice').hidden=false;setText('reportNotice','当前为上次成功报告，最新行情状态尚未确认。');}
    }finally{polling=false;timer=setTimeout(poll,revision!==personalProjectionRevision?100:['running','idle'].includes(state.status)?5000:30000);}
  }
  async function refresh(){if(cloudMode&&root.FundPilotCloud.role!=='admin'){toast('公共研究由后台自动更新');return;}try{const s=await request('/api/auto/refresh',{});renderState(s);viewingHistory=false;reportNeedsRefresh=true;reportVersion='';toast('板块研究已启动，将自动更新结果');poll();}catch(e){toast(e.message);}}
  $('#returnLatestReport').onclick=()=>{viewingHistory=false;reportNeedsRefresh=true;$('#returnLatestReport').hidden=true;setText('reportNotice','正在读取最新报告…');poll();};
  $('#autoRefresh').onclick=refresh;$('#refreshSources').onclick=refresh;
  renderHistory();updateSchedule();loadConfig();loadDataConfig();poll();
})(typeof globalThis !== 'undefined' ? globalThis : this);
