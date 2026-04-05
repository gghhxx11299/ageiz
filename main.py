import json
import os
import bcrypt
import asyncio
from datetime import datetime
from fastapi import FastAPI, Request, Form, HTTPException, Depends, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from dotenv import load_dotenv
import random
from database import (
    init_db, get_user_by_email, create_user, update_user_hotel,
    save_hotel_profile, get_hotel_profile, get_cache,
    get_recommendation_history, create_pipeline_task, get_pipeline_task,
    get_pending_pipeline_task, update_pipeline_task, get_latest_pipeline_task,
    save_otp_code, unlink_telegram_id, update_user_language
)
from scraper import scrape_website_async
from ai_client import call_ai_for_json
from pipeline import run_pipeline
from chat_agent import get_chat_response
from database import get_chat_history
from translator import translate_text
from translations import get_translation

load_dotenv()

app = FastAPI(title="Ageiz")

templates = Jinja2Templates(directory="templates")

@app.on_event("startup")
async def startup_event():
    try:
        init_db()
        print("[startup] Database initialized.")
    except Exception as e:
        print(f"[startup] DB init failed (non-fatal): {e}")

    # Fire-and-forget Telegram bot setup — never blocks
    try:
        from telegram_bot import setup_bot
        asyncio.create_task(setup_bot())
    except Exception as e:
        print(f"[startup] Telegram bot disabled (non-fatal): {e}")

SECRET_KEY = os.getenv("SECRET_KEY", "ageiz-local-dev-secret-key-change-in-production")
serializer = URLSafeTimedSerializer(SECRET_KEY)

# --- Rate Limiting Middleware ---
from collections import defaultdict
import time

_rate_limit_store = defaultdict(list)
RATE_LIMIT_MAX = 10  # requests per window
RATE_LIMIT_WINDOW = 60  # seconds

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.method in ("POST", "PUT", "DELETE") and request.url.path.startswith("/api/"):
        client_ip = request.client.host
        now = time.time()
        _rate_limit_store[client_ip] = [t for t in _rate_limit_store[client_ip] if now - t < RATE_LIMIT_WINDOW]
        if len(_rate_limit_store[client_ip]) >= RATE_LIMIT_MAX:
            return JSONResponse(
                status_code=429,
                content={"error": "Rate limit exceeded. Try again later."}
            )
        _rate_limit_store[client_ip].append(now)
    response = await call_next(request)
    return response

def get_session(request: Request) -> dict | None:
    token = request.cookies.get("session")
    if not token:
        return None
    try:
        data = serializer.loads(token, max_age=86400)
        return data
    except (BadSignature, SignatureExpired):
        return None

def require_session(request: Request) -> dict:
    session = get_session(request)
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return session

def get_current_user(session: dict = Depends(require_session)) -> dict:
    user = get_user_by_email(session.get("email"))
    if not user:
        raise HTTPException(status_code=401, detail="User session invalid")
    return user

# Telegram webhook endpoint
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    """Receive Telegram updates via webhook."""
    try:
        from telegram_bot import bot_app
        if not bot_app:
            return JSONResponse({"error": "Bot not initialized"}, status_code=503)

        data = await request.json()
        update = Update.de_json(data, bot_app.bot)
        await bot_app.process_update(update)
        return JSONResponse({"status": "ok"})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat(), "service": "Ageiz"}

@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    session = get_session(request)
    if session:
        return RedirectResponse(url="/dashboard")
    return templates.TemplateResponse(request, "home.html", {})

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {})

@app.post("/auth/register")
async def register(request: Request, email: str = Form(...), password: str = Form(...), role: str = Form("manager")):
    existing = get_user_by_email(email)
    if existing:
        return templates.TemplateResponse(request, "login.html", {
            "error": "Email already registered",
            "tab": "register"
        })

    valid_roles = ["manager", "staff"]
    if role not in valid_roles:
        role = "manager"

    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    user_id = create_user(email, password_hash, role)

    token = serializer.dumps({"user_id": user_id, "email": email, "hotel_id": None, "role": role, "language": "english"})
    if role == "staff":
        response = RedirectResponse(url="/staff", status_code=302)
    else:
        response = RedirectResponse(url="/onboard", status_code=302)
    response.set_cookie("session", token, httponly=True, max_age=86400, samesite="lax")
    return response

@app.post("/auth/login")
async def login(request: Request, email: str = Form(...), password: str = Form(...), role: str = Form("manager")):
    user = get_user_by_email(email)
    if not user:
        return templates.TemplateResponse(request, "login.html", {
            "error": "Invalid email or password",
            "tab": "login"
        })

    if not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
        return templates.TemplateResponse(request, "login.html", {
            "error": "Invalid email or password",
            "tab": "login"
        })

    user_role = user.get("role", "manager")
    user_language = user.get("language", "english")
    token = serializer.dumps({
        "user_id": user["id"],
        "email": user["email"],
        "hotel_id": user["hotel_id"],
        "role": user_role,
        "language": user_language
    })

    # Redirect based on role
    if user_role == "staff":
        redirect_url = "/staff"
    else:
        redirect_url = "/dashboard" if user["hotel_id"] else "/onboard"

    response = RedirectResponse(url=redirect_url, status_code=302)
    response.set_cookie("session", token, httponly=True, max_age=86400, samesite="lax")
    return response

