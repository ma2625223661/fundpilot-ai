'use strict';
// Markup contract for the AI schedule form in the live page (previously checked
// alongside the retired fund UI in test_ai_schedule.cjs).
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');

test('index page exposes the AI schedule controls with free integer intervals and optional stop time',()=>{
  const html=fs.readFileSync('dist/index.html','utf8');
  assert.match(html,/aiScheduleMode/);
  assert.match(html,/aiScheduleTime/);
  assert.match(html,/<input id="aiScheduleInterval" type="number" min="1" max="1440" step="1"/);
  assert.doesNotMatch(html,/<select id="aiScheduleInterval"/);
  assert.match(html,/id="aiScheduleEndTime" type="time"/);
  assert.doesNotMatch(html,/id="aiScheduleEndTime"[^>]*value=/);
});

test('index page loads only the sector workspace, never the retired fund UI',()=>{
  const html=fs.readFileSync('dist/index.html','utf8');
  assert.match(html,/sector-research\.js/);
  assert.doesNotMatch(html,/["/]app\.js/);
  assert.doesNotMatch(html,/board-opportunity/);
});
