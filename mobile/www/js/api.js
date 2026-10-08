(function (global) {
  const cfg = () => global.APP_CONFIG;

    async function request(path, options = {}) {
    const url = cfg().apiBase.replace(/\/$/, "") + path;
    const headers = Object.assign(
      { Authorization: cfg().token, Accept: "application/json" },
      options.headers || {}
    );
    if (options.body && !headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }
    const res = await fetch(url, Object.assign({}, options, { headers }));
    if (!res.ok) {
      let detail = "";
      try {
        const t = await res.text();
        try {
          const j = JSON.parse(t);
          detail = j.detail || t;
        } catch (e) {
          detail = t;
        }
      } catch (e) {}
      if (Array.isArray(detail)) {
        detail = detail.map(function (x) { return x.msg || JSON.stringify(x); }).join("; ");
      }
      throw new Error(detail || ("HTTP " + res.status));
    }
    return res.json();
  }

  global.Api = {
    listConversations(accountId, platform) {
      const q = new URLSearchParams();
      if (accountId) q.set("account_id", accountId);
      if (platform) q.set("platform", platform);
      const s = q.toString();
      return request("/api/conversations" + (s ? "?" + s : ""));
    },
    getMessages(convKey) {
      return request("/api/conversations/" + encodeURIComponent(convKey) + "/messages");
    },
    sendMessage(payload) {
      return request("/api/messages/send", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
  };
})(window);
