import asyncio, base64, json, time
from typing import AsyncGenerator, Optional, Dict, Any, List
import httpx

from .connect import encode_unary, read_streamed_frames
from .models import ChatRequest, Message, TextBlock


BASE_URL = "https://www.kimi.com"
FILES_BASE = "https://www.kimi.com/apiv2-files"
CHAT_ENDPOINT = "/apiv2/kimi.gateway.chat.v1.ChatService/Chat"
GET_CHAT_ENDPOINT = "/apiv2/kimi.gateway.chat.v1.ChatService/GetChat"
UPDATE_CHAT_ENDPOINT = "/apiv2/kimi.chat.v1.ChatService/UpdateChat"
DELETE_CHAT_ENDPOINT = "/apiv2/kimi.chat.v1.ChatService/DeleteChat"
CANCEL_CHAT_ENDPOINT = "/apiv2/kimi.gateway.chat.v1.ChatService/CancelChat"
PIN_RESOURCE_ENDPOINT = "/apiv2/kimi.gateway.pin.v1.PinService/PinResource"
UNPIN_RESOURCE_ENDPOINT = "/apiv2/kimi.gateway.pin.v1.PinService/UnpinResource"
LIST_PINS_ENDPOINT = "/apiv2/kimi.gateway.pin.v1.PinService/ListPinResources"
LIST_FEEDS_ENDPOINT = "/apiv2/kimi.gateway.feed.v1.FeedService/ListFeeds"
LIST_MSGS_ENDPOINT = "/apiv2/kimi.gateway.chat.v1.ChatService/ListMessages"
FILE_UPLOAD_ENDPOINT = "/apiv2-files/file/upload"
FILE_PARSE_PROGRESS_ENDPOINT = "/apiv2-files/kimi.gateway.file.v1.FileService/GetFileParseProgress"
MODELS_ENDPOINT = "/apiv2/kimi.gateway.config.v1.ConfigService/GetAvailableModels"
REFRESH_TOKEN_ENDPOINT = "https://auth.kimi.ai/api/account.gateway.v1.AuthService/RefreshToken"

REFRESH_BUFFER = 60
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"


class KimiError(Exception):
    pass


