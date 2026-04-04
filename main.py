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
from telegram_bot import setup_bot, bot_app
from translator import translate_text
from translations import get_translation

load_dotenv()
init_db()

app = FastAPI(title="Ageiz")

@app.on_event("startup")
async def startup_event():
    # Start Telegram Bot in the same event loop
    asyncio.create_task(setup_bot())
templates = Jinja2Templates(directory="templates")

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
async def register(request: Request, email: str = Form(...), password: str = Form(...)):
    existing = get_user_by_email(email)
    if existing:
        return templates.TemplateResponse(request, "login.html", {
            "error": "Email already registered",
            "tab": "register"
        })

    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    user_id = create_user(email, password_hash)

    token = serializer.dumps({"user_id": user_id, "email": email, "hotel_id": None, "language": "english"})
    response = RedirectResponse(url="/onboard", status_code=302)
    response.set_cookie("session", token, httponly=True, max_age=86400, samesite="lax")
    return response

@app.post("/auth/login")
async def login(request: Request, email: str = Form(...), password: str = Form(...)):
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

    user_language = user.get("language", "english")
    token = serializer.dumps({
        "user_id": user["id"],
        "email": user["email"],
        "hotel_id": user["hotel_id"],
        "language": user_language
    })

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
    return templates.TemplateResponse(request, "onboard.html", {"session": session})

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
    otp = f"{random.randint(1000, 9999)}"
    save_otp_code(user_id, otp)
    return {"otp": otp, "expires_in": "5 minutes"}

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
        if bot_app:
            try:
                await bot_app.bot.send_message(
                    chat_id=tg_id,
                    text="🚪 *Security Alert*\nYour mobile session has been terminated from the web interface. Please generate a new OTP to reconnect.",
                    parse_mode='Markdown'
                )
            except: pass
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
