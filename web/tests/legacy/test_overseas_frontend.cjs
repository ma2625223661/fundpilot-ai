const test=require('node:test');
const assert=require('node:assert/strict');
const ui=require('../../src/lib/legacy/sector-research.js');
test('overseas stock identity and currency survive normalization while invalid codes are rejected',()=>{
 const company=ui.normalizeCompanyEvidence({sector_leaders:{x:[
 {ts_code:'00700.HK',quote:{currency:'HKD',close:520},financials:{currency:'CNY',eps:4.3},membership_evidence:{snapshot_date:'2026-10-30',evidence_type:'official_business'}},
 {ts_code:'MSFT.US',quote:{currency:'USD',close:400},financials:{currency:'USD',eps:3}},
 {ts_code:'../evil.US',quote:{currency:'USD'}}]}});
 assert.equal(company.sector_leaders.x.length,2);
 assert.equal(company.sector_leaders.x[0].quote.currency,'HKD');
 assert.equal(company.sector_leaders.x[0].financials.currency,'CNY');
 assert.equal(company.sector_leaders.x[0].membership_evidence.evidence_type,'official_business');
 const index=ui.normalizeCustomIndex({constituents:[{code:'00700.HK'},{code:'MSFT.US'},{code:'../evil.US'}]});
 assert.deepEqual(index.constituents.map(r=>r.code),['00700.HK','MSFT.US']);
});