@app.post("/auth/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("session", path="/", httponly=True, samesite="lax")
    return response

@app.get("/auth/logout")
def logout_get():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("session", path="/", httponly=True, samesite="lax")
    return response

@app.get("/onboard", response_class=HTMLResponse)
def onboard_page(request: Request, session: dict = Depends(require_session)):
    user_language = session.get("language", "english")
    translations = {
        "onboarding_subtitle": get_translation("onboarding_subtitle", user_language),
        "back_to_home": get_translation("back_to_home", user_language),
        "neural_property_scan": get_translation("neural_property_scan", user_language),
        "scan_desc": get_translation("scan_desc", user_language),
        "website_url_placeholder": get_translation("website_url_placeholder", user_language),
        "initialize_scan": get_translation("initialize_scan", user_language),
        "scanning_text": get_translation("scanning_text", user_language),
        "calibration_audit": get_translation("calibration_audit", user_language),
        "calibration_desc": get_translation("calibration_desc", user_language),
        "official_property_identity": get_translation("official_property_identity", user_language),
        "validated_url": get_translation("validated_url", user_language),
        "operational_locations": get_translation("operational_locations", user_language),
        "locations_placeholder": get_translation("locations_placeholder", user_language),
        "inventory_classes": get_translation("inventory_classes", user_language),
        "room_types_placeholder": get_translation("room_types_placeholder", user_language),
        "market_tier": get_translation("market_tier", user_language),
        "select_tier": get_translation("select_tier", user_language),
        "tier_value": get_translation("tier_value", user_language),
        "tier_mid_market": get_translation("tier_mid_market", user_language),
        "tier_premium": get_translation("tier_premium", user_language),
        "tier_luxury": get_translation("tier_luxury", user_language),
        "core_amenities": get_translation("core_amenities", user_language),
        "amenities_placeholder": get_translation("amenities_placeholder", user_language),
        "brand_value_proposition": get_translation("brand_value_proposition", user_language),
        "brand_positioning_placeholder": get_translation("brand_positioning_placeholder", user_language),
        "yield_objectives": get_translation("yield_objectives", user_language),
        "business_objectives_placeholder": get_translation("business_objectives_placeholder", user_language),
        "establish_dashboard": get_translation("establish_dashboard", user_language),
        "scan_successful": get_translation("scan_successful", user_language),
        "scan_failed": get_translation("scan_failed", user_language),
    }
    return templates.TemplateResponse(request, "onboard.html", {
        "session": session,
        "user_language": user_language,
        "translations": translations
    })

@app.post("/onboard/scrape")
async def scrape_hotel(request: Request, url: str = Form(...), session: dict = Depends(require_session)):
    scrape_result = await scrape_website_async(url)
    
    if not scrape_result["success"]:
        return JSONResponse({
            "success": False,
            "error": "Could not scrape website. Please fill in details manually.",
            "scraped_text": ""
        })
    
    scraped_text = scrape_result["text"]
    
    prompt = f"""You are onboarding a hotel onto Ageiz, an Ethiopian resort pricing intelligence platform.
Here is raw text scraped from their website and search intel.
Extract all available information and return ONLY this JSON with no other text.
IMPORTANT: For 'price_range', you MUST select exactly one of these: "budget", "mid-range", "premium", "luxury".

{{
  "hotel_name": "full name of the hotel or resort",
  "website_url": "{url}",
  "locations": ["list", "of", "property", "locations"],
  "room_types": ["list", "of", "room", "classes", "e.g. Standard, Deluxe"],
  "amenities": ["comprehensive", "list", "of", "all", "facilities", "found"],
  "brand_positioning": "one sentence describing the hotel brand",
  "target_guest_segments": ["diaspora", "foreign tourists", "local"],
  "price_range": "budget or mid-range or premium or luxury",
  "unique_selling_points": ["list", "of", "USPs"],
  "business_objectives": "one sentence about goals"
}}

Scraped text:
{scraped_text[:5000]}"""
    
    try:
        profile = call_ai_for_json(prompt, use_heavy_model=True)
        # Ensure website_url is set even if AI missed it
        if not profile.get("website_url"):
            profile["website_url"] = url
            
        return JSONResponse({
            "success": True,
            "profile": profile,
            "scraped_text": scraped_text[:500]
        })
    except Exception as e:
        return JSONResponse({
            "success": False,
            "error": f"Could not extract hotel profile: {str(e)}",
            "scraped_text": scraped_text[:500]
        })

@app.post("/onboard/save")
async def save_onboarding(
    request: Request,
    hotel_name: str = Form(...),
    website_url: str = Form(""),
    locations: str = Form(...),
    room_types: str = Form(""),
    amenities: str = Form(""),
    brand_positioning: str = Form(""),
    target_guest_segments: str = Form(""),
    price_range: str = Form(""),
    unique_selling_points: str = Form(""),
    business_objectives: str = Form(""),
    raw_scraped_text: str = Form(""),
    session: dict = Depends(require_session)
):
    hotel_id = save_hotel_profile(
        user_id=session["user_id"],
        hotel_name=hotel_name,
        website_url=website_url,
        locations=locations,
        room_types=room_types,
        amenities=amenities,
        brand_positioning=brand_positioning,
        target_guest_segments=target_guest_segments,
        price_range=price_range,
        unique_selling_points=unique_selling_points,
        business_objectives=business_objectives,
        raw_scraped_text=raw_scraped_text
    )
    
    update_user_hotel(session["user_id"], hotel_id)
    
    token = serializer.dumps({
        "user_id": session["user_id"],
        "email": session["email"],
        "hotel_id": hotel_id
    })
    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie("session", token, httponly=True, max_age=86400, samesite="lax")
    return response

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, session: dict = Depends(require_session)):
    hotel_id = session.get("hotel_id")
    if not hotel_id:
        return RedirectResponse(url="/onboard")

    hotel = get_hotel_profile(hotel_id)
    if not hotel:
        return RedirectResponse(url="/onboard")

    # Get user telegram status
    user = get_user_by_email(session["email"])
    telegram_linked = user.get("telegram_id") is not None if user else False

    locations_raw = hotel.get("locations", "[]")
    try:
        locations = json.loads(locations_raw)
    except Exception:
        locations = [loc.strip() for loc in locations_raw.split(",") if loc.strip()]

    dashboard_data = {}
    for location in locations:
        rec_cache = get_cache(hotel_id, location, "latest_recommendation")
        signals_cache = get_cache(hotel_id, location, "today_signals")
        history = get_recommendation_history(hotel_id, location, limit=7)

        dashboard_data[location] = {
            "recommendation": json.loads(rec_cache) if rec_cache else None,
            "signals": json.loads(signals_cache) if signals_cache else None,
            "history": history
        }

    # Get translated strings
    user_language = session.get("language", "english")
    translations = {
        "update_intelligence": get_translation("update_intelligence", user_language),
        "neural_nodes": get_translation("neural_nodes", user_language),
        "account": get_translation("account", user_language),
        "settings": get_translation("settings", user_language),
        "telegram_neural_link": get_translation("telegram_neural_link", user_language),
        "link_account_mobile": get_translation("link_account_mobile", user_language),
        "logout": get_translation("logout", user_language),
        "terminate_session": get_translation("terminate_session", user_language),
        "generate_code": get_translation("generate_code", user_language),
        "connected": get_translation("connected", user_language),
        "disconnect": get_translation("disconnect", user_language),
        "market_intelligence_pending": get_translation("market_intelligence_pending", user_language),
        "execute_market_scan": get_translation("execute_market_scan", user_language),
        "recommendation": get_translation("recommendation", user_language),
        "neural_confidence": get_translation("neural_confidence", user_language),
        "primary_driver": get_translation("primary_driver", user_language),
        "risk_profile": get_translation("risk_profile", user_language),
        "cycle_calibration": get_translation("cycle_calibration", user_language),
        "inventory_calibration": get_translation("inventory_calibration", user_language),
        "standard_inventory": get_translation("standard_inventory", user_language),
        "premium_suites": get_translation("premium_suites", user_language),
        "yield_food_beverage": get_translation("yield_food_beverage", user_language),
        "main_intake": get_translation("main_intake", user_language),
        "events_bar": get_translation("events_bar", user_language),
        "asset_specific_yield": get_translation("asset_specific_yield", user_language),
        "stable": get_translation("stable", user_language),
        "neural_cycle_summary": get_translation("neural_cycle_summary", user_language),
        "live_market_nodes": get_translation("live_market_nodes", user_language),
        "security_sessions": get_translation("security_sessions", user_language),
        "manage_sessions": get_translation("manage_sessions", user_language),
        "telegram_mobile_node": get_translation("telegram_mobile_node", user_language),
        "status_active_linked": get_translation("status_active_linked", user_language),
        "status_not_linked": get_translation("status_not_linked", user_language),
        "account_linked_telegram": get_translation("account_linked_telegram", user_language),
        "receive_real_time": get_translation("receive_real_time", user_language),
        "terminate_mobile_session": get_translation("terminate_mobile_session", user_language),
        "link_telegram_account": get_translation("link_telegram_account", user_language),
        "link_telegram_desc": get_translation("link_telegram_desc", user_language),
        "initialize_mobile_link": get_translation("initialize_mobile_link", user_language),
        "strategy_ai": get_translation("strategy_ai", user_language),
        "neural_link_established": get_translation("neural_link_established", user_language),
        "awaiting_strategic_query": get_translation("awaiting_strategic_query", user_language),
        "query_strategy_engine": get_translation("query_strategy_engine", user_language),
        "processing_signals": get_translation("processing_signals", user_language),
        "dismiss": get_translation("dismiss", user_language),
        "not_you_session_management": get_translation("not_you_session_management", user_language),
        "translating_interface": get_translation("translating_interface", user_language),
        "applying_language": get_translation("applying_language", user_language),
        "generating": get_translation("generating", user_language),
        # JS T object keys - MUST be present or template renders empty strings
        "operator": get_translation("operator", user_language),
        "ageiz_intelligence": get_translation("ageiz_intelligence", user_language),
        "accessing_data_node": get_translation("accessing_data_node", user_language),
        "error_loading_telemetry": get_translation("error_loading_telemetry", user_language),
        "neural_interpretation": get_translation("neural_interpretation", user_language),
        "node_sentiment": get_translation("node_sentiment", user_language),
        "raw_telemetry_data": get_translation("raw_telemetry_data", user_language),
        "cycle_error": get_translation("cycle_error", user_language),
        "initializing": get_translation("initializing", user_language),
        "restoring_session": get_translation("restoring_session", user_language),
        "finalizing_cycle": get_translation("finalizing_cycle", user_language),
        "market_stability": get_translation("market_stability", user_language),
        "nominal": get_translation("nominal", user_language),
        "live": get_translation("live", user_language),
        "no_granular_asset": get_translation("no_granular_asset", user_language),
        "terminate_mobile_confirm": get_translation("terminate_mobile_confirm", user_language),
        "checking_link_status": get_translation("checking_link_status", user_language),
        "not_you": get_translation("not_you", user_language),
        "account_settings": get_translation("account_settings", user_language),
        "link_for_mobile": get_translation("link_for_mobile", user_language),
    }

    return templates.TemplateResponse(request, "dashboard.html", {
        "session": session,
        "hotel": hotel,
        "locations": locations,
        "dashboard_data": dashboard_data,
        "user_language": user_language,
        "telegram_linked": telegram_linked,
        "translations": translations
    })

