/* Real unpacked-extension test; GitHub page is an intercepted fixture, backend and worker are real. */
const {chromium} = require("playwright");
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const vm = require("node:vm");

async function screenshot(page, name) {
  for (let attempt = 0; attempt < 4; attempt++) {
    try { await page.locator(".panel").screenshot({path: `test-results/${name}.png`}); return; }
    catch(error) { if (attempt === 3 || !/attached|stable/.test(error.message)) throw error; }
  }
}

(async () => {
  const extension = path.resolve("extension");
  const profile = path.resolve(".forge", "browser-" + Date.now());
  fs.mkdirSync("test-results", {recursive: true});
  const token = fs.readFileSync(".forge/owner-token", "utf8").trim();
  const bridgeMode = process.env.FORGE_TEST_UI_BRIDGE === "1";
  let browser;
  const context = bridgeMode ? await (async () => {
    browser = await chromium.launch({headless: true});
    return browser.newContext({viewport: {width: 1440, height: 1000}});
  })() : await chromium.launchPersistentContext(profile, {
    channel: "chromium", headless: true, viewport: {width: 1440, height: 1000},
    ...(process.env.FORGE_TEST_CHROMIUM ? {executablePath: process.env.FORGE_TEST_CHROMIUM} : {}),
    args: [`--disable-extensions-except=${extension}`, `--load-extension=${extension}`],
    ignoreDefaultArgs: ["--disable-extensions"],
  });
  const errors = [];
  try {
    if (!bridgeMode) {
      let worker = context.serviceWorkers()[0];
      if (!worker) worker = await context.waitForEvent("serviceworker");
      await worker.evaluate(async ({token}) => {
        await chrome.storage.local.set({baseUrl: "http://127.0.0.1:8787", token});
      }, {token});
    } else {
      // Test the actual service-worker source with a storage/runtime shim when Windows
      // cannot start the full extension-capable Chromium. This is NOT an installed-extension test.
      let listener;
      const data = {baseUrl: "http://127.0.0.1:8787", token};
      const storage = {get: async keys => Object.fromEntries((Array.isArray(keys) ? keys : [keys]).map(k => [k, data[k]])),
        set: async values => Object.assign(data, values), setAccessLevel: async () => {}};
      const chrome = {storage: {local: storage, session: storage}, action: {onClicked: {addListener() {}}},
        runtime: {getURL: file => "chrome-extension://test/" + file, openOptionsPage: async () => {},
          onMessage: {addListener(fn) {listener = fn;}}}};
      vm.runInNewContext(fs.readFileSync("extension/background.js", "utf8"), {chrome, URL, fetch, AbortSignal, console});
      await context.exposeBinding("forgeTestBridge", (source, message) => new Promise(resolve => {
        listener(message, {url: source.frame.url(), tab: {id: 1}}, resolve);
      }));
      await context.addInitScript(() => {
        window.chrome = {runtime: {getURL: file => "https://github.com/forge-test-assets/" + file,
          sendMessage: message => window.forgeTestBridge(message)}};
      });
      await context.route("https://github.com/forge-test-assets/panel.css", route => route.fulfill({
        contentType: "text/css", body: fs.readFileSync("extension/panel.css", "utf8")}));
    }
    const page = await context.newPage();
    page.on("pageerror", e => errors.push(e.message));
    await page.route("https://github.com/forge-demo/sample-api/issues/42", route => route.fulfill({
      contentType: "text/html", body: `<!doctype html><html lang="en" data-color-mode="light"><head><meta charset="utf-8"><title>Sample issue · Forge test fixture</title><style>
      body{margin:0;color:#252b32;background:#fff;font:14px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}header{padding:20px 36px;background:#f6f8fa;border-bottom:1px solid #d8dee4;display:flex;gap:26px;align-items:center}header b{font-size:19px}nav{padding:20px 38px;border-bottom:1px solid #d8dee4;color:#59636e;word-spacing:25px}main{margin:55px 70px;max-width:810px}h1{font-size:30px;font-weight:500;letter-spacing:-.5px}h1 span{color:#8b949e}small{color:#656d76}article{border:1px solid #d8dee4;border-radius:8px;margin-top:32px;padding:28px;font-size:15px;line-height:1.9}code{background:#f1f3f5;border-radius:4px;padding:3px 5px}aside{margin-top:40px;color:#7c858e;font-size:12px}
      </style></head><body><header><b>◉</b><strong>forge-demo / sample-api</strong><span>Public repository fixture</span></header><nav>Code Issues Pull-requests Actions Settings</nav><main><h1><bdi data-testid="issue-title">Reject a page size of zero</bdi> <span>#42</span></h1><small>Open · sample-maintainer opened this issue · 2 comments</small><article><strong>Page-size validation accepts zero.</strong><p><code>validate_limit(0)</code> currently returns zero. It should raise <code>ValueError</code>, while retaining valid values from 1 to 100.</p><p>Please add a regression test and keep the change focused.</p></article><aside>INTERCEPTED GITHUB PAGE · OWNED TEST FIXTURE · NO LIVE REPOSITORY CHANGES</aside></main></body></html>`}));
    await page.goto("https://github.com/forge-demo/sample-api/issues/42");
    if (bridgeMode) await page.addScriptTag({path: "extension/content.js"});
    await page.getByRole("button", {name: "Open Forge", exact: true}).click();
    await page.getByRole("heading", {name: "From issue to possibility."}).waitFor();
    await page.waitForFunction(() => !document.querySelector("#forge-companion").shadowRoot.querySelector('[data-action="demo"]').disabled);
    await screenshot(page, "forge-welcome");
    await page.getByRole("button", {name: "Run bundled demo", exact: true}).click();
    await page.getByRole("button", {name: "Approve demo proposal", exact: true}).waitFor({timeout: 45_000});
    await screenshot(page, "forge-progress");
    await page.getByRole("tab", {name: "Changes"}).click();
    await page.getByRole("button", {name: "pagination.py M", exact: true}).waitFor();
    assert.match(await page.locator(".diff-box").innerText(), /limit <= 0/);
    await page.getByRole("button", {name: "test_pagination.py M", exact: true}).click();
    assert.match(await page.locator(".diff-box").innerText(), /test_zero_limit/);
    await screenshot(page, "forge-changes");
    await page.getByRole("tab", {name: "Checks"}).click();
    assert.equal(await page.locator(".check-card").count(), 3);
    assert.match(await page.locator(".checks-list").innerText(), /Reproduced/);
    await screenshot(page, "forge-checks");
    await page.evaluate(() => document.documentElement.dataset.colorMode = "dark");
    await page.locator('.forge[data-theme="dark"]').waitFor({state: "attached"});
    await screenshot(page, "forge-dark");
    await page.getByRole("button", {name: "Approve demo proposal", exact: true}).click();
    await page.getByText("Demo complete. No GitHub changes made.", {exact: true}).waitFor({timeout: 15_000});
    await page.getByRole("button", {name: "Recent runs", exact: true}).click();
    await page.locator(".history-row").first().waitFor();
    assert.ok(await page.locator(".history-row").count() > 0);
    await page.getByRole("button", {name: "Back", exact: true}).click();
    await page.getByRole("button", {name: "Back to this issue", exact: true}).click();
    await page.setViewportSize({width: 390, height: 844});
    await screenshot(page, "forge-mobile");
    const overflow = await page.locator(".panel").evaluate(el => el.scrollWidth > el.clientWidth);
    assert.equal(overflow, false, "Panel must not overflow on mobile");
    await page.getByRole("button", {name: "Close Forge", exact: true}).click();
    await page.getByRole("button", {name: "Open Forge", exact: true}).waitFor();
    assert.deepEqual(errors, []);
    console.log(`PASS · ${bridgeMode ? "UI + real background source through test bridge" : "unpacked extension"}, bundled run, diff switching, checks, approval, history, dark theme, mobile, close`);
    fs.writeFileSync("test-results/extension-report.json", JSON.stringify({passed: true,
      page: "Intercepted GitHub issue fixture", backend: "Real localhost API and worker",
      browser_mode: bridgeMode ? "Headless UI; runtime/storage bridge; installed-extension validation pending" : "Real unpacked extension",
      model: "Scripted bundled fixture; no API calls", errors, screenshots: 6}, null, 2));
  } finally {
    await context.close();
    if (browser) await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
