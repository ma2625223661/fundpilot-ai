const test=require('node:test');
const assert=require('node:assert/strict');
const ui=require('../../dist/sector-research.js');
const scarcity=require('../../dist/sector-scarcity.js');
const profile=()=>({version:'scarcity_news_20261101_v2',category:'capacity',status:'reviewed',sector_id:'sector_memory_chip',label:'高端产能约束',scope:'仅HBM制造与先进封装',basis:'供应商披露',verification:{status:'single_source',claim_type:'fact',reason:'仅供测试的来源研判',uncertainties:['单一来源']},strength:{confirmed_score:20,score:null,dimensions:[{title:'扩产难度',points:20,reason:'测试原文依据',fact_excerpt:'产线客户认证周期较长'}]},boundary:'普通模组不等于HBM制造商',checks:['核验收入'],invalidation:['扩产'],sources:[{title:'披露原文',url:'https://news.skhynix.com/en/q3-2026-business-results/'}],reviewed_at:'2026-11-01',review_due_at:'2026-12-01',secret:'drop'});
test('scarcity carries scoped evidence and cannot introduce score or private fields',()=>{
 const s=ui.normalizeSector({id:'sector_memory_chip',status:'ok',score:40,scarcity:profile()});
 assert.equal(s.score,40);assert.equal(s.scarcity.scope,'仅HBM制造与先进封装');assert.equal(s.scarcity.secret,undefined);assert.equal(s.scarcity.score,undefined);assert.ok(scarcity.isMarked(s));
 const wrong=ui.normalizeSector({id:'sector_ai',status:'ok',score:40,scarcity:profile()});assert.equal(wrong.scarcity,null);
});
test('unverified or unsafe source metadata cannot create an active badge',()=>{
 assert.equal(scarcity.normalize({...profile(),sources:[{title:'unsafe',url:'javascript:alert(1)'}]}),null);
 assert.equal(scarcity.normalize({...profile(),status:'guaranteed'}),null);
 assert.equal(scarcity.isMarked({scarcity:{...profile(),status:'needs_review'}}),false);
 assert.equal(scarcity.isMarked({}),false);
});
test('historical snapshots cannot inherit a current news assessment badge',()=>{
 const report=ui.normalizeReport({research_scope:'sectors',report_stale:true,sector_analysis:[{id:'sector_memory_chip',status:'ok',score:40,scarcity:profile()}],snapshot:{}});
 assert.equal(report.sector_analysis[0].scarcity,null);
});

class Element{
 constructor(tag){this.tagName=tag;this.children=[];this.dataset={};this.textContent='';}
 append(...items){this.children.push(...items);}
 set innerHTML(_){throw Error('Untrusted evidence must not be rendered as HTML');}
}
const walk=n=>[n,...n.children.flatMap(walk)];
const copy=n=>walk(n).map(x=>x.textContent).join(' ');
const withDOM=fn=>{const old=global.document;global.document={createElement:tag=>new Element(tag)};try{return fn();}finally{global.document=old;}};
test('partial scores are explained and compact detail avoids repeating the metrics',()=>withDOM(()=>{
 const metric=scarcity.metrics(profile());assert.match(copy(metric),/已支持 20 分/);assert.match(copy(metric),/1\/4项有依据/);assert.match(copy(metric),/待完成评估/);
 const details=scarcity.detail(profile(),true,false);assert.equal(walk(details).filter(n=>n.className==='scarcity-metrics').length,0);assert.match(copy(details),/疑点与局限/);assert.match(copy(details),/单一来源/);assert.match(copy(details),/对应原文/);
}));
test('old hardcoded profiles and opinion-only claims cannot make active news badges',()=>{
 const p=profile();delete p.version;assert.equal(scarcity.normalize(p),null);
 const opinion=profile();opinion.verification.claim_type='forecast';assert.equal(scarcity.isMarked({scarcity:opinion}),false);
 const disputed=profile();disputed.verification.status='disputed';assert.equal(scarcity.isMarked({scarcity:disputed}),false);
});
test('AI text is inert and cross references require safe source URLs',()=>withDOM(()=>{
 const p=profile();p.verification.reason='<img src=x onerror=alert(1)>';p.verification.links=[{relation:'contradicts',title:'unsafe',url:'javascript:alert(1)'},{relation:'supports',title:'source',url:'https://www.ndrc.gov.cn/'}];
 const v=scarcity.normalize(p);assert.equal(v.verification.links.length,1);const detail=scarcity.detail(p);assert.match(copy(detail),/<img src=x onerror=alert\(1\)>/);assert.equal(walk(detail).filter(n=>n.tagName==='img').length,0);
}));
