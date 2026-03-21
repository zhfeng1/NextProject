import { ref, onUnmounted } from 'vue'
import type { Ref } from 'vue'

export interface ConsoleError {
  type: 'js' | 'network'
  message: string
  url?: string
  time: string
}

export interface PickedElement {
  xpath: string
  outerHTML: string
  screenshotDataUrl: string | null
}

// 注入到 iframe 的完整桥接脚本（字符串化，避免序列化问题）
function getBridgeScript(): string {
  return `
(function() {
  if (window.__bridgeInjected) return;
  window.__bridgeInjected = true;

  function postToParent(data) {
    try { window.parent.postMessage(data, '*'); } catch(e) {}
  }

  // ── 控制台错误捕获 ──────────────────────────────────────────
  const _origError = console.error.bind(console);
  console.error = function(...args) {
    _origError(...args);
    postToParent({ __bridge: 'console_error', message: args.map(String).join(' '), time: new Date().toISOString() });
  };

  window.addEventListener('error', function(e) {
    postToParent({ __bridge: 'js_error', message: e.message || String(e), url: e.filename, time: new Date().toISOString() });
  });

  window.addEventListener('unhandledrejection', function(e) {
    postToParent({ __bridge: 'js_error', message: 'Unhandled Promise: ' + String(e.reason), time: new Date().toISOString() });
  });

  // ── 网络请求拦截 ─────────────────────────────────────────────
  const _origFetch = window.fetch;
  window.fetch = function(input, init) {
    return _origFetch.call(this, input, init).then(function(resp) {
      if (!resp.ok) {
        postToParent({ __bridge: 'network_error', message: resp.status + ' ' + resp.statusText + ' ' + (typeof input === 'string' ? input : input.url), url: typeof input === 'string' ? input : input.url, time: new Date().toISOString() });
      }
      return resp;
    });
  };

  const _origOpen = XMLHttpRequest.prototype.open;
  const _origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function(method, url) {
    this.__url = url; return _origOpen.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function() {
    this.addEventListener('load', function() {
      if (this.status >= 400) {
        postToParent({ __bridge: 'network_error', message: this.status + ' ' + this.statusText + ' ' + this.__url, url: this.__url, time: new Date().toISOString() });
      }
    });
    return _origSend.apply(this, arguments);
  };

  // ── XPath 计算 ───────────────────────────────────────────────
  function getXPath(el) {
    if (!el || el.nodeType !== 1) return '';
    if (el.id) return '//*[@id="' + el.id + '"]';
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1) {
      let idx = 1, sib = node.previousSibling;
      while (sib) { if (sib.nodeType === 1 && sib.tagName === node.tagName) idx++; sib = sib.previousSibling; }
      parts.unshift(node.tagName.toLowerCase() + '[' + idx + ']');
      node = node.parentNode;
    }
    return '/' + parts.join('/');
  }

  // ── 元素选取器 ───────────────────────────────────────────────
  var _pickerActive = false;
  var _hovered = null;
  var _pickerStyle = null;

  function enablePicker() {
    if (_pickerActive) return;
    _pickerActive = true;
    _pickerStyle = document.createElement('style');
    _pickerStyle.id = '__bridge_picker_style';
    _pickerStyle.textContent = '.__bridge_hover { outline: 2px solid #6366f1 !important; outline-offset: 2px !important; cursor: crosshair !important; }';
    document.head.appendChild(_pickerStyle);
    document.addEventListener('mouseover', _onHover, true);
    document.addEventListener('click', _onClick, true);
  }

  function disablePicker() {
    if (!_pickerActive) return;
    _pickerActive = false;
    document.removeEventListener('mouseover', _onHover, true);
    document.removeEventListener('click', _onClick, true);
    if (_hovered) { _hovered.classList.remove('__bridge_hover'); _hovered = null; }
    var s = document.getElementById('__bridge_picker_style');
    if (s) s.remove();
  }

  function _onHover(e) {
    if (_hovered) _hovered.classList.remove('__bridge_hover');
    _hovered = e.target;
    if (_hovered) _hovered.classList.add('__bridge_hover');
  }

  function _onClick(e) {
    e.preventDefault(); e.stopPropagation();
    var el = e.target;
    var xpath = getXPath(el);
    var outerHTML = el.outerHTML ? el.outerHTML.substring(0, 2000) : '';
    disablePicker();
    // 尝试用 html2canvas 截图
    function sendResult(dataUrl) {
      postToParent({ __bridge: 'element_picked', xpath: xpath, outerHTML: outerHTML, screenshotDataUrl: dataUrl });
    }
    if (window.html2canvas) {
      window.html2canvas(el, { useCORS: true, scale: 1 }).then(function(c) { sendResult(c.toDataURL()); }).catch(function() { sendResult(null); });
    } else {
      // 动态加载 html2canvas
      var script = document.createElement('script');
      script.src = 'https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js';
      script.onload = function() {
        window.html2canvas(el, { useCORS: true, scale: 1 }).then(function(c) { sendResult(c.toDataURL()); }).catch(function() { sendResult(null); });
      };
      script.onerror = function() { sendResult(null); };
      document.head.appendChild(script);
    }
  }

  // 监听父窗口指令
  window.addEventListener('message', function(e) {
    if (!e.data || e.data.__bridgeCmd === undefined) return;
    var cmd = e.data.__bridgeCmd;
    if (cmd === 'enable_picker') enablePicker();
    else if (cmd === 'disable_picker') disablePicker();
    else if (cmd === 'ping') postToParent({ __bridge: 'pong' });
  });

  postToParent({ __bridge: 'ready' });
})();
`
}

