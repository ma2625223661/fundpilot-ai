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

test('login username field accepts a plain handle or an email address',()=>{
  const html=fs.readFileSync('dist/login.html','utf8');
  const input=html.match(/<input id="username"[^>]*>/)[0];
  assert.match(input,/maxlength="64"/);
  // Browsers compile the pattern attribute with the v flag and anchor it.
  const re=new RegExp('^(?:'+input.match(/pattern="([^"]*)"/)[1]+')$','v');
  for(const ok of ['owner','abc_123','ma2625223661@gmail.com','first.last+tag@mail.example.cn'])assert.ok(re.test(ok),ok);
  for(const bad of ['ab','has space','name@host','@gmail.com','a@b.c'])assert.ok(!re.test(bad),bad);
});
