const {test} = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");

function service(values = {}, response = null) {
  let listener, accessLevel;
  const data = {...values}, requests = [];
  const storage = {
    get: async keys => Object.fromEntries((Array.isArray(keys) ? keys : [keys]).map(k => [k, data[k]])),
    set: async values => Object.assign(data, values),
    setAccessLevel: async value => {accessLevel = value.accessLevel;},
  };
  const chrome = {storage: {local: storage, session: storage}, action: {onClicked: {addListener() {}}},
    runtime: {getURL: file => "chrome-extension://fixture/" + file, openOptionsPage: async () => {},
      onMessage: {addListener(fn) {listener = fn;}}}};
  const fetch = async (url, options) => {
    requests.push({url, options});
    return response || {ok: true, json: async () => ({service: "forge"})};
  };
  vm.runInNewContext(fs.readFileSync("extension/background.js", "utf8"), {chrome, URL, fetch, AbortSignal});
  const send = (action, extra = {}, source = "github") => new Promise(resolve => {
    const sender = source === "options" ? {url: chrome.runtime.getURL("options.html")} :
      {url: source === "github" ? "https://github.com/owner/repo/issues/1" : "https://evil.example", tab: {id: 1}};
    listener({type: "forge", action, ...extra}, sender, resolve);
  });
  return {send, requests, data, accessLevel};
}

test("an outdated owner token explains re-pairing instead of reporting offline", async () => {
  const s = service({token:"old-fixture-token"}, {ok:false,status:401,json:async()=>({})});
  const result = await s.send("status");
  assert.equal(result.ok,false);
  assert.match(result.error,/Forge is running/);
  assert.match(result.error,/owner token is outdated/);
  assert.match(result.error,/Change connection/);
});

test("background storage restricts token access and sends it only to loopback", async () => {
  const serviceWorker = service({token: "private-fixture-owner-token", baseUrl: "http://127.0.0.1:8787"});
  assert.equal(serviceWorker.accessLevel, "TRUSTED_CONTEXTS");
  const result = await serviceWorker.send("status");
  assert.equal(result.ok, true);
  assert.equal(serviceWorker.requests[0].url, "http://127.0.0.1:8787/api/status");
  assert.equal(serviceWorker.requests[0].options.headers.Authorization, "Bearer private-fixture-owner-token");
  assert.ok(!JSON.stringify(result).includes("private-fixture"));
});

test("only the extension options page can configure the backend", async () => {
  const s = service();
  const values = {baseUrl: "http://127.0.0.1:8787", token: "a-private-fixture-token-long-enough"};
  assert.equal((await s.send("configure", values)).ok, false);
  assert.equal((await s.send("configure", values, "options")).ok, true);
  const config = await s.send("configuration", {}, "options");
  assert.equal(config.data.paired, true);
  assert.equal(config.data.token, undefined);
});

test("a GitHub page cannot turn the service worker into an arbitrary fetch proxy", async () => {
  const s = service({token: "fixture-token", baseUrl: "http://127.0.0.1:8787"});
  assert.equal((await s.send("fetch", {url: "http://metadata.internal"})).ok, false);
  assert.equal((await s.send("run", {id: "../../other"})).ok, false);
  assert.equal((await s.send("status", {}, "evil")).ok, false);
  assert.equal(s.requests.length, 0);
});

test("nonloopback settings and unpaired requests are rejected", async () => {
  const s = service();
  assert.equal((await s.send("status")).ok, false);
  assert.equal((await s.send("configure", {baseUrl: "https://paid.example", token: "long-token-that-is-never-written"}, "options")).ok, false);
  assert.equal(s.requests.length, 0);
});

test("GitHub pages cannot manage provider keys or grant API spending", async () => {
  const s=service({token:"fixture-token",baseUrl:"http://127.0.0.1:8787"});
  for(const action of ["model-policy","model-connect","model-profiles","model-delete","model-decide","setup-helper-connect","setup-helper-analyze","device-setup-action"]){
    assert.equal((await s.send(action,{id:"a".repeat(32),body:{api_key:"fixture-provider-secret"},approve:true})).ok,false);
  }
  assert.equal(s.requests.length,0);
  assert.equal((await s.send("model-profiles",{},"options")).ok,true);
  assert.equal(s.requests[0].url,"http://127.0.0.1:8787/api/model-profiles");
});
