import time
import functools

def with_retry(max_retries=3, backoff_factor=2):
    """
    Decorator that retries a function on failure with exponential backoff.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            last_error = None
            while retries < max_retries:
                try:
                    result = func(*args, **kwargs)
                    # Some fetchers return {"error": "..."} instead of raising
                    if isinstance(result, dict) and "error" in result:
                        if retries + 1 == max_retries:
                            return result
                        raise Exception(result["error"])
                    return result
                except Exception as e:
                    retries += 1
                    last_error = e
                    if retries == max_retries:
                        print(f"[retry] Final failure for {func.__name__}: {e}")
                        return {"error": str(e)}
                    sleep_time = backoff_factor ** retries
                    print(f"[retry] {func.__name__} failed ({e}). Retrying in {sleep_time}s... ({retries}/{max_retries})")
                    time.sleep(sleep_time)
            return {"error": str(last_error) if last_error else "Max retries exceeded"}
        return wrapper
    return decorator