class APIError(KimiError):
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class AuthError(APIError):
    pass


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
        auth_token: str = "",
        cookies: Optional[dict] = None,
        device_id: str = "",
        session_id: str = "",
        traffic_id: str = "",
        shield_data: str = "",
        language: str = "en-US",
        refresh_token: str = "",
    ):
        if not auth_token and not refresh_token:
            raise ValueError("KimiAPI requires an auth_token and/or a refresh_token")

        self.auth_token = auth_token
        self.refresh_token = refresh_token
        self.cookies = cookies or {}
        if auth_token and "kimi-auth" not in self.cookies:
            self.cookies["kimi-auth"] = auth_token

        self._user_device_id = device_id
        self._user_session_id = session_id
        self._user_traffic_id = traffic_id

        claims = _decode_jwt(auth_token) if auth_token else {}
        self._access_exp: Optional[int] = claims.get("exp") if claims else None
        base_claims = claims or _decode_jwt(refresh_token)
        self.device_id = device_id or base_claims.get("device_id", "")
        self.session_id = session_id or base_claims.get("ssid", "")
        self.traffic_id = traffic_id or base_claims.get("sub", "")
        self.shield_data = shield_data
        self.language = language

        self._last_user_msg: Dict[str, str] = {}
        self.last_chat_id: str = ""
        self.last_message_id: str = ""
        self._refresh_lock = asyncio.Lock()

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
            "user-agent": USER_AGENT,
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

    def _access_expired(self) -> bool:
        if self._access_exp is None:
            return True
        return time.time() >= self._access_exp - REFRESH_BUFFER

    def _apply_tokens(self, access_token: str, refresh_token: str = "") -> None:
        self.auth_token = access_token
        if refresh_token:
            self.refresh_token = refresh_token
        self.cookies["kimi-auth"] = access_token

        claims = _decode_jwt(access_token)
        exp = claims.get("exp")
        self._access_exp = exp if isinstance(exp, int) else None
        if claims:
            self.device_id = self._user_device_id or claims.get("device_id", "") or self.device_id
            self.session_id = self._user_session_id or claims.get("ssid", "") or self.session_id
            self.traffic_id = self._user_traffic_id or claims.get("sub", "") or self.traffic_id

    async def refresh_tokens(self, force: bool = False) -> Dict[str, str]:
        """Exchange the refresh token for a fresh access token.

        Kimi rotates refresh tokens: persist the returned ``refresh_token``
        (also available as ``api.refresh_token``) after every refresh.
        """
        if not self.refresh_token:
            raise AuthError("no refresh_token configured", 401)

        async with self._refresh_lock:
            if not force and not self._access_expired():
                return {"access_token": self.auth_token, "refresh_token": self.refresh_token}

            headers = {
                "accept": "*/*",
                "content-type": "application/json",
                "origin": BASE_URL,
                "referer": f"{BASE_URL}/",
                "user-agent": USER_AGENT,
                "x-msh-platform": "web",
                "x-msh-version": "1.0.0",
            }
            if self.device_id:
                headers["x-msh-device-id"] = self.device_id
            if self.session_id:
                headers["x-msh-session-id"] = self.session_id
            if self.traffic_id:
                headers["x-traffic-id"] = self.traffic_id

            try:
                response = await self.client.post(
                    REFRESH_TOKEN_ENDPOINT,
                    headers=headers,
                    json={"refresh_token": self.refresh_token},
                )
            except httpx.HTTPError as e:
                raise APIError(f"token refresh failed: {e}") from e

            if response.status_code != 200:
                if response.status_code in (401, 403):
                    raise AuthError(
                        f"refresh token rejected: HTTP {response.status_code}: {response.text[:500]}",
                        response.status_code,
                    )
                raise APIError(
                    f"token refresh failed: HTTP {response.status_code}: {response.text[:500]}",
                    response.status_code,
                )

            data = response.json()
            access = data.get("accessToken", "")
            if not access:
                raise AuthError(f"unexpected refresh response: {response.text[:500]}", 401)

            self._apply_tokens(access, data.get("refreshToken", ""))
            return {"access_token": access, "refresh_token": self.refresh_token}

    async def _ensure_token(self) -> None:
        if self._access_exp is None:
            if not self.auth_token:
                if self.refresh_token:
                    await self.refresh_tokens()
                else:
                    raise AuthError("no auth token configured", 401)
            return

        now = time.time()
        if now < self._access_exp - REFRESH_BUFFER:
            return
        if self.refresh_token:
            await self.refresh_tokens()
            return
        if now >= self._access_exp:
            raise AuthError(
                "access token has expired; pass a refresh_token to auto-renew it",
                401,
            )

    def _raise_for_status(self, response: httpx.Response, prefix: str = "") -> None:
        if response.status_code in (401, 403):
            raise AuthError(
                f"{prefix}HTTP {response.status_code}: {response.text[:500]}",
                response.status_code,
            )
        if response.status_code != 200:
            raise APIError(
                f"{prefix}HTTP {response.status_code}: {response.text[:500]}",
                response.status_code,
            )

    async def _post(
        self,
        endpoint: str,
        referer: str,
        *,
        json: Optional[dict] = None,
        files: Optional[dict] = None,
        prefix: str = "",
    ) -> httpx.Response:
        """POST with proactive token refresh and one reactive retry on 401/403."""
        await self._ensure_token()
        for attempt in range(2):
            if files is not None:
                headers = self._base_headers(referer, content_type="")
                headers["accept"] = "application/json, text/plain, */*"
                headers.pop("content-type", None)
            else:
                headers = self._base_headers(referer, content_type="application/json")

            kwargs: Dict[str, Any] = {"files": files} if files is not None else {"json": json}
            response = await self.client.post(
                endpoint,
                headers=headers,
                cookies=self.cookies,
                **kwargs,
            )
            if response.status_code in (401, 403) and attempt == 0 and self.refresh_token:
                await self.refresh_tokens(force=True)
                continue
            self._raise_for_status(response, prefix)
            return response

        return response

    async def _send_connect(self, body: dict, endpoint: str, referer: str) -> AsyncGenerator[bytes, None]:
        attempt = 0
        while True:
            await self._ensure_token()
            framed = encode_unary(json.dumps(body).encode(), flag_byte=0x00)

            async with self.client.stream(
                "POST",
                endpoint,
                headers=self._base_headers(referer),
                cookies=self.cookies,
                content=framed,
            ) as response:
                if response.status_code in (401, 403):
                    text = await response.aread()
                    if attempt == 0 and self.refresh_token:
                        attempt += 1
                        await self.refresh_tokens(force=True)
                        continue
                    raise AuthError(
                        f"HTTP {response.status_code}: {text[:500]}",
                        response.status_code,
                    )
                if response.status_code != 200:
                    text = await response.aread()
                    raise APIError(
                        f"HTTP {response.status_code}: {text[:500]}",
                        response.status_code,
                    )

                async for flag, payload in read_streamed_frames(response.aiter_bytes()):
                    if payload:
                        yield payload
            return

    async def _send_json(self, body: dict, endpoint: str, referer: str) -> dict:
        response = await self._post(endpoint, referer, json=body)
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
        if chat_id:
            self.last_chat_id = chat_id

        async for payload in self._send_connect(body, CHAT_ENDPOINT, referer):
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                continue

            chat_obj = obj.get("chat") or {}
            if chat_obj.get("id") and not resolved_chat:
                resolved_chat = chat_obj["id"]
                self.last_chat_id = resolved_chat

            msg_obj = obj.get("message") or {}
            if msg_obj.get("role") == "user" and msg_obj.get("id"):
                user_msg_id = msg_obj["id"]
            if msg_obj.get("role") == "assistant" and msg_obj.get("id"):
                self.last_message_id = msg_obj["id"]

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

    async def stop_stream(
        self,
        chat_id: str = "",
        message_id: str = "",
    ) -> dict:
        chat_id = chat_id or self.last_chat_id
        message_id = message_id or self.last_message_id
        referer = f"{BASE_URL}/chat/{chat_id}"
        return await self._send_json(
            {"chat_id": chat_id, "message_id": message_id},
            CANCEL_CHAT_ENDPOINT,
            referer,
        )

    async def pin_chat(self, chat_id: str) -> dict:
        referer = f"{BASE_URL}/"
        return await self._send_json(
            {"resource_type": "PIN_RESOURCE_TYPE_CHAT", "resource_id": chat_id},
            PIN_RESOURCE_ENDPOINT,
            referer,
        )

    async def unpin_chat(self, chat_id: str) -> dict:
        referer = f"{BASE_URL}/"
        return await self._send_json(
            {"resource_type": "PIN_RESOURCE_TYPE_CHAT", "resource_id": chat_id},
            UNPIN_RESOURCE_ENDPOINT,
            referer,
        )

    async def list_pins(
        self,
        page_size: int = 100,
        resource_types: Optional[List[str]] = None,
    ) -> List[dict]:
        if resource_types is None:
            resource_types = ["PIN_RESOURCE_TYPE_PROJECT", "PIN_RESOURCE_TYPE_CHAT"]
        referer = f"{BASE_URL}/"
        data = await self._send_json(
            {"page_size": page_size, "resource_types": resource_types},
            LIST_PINS_ENDPOINT,
            referer,
        )
        return data.get("resources", [])

    async def get_chat(self, chat_id: str) -> dict:
        referer = f"{BASE_URL}/chat/{chat_id}"
        return await self._send_json(
            {"chat_id": chat_id},
            GET_CHAT_ENDPOINT,
            referer,
        )

    async def rename_chat(self, chat_id: str, name: str) -> dict:
        referer = f"{BASE_URL}/chat/{chat_id}"
        return await self._send_json(
            {"chat": {"id": chat_id, "name": name}},
            UPDATE_CHAT_ENDPOINT,
            referer,
        )

    async def delete_chat(self, chat_id: str) -> dict:
        referer = f"{BASE_URL}/chat/{chat_id}"
        return await self._send_json(
            {"chat_id": chat_id},
            DELETE_CHAT_ENDPOINT,
            referer,
        )

    async def list_feeds(
        self,
        page_size: int = 15,
        project_id: str = "",
        filter_types: Optional[List[str]] = None,
        include_pinned: bool = False,
    ) -> List[dict]:
        if filter_types is None:
            filter_types = ["FEED_TYPE_CHAT", "FEED_TYPE_TASK"]
        referer = f"{BASE_URL}/"
        data = await self._send_json(
            {
                "page_size": page_size,
                "project_id": project_id,
                "filter_types": filter_types,
                "include_pinned": include_pinned,
            },
            LIST_FEEDS_ENDPOINT,
            referer,
        )
        return data.get("items", [])

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

    async def get_available_models(self) -> dict:
        """Return the model catalogue.

        The response contains ``availableModels`` (list of model dicts),
        ``defaultScenario``, ``defaultAgentModel`` and ``defaultChatModel``.
        """
        referer = f"{BASE_URL}/"
        return await self._send_json({}, MODELS_ENDPOINT, referer)

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
        response = await self._post(
            FILE_UPLOAD_ENDPOINT,
            f"{BASE_URL}/chat",
            files=files,
            prefix="Upload ",
        )
        return response.json()

    async def get_file_parse_progress(
        self,
        file_ids: list[str],
    ) -> list[dict]:
        response = await self._post(
            FILE_PARSE_PROGRESS_ENDPOINT,
            f"{BASE_URL}/chat",
            json={"file_ids": file_ids},
            prefix="ParseProgress ",
        )
        return response.json().get("progresses", [])

    async def close(self):
        await self.client.aclose()
