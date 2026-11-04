const test=require('node:test');
const assert=require('node:assert/strict');
const ui=require('./dist/sector-research.js');
const {boardHarness}=require('./test_helpers/board_presentation.cjs');


function company(changes={}){return {id:'chemicals',title:'化工',group:'industry',status:'ok',score:49.08,score_model:'company_research_v2',score_scope:'company_composite',score_status:'provisional',score_maximum:70,change_pct:-.81,research_tier:{id:'pending',label:'待完成评估'},score_breakdown:{fundamentals:{points:35,coverage_pct:100},trend:{points:14.08,coverage_pct:100},catalysts:{points:null,observed_adjustment:null}},market_risk:{score:58,level:'中风险',status:'complete'},...changes};}

test('directory hides unscored directions while retaining zero scores and staged company evidence',()=>{
 const h=boardHarness({research_scope:'sectors',sector_analysis:[{id:'reference',title:'参考指数',group:'broad',status:'ok',score:0,score_scope:'reference_trend'},company(),{id:'unknown',title:'缺口方向',group:'industry',status:'missing'}],event_analysis:{status:'scheduled'},ai_research:{next_run_at:'2026-11-02T09:25:00+08:00'}});
 const children=h.$('#boardDirectory').children,rows=children.filter(n=>n.tag==='button');
 assert.deepEqual(rows.map(n=>n.dataset.sector),['chemicals','reference']);
 assert.equal(children.filter(n=>n.className==='sector-score-group').length,2);
 assert.equal(rows[0].styles['--sector-tone'],ui.colorForScore(49.08).color);
 assert.notEqual(rows[0].styles['--sector-tone'],ui.colorForScore(null).color);
 const score=rows[0].children.find(n=>n.className==='sector-row-score');assert.match(h.text(score),/49.08 基础 \/ 70 事件待评估/);
 const evidence=rows[0].children.find(n=>n.className==='sector-row-evidence');assert.match(h.text(evidence),/基本面 35.00\/40 走势 14.08\/30 事件 待评估/);
 assert.match(h.text(rows[0].children[3]),/环境 中风险 58\/100/);
 assert.match(h.$('#boardResearchNotice').textContent,/2026-11-02 09:25/);
 assert.match(h.$('#boardCoverageSummary').textContent,/共 2 个方向/);
 assert.doesNotMatch(h.$('#boardCoverageSummary').textContent,/待补数据/);
 assert.deepEqual(h.$('#boardGroups').children.map(n=>n.textContent),['全部方向 2','行业主题 1','宽基指数 1']);
 h.ctx.query='缺口';h.ctx.renderBoards();assert.equal(h.$('#boardDirectory').children.filter(n=>n.tag==='button').length,0);assert.equal(h.$('#sectorEmpty').hidden,false);
 h.ctx.query='';h.ctx.sort='name';h.ctx.renderBoards();assert.equal(h.$('#boardDirectory').children.filter(n=>n.className==='sector-score-group').length,0);
});

test('unscored watchlist shortcuts remain accurate and restored evidence returns to the directory',()=>{
 const h=boardHarness({research_scope:'sectors',sector_analysis:[company(),{id:'unknown',title:'缺口方向',group:'defensive',status:'missing'}]});
 assert.equal(h.ctx.report.sector_analysis.length,2);
 assert.equal(h.ctx.root.SectorWorkspace.openSector('unknown'),true);assert.equal(h.ctx.selected,'unknown');
 assert.deepEqual(h.$('#boardDirectory').children.filter(n=>n.tag==='button').map(n=>n.dataset.sector),['chemicals']);
 h.ctx.report.sector_analysis[1]=ui.normalizeSector({id:'unknown',title:'缺口方向',group:'defensive',status:'ok',score:35});
 h.ctx.group='defensive';h.ctx.renderBoards();assert.deepEqual(h.$('#boardDirectory').children.filter(n=>n.tag==='button').map(n=>n.dataset.sector),['unknown']);
 h.ctx.report.sector_analysis[1]=ui.normalizeSector({id:'unknown',title:'缺口方向',group:'defensive',status:'missing'});
 h.ctx.renderBoards();assert.equal(h.ctx.group,'all');assert.deepEqual(h.$('#boardDirectory').children.filter(n=>n.tag==='button').map(n=>n.dataset.sector),['chemicals']);
});

test('historical directory neutralizes colours and critical signals while preserving original scores',()=>{
 const h=boardHarness({research_scope:'sectors',report_stale:true,sector_analysis:[company({severity:'critical',indicator_reason:'过去风险'})]});
 const row=h.$('#boardDirectory').children.find(n=>n.tag==='button');assert.equal(row.styles['--sector-tone'],ui.colorForScore(null).color);
 assert.equal(h.ctx.report.sector_analysis[0].score,49.08);assert.match(h.$('#boardResearchNotice').textContent,/历史报告/);
 assert.equal(row.children.some(n=>n.className==='sector-indicator risk-critical'),false);
});

test('personal shortcut clears directory filters and opens the requested sector',()=>{
 const h=boardHarness({research_scope:'sectors',sector_analysis:[company(),company({id:'other',title:'另一个方向'})]});
 h.ctx.query='找不到';h.ctx.group='overseas';h.ctx.renderBoards();assert.equal(h.ctx.selected,null);
 assert.equal(h.ctx.root.SectorWorkspace.openSector('chemicals'),true);
 assert.equal(h.ctx.selected,'chemicals');assert.equal(h.ctx.query,'');assert.equal(h.ctx.group,'all');assert.equal(h.$('#boardSearch').value,'');
 assert.equal(h.ctx.root.SectorWorkspace.openSector('invalid-id'),false);
});

test('directory uses the real scarcity assessment and shortcuts clear its filter',()=>{
 const scarcity={version:'scarcity_news_20261101_v2',category:'capacity',status:'reviewed',sector_id:'chemicals',label:'测试产能线索',scope:'仅测试环节',basis:'测试披露',verification:{status:'single_source',claim_type:'fact'},sources:[{title:'测试披露原文',url:'https://www.ndrc.gov.cn/'}]};
 const h=boardHarness({research_scope:'sectors',scarcity_access:{allowed:true},sector_analysis:[company({scarcity}),company({id:'other',title:'另一个方向'})]});
 assert.equal(h.$('#scarcityFilter').parentElement.hidden,false);
 h.$('#scarcityFilter').onclick();
 assert.equal(h.ctx.onlyScarcity,true);
 assert.deepEqual(h.$('#boardDirectory').children.filter(n=>n.tag==='button').map(n=>n.dataset.sector),['chemicals']);
 assert.match(h.text(h.$('#boardDirectory').children.find(n=>n.tag==='button').children[0]),/稀缺线索/);
 assert.equal(h.ctx.root.SectorWorkspace.openSector('other'),true);
 assert.equal(h.ctx.onlyScarcity,false);assert.equal(h.ctx.selected,'other');
 assert.equal(h.$('#boardDirectory').children.filter(n=>n.tag==='button').length,2);
});

