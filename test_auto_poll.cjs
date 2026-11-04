const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('dist/app.js', 'utf8');

function setup(fetch) {
  const nodes = new Map();
  const renders = [];
  const context = vm.createContext({
    AbortSignal, Date, fetch, connected: true, autoPollBusy: false, autoReportBusy: false,
    autoTimer: null, loadedAutoReportVersion: '', loadedAutoReport: null, latestAutoState: null,
    current: null, manualReportActive: false, aiConfigBusy: true, aiConfigCheckedAt: Date.now(),
    $: selector => {
      if (!nodes.has(selector)) nodes.set(selector, {hidden: true, textContent: '', style: {}});
      return nodes.get(selector);
    },
    setTimeout: () => 1, clearTimeout() {}, status() {}, loadAiConfig() {},
    renderAutoState: state => { context.latestAutoState = state; renders.push(state); },
    renderFundBoards() {}, renderAutoSummary() {}
  });
  vm.runInContext(source.slice(source.indexOf('async function loadAutoReport('), source.indexOf("$('#autoRefresh').onclick=")), context);
  return {context, nodes, renders};
}
const reply = body => ({ok: true, json: async () => body});
const summary = (version='v1') => ({status:'ready', completed_at:'2026-10-30T18:22:19+08:00',
  has_report:true, report_version:version, report_stale:false, report:null});
const flush = () => new Promise(resolve => setImmediate(resolve));

test('slow report downloads do not block heartbeats or cause duplicate downloads', async () => {
  let finish, reportCalls=0, statusCalls=0;
  const pending = new Promise(resolve => {finish=resolve;});
  const {context, nodes, renders} = setup(async path => {
    if (path.includes('summary=1')) {statusCalls++; return reply(summary());}
    reportCalls++;
    return pending;
  });
  await context.pollAuto();
  assert.equal(context.autoReportBusy, true);
  assert.equal(context.autoPollBusy, false);
  await context.pollAuto();
  assert.equal(statusCalls, 2);
  assert.equal(reportCalls, 1);
  finish(reply({...summary(), report:{engine:'automatic'}}));
  await flush();
  assert.equal(context.loadedAutoReportVersion, 'v1');
  assert.equal(nodes.get('#autoReportNotice').hidden, true);
  await context.pollAuto();
  assert.equal(reportCalls, 1, 'unchanged reports are reused, not re-downloaded');
  assert.ok(renders.at(-1).report, 'a recovered heartbeat restores cached report labels');
});

test('report failure keeps the heartbeat healthy and retries the report separately', async () => {
  let reportCalls=0;
  const {context, nodes} = setup(async path => {
    if (path.includes('summary=1')) return reply(summary());
    if (++reportCalls === 1) throw new Error('slow report');
    return reply({...summary(), report:{engine:'automatic'}});
  });
  await context.pollAuto();
  await flush();
  assert.equal(context.connected, true);
  assert.match(nodes.get('#autoReportNotice').textContent, /报告加载尚未完成/);
  assert.notEqual(nodes.get('#autoStatus')?.textContent, '自动研究状态暂时不可用');
  await context.pollAuto();
  await flush();
  assert.equal(reportCalls, 2);
  assert.equal(context.loadedAutoReportVersion, 'v1');
});

test('an old in-flight report cannot overwrite a newer report version', async () => {
  let finish;
  const {context, renders} = setup(() => new Promise(resolve => {finish=resolve;}));
  context.latestAutoState = summary();
  const loading = context.loadAutoReport(context.latestAutoState);
  context.latestAutoState = summary('v2');
  finish(reply({...summary(), report:{engine:'automatic'}}));
  await loading;
  assert.equal(context.loadedAutoReportVersion, '');
  assert.equal(renders.length, 0);
  assert.equal(context.autoReportBusy, false);
});

test('old actionable cards are suspended while a changed report is loading', async () => {
  const {context} = setup(async () => {throw new Error('offline report');});
  context.current = {engine:'automatic', report_stale:false};
  context.latestAutoState = summary('v2');
  await context.loadAutoReport(context.latestAutoState);
  assert.equal(context.current.report_stale, true);
  assert.equal(context.loadedAutoReportVersion, '');
});
