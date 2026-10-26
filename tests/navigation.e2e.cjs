/* Repository switching and request history; no external calls or repository writes. */
const {chromium} = require("playwright");
const fs = require("node:fs");
const assert = require("node:assert/strict");
(async()=>{
  const browser=await chromium.launch({headless:true});
  try {
    const page=await browser.newPage({viewport:{width:1280,height:900}});
    await page.route("https://github.com/**",route=>route.fulfill({contentType:"text/html",body:'<html data-color-mode="dark"><body>Repository fixture</body></html>'}));
    await page.goto("https://github.com/new-owner/new-repo");
    await page.evaluate(()=>{
      const old={id:"a".repeat(32),repo:"old-owner/old-repo",issue:1,title:"Previous change",status:"failed",mode:"github",created:Date.now()/1000,events:[{message:"Previous check failed",created:Date.now()/1000}],chat:[]};
      const fresh={...old,id:"b".repeat(32),repo:"new-owner/new-repo",issue:0,title:"New contribution",status:"queued"};
      window.calls=[];let active=old.id;
      window.chrome={runtime:{getURL:()=>"data:text/css,",sendMessage:async m=>{
        window.calls.push(m);let data={};
        if(m.action==="status") data={github:true,model:true,runner:true};
        if(m.action==="active") {if(Object.hasOwn(m,"id"))active=m.id;data={id:active};}
        if(m.action==="run") data=m.id===old.id ? old : fresh;
        if(m.action==="list") data={runs:[fresh,old]};
        if(m.action==="create") data=fresh;
        return {ok:true,data};
      }}};
    });
    await page.addScriptTag({content:fs.readFileSync("extension/content.js","utf8")});
    await page.evaluate(css=>{const style=document.createElement("style");style.textContent=css;document.querySelector("#forge-companion").shadowRoot.append(style);},fs.readFileSync("extension/panel.css","utf8"));
    await page.getByRole("button",{name:"Open Forge",exact:true}).click();
    await page.getByRole("button",{name:"Start new request",exact:true}).waitFor();
    assert.equal(await page.getByRole("heading",{name:"Previous change",exact:true}).count(),0);
    assert.match(await page.getByRole("link",{name:"Create a GitHub issue"}).getAttribute("href"),/new-owner\/new-repo\/issues\/new/);
    await page.getByRole("textbox",{name:"Or describe your contribution"}).fill("Add tests for the new repository.");
    await page.getByRole("button",{name:"Start new request",exact:true}).click();
    await page.getByRole("heading",{name:"New contribution",exact:true}).waitFor();
    const created=await page.evaluate(()=>window.calls.find(m=>m.action==="create"));
    assert.equal(created.body.repo,"new-owner/new-repo");
    assert.equal(created.body.issue,0);
    await page.getByRole("tab",{name:"History",exact:true}).click();
    await page.getByText("Current request timeline · New contribution",{exact:true}).waitFor();
    await page.getByRole("button",{name:/Previous change/}).click();
    await page.getByRole("heading",{name:"Previous change",exact:true}).waitFor();
    await page.getByRole("tab",{name:"Changes",exact:true}).click();
    await page.getByRole("button",{name:"Start afresh",exact:true}).click();
    await page.getByRole("button",{name:"Start new request",exact:true}).waitFor();
    assert.equal(await page.getByRole("textbox",{name:"Or describe your contribution"}).inputValue(),"");
    assert.equal(await page.getByRole("tab").count(),0);
    await page.getByRole("button",{name:"History",exact:true}).click();
    assert.equal(await page.locator(".history-row").count(),2);
    await page.getByRole("button",{name:"Start afresh",exact:true}).click();
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.locator(".panel").evaluate(el=>el.scrollWidth>el.clientWidth),false);
    await page.screenshot({path:"test-results/forge-start-afresh.png"});
    console.log("PASS repository-scoped restore, new request, combined history, previous changes, start afresh and preserved history");
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
