'use strict';
(() => {
  const node=(tag,text,cls)=>{const item=document.createElement(tag);if(text!==undefined)item.textContent=text;if(cls)item.className=cls;return item;};
  function mount(container,api) {
    const card=node('section',undefined,'card cloud-personal cloud-phone');card.id='cloudPhone';
    const head=node('div',undefined,'settings-card-head'),title=node('div',undefined,'settings-heading'),copy=node('div');
    const icon=node('span','↗','settings-icon secondary');icon.setAttribute('aria-hidden','true');
    copy.append(node('span','PHONE VERIFICATION','eyebrow'),node('h2','手机号与验证码'));
    title.append(icon,copy);const badge=node('span','正在读取','settings-provider');head.append(title,badge);
    const description=node('p','正在读取手机号绑定状态…','muted');
    const feedback=node('p','','cloud-status');feedback.setAttribute('role','status');feedback.setAttribute('aria-live','polite');
    const retry=node('button','重新读取','btn ghost');retry.type='button';retry.hidden=true;
    const form=node('form',undefined,'cloud-phone-form');form.hidden=true;
    const controls={};
    for(const [id,label,type,autocomplete,placeholder] of [
      ['bindPhone','手机号（中国大陆 +86）','tel','tel-national','11 位手机号'],
      ['bindCode','短信验证码','text','one-time-code','6 位验证码'],
      ['bindPassword','当前账号密码','password','current-password','确认本人操作']]) {
      const field=node('div',undefined,'cloud-phone-field'),l=node('label',label),input=node('input');
      input.id=id;input.type=type;input.autocomplete=autocomplete;input.placeholder=placeholder;input.required=true;l.htmlFor=id;
      if(type==='tel'){input.inputMode='tel';input.maxLength=11;input.pattern='1[3-9][0-9]{9}';}
      if(id==='bindCode'){input.inputMode='numeric';input.maxLength=6;input.pattern='[0-9]{6}';}
      if(type==='password'){input.minLength=8;input.maxLength=128;}
      field.append(l);controls[id]=input;
      if(id==='bindCode'){const row=node('div',undefined,'cloud-phone-code');controls.send=node('button','获取验证码','btn ghost');row.append(input,controls.send);field.append(row);}
      else field.append(input);
      form.append(field);
    }
    const smsStatus=node('p','','cloud-status');smsStatus.setAttribute('role','status');smsStatus.setAttribute('aria-live','polite');
    const actions=node('div',undefined,'cloud-phone-actions'),submit=node('button','验证并绑定','btn');submit.type='submit';
    actions.append(node('small','验证码 5 分钟有效；绑定后可使用短信登录。','muted'),submit);form.append(smsStatus,actions);
    card.append(head,description,form,feedback,retry);container.append(card);
    let state=null,busy=false;
    const verification=window.FundPilotPhone.create({phone:controls.bindPhone,code:controls.bindCode,send:controls.send,feedback:smsStatus,
      request:phone=>api('/api/me/phone/send',{phone})});
    function render() {
      badge.textContent=state?.bound?'已绑定':state?.available?'未绑定':'暂未开通';
      description.textContent=state?.bound?`已绑定 ${state.phone_masked}。${state.available?'您可以使用该手机号接收验证码登录。':'短信服务当前未开通，请继续使用账号密码登录。'}`:
        state?.available?'验证手机号并确认当前密码后完成绑定，同一手机号仅可绑定一个账号。':'短信验证暂未开通。开通后可在这里绑定手机号，并使用短信验证码登录；当前继续使用账号密码。';
      form.hidden=!state?.available||state.bound;
      verification.setEnabled(state?.available&&!state.bound);verification.setBusy(busy);
      controls.bindPassword.disabled=busy||form.hidden;submit.disabled=busy||form.hidden;submit.textContent=busy?'正在绑定…':'验证并绑定';
    }
    async function load() {
      retry.hidden=true;
      try {state=await api('/api/me/phone');feedback.textContent='';render();}
      catch(error){badge.textContent='暂无法读取';description.textContent='手机号绑定状态暂未读取成功，请重试。';feedback.textContent=error.message;retry.hidden=false;}
    }
    retry.onclick=load;
    form.onsubmit=async event=>{
      event.preventDefault();if(busy||!state?.available||state.bound)return;
      let body;try{body={...verification.payload(),password:controls.bindPassword.value};}
      catch(error){feedback.textContent=error.message;return;}
      busy=true;render();feedback.textContent='正在验证并绑定…';
      try {state=await api('/api/me/phone/bind',body);verification.reset(true);controls.bindPassword.value='';feedback.textContent='手机号已验证并绑定。下次登录可选择短信验证码。';}
      catch(error){feedback.textContent=error.message;}
      finally{busy=false;render();}
    };
    load();
  }
  window.FundPilotPhone.mountAccount=mount;
})();
