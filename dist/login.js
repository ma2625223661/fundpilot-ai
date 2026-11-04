'use strict';
(() => {
  const $=id=>document.getElementById(id);
  let status=null, mode='login', method='password', busy=false, captchaId='', captchaLoading=null;
  async function api(path,body) {
    let response;
    try {response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(20000)});}
    catch {throw new Error('请求未完成，请稍后重试；发送验证码后请先查看短信。');}
    const data=await response.json();if(!response.ok)throw new Error(data.error||'请求失败');return data;
  }
  // Sending an SMS also spends one image challenge (anti SMS-bombing).
  function captchaProblem() {
    if(!captchaId)return '图片验证码尚未加载，请点击图片刷新';
    return /^[A-Za-z0-9]{6}$/.test($('captchaCode').value.trim())?'':'请先输入上方 6 位图片验证码，再获取短信验证码';
  }
  const verification=window.FundPilotPhone.create({phone:$('phone'),code:$('smsCode'),send:$('sendCode'),feedback:$('smsStatus'),
    precheck:captchaProblem,
    request:phone=>{const body={phone,purpose:mode==='register'?'register':'login',captcha_id:captchaId,captcha_code:$('captchaCode').value.trim()};
      return api('/api/auth/sms/send',body).finally(()=>loadCaptcha());}});
  function render() {
    if(!status)return;
    const setup=mode==='setup',creating=mode!=='login',smsLogin=mode==='login'&&method==='sms';
    const phone=status.phone_auth||{},usePhone=smsLogin||mode==='register'&&(phone.available||phone.registration_required);
    const unavailable=usePhone&&!phone.available;
    $('formTitle').textContent=setup?'创建管理员账号':creating?'创建个人研究账号':'登录研究工作台';
    $('formIntro').textContent=setup?(status.setup_available===false?'请先在运行后台的电脑上完成初始化，再回到此处登录。':'首次使用，请设置管理员账号和密码。'):creating?'个人关注与研究记录单独保存。':'欢迎回来，继续您的板块研究。';
    $('loginMethods').hidden=mode!=='login';
    $('passwordMethod').disabled=busy;$('smsMethod').disabled=busy||!phone.available;
    $('passwordMethod').setAttribute('aria-pressed',String(!smsLogin));$('smsMethod').setAttribute('aria-pressed',String(smsLogin));
    $('phoneNotice').hidden=setup||Boolean(phone.available);
    $('phoneNotice').textContent=phone.message||'短信验证暂未开通，当前可使用用户名和密码注册、登录。';
    $('credentials').hidden=smsLogin;$('credentials').disabled=smsLogin||busy;
    $('confirmField').hidden=!creating;$('confirm').required=creating;
    $('phoneFields').hidden=!usePhone;
    $('phoneLegend').textContent=smsLogin?'使用已绑定的手机号登录':'验证手机号 · 保护您的账号';
    $('phone').required=usePhone;$('smsCode').required=usePhone;
    verification.setEnabled(usePhone&&phone.available);verification.setBusy(busy);
    $('setupField').hidden=!setup||!status.setup_token_required;
    $('setupToken').required=setup&&status.setup_token_required;$('setupToken').disabled=busy;
    $('password').autocomplete=creating?'new-password':'current-password';
    $('captchaRefresh').disabled=busy;$('captchaCode').disabled=busy;$('captchaCode').required=!smsLogin;
    $('captchaHelp').textContent=smsLogin||usePhone?'不区分大小写；获取短信验证码前需先填写，每张只能用一次（发送后会自动换一张）。':'不区分大小写；看不清可点击图片换一张。每张只能用一次，5 分钟内有效。';
    $('switchMode').hidden=setup||!status.registration_open;$('switchMode').disabled=busy;
    $('switchMode').textContent=creating?'已有账号，返回登录':'还没有账号？注册';
    $('submitAuth').textContent=busy?'正在验证…':setup?'初始化并进入':creating?'注册并进入':smsLogin?'验证并登录':'登录';
    $('submitAuth').disabled=busy||unavailable||setup&&status.setup_available===false;
  }
  // Each challenge is single use, so a fresh one is fetched after every failed submit.
  function loadCaptcha() {
    if(captchaLoading)return captchaLoading;
    captchaId='';$('captchaCode').value='';$('captchaImg').removeAttribute('src');$('captchaImg').alt='图片验证码加载中';
    captchaLoading=fetch('/api/auth/captcha',{cache:'no-store',signal:AbortSignal.timeout(10000)}).then(async response=>{
      const data=await response.json();if(!response.ok)throw new Error(data.error||'');
      captchaId=data.captcha_id;$('captchaImg').src=data.image;$('captchaImg').alt='图片验证码，看不清可点击更换';
    }).catch(error=>{$('captchaImg').alt='验证码加载失败，点击重试';if(error.message)$('authStatus').textContent=error.message;})
      .finally(()=>{captchaLoading=null;});
    return captchaLoading;
  }
  $('captchaRefresh').onclick=()=>{if(!busy)loadCaptcha().then(()=>$('captchaCode').focus());};
  function reset() {verification.reset(true);$('authStatus').textContent='';$('password').value='';$('confirm').value='';render();}
  $('switchMode').onclick=()=>{if(busy)return;mode=mode==='login'?'register':'login';method='password';reset();};
  $('passwordMethod').onclick=()=>{if(busy)return;method='password';reset();};
  $('smsMethod').onclick=()=>{if(busy||!status?.phone_auth?.available)return;method='sms';reset();};
  $('authForm').onsubmit=async event=>{
    event.preventDefault();if(busy||!status||$('submitAuth').disabled)return;
    const smsLogin=mode==='login'&&method==='sms';
    if(mode!=='login'&&$('password').value!==$('confirm').value){$('authStatus').textContent='两次密码不一致';return;}
    let body=smsLogin?{}:{username:$('username').value,password:$('password').value};
    if(!smsLogin){if(!captchaId){$('authStatus').textContent='图片验证码尚未加载，请点击图片刷新';return;}body.captcha_id=captchaId;body.captcha_code=$('captchaCode').value.trim();}
    try {if(smsLogin||mode==='register'&&(status.phone_auth?.available||status.phone_auth?.registration_required))body={...body,...verification.payload()};}
    catch(error){$('authStatus').textContent=error.message;return;}
    if(mode==='setup')body.setup_token=$('setupToken').value;
    busy=true;render();$('authStatus').textContent='正在验证…';
    try {
      await api('/api/auth/'+(smsLogin?'sms/login':mode),body);
      verification.reset(true);$('password').value='';$('confirm').value='';$('setupToken').value='';location.replace('/index.html');
    } catch(error) {$('authStatus').textContent=error.message;if(!smsLogin)loadCaptcha();}
    finally {busy=false;render();}
  };
  // Plain HTTP to another device's address crosses the local network unencrypted.
  if(location.protocol==='http:'&&!['127.0.0.1','localhost','[::1]','::1'].includes(location.hostname)){
    $('lanNotice').textContent='当前通过局域网 HTTP 连接，未加密：密码会以明文经过网络。请只在自己信任的家庭或办公 Wi-Fi 中登录，不要在公共网络使用。';
    $('lanNotice').hidden=false;
  }
  fetch('/api/auth/status',{cache:'no-store',signal:AbortSignal.timeout(10000)}).then(async response=>{
    if(!response.ok)throw new Error();status=await response.json();mode=status.needs_setup?'setup':'login';render();loadCaptcha();
  }).catch(()=>{$('formIntro').textContent='账号服务暂时无法连接，请刷新页面重试。';});
})();
