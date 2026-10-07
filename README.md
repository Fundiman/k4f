# k4f (kimi4free)

![Python](https://img.shields.io/badge/python-3.10+-blue.svg)
![Async](https://img.shields.io/badge/async-supported-green.svg)
![License](https://img.shields.io/badge/license-Apache2.0-lightgrey.svg)
![Status](https://img.shields.io/badge/status-experimental-orange.svg)

A lightweight async Python client for interacting with Kimi (Moonshot AI) chat infrastructure through the connect protocol. This **free Kimi API** wrapper provides a simple, programmatic way to use **Kimi chat** without a browser — perfect for building **Kimi API** integrations, automations, and tools.

> [!WARNING]
> This project is built around reverse-engineered infrastructure behavior. Use responsibly and be aware that API changes may break functionality without notice.

> [!NOTE]
> Despite the similar naming convention, **kimi4free** is an independent project built from the ground up — not a fork of [SertraFurr/kimi4free](https://github.com/SertraFurr/kimi4free) or any other existing wrapper. The naming similarity is purely stylistic.

---

## overview

**kimi4free** provides:

* async **Kimi API** client with full streaming support
* streaming response parsing via the connect protocol (unary frames)
* file upload with parse progress tracking
* session-based conversation handling with chat management
* refresh token auth with **automatic access-token renewal** (or bring your own access token)
* available model listing (`get_available_models`)
* mid-stream cancellation (`stop_stream`)
* JWT token decoding for automatic credential extraction
* browser cookie extraction for seamless authentication
* JSON cookie/token storage and retrieval
* structured error handling with specific exception types

---

## installation

### clone repo

> [!CAUTION]
> Do not cd (change directory) into it, you'll import it like k4f.api!

```bash
git clone https://github.com/fundiman/k4f
```

### install dependencies

```bash
pip install -r requirements.txt
```

**Dependencies:**

* httpx >= 0.28.0
* httpx-sse >= 0.4.0

> [!NOTE]
> Optional: `browser_cookie3` for automatic browser cookie extraction.

---

## quick start

> [!IMPORTANT]
> Before using the API client, you need a credential from Kimi: either a short-lived **access token** or a long-lived **refresh token** (recommended — k4f renews the access token for you). See [authentication](#authentication).

```python
import asyncio
from k4f import KimiAPI

async def main():
    api = KimiAPI(auth_token="your-kimi-auth-jwt-here")
    # or, so expired access tokens are renewed automatically:
    # api = KimiAPI(refresh_token="your-refresh-token-here")
    
    async for chunk in api.chat_stream(content="Hello Kimi!"):
        print(chunk["content"], end="", flush=True)
    
    await api.close()

asyncio.run(main())
```

---

## authentication

k4f accepts either credential — both work on their own:

| credential | lifetime | where it lives |
|---|---|---|
| **access token** (`auth_token=`) | ~15 minutes | cookie `kimi-auth`, localStorage `access_token`, `authorization: Bearer ...` header |
| **refresh token** (`refresh_token=`) | ~90 days | localStorage `refresh_token` |

### getting the tokens (browser devtools)

> [!NOTE]
> This is the one manual step — everything after it is automatic.

1. log in to [kimi.com](https://www.kimi.com) (or kimi.ai)
2. press `F12` → **Application** tab → **Local Storage** → `https://www.kimi.com`
3. copy the value of `refresh_token` (and optionally `access_token`)

Alternative: **Network** tab → any `/apiv2/...` request → request headers → copy the `authorization: Bearer ...` value (that's the access token).

### using a refresh token (recommended)

```python
from k4f import KimiAPI

api = KimiAPI(refresh_token="paste-refresh-token-here")
# no access token needed — k4f fetches one on first use
# and renews it automatically whenever it is about to expire
```

If the server rejects a request with `401`, k4f refreshes once and retries transparently. If the refresh token itself is rejected, `AuthError` is raised.

> [!IMPORTANT]
> Kimi **rotates** refresh tokens: every exchange returns a new one. Persist the current value (also exposed as `api.refresh_token`) after refreshing:

```python
from k4f.auth import save_tokens, load_tokens

tokens = load_tokens("tokens.json") or {}
api = KimiAPI(
    auth_token=tokens.get("auth_token", ""),
    refresh_token=tokens.get("refresh_token", ""),
)

# ... use api ...

save_tokens("tokens.json", api.auth_token, api.refresh_token)
```

### using an access token only

```python
api = KimiAPI(auth_token="paste-access-token-here")
```

Works until the token expires (~15 minutes). Afterwards `AuthError` is raised telling you to supply a refresh token instead.

> [!NOTE]
> Refresh requests echo your `x-msh-device-id` / `x-msh-session-id` headers so device identity survives rotation. If your refresh token no longer carries them, pass `device_id=` / `session_id=` explicitly (grab both from any devtools request header) — once provided they stick for every later refresh.

---

## project structure

```
k4f/
│
├── k4f/                     # kimi4free package
│   ├── __init__.py          # exports KimiAPI, errors
│   ├── api.py               # async Kimi API client
│   ├── models.py            # data models (ChatRequest, Message, etc.)
│   ├── connect.py           # connect protocol encoder/decoder
│   └── auth.py              # cookie/token extraction & storage
│
├── example.py               # usage examples
├── requirements.txt         # dependencies
└── README.md
```

---

## usage

### initialize client

```python
from k4f import KimiAPI

# access token only
api = KimiAPI(auth_token="your_token")

# or refresh token (auto-renews the access token)
api = KimiAPI(refresh_token="your_refresh_token")
```

> [!NOTE]
> See [authentication](#authentication) for how to grab the tokens from your browser and how rotation works.

---

### streaming chat

```python
async for chunk in api.chat_stream(
    content="Tell me about Python",
):
    # chunk is a dictionary with 'content' and 'full_content' keys
    print(chunk["content"], end="", flush=True)
```

> [!TIP]
> Use `chat_stream()` for real-time streaming output, or `chat()` for raw text chunks only.

---

### chat with file context

```python
# Upload a file first
upload = await api.upload_file("document.pdf")
file_id = upload["file"]["id"]

# Wait for parsing to complete
while True:
    progs = await api.get_file_parse_progress([file_id])
    status = progs[0]["status"]
    if status in ("PROCESS_STATUS_SUCCESS", "PROCESS_STATUS_FAILED"):
        break
    await asyncio.sleep(0.5)

# Chat with file as context
async for chunk in api.chat_stream(
    content="Summarize this document",
    file_ids=[file_id],
):
    print(chunk["content"], end="", flush=True)
```

> [!NOTE]
> Files are uploaded to Kimi's servers and parsed asynchronously. The `get_file_parse_progress` method tracks parsing status.

---

### continue existing chat

```python
# chat_id is automatically tracked from the last chat_stream call
chat_id = api.last_chat_id

# Send follow-up message
async for chunk in api.chat_stream(
    content="Tell me more about that",
    chat_id=chat_id,
):
    print(chunk["content"], end="", flush=True)
```

---

### get chat info

```python
chat_info = await api.get_chat(chat_id)
print(chat_info)
```

---

### rename chat

```python
result = await api.rename_chat(chat_id, "New Chat Name")
print(result)
```

---

### delete chat

```python
result = await api.delete_chat(chat_id)
print(result)
```

---

### stop stream

Stop an active response mid-generation. The `chat_id` and `message_id` are automatically tracked from the last `chat_stream` call:

```python
result = await api.stop_stream()
print(result)
```

A specific `chat_id` and `message_id` can also be passed directly:

```python
result = await api.stop_stream(
    chat_id="chat_id_here",
    message_id="message_id_here",
)
```

> [!NOTE]
> The response is an empty dict (`{}`). Kimi has **no resume endpoint** — a stopped stream is finished for good; to continue the conversation, send a follow-up message with `chat_id=api.last_chat_id`.

---

### list available models

```python
data = await api.get_available_models()

for model in data["availableModels"]:
    print(f"{model['key']}: {model['displayName']} — {model['description']}")

print(data["defaultChatModel"])  # e.g. "k2d6-chat"
```

> [!NOTE]
> The raw response also contains `defaultScenario` and `defaultAgentModel`. Model entries include `reasoningEffortOptions` and `contextLengthOptions` when applicable.

---

### list feeds (conversations)

```python
items = await api.list_feeds(page_size=20)
for item in items:
    chat = item["chat"]
    print(f"{chat['name']} ({chat['id']})")
```

> [!NOTE]
> By default, `list_feeds` returns both chats and tasks. Pass `filter_types=["FEED_TYPE_CHAT"]` to get only chats.

---

### pin chat

```python
result = await api.pin_chat(chat_id)
print(result)
```

---

### unpin chat

```python
result = await api.unpin_chat(chat_id)
print(result)
```

---

### list pins

```python
pins = await api.list_pins(page_size=50)
for pin in pins:
    chat = pin["chat"]
    print(f"{chat['name']} ({chat['id']})")
```

---

### list messages

```python
messages = await api.list_messages(chat_id, page_size=50)
for msg in messages:
    print(msg)
```

---

### cookie extraction

```python
from k4f.auth import extract_from_browser, load_from_json

# Extract from browser (requires browser_cookie3)
auth_data = extract_from_browser("chrome")

# Or load from JSON file
auth_data = load_from_json("cookies.json")

# Initialize with extracted cookies
api = KimiAPI(
    auth_token=auth_data["auth_token"],
    cookies=auth_data["cookies"],
)
```

---

### save cookies

```python
from k4f.auth import save_to_json

save_to_json("cookies.json", api.cookies)
```

---

### cleanup

> [!IMPORTANT]
> Always close the session when done to free resources:

```python
await api.close()
```

---

## architecture

The system is composed of three core layers:

### 1. API layer (`api.py`)

Async client for streaming chat interaction with:
- connect protocol framing (unary encode/decode)
- streaming response parsing for text extraction
- file upload with progress tracking
- chat management and message listing
- automatic access-token renewal (refresh token exchange, one 401 retry)
- model catalogue (`get_available_models`) and stream cancellation (`stop_stream`)
- automatic credential extraction from JWT

### 2. Connect layer (`connect.py`)

Low-level protocol handler for Kimi's connect protocol:
- unary frame encoding with flag bytes
- streamed frame reader for async byte streams
- binary protocol parsing for real-time data

### 3. Auth layer (`auth.py`)

Authentication and credential management:
- refresh token exchange against Kimi's auth service (rotating tokens)
- access/refresh token persistence (`load_tokens` / `save_tokens`)
- browser cookie extraction (Chrome, Firefox, etc.)
- JSON cookie storage and retrieval
- automatic `kimi-auth` token handling

---

## async design notes

The system is designed around non-blocking execution:

* network I/O uses async HTTP sessions from httpx
* streaming responses use async generators that yield control between chunks
* connect protocol frames are parsed incrementally from byte streams
* file uploads are handled asynchronously
* credential extraction runs without blocking the event loop

---

## error handling

The client provides specific exceptions for different failure modes:

```python
from k4f import KimiError, AuthError, APIError

try:
    await api.chat_stream(content="Hello")
except AuthError as e:
    # expired access token (no refresh_token configured),
    # rejected refresh token, or any 401/403 response
    print(f"Auth failed ({e.status_code}): {e}")
except APIError as e:
    print(f"API error {e.status_code}: {e}")
except KimiError as e:
    print(f"General Kimi error: {e}")
```

> [!NOTE]
> `AuthError` subclasses `APIError`, so catching `APIError` also catches auth failures — put `except AuthError` first.

---

## example: full flow with file upload

```python
import asyncio
from k4f import KimiAPI

async def main():
    api = KimiAPI(auth_token="your_token_here")

    # Upload a file
    print("Uploading file...")
    upload = await api.upload_file("report.pdf")
    file_id = upload["file"]["id"]
    print(f"File ID: {file_id}")

    # Wait for parsing to complete
    print("Waiting for parse...")
    while True:
        progs = await api.get_file_parse_progress([file_id])
        status = progs[0]["status"]
        print(f"  status: {status}")
        if status in ("PROCESS_STATUS_SUCCESS", "PROCESS_STATUS_FAILED"):
            break
        await asyncio.sleep(0.5)

    # Chat with file context
    print("\nChat with file context:")
    async for chunk in api.chat_stream(
        content="Analyze this file and summarize key points",
        file_ids=[file_id],
    ):
        print(chunk["content"], end="", flush=True)
    
    print(f"\n(chat_id: {api.last_chat_id})")

    # Cleanup
    await api.close()

asyncio.run(main())
```

---

## notes

> [!CAUTION]
> This project is experimental and based on reverse-engineered behavior of Kimi's infrastructure. Kimi/Moonshot AI may modify their API at any time, which could break this client — while efforts will be made to address issues, full compatibility cannot be guaranteed. Use of this client may also violate Kimi's terms of service and could result in account suspension or banning. Please use at your own risk.

> [!NOTE]
> The connect protocol uses binary framing with flag bytes and length prefixes. The client automatically handles frame decoding and text extraction from the streamed response.

---

## related projects

* [dskpp](https://github.com/fundiman/dskpp) - Similar async API client for DeepSeek chat

---

## license

This project is licensed under [Apache 2.0](LICENSE).
