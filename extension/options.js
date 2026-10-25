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
}

const modelMessage = document.querySelector("#model-message");
let connectionMethod = "key";
document.querySelectorAll("[data-method]").forEach(button => button.addEventListener("click", () => {
  connectionMethod = button.dataset.method;
  document.querySelectorAll("[data-method]").forEach(item=>item.setAttribute("aria-pressed",String(item===button)));
  document.querySelector("#endpoint-fields").hidden = connectionMethod !== "endpoint";
  document.querySelector("#cli-fields").hidden = connectionMethod !== "cli";
  document.querySelector("#key-fields").hidden = connectionMethod === "cli";
}));
document.querySelector("#model-policy").addEventListener("change", event => {
  document.querySelector("#model-budget-fields").hidden = event.target.value === "free_only";
});

function profileView(data) {
  const list = document.querySelector("#model-profiles"); list.replaceChildren();
  for (const profile of data.profiles || []) {
    const box = document.createElement("article"); box.className="model-profile";
    const heading = document.createElement("h3"); heading.textContent=profile.label + (profile.active ? " · Active" : ""); box.append(heading);
    const info=document.createElement("p"); info.textContent=`${profile.provider} · ${profile.mode} · reserved/spent $${Number(profile.spent_usd || 0).toFixed(6)} / $${Number(profile.budget_usd).toFixed(2)}`; box.append(info);
    const select=document.createElement("select"); select.setAttribute("aria-label",`Model for ${profile.label}`);
    for(const model of profile.models) {const option=document.createElement("option");option.value=model.id;option.textContent=model.name + (model.free ? " · Free" : " · Paid");option.selected=model.id===profile.model;select.append(option);} box.append(select);
    const activate=document.createElement("button"); activate.type="button"; activate.textContent="Use this model";
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
    const body={api_key:connectionMethod === "cli" ? "" : document.querySelector("#model-key").value,provider:document.querySelector("#model-provider").value,label:document.querySelector("#model-label").value,mode,budget_usd:mode === "free_only" ? 0 : Number(document.querySelector("#model-budget").value),groq_confirmed:document.querySelector("#model-groq-confirmed").checked,
      endpoint:connectionMethod === "endpoint" ? document.querySelector("#model-endpoint").value : "",command:connectionMethod === "cli" ? document.querySelector("#model-command").value : "",environment:connectionMethod === "cli" ? document.querySelector("#model-environment").value : ""};
    profileView(await call("model-connect",{body}));document.querySelector("#model-key").value="";document.querySelector("#model-command").value="";modelMessage.textContent="Connected. Forge selected a compatible model; change it in your saved profile if needed.";await inspect();
  }catch(error){modelMessage.textContent=error.message;}finally{button.disabled=false;}
});
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
