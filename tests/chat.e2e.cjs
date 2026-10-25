/* Agent chat UI contract: no live provider calls or GitHub writes. */
const {chromium} = require("playwright");
const fs = require("node:fs");
const assert = require("node:assert/strict");
(async () => {
  const browser = await chromium.launch({headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1280,height:900}});
    await page.route("https://github.com/**", route=>route.fulfill({contentType:"text/html",body:'<html data-color-mode="dark"><body>Repository fixture</body></html>'}));
    await page.goto("https://github.com/owner/repo");
    await page.evaluate(()=>{
      const run={id:"a".repeat(32),repo:"owner/repo",issue:0,mode:"github",conversation_only:true,status:"needs_input",title:"Conversation",events:[],usage:{},chat:[]};
      window.chrome={runtime:{getURL:()=>"data:text/css,",sendMessage:async message=>{
        if(message.action==="status") return {ok:true,data:{github:true,model:true,runner:true}};
        if(message.action==="active") return {ok:true,data:{id:message.id||null}};
        if(message.action==="conversation" || message.action==="run") return {ok:true,data:run};
        if(message.action==="chat") {
          if(window.failChat) return {ok:false,error:"Service unavailable; retry"};
          run.chat.push({id:message.body.request_key,message:message.body.message,reply:"I can help refine that change. Build from conversation creates a checked proposal.",status:"answered",created:Date.now()/1000});
          return {ok:true,data:run};
        }
        if(message.action==="revision") {window.builtFeedback=message.body.feedback;return {ok:false,error:"Fixture stops before execution"};}
        return {ok:true,data:{}};
      }}};
    });
    await page.addScriptTag({content:fs.readFileSync("extension/content.js","utf8")});
    await page.evaluate(css=>{const style=document.createElement("style");style.textContent=css;document.querySelector("#forge-companion").shadowRoot.append(style);},fs.readFileSync("extension/panel.css","utf8"));
    await page.getByRole("button",{name:"Open Forge",exact:true}).click();
    await page.getByRole("button",{name:"Talk to Forge",exact:true}).click();
    assert.equal(await page.getByRole("button",{name:/Request follow-up changes|Analyze failure with Groq|Suggest changes/}).count(),0);
    const input=page.getByRole("textbox",{name:"Message Forge",exact:true});
    await page.evaluate(()=>document.addEventListener("keydown",event=>{if(event.composedPath().some(el=>el?.tagName === "TEXTAREA")){event.preventDefault();window.pageShortcutCaptured=true;}}));
    await input.focus();await input.pressSequentially("Typing works");
    assert.equal(await input.inputValue(),"Typing works");
    assert.equal(await page.evaluate(()=>Boolean(window.pageShortcutCaptured)),false);
    await input.fill("Please add keyboard navigation and <script>alert(1)</script> tests.");
    await input.press("Control+Enter");
    await page.getByRole("log",{name:"Agent conversation"}).getByText(/I can help refine/).waitFor();
    assert.equal(await input.inputValue(),"");
    assert.equal(await page.getByRole("log").locator("script").count(),0);
    await page.evaluate(()=>window.failChat=true);
    await input.fill("Keep this draft if the service is offline.");
    await page.getByRole("button",{name:"Send",exact:true}).click();
    await page.getByRole("alert").filter({hasText:"Service unavailable"}).waitFor();
    assert.equal(await input.inputValue(),"Keep this draft if the service is offline.");
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.locator(".panel").evaluate(el=>el.scrollWidth>el.clientWidth),false);
    await page.screenshot({path:"test-results/forge-agent-chat.png"});
    await page.getByRole("button",{name:"Build from conversation",exact:true}).click();
    assert.match(await page.evaluate(()=>window.builtFeedback),/keyboard navigation/);
    assert.match(await page.evaluate(()=>window.builtFeedback),/Keep this draft/);
    console.log("PASS direct chat entry, conversation rendering, keyboard send, escaping, draft recovery, mobile and proposal handoff");
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
