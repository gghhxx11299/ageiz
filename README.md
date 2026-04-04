# 🏨 Agéiz — Ethiopian Resort Pricing Intelligence

> AI-powered revenue management and pricing intelligence for Ethiopian hotels and resorts.

[![Live](https://img.shields.io/badge/Live-https://ageiz.onrender.com-brightgreen)](https://ageiz.onrender.com)
[![Python](https://img.shields.io/badge/Python-3.11-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688)](https://fastapi.tiangolo.com/)

---

## 🚀 Try It Now

👉 **[https://ageiz.onrender.com](https://ageiz.onrender.com)**

Register as a **Manager** or **Staff** and start getting data-driven pricing recommendations in under 5 minutes.

---

## 📖 What Is Agéiz?

Agéiz analyzes **8+ real-time market signals** — weather, holidays, flight arrivals, search trends, news, social media, exchange rates, and custom data sources — to deliver precise pricing recommendations tailored to Ethiopian resort dynamics.

Built for hotel **managers, revenue officers, and operational staff** who need data-driven pricing decisions, not guesswork.

---

## ✨ Features

### 🧠 Market Intelligence Engine
- **Weather Intelligence** — Real-time rainfall & temperature for every Ethiopian location
- **Holiday Calendar** — Orthodox fasting periods, Genna, Timket, Fasika, Enkutatash, Meskel
- **Flight Tracking** — OpenSky arrivals at Bole Airport + Amadeus search intent
- **Google Trends** — Search interest for Ethiopian tourism keywords
- **News Sentiment** — Ethiopian tourism & hospitality news analysis
- **Social Listening** — Reddit posts, YouTube travel vlogs, exchange rates

### 📊 Manager Dashboard
- **Multi-location support** — Track multiple resort locations from one dashboard
- **Pricing recommendations** — AI-generated % adjustments for rooms, F&B, and every amenity
- **Signal dashboard** — Live sentiment analysis with emoji-coded signals (🟢🔴🟡)
- **AI Strategy Chat** — Conversational revenue management assistant with web search
- **Staff intelligence** — View aggregated staff reports and insights
- **Leaderboard** — Top 3 contributors with points and report counts
- **Employee management** — Create, manage, and remove staff accounts
- **Embeddable feedback forms** — Generate shareable links or iframes for guest feedback
- **Multi-language** — English, Amharic, Afaan Oromoo, Tigrinya, Chinese

### 📝 Staff Portal
- **Daily/Weekly/Monthly reports** — Submit observations in free text, AI structures the data
- **Smart sliders** — Customer satisfaction, guest count, occupancy %
- **AI auto-structuring** — As staff types, AI parses and previews structured data
- **Gamification** — Points system, leaderboard, rank tracking
- **QR code rewards** — Submit feedback → earn redeemable points

### 🤖 Telegram Bot
- **Full feature parity** — All manager and staff features available on mobile
- **Inline keyboards** — Location nodes, signals, strategies, leaderboards
- **Real-time pipeline progress** — Streamed updates during market scans
- **AI chat** — Free-text strategy consultant
- **Staff reports** — Submit observations directly from Telegram
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
| **Database** | SQLite 3 |
| **AI/ML** | Groq (Llama 3.3 70B), OpenRouter fallback, Poe Web-Search |
| **Translation** | HuggingFace NLLB-200 (Amharic, Oromoo, Tigrinya, Chinese) |
| **Data Sources** | Open-Meteo, OpenSky, Google Trends, YouTube API, Exchange rates, DDGS |
| **Telegram** | python-telegram-bot v21 |
| **Frontend** | Jinja2, vanilla JS, CSS |
| **Fonts** | Playfair Display (headings), Inter (body) |
| **Deployment** | Render |

---

## 📊 Signal Reference

| Signal | Description |
|---|---|
| `weather` | Rainfall, temperature, seasonal deviation for Ethiopian locations |
| `calendar` | Ethiopian Orthodox holidays with demand impact scores |
| `flights` | Bole Airport arrivals + search intent |
| `trends` | Google Trends for Ethiopian tourism keywords |
| `news` | Ethiopian tourism & hospitality news |
| `reddit` | Reddit posts about Ethiopia travel |
| `youtube` | Travel vlogs and resort content |
| `exchange` | USD/ETB rate with 30-day trend |
| `staff_intelligence` | Aggregated ground intelligence from staff submissions |
| `custom_*` | External APIs configured by the manager |

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

| Language | Script |
|---|---|
| 🇬🇧 English | Latin |
| 🇪🇹 Amharic | Ethiopic (ግዕዝ) |
| 🇪🇹 Afaan Oromoo | Latin |
| 🇪🇭 Tigrinya | Ethiopic (ግዕዝ) |
| 🇨🇳 Chinese | Simplified |

---

## 📁 Project Structure

```
ageiz/
├── main.py                 # FastAPI app, routes, middleware
├── database.py             # SQLite data models
├── pipeline.py             # Parallel signal pipeline engine
├── pricing_engine.py       # AI-driven recommendation generator
├── ai_client.py            # Groq + OpenRouter with fallback
├── chat_agent.py           # Strategy AI with web search
├── scraper.py              # 4-level hotel website scraper
├── telegram_bot.py         # Full Telegram bot
├── translator.py           # HuggingFace NLLB-200
├── interpreter.py          # Signal-specific AI interpretation
├── ethiopia_calendar.py    # 2026 Ethiopian holidays
├── translations.py         # Multi-language translation strings
├── signals/                # Signal fetcher modules
├── templates/              # Jinja2 HTML templates
├── render.yaml             # Render deployment blueprint
├── Procfile                # Gunicorn start command
└── requirements.txt
```

---

## 📄 License

MIT License

---

**Built with ❤️ for Ethiopian hospitality**
