import os
import json
import time
import random
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
import psutil
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from azure.identity import DefaultAzureCredential

# -------------------------
# Load env + logging
# -------------------------
load_dotenv()
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("infracopilot-lite")

# -------------------------
# Config: Gemini
# -------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "").strip()
GEMINI_BASE = os.getenv("GEMINI_BASE", "https://generativelanguage.googleapis.com/v1beta").strip()

# -------------------------
# Config: Azure
# -------------------------
AZURE_SUBSCRIPTION_ID = os.getenv("AZURE_SUBSCRIPTION_ID", "").strip()
AZURE_RESOURCE_GROUP = os.getenv("AZURE_RESOURCE_GROUP", "").strip()

# -------------------------
# Config: Custom endpoints checks
# -------------------------
CUSTOM_ENDPOINTS_RAW = os.getenv("CUSTOM_ENDPOINTS", "[]").strip()
CUSTOM_ENDPOINT_TIMEOUT_SEC = float(os.getenv("CUSTOM_ENDPOINT_TIMEOUT_SEC", "5"))

# -------------------------
# Local thresholds
# -------------------------
LOCAL_CPU_WARN = float(os.getenv("LOCAL_CPU_WARN", "85"))
LOCAL_MEM_WARN = float(os.getenv("LOCAL_MEM_WARN", "90"))
LOCAL_DISK_WARN = float(os.getenv("LOCAL_DISK_WARN", "90"))

# -------------------------
# CORS
# -------------------------
ALLOWED_ORIGINS_RAW = os.getenv("ALLOWED_ORIGINS", "*").strip()
if ALLOWED_ORIGINS_RAW == "*":
    ALLOWED_ORIGINS = ["*"]
else:
    ALLOWED_ORIGINS = [o.strip() for o in ALLOWED_ORIGINS_RAW.split(",") if o.strip()]

# -------------------------
# Paths
# -------------------------
BASE_DIR = os.path.dirname(__file__)
PUBLIC_DIR = os.path.join(BASE_DIR, "public")

