import json
import os
import httpx
import time
import hashlib

# Hugging Face API for NLLB-200
HF_TOKEN = os.getenv("HUGGINGFACE_TOKEN", "")
API_URL = "https://router.huggingface.co/hf-inference/models/facebook/nllb-200-distilled-600M"

# Language Mapping for NLLB-200 (Flores-200 codes)
NLLB_CODES = {
    "english": "eng_Latn",
    "amharic": "amh_Ethi",
    "oromoo": "gaz_Latn",
    "tigrinya": "tir_Ethi",
    "chinese": "zho_Hans"
}

# In-memory cache with TTL (time-based expiration)
_translation_cache = {}
CACHE_TTL = 3600  # 1 hour cache lifetime

def _get_cache_key(text: str, target_lang: str) -> str:
    """Create a unique cache key using hash for efficiency."""
    raw = f"{text}_{target_lang}"
    return hashlib.md5(raw.encode()).hexdigest()

def _get_cached(cache_key: str) -> str | None:
    """Get cached translation if not expired."""
    if cache_key in _translation_cache:
        entry = _translation_cache[cache_key]
        if time.time() - entry["timestamp"] < CACHE_TTL:
            return entry["translation"]
        else:
            del _translation_cache[cache_key]
    return None

def _set_cache(cache_key: str, translation: str):
    """Store translation in cache with timestamp."""
    _translation_cache[cache_key] = {
        "translation": translation,
        "timestamp": time.time()
    }

def translate_text(text: str, target_lang: str) -> str:
    """Translate text to target language with caching."""
    if not target_lang or target_lang.lower() == "english":
        return text

    target_code = NLLB_CODES.get(target_lang.lower(), "eng_Latn")
    if target_code == "eng_Latn":
        return text

    # Check cache first
    cache_key = _get_cache_key(text, target_lang)
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    headers = {}
    if HF_TOKEN:
        headers["Authorization"] = f"Bearer {HF_TOKEN}"

    try:
        payload = {
            "inputs": text,
            "parameters": {"src_lang": "eng_Latn", "tgt_lang": target_code}
        }

        # Retry logic for API loading (max 3 attempts with backoff)
        for attempt in range(3):
            response = httpx.post(API_URL, headers=headers, json=payload, timeout=20.0)
            result = response.json()

            if isinstance(result, list) and len(result) > 0:
                translated = result[0].get("translation_text", text)
                _set_cache(cache_key, translated)
                return translated
            elif "error" in result and "loading" in result["error"].lower():
                wait_time = 2 * (attempt + 1)  # 2s, 4s, 6s
                time.sleep(wait_time)
                continue
            else:
                print(f"[translator] API Error: {result}")
                return text

        return text
    except Exception as e:
        print(f"[translator] Exception: {e}")
        return text

def translate_batch(texts: list[str], target_lang: str) -> list[str]:
    """Translate multiple texts efficiently (batch optimization)."""
    if not target_lang or target_lang.lower() == "english":
        return texts

    target_code = NLLB_CODES.get(target_lang.lower(), "eng_Latn")
    if target_code == "eng_Latn":
        return texts

    # Check cache for all items first
    results = []
    to_translate = []
    indices_to_translate = []

    for i, text in enumerate(texts):
        cache_key = _get_cache_key(text, target_lang)
        cached = _get_cached(cache_key)
        if cached is not None:
            results.append(cached)
        else:
            to_translate.append(text)
            indices_to_translate.append(i)
            results.append(None)  # placeholder

    # If all cached, return early
    if not to_translate:
        return results

    # Translate uncached items
    headers = {}
    if HF_TOKEN:
        headers["Authorization"] = f"Bearer {HF_TOKEN}"

    for idx, text in enumerate(to_translate):
        try:
            payload = {
                "inputs": text,
                "parameters": {"src_lang": "eng_Latn", "tgt_lang": target_code}
            }

            for attempt in range(3):
                response = httpx.post(API_URL, headers=headers, json=payload, timeout=20.0)
                result = response.json()

                if isinstance(result, list) and len(result) > 0:
                    translated = result[0].get("translation_text", text)
                    cache_key = _get_cache_key(text, target_lang)
                    _set_cache(cache_key, translated)
                    results[indices_to_translate[idx]] = translated
                    break
                elif "error" in result and "loading" in result["error"].lower():
                    time.sleep(2 * (attempt + 1))
                    continue
                else:
                    print(f"[translator] API Error: {result}")
                    results[indices_to_translate[idx]] = text
                    break
            else:
                results[indices_to_translate[idx]] = text
        except Exception as e:
            print(f"[translator] Exception: {e}")
            results[indices_to_translate[idx]] = text

    return results

def translate_dict(data: dict, target_lang: str) -> dict:
    """Recursively translate all string values in a dictionary."""
    if not target_lang or target_lang.lower() == "english":
        return data

    if isinstance(data, str):
        return translate_text(data, target_lang)

    if isinstance(data, list):
        return [translate_dict(i, target_lang) for i in data]

    if isinstance(data, dict):
        new_data = {}
        for k, v in data.items():
            new_data[k] = translate_dict(v, target_lang)
        return new_data

    return data

def get_cache_stats() -> dict:
    """Return cache statistics for monitoring."""
    now = time.time()
    valid = sum(1 for v in _translation_cache.values() if now - v["timestamp"] < CACHE_TTL)
    return {
        "total_entries": len(_translation_cache),
        "valid_entries": valid,
        "cache_size_kb": len(json.dumps(_translation_cache)) / 1024
    }
