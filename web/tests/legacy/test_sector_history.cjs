'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {createHistoryStore}=require('../../src/lib/legacy/sector-history.js');
const row=id=>({research_scope:'sectors',as_of:String(id),sector_analysis:[{id:'x',text:'x'.repeat(200)}]});
function storage(capacity=Infinity){const values=new Map();return {getItem:k=>values.get(k)||null,setItem(k,v){if(v.length>capacity)throw new Error('quota');values.set(k,v);},removeItem:k=>values.delete(k)};}
function database(){
 const values=new Map();
 return {values,open(){const request={};setImmediate(()=>{request.result={objectStoreNames:{contains:()=>true},close(){},transaction(){const tx={objectStore(){return {get(k){const r={};setImmediate(()=>{r.result=values.get(k);r.onsuccess?.();tx.oncomplete?.();});return r;},put(value,k){const r={};setImmediate(()=>{values.set(k,structuredClone(value));r.onsuccess?.();tx.oncomplete?.();});return r;}};}};return tx;}};request.onsuccess?.();});return request;}};
}
test('large histories persist in indexedDB and migrate legacy only after successful commit',async()=>{
 const db=database(),legacy=storage();legacy.setItem('fundpilot_sector_history_v1',JSON.stringify([row('old')]));
 const store=createHistoryStore({database:db,storage:legacy});assert.equal((await store.load()).items[0].as_of,'old');
 const rows=Array.from({length:20},(_,i)=>({...row(i),text:'大'.repeat(60000)}));
 assert.deepEqual(await store.save(rows),{saved_count:20,limited:false,backend:'indexedDB'});
 assert.equal(legacy.getItem('fundpilot_sector_history_v1'),null);
 const reopened=await createHistoryStore({database:db,storage:legacy}).load();assert.equal(reopened.durable,true);assert.deepEqual(reopened.items,rows);
});
test('quota fallback keeps newest available history and explicitly reports truncation',async()=>{
 const target=storage(JSON.stringify([row(1),row(2)]).length),store=createHistoryStore({database:null,storage:target});
 const result=await store.save([row(1),row(2),row(3)]);assert.equal(result.backend,'localStorage');assert.equal(result.saved_count,2);assert.equal(result.limited,true);
 assert.deepEqual((await store.load()).items.map(r=>r.as_of),['1','2']);
});
test('unavailable storage reports memory-only and saved zero instead of false success',async()=>{
 const store=createHistoryStore({database:null,storage:null});assert.deepEqual(await store.save([row(1)]),{saved_count:0,limited:true,backend:'memory'});
});
test('serialized saves preserve clear and latest-save order',async()=>{
 const db=database(),store=createHistoryStore({database:db,storage:storage()});
 await Promise.all([store.save([row(1)]),store.save([]),store.save([row(2)])]);assert.deepEqual((await store.load()).items,[row(2)]);
 await store.save([]);assert.deepEqual((await store.load()).items,[]);
});
