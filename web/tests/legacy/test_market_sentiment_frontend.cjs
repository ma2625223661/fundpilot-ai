const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ui = require('../../src/lib/legacy/sector-research.js');

function sentiment(changes = {}) {
  return {
    score: 52.25, label: 'incorrect server label', status: 'ok', coverage_pct: 100,
    as_of: '2026-10-31T15:22:50+08:00', sample_date: '2026-10-30',
    history_date: '2026-10-30', sample_count: 300, candidate_count: 310, index_count: 4,
    components: [
      {id: 'breadth', label: '样本上涨广度', weight: .4, score: 50, count: 300, status: 'ok', note: '去重A股', as_of: '2026-10-30', source_ids: ['quotes']},
      {id: 'index_strength', label: '主要指数强弱', weight: .3, score: 40, count: 4, status: 'ok', source_ids: ['indices']},
      {id: 'ma20_participation', label: '20日均线参与度', weight: .3, score: 67.5, count: 295, status: 'ok', source_ids: ['history']},
    ],
    source_ids: ['quotes', 'indices', 'history'], missing: [],
    method: '上涨广度40% + 指数强弱30% + 均线参与度30%', scope: 'A股样本代理',
    summary: '分数反映样本活跃度。', ...changes,
  };
}

function report(value, stale = false) {
  return ui.normalizeReport({
    research_scope: 'sectors', as_of: '2026-10-31T15:22:50+08:00',
    report_stale: stale, sector_analysis: [], market_sentiment: value,
    snapshot: {market: [], sources: []},
  });
}

test('sentiment accepts only finite numeric scores between zero and one hundred', () => {
  for (const score of [-1, 100.01, NaN, Infinity, -Infinity, '50', undefined, null]) {
    const s = ui.normalizeMarketSentiment(sentiment({score}));
    assert.equal(s.score, null, String(score));
    assert.equal(ui.sentimentPresentation(s).tone, 'unknown');
    assert.equal(ui.sentimentPresentation(s).scoreText, '—');
  }
  for (const score of [0, 0.01, 52.25, 100]) {
    assert.equal(ui.normalizeMarketSentiment(sentiment({score})).score, score);
  }
});

test('sentiment strictly whitelists fields and components instead of retaining private payloads', () => {
  const input = sentiment({api_key: 'SECRET', private: {token: 'SECRET'}, raw_samples: ['SECRET']});
  input.components[0] = {...input.components[0], api_key: 'SECRET', raw_quote: {secret: 'SECRET'}};
  input.components.push({id: 'unknown_indicator', label: 'SECRET', score: 100, weight: 1});
  const s = ui.normalizeMarketSentiment(input);
  assert.doesNotMatch(JSON.stringify(s), /SECRET|api_key|raw_quote|raw_samples|unknown_indicator/);
  assert.deepEqual(Object.keys(s).sort(), [
    'score', 'status', 'label', 'coverage_pct', 'as_of', 'sample_date', 'history_date',
    'sample_count', 'candidate_count', 'index_count', 'components', 'source_ids',
    'missing', 'method', 'scope', 'summary',
  ].sort());
  assert.deepEqual(Object.keys(s.components[0]).sort(), [
    'id', 'label', 'weight', 'score', 'count', 'status', 'note', 'as_of', 'source_ids',
  ].sort());
  assert.equal(input.api_key, 'SECRET');
});

test('duplicate components cannot increase displayed weight and model weights stay fixed', () => {
  const input = sentiment();
  input.components[0].weight = 9;
  input.components[1].weight = -1;
  input.components.push({...input.components[0], score: 100});
  const s = ui.normalizeMarketSentiment(input);
  assert.deepEqual(s.components.map(c => [c.id, c.weight]), [
    ['breadth', .4], ['index_strength', .3], ['ma20_participation', .3],
  ]);
  assert.equal(s.components[0].score, 50);
  assert.equal(s.components.reduce((n, c) => n + c.weight, 0), 1);
});

