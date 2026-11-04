'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {test}=require('node:test');
const source=fs.readFileSync(require.resolve('./dist/app.js'),'utf8');
class Element {
  constructor(tag,text='',className=''){this.tag=tag;this.textContent=text ?? '';this.className=className;this.children=[];this.dataset={};}
  append(...nodes){this.children.push(...nodes);}
}
const context=vm.createContext({...require('./dist/board-opportunity.js'),
  array:value=>Array.isArray(value)?value:[],string:(value,fallback='')=>typeof value==='string'?value:fallback,
  el:(tag,text,cls)=>new Element(tag,text,cls),link:(text,url)=>{const a=new Element('a',text);a.href=url;return a;}});
vm.runInContext(source.slice(source.indexOf('function holdingsRatioText('),source.indexOf('function holdingsBoardComparison(')),context);
vm.runInContext(source.slice(source.indexOf('function isYangjibaoBoardReference('),source.indexOf('function renderFundBoards(')),context);
vm.runInContext(source.slice(source.indexOf('function fundCategory('),source.indexOf('function addPlanDetails(')),context);
const text=node=>String(node.textContent || '')+node.children.map(text).join(' ');
const descendants=(node,cls)=>[...(node.className===cls?[node]:[]),...node.children.flatMap(child=>descendants(child,cls))];
const candidate=(code,changes={})=>({code,name:'显示名称 '+code,source_kind:'user_reference',source_label:'养基宝板块分类（用户提供）',
  status:'displayed',requested_board_id:'sector_liquor',actual_board_id:'sector_liquor',actual_board_label:'白酒',
  matched_disclosed_pct:100,report_date:'2026-09-30',source_url:'https://fund.eastmoney.com/'+code+'.html',...changes});

test('Yangjibao board funds show independently verified holding evidence, with duplicates removed',()=>{
  const candidates=[candidate('009941'),candidate('012414'),candidate('002605',{
    status:'reclassified',actual_board_id:'sector_consumer',actual_board_label:'消费',matched_disclosed_pct:71.59}),candidate('009941')];
  const before=JSON.stringify(candidates);
  const rows=context.boardReferenceCandidatesModel({reference_candidates:candidates});
  assert.deepEqual(Array.from(rows,row=>row.code),['009941','012414','002605']);
  assert.equal(rows[0].ratio_text,'100.00%');
  assert.equal(rows[2].ratio_text,'71.59%');
  assert.equal(rows[2].assignment_text,'实际归属：消费');
  assert.match(rows[2].state_label,/其他板块/);
  assert.equal(before,JSON.stringify(candidates));
});

test('unknown holdings never become zero, complete, or a live estimate',()=>{
  for(const ratio of [null,undefined,'90',NaN,Infinity,-1,101]){
    const [row]=context.boardReferenceCandidatesModel({reference_candidates:[candidate('009941',{matched_disclosed_pct:ratio,status:'holdings_pending'})]});
    assert.equal(row.ratio_text,'*****');
    assert.match(row.state_label,/待完善/);
  }
  const [lower]=context.boardReferenceCandidatesModel({reference_candidates:[candidate('009941',{matched_disclosed_pct:200/3,ratio_is_lower_bound:true})]});
  assert.equal(lower.ratio_text,'已确认至少 66.66%');
});

test('three Yangjibao board funds render as a collapsed evidence list distinct from strategy cards',()=>{
  const parent=new Element('section');
  const board={reference_candidates:[candidate('009941'),candidate('012414'),candidate('002605',{
    status:'reclassified',actual_board_label:'消费',matched_disclosed_pct:71.59,reason:'消费匹配比例最高，按持仓归入消费。'})]};
  context.renderBoardReferenceCandidates(parent,board);
  const details=descendants(parent,'board-reference-candidates')[0];
  assert.equal(details.tag,'details');
  assert.equal(details.open,undefined);
  assert.equal(descendants(parent,'board-reference-row').length,3);
  assert.equal(descendants(parent,'strategy-card').length,0);
  const rendered=text(parent);
  for(const expected of ['养基宝板块基金','3 只','009941','012414','002605','100.00%','71.59%','本板块 / 已披露股票','实际归属：消费','2026-09-30','按养基宝板块分类收录；持仓占比来自公开报告。','养基宝板块分类（用户提供）'])assert.ok(rendered.includes(expected),expected);
  assert.ok(!/截图|已同步|已连接|尚未自动同步/.test(rendered));
  assert.equal(descendants(parent,'board-reference-footer')[0].children[1].href,'https://fund.eastmoney.com/009941.html');
});

