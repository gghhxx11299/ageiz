import httpx
import json
import time
import traceback
from decorators import with_retry


def _resolve_path(data, path):
    """Resolve a dot-notation path into nested data.
    Examples: 'data.results[0].price', 'body.items[*].name'
    """
    if not path:
        return data
    parts = path.replace('[*]', '').replace('[', '.').replace(']', '').split('.')
    parts = [p for p in parts if p]
    for part in parts:
        if data is None:
            return None
        if isinstance(data, dict):
            data = data.get(part)
        elif isinstance(data, list):
            try:
                data = data[int(part)]
            except (ValueError, IndexError, TypeError):
                return None
        else:
            return None
    return data


@with_retry(max_retries=2, backoff_factor=3)
def _fetch_single_source(config):
    """Fetch one custom signal source. Returns dict with data or error."""
    name = config.get("name", "unknown")
    url = config.get("url", "").strip()
    if not url:
        return {"error": "No URL configured", "name": name}

    # Validate URL format
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
        config["url"] = url

    # Build headers
    headers = {}
    if config.get("headers"):
        try:
            headers.update(json.loads(config["headers"]))
        except json.JSONDecodeError as e:
            return {"error": f"Invalid JSON in headers: {str(e)}", "name": name}

    # Inject API key if provided and not already in headers
    api_key = config.get("api_key", "")
    api_key_label = config.get("api_key_label", "Authorization")
    if api_key:
        existing_keys = {k.lower() for k in headers}
        if api_key_label.lower() not in existing_keys:
            headers[api_key_label] = f"Bearer {api_key}"

    # Determine method and body
    method = config.get("method", "GET").upper()
    request_body = None
    if config.get("body"):
        try:
            request_body = json.loads(config["body"])
        except json.JSONDecodeError as e:
            return {"error": f"Invalid JSON in request body: {str(e)}", "name": name}

    # Make the request
    start = time.time()
    try:
        if method == "POST":
            resp = httpx.post(url, headers=headers, json=request_body, timeout=15, follow_redirects=True)
        else:
            resp = httpx.get(url, headers=headers, timeout=15, follow_redirects=True)

        resp.raise_for_status()
        elapsed_ms = round((time.time() - start) * 1000)

        # Parse response
        content_type = resp.headers.get("content-type", "")
        if "application/json" in content_type:
            raw = resp.json()
        else:
            text_preview = resp.text[:500] if resp.text else ""
            raw = {"text": text_preview, "note": "Non-JSON response, showing first 500 chars"}

        # Extract data using response_path if specified
        response_path = config.get("response_path", "")
        extracted = _resolve_path(raw, response_path)

        print(f"[custom] ✅ {name}: fetched in {elapsed_ms}ms, status={resp.status_code}")

        return {
            "name": name,
            "description": config.get("description", ""),
            "data": extracted if extracted is not None else raw,
            "fetch_time_ms": elapsed_ms,
            "status_code": resp.status_code
        }

    except httpx.HTTPStatusError as e:
        elapsed_ms = round((time.time() - start) * 1000)
        error_detail = f"HTTP {e.response.status_code}: {e.response.text[:300]}"
        print(f"[custom] ❌ {name}: {error_detail} ({elapsed_ms}ms)")
        return {"error": error_detail, "name": name, "fetch_time_ms": elapsed_ms}

    except httpx.ConnectTimeout:
        elapsed_ms = round((time.time() - start) * 1000)
        print(f"[custom] ❌ {name}: connection timeout after {elapsed_ms}ms")
        return {"error": f"Connection timed out after {elapsed_ms}ms. Check if the URL is reachable.", "name": name, "fetch_time_ms": elapsed_ms}

    except httpx.ReadTimeout:
        elapsed_ms = round((time.time() - start) * 1000)
        print(f"[custom] ❌ {name}: read timeout after {elapsed_ms}ms")
        return {"error": f"Server did not respond within 15s. The endpoint may be slow.", "name": name, "fetch_time_ms": elapsed_ms}

    except httpx.ConnectError as e:
        elapsed_ms = round((time.time() - start) * 1000)
        print(f"[custom] ❌ {name}: connection error — {e}")
        return {"error": f"Cannot connect to {url}. Check URL and network.", "name": name, "fetch_time_ms": elapsed_ms}

    except Exception as e:
        elapsed_ms = round((time.time() - start) * 1000)
        print(f"[custom] ❌ {name}: unexpected error — {e}")
        print(traceback.format_exc())
        return {"error": f"Unexpected error: {str(e)[:200]}", "name": name, "fetch_time_ms": elapsed_ms}


def fetch_custom_signals(configs: list) -> list:
    """Fetch all custom signal sources sequentially.
    Each source is isolated — one failure does not affect others.
    Returns list of results in same order as configs.
    """
    results = []
    for idx, config in enumerate(configs):
        if not config.get("enabled", True):
            print(f"[custom] ⏭ Skipping disabled source: {config.get('name', '?')}")
            results.append({
                "error": "Source disabled",
                "name": config.get("name", "unknown"),
                "description": config.get("description", "")
            })
            continue

        try:
            result = _fetch_single_source(config)
            results.append(result)
        except Exception as e:
            print(f"[custom] ❌ {config.get('name', '?')} completely crashed: {e}")
            print(traceback.format_exc())
            results.append({
                "error": f"Fetcher crashed: {str(e)[:200]}",
                "name": config.get("name", "unknown"),
                "description": config.get("description", "")
            })

        # Small delay between requests to avoid rate limiting
        time.sleep(1)
    return results