test('unavailable, unrecognized and stale statuses never retain a current total score', () => {
  for (const status of ['unavailable', 'error', 'expired', '', undefined]) {
    const s = ui.normalizeMarketSentiment(sentiment({status}));
    assert.equal(s.status, 'unavailable');
    assert.equal(s.score, null);
  }
  const stale = ui.normalizeMarketSentiment(sentiment({status: 'stale'}));
  assert.equal(stale.score, null);
  assert.equal(stale.label, '待更新');
  assert.ok(stale.components.every(c => c.score === null && c.status === 'stale'));
  assert.match(stale.summary, /历史/);
});

test('report stale flag clears sentiment and repeated normalization cannot restore it', () => {
  const old = report(sentiment(), true);
  assert.equal(old.market_sentiment.status, 'stale');
  assert.equal(old.market_sentiment.score, null);
  const again = ui.normalizeReport(old);
  assert.equal(again.market_sentiment.score, null);
  assert.ok(again.market_sentiment.components.every(c => c.score === null));
  assert.equal(ui.sentimentPresentation(again.market_sentiment).statusLabel, '历史 / 待更新');
  assert.equal(ui.normalizeMarketSentiment(old.market_sentiment).score, null);
});

test('all five emotion boundaries are exact and independent from company research tiers', () => {
  const rows = [
    [0, '低迷', 'cold'], [19.999, '低迷', 'cold'],
    [20, '偏冷', 'cool'], [39.999, '偏冷', 'cool'],
    [40, '平稳', 'steady'], [59.999, '平稳', 'steady'],
    [60, '活跃', 'active'], [79.999, '活跃', 'active'],
    [80, '过热', 'hot'], [100, '过热', 'hot'],
  ];
  for (const [score, label, tone] of rows) {
    const view = ui.sentimentPresentation(sentiment({score}));
    assert.equal(view.label, label, String(score));
    assert.equal(view.tone, tone, String(score));
    assert.equal(view.scoreText, score.toFixed(2));
  }
  assert.equal(ui.sentimentPresentation(sentiment({score: 65})).label, '活跃');
  assert.equal(ui.sentimentPresentation(sentiment({score: 100})).label, '过热');
  assert.deepEqual(ui.colorForScore(65), ui.colorForScore(100));
  assert.notEqual(ui.sentimentPresentation(sentiment({score: 65})).tone,
    ui.sentimentPresentation(sentiment({score: 100})).tone);
});

test('less than seventy percent usable component weight suppresses total instead of filling missing data', () => {
  for (const coverage_pct of [0, 40, 60, 69.999, -1, 101, '100', NaN, null]) {
    assert.equal(ui.normalizeMarketSentiment(sentiment({status: 'partial', coverage_pct})).score, null,
      String(coverage_pct));
  }
  const partial = ui.sentimentPresentation(sentiment({status: 'partial', coverage_pct: 70}));
  assert.equal(partial.score, 52.25);
  assert.match(partial.statusLabel, /部分数据/);
});

test('counts, missing reasons and source ids reject malformed types and remove duplicates', () => {
  const s = ui.normalizeMarketSentiment(sentiment({
    sample_count: -1, candidate_count: 2.5, index_count: 99,
    missing: ['历史不足', '历史不足', '', ' ', null, {reason: 'bad'}],
    source_ids: ['quotes', 'quotes', null, 5, ''],
  }));
  assert.equal(s.sample_count, 0);
  assert.equal(s.candidate_count, 0);
  assert.equal(s.index_count, 4);
  assert.deepEqual(s.missing, ['历史不足']);
  assert.deepEqual(s.source_ids, ['quotes']);
  for (const index_count of [-1, NaN, Infinity, '4', 1.5]) {
    assert.equal(ui.normalizeMarketSentiment(sentiment({index_count})).index_count, 0);
  }
});