@app.get("/api/recommendation/{hotel_id}/{location}")
def get_recommendation(hotel_id: int, location: str, session: dict = Depends(require_session)):
    session_hotel = session.get("hotel_id")
    if session_hotel is not None and session_hotel != hotel_id:
        raise HTTPException(status_code=403, detail="Access denied")

    cached = get_cache(hotel_id, location, "latest_recommendation")
    if not cached:
        return JSONResponse({"error": "No recommendation available. Run the pipeline first."})
    return JSONResponse(json.loads(cached))

@app.get("/api/signals/{hotel_id}/{location}")
def get_signals(hotel_id: int, location: str, session: dict = Depends(require_session)):
    session_hotel = session.get("hotel_id")
    if session_hotel is not None and session_hotel != hotel_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    cached = get_cache(hotel_id, location, "today_signals")
    if not cached:
        return JSONResponse({"error": "No signals available. Run the pipeline first."})
    return JSONResponse(json.loads(cached))

@app.get("/api/history/{hotel_id}/{location}")
def get_history(hotel_id: int, location: str, session: dict = Depends(require_session)):
    session_hotel = session.get("hotel_id")
    if session_hotel is not None and session_hotel != hotel_id:
        raise HTTPException(status_code=403, detail="Access denied")

    history = get_recommendation_history(hotel_id, location, limit=7)
    return JSONResponse(history)

