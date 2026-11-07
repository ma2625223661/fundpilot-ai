const test=require('node:test');
const assert=require('node:assert/strict');
const ui=require('../../dist/sector-research.js');

test('liquidity normalizer keeps an explicit health score and inverse risk score',()=>{
  const s=ui.normalizeMarketLiquidity({score:53,risk_score:47,status:'ok',label:'中性',sample_count:121,annual_rate_pct:1.289,source_ids:['sector_reference:money']});
  assert.equal(s.score,53);assert.equal(s.risk_score,47);assert.equal(s.sample_count,121);assert.equal(s.annual_rate_pct,1.289);
  assert.equal(ui.liquidityPresentation(s).tone,'steady');assert.equal(ui.liquidityPresentation(s).scoreText,'53');
});

test('liquidity boundaries are explicit and stale data cannot retain a score',()=>{
  for(const [score,label,tone] of [[29,'偏紧','tight'],[30,'略紧','slightly-tight'],[45,'中性','steady'],[60,'偏宽','slightly-loose'],[75,'宽松','loose']]){
    const p=ui.liquidityPresentation({score,risk_score:100-score,status:'ok'});
    assert.equal(p.label,label);assert.equal(p.tone,tone);
  }
  const stale=ui.normalizeMarketLiquidity({score:53,risk_score:47,status:'ok'},true);
  assert.equal(stale.score,null);assert.equal(stale.risk_score,null);assert.equal(stale.status,'stale');assert.equal(stale.label,'待更新');
});

test('root report normalization exposes only the public liquidity fields',()=>{
  const r=ui.normalizeReport({research_scope:'sectors',as_of:'2026-10-31T16:00:00+08:00',sector_analysis:[],snapshot:{},strategy:{},market_liquidity:{score:53,status:'ok',secret:'drop'}});
  assert.equal(r.market_liquidity.score,53);assert.equal('secret' in r.market_liquidity,false);
});
