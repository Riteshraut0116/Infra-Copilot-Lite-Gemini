/* ==========================================================
   InfraCopilot Lite - app.js (Agentic Chat via /api/chat)
   - Chat is handled by Gemini agent through backend /api/chat
   - Dashboard buttons remain deterministic and unchanged:
       /api/healthcheck, /api/metrics, /api/report
   - ChatOps pills above chat (Health/Metrics/Report/Run/Daily) call /api/chat
   ========================================================== */

   const $ = (id) => document.getElementById(id);
   const chatEl = $("chat");
   const reportBox = $("reportBox");
   const toastEl = $("toast");
   
   let cpuChart, memChart;
   let lastHealth = null;
   let lastMetrics = null;
   let lastReport = "";
   let chatSessionId = null;
   
   // ChatOps mode (auto | health | metrics | report | daily_report)
   let chatMode = "auto";
   
   /* ------------------ UI helpers ------------------ */
   function toast(msg) {
     if (!toastEl) return;
     toastEl.textContent = msg;
     toastEl.classList.add("show");
     setTimeout(() => toastEl.classList.remove("show"), 1800);
   }
   
   function setStatus(text) {
     const pill = $("pillStatus");
     if (pill) pill.textContent = "● " + text;
   }
   
   function addMessage(role, text) {
     if (!chatEl) return;
     const wrap = document.createElement("div");
     wrap.className = "msg " + role;
   
     // Preserve new lines
     const body = document.createElement("div");
     body.className = "body";
     body.textContent = text;
     body.style.whiteSpace = "pre-wrap";
   
     const meta = document.createElement("div");
     meta.className = "meta";
     meta.textContent = role === "user" ? "You" : "InfraCopilot";
   
     wrap.appendChild(body);
     wrap.appendChild(meta);
     chatEl.appendChild(wrap);
     chatEl.scrollTop = chatEl.scrollHeight;
   }
   
   function setKPIs(health) {
     $("kpiTotal").textContent = health?.summary?.total ?? "—";
     $("kpiHealthy").textContent = health?.summary?.healthy ?? "—";
     $("kpiWarnings").textContent = health?.summary?.warnings ?? "—";
   
     const warnText =
       health?.warnings && health.warnings.length ? health.warnings[0] : "No alerts";
     $("kpiWarnText").textContent = warnText;
   
     const ts = health?.timestamp
       ? new Date(health.timestamp).toLocaleString()
       : new Date().toLocaleString();
     $("chipTime").textContent = ts;
   }
   
   function avg(arr) {
     if (!arr || !arr.length) return 0;
     return arr.reduce((s, p) => s + (p?.v ?? 0), 0) / arr.length;
   }
   
   function inferRisk(health, metrics) {
     let risk = "LOW";
     let text = "All systems look stable. Continue monitoring.";
   
     const cpuAvg = metrics ? avg(metrics.cpu) : 0;
     const memAvg = metrics ? avg(metrics.memory) : 0;
     const warn = health?.summary?.warnings ?? 0;
   
     if (warn >= 2 || cpuAvg > 75 || memAvg > 80) {
       risk = "MED";
       text =
         "Potential capacity/health issues detected. Review warnings and investigate high utilization.";
     }
     if (warn >= 3 || cpuAvg > 85 || memAvg > 90) {
       risk = "HIGH";
       text =
         "High risk. Prioritize incident triage and validate resource health & scaling signals.";
     }
   
     $("riskText").textContent = text;
     const tag = document.querySelector(".riskTag");
     if (!tag) return;
   
     tag.textContent = risk;
     tag.style.background =
       risk === "HIGH"
         ? "rgba(240,68,56,.16)"
         : risk === "MED"
         ? "rgba(253,176,34,.16)"
         : "rgba(50,213,131,.16)";
     tag.style.borderColor =
       risk === "HIGH"
         ? "rgba(240,68,56,.28)"
         : risk === "MED"
         ? "rgba(253,176,34,.26)"
         : "rgba(50,213,131,.25)";
   }
   
   /* ------------------ Charts ------------------ */
   function toChartData(series) {
     series = series || [];
     return {
       labels: series.map((p) => new Date(p.t).getHours() + ":00"),
       data: series.map((p) => Math.round(((p.v ?? 0) * 10)) / 10),
     };
   }
   
   function renderCharts(metrics) {
     if (!window.Chart || !metrics) return;
   
     const cpu = toChartData(metrics.cpu || []);
     const mem = toChartData(metrics.memory || []);
   
     const baseOptions = {
       responsive: true,
       plugins: { legend: { labels: { color: "#e8eefc" } } },
       scales: {
         x: {
           ticks: { color: "rgba(232,238,252,.7)" },
           grid: { color: "rgba(255,255,255,.06)" },
         },
         y: {
           ticks: { color: "rgba(232,238,252,.7)" },
           grid: { color: "rgba(255,255,255,.06)" },
           suggestedMin: 0,
           suggestedMax: 100,
         },
       },
     };
   
     if (cpuChart) cpuChart.destroy();
     if (memChart) memChart.destroy();
   
     cpuChart = new Chart($("chartCpu"), {
       type: "line",
       data: {
         labels: cpu.labels,
         datasets: [
           {
             label: "CPU %",
             data: cpu.data,
             borderColor: "rgba(96,165,250,.95)",
             backgroundColor: "rgba(96,165,250,.15)",
             fill: true,
             tension: 0.35,
             pointRadius: 2,
           },
         ],
       },
       options: baseOptions,
     });
   
     memChart = new Chart($("chartMem"), {
       type: "line",
       data: {
         labels: mem.labels,
         datasets: [
           {
             label: "Memory %",
             data: mem.data,
             borderColor: "rgba(50,213,131,.95)",
             backgroundColor: "rgba(50,213,131,.12)",
             fill: true,
             tension: 0.35,
             pointRadius: 2,
           },
         ],
       },
       options: baseOptions,
     });
   }
   
   /* ------------------ Health details renderer ------------------ */
   function renderHealthDetails(health) {
     const el = $("healthDetails");
     if (!el || !health) return;
   
     const local = health.local || {};
     const azure = health.azure || {};
     const custom = health.custom || {};
   
     let html = "";
   
     html += `<div class="detailsItem">
       <span class="badge info">LOCAL</span>
       CPU: <b>${local.cpu_percent ?? "—"}%</b>
       &nbsp; MEM: <b>${local.memory_percent ?? "—"}%</b>
       &nbsp; DISK: <b>${local.disk_percent ?? "—"}%</b><br/>
       Uptime: <b>${
         local.uptime_seconds != null ? Math.floor(local.uptime_seconds / 3600) + "h" : "—"
       }</b>
     </div>`;
   
     if (azure.configured) {
       html += `<div class="detailsItem">
         <span class="badge info">AZURE</span>
         Status: <b>${azure.status ?? "—"}</b><br/>
         VMs: <b>${(azure.vms || []).length}</b>,
         Apps: <b>${(azure.appServices || []).length}</b>,
         Storage: <b>${(azure.storageAccounts || []).length}</b>
       </div>`;
     } else {
       html += `<div class="detailsItem">
         <span class="badge info">AZURE</span>
         Not configured. Set <code>AZURE_SUBSCRIPTION_ID</code> and <code>AZURE_RESOURCE_GROUP</code>.
       </div>`;
     }
   
     const items = custom.results || [];
     if (items.length) {
       html += `<div class="detailsItem">
         <span class="badge info">CUSTOM</span>
         Endpoints: <b>${items.length}</b>
       </div>`;
       for (const ep of items) {
         const ok = ep.status === "UP";
         html += `<div class="detailsItem">
           <span class="badge ${ok ? "up" : "down"}">${ok ? "UP" : "DOWN"}</span>
           <b>${ep.name}</b> — ${ep.latency_ms ?? "—"}ms — ${ep.http_status ?? "—"}<br/>
           <span class="muted">${ep.url}</span>
         </div>`;
       }
     } else {
       html += `<div class="detailsItem">
         <span class="badge info">CUSTOM</span>
         No endpoints configured (CUSTOM_ENDPOINTS is empty).
       </div>`;
     }
   
     el.innerHTML = html;
   }
   
   /* ------------------ API wrapper ------------------ */
   async function api(path, method = "GET", body) {
     const res = await fetch(path, {
       method,
       headers: body ? { "Content-Type": "application/json" } : undefined,
       body: body ? JSON.stringify(body) : undefined,
     });
   
     let json;
     try {
       json = await res.json();
     } catch {
       throw new Error(`API error (${res.status})`);
     }
   
     if (!json.ok) throw new Error(json.detail || json.error || "API error");
     return json;
   }
   
   /* ==========================================================
      Dashboard buttons (unchanged behavior)
      ========================================================== */
   async function runHealth() {
     try {
       setStatus("Running health check…");
       toast("Running health check…");
       const out = await api("/api/healthcheck");
       lastHealth = out.data;
       setKPIs(lastHealth);
       renderHealthDetails(lastHealth);
       inferRisk(lastHealth, lastMetrics);
       setStatus("Ready");
       toast("Health check complete ✅");
     } catch (e) {
       setStatus("Error");
       toast(`Error: ${e.message}`);
     }
   }
   
   async function loadMetrics() {
     try {
       setStatus("Loading metrics…");
       toast("Loading metrics…");
       const out = await api("/api/metrics");
       lastMetrics = out.data;
       renderCharts(lastMetrics);
       inferRisk(lastHealth, lastMetrics);
       setStatus("Ready");
       toast("Metrics loaded 📈");
     } catch (e) {
       setStatus("Error");
       toast(`Error: ${e.message}`);
     }
   }
   
   async function generateReport() {
     try {
       setStatus("Generating report…");
       toast("Generating report… (Gemini)");
       const out = await api("/api/report", "POST", {
         health: lastHealth || undefined,
         metrics: lastMetrics || undefined,
       });
   
       $("chipModel").textContent = "Model: " + (out.usedModel || "Gemini");
       lastReport = out.reportMarkdown || "";
       reportBox.textContent = lastReport || "No content returned.";
   
       setStatus("Ready");
       toast("Report generated 🧾");
     } catch (e) {
       setStatus("Error");
       toast(`Error: ${e.message}`);
     }
   }
   
   /* ==========================================================
      Agentic Chat via /api/chat (Gemini decides tools + answers)
      ========================================================== */
   
   /**
    * Update dashboard state based on tool outputs returned by /api/chat agent.
    * We support multiple shapes, so it works even if your backend returns:
    *  - { health: {...}, metrics: {...}, reportMarkdown: "..." }
    *  - { data: { health: {...}, metrics: {...} } }
    */
   function applyAgentOutputs(payload) {
     const health = payload?.health || payload?.data?.health || null;
     const metrics = payload?.metrics || payload?.data?.metrics || null;
     const reportMarkdown = payload?.reportMarkdown || payload?.data?.reportMarkdown || null;
   
     if (health) {
       lastHealth = health;
       setKPIs(lastHealth);
       renderHealthDetails(lastHealth);
     }
     if (metrics) {
       lastMetrics = metrics;
       renderCharts(lastMetrics);
     }
     if (reportMarkdown != null) {
       lastReport = reportMarkdown || "";
       if (reportBox) reportBox.textContent = lastReport || "No content returned.";
     }
   
     inferRisk(lastHealth, lastMetrics);
   }
   
   /**
    * Core chat call – ALWAYS uses /api/chat.
    * mode:
    *   auto | health | metrics | report | daily_report
    */
   async function agentChatSend(userText, mode = "auto") {
     setStatus("Thinking…");
     const out = await api("/api/chat", "POST", {
       input: userText,
       mode: mode || "auto",
       sessionId: chatSessionId || undefined,
     });
   
     // persist session id for follow-ups
     if (out.sessionId) chatSessionId = out.sessionId;
   
     // update UI with any tool results returned
     applyAgentOutputs(out);
   
     // update model chip if present
     if (out.usedModel && $("chipModel")) {
       $("chipModel").textContent = "Model: " + out.usedModel;
     }
   
     // bot answer text
     const text = out.text || out.reply || out.message || "No response.";
     addMessage("bot", text);
   
     setStatus("Ready");
   }
   
   /* ==========================================================
      ChatOps pills (above chat) – intelligent via /api/chat
      ========================================================== */
   
   function setChatMode(mode) {
     chatMode = mode || "auto";
     // Optional UI highlight: elements with [data-chatops-mode] toggle "active"
     document.querySelectorAll("[data-chatops-mode]").forEach((el) => {
       el.classList.toggle("active", (el.getAttribute("data-chatops-mode") || "").toLowerCase() === chatMode);
     });
     toast(`ChatOps mode: ${chatMode}`);
   }
   
   /**
    * Resolve ChatOps buttons by:
    *  - IDs if you have them
    *  - OR by data attributes:
    *      data-chatops="health|metrics|report|run|daily"
    *      data-chatops-mode="health|metrics|report|auto|daily_report" (optional highlight)
    */
   function bindChatOpsButtons() {
     const byId = (id) => $(id);
   
     // Preferred explicit IDs (use these if you add them in HTML)
     const btnCOHealth = byId("btnChatOpsHealth");
     const btnCOMetrics = byId("btnChatOpsMetrics");
     const btnCOReport = byId("btnChatOpsReport");
     const btnCORun = byId("btnChatOpsRun");
     const btnCODaily = byId("btnChatOpsDaily");
   
     // Fallback via data-chatops
     const q = (key) => document.querySelector(`[data-chatops="${key}"]`);
     const dHealth = q("health");
     const dMetrics = q("metrics");
     const dReport = q("report");
     const dRun = q("run");
     const dDaily = q("daily");
   
     const healthBtn = btnCOHealth || dHealth;
     const metricsBtn = btnCOMetrics || dMetrics;
     const reportBtn = btnCOReport || dReport;
     const runBtn = btnCORun || dRun;
     const dailyBtn = btnCODaily || dDaily;
   
     // Health/Metrics/Report: one-click agent run + show results
     healthBtn?.addEventListener("click", async () => {
       setChatMode("health");
       addMessage("user", "Run local health check and show results.");
       await agentChatSend("Run local health check and show results.", "health");
     });
   
     metricsBtn?.addEventListener("click", async () => {
       setChatMode("metrics");
       addMessage("user", "Load metrics for the last 24 hours and summarize.");
       await agentChatSend("Load metrics for the last 24 hours and summarize.", "metrics");
     });
   
     reportBtn?.addEventListener("click", async () => {
       setChatMode("report");
       addMessage("user", "Generate today's infra health report.");
       await agentChatSend("Generate today's infra health report.", "report");
     });
   
     // Run via Chat: uses typed input; if empty, runs current mode
     runBtn?.addEventListener("click", async () => {
       const input = $("chatInput");
       const typed = (input?.value || "").trim();
   
       // If user typed something, send as-is in current mode (or auto)
       if (typed) {
         addMessage("user", typed);
         input.value = "";
         await agentChatSend(typed, chatMode || "auto");
         return;
       }
   
       // If empty input, run based on mode
       if (chatMode === "health") {
         addMessage("user", "Run local health check and show results.");
         await agentChatSend("Run local health check and show results.", "health");
       } else if (chatMode === "metrics") {
         addMessage("user", "Load metrics for the last 24 hours and summarize.");
         await agentChatSend("Load metrics for the last 24 hours and summarize.", "metrics");
       } else if (chatMode === "report") {
         addMessage("user", "Generate today's infra health report.");
         await agentChatSend("Generate today's infra health report.", "report");
       } else if (chatMode === "daily_report") {
         addMessage("user", "Generate daily report with health + metrics and next actions.");
         await agentChatSend("Generate daily report with health + metrics and next actions.", "daily_report");
       } else {
         toast("Type a message to run, or select Health/Metrics/Report mode.");
       }
     });
   
     // Daily report (Chat): runs combined flow through agent
     dailyBtn?.addEventListener("click", async () => {
       setChatMode("daily_report");
       addMessage("user", "Generate daily report with health + metrics and next actions.");
       await agentChatSend("Generate daily report with health + metrics and next actions.", "daily_report");
     });
   }
   
   /* ==========================================================
      Wire up UI
      ========================================================== */
   window.addEventListener("DOMContentLoaded", () => {
     // Dashboard buttons (unchanged)
     $("btnHealth")?.addEventListener("click", runHealth);
     $("btnMetrics")?.addEventListener("click", loadMetrics);
     $("btnReport")?.addEventListener("click", generateReport);
     $("btnRefreshCharts")?.addEventListener("click", loadMetrics);
   
     $("btnCopyReport")?.addEventListener("click", async () => {
       if (!lastReport) return toast("No report to copy.");
       await navigator.clipboard.writeText(lastReport);
       toast("Report copied ✨");
     });
   
     $("btnDownloadReport")?.addEventListener("click", () => {
       if (!lastReport) return toast("No report to download.");
       const blob = new Blob([lastReport], { type: "text/markdown" });
       const a = document.createElement("a");
       a.href = URL.createObjectURL(blob);
       a.download = "infracopilot-report-" + Date.now() + ".md";
       a.click();
       toast("Downloaded .md");
     });
   
     // Chat form: ALWAYS agentic /api/chat
     $("chatForm")?.addEventListener("submit", async (e) => {
       e.preventDefault();
       const input = $("chatInput");
       const text = input.value.trim();
       if (!text) return;
   
       addMessage("user", text);
       input.value = "";
       await agentChatSend(text, chatMode || "auto");
     });
   
     // Existing “quick pills” (keep as-is if present)
     $("quickHealth")?.addEventListener("click", () => $("btnHealth")?.click());
     $("quickMetrics")?.addEventListener("click", () => $("btnMetrics")?.click());
     $("quickReport")?.addEventListener("click", () => $("btnReport")?.click());
   
     // Optional toolbar
     $("btnToggleSidebar")?.addEventListener("click", () => {
       $("sidebar")?.classList.toggle("collapsed");
     });
   
     $("btnClearChat")?.addEventListener("click", () => {
       if (chatEl) chatEl.innerHTML = "";
       toast("Chat cleared");
     });
   
     // Auto refresh (unchanged)
     let autoTimer = null;
     const stateEl = $("autoRefreshState");
     const intervalEl = $("refreshInterval");
   
     function getIntervalMs() {
       const seconds = parseInt(intervalEl?.value || "30", 10);
       return Math.max(10, seconds) * 1000;
     }
   
     async function runCycle() {
       await runHealth();
       await loadMetrics();
     }
   
     $("btnAutoRefresh")?.addEventListener("click", async () => {
       if (autoTimer) {
         clearInterval(autoTimer);
         autoTimer = null;
         if (stateEl) stateEl.textContent = "OFF";
         toast("Auto refresh stopped");
         return;
       }
       if (stateEl) stateEl.textContent = "ON";
       toast("Auto refresh started");
       await runCycle();
       autoTimer = setInterval(runCycle, getIntervalMs());
     });
   
     intervalEl?.addEventListener("change", () => {
       if (!autoTimer) return;
       clearInterval(autoTimer);
       autoTimer = setInterval(runCycle, getIntervalMs());
       toast("Interval updated");
     });
   
     // Bind ChatOps pills above chat
     bindChatOpsButtons();
   
     // Warm welcome
     addMessage("bot", "Hi Ritesh 👋 I’m InfraCopilot Lite (Agentic). Use dashboard buttons or ChatOps pills, or ask in chat.");
     $("chipTime").textContent = new Date().toLocaleString();
   });
   