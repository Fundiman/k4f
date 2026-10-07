import json
from typing import Optional


def extract_from_cookies(cookie_dict: dict) -> dict:
    auth_token = cookie_dict.get("kimi-auth", "")
    return {
        "auth_token": auth_token,
        "cookies": cookie_dict,
    }


def extract_from_browser(browser: str = "chrome") -> Optional[dict]:
    try:
        import browser_cookie3
    except ImportError:
        return None

    try:
        cj = getattr(browser_cookie3, browser)(domain_name="kimi.com")
    except Exception:
        return None

    cookies = {}
    for c in cj:
        if c.domain and "kimi.com" in c.domain:
            cookies[c.name] = c.value

    if not cookies.get("kimi-auth"):
        return None

    return extract_from_cookies(cookies)


def load_from_json(path: str) -> Optional[dict]:
    try:
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, dict):
            return extract_from_cookies(data)
        return None
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_to_json(path: str, cookies: dict):
    with open(path, "w") as f:
        json.dump(cookies, f, indent=2)


def load_tokens(path: str) -> Optional[dict]:
    """Load an access/refresh token pair saved by :func:`save_tokens`.

    Also accepts a plain cookie dump (``{"kimi-auth": ...}``) so it works
    with files written by :func:`save_to_json`.
    """
    try:
        with open(path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None

    auth_token = data.get("auth_token") or data.get("access_token") or data.get("kimi-auth", "")
    refresh_token = data.get("refresh_token", "")
    cookies = data.get("cookies") or {}
    if not cookies and auth_token:
        cookies = {"kimi-auth": auth_token}
    if not auth_token and not refresh_token:
        return None
    return {
        "auth_token": auth_token,
        "refresh_token": refresh_token,
        "cookies": cookies,
    }


def save_tokens(
    path: str,
    auth_token: str = "",
    refresh_token: str = "",
    cookies: Optional[dict] = None,
):
    """Persist a token pair; call again after ``refresh_tokens()`` (Kimi rotates refresh tokens)."""
    data = {"access_token": auth_token, "refresh_token": refresh_token}
    if cookies:
        data["cookies"] = cookies
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