# -------------------------
# FastAPI
# -------------------------
app = FastAPI(title="InfraCopilot Lite (Hybrid Health)", version="2.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if os.path.isdir(PUBLIC_DIR):
    app.mount("/static", StaticFiles(directory=PUBLIC_DIR), name="static")
else:
    logger.warning("public/ directory not found. UI static serving is disabled.")

_AZ_CREDENTIAL: Optional[DefaultAzureCredential] = None


# -------------------------
# Session memory (in-memory)
# -------------------------
SESSION_TTL_MIN = int(os.getenv("SESSION_TTL_MIN", "60"))
_SESSIONS: Dict[str, Dict[str, Any]] = {}


def _purge_sessions():
    now = datetime.now(timezone.utc)
    dead = []
    for sid, blob in _SESSIONS.items():
        ts = blob.get("_ts")
        if not ts:
            dead.append(sid)
            continue
        if now - ts > timedelta(minutes=SESSION_TTL_MIN):
            dead.append(sid)
    for sid in dead:
        _SESSIONS.pop(sid, None)


def _get_session(session_id: str) -> Dict[str, Any]:
    _purge_sessions()
    if session_id not in _SESSIONS:
        _SESSIONS[session_id] = {"_ts": datetime.now(timezone.utc), "history": []}
    _SESSIONS[session_id]["_ts"] = datetime.now(timezone.utc)
    return _SESSIONS[session_id]


# -------------------------
# Models
# -------------------------
class ReportRequest(BaseModel):
    health: Optional[Dict[str, Any]] = None
    metrics: Optional[Dict[str, Any]] = None


class SupervisorRequest(BaseModel):
    input: str = ""


class ChatRequest(BaseModel):
    input: str = ""
    # "auto" lets Gemini decide; or force tool routing from ChatOps pills
    mode: str = "auto"  # auto | health | metrics | report | daily_report
    sessionId: Optional[str] = None


# -------------------------
# Helpers
# -------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_json_loads(s: str, default):
    try:
        return json.loads(s)
    except Exception:
        return default


def _normalize_gemini_model(model: str) -> str:
    model = (model or "").strip()
    if not model:
        return ""
    return model.replace("models/", "", 1) if model.startswith("models/") else model


# -------------------------
# UI routes
# -------------------------
@app.get("/")
def ui_index():
    if not os.path.isdir(PUBLIC_DIR):
        return JSONResponse({"ok": False, "message": "UI not available. public/ folder missing."}, status_code=404)
    return FileResponse(os.path.join(PUBLIC_DIR, "index.html"))


@app.get("/healthz")
def healthz():
    return {"ok": True, "timestamp": _now_iso()}


# -------------------------
# Local health (REAL via psutil)
# -------------------------
def local_health() -> Dict[str, Any]:
    warnings: List[str] = []

    cpu = psutil.cpu_percent(interval=0.2)
    mem = psutil.virtual_memory().percent

    root_path = (os.getenv("SYSTEMDRIVE", "C:") + "\\") if os.name == "nt" else "/"
    disk = psutil.disk_usage(root_path).percent

    boot = datetime.fromtimestamp(psutil.boot_time(), tz=timezone.utc)
    uptime_sec = int((datetime.now(timezone.utc) - boot).total_seconds())

    if cpu >= LOCAL_CPU_WARN:
        warnings.append(f"LOCAL: High CPU {cpu:.1f}% (>= {LOCAL_CPU_WARN}%)")
    if mem >= LOCAL_MEM_WARN:
        warnings.append(f"LOCAL: High Memory {mem:.1f}% (>= {LOCAL_MEM_WARN}%)")
    if disk >= LOCAL_DISK_WARN:
        warnings.append(f"LOCAL: High Disk {disk:.1f}% (>= {LOCAL_DISK_WARN}%)")

    return {
        "cpu_percent": round(cpu, 2),
        "memory_percent": round(mem, 2),
        "disk_percent": round(disk, 2),
        "uptime_seconds": uptime_sec,
        "warnings": warnings,
    }


# -------------------------
# Azure health (optional)
# -------------------------
def _azure_get_credential() -> DefaultAzureCredential:
    global _AZ_CREDENTIAL
    if _AZ_CREDENTIAL is None:
        _AZ_CREDENTIAL = DefaultAzureCredential(exclude_interactive_browser_credential=False)
    return _AZ_CREDENTIAL


async def _azure_get_token() -> str:
    cred = _azure_get_credential()
    token = cred.get_token("https://management.azure.com/.default")
    return token.token


async def azure_health() -> Dict[str, Any]:
    if not AZURE_SUBSCRIPTION_ID or not AZURE_RESOURCE_GROUP:
        return {
            "configured": False,
            "status": "not_configured",
            "message": "Set AZURE_SUBSCRIPTION_ID and AZURE_RESOURCE_GROUP to enable Azure checks.",
            "vms": [],
            "appServices": [],
            "storageAccounts": [],
            "warnings": [],
        }

    warnings: List[str] = []
    try:
        token = await _azure_get_token()
    except Exception as e:
        return {
            "configured": True,
            "status": "auth_failed",
            "message": f"Azure auth failed: {e}",
            "vms": [],
            "appServices": [],
            "storageAccounts": [],
            "warnings": [f"AZURE: auth_failed - {e}"],
        }

    headers = {"Authorization": f"Bearer {token}"}
    base = "https://management.azure.com"
    sub = AZURE_SUBSCRIPTION_ID
    rg = AZURE_RESOURCE_GROUP

    vm_api = os.getenv("AZURE_VM_API_VERSION", "2024-03-01")
    web_api = os.getenv("AZURE_WEB_API_VERSION", "2024-04-01")
    st_api = os.getenv("AZURE_STORAGE_API_VERSION", "2023-01-01")

    vms: List[Dict[str, Any]] = []
    apps: List[Dict[str, Any]] = []
    storages: List[Dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=30) as client:
        # VMs
        try:
            url = f"{base}/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Compute/virtualMachines?api-version={vm_api}"
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            for item in r.json().get("value", []):
                name = item.get("name")
                vm_id = item.get("id")
                state = "unknown"
                iv_url = f"{base}{vm_id}/instanceView?api-version={vm_api}"
                iv = await client.get(iv_url, headers=headers)
                if iv.status_code == 200:
                    statuses = iv.json().get("statuses") or []
                    for s in statuses:
                        code = s.get("code", "")
                        if code.startswith("PowerState/"):
                            state = code.split("/", 1)[1]
                            break
                vms.append({"name": name, "state": state})
                if state not in ("running", "stopped", "deallocated"):
                    warnings.append(f"AZURE: VM {name} state={state}")
        except Exception as e:
            warnings.append(f"AZURE: VM list failed - {e}")

        # App Services
        try:
            url = f"{base}/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Web/sites?api-version={web_api}"
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            for item in r.json().get("value", []):
                name = item.get("name")
                state = (item.get("properties") or {}).get("state", "unknown")
                apps.append({"name": name, "state": state})
                if state.lower() != "running":
                    warnings.append(f"AZURE: AppService {name} state={state}")
        except Exception as e:
            warnings.append(f"AZURE: AppService list failed - {e}")

        # Storage Accounts
        try:
            url = f"{base}/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Storage/storageAccounts?api-version={st_api}"
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            for item in r.json().get("value", []):
                name = item.get("name")
                prov = (item.get("properties") or {}).get("provisioningState", "unknown")
                storages.append({"name": name, "provisioningState": prov})
                if prov.lower() != "succeeded":
                    warnings.append(f"AZURE: Storage {name} provisioningState={prov}")
        except Exception as e:
            warnings.append(f"AZURE: Storage list failed - {e}")

    status = "ok" if not warnings else "warnings"
    return {
        "configured": True,
        "status": status,
        "message": "Azure checks executed.",
        "vms": vms,
        "appServices": apps,
        "storageAccounts": storages,
        "warnings": warnings,
    }


# -------------------------
# Custom endpoints checks
# -------------------------
async def custom_endpoints_health() -> Dict[str, Any]:
    endpoints = _safe_json_loads(CUSTOM_ENDPOINTS_RAW, [])
    results: List[Dict[str, Any]] = []
    warnings: List[str] = []

    if not isinstance(endpoints, list):
        return {"configured": False, "results": [], "warnings": ["CUSTOM: CUSTOM_ENDPOINTS is not a JSON list"]}

    async with httpx.AsyncClient(timeout=CUSTOM_ENDPOINT_TIMEOUT_SEC, follow_redirects=True) as client:
        for ep in endpoints:
            name = ep.get("name") if isinstance(ep, dict) else None
            url = ep.get("url") if isinstance(ep, dict) else None
            if not name or not url:
                continue

            start = time.perf_counter()
            status = "DOWN"
            http_status = None
            err = None

            try:
                r = await client.get(url)
                http_status = r.status_code
                if 200 <= r.status_code < 400:
                    status = "UP"
                else:
                    err = f"Bad status {r.status_code}"
            except Exception as e:
                err = str(e)

            latency_ms = int((time.perf_counter() - start) * 1000)
            results.append(
                {
                    "name": name,
                    "url": url,
                    "status": status,
                    "http_status": http_status,
                    "latency_ms": latency_ms,
                    "error": err,
                }
            )
            if status != "UP":
                warnings.append(f"CUSTOM: {name} DOWN ({err})")

    return {"configured": True, "results": results, "warnings": warnings}


def aggregate_summary(local_warnings, azure_warnings, custom_warnings) -> Dict[str, Any]:
    warnings: List[str] = []
    warnings.extend(local_warnings or [])
    warnings.extend(azure_warnings or [])
    warnings.extend(custom_warnings or [])
    total_checks = 3 + 1 + 1
    return {
        "total": total_checks,
        "warnings": len(warnings),
        "healthy": max(0, total_checks - len(warnings)),
        "warnings_list": warnings,
    }


# =====================
# API: healthcheck (REAL local health snapshot)
# =====================
@app.get("/api/healthcheck")
async def api_healthcheck():
    local = local_health()
    azure = await azure_health()
    custom = await custom_endpoints_health()

    summary = aggregate_summary(
        local_warnings=local.get("warnings"),
        azure_warnings=azure.get("warnings"),
        custom_warnings=custom.get("warnings"),
    )

    return {
        "ok": True,
        "data": {
            "timestamp": _now_iso(),
            "summary": {
                "total": summary["total"],
                "healthy": summary["healthy"],
                "warnings": summary["warnings"],
            },
            "warnings": summary["warnings_list"],
            "local": local,
            "azure": azure,
            "custom": custom,
        },
    }


# =====================
# API: metrics (24h trend is synthetic, base uses live cpu/mem)
# =====================
@app.get("/api/metrics")
def api_metrics():
    base_cpu = psutil.cpu_percent(interval=0.1)
    base_mem = psutil.virtual_memory().percent

    def series(points=24, base=50, jitter=10):
        out = []
        now = datetime.now(timezone.utc)
        for i in range(points):
            t = now - timedelta(hours=(points - 1 - i))
            v = max(0, min(100, base + (random.random() - 0.5) * jitter))
            out.append({"t": t.isoformat(), "v": round(v, 2)})
        return out

    return {
        "ok": True,
        "data": {
            "timestamp": _now_iso(),
            "range": "24h",
            "syntheticTrend": True,
            "cpu": series(base=base_cpu, jitter=18),
            "memory": series(base=base_mem, jitter=14),
            "disk": series(base=55, jitter=10),
            "netio": series(base=35, jitter=22),
        },
    }


# =====================
# API: model listing
# =====================
@app.get("/api/models")
async def api_models():
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY missing. Set it in .env")

    url = f"{GEMINI_BASE}/models"
    headers = {"x-goog-api-key": GEMINI_API_KEY}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url, headers=headers)
        data = r.json()
        if r.status_code >= 400:
            msg = (data.get("error") or {}).get("message") or "Failed to list models"
            raise HTTPException(status_code=500, detail=msg)

    models = []
    for m in data.get("models", []):
        name = m.get("name")
        methods = m.get("supportedGenerationMethods") or []
        models.append(
            {
                "name": name,
                "supports_generateContent": "generateContent" in methods,
                "supportedGenerationMethods": methods,
            }
        )
    return {"ok": True, "models": models}


