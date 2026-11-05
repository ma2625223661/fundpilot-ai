const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const flush=()=>new Promise(resolve=>setImmediate(resolve));

function setup(){
  const nodes=new Map(),calls=[],events={},state={preference:null,fail:false};
  class Element{
    constructor(tag){this.tag=tag;this.children=[];this.attributes={};this.disabled=false;this.dataset={};}
    set id(value){this._id=value;nodes.set(value,this);}get id(){return this._id;}
    get firstChild(){return this.children[0];}get lastChild(){return this.children.at(-1);}
    detach(){if(!this.parentElement)return;const siblings=this.parentElement.children;siblings.splice(siblings.indexOf(this),1);this.parentElement=null;}
    append(...items){for(const item of items){item.detach();item.parentElement=this;this.children.push(item);}}
    replaceChildren(...items){for(const item of this.children)item.parentElement=null;this.children=[];this.append(...items);}
    before(...items){if(!this.parentElement)return;const parent=this.parentElement;for(const item of items){item.detach();const index=parent.children.indexOf(this);parent.children.splice(index,0,item);item.parentElement=parent;}}
    after(...items){if(!this.parentElement)return;const parent=this.parentElement;let previous=this;for(const item of items){item.detach();const index=parent.children.indexOf(previous);parent.children.splice(index+1,0,item);item.parentElement=parent;previous=item;}}
    setAttribute(k,v){this.attributes[k]=v;}
    addEventListener(){}scrollIntoView(){}
  }
  const dash=new Element('section');dash.id='dash';const watch=new Element('section');watch.id='cloudWatchlist';dash.append(watch);
  const summary=()=>({status:'active',credits_remaining:4,unlocked_count:0,can_unlock:true,preferred_reasoning_effort:state.preference});
  const root={FundPilotCloud:{role:'member'},SectorWorkspace:{refreshPersonalReport:async()=>calls.push(['projection'])}};
  const context=vm.createContext({window:root,AbortSignal,Date,Set,console,document:{hidden:false,createElement:tag=>new Element(tag),getElementById:id=>nodes.get(id),addEventListener:(key,fn)=>events[key]=fn},
    fetch:async(path,options)=>{calls.push([path,options]);if(path==='/api/me/ai-preference'){
      if(state.fail)return {ok:false,json:async()=>({error:'保存失败，请重试'})};
      state.preference=JSON.parse(options.body).reasoning_effort;
    }return {ok:true,json:async()=>({subscription:summary(),items:[]})};}
  });
  vm.runInContext(fs.readFileSync('dist/ai-subscription.js','utf8'),context);
  root.FundPilotSubscriptions.mountProfile();
  const all=(n)=>[n,...n.children.flatMap(all)];
  const cards=()=>all(nodes.get('aiSubscription')).filter(n=>n.tag==='button'&&n.dataset.effort);
  const feedback=()=>all(nodes.get('aiSubscription')).findLast(n=>n.className==='cloud-status');
  return {root,calls,state,cards,feedback,dash,watch};
}

test('a member can choose both reasoning levels and save only a personal preference',async()=>{
  const ui=setup();await flush();
  assert.equal(ui.dash.children[ui.dash.children.indexOf(ui.watch)+1].id,'aiSubscription');
  assert.deepEqual(ui.cards().map(n=>n.attributes['aria-pressed']),['false','false']);
  await ui.cards()[0].onclick();
  assert.equal(ui.state.preference,'medium');
  assert.deepEqual(ui.cards().map(n=>n.attributes['aria-pressed']),['true','false']);
  await ui.cards()[1].onclick();
  assert.equal(ui.state.preference,'xhigh');
  assert.deepEqual(ui.cards().map(n=>n.attributes['aria-pressed']),['false','true']);
  const writes=ui.calls.filter(c=>c[1]?.method==='POST');
  assert.deepEqual(writes.map(c=>c[0]),['/api/me/ai-preference','/api/me/ai-preference']);
  assert.deepEqual(writes.map(c=>JSON.parse(c[1].body)),[{reasoning_effort:'medium'},{reasoning_effort:'xhigh'}]);
  assert.equal(ui.calls.filter(c=>c[0]==='projection').length,2);
  assert.match(ui.feedback().textContent,/未扣点/);
});
test('failed choice keeps the saved option and shows an actionable error',async()=>{
  const ui=setup();await flush();await ui.cards()[0].onclick();ui.state.fail=true;
  await ui.cards()[1].onclick();
  assert.deepEqual(ui.cards().map(n=>n.attributes['aria-pressed']),['true','false']);
  assert.match(ui.feedback().textContent,/保存失败/);
  assert.equal(ui.cards().some(n=>n.disabled),false);
  assert.equal(ui.calls.filter(c=>c[0]==='projection').length,1);
});
