'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {test} = require('node:test');
const source = fs.readFileSync(require.resolve('./dist/app.js'), 'utf8');
class Element {
  constructor(tag, text = '', cls = '') { this.tag = tag; this.textContent = text ?? ''; this.className = cls; this.children = []; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; this.textContent = ''; }
  setAttribute() {}
}
const elements = new Map();
const renders = [];
const context = vm.createContext({
  $: id => { if (!elements.has(id)) elements.set(id, new Element('div')); return elements.get(id); },
  el: (tag, text, cls) => new Element(tag, text, cls),
  link: text => new Element('a', text),
  array: value => Array.isArray(value) ? value : [],
  string: (value, fallback = '') => typeof value === 'string' ? value : fallback,
  stamp: value => value || '时间未提供', number: value => String(value), percent: value => String(value),
  lines() {}, currentSnapshot: null,
  latestAutoState: null, updateScheduleFields() {}, readable: value => String(value),
  running: false, manualReportActive: false, displayedAutoId: '', prefs: {}, history: [], connected: false,
  validateResponse() {}, render: record => renders.push(record), renderAutoSummary() {},
  compactRecord: value => value, persistHistory() {}, renderHistory() {}, status() {}, renderAiResearch() {}
});
vm.runInContext(source.slice(source.indexOf('function isFundAnnouncementEvidence('), source.indexOf('function render(record')), context);
vm.runInContext(source.slice(source.indexOf('function renderAutoState('), source.indexOf('async function pollAuto(')), context);
const text = node => String(node.textContent || '') + node.children.map(text).join(' ');

test('data page hides identified fund announcements while retaining other source states and news', () => {
  const snapshot = {
    sources: [
      {id: 'announcements_000001', name: '基金公告旧标识', status: 'ok'},
      {id: 'fund:000002:announcements', name: '基金公告新标识', status: 'ok'},
      {id: 'fund_000001', name: '基金净值', status: 'ok'},
      {id: 'holdings_000001', name: '基金持仓', status: 'ok'},
      {id: 'regulator_notices', name: '监管公告', status: 'ok'},
      {id: 'market_news', name: '财经新闻', status: 'ok'}
    ],
    news: [
      {source_id: 'announcements_000001', title: '基金公告原文甲'},
      {source_id: 'fund:000002:announcements', title: '基金公告原文乙'},
      {source_id: 'regulator_notices', title: '监管公告原文', category: '监管发布'},
      {source_id: 'market_news', title: '市场新闻原文', category: '财经新闻'},
      {source_id: 'announcements_market', title: '其他公告原文', category: '公告'}
    ]
  };
  const original = structuredClone(snapshot);
  context.renderSnapshot(snapshot, []);
  const sources = text(elements.get('#sourceList'));
  assert.doesNotMatch(sources, /基金公告旧标识|基金公告新标识/);
  for (const label of ['基金净值', '基金持仓', '监管公告', '财经新闻']) assert.ok(sources.includes(label));
  const news = text(elements.get('#newsList'));
  assert.doesNotMatch(news, /基金公告原文甲|基金公告原文乙/);
  for (const title of ['监管公告原文', '市场新闻原文', '其他公告原文']) assert.ok(news.includes(title));
  assert.equal(elements.get('#newsCount').textContent, '3 条 · 当前快照');
  assert.deepEqual(snapshot, original, 'display filtering must leave research evidence and export data intact');
  assert.equal(context.currentSnapshot, snapshot);
});

test('schema upgrade refreshes automatic boards even when the report timestamp is unchanged', () => {
  const state = {status: 'ready', completed_at: '2026-10-30T14:00:00+08:00', report: {
    board_schema_version: 4, strategy: {regime: {mode: 'cautious'}}, ai_research: {status: 'completed', analyzed_count: 2}
  }};
  context.renderAutoState(state);
  context.renderAutoState(state);
  assert.equal(renders.length, 1);
  context.renderAutoState({...state, report: {...state.report, board_schema_version: 5}});
  assert.equal(renders.length, 2);
  assert.equal(renders[1].board_schema_version, 5);
  assert.equal(context.history.length, 1, 'schema refresh should not duplicate the saved report');
});