@app.get("/api/signals/{hotel_id}/{location}/raw")
def get_raw_signals(hotel_id: int, location: str, session: dict = Depends(require_session)):
    """Get raw signal data for the modal display."""
    session_hotel = session.get("hotel_id")
    if session_hotel is not None and session_hotel != hotel_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Get the latest signals from cache
    signals_cache = get_cache(hotel_id, location, "today_signals")
    if not signals_cache:
        return JSONResponse({"error": "No signals available"})
    
    signals = json.loads(signals_cache)
    
    # Get raw signal history for more details
    from database import get_signal_history
    history = get_signal_history(hotel_id, location, days=1)
    
    # Build raw data by signal type
    raw_data = {}
    for record in history:
        # record from database.py: {"signal_type": r[0], "sentiment": r[1], "interpretation": r[2], "recorded_at": r[3], "raw_data": r[4]}
        sig_type = record.get("signal_type")
        if sig_type and sig_type not in raw_data:
            try:
                raw_json = json.loads(record["raw_data"]) if record["raw_data"] else {}
            except Exception:
                raw_json = {"note": "Raw data truncated or unparsed", "data": record["raw_data"][:1000] if record["raw_data"] else ""}
            
            raw_data[sig_type] = {
                "sentiment": record.get("sentiment"),
                "interpretation": record.get("interpretation"),
                "raw_data": raw_json,
                "recorded_at": record.get("recorded_at")
            }
    
    return JSONResponse({
        "signals": signals,
        "raw_data": raw_data
    })

@app.post("/api/refresh/{hotel_id}")
async def refresh_pipeline(hotel_id: int, background_tasks: BackgroundTasks, session: dict = Depends(require_session)):
    # Allow if session hotel_id matches OR if session has no hotel_id but user owns this hotel
    session_hotel = session.get("hotel_id")
    if session_hotel is not None and session_hotel != hotel_id:
        # Update session with correct hotel_id
        session["hotel_id"] = hotel_id
    task_id = create_pipeline_task(hotel_id)
    background_tasks.add_task(process_pipeline_task, task_id)
    return JSONResponse({"success": True, "task_id": task_id, "message": "Pipeline started in background"})

@app.get("/api/refresh/{hotel_id}/status")
def refresh_status(hotel_id: int, session: dict = Depends(require_session)):
    # Allow if session hotel_id matches OR if session has no hotel_id but user owns this hotel
    session_hotel = session.get("hotel_id")
    if session_hotel is not None and session_hotel != hotel_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    task = get_latest_pipeline_task(hotel_id)
    return {"task": task}

@app.post("/api/telegram/generate-otp")
def generate_telegram_otp(session: dict = Depends(require_session)):
    user_id = session["user_id"]
    otp = f"{random.randint(1000, 9994)}"
    save_otp_code(user_id, otp)
    return {"otp": otp, "expires_in": "5 minutes"}


# ============================================================
# STAFF PORTAL
# ============================================================

def require_staff_session(request: Request) -> dict:
    session = get_session(request)
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if session.get("role") != "staff":
        raise HTTPException(status_code=403, detail="Staff access required")
    return session


