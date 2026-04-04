import os
import json
import httpx
from typing import Optional, List, Dict, Any
from ai_client import groq_client
from database import get_hotel_profile, get_cache, get_chat_history, save_chat_message
from translator import translate_text

POE_API_KEY = os.getenv("POE_API_KEY", "")
POE_BOT_NAME = "Web-Search"
CHAT_HISTORY_LIMIT = 10
POE_TIMEOUT = 30.0

async def call_poe_search(query: str) -> str:
    """Calls Poe's Web-Search bot to get external information."""
    if not POE_API_KEY:
        print("[chat_agent] POE_API_KEY not configured")
        return "Search unavailable (credentials missing)."

    print(f"[chat_agent] Consulting Poe Web-Search for: {query}")
    try:
        async with httpx.AsyncClient(timeout=POE_TIMEOUT) as client:
            response = await client.post(
                "https://api.poe.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {POE_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": POE_BOT_NAME,
                    "messages": [{"role": "user", "content": query}]
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                return data["choices"][0]["message"]["content"]
            else:
                print(f"[chat_agent] Poe API error: {response.status_code} - {response.text}")
                return f"Error searching: {response.status_code}"
    except Exception as e:
        print(f"[chat_agent] Poe search failed: {e}")
        return "Search unavailable due to connection error."

async def get_chat_response(
    hotel_id: int,
    user_id: int,
    user_message: str,
    location: Optional[str] = None,
    user_language: str = "english"
) -> str:
    # 1. Gather Context
    profile = get_hotel_profile(hotel_id)
    if not profile:
        return "Error: Hotel profile not found."

    history = get_chat_history(hotel_id, location=None, limit=CHAT_HISTORY_LIMIT)

    # Get latest signals and recommendations from cache
    signals_raw = get_cache(hotel_id, location, "today_signals") if location else None
    signals = json.loads(signals_raw) if signals_raw else {}

    # 2. Build System Prompt with language instruction
    lang_instruction = ""
    if user_language and user_language.lower() != "english":
        lang_map = {
            "amharic": "IMPORTANT: Respond entirely in Amharic (አማርኛ).",
            "oromoo": "IMPORTANT: Respond entirely in Afaan Oromoo.",
            "tigrinya": "IMPORTANT: Respond entirely in Tigrinya (ትግርኛ).",
            "chinese": "IMPORTANT: Respond entirely in Chinese (中文).",
        }
        lang_instruction = f"\nLANGUAGE: {lang_map.get(user_language.lower(), '')}"

    context_str = f"""You are the Agéiz Strategy AI, an expert revenue management consultant advising the management team and staff of Ethiopian hotels and resorts.
You speak directly to hotel managers, revenue officers, and operational staff — NOT to guests or customers.
Your role is to help them make data-driven pricing, yield, and operational decisions.

Hotel You Are Advising: {profile.get('hotel_name', 'Unknown Hotel')}
Positioning: {profile.get('brand_positioning', 'Standard')}
Objectives: {profile.get('business_objectives', 'Revenue growth and high occupancy')}
Target Segments: {profile.get('target_guest_segments', 'Local and Diaspora')}
Current Location Focus: {location if location else 'All'}
User Language: {user_language}

Latest Market Intelligence:
{json.dumps(signals, indent=2)}

Guidelines:
- Address the user as a hotel professional (manager, revenue officer, operations staff).
- Never greet the user as if they are a hotel guest — they are the staff running the hotel.
- Provide specific, actionable advice based on the signals.
- Use Ethiopian cultural context (holidays, fasting, diaspora trends).
- If the user asks for information you don't have (like competitor rates today, general news outside your cache, or technical tourism stats), you should explicitly say you are 'searching' and then you will be provided with search results.
{lang_instruction}
"""

    # 3. Decision: Do we need search? (Simple heuristic for now)
    search_triggers = ["search", "competitor", "latest", "news", "stats", "price of", "weather next month"]
    needs_search = any(word in user_message.lower() for word in search_triggers)

    search_results = ""
    if needs_search:
        search_results = await call_poe_search(user_message)

    # 4. Final Call to Groq
    messages: List[Dict[str, str]] = [{"role": "system", "content": context_str}]

    # Add history
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})

    # Add search results if any
    if search_results:
        messages.append({"role": "system", "content": f"EXTERNAL SEARCH RESULTS FROM POE WEB-SEARCH:\n{search_results}"})

    # Add current message
    messages.append({"role": "user", "content": user_message})

    try:
        completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.7,
            max_tokens=1024
        )
        ai_response = completion.choices[0].message.content

        # 5. Save history
        save_chat_message(hotel_id, user_id, location, "user", user_message)
        save_chat_message(hotel_id, user_id, location, "assistant", ai_response)

        # 6. Translate only if AI didn't follow language instruction (fallback)
        if user_language and user_language.lower() != "english":
            # Check if response is still in English (AI might not have followed instruction)
            # Simple heuristic: if first 50 chars are ASCII, it's likely English
            first_chars = ai_response[:50]
            is_likely_english = all(ord(c) < 128 for c in first_chars if c.isalpha())
            if is_likely_english:
                print(f"[chat_agent] AI responded in English, translating to {user_language}")
                translated = translate_text(ai_response, user_language)
                if translated != ai_response:
                    ai_response = translated
                    # Re-save with translated response
                    save_chat_message(hotel_id, user_id, location, "assistant", ai_response)

        return ai_response
    except Exception as e:
        print(f"[chat_agent] Groq call failed: {e}")
        error_msg = "I'm having trouble processing your request right now. Please try again in a moment."
        if user_language and user_language.lower() != "english":
            error_msg = translate_text(error_msg, user_language)
        return error_msg
