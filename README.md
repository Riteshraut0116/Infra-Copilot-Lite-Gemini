# 🤖 InfraCopilot Lite — Agentic ChatOps + Hybrid Infra Health (Gemini)

A lightweight **ChatOps + SRE dashboard** powered by **FastAPI** and **Google Gemini**. It can run:

- ✅ **Local system health checks** (REAL: CPU / Memory / Disk / Uptime via `psutil`).
- ☁️ **Azure resource health checks** (Optional: VMs, App Services, Storage Accounts via Azure ARM REST).
- 🌐 **Custom endpoint checks** (Optional: HTTP availability + latency for configured URLs).
- 🧠 **Agentic chat** (`/api/chat`) where Gemini decides which tool(s) to run and then explains results.

---

## ✨ Highlights

- **FastAPI backend** serving both APIs and a static UI. citeturn1search1turn11search1
- **Real local health** (CPU/Mem/Disk/Uptime) gathered using `psutil`. citeturn1search1
- **Azure checks (optional)** via `DefaultAzureCredential` + ARM REST calls. citeturn1search1
- **Custom endpoint monitoring (optional)** via HTTP GET + latency measurement. citeturn1search1
- **Metrics endpoint** provides a 24h series for charts (synthetic trend based on live CPU/mem base). citeturn1search1
- **Daily report generator** uses Gemini to produce Markdown output. citeturn1search1
- **ChatOps quick buttons** in UI (Health/Metrics/Report/Run via Chat/Daily Report). citeturn11search1turn6search1

---

## 📂 File Structure

INFRA-COPILOT-LITE/
├── app/
│   └── public/
│       ├── index.html        # UI layout and ChatOps buttons
│       ├── styles.css        # UI styling
│       └── app.js            # UI logic (buttons, charts, chat)
│
├── main.py                   # FastAPI backend (health/metrics/report/chat)
├── .env                      # Local config (DO NOT COMMIT)
├── requirements.txt          # Python dependencies
└── README.md                 # Documentation

---

## 🎯 What You Get (Output)

InfraCopilot Lite provides a unified hybrid‑health view with:

- **Real Local System Health**
  - CPU %, Memory %, Disk %, Uptime (via psutil)
  - Auto‑warnings based on customizable thresholds
- **Optional Azure Health**
  - VM power states
  - App Service state
  - Storage Account provisioning state
- **Optional Custom Endpoint Health**
  - URL availability (UP/DOWN)
  - HTTP status code
  - Latency (ms)
- **Daily AI‑Generated Reports** (Markdown)
- **Agentic ChatOps**
  - Gemini decides actions and provides explanations
  - Multi‑turn memory for follow‑up questions
- **24‑Hour Metrics Dashboard**
  - CPU & Memory trend visualization
- **Interactive UI**
  - Buttons for Health / Metrics / Report
  - ChatOps Quick Actions

### 📸 UI Dashboard Preview

![InfraCopilot Dashboard](app/public/screenshot.png)

---

## 🛠️ Prerequisites

- Python **3.10+** recommended
- A **Gemini API key**
- Optional: Azure access (for Azure checks)

---

## ⚙️ Configuration (.env)

Create a `.env` file at repo root (never commit it).

### ✅ Required (Gemini)

```env
GEMINI_API_KEY=YOUR_GEMINI_KEY
GEMINI_MODEL=gemini-1.5-flash
```

You can use `GET /api/models` to list models available for your key. citeturn1search1

### ☁️ Optional (Azure health checks)

```env
AZURE_SUBSCRIPTION_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_RESOURCE_GROUP=your-resource-group
```

If these are not set, Azure health checks return `not_configured`. citeturn1search1

### 🌐 Optional (Custom endpoints)

```env
CUSTOM_ENDPOINTS=[
  {"name":"Public Website","url":"https://example.com/"},
  {"name":"Public Health","url":"https://example.com/health"}
]
CUSTOM_ENDPOINT_TIMEOUT_SEC=5
```

### ⚠️ Optional (Local thresholds)

```env
LOCAL_CPU_WARN=85
LOCAL_MEM_WARN=90
LOCAL_DISK_WARN=90
```

