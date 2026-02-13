"""
RikkaHub 数据模型定义。
"""

from dataclasses import dataclass, field


@dataclass
class MessagePart:
    """消息的一个组成部分。"""
    type: str  # text, reasoning, image, tool, document, video, audio
    text: str = ""
    url: str = ""
    file_name: str = ""
    mime: str = ""
    created_at: str = ""
    finished_at: str | None = None
    # Tool 专用
    tool_call_id: str = ""
    tool_name: str = ""
    input: str = ""
    output: list["MessagePart"] = field(default_factory=list)


@dataclass
class Message:
    """一条对话消息。"""
    role: str
    parts: list[MessagePart] = field(default_factory=list)
    annotations: list[dict] = field(default_factory=list)
    usage: dict | None = None
    created_at: str = ""
    finished_at: str | None = None
    model_id: str | None = None
    translation: str | None = None
    branch_count: int = 1
    branch_index: int = 0


@dataclass
class Conversation:
    """一条对话记录。"""
    id: str
    assistant_id: str = ""
    title: str = "(无标题)"
    create_at: str = ""
    update_at: str = ""
    create_at_ts: int = 0
    update_at_ts: int = 0
    is_pinned: bool = False
    messages: list[Message] = field(default_factory=list)


@dataclass
class Memory:
    """AI 记忆条目。"""
    id: int = 0
    assistant_id: str = ""
    content: str = ""


@dataclass
class ParseResult:
    """解析结果。"""
    conversations: list[Conversation] = field(default_factory=list)
    memories: list[Memory] = field(default_factory=list)
    settings: dict | None = None
    assistants: dict[str, str] = field(default_factory=dict)
