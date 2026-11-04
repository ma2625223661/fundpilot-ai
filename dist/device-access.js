/* Phone entry points and local configuration admission; no upstream requests. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const controls = [...document.querySelectorAll('[data-local-controls]')];
  const fallbackLocal = ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname);
  function admit(local) {
    controls.forEach(node => { node.disabled = !local; });
    $('remoteSettingsNote').hidden = local;
  }
  admit(fallbackLocal);
  document.querySelectorAll('[data-view],[data-go-settings]').forEach(button => {
    button.addEventListener('click', () => {
      window.history.replaceState(null, '', '#' + (button.dataset.view || 'settings'));
    });
  });
  const initialView = location.hash.slice(1);
  const settingsAnchors = ['mobileAccess', 'researchSettings', 'researchDataSettings', 'aiSupport'];
  if (['dash', 'data', 'history', 'cycle', 'settings', ...settingsAnchors].includes(initialView)) {
    document.querySelector('[data-view="' + (settingsAnchors.includes(initialView) ? 'settings' : initialView) + '"]').click();
    if (settingsAnchors.includes(initialView)) {
      window.history.replaceState(null, '', '#' + initialView);
      $(initialView).scrollIntoView();
    }
  }
  let urls = [];
  function selectUrl(value) {
    $('mobileAccessUrl').value = value;
    $('copyMobileUrl').disabled = false;
  }
  function useConfiguredPublicEntry() {
    const configured = $('mobileAccess').dataset.publicUrl;
    if (!configured) return false;
    try {
      const url = new URL(configured);
      if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || url.pathname !== '/index.html') throw new Error('云端网址配置无效');
      urls = [url.href];
      selectUrl(url.href);
      $('mobileAccessAlternates').replaceChildren();
      $('mobileAccessAlternates').hidden = true;
    } catch {
      urls = [];
      $('mobileAccessUrl').value = '云端网址配置无效';
      $('copyMobileUrl').disabled = true;
      $('mobileAccessStatus').textContent = '请由管理员检查云端网址配置。';
    }
    return true;
  }
  const configuredPublicEntry = useConfiguredPublicEntry();
  async function loadAccess() {
    try {
      const response = await fetch('/api/access', {cache:'no-store', signal:AbortSignal.timeout(10000)});
      if (!response.ok) throw new Error('访问入口读取失败');
      const data = await response.json();
      admit(data.can_manage_settings === true);
      if (data.scope === 'account_local') {
        $('remoteSettingsNote').textContent = '公共设置仅限管理员在运行后台的电脑上修改。您可以管理自己的关注、研究记录和密码。';
        $('keyHelp').textContent = '由当前 Windows 账号加密保存。只有管理员在此电脑上可修改，页面不读取已保存的密钥原文。';
        if (!configuredPublicEntry) {
          const tips = $('mobileAccess').querySelector('.mobile-access-tips');
          tips.children[2].textContent = '登录自己的账号查看研究；使用期间电脑和网站后台需保持运行。';
        }
      }
      if (data.scope === 'cloud') {
        if (!configuredPublicEntry) {
          const url = new URL(data.site_url);
          if (url.origin !== location.origin || url.pathname !== '/index.html' || url.search || url.hash || url.username || url.password) throw new Error('访问地址无效');
          urls = [url.href]; selectUrl(url.href);
          const card = $('mobileAccess');
          card.querySelector('.settings-provider').textContent = data.preview ? '仅本机预览' : '无需同一 Wi-Fi';
          card.querySelector('p.muted').textContent = data.preview ? '当前为本机账号版预览，正式托管后可跨网络访问。' : '在手机或电脑浏览器打开同一网址，登录自己的账号即可使用。';
          $('mobileAccessLabel').textContent = data.preview ? '当前电脑预览网址' : '手机与电脑通用网址';
          card.querySelector('.mobile-access-tips').replaceChildren(...(data.preview ? ['当前网址只用于这台电脑的本地预览。', '手机访问需先配置局域网入口或完成云端上线。'] : ['复制上方网址，在手机浏览器中打开。', '使用自己的账号登录，关注与研究记录独立保存。', '网站由云端运行，个人电脑可以关机。']).map(text => {const item=document.createElement('li');item.textContent=text;return item;}));
          $('mobileAccessStatus').textContent = data.preview ? '本机预览网址不能直接分享给手机或外网用户。' : '云端访问网址；手机可使用 Wi-Fi 或移动网络。';
          $('mobileAccessNotice').textContent = data.preview ? '当前尚未发布为可供外部访问的云端网站。' : '云端访问无需与个人电脑连接同一 Wi-Fi。';
          $('mobileAccessHelp').textContent = data.preview ? '请先由管理员配置手机可访问的入口；127.0.0.1 只代表打开网页的设备本身。' : '先检查手机网络和网址；若提示备案限制，请联系管理员完成备案。';
        }
        $('remoteSettingsNote').textContent = '公共研究报告与模型设置由管理员维护。您可管理自己的关注、记录和密码。';
        $('key').disabled = true; $('key').placeholder = '由托管平台环境变量管理';
        $('keyHelp').textContent = '服务密钥由管理员在云端托管平台配置，不发送到浏览器。';
        document.querySelector('#marketSessionTimes small').textContent = '仅 A 股交易日，休市日跳过。云端后台按北京时间运行，错过的时段不补跑。';
        return;
      }
      if (configuredPublicEntry) return;
      // Accept only the private IPv4 links produced by our own server.
      urls = (Array.isArray(data.lan_urls) ? data.lan_urls : []).filter(value => {
        try {
          const url = new URL(value);
          const octets = url.hostname.split('.').map(Number);
          return octets.length === 4 && octets.every(n => Number.isInteger(n) && n >= 0 && n <= 255) &&
            (octets[0] === 10 || octets[0] === 192 && octets[1] === 168 || octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31) &&
            url.protocol === 'http:' && url.port === location.port && url.pathname === '/index.html' && !url.search && !url.hash && !url.username && !url.password;
        } catch { return false; }
      });
      const choices = $('mobileAccessAlternates');
      choices.replaceChildren();
      choices.hidden = urls.length < 2;
      if (urls.length) {
        selectUrl(urls.find(url => new URL(url).hostname === location.hostname) || urls[0]);
        for (const url of urls) {
          const button = document.createElement('button');
          button.type = 'button'; button.className = 'btn'; button.textContent = new URL(url).hostname;
          button.onclick = () => selectUrl(url);
          choices.append(button);
        }
        $('mobileAccessStatus').textContent = data.can_manage_settings ? '切换 Wi-Fi 后，请刷新页面获取新的手机访问网址。' : '已连接同一局域网，可用此网址继续访问。';
      } else {
        $('mobileAccessUrl').value = '未检测到可用的局域网地址';
        $('copyMobileUrl').disabled = true;
        $('mobileAccessStatus').textContent = '请先将电脑连接到 Wi-Fi 或有线网络，再刷新页面。';
      }
    } catch {
      if (configuredPublicEntry) return;
      $('mobileAccessUrl').value = '暂时无法读取访问地址';
      $('copyMobileUrl').disabled = true;
      $('mobileAccessStatus').textContent = '请确认网站后台运行后刷新。手机需使用电脑的局域网 IP，不能使用 127.0.0.1。';
    }
  }
  $('copyMobileUrl').onclick = async () => {
    const field = $('mobileAccessUrl');
    if (!urls.includes(field.value)) return;
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(field.value);
      } else {
        field.focus(); field.select(); field.setSelectionRange(0, field.value.length);
        if (!document.execCommand('copy')) throw new Error('manual copy');
      }
      $('mobileAccessStatus').textContent = configuredPublicEntry && $('mobileAccess').dataset.publicState === 'pending_filing'
        ? '网址已复制 · 当前待备案，正式开通后可跨网络使用。'
        : '网址已复制，请在手机浏览器的地址栏中粘贴打开。';
    } catch {
      field.focus(); field.select(); field.setSelectionRange(0, field.value.length);
      $('mobileAccessStatus').textContent = '地址已选中，请长按或使用复制快捷键。';
    }
  };
  loadAccess();
})();