Warnings are generated when thresholds are exceeded. citeturn1search1

---

## 🚀 Getting Started

### 1) Clone

```bash
git clone <repo-url>
cd INFRA-COPILOT-LITE
```

### 2) Create & activate venv

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate
```

### 3) Install dependencies

```bash
pip install -r requirements.txt
```

### 4) Run the server

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 5) Open UI

- UI: http://localhost:8000/ citeturn11search1turn1search1
- Health probe: http://localhost:8000/healthz citeturn1search1

---

## 🧪 Running the Three Health Checks (Local + Azure + Endpoints)

InfraCopilot’s *health check* endpoint aggregates three sources:

1. **Local system health** (always available)
2. **Azure health** (optional; requires `.env` + Azure identity)
3. **Custom endpoint health** (optional; requires `CUSTOM_ENDPOINTS`)

You can run them in two ways:

- **Dashboard button**: `Run Health Check` (UI)
- **API call**: `GET /api/healthcheck`
- **Agentic chat**: ask in chat or use ChatOps pill `Health`

### ✅ A) Local System Health (REAL)

#### What it checks

- CPU utilization (`psutil.cpu_percent`)
- Memory utilization (`psutil.virtual_memory().percent`)
- Disk utilization (`psutil.disk_usage`)
- Uptime seconds (`psutil.boot_time` delta)

These are computed in `local_health()` and returned under `data.local`. citeturn1search1

#### Run via UI

1. Start server
2. Open UI: `http://localhost:8000/`
3. Click **✅ Run Health Check**

The dashboard updates:
- KPI totals/healthy/warnings
- Health details panel

The UI wiring for the health button is in `app.js` via `btnHealth → runHealth() → /api/healthcheck`. citeturn6search1turn11search1

#### Run via API

```bash
curl http://localhost:8000/api/healthcheck
```

Look for:

```json
{
  "ok": true,
  "data": {
    "local": {
      "cpu_percent": 12.3,
      "memory_percent": 55.8,
      "disk_percent": 71.2,
      "uptime_seconds": 123456,
      "warnings": []
    }
  }
}
```

#### Verify values are real (not dummy)

- Compare with OS tools (Task Manager / Activity Monitor / `top`, `df -h`).
- Create a brief CPU load and re-run `/api/healthcheck`; CPU% should change.

> Note: values reflect the machine running the FastAPI server (not the browser client). citeturn1search1

---

### ☁️ B) Azure Health (Optional)

#### What it checks

When configured, the backend uses Azure ARM REST to list and evaluate:

- **Virtual Machines**: reads power state via `instanceView`
- **App Services**: checks `properties.state`
- **Storage Accounts**: checks `properties.provisioningState`

These checks run in `azure_health()` and are included under `data.azure`. citeturn1search1

#### Enable Azure checks

1. Set `.env`:

```env
AZURE_SUBSCRIPTION_ID=...
AZURE_RESOURCE_GROUP=...
```

2. Ensure Azure authentication works with `DefaultAzureCredential`.
   - Locally: `az login` is commonly used.
   - In cloud: Managed Identity can be used.

Azure token acquisition is handled by `DefaultAzureCredential` in `_azure_get_token()`. citeturn1search1

#### Run and view output

```bash
curl http://localhost:8000/api/healthcheck
```

Check `data.azure`:

- `configured: true/false`
- `status: ok|warnings|not_configured|auth_failed`
- lists: `vms`, `appServices`, `storageAccounts`

If Azure is not configured, the API returns `configured=false` and a message. citeturn1search1

---

### 🌐 C) Custom Endpoint Health (Optional)

#### What it checks

For each configured endpoint, the backend performs:
- HTTP GET
- timeout handling
- marks **UP** for 2xx/3xx
- records latency in ms

This runs in `custom_endpoints_health()` and is included under `data.custom`. citeturn1search1

#### Enable endpoint checks

Set in `.env`:

```env
CUSTOM_ENDPOINTS=[
  {"name":"Public Website","url":"https://example.com/"}
]
CUSTOM_ENDPOINT_TIMEOUT_SEC=5
```

