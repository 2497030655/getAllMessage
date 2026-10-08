(function () {
  const state = {
    conversations: [],
    active: null,
    messages: [],
    msgCache: {}, // conv_key -> messages[]
    ws: null,
    connected: false,
  };

  const el = {
    titleMain: document.getElementById("titleMain"),
    titleSub: document.getElementById("titleSub"),
    btnBack: document.getElementById("btnBack"),
    btnRefresh: document.getElementById("btnRefresh"),
    viewList: document.getElementById("viewList"),
    viewChat: document.getElementById("viewChat"),
    convList: document.getElementById("convList"),
    convEmpty: document.getElementById("convEmpty"),
    msgList: document.getElementById("msgList"),
    sendForm: document.getElementById("sendForm"),
    msgInput: document.getElementById("msgInput"),
    btnSend: document.getElementById("btnSend"),
  };

  function setStatus(text, ok) {
    el.titleSub.textContent = text;
    el.titleSub.className = "sub " + (ok === true ? "ok" : ok === false ? "bad" : "");
  }

  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function displayName(c) {
    return c.nickname || c.conv_id || c.key || "未知联系人";
  }

  function initial(name) {
    const s = String(name || "?").trim();
    return s ? s.slice(0, 1).toUpperCase() : "?";
  }

  function cacheMessage(convKey, message) {
    if (!convKey) return;
    const text = String(message.text || "").trim();
    const nick = String(message.nickname || "").trim();
    if (!text || (nick && text === nick)) return;
    const list = state.msgCache[convKey] || (state.msgCache[convKey] = []);
    const mid = message.message_id || "";
    if (mid && list.some(function (m) { return m.message_id === mid; })) return;
    if (
      list.length &&
      list[list.length - 1].text === text &&
      list[list.length - 1].direction === message.direction
    ) {
      return;
    }
    list.push({
      message_id: mid,
      direction: message.direction === "up" ? "up" : "down",
      text: text,
      time: message.time || "",
    });
  }

  function showList() {
    state.active = null;
    el.viewList.classList.remove("hidden");
    el.viewChat.classList.add("hidden");
    el.btnBack.classList.add("hidden");
    el.titleMain.textContent = "消息";
  }

  function showChat(conv) {
    state.active = conv;
    el.viewList.classList.add("hidden");
    el.viewChat.classList.remove("hidden");
    el.btnBack.classList.remove("hidden");
    el.titleMain.textContent = displayName(conv);
    // 先展示本地缓存，再拉服务端
    state.messages = (state.msgCache[conv.key] || []).slice();
    renderMessages();
    loadMessages(conv.key);
  }

  function renderConversations() {
    const items = state.conversations || [];
    el.convEmpty.classList.toggle("hidden", items.length > 0);
    el.convList.innerHTML = items
      .map(function (c) {
        const name = displayName(c);
        const plat = c.platform === "douyin" ? "dy" : "xhs";
        const unread = Number(c.unread || 0);
        return (
          '<li class="conv-item" data-key="' +
          escapeHtml(c.key) +
          '">' +
          '<div class="avatar ' +
          plat +
          '">' +
          escapeHtml(initial(name)) +
          "</div>" +
          '<div class="meta">' +
          '<div class="name-row"><div class="name">' +
          escapeHtml(name) +
          '</div><div class="time">' +
          escapeHtml(c.updated_at || "") +
          "</div></div>" +
          '<div class="preview">' +
          escapeHtml(c.preview || "") +
          "</div></div>" +
          (unread > 0 ? '<div class="badge">' + unread + "</div>" : "") +
          "</li>"
        );
      })
      .join("");
  }

  function renderMessages() {
    const msgs = state.messages || [];
    if (!msgs.length) {
      el.msgList.innerHTML =
        '<div class="empty" style="margin:24px">暂无消息</div>';
      return;
    }
    el.msgList.innerHTML = msgs
      .map(function (m) {
        const dir = m.direction === "up" ? "up" : "down";
        return (
          '<div class="bubble-row ' +
          dir +
          '"><div class="bubble ' +
          dir +
          '">' +
          escapeHtml(m.text || "") +
          '<span class="t">' +
          escapeHtml(m.time || "") +
          "</span></div></div>"
        );
      })
      .join("");
    el.msgList.scrollTop = el.msgList.scrollHeight;
  }

  function mergeConversations(items) {
    const map = {};
    (state.conversations || []).forEach(function (c) {
      if (c && c.key) map[c.key] = c;
    });
    (items || []).forEach(function (c) {
      if (!c || !c.key) return;
      map[c.key] = Object.assign({}, map[c.key] || {}, c);
    });
    state.conversations = Object.keys(map).map(function (k) {
      return map[k];
    });
    state.conversations.sort(function (a, b) {
      return String(b.updated_at || "").localeCompare(String(a.updated_at || ""));
    });
  }

  async function refreshList() {
    try {
      const data = await Api.listConversations();
      mergeConversations(data.items || []);
      renderConversations();
    } catch (e) {
      setStatus("拉取失败: " + e.message, false);
      // 保留 WS 已推送的列表，不清空
      renderConversations();
    }
  }

  async function loadMessages(convKey) {
    try {
      const data = await Api.getMessages(convKey);
      const remote = data.messages || [];
      remote.forEach(function (m) {
        cacheMessage(convKey, m);
      });
      state.messages = (state.msgCache[convKey] || []).slice();
      renderMessages();
    } catch (e) {
      // REST 失败时继续展示本地缓存
      state.messages = (state.msgCache[convKey] || []).slice();
      renderMessages();
      if (!(state.messages && state.messages.length)) {
        setStatus("消息加载失败: " + e.message, false);
      }
    }
  }

  function upsertConversationFromEvent(msg) {
    const key = msg.conv_key;
    if (!key) return;
    let found = state.conversations.find(function (c) {
      return c.key === key;
    });
    if (!found) {
      found = {
        key: key,
        conv_id: msg.conv_id,
        account_id: msg.account_id,
        platform: msg.platform,
        nickname: msg.nickname || "",
        unread: 0,
        preview: "",
        updated_at: msg.time || "",
      };
      state.conversations.unshift(found);
    }
    const text = String(msg.text || "").trim();
    const nick = String(msg.nickname || "").trim();
    if (nick && (!found.nickname || found.nickname === found.conv_id)) {
      found.nickname = nick;
    }
    if (text && text !== nick) {
      found.preview = text;
      found.updated_at = msg.time || found.updated_at;
      if (!state.active || state.active.key !== key) {
        found.unread =
          Number(found.unread || 0) + (msg.direction === "down" ? 1 : 0);
      }
    } else if (msg.time) {
      found.updated_at = msg.time || found.updated_at;
    }
    state.conversations.sort(function (a, b) {
      return String(b.updated_at || "").localeCompare(String(a.updated_at || ""));
    });
    renderConversations();
  }

  function connectWs() {
    try {
      if (state.ws) {
        state.ws.onclose = null;
        state.ws.close();
      }
    } catch (e) {}
    const url =
      APP_CONFIG.wsUrl +
      (APP_CONFIG.wsUrl.indexOf("?") >= 0 ? "&" : "?") +
      "token=" +
      encodeURIComponent(APP_CONFIG.token);
    const ws = new WebSocket(url);
    state.ws = ws;
    ws.onopen = function () {
      state.connected = true;
      setStatus("已连接云端", true);
      ws.send(JSON.stringify({ type: "ping" }));
    };
    ws.onclose = function () {
      state.connected = false;
      setStatus("未连接，3 秒后重连…", false);
      setTimeout(connectWs, 3000);
    };
    ws.onerror = function () {
      setStatus("WebSocket 异常", false);
    };
    ws.onmessage = function (ev) {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch (e) {
        return;
      }
      if (msg.type === "im_message") {
        // 云端偶发把昵称当成正文，移动端直接丢弃
        if (
          msg.nickname &&
          String(msg.text || "").trim() === String(msg.nickname || "").trim()
        ) {
          if (msg.nickname && msg.conv_key) {
            upsertConversationFromEvent(
              Object.assign({}, msg, { text: "", direction: "down" })
            );
          }
          return;
        }
        if (!String(msg.text || "").trim()) return;
        cacheMessage(msg.conv_key, msg);
        upsertConversationFromEvent(msg);
        if (state.active && state.active.key === msg.conv_key) {
          state.messages = (state.msgCache[msg.conv_key] || []).slice();
          renderMessages();
        }
      } else if (msg.type === "send_result") {
        if (!msg.ok) {
          setStatus("发送失败: " + (msg.error || ""), false);
        } else {
          setStatus("已连接云端", true);
        }
      }
    };
  }

  el.convList.addEventListener("click", function (e) {
    const item = e.target.closest(".conv-item");
    if (!item) return;
    const key = item.getAttribute("data-key");
    const conv = state.conversations.find(function (c) {
      return c.key === key;
    });
    if (conv) {
      conv.unread = 0;
      renderConversations();
      showChat(conv);
    }
  });

  el.btnBack.addEventListener("click", showList);
  el.btnRefresh.addEventListener("click", function () {
    if (state.active) loadMessages(state.active.key);
    else refreshList();
  });

  el.sendForm.addEventListener("submit", async function (e) {
    e.preventDefault();
    const text = el.msgInput.value.trim();
    if (!text || !state.active) return;
    el.btnSend.disabled = true;
    try {
      await Api.sendMessage({
        account_id: state.active.account_id || "default",
        conv_key: state.active.key,
        conv_id: state.active.conv_id || "",
        platform: state.active.platform || "xhs",
        text: text,
      });
      el.msgInput.value = "";
      const local = {
        direction: "up",
        text: text,
        time: new Date().toISOString().slice(0, 19).replace("T", " "),
      };
      cacheMessage(state.active.key, local);
      state.messages = (state.msgCache[state.active.key] || []).slice();
      renderMessages();
      upsertConversationFromEvent({
        conv_key: state.active.key,
        conv_id: state.active.conv_id,
        account_id: state.active.account_id,
        platform: state.active.platform,
        nickname: state.active.nickname,
        direction: "up",
        text: text,
        time: local.time,
      });
    } catch (err) {
      setStatus("发送失败: " + err.message, false);
    } finally {
      el.btnSend.disabled = false;
    }
  });

  function boot() {
    setStatus("连接中…");
    showList();
    refreshList();
    connectWs();
    setInterval(function () {
      if (!state.active) refreshList();
    }, 15000);
  }

  document.addEventListener("deviceready", boot, false);
  if (!window.cordova) {
    document.addEventListener("DOMContentLoaded", boot);
  }
})();
