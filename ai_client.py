import os
import time
import json
import re
from typing import Dict, Any, Optional
from groq import Groq
import httpx
from dotenv import load_dotenv

load_dotenv()

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

_consecutive_failures = 0
_fallback_until = 0.0

GROQ_HEAVY_MODEL = "llama-3.3-70b-versatile"
GROQ_LIGHT_MODEL = "llama-3.1-8b-instant"
OPENROUTER_MODEL = "meta-llama/llama-3-70b-instruct"

# Constants for retry and fallback logic
MAX_RETRIES = 2
RETRY_DELAY_SECONDS = 5
FALLBACK_DURATION_SECONDS = 180
FAILURE_THRESHOLD = 2
OPENROUTER_TIMEOUT_SECONDS = 30
HARD_TIMEOUT_SECONDS = 45

def _clean_json_response(text: str) -> str:
    text = text.strip()
    text = re.sub(r'^```json\s*', '', text)
    text = re.sub(r'^```\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    return text.strip()

def _call_groq(prompt: str, use_heavy_model: bool) -> str:
    model = GROQ_HEAVY_MODEL if use_heavy_model else GROQ_LIGHT_MODEL
    response = groq_client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=1024
    )
    return response.choices[0].message.content

def _call_openrouter(prompt: str) -> str:
    headers = {
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://ageiz.onrender.com",
        "X-Title": "Ageiz"
    }
    body = {
        "model": OPENROUTER_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 1024
    }
    response = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        json=body,
        headers=headers,
        timeout=OPENROUTER_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

def call_ai(prompt: str, use_heavy_model: bool = False) -> str:
    global _consecutive_failures, _fallback_until

    start = time.time()

    if time.time() < _fallback_until:
        print(f"[ai_client] In fallback mode. Using OpenRouter.")
        return _call_openrouter(prompt)

    for attempt in range(MAX_RETRIES):
        if time.time() - start > HARD_TIMEOUT_SECONDS:
            print("[ai_client] Hard timeout reached. Switching to OpenRouter.")
            _fallback_until = time.time() + FALLBACK_DURATION_SECONDS
            return _call_openrouter(prompt)

        try:
            result = _call_groq(prompt, use_heavy_model)
            _consecutive_failures = 0
            return result
        except Exception as e:
            _consecutive_failures += 1
            print(f"[ai_client] Groq failure {_consecutive_failures}: {e}")
            if _consecutive_failures >= FAILURE_THRESHOLD:
                _fallback_until = time.time() + FALLBACK_DURATION_SECONDS
                print(f"[ai_client] {FAILURE_THRESHOLD} consecutive Groq failures. Switching to OpenRouter for {FALLBACK_DURATION_SECONDS//60} minutes.")
                return _call_openrouter(prompt)
            if attempt < MAX_RETRIES - 1:
                wait = min(RETRY_DELAY_SECONDS, HARD_TIMEOUT_SECONDS - (time.time() - start))
                if wait > 0:
                    time.sleep(wait)

    print("[ai_client] All Groq retries failed. Switching to OpenRouter.")
    _fallback_until = time.time() + FALLBACK_DURATION_SECONDS
    return _call_openrouter(prompt)

def call_ai_for_json(prompt: str, use_heavy_model: bool = False) -> Dict[str, Any]:
    for attempt in range(2):
        try:
            raw = call_ai(prompt, use_heavy_model)
            cleaned = _clean_json_response(raw)
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            print(f"[ai_client] JSON parse failed attempt {attempt + 1}: {e}")
            if attempt == 0:
                time.sleep(5)
                continue
            raise ValueError(f"AI returned invalid JSON after 2 attempts. Raw response: {raw}")

