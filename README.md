# 🏨 Agéiz — Ethiopian Resort Pricing Intelligence

> AI-powered revenue management and pricing intelligence for Ethiopian hotels and resorts.

[![Python](https://img.shields.io/badge/Python-3.11-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

---

## 📖 Overview

Agéiz analyzes **8+ real-time market signals** — weather, holidays, flight arrivals, search trends, news, social media, exchange rates, and custom data sources — to deliver precise pricing recommendations tailored to Ethiopian resort dynamics.

Built for hotel **managers, revenue officers, and operational staff** who need data-driven pricing decisions, not guesswork.

---

## ✨ Features

### 🧠 Market Intelligence Engine
- **Weather Intelligence** — Real-time rainfall & temperature for every Ethiopian location, with highland commodity impact
- **Holiday Calendar** — Orthodox fasting periods, Genna, Timket, Fasika, Enkutatash, Meskel — with demand impact scores
- **Flight Tracking** — OpenSky arrivals at Bole Airport + Amadeus search intent
- **Google Trends** — Search interest for Ethiopian tourism keywords
- **News Sentiment** — Ethiopian tourism & hospitality news analysis
- **Social Listening** — Reddit posts, YouTube travel vlogs, exchange rates

### 📊 Manager Dashboard
- **Multi-location support** — Track multiple resort locations from one dashboard
- **Pricing recommendations** — AI-generated % adjustments for rooms, F&B, and every amenity
- **Signal dashboard** — Live sentiment analysis with emoji-coded signals (🟢🔴🟡)
- **AI Strategy Chat** — Conversational revenue management assistant with web search
- **Custom signal sources** — Add external APIs, RSS feeds, or data endpoints
- **Embeddable feedback forms** — Generate shareable links or iframes for guest feedback
- **Staff intelligence** — View aggregated staff reports and insights
- **Leaderboard** — Top 3 contributors with points and report counts
- **Employee management** — Create, manage, and remove staff accounts
- **Multi-language** — English, Amharic, Afaan Oromoo, Tigrinya, Chinese

### 📝 Staff Portal
- **Daily/Weekly/Monthly reports** — Submit observations in free text, AI structures the data
- **Smart sliders** — Customer satisfaction (1-5), guest count, occupancy %
- **AI auto-structuring** — As staff types, AI parses and previews structured data
- **Gamification** — Points system, leaderboard, rank tracking
- **QR code rewards** — Submit feedback → earn redeemable points

### 🤖 Telegram Bot
- **Full feature parity** — All manager and staff features available on mobile
- **Inline keyboards** — Location nodes, signals, strategies, leaderboards
- **Real-time pipeline progress** — Streamed 10%, 20%, 30%... during market scans
- **AI chat** — Free-text strategy consultant
- **Staff reports** — Submit observations directly from Telegram
- **Employee management** — Create accounts, generate passwords
- **Embed form management** — Create links, view submissions
- **Leaderboard** — Full rankings with points
- **OTP authentication** — Secure 4-digit code linking

### 🌐 Embeddable Guest Feedback
- **Branded feedback form** — Star ratings (Overall, Cleanliness, Staff, Value, Food)
- **QR code rewards** — Guests earn points for submitting feedback
- **Manager dashboard** — View submissions with stats, averages, and recommend rates
- **Copy-paste deploy** — Share link or embed via `<iframe>` on any website

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    User Interfaces                       │
├─────────────┬──────────────┬──────────────┬─────────────┤
│   Manager   │    Staff     │   Telegram   │   Guest     │
│  Dashboard  │    Portal    │     Bot      │  Embed Form │
├─────────────┴──────────────┴──────────────┴─────────────┤
│                     FastAPI Backend                       │
├─────────────┬──────────────┬──────────────┬─────────────┤
│  Pipeline   │  AI Client   │  Scraper     │  Chat Agent │
│  Engine     │  (Groq +     │  (4-level    │  (Strategy  │
│             │  OpenRouter) │  scrape)     │  AI)        │
├─────────────┴──────────────┴──────────────┴─────────────┤
│                      Signal Sources                       │
├───────┬────────┬────────┬────────┬────────┬─────────────┤
│Weather│Calendar│Flights │Trends  │News    │Custom APIs  │
├───────┼────────┼────────┼────────┼────────┼─────────────┤
│Reddit │YouTube │Exchange│Staff Rpt│Embed Fb│Commodity    │
├───────┴────────┴────────┴────────┴────────┴─────────────┤
│                    SQLite Database                        │
└─────────────────────────────────────────────────────────┘
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | FastAPI, Gunicorn, UvicornWorker |
| **Database** | SQLite 3 (local) |
| **AI/ML** | Groq (Llama 3.3 70B), OpenRouter fallback, Poe Web-Search |
| **Translation** | HuggingFace NLLB-200 (Amharic, Oromoo, Tigrinya, Chinese) |
| **Data Sources** | Open-Meteo (weather), OpenSky (flights), Google Trends, YouTube API, Exchange rates, DDGS search |
| **Telegram** | python-telegram-bot v21 |
| **Frontend** | Jinja2 templates, vanilla JS, CSS |
| **Fonts** | Playfair Display (headings), Inter (body) |
| **Deployment** | Render (free tier) |

---

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- API keys (see `.env.example` below)

### 1. Clone & Install
```bash
git clone https://github.com/gghhxx11299/ageiz.git
cd ageiz
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium --with-deps
```

### 2. Configure Environment
Create a `.env` file:
```env
GROQ_API_KEY=your_groq_key
OPENROUTER_API_KEY=your_openrouter_key
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
AMADEUS_CLIENT_ID=your_amadeus_id
AMADEUS_CLIENT_SECRET=your_amadeus_secret
EXCHANGE_RATE_API_KEY=your_exchange_key
YOUTUBE_API_KEY=your_youtube_key
HUGGINGFACE_TOKEN=your_hf_token
POE_API_KEY=your_poe_key
SECRET_KEY=your_secret_key
WEBHOOK_URL=https://your-domain.com
```

### 3. Run Locally
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000** — register as a Manager, onboard your hotel, and run your first pipeline.

### 4. Test Accounts (Local)
```python
# Run once to seed test data
python3 -c "
import bcrypt
from database import create_user, save_hotel_profile, update_user_hotel
m = create_user('manager@test.com', bcrypt.hashpw(b'test123', bcrypt.gensalt()).decode(), 'manager')
h = save_hotel_profile(m, 'Test Grand Hotel', 'https://test.ai', '[\"Addis Ababa\"]', '[\"Standard\"]', '[\"Pool\"]', 'Luxury resort', '[\"Local\"]', 'premium', '[\"Lakefront\"]', 'Grow revenue')
update_user_hotel(m, h)
create_user('staff@test.com', bcrypt.hashpw(b'test123', bcrypt.gensalt()).decode(), 'staff')
update_user_hotel(create_user('staff@test.com', bcrypt.hashpw(b'test123', bcrypt.gensalt()).decode(), 'staff'), h)
"
```

| Role | Email | Password | URL |
|---|---|---|---|
| Manager | `manager@test.com` | `test123` | `/dashboard` |
| Staff | `staff@test.com` | `test123` | `/staff` |

---

## 📡 Deploy to Render

1. Fork this repo
2. Go to [Render Dashboard](https://dashboard.render.com) → **New +** → **Blueprint**
3. Connect your repo
4. Fill in environment variables (API keys)
5. Set `WEBHOOK_URL: https://ageiz.onrender.com` for Telegram webhooks
6. Click **Apply**

The `render.yaml` blueprint handles build and start automatically.

---

## 📊 Signal Reference

| Signal | Source | Frequency | Description |
|---|---|---|---|
| `weather` | Open-Meteo | Per run | Rainfall, temperature, seasonal deviation for Ethiopian locations |
| `calendar` | Built-in | Per run | Ethiopian Orthodox holidays with demand impact scores |
| `flights` | OpenSky + Amadeus | Per run | Bole Airport arrivals + search intent |
| `trends` | pytrends | Per run | Google Trends for Ethiopian tourism keywords |
| `news` | DDGS search | Per run | Ethiopian tourism & hospitality news |
| `reddit` | DDGS search | Per run | Reddit posts about Ethiopia travel |
| `youtube` | YouTube API | Per run | Travel vlogs and resort content |
| `exchange` | Exchange API | Per run | USD/ETB rate with 30-day trend |
| `highland` | Open-Meteo (regions) | Per run | Amhara, Oromia, SNNPR commodity weather |
| `staff_intelligence` | Staff reports | Pipeline | Aggregated ground intelligence from staff submissions |
| `custom_*` | User-defined APIs | Per run | External APIs configured by the manager |

---

## 🏆 Points System

| Action | Points |
|---|---|
| Daily report | 10 pts |
| Weekly report | 25 pts |
| Monthly report | 50 pts |
| AI-structured (rich detail) | +10 bonus |
| Excellent quality | +15 bonus |
| Guest feedback submission | 25 pts |

---

## 🌍 Multi-Language Support

All user-facing text is translated across 5 languages:

| Language | Code | Script |
|---|---|---|
| English | `english` | Latin |
| Amharic | `amharic` | Ethiopic (ግዕዝ) |
| Afaan Oromoo | `oromoo` | Latin |
| Tigrinya | `tigrinya` | Ethiopic (ግዕዝ) |
| Chinese | `chinese` | Simplified |

---

## 📁 Project Structure

```
ageiz/
├── main.py                 # FastAPI app, routes, middleware
├── database.py             # SQLite ORM, all data models
├── pipeline.py             # Parallel signal pipeline engine
├── pricing_engine.py       # AI-driven recommendation generator
├── ai_client.py            # Groq + OpenRouter with fallback
├── chat_agent.py           # Strategy AI with web search
├── scraper.py              # 4-level hotel website scraper
├── telegram_bot.py         # Full Telegram bot (inline keyboards)
├── translator.py           # HuggingFace NLLB-200 with caching
├── interpreter.py          # Signal-specific AI interpretation
├── ethiopia_calendar.py    # 2026 Ethiopian holidays
├── translations.py         # Multi-language translation strings
├── weekly_summary.py       # Weekly sentiment aggregation
├── signals/                # Signal fetcher modules
│   ├── weather.py
│   ├── calendar.py
│   ├── flights.py
│   ├── trends.py
│   ├── news.py
│   ├── reddit.py
│   ├── youtube.py
│   ├── exchange.py
│   └── custom.py
├── templates/              # Jinja2 HTML templates
│   ├── home.html           # Landing page
│   ├── login.html          # Auth with role selector
│   ├── onboard.html        # Hotel onboarding
│   ├── dashboard.html      # Manager dashboard
│   ├── staff_dashboard.html # Staff portal
│   └── embed.html          # Guest feedback form + QR
├── render.yaml             # Render deployment blueprint
├── Procfile                # Gunicorn start command
├── requirements.txt        # Python dependencies
└── .gitignore
```

---

## 🔑 API Endpoints

### Auth
- `POST /auth/register` — Register (Manager or Staff)
- `POST /auth/login` — Login with role
- `POST /auth/logout` — Logout

### Manager
- `GET /dashboard` — Manager dashboard
- `POST /onboard/scrape` — Scrape hotel website
- `POST /api/refresh/{hotel_id}` — Run market pipeline
- `GET /api/recommendation/{hotel_id}/{location}` — Get cached recommendation
- `GET /api/signals/{hotel_id}/{location}` — Get cached signals
- `POST /api/employee/create` — Create staff account
- `GET /api/employees` — List employees
- `DELETE /api/employee/{id}` — Remove employee
- `POST /api/embed/create-token` — Create embed form
- `GET /api/embed/submissions` — View guest feedback
- `GET /api/leaderboard?hotel_id=X` — Staff leaderboard

### Staff
- `GET /staff` — Staff portal
- `POST /api/staff/structure` — AI-structure free text
- `POST /api/staff/report` — Submit structured report
- `GET /api/staff/leaderboard` — My rank + leaderboard

### Embed
- `GET /embed/{token}` — Guest feedback form
- `POST /api/embed/{token}` — Submit feedback

### Health
- `GET /health` — Status + latency ping

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

**Built with ❤️ for Ethiopian hospitality**
