const test=require('node:test');
const assert=require('node:assert/strict');
const {signalReading,scoreReading}=require('./dist/research-cycle.js');

test('macro readings follow source thresholds, including equality and the neutral band',()=>{
  const demand=value=>signalReading({id:'demand',status:'ready',value});
  assert.equal(demand(49.9).tone,'caution');
  assert.equal(demand(50).tone,'positive');
  const funding=change_bp=>signalReading({id:'funding',status:'ready',value:1.2,change_bp});
  assert.equal(funding(-5).label,'短端资金趋宽');
  assert.equal(funding(5).label,'短端资金趋紧');
  assert.equal(funding(-4.99).tone,'neutral');
  assert.equal(funding(4.99).tone,'neutral');
});

test('unavailable and nonnumeric observations never acquire an economic reading',()=>{
  for(const value of [undefined,null,NaN,Infinity,'50'])
    assert.equal(signalReading({id:'demand',status:'ready',value}).tone,'pending');
  assert.equal(signalReading({id:'demand',status:'missing',value:52}).tone,'pending');
});

test('partial scores state what is missing and never introduce a 100-point denominator',()=>{
  const value=scoreReading({score:null,known_score:54,fundamentals:30,trend:24,catalysts:null});
  assert.equal(value.state,'partial');
  assert.equal(value.maximum,'');
  assert.match(value.copy,/待补事件/);
  assert.match(value.copy,/暂不划档/);
  assert.equal(scoreReading({score:0,tier:'规避'}).state,'complete');
  assert.equal(scoreReading({score:0,tier:'规避'}).maximum,'/ 100');
  assert.equal(scoreReading({score:null,known_score:null}).state,'pending');
});
