const button = document.querySelector("#check-api");
const statusEl = document.querySelector("#api-status");

button?.addEventListener("click", async () => {
  statusEl.textContent = "检查中...";
  try {
    const response = await fetch("/api/info");
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    statusEl.textContent = `${data.name} / ${data.stack.join(" + ")}`;
  } catch (error) {
    statusEl.textContent = `API 异常: ${error.message}`;
  }
});