export function useIframeBridge(iframeRef: Ref<HTMLIFrameElement | null>) {
  const currentUrl = ref('')
  const consoleErrors = ref<ConsoleError[]>([])
  const pickedElement = ref<PickedElement | null>(null)
  const pickerMode = ref(false)
  const bridgeReady = ref(false)

  function injectBridge() {
    const iframe = iframeRef.value
    if (!iframe?.contentWindow) return
    try {
      const doc = iframe.contentDocument || iframe.contentWindow.document
      // 检查是否已注入
      if ((iframe.contentWindow as any).__bridgeInjected) return
      const script = doc.createElement('script')
      script.textContent = getBridgeScript()
      doc.head?.appendChild(script) || doc.body?.appendChild(script)
    } catch {
      // 跨域时注入失败，静默处理
    }
  }

  function onIframeLoad() {
    const iframe = iframeRef.value
    if (!iframe) return
    try {
      const loc = iframe.contentWindow?.location
      currentUrl.value = loc?.href || ''
    } catch {
      currentUrl.value = ''
    }
    bridgeReady.value = false
    setTimeout(() => injectBridge(), 100)
  }

  function onMessage(e: MessageEvent) {
    const data = e.data
    if (!data || !data.__bridge) return

    switch (data.__bridge) {
      case 'ready':
        bridgeReady.value = true
        // 如果 picker 模式已开启，立即重新启用
        if (pickerMode.value) sendToIframe({ __bridgeCmd: 'enable_picker' })
        break

      case 'console_error':
        consoleErrors.value.push({ type: 'js', message: data.message, time: data.time })
        break

      case 'js_error':
        consoleErrors.value.push({ type: 'js', message: data.message, url: data.url, time: data.time })
        break

      case 'network_error':
        consoleErrors.value.push({ type: 'network', message: data.message, url: data.url, time: data.time })
        break

      case 'element_picked':
        pickedElement.value = {
          xpath: data.xpath,
          outerHTML: data.outerHTML,
          screenshotDataUrl: data.screenshotDataUrl,
        }
        pickerMode.value = false
        break
    }
  }

  function sendToIframe(msg: object) {
    iframeRef.value?.contentWindow?.postMessage(msg, '*')
  }

  function togglePicker() {
    pickerMode.value = !pickerMode.value
    sendToIframe({ __bridgeCmd: pickerMode.value ? 'enable_picker' : 'disable_picker' })
  }

  function clearErrors() {
    consoleErrors.value = []
  }

  function clearPicked() {
    pickedElement.value = null
  }

  function reloadIframe() {
    const iframe = iframeRef.value
    if (!iframe) return
    iframe.src = iframe.src
  }

  window.addEventListener('message', onMessage)
  onUnmounted(() => window.removeEventListener('message', onMessage))

  return {
    currentUrl,
    consoleErrors,
    pickedElement,
    pickerMode,
    bridgeReady,
    onIframeLoad,
    togglePicker,
    clearErrors,
    clearPicked,
    reloadIframe,
    sendToIframe,
  }
}
