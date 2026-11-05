'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');

function renderSources(ids,report){
  const root={FundPilotCloud:{role:'member'}},source=fs.readFileSync('dist/cloud-account.js','utf8').replace("  const identity = node",'  window.renderAdviceSources=adviceSources; return;\n  const identity = node');
  const node=tag=>({tag,children:[],textContent:'',append(...children){this.children.push(...children);}});
  vm.runInNewContext(source,{window:root,document:{getElementById(){},createElement:node},URL,Map});
  return root.renderAdviceSources(ids,report);
}

test('watchcard evidence shows readable source names and safe source links',()=>{
  const result=renderSources(['official_history_with_a_long_technical_identifier','company:finance'],{snapshot:{sources:[{id:'official_history_with_a_long_technical_identifier',name:'公司行情记录',url:'https://example.test/history'}]},company_evidence:{sources:[{id:'company:finance',title:'最近一期财报',url:'https://example.test/finance'}]}});
  assert.deepEqual(Array.from(result.children,item=>item.textContent),['依据：','公司行情记录','最近一期财报']);
  assert.deepEqual(Array.from(result.children.slice(1),item=>item.tag),['a','a']);
  assert.equal(result.children[1].href,'https://example.test/history');assert.equal(result.children[1].rel,'noopener noreferrer');assert.equal(result.children[1].target,'_blank');
});

test('unnamed or unknown sources use short labels and unsafe URLs are never links',()=>{
  const result=renderSources(['raw:unknown:very:long','unsafe:source','unnamed'],{snapshot:{sources:[{id:'unsafe:source',name:'公告原文',url:'javascript:alert(1)'},{id:'unnamed',url:'data:text/html,unsafe'}]}});
  assert.deepEqual(Array.from(result.children,item=>item.textContent),['依据：','来源 1','公告原文','来源 3']);
  assert.equal(result.children.some(item=>item.tag==='a'),false);assert.equal(result.children.some(item=>'href' in item),false);
});