@app.get("/staff", response_class=HTMLResponse)
def staff_dashboard(request: Request, session: dict = Depends(require_staff_session)):
    from database import get_staff_reports, get_hotel_profile, get_staff_report_summary, get_user_by_email

    # Look up hotel_id from DB (handles stale sessions)
    user = get_user_by_email(session.get("email", ""))
    hotel_id = user.get("hotel_id") if user else session.get("hotel_id")

    if not hotel_id:
        return templates.TemplateResponse(request, "staff_dashboard.html", {
            "session": session,
            "hotel": None,
            "reports": [],
            "summary": {},
            "user_language": session.get("language", "english")
        })

    hotel = get_hotel_profile(hotel_id)
    # Get recent reports
    reports = get_staff_reports(hotel_id, limit=20)
    # Get summary
    summary = get_staff_report_summary(hotel_id, days=7)

    user_language = session.get("language", "english")
    translations = {
        "submit_report": get_translation("submit_report", user_language),
        "daily_report": get_translation("daily_report", user_language),
        "weekly_report": get_translation("weekly_report", user_language),
        "monthly_report": get_translation("monthly_report", user_language),
        "customer_satisfaction": get_translation("customer_satisfaction", user_language),
        "guest_count": get_translation("guest_count", user_language),
        "occupancy": get_translation("occupancy", user_language),
        "supply_issues": get_translation("supply_issues", user_language),
        "complaints": get_translation("complaints", user_language),
        "competitor_activity": get_translation("competitor_activity", user_language),
        "events_booked": get_translation("events_booked", user_language),
        "maintenance_issues": get_translation("maintenance_issues", user_language),
        "notes": get_translation("notes", user_language),
        "free_text_observation": get_translation("free_text_observation", user_language),
        "submit": get_translation("submit", user_language),
        "recent_reports": get_translation("recent_reports", user_language),
        "report_history": get_translation("report_history", user_language),
        "no_reports_yet": get_translation("no_reports_yet", user_language),
        "staff_portal": get_translation("staff_portal", user_language),
        "daily": get_translation("daily", user_language),
        "weekly": get_translation("weekly", user_language),
        "monthly": get_translation("monthly", user_language),
        "logout": get_translation("logout", user_language),
        "ai_processing": get_translation("ai_processing", user_language),
        "report_submitted": get_translation("report_submitted", user_language),
    }

    return templates.TemplateResponse(request, "staff_dashboard.html", {
        "session": session,
        "hotel": hotel,
        "reports": reports,
        "summary": summary,
        "user_language": user_language,
        "translations": translations
    })


@app.post("/api/staff/structure")
async def structure_staff_report(
    request: Request,
    session: dict = Depends(require_staff_session)
):
    """AI-structure free-text staff input into structured data."""
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    raw_input = data.get("raw_input", "")
    report_type = data.get("report_type", "daily")

    if not raw_input:
        return JSONResponse({"error": "No input provided"}, status_code=400)

    from ai_client import call_ai_for_json
    import json

    prompt = f"""You are an AI assistant for Agéiz, a hotel intelligence platform.
A hotel staff member has submitted a {report_type} observation report in free text.
Your job is to extract and structure the information.

Based on the text, determine:
1. overall sentiment (positive/negative/neutral)
2. customer_satisfaction (1-5 integer, or null if not mentioned)
3. guest_count (integer estimate, or null)
4. occupancy_pct (percentage 0-100 float, or null)
5. popular_dishes (comma-separated string of mentioned popular foods/drinks)
6. complaints (string summary of any complaints mentioned)
7. supply_issues (string describing any supply chain or inventory issues)
8. competitor_activity (string describing any competitor activity mentioned)
9. events_booked (string about events or group bookings mentioned)
10. maintenance_issues (string about any facility or maintenance issues)
11. summary (one clear sentence summarizing the report)
12. ai_insights (one sentence of AI-generated insight or recommendation based on the data)

Return ONLY this JSON with no other text. Use null for fields not mentioned:
{{
  "sentiment": "positive" or "negative" or "neutral",
  "customer_satisfaction": 1-5 or null,
  "guest_count": integer or null,
  "occupancy_pct": 0-100 float or null,
  "popular_dishes": "comma-separated or empty string",
  "complaints": "string or empty",
  "supply_issues": "string or empty",
  "competitor_activity": "string or empty",
  "events_booked": "string or empty",
  "maintenance_issues": "string or empty",
  "summary": "one sentence summary",
  "ai_insights": "one sentence insight/recommendation"
}}

Staff free text:
{raw_input}
"""

    try:
        structured = call_ai_for_json(prompt, use_heavy_model=False)
        return JSONResponse({"success": True, "structured": structured})
    except Exception as e:
        return JSONResponse({
            "success": True,
            "structured": {
                "sentiment": "neutral",
                "customer_satisfaction": None,
                "guest_count": None,
                "occupancy_pct": None,
                "popular_dishes": "",
                "complaints": "",
                "supply_issues": "",
                "competitor_activity": "",
                "events_booked": "",
                "maintenance_issues": "",
                "summary": f"Staff submitted {report_type} report. AI processing failed to structure.",
                "ai_insights": "Data could not be auto-structured. Manager should review raw input."
            }
        })


@app.post("/api/staff/report")
async def submit_staff_report(
    request: Request,
    session: dict = Depends(require_staff_session)
):
    """Save a structured staff report."""
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    hotel_id = session.get("hotel_id")
    user_id = session["user_id"]
    report_type = data.get("report_type", "daily")
    raw_input = data.get("raw_input", "")
    structured = data.get("structured", {})

    from database import create_staff_report, award_points
    import json

    # Determine quality for points
    has_ai = bool(structured.get("summary") and len(structured.get("summary", "")) > 20)
    data_quality = "ai_structured" if has_ai else "good"

    report_id = create_staff_report(
        hotel_id=hotel_id,
        user_id=user_id,
        report_type=report_type,
        raw_input=raw_input,
        structured_data=json.dumps(structured),
        sentiment=structured.get("sentiment", "neutral"),
        customer_satisfaction=structured.get("customer_satisfaction"),
        guest_count=structured.get("guest_count"),
        occupancy_pct=structured.get("occupancy_pct"),
        popular_dishes=structured.get("popular_dishes"),
        complaints=structured.get("complaints"),
        supply_issues=structured.get("supply_issues"),
        competitor_activity=structured.get("competitor_activity"),
        events_booked=structured.get("events_booked"),
        maintenance_issues=structured.get("maintenance_issues"),
        summary=structured.get("summary"),
        ai_insights=structured.get("ai_insights")
    )

    # Award points
    points = award_points(user_id, hotel_id, report_type, data_quality)

    return JSONResponse({"success": True, "report_id": report_id, "points_earned": points})


