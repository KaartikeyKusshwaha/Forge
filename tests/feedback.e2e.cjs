/* Focused UI fixtures: no GitHub writes or model calls. */
const {chromium} = require("playwright");
const fs = require("node:fs");
const assert = require("node:assert/strict");
(async () => {
  const browser = await chromium.launch({headless: true});
  try {
    const page = await browser.newPage();
    await page.route("https://github.com/**", route => route.fulfill({contentType: "text/html", body: "<html><body>Issue fixture</body></html>"}));
    await page.goto("https://github.com/owner/repo/issues/1");
    await page.evaluate(() => {
      const run = {id: "a".repeat(32), repo: "owner/repo", issue: 1, mode: "github",
        title: "Issue fixture", status: "awaiting_approval", created: Date.now()/1000,
        events: [{created: Date.now()/1000, message: "Candidate verified"}], usage: {}};
      window.chrome = {runtime: {getURL: () => "data:text/css,", sendMessage: async message => {
        if (message.action === "status") return {ok: true, data: {github:true, model:true, runner:true}};
        if (message.action === "active") return {ok:true, data:{id:run.id}};
        if (message.action === "run") return {ok:true, data:run};
        if (message.action === "revision") {window.sentFeedback = message.body.feedback; return {ok:false, error:"Fixture retry error"};}
        return {ok:true, data:{}};
      }}};
    });
    await page.addScriptTag({content: fs.readFileSync("extension/content.js", "utf8")});
    await page.evaluate(css => {const style=document.createElement("style");style.textContent=css;document.querySelector("#forge-companion").shadowRoot.append(style);}, fs.readFileSync("extension/panel.css", "utf8"));
    await page.getByRole("button", {name:"Open Forge", exact:true}).click();
    await page.getByRole("button", {name:"Suggest changes", exact:true}).click();
    await page.getByRole("dialog").waitFor();
    const input = page.getByRole("textbox", {name:"Your request"});
    await input.fill("Also reject booleans and cover the boundary values.");
    await page.getByRole("button", {name:"Create revised proposal", exact:true}).click();
    await page.getByRole("dialog").getByRole("alert").waitFor();
    assert.equal(await input.inputValue(), "Also reject booleans and cover the boundary values.");
    assert.equal(await page.evaluate(() => window.sentFeedback), await input.inputValue());
    await input.focus(); await page.keyboard.press("Shift+Tab");
    assert.equal(await page.getByRole("button", {name:"Create revised proposal", exact:true}).evaluate(el=>el.matches(":focus")), true);
    await page.keyboard.press("Escape");
    await page.getByRole("dialog").waitFor({state:"detached"});
    await page.getByRole("tab", {name:"Timeline", exact:true}).click();
    assert.match(await page.locator(".panel-body").innerText(), /Candidate verified/);
    await page.setViewportSize({width:390,height:844});
    await page.getByRole("button", {name:"Suggest changes", exact:true}).click();
    assert.equal(await page.getByRole("dialog").evaluate(el=>el.scrollWidth > el.clientWidth), false);
    await page.screenshot({path:"test-results/forge-feedback.png"});

    const options = await browser.newPage();
    await options.setContent(fs.readFileSync("extension/options.html", "utf8"));
    await options.evaluate(() => {window.chrome = {runtime:{sendMessage: async message => ({ok:true, data:message.action === "configuration" ? {paired:true,baseUrl:"http://127.0.0.1:8787"} : {github:true,model:true,runner:true}})}};});
    await options.addScriptTag({content:fs.readFileSync("extension/options.js","utf8")});
    await options.getByRole("heading", {name:"Connected to Forge"}).waitFor();
    assert.equal(await options.locator("#connection").isVisible(), false);
    await options.getByRole("button", {name:"Change connection",exact:true}).click();
    assert.equal(await options.locator("#connection").isVisible(), true);
    console.log("PASS feedback submission, draft preservation, focus trap, Escape, timeline, mobile and paired connection");
  } finally {await browser.close();}
})().catch(error => {console.error(error);process.exitCode=1;});
