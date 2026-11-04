'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const helper=fs.readFileSync('dist/phone-verification.js','utf8'),login=fs.readFileSync('dist/login.js','utf8');
class Element {
  constructor(tag='div'){this.tagName=tag;this.children=[];this.value='';this.textContent='';this.hidden=false;this.disabled=false;this.listeners={};this.attributes={};}
  append(...children){this.children.push(...children);}
  addEventListener(name,fn){this.listeners[name]=fn;}
  setAttribute(name,value){this.attributes[name]=value;}
  focus(){this.focused=true;}
}
function runtime(request) {
  let now=1000;const timers=new Map();let id=0;
  const context=vm.createContext({window:{},Date:{now:()=>now},setTimeout:fn=>{timers.set(++id,fn);return id;},clearTimeout:key=>timers.delete(key)});
  vm.runInContext(helper,context);
  const phone=new Element(),code=new Element(),send=new Element(),feedback=new Element();
  const verification=context.window.FundPilotPhone.create({phone,code,send,feedback,request});
  return {context,phone,code,send,feedback,verification,advance(ms){now+=ms;[...timers.values()].forEach(fn=>fn());}};
}
const response={challenge_id:'test-challenge',retry_after:60,expires_in:300,message:'验证码请求已提交'};
test('no automatic SMS send, disabled state is honest, and invalid input never sends',async()=>{
  let calls=0;const h=runtime(async()=>{calls++;return response;});
  assert.equal(h.send.disabled,true);await h.send.onclick();assert.equal(calls,0);
  h.verification.setEnabled(true);h.phone.value='bad';await h.send.onclick();assert.equal(calls,0);assert.match(h.feedback.textContent,/11 位/);
});
test('explicit send has countdown, payload needs code, phone edits invalidate it, and code expires',async()=>{
  let calls=0;const h=runtime(async phone=>{assert.equal(phone,'13800138000');calls++;return response;});
  h.verification.setEnabled(true);h.phone.value='13800138000';await h.send.onclick();
  assert.equal(calls,1);assert.match(h.send.textContent,/60 秒/);await h.send.onclick();assert.equal(calls,1);
  assert.throws(()=>h.verification.payload(),/6 位/);h.code.value='123456';assert.equal(h.verification.payload().challenge_id,'test-challenge');
  h.phone.listeners.input();assert.throws(()=>h.verification.payload(),/先获取/);assert.equal(h.send.disabled,true);
  h.advance(61000);assert.equal(h.send.disabled,false);await h.send.onclick();h.code.value='123456';
  h.advance(300001);assert.throws(()=>h.verification.payload(),/先获取/);
});
test('late SMS response after changing mode cannot restore a challenge',async()=>{
  let resolve;const h=runtime(()=>new Promise(r=>resolve=r));h.verification.setEnabled(true);h.phone.value='13800138000';
  const pending=h.send.onclick();h.verification.reset(true);h.verification.setEnabled(false);resolve(response);await pending;
  h.verification.setEnabled(true);h.phone.value='13800138000';h.code.value='123456';
  assert.throws(()=>h.verification.payload(),/先获取/);assert.equal(h.send.disabled,true);assert.equal(h.feedback.textContent,'');
});
test('provider failure never displays success or exposes a usable challenge',async()=>{
  const h=runtime(async()=>{throw new Error('短信未开通');});h.verification.setEnabled(true);h.phone.value='13800138000';await h.send.onclick();
  assert.equal(h.feedback.textContent,'短信未开通');assert.equal(h.send.disabled,true);assert.throws(()=>h.verification.payload(),/先获取/);
});
async function loginPage(phoneAuth, {loginFails=false,host='127.0.0.1'}={}) {
  const elements=new Map();const get=id=>{if(!elements.has(id)){const element=new Element();element.removeAttribute=name=>{delete element[name];};element.focus=()=>{};elements.set(id,element);}return elements.get(id);};
  const calls=[],replaced=[];const h=runtime();let captchas=0;
  h.context.document={getElementById:get};h.context.AbortSignal=AbortSignal;h.context.location={protocol:'http:',hostname:host,replace:target=>replaced.push(target)};
  h.context.fetch=async(path,options)=>{calls.push({path,body:options?.body&&JSON.parse(options.body)});
    if(path==='/api/auth/status')return {ok:true,json:async()=>({needs_setup:false,registration_open:true,phone_auth:phoneAuth,captcha_required:true})};
    if(path==='/api/auth/captcha'){captchas++;return {ok:true,json:async()=>({captcha_id:'captcha-'+captchas,image:'data:image/png;base64,AA==',length:6})};}
    if(loginFails)return {ok:false,json:async()=>({error:'图片验证码不正确或已过期，请输入新的验证码'})};
    return {ok:true,json:async()=>({user:{id:'test'}})};};
  vm.runInContext(login,h.context);await new Promise(resolve=>setImmediate(resolve));await new Promise(resolve=>setImmediate(resolve));
  return {get,calls,replaced};
}
const settle=()=>new Promise(resolve=>setImmediate(resolve));
test('password login sends the image challenge and a failed attempt loads a fresh one',async()=>{
  const h=await loginPage({available:false},{loginFails:true});
  assert.equal(h.get('captchaImg').src,'data:image/png;base64,AA==');
  h.get('username').value='ma2625223661@gmail.com';h.get('password').value='pass1234';h.get('captchaCode').value=' ab3k7z ';
  await h.get('authForm').onsubmit({preventDefault(){}});await settle();await settle();
  const login=h.calls.find(call=>call.path==='/api/auth/login');
  assert.deepEqual({id:login.body.captcha_id,code:login.body.captcha_code},{id:'captcha-1',code:'ab3k7z'});
  assert.equal(h.calls.at(-1).path,'/api/auth/captcha');assert.equal(h.get('captchaCode').value,'');
  assert.match(h.get('authStatus').textContent,/图片验证码/);
});
test('unconfigured service keeps legacy registration and disables SMS login',async()=>{
  const h=await loginPage({available:false,registration_required:false,message:'短信验证暂未开通'});
  assert.equal(h.get('smsMethod').disabled,true);assert.match(h.get('phoneNotice').textContent,/暂未开通/);
  h.get('switchMode').onclick();assert.equal(h.get('phoneFields').hidden,true);assert.equal(h.get('submitAuth').disabled,false);
  h.get('username').value='member';h.get('password').value=h.get('confirm').value='test password long enough';
  h.get('captchaCode').value='AB3K7Z';await h.get('authForm').onsubmit({preventDefault(){}});
  assert.equal(h.calls.at(-1).path,'/api/auth/register');assert.equal('phone' in h.calls.at(-1).body,false);
  assert.equal(h.calls.at(-1).body.captcha_code,'AB3K7Z');
});
test('enabled registration requires a challenge; SMS login hides password inputs',async()=>{
  const h=await loginPage({available:true,registration_required:true});h.get('switchMode').onclick();
  assert.equal(h.get('phoneFields').hidden,false);h.get('password').value=h.get('confirm').value='test password long enough';
  await h.get('authForm').onsubmit({preventDefault(){}});assert.deepEqual(h.calls.map(call=>call.path),['/api/auth/status','/api/auth/captcha']);assert.match(h.get('authStatus').textContent,/手机号/);
  h.get('switchMode').onclick();h.get('smsMethod').onclick();
  assert.equal(h.get('credentials').hidden,true);assert.equal(h.get('credentials').disabled,true);assert.equal(h.get('phoneFields').hidden,false);
});
test('required but unready service blocks registration while password login remains available',async()=>{
  const h=await loginPage({available:false,registration_required:true,message:'当前要求手机号验证，但短信服务尚未就绪'});
  assert.equal(h.get('submitAuth').disabled,false);h.get('switchMode').onclick();assert.equal(h.get('submitAuth').disabled,true);
  assert.equal(h.get('phoneFields').hidden,false);assert.equal(h.get('sendCode').disabled,true);
});
test('account binding submits explicit verified phone and current password, then clears private inputs',async()=>{
  const h=runtime(),container=new Element(),calls=[];
  h.context.document={createElement:tag=>new Element(tag)};
  vm.runInContext(fs.readFileSync('dist/phone-account.js','utf8'),h.context);
  const api=async(path,body)=>{calls.push({path,body});return path.endsWith('/send')?response:path.endsWith('/bind')?
    {available:true,bound:true,phone_masked:'138****8000'}:{available:true,bound:false};};
  h.context.window.FundPilotPhone.mountAccount(container,api);await new Promise(resolve=>setImmediate(resolve));
  const all=item=>[item,...item.children.flatMap(all)],nodes=all(container),find=id=>nodes.find(item=>item.id===id);
  const form=nodes.find(item=>item.tagName==='form'),send=nodes.find(item=>item.textContent==='获取验证码');
  assert.equal(form.hidden,false);assert.deepEqual(calls.map(c=>c.path),['/api/me/phone']);
  find('bindPhone').value='13800138000';await send.onclick();find('bindCode').value='123456';find('bindPassword').value='isolated current password';
  await form.onsubmit({preventDefault(){}});
  assert.deepEqual(JSON.parse(JSON.stringify(calls.at(-1).body)),{phone:'13800138000',challenge_id:'test-challenge',code:'123456',password:'isolated current password'});
  assert.equal(calls.at(-1).path,'/api/me/phone/bind');assert.equal(form.hidden,true);
  assert.equal(find('bindPassword').value,'');assert.equal(find('bindCode').value,'');assert.equal(find('bindPhone').value,'');
  assert.ok(nodes.some(item=>item.textContent.includes('138****8000')));
});
test('SMS send needs the image challenge first, sends it, and then loads a fresh image',async()=>{
  const h=await loginPage({available:true,registration_required:false});h.get('smsMethod').onclick();
  assert.equal(h.get('captchaCode').required,false);
  h.get('phone').value='13800138000';await h.get('sendCode').onclick();
  assert.match(h.get('smsStatus').textContent,/6 位图片验证码/);assert.equal(h.calls.some(c=>c.path==='/api/auth/sms/send'),false);
  h.get('captchaCode').value='AC3K7Z';await h.get('sendCode').onclick();await settle();await settle();
  const sent=h.calls.find(c=>c.path==='/api/auth/sms/send');
  assert.deepEqual([sent.body.captcha_id,sent.body.captcha_code,sent.body.purpose],['captcha-1','AC3K7Z','login']);
  assert.equal(h.calls.at(-1).path,'/api/auth/captcha');
});
test('LAN HTTP access shows an unencrypted-connection notice; localhost does not',async()=>{
  const local=await loginPage({available:false});assert.equal(local.get('lanNotice').textContent,'');
  const lan=await loginPage({available:false},{host:'192.168.1.23'});
  assert.equal(lan.get('lanNotice').hidden,false);assert.match(lan.get('lanNotice').textContent,/未加密/);
});