@app.get("/api/staff/leaderboard")
def get_staff_leaderboard(session: dict = Depends(require_staff_session)):
    """Get leaderboard for the staff member's hotel."""
    hotel_id = session.get("hotel_id")
    if not hotel_id:
        return JSONResponse({"leaderboard": [], "my_rank": {"rank": 0, "points": 0}})

    from database import get_leaderboard, get_user_rank
    leaderboard = get_leaderboard(hotel_id, limit=10)
    my_rank = get_user_rank(hotel_id, session["user_id"])

    return JSONResponse({"leaderboard": leaderboard, "my_rank": my_rank})


@app.get("/api/leaderboard")
def get_manager_leaderboard(hotel_id: int, session: dict = Depends(require_session)):
    """Manager endpoint: get leaderboard for their hotel."""
    session_hotel = session.get("hotel_id")
    if session_hotel is not None and session_hotel != hotel_id:
        raise HTTPException(status_code=403, detail="Access denied")

    from database import get_leaderboard
    leaderboard = get_leaderboard(hotel_id, limit=10)
    return JSONResponse({"leaderboard": leaderboard})


@app.get("/api/staff/reports")
def get_staff_reports_api(session: dict = Depends(require_staff_session)):
    """Get staff report history for the current hotel."""
    hotel_id = session.get("hotel_id")
    if not hotel_id:
        return JSONResponse({"reports": []})

    from database import get_staff_reports
    reports = get_staff_reports(hotel_id, limit=30)
    return JSONResponse({"reports": reports})


@app.get("/api/staff/intelligence")
def get_staff_intelligence_api(hotel_id: int, session: dict = Depends(require_session)):
    """Manager endpoint: get aggregated staff intelligence for their hotel."""
    session_hotel = session.get("hotel_id")
    if session_hotel is not None and session_hotel != hotel_id:
        raise HTTPException(status_code=403, detail="Access denied")

    from database import get_staff_reports, get_staff_report_summary
    reports = get_staff_reports(hotel_id, limit=30)
    summary = get_staff_report_summary(hotel_id, days=7)

    return JSONResponse({
        "reports": reports,
        "summary": summary
    })


# ============================================================
# EMBEDDABLE FORM / WIDGET
# ============================================================

@app.get("/embed/{token}")
def embed_form(token: str):
    """Render the embeddable form as a standalone page."""
    from database import verify_embed_token
    embed = verify_embed_token(token)
    if not embed:
        return JSONResponse({"error": "Invalid embed token"}, status_code=404)

    return templates.TemplateResponse(None, "embed.html", {
        "token": token,
        "label": embed["label"],
        "api_url": request.base_url
    })

@app.post("/api/embed/{token}")
async def submit_embed_form(token: str, request: Request):
    """Receive embedded form submission."""
    from database import verify_embed_token, save_embedded_submission
    embed = verify_embed_token(token)
    if not embed:
        return JSONResponse({"error": "Invalid embed token"}, status_code=404)

    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    submission_id = save_embedded_submission(
        hotel_id=embed["hotel_id"],
        token=token,
        data=data
    )
    return JSONResponse({"success": True, "id": submission_id})

@app.post("/api/embed/create-token")
async def create_embed_token_api(request: Request, session: dict = Depends(require_session)):
    """Manager creates a new embed token."""
    hotel_id = session.get("hotel_id")
    if not hotel_id:
        return JSONResponse({"error": "No hotel linked"}, status_code=400)

    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    label = data.get("label", "Website Feedback Widget")
    form_fields = data.get("form_fields")

    from database import create_embed_token
    token = create_embed_token(hotel_id, label, form_fields)

    return JSONResponse({"success": True, "token": token, "label": label})

@app.get("/api/embed/tokens")
def list_embed_tokens(session: dict = Depends(require_session)):
    """List embed tokens for manager's hotel."""
    hotel_id = session.get("hotel_id")
    if not hotel_id:
        return JSONResponse({"tokens": []})

    from database import get_embed_tokens
    tokens = get_embed_tokens(hotel_id)
    return JSONResponse({"tokens": tokens})

