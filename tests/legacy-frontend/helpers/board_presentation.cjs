const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const ui=require('../../../dist/sector-research.js');
const source=fs.readFileSync(path.join(__dirname,'../../../dist/sector-research.js'),'utf8');
const scarcitySource=fs.readFileSync(path.join(__dirname,'../../../dist/sector-scarcity.js'),'utf8');

function boardHarness(raw){
 const nodes=new Map();
 class Node{
  constructor(tag,text='',className=''){this.tag=tag;this.textContent=text||'';this.className=className||'';this.children=[];this.dataset={};this.attributes={};this.styles={};this.style={setProperty:(k,v)=>this.styles[k]=v};}
  append(...items){for(const item of items){item.parentElement=this;this.children.push(item);}}replaceChildren(){for(const item of this.children)item.parentElement=null;this.children=[];}setAttribute(k,v){this.attributes[k]=v;}scrollIntoView(){}
 }
 const $=id=>{if(!nodes.has(id))nodes.set(id,new Node('div'));return nodes.get(id);};
 const filterGroup=new Node('div');filterGroup.append($('#scarcityFilter'));
 const ctx=vm.createContext({...ui,URL,$,report:ui.normalizeReport(raw),selected:null,group:'all',query:'',sort:'score',onlyScarcity:false,groups:{industry:'行业主题',broad:'宽基指数',overseas:'海外市场',style:'风格策略',defensive:'防守资产',commodity:'商品资产',other:'其他方向'},finite:Number.isFinite,txt:(v,f='')=>typeof v==='string'?v:f,num:(v,d=2)=>Number.isFinite(v)?v.toFixed(d):'*****',el:(...args)=>new Node(...args),setText:(id,value)=>$('#'+id).textContent=value,renderDetail:()=>{},refreshResearchHistory:async()=>true,indicatorNode:indicator=>new Node('i',indicator.symbol,'sector-indicator '+indicator.className)});
 ctx.root={};ctx.document={dispatchEvent:()=>{},createElement:tag=>new Node(tag)};ctx.CustomEvent=class{constructor(type){this.type=type;}};ctx.view=()=>{};
 vm.runInContext(scarcitySource,ctx);ctx.scarcityUI=ctx.FundPilotScarcity;
 const toneStart=source.indexOf('  function applyTone('),toneEnd=source.indexOf('  function list(',toneStart);
 vm.runInContext(source.slice(toneStart,toneEnd),ctx);
 const start=source.indexOf('  function renderBoards()'),end=source.indexOf("  $('#boardSearch')",start);
 vm.runInContext(source.slice(start,end),ctx);ctx.renderBoards();
 return {ctx,nodes,$,text:n=>[n.textContent,...n.children.map(child=>[child.textContent,...child.children.map(c=>c.textContent)].join(' '))].join(' ')};
}

module.exports={boardHarness};
