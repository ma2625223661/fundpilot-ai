const test=require('node:test'),assert=require('node:assert/strict');
const ui=require('../../dist/sector-research.js');
function sample(changes={}){return ui.normalizeSector({id:'x',status:'ok',score:65,score_model:'company_research_v2',score_status:'complete',
 score_breakdown:{fundamentals:{points:28},trend:{points:18},catalysts:{points:0}},
 ai_reason:'基于输入财务和走势的分析',ai_research_status:'completed',ai_risks:['高环境风险'],ai_invalidation:'财务转弱后复核',
 ai_advice:{action:'track',reason:'重点核验下一期财报的持续性',watch_points:['财务披露后核验净利增长']},...changes});}
test('current AI advice is visible only when its action matches measured research gates',()=>{
 const value=ui.researchAdvicePresentation(sample(),{ai_research:{status:'completed'}});
 assert.match(value.label,/AI 研究建议：重点跟踪/);assert.equal(value.summary,'重点核验下一期财报的持续性');assert.equal(value.watchPoints.length,1);
 const downgrade=ui.researchAdvicePresentation(sample({score:60}));assert.equal(downgrade.action,'observe');assert.match(downgrade.label,/研究分层建议/);assert.doesNotMatch(downgrade.summary,/下一期财报/);
});
test('historical, missing and incomplete evidence never generates an optimistic AI suggestion',()=>{
 for(const [sector,context] of [[sample(),{report_stale:true}],[sample({score:null}),{}],[sample({score_status:'partial',score_maximum:70}),{}]]){
  const result=ui.researchAdvicePresentation(sector,context);assert.equal(result.action,'wait');assert.doesNotMatch(result.label,/重点跟踪/);
 }
 assert.equal(ui.researchAdvicePresentation(sample(),{report_stale:true}).completed,false);
 assert.equal(ui.researchAdvicePresentation(sample(),{ai_research:{status:'stale'}}).completed,false);
});
test('missing AI output shows rule guidance without inventing model recommendations',()=>{
 const result=ui.researchAdvicePresentation(sample({ai_reason:'',ai_advice:null,ai_research_status:''}));
 assert.equal(result.completed,false);assert.match(result.label,/研究分层建议/);assert.equal(result.summary,'');assert.match(result.statusText,/尚未完成 AI 研究/);
});
test('action thresholds and additional fundamentals gate retain the agreed study levels',()=>{
 for(const [score,action] of [[65,'track'],[64.99,'observe'],[50,'observe'],[49.99,'cautious'],[30,'cautious'],[29.99,'avoid']])assert.equal(ui.researchAdvicePresentation(sample({score})).action,action);
 assert.equal(ui.researchAdvicePresentation(sample({score_breakdown:{fundamentals:{points:27.9},trend:{points:30}}})).action,'observe');
 assert.equal(ui.researchAdvicePresentation(sample({score_model:'reference'})).action,'reference');
});