@app.delete("/api/embed/token/{token_id}")
def delete_embed_token_api(token_id: int, session: dict = Depends(require_session)):
    hotel_id = session.get("hotel_id")
    if not hotel_id:
        raise HTTPException(status_code=400, detail="No hotel linked")

    from database import delete_embed_token
    ok = delete_embed_token(token_id, hotel_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Token not found")
    return JSONResponse({"success": True})

@app.get("/api/embed/submissions")
def list_embed_submissions(session: dict = Depends(require_session)):
    hotel_id = session.get("hotel_id")
    if not hotel_id:
        return JSONResponse({"submissions": [], "stats": {}})

    from database import get_embedded_submissions, get_embedded_stats
    submissions = get_embedded_submissions(hotel_id)
    stats = get_embedded_stats(hotel_id)
    return JSONResponse({"submissions": submissions, "stats": stats})


# ============================================================
# EMPLOYEE MANAGEMENT (Manager Only)
# ============================================================

@app.post("/api/employee/create")
async def create_employee(
    request: Request,
    session: dict = Depends(require_session)
):
    """Manager creates a staff account linked to their hotel."""
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    role = data.get("role", "staff")

    if not email or not password:
        return JSONResponse({"error": "Email and password are required"}, status_code=400)

    if "@" not in email:
        return JSONResponse({"error": "Invalid email address"}, status_code=400)

    if len(password) < 4:
        return JSONResponse({"error": "Password must be at least 4 characters"}, status_code=400)

    if role not in ("staff", "manager"):
        role = "staff"

    from database import get_user_by_email, create_user, update_user_hotel
    existing = get_user_by_email(email)
    if existing:
        return JSONResponse({"error": "Email already registered"}, status_code=409)

    hotel_id = session.get("hotel_id")
    if not hotel_id:
        return JSONResponse({"error": "Your account is not linked to a hotel. Complete onboarding first."}, status_code=400)

    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    user_id = create_user(email, password_hash, role)
    update_user_hotel(user_id, hotel_id)

    return JSONResponse({
        "success": True,
        "user_id": user_id,
        "email": email,
        "role": role
    })


@app.get("/api/employees")
def list_employees(session: dict = Depends(require_session)):
    """List all employees linked to the manager's hotel."""
    hotel_id = session.get("hotel_id")
    if not hotel_id:
        return JSONResponse({"employees": []})

    import sqlite3
    conn = sqlite3.connect("ageiz.db")
    cursor = conn.execute("""
        SELECT id, email, role, telegram_id, language, created_at
        FROM users
        WHERE hotel_id = ?
        ORDER BY created_at DESC
    """, (hotel_id,))
    rows = cursor.fetchall()
    conn.close()

    employees = [
        {"id": r[0], "email": r[1], "role": r[2], "telegram_id": r[3], "language": r[4], "created_at": r[5]}
        for r in rows
    ]
    return JSONResponse({"employees": employees})


@app.delete("/api/employee/{employee_id}")
def delete_employee(employee_id: int, session: dict = Depends(require_session)):
    """Remove an employee (reset their hotel link so they can't login)."""
    hotel_id = session.get("hotel_id")
    if not hotel_id:
        raise HTTPException(status_code=400, detail="No hotel linked")

    import sqlite3
    conn = sqlite3.connect("ageiz.db")
    # Verify the employee belongs to this hotel
    cursor = conn.execute("SELECT hotel_id FROM users WHERE id = ?", (employee_id,))
    row = cursor.fetchone()
    if not row or row[0] != hotel_id:
        conn.close()
        raise HTTPException(status_code=403, detail="Access denied")

    conn.execute("UPDATE users SET hotel_id = NULL WHERE id = ?", (employee_id,))
    conn.commit()
    conn.close()

    return JSONResponse({"success": True})


@app.post("/api/employee/{employee_id}/reset-password")
async def reset_employee_password(
    employee_id: int, request: Request, session: dict = Depends(require_session)
):
    """Reset an employee's password."""
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    new_password = data.get("new_password", "")
    if len(new_password) < 4:
        return JSONResponse({"error": "Password must be at least 4 characters"}, status_code=400)

    hotel_id = session.get("hotel_id")
    if not hotel_id:
        raise HTTPException(status_code=400, detail="No hotel linked")

    import sqlite3
    conn = sqlite3.connect("ageiz.db")
    cursor = conn.execute("SELECT hotel_id FROM users WHERE id = ?", (employee_id,))
    row = cursor.fetchone()
    if not row or row[0] != hotel_id:
        conn.close()
        raise HTTPException(status_code=403, detail="Access denied")

    password_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, employee_id))
    conn.commit()
    conn.close()

    return JSONResponse({"success": True})


# ============================================================
# TELEGRAM & MISC
# ============================================================

@app.get("/api/telegram/status")
def telegram_status(request: Request):
    """Check Telegram link status. Gracefully handles missing session instead of 401."""
    session = get_session(request)
    if not session:
        return {"linked": False, "note": "Not authenticated"}
    email = session.get("email")
    if not email:
        return {"linked": False, "note": "No email in session"}
    user = get_user_by_email(email)
    if not user:
        return {"linked": False, "note": "User not found"}
    return {"linked": user.get("telegram_id") is not None}

@app.post("/api/telegram/unlink")
async def telegram_unlink(user: dict = Depends(get_current_user)):
    tg_id = user.get("telegram_id")
    if tg_id:
        try:
            from telegram_bot import bot_app
            if bot_app:
                await bot_app.bot.send_message(
                    chat_id=tg_id,
                    text="🚪 *Security Alert*\nYour mobile session has been terminated from the web interface. Please generate a new OTP to reconnect.",
                    parse_mode='Markdown'
                )
        except Exception:
            pass
        unlink_telegram_id(tg_id)
    return {"success": True}

@app.post("/api/language")
async def set_language(request: Request, session: dict = Depends(require_session)):
    try:
        data = await request.json()
    except:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    language = data.get("language", "english")
    valid_languages = ["english", "amharic", "oromoo", "tigrinya", "chinese"]
    if language not in valid_languages:
        return JSONResponse({"error": "Invalid language"}, status_code=400)

    # Update in database
    update_user_language(session["user_id"], language)

    # Update session cookie
    token = serializer.dumps({
        "user_id": session["user_id"],
        "email": session["email"],
        "hotel_id": session.get("hotel_id"),
        "language": language
    })
    response = JSONResponse({"success": True, "language": language})
    response.set_cookie("session", token, httponly=True, max_age=86400, samesite="lax")
    return response

