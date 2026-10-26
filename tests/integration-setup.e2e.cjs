/* Interactive setup flow fixtures; no external credentials or commands are used. */
const {chromium}=require("playwright");
const fs=require("node:fs");
const assert=require("node:assert/strict");
(async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1000,height:1100}});
  await page.setContent(fs.readFileSync("extension/options.html","utf8"));
  await page.addStyleTag({content:fs.readFileSync("extension/options.css","utf8")});
  await page.evaluate(()=>{
   window.connectRequests=[];window.deviceActions=[];
   window.chrome={runtime:{sendMessage:async m=>{
    let data={};
    if(m.action==="configuration")data={paired:true,baseUrl:"http://127.0.0.1:8787"};
    if(m.action==="status")data={github:true,model:false,runner:true};
    if(m.action==="model-profiles")data=window.savedProfiles || {profiles:[]};
    if(m.action==="model-spending")data={requests:[]};
    if(m.action==="setup-helper-status")data={configured:false,required:false};
    if(m.action==="model-connect"){
     window.connectRequests.push(m.body);
     if(!m.body.environment_values?.EXAMPLE_API_KEY)data={setup:{needs:"environment",variables:["EXAMPLE_API_KEY"],endpoint:"https://example.com/v1",message:"Enter the missing environment key"}};
     else if(!m.body.endpoint_consent)data={setup:{needs:"endpoint_consent",endpoint:"https://example.com/v1",message:"Approve example.com before sending your key"}};
     else if(!m.body.billing_guard_confirmed)data={setup:{needs:"billing_guard",endpoint:"https://example.com/v1",message:"Confirm provider-side zero billing controls"}};
     else{window.savedProfiles={profiles:[{id:"a".repeat(32),label:"Example",provider:"compatible",active:true,model:"coder",mode:"free_only",budget_usd:0,models:[{id:"coder",name:"Coder",free:true}]}]};data=window.savedProfiles;}
    }
    return {ok:true,data};
   }}};
  });
  await page.addScriptTag({content:fs.readFileSync("extension/options.js","utf8")});
  await page.getByRole("button",{name:"CLI / environment",exact:true}).click();
  assert.equal(await page.locator("#model-provider").count(),0);
  await page.getByLabel("Provider API example",{exact:true}).fill('client=OpenAI(base_url="https://example.com/v1",api_key=os.getenv("EXAMPLE_API_KEY"))');
  await page.getByRole("button",{name:"Detect, verify & connect",exact:true}).click();
  await page.getByLabel("EXAMPLE_API_KEY",{exact:true}).fill("fixture-user-secret");
  await page.getByRole("button",{name:"Save setup and retry connection",exact:true}).click();
  await page.getByRole("button",{name:"Approve this endpoint and continue",exact:true}).click();
  await page.getByRole("button",{name:"Confirm provider billing controls and continue",exact:true}).click();
  await page.getByRole("heading",{name:"coder · Active",exact:true}).waitFor();
  assert.equal(await page.locator("#model-label").count(),0);
  const requests=await page.evaluate(()=>window.connectRequests);
  assert.equal(requests.length,4);
  assert.equal(requests[3].environment_values.EXAMPLE_API_KEY,"fixture-user-secret");
  assert.equal(requests[3].provider,"auto");
  assert.equal(await page.locator("#model-command").inputValue(),"");
  assert.equal(await page.locator("#integration-setup").isVisible(),false);
  await page.screenshot({path:"test-results/forge-integration-settings.png",fullPage:true});
  await page.evaluate(()=>{
    window.localReady=false;window.localConnectCount=0;
    const old=chrome.runtime.sendMessage;
    chrome.runtime.sendMessage=async message=>{
      if(message.action==="model-connect"){
        window.localConnectCount++;
        return {ok:true,data:window.localReady ? window.savedProfiles : {setup:{needs:"local_runtime",endpoint:"http://127.0.0.1:11434/v1",message:"Local runtime unavailable"}}};
      }
      if(message.action==="device-setup-action"){
        window.deviceActions.push(message.body);window.localReady=true;
        return {ok:true,data:{job_id:"fixture-job"}};
      }
      if(message.action==="device-setup-status")return {ok:true,data:{jobs:[{id:"fixture-job",action:"start_ollama",status:"started",message:"Ready"}]}};
      return old(message);
    };
  });
  await page.getByRole("button",{name:"Endpoint",exact:true}).click();
  await page.getByLabel("Provider endpoint",{exact:true}).fill("http://127.0.0.1:11434/v1");
  await page.getByRole("button",{name:"Detect, verify & connect",exact:true}).click();
  await page.getByRole("button",{name:"Approve starting Ollama locally",exact:true}).click();
  await page.waitForFunction(()=>window.localConnectCount === 2,{timeout:10000});
  await page.locator("#integration-setup").waitFor({state:"hidden"});
  assert.equal((await page.evaluate(()=>window.deviceActions))[0].consent,true);
  console.log("PASS missing-environment setup, endpoint consent, billing confirmation, automatic profile and secret field cleanup");
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
