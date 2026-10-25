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
      const published = {...run, id:"b".repeat(32), title:"Published fix", status:"pr_opened", publication:{pr_url:"https://github.com/owner/repo/pull/7",commit_sha:"c".repeat(40),write_repo:"contributor/repo",branch:"forge/fix"}};
      window.chrome = {runtime: {getURL: () => "data:text/css,", sendMessage: async message => {
        if (message.action === "status") return {ok: true, data: {github:true, model:true, runner:true}};
        if (message.action === "active") return {ok:true, data:{id:run.id}};
        if (message.action === "run") return {ok:true, data:message.id === published.id ? published : run};
        if (message.action === "list") return {ok:true, data:{runs:[run,published]}};
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
    await page.keyboard.press("Escape");
    await page.getByRole("button", {name:"Recent runs",exact:true}).click();
    await page.getByRole("button", {name:"Commits & pull requests",exact:true}).click();
    assert.equal(await page.locator(".history-row").count(), 1);
    await page.locator(".history-row").click();
    await page.getByRole("tab", {name:"Timeline",exact:true}).click();
    assert.equal(await page.locator('a[href="https://github.com/contributor/repo/commit/' + "c".repeat(40) + '"]').count(),1);
    await page.getByRole("button", {name:"Request follow-up changes",exact:true}).click();
    await page.getByRole("dialog").waitFor();

    const repoPage = await browser.newPage();
    await repoPage.route("https://github.com/**", route => route.fulfill({contentType:"text/html",body:"<html><body>Repository fixture</body></html>"}));
    await repoPage.goto("https://github.com/owner/repo");
    await repoPage.evaluate(() => {window.chrome={runtime:{getURL:()=>"data:text/css,",sendMessage:async message=> {
      const values={status:{github:true,model:true,runner:true},active:{id:null},list:{runs:[]},"analyze-repo":{enabled:true,file_count:5,base_sha:"a".repeat(40),tests:["tests/test_a.py"],guides:[],limitations:["Blender runtime unavailable"],issues:[{number:2,title:"Fix validation"}]}};
      if(message.action === "create") {window.createdTask=message.body; return {ok:false,error:"Fixture ends before execution"};}
      return {ok:true,data:values[message.action]};
    }}};});
    await repoPage.addScriptTag({content:fs.readFileSync("extension/content.js","utf8")});
    await repoPage.evaluate(css=>{const s=document.createElement("style");s.textContent=css;document.querySelector("#forge-companion").shadowRoot.append(s);},fs.readFileSync("extension/panel.css","utf8"));
    await repoPage.getByRole("button", {name:"Open Forge",exact:true}).click();
    await repoPage.getByRole("button", {name:"Enable and analyze repository",exact:true}).click();
    await repoPage.getByRole("link", {name:"#2 Fix validation",exact:true}).waitFor();
    await repoPage.getByRole("textbox", {name:"Or describe your contribution"}).fill("Add a regression test for invalid page sizes.");
    await repoPage.getByRole("button", {name:"Analyze my task and propose changes",exact:true}).click();
    const task=await repoPage.evaluate(()=>window.createdTask);
    assert.equal(task.issue,0); assert.equal(task.mode,"github"); assert.match(task.request,/regression/);

    const options = await browser.newPage();
    await options.setContent(fs.readFileSync("extension/options.html", "utf8"));
    await options.evaluate(() => {window.chrome = {runtime:{sendMessage: async message => {
      if(message.action === "model-profiles") return {ok:true,data:window.savedModels || {profiles:[]}}; if(message.action === "model-connect") {window.modelConnection=message.body;window.savedModels={profiles:[{id:"d".repeat(32),label:"Inkling",active:true,provider:"openrouter-free",mode:message.body.mode,budget_usd:0,model:"thinkingmachines/inkling:free",models:[{id:"thinkingmachines/inkling:free",name:"Inkling",free:true}]}]}; return {ok:true,data:window.savedModels};}
      return {ok:true,data:message.action === "configuration" ? {paired:true,baseUrl:"http://127.0.0.1:8787"} : {github:true,model:true,runner:true}};
    }}};});
    await options.addScriptTag({content:fs.readFileSync("extension/options.js","utf8")});
    await options.getByRole("heading", {name:"Connected to Forge"}).waitFor();
    assert.equal(await options.locator("#connection").isVisible(), false);
    await options.getByRole("button", {name:"Change connection",exact:true}).click();
    assert.equal(await options.locator("#connection").isVisible(), true);
    await options.getByLabel("API key",{exact:true}).fill("sk-or-ui-fixture-not-real");
    await options.getByRole("button",{name:"Detect, verify & connect",exact:true}).click();
    await options.getByText("Inkling · Active",{exact:true}).waitFor();
    assert.equal(await options.locator("#model-key").inputValue(),"");
    assert.equal((await options.evaluate(()=>window.modelConnection)).mode,"free_only");
    await options.getByRole("button",{name:"Endpoint",exact:true}).click();
    assert.equal(await options.locator("#endpoint-fields").isVisible(),true);
    await options.getByRole("button",{name:"CLI / environment",exact:true}).click();
    assert.equal(await options.locator("#cli-fields").isVisible(),true);
    assert.equal(await options.locator("#key-fields").isVisible(),false);
    await options.getByLabel("Usage permissions",{exact:true}).selectOption("ask_paid");
    assert.equal(await options.locator("#model-budget-fields").isVisible(),true);
    console.log("PASS repository onboarding, custom task, published history, commit link, follow-up, feedback, keyboard, mobile and pairing");
  } finally {await browser.close();}
})().catch(error => {console.error(error);process.exitCode=1;});
