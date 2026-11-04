'use strict';
(() => {
  // Shared by registration, SMS login and account binding. Never stores codes.
  function create({phone, code, send, feedback, request}) {
    let enabled=false, blocked=false, sending=false, challenge='', expires=0, nextSend=0, revision=0, timer;
    const normalized=()=>phone.value.trim().replace(/^\+86/, '');
    function render() {
      clearTimeout(timer);
      const seconds=Math.max(0,Math.ceil((nextSend-Date.now())/1000));
      phone.disabled=!enabled||blocked||sending;code.disabled=!enabled||blocked;
      send.disabled=!enabled||blocked||sending||seconds>0;
      send.textContent=sending?'正在发送…':seconds?`${seconds} 秒后重发`:'获取验证码';
      if(seconds)timer=setTimeout(render,1000);
    }
    function reset(clearPhone=false) {
      revision++;challenge='';expires=0;code.value='';feedback.textContent='';
      if(clearPhone)phone.value='';
      render();
    }
    phone.addEventListener('input',()=>reset());
    send.type='button';
    send.onclick=async()=>{
      if(send.disabled)return;
      if(!/^1[3-9][0-9]{9}$/.test(normalized())){feedback.textContent='请输入中国大陆 11 位手机号';phone.focus();return;}
      reset();const ticket=revision, number=normalized();nextSend=Date.now()+60000;sending=true;render();feedback.textContent='正在请求验证码…';
      try {
        const data=await request(number);
        nextSend=Date.now()+Math.max(60,Number(data.retry_after)||60)*1000;
        if(ticket!==revision)return;
        challenge=data.challenge_id;expires=Date.now()+Math.min(300,Number(data.expires_in)||300)*1000;
        feedback.textContent=data.message;code.focus();
      } catch(error) {if(ticket===revision)feedback.textContent=error.message;}
      finally {sending=false;render();}
    };
    render();
    return {
      reset,
      setEnabled(value){enabled=Boolean(value);render();},
      setBusy(value){blocked=Boolean(value);render();},
      payload(){
        if(!/^1[3-9][0-9]{9}$/.test(normalized()))throw new Error('请输入中国大陆 11 位手机号');
        if(!challenge||expires<=Date.now())throw new Error('请先获取有效的短信验证码');
        if(!/^[0-9]{6}$/.test(code.value))throw new Error('请输入 6 位短信验证码');
        return {phone:normalized(),challenge_id:challenge,code:code.value};
      }
    };
  }
  window.FundPilotPhone={create};
})();
