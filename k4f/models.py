from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TextBlock:
    content: str
    message_id: str = ""


@dataclass
class Message:
    role: str
    blocks: list
    parent_id: Optional[str] = None
    scenario: str = "SCENARIO_K2D5"
    is_goal: bool = False


@dataclass
class ChatOptions:
    thinking: bool = False
    enable_plugin: bool = True


@dataclass
class ChatRequest:
    chat_id: str
    message: Message
    scenario: str = "SCENARIO_K2D5"
    tools: list[dict] = field(default_factory=lambda: [
        {"type": "TOOL_TYPE_SEARCH", "search": {}},
        {"type": "TOOL_TYPE_CRON_JOB"},
    ])
    options: Optional[ChatOptions] = None
    project_id: str = ""

    def to_dict(self) -> dict:
        d = {
            "scenario": self.scenario,
            "tools": self.tools,
            "message": {
                "parent_id": self.message.parent_id,
                "role": self.message.role,
                "blocks": [
                    {"message_id": b.message_id, "text": {"content": b.content}}
                    if isinstance(b, TextBlock) else b
                    for b in self.message.blocks
                ],
                "scenario": self.message.scenario,
                "is_goal": self.message.is_goal,
            },
            "options": {
                "thinking": self.options.thinking if self.options else False,
                "enable_plugin": self.options.enable_plugin if self.options else True,
            },
            "project_id": self.project_id,
        }
        if self.chat_id:
            d["chat_id"] = self.chat_id
        if self.message.parent_id is None:
            del d["message"]["parent_id"]
        return d


@dataclass
class ChatResponse:
    content: str
    finish_reason: Optional[str] = None