test('boards without Yangjibao references retain existing rendering',()=>{
  for(const board of [undefined,{}, {reference_candidates:[]},{reference_candidates:[null,{code:'bad'}]}]){
    const parent=new Element('section');
    context.renderBoardReferenceCandidates(parent,board);
    assert.equal(parent.children.length,0);
  }
  assert.match(source,/renderBoardReferenceCandidates\(board,coverage\.find\(item=>item\.id===section\.id\) \|\| section\)/);
  assert.equal(context.isYangjibaoBoardReference({source_kind:'user_reference'}),true);
  assert.equal(context.isYangjibaoBoardReference({source_kind:'yangjibao'}),true);
  assert.equal(context.isYangjibaoBoardReference({source_kind:'other'}),false);
  assert.match(source,/'养基宝分类 · '\+string\(section\.label/);
});

test('Yangjibao membership keeps 002605 in liquor and all three referenced funds before higher exposure outsiders',()=>{
  const fund=(code,ratio,reference=true)=>({code,name:'名称只展示 '+code,
    reference_candidate:reference?candidate(code):undefined,
    board_match:{status:'matched',rule_version:'single_board_holdings_rank_v4',matched_disclosed_pct:ratio},
    board_comparison:[{id:'sector_consumer',matched_disclosed_pct:100},{id:'sector_liquor',matched_disclosed_pct:ratio}]});
  for(const sourceKind of ['user_reference','yangjibao']){
    for(const reverse of [false,true]){
      const references=[fund('009941',100),fund('012414',100),fund('002605',71.59)];
      references.forEach(item=>item.reference_candidate.source_kind=sourceKind);
      const sections=[{id:'sector_liquor',requires_holdings_match:true,funds:[fund('000001',100,false),...references]},
        {id:'sector_consumer',requires_holdings_match:true,funds:[fund('002605',100)]}];
      if(reverse)sections.reverse();
      const record={sections};const original=JSON.stringify(record);
      const result=context.reportSections(record);
      const liquor=result.find(board=>board.id==='sector_liquor');
      assert.deepEqual(Array.from(liquor.funds,item=>item.code),['009941','012414','002605']);
      assert.equal(liquor.funds[2].board_match.matched_disclosed_pct,71.59);
      assert.equal(result.find(board=>board.id==='sector_consumer').funds.length,0);
      assert.equal(result.flatMap(board=>board.funds).filter(item=>item.code==='002605').length,1);
      assert.equal(JSON.stringify(record),original);
    }
  }
});

test('funds without a matching Yangjibao board reference retain exposure first deduplication and ranking',()=>{
  const fund=(code,ratio,sourceKind='other')=>({code,name:'名称只展示 '+code,
    reference_candidate:{source_kind:sourceKind,requested_board_id:'sector_liquor'},
    board_match:{status:'matched',rule_version:'single_board_holdings_rank_v4',matched_disclosed_pct:ratio}});
  const record={sections:[{id:'sector_liquor',requires_holdings_match:true,
    funds:[fund('002605',71.59),fund('000001',55),fund('000002',100),fund('000003',90),fund('000004',80)]},
    {id:'sector_consumer',requires_holdings_match:true,funds:[fund('002605',100)]}]};
  const result=context.reportSections(record);
  assert.deepEqual(Array.from(result[0].funds,item=>item.code),['000002','000003','000004']);
  assert.deepEqual(Array.from(result[1].funds,item=>item.code),['002605']);
});

test('global classification text explains Yangjibao membership separately from independently calculated exposure',()=>{
  for(const record of [{candidate_references:[candidate('002605')]},
    {board_coverage:[{reference_candidates:[candidate('002605')]}]},
    {sections:[{funds:[{reference_candidate:candidate('002605')}]}]}]){
    const copy=context.boardClassificationCopy(record);
    assert.equal(copy.summary,'养基宝分类基金按指定板块展示；其余按持仓归类，真实比例独立计算');
    assert.match(copy.footer,/养基宝分类基金按指定板块展示/);
    assert.match(copy.method,/优先保留来源成员；其余基金按持仓匹配比例最高的板块归类/);
    assert.match(copy.method,/匹配比例＝符合本板块的股票权重÷已披露股票总权重/);
    assert.match(copy.method,/未分类股票仍计入分母/);
    assert.ok(!copy.summary.includes('每只基金仅归入最高匹配板块'));
  }
  for(const record of [{},{candidate_references:[candidate('002605',{source_kind:'other'})]}]){
    const copy=context.boardClassificationCopy(record);
    assert.equal(copy.summary,'每只基金仅归入最高匹配板块');
    assert.match(copy.footer,/每只基金归入持仓匹配最高的一个板块/);
  }
  const html=fs.readFileSync(require.resolve('./dist/index.html'),'utf8');
  assert.doesNotMatch(html,/id="boardClassificationMethod"/);
  assert.doesNotMatch(html,/id="boardClassificationNote"/);
  assert.match(html,/sector-research\.js/);
  assert.doesNotMatch(html,/<script[^>]+src="app\.js"/);
  assert.match(source,/classificationNote\.textContent=classificationCopy\.footer/);
  assert.match(source,/classificationMethod\.textContent=classificationCopy\.method/);
});

test('directly included pending members survive the UI holdings filter and take at most three slots',()=>{
  const pending=(code,board='sector_liquor')=>({code,name:'来源基金 '+code,direct_selection:true,score:null,recommendation_index:null,
    reference_candidate:{code,source_kind:'web_discovery',forced_selection:true,requested_board_id:board},
    board_match:{status:'unknown',matched_disclosed_pct:null}});
  const record={sections:[{id:'sector_liquor',requires_holdings_match:true,funds:[
    {code:'ordinary',name:'普通基金',board_match:{status:'matched',rule_version:'single_board_holdings_rank_v4',matched_disclosed_pct:100}},
    pending('000001'),pending('000002'),pending('000003'),pending('000004')]},
    {id:'sector_consumer',requires_holdings_match:true,funds:[pending('000001','sector_consumer')]}]};
  const before=JSON.stringify(record);
  const sections=context.reportSections(record);
  assert.deepEqual(Array.from(sections[0].funds,f=>f.code),['000001','000002','000003']);
  assert.equal(sections[1].funds.length,1,'an explicit source may include the same fund in two requested boards');
  assert.ok(sections[0].funds.every(f=>f.recommendation_index===null && f.board_match.matched_disclosed_pct===null));
  assert.equal(before,JSON.stringify(record));
  const parent=new Element('section');
  context.renderBoardReferenceCandidates(parent,{reference_candidates:[candidate('000001',{matched_disclosed_pct:null,report_date:null,source_kind:'web_discovery',forced_selection:true,status:'forced_pending'})]});
  assert.match(text(parent),/强制纳入.*\*{5}.*持仓报告日：\*{5}/);
});

test('cached reports materialize source members immediately without turning missing evidence into a score',()=>{
  const ref=candidate('022073',{name:'公开来源基金',source_kind:'web_discovery',forced_selection:true,
    requested_board_id:'overseas_hk_dividend',matched_disclosed_pct:null,report_date:null});
  const record={sections:[{id:'overseas_hk_dividend',label:'港股红利',requires_holdings_match:true,funds:[]}],
    board_coverage:[{id:'overseas_hk_dividend',label:'港股红利',requires_holdings_match:true,reference_candidates:[ref]}]};
  const original=JSON.stringify(record);
  const [section]=context.reportSections(record);
  assert.equal(section.funds.length,1);
  assert.equal(section.funds[0].code,'022073');
  assert.equal(section.funds[0].name,'公开来源基金');
  assert.equal(section.funds[0].recommendation_index,null);
  assert.equal(section.funds[0].board_match.status,'unknown');
  assert.equal(section.funds[0].board_match.matched_disclosed_pct,null);
  assert.equal(JSON.stringify(record),original);
});
