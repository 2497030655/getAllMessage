# -*- coding: utf-8 -*-
"""注入到页面的 JS 脚本。"""

WS_TRACKER_SCRIPT = """
(() => {
  window.__apiMonWs = window.__apiMonWs || [];
  if (!window.__apiMonWsHooked) {
    window.__apiMonWsHooked = true;
    const NativeWS = window.WebSocket;
    function HookedWS(url, protocols) {
      const ws = protocols === undefined
        ? new NativeWS(url)
        : new NativeWS(url, protocols);
      window.__apiMonWs.push(ws);
      return ws;
    }
    HookedWS.prototype = NativeWS.prototype;
    HookedWS.CONNECTING = NativeWS.CONNECTING;
    HookedWS.OPEN = NativeWS.OPEN;
    HookedWS.CLOSING = NativeWS.CLOSING;
    HookedWS.CLOSED = NativeWS.CLOSED;
    window.WebSocket = HookedWS;
  }
  if (!window.__apiMonSendHooked) {
    window.__apiMonSendHooked = true;
    const origSend = WebSocket.prototype.send;
    WebSocket.prototype.send = function (data) {
      if (!window.__apiMonWs.includes(this)) {
        window.__apiMonWs.push(this);
      }
      return origSend.apply(this, arguments);
    };
  }
})();
"""

WS_HOOK_SCRIPT = WS_TRACKER_SCRIPT

WS_SEND_JS = """
(payloadStr) => {
  const diag = {
    hooked: !!window.__apiMonWsHooked,
    count: (window.__apiMonWs || []).length,
    urls: [],
    page: location.href
  };
  const list = window.__apiMonWs || [];
  for (const w of list) {
    diag.urls.push({ url: w.url, state: w.readyState });
  }
  const prefer = (u) =>
    u && (u.includes('apppush-rws') || u.includes('frontier-im'));
  let ws = list.find((w) => prefer(w.url) && w.readyState === 1);
  if (!ws) {
    ws = list.find((w) => w.readyState === 1);
  }
  if (!ws) {
    return {
      ok: false,
      error: '未找到已连接的 IM WebSocket（hook=' + diag.hooked
        + ', count=' + diag.count + '），请打开对应平台页面后重试',
      diag
    };
  }
  // 文本 JSON（小红书）或 Base64 二进制（抖音等）
  let data = payloadStr;
  if (typeof payloadStr === 'string' && payloadStr.startsWith('b64:')) {
    const b64 = payloadStr.slice(4);
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    data = bytes.buffer;
  }
  ws.send(data);
  return { ok: true, url: ws.url, diag };
}
"""

IM_WS_ALIVE_JS = """
() => {
  const list = window.__apiMonWs || [];
  const urls = [];
  for (const w of list) {
    if (w && w.readyState === 1 && w.url) urls.push(String(w.url));
  }
  return { href: location.href, urls };
}
"""

DETECT_IDENTITY_JS = """
() => {
  const hex24 = (s) => /^[0-9a-f]{24}$/i.test(String(s || ''));
  const host = location.hostname || '';
  const out = { xhs_uid: '', douyin_uid: '', name: '' };
  const scan = (obj, depth) => {
    if (!obj || depth > 5 || typeof obj !== 'object') return;
    for (const [k, v] of Object.entries(obj)) {
      const lk = String(k).toLowerCase();
      if (typeof v === 'string') {
        if (hex24(v) && /userid|user_id|redid|useridstr/.test(lk) && !out.xhs_uid) {
          out.xhs_uid = v;
        }
        if (/nickname|user_name|username|nick_name/.test(lk) && v.length >= 1 && v.length <= 24 && !out.name) {
          out.name = v;
        }
        if (/^\\d{6,20}$/.test(v) && /userid|uid/.test(lk) && host.includes('douyin') && !out.douyin_uid) {
          out.douyin_uid = v;
        }
      } else if (v && typeof v === 'object') {
        scan(v, depth + 1);
      }
    }
  };
  try { scan(window.__INITIAL_STATE__, 0); } catch (e) {}
  try { scan(window.__NEXT_DATA__, 0); } catch (e) {}
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      const raw = localStorage.getItem(k) || '';
      if (hex24(raw) && /user/i.test(k || '') && !out.xhs_uid) out.xhs_uid = raw;
      try { scan(JSON.parse(raw), 0); } catch (e) {}
    }
  } catch (e) {}
  return out;
}
"""
