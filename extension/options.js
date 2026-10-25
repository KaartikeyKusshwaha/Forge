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
}
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
