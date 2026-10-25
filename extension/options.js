const call = async (action, values = {}) => {
  const result = await chrome.runtime.sendMessage({type: "forge", action, ...values});
  if (!result.ok) throw new Error(result.error);
  return result.data;
};
const message = document.querySelector("#message");
async function inspect() {
  const data = await call("status");
  document.querySelector("#connection").hidden = true;
  document.querySelector("#connected").hidden = false;
  document.querySelector("#connected h2").textContent = "Connected to Forge";
  document.querySelector("#github-setup").hidden = data.github;
  const box = document.querySelector("#capabilities");
  box.hidden = false;
  box.replaceChildren();
  for (const line of [
    `GitHub access: ${data.github ? data.github_auth === "cli" ? "connected · owner CLI" : "connected · App" : "not connected yet"}`,
    `Free model: ${data.model ? data.model_name : "API key needed · demo available"}`,
    `Isolated GitHub runner: ${data.runner ? "available" : "sign in to GitHub CLI"}`,
    `Publishing: ${data.publishing ? "enabled after approval" : "disabled"}`
  ]) { const p = document.createElement("div"); p.textContent = line; box.append(p); }
  document.querySelector("#model-panel").hidden = false;
  await loadProfiles();
  try {const helper=await call("setup-helper-status");document.querySelector("#helper-status").textContent=helper.configured ? "Your local Groq setup assistant is configured. Normal detection works without it." : "Optional. Detection and local configuration work without an AI API.";}catch{}
}

const modelMessage = document.querySelector("#model-message");
let connectionMethod = "key";
let setupState = null;
let setupValues = {};
let endpointConsent = false;
let billingConsent = false;
let setupEndpoint = "";
let localSetupJob = null;
let localSetupChecking = false;
for (const id of ["model-key", "model-command", "model-endpoint", "model-environment", "model-policy"]) document.querySelector("#" + id).addEventListener("input",()=>{
  endpointConsent=false;billingConsent=false;setupEndpoint="";setupValues={};setupState=null;localSetupJob=null;document.querySelector("#integration-setup").hidden=true;
});
function setupView(setup) {
  setupState = setup;
  const box=document.querySelector("#integration-setup");box.replaceChildren();box.hidden=false;
  const heading=document.createElement("h3");heading.textContent="Finish connection setup";box.append(heading);
  const text=document.createElement("p");text.textContent=setup.message;box.append(text);
  if(setup.endpoint){const endpoint=document.createElement("code");endpoint.textContent=setup.endpoint;box.append(endpoint);}
  if(setup.needs === "endpoint"){
    const input=document.createElement("input");input.id="setup-endpoint";input.type="url";input.placeholder="https://provider.example/v1";input.setAttribute("aria-label","Missing provider endpoint");box.append(input);
  }
  if(["key","environment"].includes(setup.needs)){
    for(const name of setup.variables || ["API_KEY"]){const label=document.createElement("label");label.textContent=name;const input=document.createElement("input");input.type="password";input.autocomplete="off";input.dataset.variable=name;input.setAttribute("aria-label",name);box.append(label,input);}
    const note=document.createElement("p");note.textContent="Save on this device for this Forge integration. No global shell profile changes or provider key sharing.";box.append(note);
  }
  if(setup.needs === "pricing"){
    for(const [id,label] of [["setup-input-price","Input USD per million tokens"],["setup-output-price","Output USD per million tokens"]]){const l=document.createElement("label");l.textContent=label;const i=document.createElement("input");i.id=id;i.type="number";i.min="0";i.step="0.01";box.append(l,i);}
  }
  if(setup.needs === "local_runtime"){
    const note=document.createElement("p");note.textContent="Setup can install Ollama with WinGet on Windows, launch it, and download a model. Each button authorizes only that action. Models may use several GB of disk/RAM. No Docker.";box.append(note);
    const model=document.createElement("input");model.id="setup-local-model";model.placeholder="Model tag, e.g. qwen2.5-coder:7b";model.setAttribute("aria-label","Local model tag");box.append(model);
    for(const [action,label] of [["install_ollama","Approve installing Ollama on this device"],["start_ollama","Approve starting Ollama locally"],["pull_model","Approve downloading this local model"]]){const b=document.createElement("button");b.type="button";b.textContent=label;b.addEventListener("click",async()=>{b.disabled=true;try{const result=await call("device-setup-action",{body:{action,consent:true,model:model.value.trim()}});localSetupJob=result.job_id;modelMessage.textContent="Local setup started. Connection will retry when this action completes.";}catch(error){modelMessage.textContent=error.message;}finally{b.disabled=false;}});box.append(b);}
  }
  const resume=document.createElement("button");resume.type="button";
  resume.textContent=setup.needs === "free_plan" ? "Confirm Free plan and continue" : ["billing_guard","pricing"].includes(setup.needs) ? "Confirm provider billing controls and continue" : setup.needs === "endpoint_consent" ? "Approve this endpoint and continue" : "Save setup and retry connection";
  resume.addEventListener("click",()=>{
    if(setup.needs === "unsupported_catalog"){connectionMethod="endpoint";document.querySelector("#endpoint-fields").hidden=false;document.querySelector("#key-fields").hidden=false;document.querySelector("#model-endpoint").focus();return;}
    if(setup.needs === "endpoint"){setupEndpoint=box.querySelector("#setup-endpoint").value;document.querySelector("#model-endpoint").value=setupEndpoint;document.querySelector("#endpoint-fields").hidden=false;}
    if(setup.needs === "free_plan") document.querySelector("#model-groq-confirmed").checked=true;
    if(setup.needs === "endpoint_consent") endpointConsent=setup.endpoint;
    if(["billing_guard","pricing"].includes(setup.needs)) billingConsent=true;
    for(const input of box.querySelectorAll("[data-variable]")){if(input.value)setupValues[input.dataset.variable]=input.value;}
    if(setup.needs === "key") document.querySelector("#model-key").value=setupValues.API_KEY || "";
    document.querySelector("#model-connection").requestSubmit();
  });box.append(resume);
}
document.querySelector("#model-command").addEventListener("input", event => {
  if (event.target.value.trim()) document.querySelector("#model-environment").value = "";
});
document.querySelector("#model-environment").addEventListener("change", event => {
  if (event.target.value) document.querySelector("#model-command").value = "";
});
document.querySelectorAll("[data-method]").forEach(button => button.addEventListener("click", () => {
  connectionMethod = button.dataset.method;
  document.querySelectorAll("[data-method]").forEach(item=>item.setAttribute("aria-pressed",String(item===button)));
  document.querySelector("#endpoint-fields").hidden = connectionMethod !== "endpoint";
  document.querySelector("#cli-fields").hidden = connectionMethod !== "cli";
  document.querySelector("#key-fields").hidden = connectionMethod === "cli";
}));
document.querySelector("#model-policy").addEventListener("change", event => {
  document.querySelector("#model-budget-fields").hidden = !["capped","ask_paid"].includes(event.target.value);
  document.querySelector("#model-limit-fields").hidden = event.target.value !== "limited";
});