async def process_pipeline_task(task_id: int):
    try:
        task = get_pipeline_task(task_id)
        if not task:
            return

        hotel_id = task["hotel_id"]
        # run_pipeline is now async and handles its own threading for sync fetchers
        result = await run_pipeline(hotel_id, task_id)

        if "error" in result:
            try:
                update_pipeline_task(task_id, 'failed', error=result.get("error"))
            except Exception as db_error:
                print(f"[worker] Failed to update task status: {db_error}")
        else:
            # Ensure task is marked as completed
            try:
                update_pipeline_task(task_id, 'completed', progress=100, message='Pipeline complete')
            except Exception as db_error:
                print(f"[worker] Failed to update task status: {db_error}")
    except Exception as e:
        print(f"[worker] Pipeline error: {e}")
        try:
            update_pipeline_task(task_id, 'failed', error=str(e))
        except Exception as db_error:
            print(f"[worker] Failed to update task status: {db_error}")

@app.get("/api/task/{task_id}")
def get_task_status(task_id: int, session: dict = Depends(require_session)):
    try:
        task = get_pipeline_task(task_id)
    except Exception as e:
        print(f"[api] Database error fetching task {task_id}: {e}")
        return JSONResponse({
            "id": task_id,
            "hotel_id": session.get("hotel_id"),
            "status": "running",
            "progress": 0,
            "message": "Checking pipeline status...",
            "thoughts": "",
            "error": None,
            "created_at": None,
            "started_at": None,
            "completed_at": None
        })

    if not task:
        return JSONResponse({"status": "not_found"})

    return JSONResponse({
        "id": task["id"],
        "hotel_id": task["hotel_id"],
        "status": task["status"],
        "progress": task["progress"],
        "message": task["message"],
        "thoughts": task["thoughts"],
        "error": task["error"],
        "created_at": task["created_at"],
        "started_at": task["started_at"],
        "completed_at": task["completed_at"]
    })

@app.get("/api/chat/history")
def chat_history(location: str = None, session: dict = Depends(require_session)):
    hotel_id = session["hotel_id"]
    # Global history for the hotel to prevent "wiping" on location change
    history = get_chat_history(hotel_id, location=None)
    return {"history": history}

@app.post("/api/chat/message")
async def chat_message(request: Request, session: dict = Depends(require_session)):
    hotel_id = session["hotel_id"]
    user_id = session["user_id"]
    user_language = session.get("language", "english")
    try:
        data = await request.json()
    except:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    message = data.get("message")
    location = data.get("location")

    if not message:
        return JSONResponse({"error": "Message required"}, status_code=400)

    response = await get_chat_response(hotel_id, user_id, message, location, user_language)
    return {"response": response}


# --- Custom Signal Sources API ---

@app.get("/api/custom-signals")
def list_custom_signals(session: dict = Depends(require_session)):
    from database import get_custom_signals
    hotel_id = session.get("hotel_id")
    if not hotel_id:
        raise HTTPException(status_code=400, detail="No hotel in session")
    signals = get_custom_signals(hotel_id)
    # Mask API keys in response
    for s in signals:
        s["api_key"] = "***" if s.get("api_key") else ""
    return {"signals": signals}

@app.post("/api/custom-signals")
async def create_custom_signal_endpoint(request: Request, session: dict = Depends(require_session)):
    from database import create_custom_signal
    hotel_id = session.get("hotel_id")
    if not hotel_id:
        raise HTTPException(status_code=400, detail="No hotel in session")
    data = await request.json()
    name = data.get("name", "").strip()
    description = data.get("description", "").strip()
    if not name or not description:
        return JSONResponse({"error": "Name and description are required"}, status_code=400)
    signal_id = create_custom_signal(
        hotel_id=hotel_id,
        name=name,
        description=description,
        url=data.get("url", ""),
        api_key=data.get("api_key", ""),
        api_key_label=data.get("api_key_label", "Authorization"),
        headers=data.get("headers", ""),
        method=data.get("method", "GET"),
        body=data.get("body", ""),
        response_path=data.get("response_path", "")
    )
    return {"success": True, "id": signal_id}

@app.put("/api/custom-signals/{signal_id}")
async def update_custom_signal_endpoint(signal_id: int, request: Request, session: dict = Depends(require_session)):
    from database import update_custom_signal
    data = await request.json()
    update_custom_signal(signal_id, **data)
    return {"success": True}

@app.delete("/api/custom-signals/{signal_id}")
def delete_custom_signal_endpoint(signal_id: int, session: dict = Depends(require_session)):
    from database import delete_custom_signal
    delete_custom_signal(signal_id)
    return {"success": True}

@app.post("/api/custom-signals/{signal_id}/toggle")
def toggle_custom_signal_endpoint(signal_id: int, session: dict = Depends(require_session)):
    from database import toggle_custom_signal
    toggle_custom_signal(signal_id)
    return {"success": True}

@app.post("/api/custom-signals/test")
async def test_custom_signal(request: Request, session: dict = Depends(require_session)):
    from signals.custom import _fetch_single_source
    data = await request.json()
    try:
        result = _fetch_single_source(data)
        return {"success": True, "data": result}
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
