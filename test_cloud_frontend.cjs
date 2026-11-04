'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const historySource=fs.readFileSync('dist/sector-history.js','utf8');
function cloud(fetch){const context=vm.createContext({FundPilotCloud:{id:'user-a'},fetch,AbortSignal});Object.defineProperty(context,'localStorage',{get(){throw new Error('must not read local data');}});Object.defineProperty(context,'indexedDB',{get(){throw new Error('must not read local data');}});vm.runInContext(historySource,context);return context.SectorHistory.createHistoryStore();}
test('cloud history uses account API only and sends IDs instead of report content',async()=>{
 const calls=[];const store=cloud(async(path,init)=>{calls.push({path,init});return {ok:true,json:async()=>({items:[{research_scope:'sectors',cloud_record:true,as_of:'record-1'}]})};});
 assert.equal((await store.load()).items[0].as_of,'record-1');
 const result=await store.save([{research_scope:'sectors',as_of:'record-1',private_text:'not sent'}]);
 assert.equal(result.backend,'cloud');assert.deepEqual(JSON.parse(calls[1].init.body),{report_ids:['record-1']});
 assert.equal(calls[0].path,'/api/me/history');assert.equal(calls[0].init.cache,'no-store');
});
test('cloud errors stay visible and never fall back to unscoped browser records',async()=>{
 const store=cloud(async()=>({ok:false,json:async()=>({error:'offline'})}));
 await assert.rejects(store.load(),/offline/);await assert.rejects(store.save([]),/offline/);
});
test('cloud history writes serialize so clear cannot be overtaken by a previous save',async()=>{
 const writes=[];const store=cloud(async(path,init)=>{writes.push(JSON.parse(init.body).report_ids);await new Promise(r=>setTimeout(r,5));return {ok:true,json:async()=>({items:[]})};});
 await Promise.all([store.save([{research_scope:'sectors',as_of:'previous'}]),store.save([])]);
 assert.deepEqual(writes,[['previous'],[]]);
});
test('model labels expose the selected GPT reasoning strength',()=>{
 const {modelLabel}=require('./dist/sector-research.js');assert.equal(modelLabel('gpt-6.1-sol','medium'),'gpt-6.1-sol · 中度推理');assert.equal(modelLabel('gpt-6.1-sol','xhigh'),'gpt-6.1-sol · 极高推理');
 const html=fs.readFileSync('dist/index.html','utf8');assert.match(html,/id="reasoningEffort"/);assert.match(html,/<option value="medium">中度推理（1 点 \/ 份）<\/option>/);assert.match(html,/<option value="xhigh">极高推理（1\.5 点 \/ 份）<\/option>/);
});
