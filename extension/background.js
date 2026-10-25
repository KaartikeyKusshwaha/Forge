/* Credentials live in this trusted extension context, never in the GitHub page. */
chrome.storage.local.setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" });
chrome.action.onClicked.addListener(() => chrome.runtime.openOptionsPage());

function endpoint(value) {
  const url = new URL(value || "http://127.0.0.1:8787");
  if (url.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(url.hostname) ||
      url.username || url.password || url.search || url.hash || url.pathname !== "/") {
    throw new Error("Use the loopback Forge service, for example http://127.0.0.1:8787.");
  }
  return url.origin;
}

function allowedRequest(message) {
  const id = message.id;
  const runPath = id && /^[a-f0-9]{32}$/.test(id) ? `/api/runs/${id}` : null;
  switch (message.action) {
    case "status": return ["GET", "/api/status"];
    case "models": return ["GET", "/api/models"];
    case "model-profiles": return ["GET", "/api/model-profiles"];
    case "model-connect": return ["POST", "/api/model-profiles", message.body];
    case "model-activate": if (/^[a-f0-9]{32}$/.test(message.id || "")) return ["POST", "/api/model-profiles/" + message.id + "/activate", {model:message.model || null}]; break;
    case "model-delete": if (/^[a-f0-9]{32}$/.test(message.id || "")) return ["DELETE", "/api/model-profiles/" + message.id]; break;
    case "model-spending": return ["GET", "/api/model-spending"];
    case "model-decide": if (/^[a-f0-9]{32}$/.test(message.id || "")) return ["POST", "/api/model-spending/" + message.id, {approve:message.approve === true}]; break;
    case "github-setup": return ["POST", "/api/setup/github"];
    case "list": return ["GET", "/api/runs" + (Number.isFinite(message.before) ? "?before=" + encodeURIComponent(message.before) : "")];
    case "analyze-repo":
      if (/^[\w.-]+\/[\w.-]+$/.test(message.body?.repo || ""))
        return ["POST", "/api/repository/analyze", {repo: message.body.repo, enable: message.body.enable === true}];
      break;
    case "create": {
      const data = message.body;
      if (!data || !/^[\w.-]+\/[\w.-]+$/.test(data.repo) || !Number.isInteger(data.issue) ||
          !["demo", "github"].includes(data.mode)) throw new Error("Invalid issue.");
      return ["POST", "/api/runs", data];
    }
    case "run": if (runPath) return ["GET", runPath]; break;
    case "pull-history": if (runPath) return ["GET", runPath + "/pull-history"]; break;
    case "diagnose": if (runPath) return ["POST", runPath + "/diagnose"]; break;
    case "patch": if (runPath) return ["GET", runPath + "/patch", null, true]; break;
    case "cancel": case "reject": if (runPath) return ["POST", runPath + "/" + message.action]; break;
    case "approve":
      if (runPath && /^[a-f0-9]{64}$/.test(message.body?.fingerprint || "")) {
        return ["POST", runPath + "/approve", {fingerprint: message.body.fingerprint,
          publish_consent: message.body.publish_consent === true}];
      }
      break;
    case "revision":
      if (runPath && typeof message.body?.feedback === "string" && typeof message.body?.request_key === "string")
        return ["POST", runPath + "/revision", {feedback: message.body.feedback, request_key: message.body.request_key}];
      break;
  }
  throw new Error("Unsupported Forge request.");
}

chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (message?.type !== "forge") return false;
  const trustedOptions = sender.url === chrome.runtime.getURL("options.html");
  const github = sender.tab && new URL(sender.url || "about:blank").origin === "https://github.com";
  if (!trustedOptions && !github) {
    respond({ok: false, error: "Forge messages are restricted to GitHub and extension settings."});
    return false;
  }
  (async () => {
    if (message.action.startsWith("model-") && !trustedOptions) throw new Error("Manage provider keys and API spending from extension settings only.");
    if (message.action === "options") {
      await chrome.runtime.openOptionsPage();
      return {opened: true};
    }
    if (message.action === "active") {
      const key = `active:${sender.tab?.id || "settings"}`;
      if (message.id === null || /^[a-f0-9]{32}$/.test(message.id || "")) {
        await chrome.storage.session.set({[key]: message.id});
      }
      return {id: (await chrome.storage.session.get(key))[key] || null};
    }
    if (message.action === "configure" && trustedOptions) {
      const baseUrl = endpoint(message.baseUrl);
      const token = String(message.token || "").trim();
      if (token.length < 24) throw new Error("Paste the full owner token from .forge/owner-token.");
      await chrome.storage.local.set({baseUrl, token});
      return {saved: true};
    }
    if (message.action === "configuration" && trustedOptions) {
      const data = await chrome.storage.local.get(["baseUrl", "token"]);
      return {baseUrl: data.baseUrl || "http://127.0.0.1:8787", paired: Boolean(data.token)};
    }
    if (message.action === "github-setup" && !trustedOptions) throw new Error("Start GitHub setup from Connection settings.");
    const [method, path, body, text] = allowedRequest(message);
    const config = await chrome.storage.local.get(["baseUrl", "token"]);
    if (!config.token) throw new Error("Connect Forge first. Open Connection and paste your local owner token.");
    let response;
    try {
      response = await fetch(endpoint(config.baseUrl) + path, {method,
        headers: {Authorization: `Bearer ${config.token}`, "Content-Type": "application/json"},
        ...(body ? {body: JSON.stringify(body)} : {}), signal: AbortSignal.timeout(message.action.startsWith("model-") ? 60_000 : 30_000),
        credentials: "omit", redirect: "error"});
    } catch {
      throw new Error("Forge is offline. Start the local service, then reconnect.");
    }
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${response.status}).`);
    }
    if (message.action === "github-setup") {
      const data = await response.json();
      const url = new URL(data.url);
      if (url.origin !== "http://127.0.0.1:8787" || url.pathname !== "/setup/github") throw new Error("Unexpected setup address.");
      await chrome.tabs.create({url: url.href});
      return {opened: true};
    }
    return text ? {text: await response.text()} : response.json();
  })().then(data => respond({ok: true, data})).catch(error => respond({ok: false, error: error.message}));
  return true;
});
