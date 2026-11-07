'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {sourceRecordState,sourceOverview,sourceIssueOverview,selectSourceRecords}=require('../../src/lib/legacy/sector-research.js');
const records=[
  {id:'a',name:'腾讯行情',status:'ok',as_of:'2020-01-01'},
  {id:'b',name:'官方公告',status:'partial'},
  {id:'c',name:'公司财务',status:'error',error:'连接超时'},
  {id:'d',name:'旧公告',status:'stale'},
  {id:'e',name:'Shibor',status:'unknown'},
];
test('retrieval summary counts incomplete and stale separately without asserting freshness',()=>{
  assert.deepEqual(sourceOverview(records),{total:5,ok:1,partial:1,attention:2,unknown:1});
  assert.equal(sourceRecordState(records[0]),'ok','display keeps reported retrieval status; original date must remain visible');
  assert.equal(sourceRecordState({status:'unexpected'}),'unknown');
  assert.deepEqual(sourceOverview(null),{total:0,ok:0,partial:0,attention:0,unknown:0});
});
test('source search and status filter combine across all records without changing the report',()=>{
  const original=structuredClone(records);
  assert.deepEqual(selectSourceRecords(records,' 连接 ','attention').map(x=>x.id),['c']);
  assert.deepEqual(selectSourceRecords(records,'SHIBOR').map(x=>x.id),['e']);
  assert.deepEqual(selectSourceRecords(records,'公告','ok'),[]);
  assert.deepEqual(selectSourceRecords(records,'','attention').map(x=>x.id),['c','d']);
  assert.deepEqual(records,original);
});
test('issue summary groups reported failures without inventing HTTP status or counting successful sources',()=>{
  assert.deepEqual(sourceIssueOverview([
    {status:'error',error:'HTTP采集总时间超限'},
    {status:'error',error:'HTTPError'},
    {status:'error',error:'连接失败或格式变化'},
    {status:'partial',error:'已取得历史，但未覆盖最新收盘日'},
    {status:'stale'},
    {status:'error'},
    {status:'ok',error:'曾经超时，已恢复'},
  ]),{timeout:1,http:1,connection:1,coverage:2,other:1});
});
