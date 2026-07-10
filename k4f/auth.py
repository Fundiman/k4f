import json
from typing import Optional, Tuple


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
