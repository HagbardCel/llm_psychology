"""
Cache utilities for HTTP response caching.
"""
from datetime import datetime, timedelta
from quart import Response


def add_cache_headers(
    response: Response,
    cache_type: str = "private",
    max_age: int = 300,
    must_revalidate: bool = False
) -> Response:
    """
    Add cache control headers to a response.

    Args:
        response: The Quart response object
        cache_type: Either 'private' (default) or 'public'
        max_age: Cache duration in seconds (default 300 = 5 minutes)
        must_revalidate: If True, adds must-revalidate directive

    Returns:
        Response with cache headers added
    """
    # Build cache-control directive
    directives = [cache_type, f"max-age={max_age}"]
    if must_revalidate:
        directives.append("must-revalidate")

    response.headers["Cache-Control"] = ", ".join(directives)

    # Add Expires header for HTTP/1.0 compatibility
    expires_time = datetime.utcnow() + timedelta(seconds=max_age)
    response.headers["Expires"] = expires_time.strftime("%a, %d %b %Y %H:%M:%S GMT")

    # Add ETag for conditional requests (using Last-Modified as base)
    if "Last-Modified" not in response.headers:
        response.headers["Last-Modified"] = datetime.utcnow().strftime(
            "%a, %d %b %Y %H:%M:%S GMT"
        )

    return response


def no_cache(response: Response) -> Response:
    """
    Add no-cache headers to prevent caching.

    Args:
        response: The Quart response object

    Returns:
        Response with no-cache headers added
    """
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# Cache presets for common use cases
CACHE_PRESETS = {
    "static_long": {"cache_type": "public", "max_age": 3600},  # 1 hour
    "static_short": {"cache_type": "public", "max_age": 300},  # 5 minutes
    "user_data": {"cache_type": "private", "max_age": 60},  # 1 minute
    "dynamic": {"cache_type": "private", "max_age": 0},  # No cache
}
