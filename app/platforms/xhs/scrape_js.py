# -*- coding: utf-8 -*-
SCRAPE_CHAT_JS = r"""
() => {
  const bad = new Set([
    '消息','私信','发消息','小红书','通知','全部','未读','搜索','聊天',
    '联系人','设置','更多','首页','我','发现','市集','发布','关注','粉丝',
    '赞和收藏','@我的','系统消息','陌生人消息','选择联系人','未知用户'
  ]);
  const isName = (t) => {
    t = (t || '').replace(/\s+/g, ' ').trim();
    if (!t || t.length > 40 || bad.has(t)) return false;
    if (/^[0-9a-f]{16,}$/i.test(t)) return false;
    return /[\u4e00-\u9fff]/.test(t) || /[a-zA-Z]{2}/.test(t);
  };
  const convMatch = (location.pathname || '').match(/\/chat\/([0-9a-f]{24})/i);
  const convId = convMatch ? convMatch[1] : '';
  let nickname = '';

  // 1) 左侧会话列表中与当前 URL 匹配的项
  const anchors = Array.from(document.querySelectorAll('a[href*="/chat/"]'));
  for (const a of anchors) {
    const href = a.getAttribute('href') || a.href || '';
    if (!convId || !href.includes(convId)) continue;
    const root = a.closest('[class]') || a;
    const texts = [];
    root.querySelectorAll('span, div, p, a').forEach((el) => {
      if (el.children && el.children.length > 2) return;
      const t = (el.innerText || el.textContent || '').trim();
      if (t && t.length <= 20) texts.push(t);
    });
    for (const t of texts) {
      if (isName(t) && t !== '刚刚' && !/^\d{1,2}:\d{2}/.test(t) && !/月|日|昨天|周/.test(t)) {
        nickname = t;
        break;
      }
    }
    if (nickname) break;
  }

  // 2) 右侧聊天顶栏
  if (!nickname) {
    const headerCands = Array.from(document.querySelectorAll('h1,h2,h3,[class*="title"],[class*="Title"],[class*="name"],[class*="Name"],[class*="nick"]'));
    for (const el of headerCands) {
      const t = (el.innerText || '').trim().split('\n')[0].trim();
      if (isName(t)) { nickname = t; break; }
    }
  }

  // 3) 可见文本气泡（粗略）
  const texts = [];
  const bubbles = Array.from(document.querySelectorAll('[class*="message"],[class*="Message"],[class*="bubble"],[class*="Bubble"],[class*="content"]'));
  for (const el of bubbles) {
    const t = (el.innerText || '').trim();
    if (!t || t.length > 200) continue;
    if (bad.has(t) || t === nickname) continue;
    if (/^\[.+\]$/.test(t) || /[\u4e00-\u9fff]/.test(t) || /[a-zA-Z]{2,}/.test(t)) {
      if (!texts.includes(t) && t.length <= 80) texts.push(t);
    }
  }

  return { convId, nickname, texts: texts.slice(-30) };
}
"""
