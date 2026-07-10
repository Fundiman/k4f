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
* JWT token decoding for automatic credential extraction
* browser cookie extraction for seamless authentication
* JSON cookie storage and retrieval
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
> Before using the API client, you need a valid auth token from Kimi.

```python
import asyncio
from k4f import KimiAPI

async def main():
    api = KimiAPI(auth_token="your-kimi-auth-jwt-here")
    
    async for chunk in api.chat_stream(content="Hello Kimi!"):
        print(chunk["content"], end="", flush=True)
    
    await api.close()

asyncio.run(main())
```

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
│   └── auth.py              # cookie extraction & storage
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

api = KimiAPI(auth_token="your_token")
```

> [!NOTE]
> The auth token is obtained after logging into Kimi. Extract it from browser developer tools or use the auth helpers to extract from cookies.

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
- automatic credential extraction from JWT

### 2. Connect layer (`connect.py`)

Low-level protocol handler for Kimi's connect protocol:
- unary frame encoding with flag bytes
- streamed frame reader for async byte streams
- binary protocol parsing for real-time data

### 3. Auth layer (`auth.py`)

Authentication and credential management:
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
except AuthError:
    print("Invalid or expired auth token")
except APIError as e:
    print(f"API error {e.status_code}: {e}")
except KimiError as e:
    print(f"General Kimi error: {e}")
```

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