# -------------------------
# Gemini call
# -------------------------
async def gemini_generate(system_instruction: str, user_text: str, history=None, temperature=0.4, max_tokens=900) -> str:
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY missing. Set it in .env")
    if not GEMINI_MODEL:
        raise HTTPException(status_code=500, detail="GEMINI_MODEL missing. Set it in .env (use /api/models).")

    model = _normalize_gemini_model(GEMINI_MODEL)
    url = f"{GEMINI_BASE}/models/{model}:generateContent"

    history = history or []
    payload = {
        "contents": [*history, {"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }
    if system_instruction:
        payload["systemInstruction"] = {"role": "system", "parts": [{"text": system_instruction}]}

    headers = {"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY}

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, headers=headers, json=payload)
        data = resp.json()

    if resp.status_code >= 400:
        msg = (data.get("error") or {}).get("message") or "Gemini API error"
        raise HTTPException(status_code=500, detail=msg)

    parts = (((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
    text = "".join([p.get("text", "") for p in parts if isinstance(p, dict)])
    return text.strip()


# =====================
# API: report (Gemini summarization)
# =====================
@app.post("/api/report")
async def api_report(req: ReportRequest):
    health = req.health
    metrics = req.metrics

    if not health:
        health_resp = await api_healthcheck()
        health = health_resp["data"]

    if not metrics:
        metrics = api_metrics()["data"]

    system_instruction = (
        "You are InfraCopilot Lite, a virtual SRE assistant. "
        "Summarize infra health + metrics in plain English. "
        "Highlight risks and suggest NON-DESTRUCTIVE next actions only. "
        "Format output as Markdown with headings, bullet points, and a short 'Next Actions' section."
    )

    user_text = f"""Generate today's hybrid infra health report.
LOCAL HEALTH:
{json.dumps(health.get('local', {}), indent=2)}

AZURE HEALTH:
{json.dumps(health.get('azure', {}), indent=2)}

CUSTOM ENDPOINTS:
{json.dumps(health.get('custom', {}), indent=2)}

METRICS:
{json.dumps(metrics, indent=2)}

Be concise, actionable, and include a short risk score (Low/Med/High).
"""

    md = await gemini_generate(system_instruction, user_text)
    return {"ok": True, "reportMarkdown": md, "usedModel": GEMINI_MODEL}


# =====================
# Legacy supervisor endpoint (keep for compatibility)
# =====================
@app.post("/api/supervisor")
async def api_supervisor(payload: SupervisorRequest):
    # Keep minimal: treat as pure chat now
    system_instruction = (
        "You are InfraCopilot Lite, a ChatOps SRE assistant for Azure-like environments. "
        "Answer clearly. If a user asks for destructive actions, suggest safe read-only alternatives."
    )
    text = await gemini_generate(system_instruction, payload.input or "")
    return {"ok": True, "intent": "chat", "text": text, "usedModel": GEMINI_MODEL}


# =====================
# Agentic Chat: /api/chat
# Gemini decides tool usage, backend executes, Gemini answers using tool output.
# =====================
def _extract_json_object(s: str) -> Optional[dict]:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        pass

    # try to extract first {...}
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        chunk = s[start : end + 1]
        try:
            return json.loads(chunk)
        except Exception:
            return None
    return None


async def _plan_action_with_gemini(user_text: str, session: Dict[str, Any], mode: str) -> Dict[str, Any]:
    """
    Returns: {"action": "...", "why": "...", "need_tools": bool}
    """
    # Mode override (from ChatOps pills)
    mode = (mode or "auto").lower().strip()
    if mode in ("health", "metrics", "report", "daily_report"):
        return {"action": mode, "why": f"forced_by_mode:{mode}", "need_tools": True}

    # Build a small context summary for Gemini
    ctx = {
        "has_last_health": bool(session.get("last_health")),
        "has_last_metrics": bool(session.get("last_metrics")),
        "has_last_report": bool(session.get("last_report")),
    }

    system = (
        "You are an SRE ChatOps router. Decide the best action for the user.\n"
        "Return ONLY a JSON object with keys:\n"
        "  action: one of [chat, health, metrics, report, daily_report]\n"
        "  why: short reason\n"
        "  need_tools: true/false\n"
        "Routing rules:\n"
        "- If user asks to run/check health/status/uptime/warnings/local system => action=health\n"
        "- If user asks charts/trends/last 24h/metrics => action=metrics\n"
        "- If user asks report/summary => action=report\n"
        "- If user asks daily report => action=daily_report\n"
        "- If user asks follow-up like 'give details' and ctx has last_health => action=health\n"
        "- Otherwise action=chat\n"
        "Output must be valid JSON only."
    )

    user = f"""User message: {user_text}
Context flags: {json.dumps(ctx)}
"""

    plan_raw = await gemini_generate(system, user, temperature=0.0, max_tokens=220)
    plan = _extract_json_object(plan_raw) or {}

    action = (plan.get("action") or "chat").strip().lower()
    if action not in ("chat", "health", "metrics", "report", "daily_report"):
        action = "chat"

    need_tools = bool(plan.get("need_tools")) if "need_tools" in plan else (action != "chat")
    why = (plan.get("why") or "n/a").strip()

    return {"action": action, "why": why, "need_tools": need_tools}


async def _answer_with_tools(user_text: str, action: str, session: Dict[str, Any], tool_payload: Dict[str, Any]) -> str:
    """
    Gemini final response using tool outputs.
    """
    system = (
        "You are InfraCopilot Lite, an SRE assistant.\n"
        "Use TOOL_OUTPUTS to answer the user's question.\n"
        "Be concise but helpful. Include:\n"
        "- what you observed\n"
        "- key values (cpu/mem/disk/uptime for health)\n"
        "- warnings if any\n"
        "- non-destructive next steps\n"
        "Format with short headings and bullets.\n"
        "Do NOT ask unnecessary clarification if TOOL_OUTPUTS already contains the needed info."
    )

    user = f"""USER_QUESTION:
{user_text}

ACTION:
{action}

TOOL_OUTPUTS (JSON):
{json.dumps(tool_payload, indent=2)[:12000]}
"""

    return await gemini_generate(system, user, temperature=0.35, max_tokens=900)


@app.post("/api/chat")
async def api_chat(req: ChatRequest):
    session_id = req.sessionId or str(uuid.uuid4())
    session = _get_session(session_id)

    user_text = (req.input or "").strip()
    if not user_text:
        return {"ok": True, "sessionId": session_id, "toolUsed": "none", "text": "Say something and I’ll help."}

    # Keep simple conversation history for better follow-ups
    history = session.get("history") or []

# ---- Append current user message to session history (Gemini format) ----
    history.append({"role": "user", "parts": [{"text": user_text}]})

    # Keep history bounded (avoid huge payloads)
    max_turns = int(os.getenv("CHAT_HISTORY_TURNS", "10"))
    if len(history) > max_turns * 2:  # user+bot pairs
        history = history[-max_turns * 2 :]

    session["history"] = history

    # ---- Plan: let Gemini (or forced mode) decide action/tool usage ----
    plan = await _plan_action_with_gemini(user_text, session, req.mode)
    action = plan.get("action", "chat")
    why = plan.get("why", "")
    need_tools = bool(plan.get("need_tools", action != "chat"))

    tool_payload: Dict[str, Any] = {"action": action, "why": why}
    tool_used = action

    # ---- Execute tools if needed ----
    health_obj = None
    metrics_obj = None
    report_md = None

    try:
        if need_tools and action in ("health", "daily_report", "report"):
            hc = await api_healthcheck()
            health_obj = hc["data"]
            session["last_health"] = health_obj
            tool_payload["health"] = health_obj

        if need_tools and action in ("metrics", "daily_report", "report"):
            mc = api_metrics()
            metrics_obj = mc["data"]
            session["last_metrics"] = metrics_obj
            tool_payload["metrics"] = metrics_obj

        if need_tools and action in ("report", "daily_report"):
            # Use tool outputs if already fetched, else pull from session
            h = health_obj or session.get("last_health")
            m = metrics_obj or session.get("last_metrics")

            rep = await api_report(ReportRequest(health=h, metrics=m))
            report_md = rep.get("reportMarkdown", "")
            session["last_report"] = report_md
            tool_payload["reportMarkdown"] = report_md

    except HTTPException:
        # bubble up FastAPI errors (e.g., missing GEMINI key/model)
        raise
    except Exception as e:
        logger.exception("Tool execution failed")
        raise HTTPException(status_code=500, detail=f"Tool execution failed: {e}")

    # ---- Final answer: Gemini composes response using tool outputs (agentic) ----
    try:
        if action == "chat":
            system = (
                "You are InfraCopilot Lite, a helpful SRE assistant.\n"
                "Answer clearly and practically.\n"
                "If the user asks for destructive actions, suggest safe read-only alternatives.\n"
                "Use brief headings and bullet points when helpful."
            )
            final_text = await gemini_generate(system, user_text, history=history, temperature=0.45, max_tokens=900)
        else:
            # If user asks follow-up like “details”, use last tool outputs even if tool didn't run
            if action == "health" and not health_obj:
                health_obj = session.get("last_health")
                if health_obj:
                    tool_payload["health"] = health_obj

            if action == "metrics" and not metrics_obj:
                metrics_obj = session.get("last_metrics")
                if metrics_obj:
                    tool_payload["metrics"] = metrics_obj

            if action in ("report", "daily_report") and not report_md:
                report_md = session.get("last_report")
                if report_md:
                    tool_payload["reportMarkdown"] = report_md

            final_text = await _answer_with_tools(user_text, action, session, tool_payload)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Gemini answer generation failed")
        raise HTTPException(status_code=500, detail=f"Gemini answer generation failed: {e}")

    # ---- Add assistant message into history ----
    history.append({"role": "model", "parts": [{"text": final_text}]})
    if len(history) > max_turns * 2:
        history = history[-max_turns * 2 :]
    session["history"] = history

    # ---- Build response expected by updated app.js ----
    resp: Dict[str, Any] = {
        "ok": True,
        "sessionId": session_id,
        "toolUsed": tool_used,
        "text": final_text,
        "usedModel": GEMINI_MODEL,
    }

    # Attach tool results so UI can update dashboard (KPIs/charts/report)
    if health_obj:
        resp["health"] = health_obj
    if metrics_obj:
        resp["metrics"] = metrics_obj
    if report_md is not None:
        resp["reportMarkdown"] = report_md

    return resp