#### Run and view output

```bash
curl http://localhost:8000/api/healthcheck
```

Check `data.custom.results`:

```json
{
  "name": "Public Website",
  "url": "https://example.com/",
  "status": "UP",
  "http_status": 200,
  "latency_ms": 123,
  "error": null
}
```

Down endpoints appear as `status: DOWN` and include an error string. citeturn1search1

---

## 🧠 Agentic ChatOps (Gemini)

### Chat endpoint

- `POST /api/chat` is designed for agentic behavior where Gemini can:
  - interpret user message
  - decide which tool(s) to run
  - generate a final answer using tool outputs

The UI (chat + ChatOps pills) calls `/api/chat` from `app.js`. citeturn6search1

### Example prompts

- “Run local health check and explain warnings.”
- “Check Azure VM states and summarize.”
- “Which custom endpoints are down and what’s the latency?”
- “Generate a daily report with next actions.”

### ChatOps quick buttons

The UI includes quick buttons above chat:
- Health
- Metrics
- Report
- Run via Chat
- Daily Report (Chat)

These are rendered in `index.html` and wired in `app.js`. citeturn11search1turn6search1

---

## 📈 Metrics (24h) Notes

- `GET /api/metrics` returns a 24h series suitable for charts.
- It uses current CPU/memory as a base and generates a synthetic series for the last 24h.

This behavior is implemented in `api_metrics()` and is intended for dashboard demos. citeturn1search1

---

## 🧾 Daily Report

### Generate via UI

- Click **🧾 Generate Daily Report**

### Generate via API

```bash
curl -X POST http://localhost:8000/api/report \
  -H "Content-Type: application/json" \
  -d '{}'
```

The backend will auto-run healthcheck/metrics if not provided and then ask Gemini to generate markdown. citeturn1search1

---

## 🔍 Troubleshooting

### Chat fails with “GEMINI_API_KEY missing”

- Ensure `.env` contains `GEMINI_API_KEY` and restart the server. citeturn1search1

### Azure shows `auth_failed`

- Ensure Azure auth is available (e.g., local `az login`, managed identity in cloud).
- Confirm `AZURE_SUBSCRIPTION_ID` and `AZURE_RESOURCE_GROUP` are set. citeturn1search1

### Custom endpoints not running

- Confirm `CUSTOM_ENDPOINTS` is valid JSON list.
- Confirm endpoint is reachable from the server host. citeturn1search1

---

## 🔐 Security Notes (Public Repo)

- Never commit `.env`.
- Review CORS settings before production.
- Azure checks use your identity; apply least privilege.

---

## 👤 Author

**Ritesh Raut**  
*Programmer Analyst, Cognizant*

🚀 AI‑Powered ChatOps for Real‑Time Local, Cloud & Endpoint Health Monitoring 🚀

---

### 🌐 Connect with me:
<p align="left">
<a href="https://github.com/Riteshraut0116" target="blank"><img align="center" src="https://raw.githubusercontent.com/rahuldkjain/github-profile-readme-generator/master/src/images/icons/Social/github.svg" alt="Riteshraut0116" height="30" width="40" /></a>
<a href="https://linkedin.com/in/ritesh-raut-9aa4b71ba" target="blank"><img align="center" src="https://raw.githubusercontent.com/rahuldkjain/github-profile-readme-generator/master/src/images/icons/Social/linked-in-alt.svg" alt="ritesh-raut-9aa4b71ba" height="30" width="40" /></a>
<a href="https://www.instagram.com/riteshraut1601/" target="blank"><img align="center" src="https://raw.githubusercontent.com/rahuldkjain/github-profile-readme-generator/master/src/images/icons/Social/instagram.svg" alt="riteshraut1601" height="30" width="40" /></a>
<a href="https://www.facebook.com/ritesh.raut.649321/" target="blank"><img align="center" src="https://raw.githubusercontent.com/rahuldkjain/github-profile-readme-generator/master/src/images/icons/Social/facebook.svg" alt="ritesh.raut.649321" height="30" width="40" /></a>
</p>

---