function renderHarness(value) {
  const source = fs.readFileSync('./dist/sector-research.js', 'utf8');
  const nodes = new Map();
  class Node {
    constructor(tag = 'div', text, className) {
      this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {};
      this.style = {}; this.hidden = false; this.attributes = new Map();
      this.textContent = text === undefined ? '' : text; this.className = className || '';
    }
    append(...items) { this.children.push(...items); }
    replaceChildren(...items) { this.children = [...items]; }
    setAttribute(name, value) { this.attributes.set(name, value); }
    removeAttribute(name) { this.attributes.delete(name); }
    set innerHTML(value) { throw new Error('untrusted HTML insertion: ' + value); }
  }
  const $ = id => {if (!nodes.has(id)) nodes.set(id, new Node()); return nodes.get(id);};
  const context = vm.createContext({
    $, report: value, URL, sentimentPresentation: ui.sentimentPresentation,
    setText: (id, text) => {$('#' + id).textContent = text;},
    el: (tag, text, className) => new Node(tag, text, className),
    finite: n => typeof n === 'number' && Number.isFinite(n),
    arr: a => Array.isArray(a) ? a : [],
    num: (n, d = 2) => Number.isFinite(n) ? n.toFixed(d) : '*****', stamp: s => s || '*****',
  });
  vm.runInContext(source.match(/^  const safeUrl = .*$/m)[0], context);
  vm.runInContext(source.match(/^  function link\(.*$/m)[0], context);
  const start = source.indexOf('  function renderSentiment()');
  const end = source.indexOf('  function renderMarket()', start);
  assert.ok(start > 0 && end > start);
  vm.runInContext(source.slice(start, end), context);
  return {$, context, run: () => context.renderSentiment()};
}
function descendants(node) {return node.children.flatMap(child => [child, ...descendants(child)]);}

test('actual sentiment render inserts evidence as text and permits only safe source links', () => {
  const malicious = '<img src=x onerror=alert(1)>';
  const input = sentiment({summary: malicious, method: malicious, missing: [malicious], source_ids: ['good', 'bad']});
  input.components[0].label = malicious;
  input.components[0].note = malicious;
  const r = report(input);
  r.snapshot.sources = [
    {id: 'good', name: 'official source', url: 'https://example.com/evidence'},
    {id: 'bad', name: malicious, url: 'javascript:alert(1)'},
  ];
  const h = renderHarness(r); h.run();
  assert.equal(h.$('#sentimentSummary').textContent, malicious);
  assert.equal(h.$('#sentimentMethod').textContent, malicious);
  assert.ok(descendants(h.$('#sentimentComponents')).some(n => n.textContent === malicious));
  const links = h.$('#sentimentSources').children;
  assert.equal(links[0].tagName, 'A');
  assert.equal(links[0].href, 'https://example.com/evidence');
  assert.equal(links[0].rel, 'noopener noreferrer');
  assert.equal(links[1].tagName, 'SPAN');
  assert.equal(links[1].href, undefined);
  assert.equal(links[1].textContent, malicious);
  assert.equal(h.$('#sentimentCard').dataset.tone, 'steady');
  assert.equal(h.$('#sentimentValue').textContent, '52.25');
  assert.equal(h.$('#sentimentMeter').attributes.get('aria-valuenow'), '52.25');
});

test('meter removes an earlier numeric value and hides its marker when current data becomes unavailable', () => {
  const h = renderHarness(report(sentiment())); h.run();
  assert.equal(h.$('#sentimentMarker').hidden, false);
  assert.equal(h.$('#sentimentMarker').style.left, '52.25%');
  h.context.report = report(sentiment({status: 'unavailable'})); h.run();
  assert.equal(h.$('#sentimentValue').textContent, '—');
  assert.equal(h.$('#sentimentMarker').hidden, true);
  assert.equal(h.$('#sentimentMeter').attributes.has('aria-valuenow'), false);
  assert.equal(h.$('#sentimentMeter').attributes.get('aria-valuetext'), '数据待补充');
  assert.equal(h.$('#sentimentCard').dataset.tone, 'unknown');
  h.context.report = report(sentiment(), true); h.run();
  assert.equal(h.$('#sentimentMarker').hidden, true);
  assert.equal(h.$('#sentimentLabel').textContent, '待更新');
  assert.match(h.$('#sentimentSummary').textContent, /历史/);
});
