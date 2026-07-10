import json, base64
from typing import AsyncGenerator, Optional, Dict, Any, List
import httpx

from .connect import encode_unary, read_streamed_frames
from .models import ChatRequest, Message, TextBlock, ChatOptions


BASE_URL = "https://www.kimi.com"
FILES_BASE = "https://www.kimi.com/apiv2-files"
CHAT_ENDPOINT = "/apiv2/kimi.gateway.chat.v1.ChatService/Chat"
GET_CHAT_ENDPOINT = "/apiv2/kimi.gateway.chat.v1.ChatService/GetChat"
LIST_MSGS_ENDPOINT = "/apiv2/kimi.gateway.chat.v1.ChatService/ListMessages"
FILE_UPLOAD_ENDPOINT = "/apiv2-files/file/upload"
FILE_PARSE_PROGRESS_ENDPOINT = "/apiv2-files/kimi.gateway.file.v1.FileService/GetFileParseProgress"


class KimiError(Exception):
    pass


class AuthError(KimiError):
    pass


class APIError(KimiError):
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def _decode_jwt(token: str) -> dict:
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    payload = parts[1]
    padded = payload + "=" * (4 - len(payload) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        return {}


def _extract_text_from_frame(obj: dict) -> Optional[str]:
    op = obj.get("op")
    mask = obj.get("mask", "")
    block = obj.get("block") or {}

    if op == "set" and mask == "block.text":
        text = block.get("text", {})
        content = text.get("content", "")
        return content if content else None

    if op == "append" and mask == "block.text.content":
        text = block.get("text", {})
        content = text.get("content", "")
        return content if content else None

    return None


def _is_done(obj: dict) -> bool:
    return "done" in obj


class KimiAPI:
    def __init__(
        self,
        auth_token: str,
        cookies: Optional[dict] = None,
        device_id: str = "",
        session_id: str = "",
        traffic_id: str = "",
        shield_data: str = "",
        language: str = "en-US",
    ):
        self.auth_token = auth_token
        self.cookies = cookies or {}
        if "kimi-auth" not in self.cookies:
            self.cookies["kimi-auth"] = auth_token

        jwt = _decode_jwt(auth_token)
        self.device_id = device_id or jwt.get("device_id", "")
        self.session_id = session_id or jwt.get("ssid", "")
        self.traffic_id = traffic_id or jwt.get("sub", "")
        self.shield_data = shield_data
        self.language = language

        self._last_user_msg: Dict[str, str] = {}
        self.last_chat_id: str = ""

        self.client = httpx.AsyncClient(
            base_url=BASE_URL,
            follow_redirects=True,
        )

    def _base_headers(self, referer: str, content_type: str = "application/connect+json") -> dict:
        lang = f"{self.language},{self.language[:2]};q=0.9"
        headers = {
            "accept": "*/*",
            "accept-language": lang,
            "authorization": f"Bearer {self.auth_token}",
            "cache-control": "no-cache",
            "content-type": content_type,
            "dnt": "1",
            "origin": BASE_URL,
            "pragma": "no-cache",
            "referer": referer,
            "sec-ch-ua": '"Not;A=Brand";v="99", "Chromium";v="130", "Google Chrome";v="130"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            "x-language": self.language,
            "x-msh-platform": "web",
            "x-msh-version": "1.0.0",
        }
        if content_type == "application/connect+json":
            headers["connect-protocol-version"] = "1"
        if self.device_id:
            headers["x-msh-device-id"] = self.device_id
        if self.session_id:
            headers["x-msh-session-id"] = self.session_id
        if self.shield_data:
            headers["x-msh-shield-data"] = self.shield_data
        if self.traffic_id:
            headers["x-traffic-id"] = self.traffic_id
        return headers

    async def _send_connect(self, body: dict, endpoint: str, referer: str) -> AsyncGenerator[bytes, None]:
        framed = encode_unary(json.dumps(body).encode(), flag_byte=0x00)

        async with self.client.stream(
            "POST",
            endpoint,
            headers=self._base_headers(referer),
            cookies=self.cookies,
            content=framed,
        ) as response:
            if response.status_code != 200:
                text = await response.aread()
                raise APIError(
                    f"HTTP {response.status_code}: {text[:500]}",
                    response.status_code,
                )

            async for flag, payload in read_streamed_frames(response.aiter_bytes()):
                if payload:
                    yield payload

    async def _send_json(self, body: dict, endpoint: str, referer: str) -> dict:
        response = await self.client.post(
            endpoint,
            headers=self._base_headers(referer, content_type="application/json"),
            cookies=self.cookies,
            json=body,
        )
        if response.status_code != 200:
            raise APIError(
                f"HTTP {response.status_code}: {response.text[:500]}",
                response.status_code,
            )
        return response.json()

    async def chat(
        self,
        content: str,
        chat_id: str = "",
        parent_id: str = "",
        file_ids: Optional[list[str]] = None,
    ) -> AsyncGenerator[str, None]:
        is_new = not chat_id
        if not is_new and not parent_id:
            parent_id = self._last_user_msg.get(chat_id, "")

        blocks: list = [TextBlock(content=content)]
        if file_ids:
            progs = await self.get_file_parse_progress(file_ids)
            prog_map = {p["fileId"]: p["status"] for p in progs}
            for fid in file_ids:
                status = prog_map.get(fid, "PROCESS_STATUS_SUCCESS")
                blocks.append({"file": {"id": fid, "status": status}})
        msg = Message(role="user", blocks=blocks)
        if parent_id:
            msg.parent_id = parent_id

        referer = f"{BASE_URL}/?chat_enter_method=new_chat" if is_new else f"{BASE_URL}/chat/{chat_id}"
        body = ChatRequest(chat_id=chat_id, message=msg).to_dict()

        resolved_chat = ""
        user_msg_id = ""

        async for payload in self._send_connect(body, CHAT_ENDPOINT, referer):
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                continue

            chat_obj = obj.get("chat") or {}
            if chat_obj.get("id") and not resolved_chat:
                resolved_chat = chat_obj["id"]

            msg_obj = obj.get("message") or {}
            if msg_obj.get("role") == "user" and msg_obj.get("id"):
                user_msg_id = msg_obj["id"]

            if _is_done(obj):
                final_chat = resolved_chat or chat_id
                if final_chat:
                    self.last_chat_id = final_chat
                    if user_msg_id:
                        self._last_user_msg[final_chat] = user_msg_id
                break

            text = _extract_text_from_frame(obj)
            if text:
                yield text

    async def chat_stream(
        self,
        content: str,
        chat_id: str = "",
        parent_id: str = "",
        file_ids: Optional[list[str]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        full_text = ""
        async for text in self.chat(
            content=content,
            chat_id=chat_id,
            parent_id=parent_id,
            file_ids=file_ids,
        ):
            full_text += text
            yield {"content": text, "full_content": full_text}

    async def get_chat(self, chat_id: str) -> dict:
        referer = f"{BASE_URL}/chat/{chat_id}"
        return await self._send_json(
            {"chat_id": chat_id},
            GET_CHAT_ENDPOINT,
            referer,
        )

    async def list_messages(
        self,
        chat_id: str,
        page_size: int = 100,
    ) -> List[dict]:
        referer = f"{BASE_URL}/chat/{chat_id}"
        data = await self._send_json(
            {"chat_id": chat_id, "page_size": page_size},
            LIST_MSGS_ENDPOINT,
            referer,
        )
        return data.get("messages", [])

    async def upload_file(
        self,
        file_path: str,
        filename: str = "",
    ) -> dict:
        with open(file_path, "rb") as f:
            file_data = f.read()
        filename = filename or file_path.rsplit("\\", 1)[-1]
        content_type = "application/octet-stream"
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext in ("txt", "md"):
            content_type = "text/plain; charset=utf-8"
        elif ext in ("py", "js", "ts", "tsx", "jsx", "java", "c", "cpp", "h", "rs", "go"):
            content_type = "text/plain; charset=utf-8"
        elif ext in ("png", "jpg", "jpeg", "gif", "bmp", "webp"):
            content_type = f"image/{ext}"
        elif ext == "svg":
            content_type = "image/svg+xml"
        elif ext == "pdf":
            content_type = "application/pdf"

        files = {"file": (filename, file_data, content_type)}
        h = self._base_headers(f"{BASE_URL}/chat", content_type="")
        h["accept"] = "application/json, text/plain, */*"
        h.pop("content-type", None)
        r = await self.client.post(
            FILE_UPLOAD_ENDPOINT,
            headers=h,
            cookies=self.cookies,
            files=files,
        )
        if r.status_code != 200:
            raise APIError(
                f"Upload HTTP {r.status_code}: {r.text[:500]}",
                r.status_code,
            )
        return r.json()

    async def get_file_parse_progress(
        self,
        file_ids: list[str],
    ) -> list[dict]:
        r = await self.client.post(
            FILE_PARSE_PROGRESS_ENDPOINT,
            headers=self._base_headers(f"{BASE_URL}/chat", content_type="application/json"),
            cookies=self.cookies,
            json={"file_ids": file_ids},
        )
        if r.status_code != 200:
            raise APIError(
                f"ParseProgress HTTP {r.status_code}: {r.text[:500]}",
                r.status_code,
            )
        return r.json().get("progresses", [])

    async def close(self):
        await self.client.aclose()
