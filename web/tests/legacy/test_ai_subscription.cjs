const {test}=require('node:test'),assert=require('node:assert/strict');
const {presentation,creditPlan,accessPrice,reasoningChoice}=require('../../src/lib/legacy/ai-subscription.js');
const study=require('../../src/lib/legacy/sector-research.js');
test('subscription presentation distinguishes account credits from provider balances',()=>{
  assert.equal(presentation().status,'unsubscribed');
  assert.equal(presentation({status:'active',credits_remaining:10,unlocked_count:3}).credits,'10');
  assert.equal(presentation({status:'active',credits_remaining:398.5}).credits,'398.5');
  assert.equal(presentation({status:'admin'}).credits,'统一管理');
  assert.equal(presentation({status:'expired'}).label,'订阅已到期');
});
test('account entitlement governs completed locked analysis even with connected backend key',()=>{
  const raw={id:'x',ai_access:{status:'locked',cost:1,content_id:'abc',can_unlock:true}};
  const sector=study.normalizeSector(raw),view=study.aiServicePresentation(sector,{},{});
  assert.equal(sector.ai_access.content_id,'abc');assert.equal(view.status,'locked');assert.equal(view.unlockable,true);
  assert.equal(view.subscribe,false);assert.equal(view.completed,false);assert.match(view.detail,/1 点/);
  const unentitled=study.normalizeSector({...raw,ai_access:{...raw.ai_access,can_unlock:false}});
  assert.equal(study.aiServicePresentation(unentitled,{},{}).subscribe,true);
});

test('credit estimates keep half points and count only complete unlocks',()=>{
  assert.deepEqual(creditPlan(400,1),{count:400,remainder:0});
  assert.deepEqual(creditPlan(400,1.5),{count:266,remainder:1});
  assert.deepEqual(creditPlan(0.5,1),{count:0,remainder:0.5});
  assert.deepEqual(creditPlan(1,1.5),{count:0,remainder:1});
  for(const value of [null,NaN,-1,1.2])assert.equal(creditPlan(value,1.5),null);
});

test('unlock presentation follows the report price and handles insufficient balance',()=>{
  const sector=study.normalizeSector({id:'x',ai_access:{status:'locked',cost:1.5,content_id:'high',can_unlock:true,subscription_status:'active'}});
  assert.equal(accessPrice(sector),1.5);
  assert.match(study.aiServicePresentation(sector,{},{}).detail,/1\.5 点/);
  const insufficient=study.normalizeSector({...sector,ai_access:{...sector.ai_access,can_unlock:false}});
  const view=study.aiServicePresentation(insufficient,{},{});assert.match(view.detail,/1\.5 点.*额度不足/);assert.equal(view.unlockable,false);
  assert.equal(accessPrice({ai_access:{cost:1,pricing_legacy:true}}),1);
});
test('waiting for report does not offer a chargeable unlock',()=>{
  const s=study.normalizeSector({id:'x',ai_access:{status:'not_ready',cost:0}}),view=study.aiServicePresentation(s,{},{});
  assert.equal(view.status,'pending');assert.equal(view.unlockable,undefined);assert.match(view.detail,/点击“生成 AI 研究”后才调用模型/);
  assert.match(view.detail,/生成有效解读后.*扣点/);assert.equal(view.nextText,'');
});
test('personal selection distinguishes no choice and both explicit rates',()=>{
  assert.equal(reasoningChoice({}),null);
  assert.equal(reasoningChoice({preferred_reasoning_effort:'high'}),null);
  assert.deepEqual(reasoningChoice({preferred_reasoning_effort:'medium'}),{effort:'medium',label:'中度推理',cost:1});
  assert.deepEqual(reasoningChoice({preferred_reasoning_effort:'xhigh'}),{effort:'xhigh',label:'极高推理',cost:1.5});
});
test('missing personal variant preserves the selected effort and explicitly waits for a user click',()=>{
  for(const [effort,label] of [['medium','中度'],['xhigh','极高']]){
    const sector=study.normalizeSector({id:'x',ai_access:{status:'not_ready',preferred_reasoning_effort:effort,preference_pending:true,available_efforts:['xhigh']}});
    const view=study.aiServicePresentation(sector,{},{});
    assert.match(view.title,new RegExp(label));assert.match(view.detail,/点击“生成 AI 研究”后才调用模型/);assert.doesNotMatch(view.detail,/09:20|14:50/);
    assert.equal(view.nextText,'');assert.equal(view.nextRunAt,'');
    assert.equal(view.personalPreference,true);assert.equal(view.unlockable,undefined);
    assert.equal(sector.ai_access.preferred_reasoning_effort,effort);assert.equal(sector.ai_access.preference_pending,true);
  }
});