function profileView(data) {
  const list = document.querySelector("#model-profiles"); list.replaceChildren();
  for (const profile of data.profiles || []) {
    const box = document.createElement("article"); box.className="model-profile";
    const heading = document.createElement("h3"); heading.textContent=profile.label + (profile.active ? " · Active" : ""); box.append(heading);
    const info=document.createElement("p"); info.textContent=`${profile.provider} · ${profile.mode === "unlimited" ? "No Forge usage cap" : profile.mode === "limited" ? "Call and token limits" : profile.mode === "free_only" ? "Free usage" : profile.mode}`; box.append(info);
    if(profile.mode === "limited"){const used=document.createElement("p");used.textContent=`${profile.usage?.calls || 0} / ${profile.call_limit || 100} calls · ${profile.usage?.tokens || 0} / ${profile.token_limit || 1000000} tokens`;box.append(used);}
    const policy=document.createElement("select");policy.setAttribute("aria-label",`Usage policy for ${profile.label}`);
    for(const [value,label] of [["free_only","Free usage"],["limited","Limited API usage"],["unlimited","Unlimited · no Forge usage cap"]]){const option=document.createElement("option");option.value=value;option.textContent=label;option.selected=profile.mode===value;policy.append(option);}box.append(policy);
    const calls=document.createElement("input");calls.type="number";calls.min="1";calls.value=profile.call_limit || 100;calls.setAttribute("aria-label",`API call limit for ${profile.label}`);
    const tokens=document.createElement("input");tokens.type="number";tokens.min="1000";tokens.value=profile.token_limit || 1000000;tokens.setAttribute("aria-label",`Token limit for ${profile.label}`);
    function policyFields(){calls.hidden=tokens.hidden=policy.value!=="limited";}policy.addEventListener("change",policyFields);policyFields();box.append(calls,tokens);
    const savePolicy=document.createElement("button");savePolicy.type="button";savePolicy.textContent="Save usage permissions";savePolicy.addEventListener("click",async()=>{savePolicy.disabled=true;try{profileView(await call("model-policy",{id:profile.id,body:{mode:policy.value,call_limit:Number(calls.value),token_limit:Number(tokens.value)}}));await inspect();}catch(error){modelMessage.textContent=error.message;}finally{savePolicy.disabled=false;}});box.append(savePolicy);
    if(profile.endpoint){const endpoint=document.createElement("p");endpoint.textContent=profile.endpoint;box.append(endpoint);}
    if(profile.billing_basis){const note=document.createElement("p");note.textContent=profile.billing_basis;box.append(note);}
    const select=document.createElement("select"); select.setAttribute("aria-label",`Model for ${profile.label}`);
    for(const model of profile.models) {const option=document.createElement("option");option.value=model.id;option.textContent=model.name + (model.free ? profile.compatible ? " · Account free allowance" : " · Free" : " · Paid");option.selected=model.id===profile.model;select.append(option);} box.append(select);
    const activate=document.createElement("button"); activate.type="button"; activate.textContent="Use this model";
    if(profile.setup_only){activate.disabled=true;activate.textContent="Setup assistance only";}
    activate.addEventListener("click",async()=>{activate.disabled=true;try {profileView(await call("model-activate",{id:profile.id,model:select.value}));modelMessage.textContent="Model connected. New runs use this profile.";await inspect();}catch(error){modelMessage.textContent=error.message;}finally{activate.disabled=false;}}); box.append(activate);
    if(!profile.active){const remove=document.createElement("button");remove.type="button";remove.textContent="Remove profile";remove.addEventListener("click",async()=>{try{profileView(await call("model-delete",{id:profile.id}));}catch(error){modelMessage.textContent=error.message;}});box.append(remove);} list.append(box);
  }
}
async function loadProfiles(){profileView(await call("model-profiles"));await loadSpending();}
async function loadSpending(){
  const data=await call("model-spending"), list=document.querySelector("#model-spending");list.replaceChildren();
  if(!data.requests?.length){list.textContent="No API spending requests awaiting permission.";return;}
  for(const request of data.requests){const box=document.createElement("article");box.className="model-profile";const text=document.createElement("p");text.textContent=`${request.role} · Run ${request.run_id || "connection test"} · maximum $${Number(request.maximum_usd).toFixed(6)}`;box.append(text);
    for(const approve of [true,false]){const button=document.createElement("button");button.type="button";button.textContent=approve ? "Approve this API call" : "Decline";button.addEventListener("click",async()=>{button.disabled=true;try{await call("model-decide",{id:request.id,approve});await loadSpending();}catch(error){modelMessage.textContent=error.message;}});box.append(button);}list.append(box);
  }
}
document.querySelector("#model-connection").addEventListener("submit",async event=>{
  event.preventDefault();if(!event.isTrusted)return;
  const button=event.target.querySelector('button[type="submit"]');button.disabled=true;modelMessage.textContent="Detecting provider and checking model access…";
  try{
    const mode=document.querySelector("#model-policy").value;
    const body={api_key:document.querySelector("#model-key").value,provider:"auto",label:document.querySelector("#model-label").value,mode,budget_usd:["capped","ask_paid"].includes(mode) ? Number(document.querySelector("#model-budget").value) : 0,call_limit:Number(document.querySelector("#model-call-limit").value),token_limit:Number(document.querySelector("#model-token-limit").value),groq_confirmed:document.querySelector("#model-groq-confirmed").checked,
      endpoint:setupEndpoint || (connectionMethod === "endpoint" ? document.querySelector("#model-endpoint").value : ""),command:connectionMethod === "cli" ? document.querySelector("#model-command").value : "",environment:connectionMethod === "cli" ? document.querySelector("#model-environment").value : "",
      environment_values:setupValues,endpoint_consent:Boolean(endpointConsent && endpointConsent === (setupState?.endpoint || document.querySelector("#model-endpoint").value)),billing_guard_confirmed:billingConsent,
      input_price:document.querySelector("#setup-input-price")?.value ? Number(document.querySelector("#setup-input-price").value) : null,output_price:document.querySelector("#setup-output-price")?.value ? Number(document.querySelector("#setup-output-price").value) : null};
    const response=await call("model-connect",{body});if(response.setup){setupView(response.setup);modelMessage.textContent="A setup step is needed before connecting.";return;}
    profileView(response);document.querySelector("#model-key").value="";document.querySelector("#model-command").value="";document.querySelector("#integration-setup").hidden=true;setupValues={};setupState=null;setupEndpoint="";endpointConsent=false;billingConsent=false;modelMessage.textContent="Connected. Forge selected a compatible model; change it in your saved profile if needed.";await inspect();
  }catch(error){modelMessage.textContent=error.message;}finally{button.disabled=false;}
});
document.querySelector("#helper-connect").addEventListener("click",async()=>{const button=document.querySelector("#helper-connect");button.disabled=true;try{await call("setup-helper-connect",{body:{api_key:document.querySelector("#helper-key").value,groq_confirmed:document.querySelector("#helper-free").checked,activate:false}});document.querySelector("#helper-key").value="";document.querySelector("#helper-status").textContent="Your Groq setup assistant is connected. The coding model is unchanged.";}catch(error){document.querySelector("#helper-status").textContent=error.message;}finally{button.disabled=false;}});
document.querySelector("#setup-help").addEventListener("click",async()=>{const button=document.querySelector("#setup-help");button.disabled=true;try{const result=await call("setup-helper-analyze",{body:{use_connected_model:document.querySelector("#setup-help-source").value === "connected",command:document.querySelector("#model-command").value,endpoint:document.querySelector("#model-endpoint").value}});document.querySelector("#setup-help-result").textContent=[result.summary || result.message,...(result.steps || [])].filter(Boolean).join("\n");}catch(error){document.querySelector("#setup-help-result").textContent=error.message;}finally{button.disabled=false;}});
setInterval(async()=>{
  if(setupState?.needs !== "local_runtime" || localSetupChecking)return;
  localSetupChecking=true;
  try{
    const data=await call("device-setup-status");
    modelMessage.textContent=(data.jobs || []).map(j=>`${j.action}: ${j.status} · ${j.message}`).join("\n") || "Waiting for local setup approval.";
    const job=(data.jobs || []).find(j=>j.id===localSetupJob);
    if(job && ["complete","started","failed"].includes(job.status)){
      localSetupJob=null;
      if(job.status !== "failed")document.querySelector("#model-connection").requestSubmit();
    }
  }catch{}finally{localSetupChecking=false;}
},3000);
setInterval(()=>{if(!document.querySelector("#model-panel").hidden)loadSpending().catch(()=>{});},5000);
document.querySelector("#change-connection").addEventListener("click", () => {
  document.querySelector("#connection").hidden = false;
  document.querySelector("#connected").hidden = true;
  document.querySelector("#token").focus();
});
document.querySelector("#check-connection").addEventListener("click", async () => {
  try {await inspect(); message.textContent = "Connected. Ready inside GitHub.";}
  catch(error) {document.querySelector("#connected h2").textContent = "Paired · service unavailable"; message.textContent = error.message;}
});
document.querySelector("#connection").addEventListener("submit", async event => {
  event.preventDefault();
  if (!event.isTrusted) return;
  const button = event.target.querySelector("button"); button.disabled = true;
  message.textContent = "Connecting…";
  try {
    await call("configure", {baseUrl: document.querySelector("#endpoint").value, token: document.querySelector("#token").value});
    await inspect();
    document.querySelector("#token").value = "";
    message.textContent = "Connected. Open a GitHub issue and choose Forge.";
  } catch (error) { message.textContent = error.message; }
  finally { button.disabled = false; }
});
document.querySelector("#connect-github").addEventListener("click", async event => {
  if (!event.isTrusted) return;
  const button = event.currentTarget;
  button.disabled = true;
  try {
    await call("github-setup");
    message.textContent = "Complete App registration and repository selection on GitHub, then return here.";
  } catch(error) { message.textContent = error.message; }
  finally { button.disabled = false; }
});
(async () => {
  const config = await call("configuration");
  document.querySelector("#endpoint").value = config.baseUrl;
  if (config.paired) {
    document.querySelector("#connected").hidden = false;
    document.querySelector("#connected h2").textContent = "Checking connection…";
    message.textContent = "This browser is paired. Checking service…";
    try { await inspect(); message.textContent = "Connected. Ready inside GitHub."; }
    catch(error) { document.querySelector("#connected h2").textContent = "Paired · service unavailable"; message.textContent = error.message; }
  } else document.querySelector("#connection").hidden = false;
})();
