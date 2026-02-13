"""
RikkaHub 备份数据库读取模块。

负责解压 zip 文件、读取 SQLite 数据库、解析消息结构。
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .models import Conversation, Memory, Message, MessagePart, ParseResult


def parse_backup_zip(zip_path: str) -> ParseResult:
    """解析 RikkaHub 备份 zip 文件，返回结构化数据。"""
    zip_path = Path(zip_path)
    if not zip_path.exists():
        print(f"错误: 文件不存在: {zip_path}", file=sys.stderr)
        sys.exit(1)
    if not zipfile.is_zipfile(zip_path):
        print(f"错误: 不是有效的 zip 文件: {zip_path}", file=sys.stderr)
        sys.exit(1)

    tmpdir = tempfile.mkdtemp(prefix="rikkahub_")
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmpdir)

        result = ParseResult()

        # 1. 读取 settings.json
        settings_path = os.path.join(tmpdir, "settings.json")
        if os.path.exists(settings_path):
            with open(settings_path, "r", encoding="utf-8") as f:
                result.settings = json.load(f)

        # 提取助手信息
        if result.settings:
            for a in result.settings.get("assistants", []):
                aid = a.get("id", "")
                result.assistants[aid] = a.get("name", "") or "默认助手"

        # 2. 读取 SQLite 数据库
        db_path = os.path.join(tmpdir, "rikka_hub.db")
        if os.path.exists(db_path):
            result.conversations = read_conversations(db_path)
            result.memories = read_memories(db_path)

        return result
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def read_conversations(db_path: str) -> list[Conversation]:
    """从 SQLite 数据库读取对话记录。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conversations = []

    try:
        cursor = conn.execute(
            "SELECT id, assistant_id, title, create_at, update_at, "
            "truncate_index, suggestions, is_pinned "
            "FROM ConversationEntity ORDER BY update_at DESC"
        )

        for row in cursor.fetchall():
            conv = Conversation(
                id=row["id"],
                assistant_id=row["assistant_id"],
                title=row["title"] or "(无标题)",
                create_at=epoch_ms_to_str(row["create_at"]),
                update_at=epoch_ms_to_str(row["update_at"]),
                create_at_ts=row["create_at"],
                update_at_ts=row["update_at"],
                is_pinned=bool(row["is_pinned"]),
            )

            # 读取该对话的消息节点
            node_cursor = conn.execute(
                "SELECT id, node_index, messages, select_index "
                "FROM message_node "
                "WHERE conversation_id = ? ORDER BY node_index ASC",
                (row["id"],),
            )
            for node_row in node_cursor.fetchall():
                messages_json = node_row["messages"]
                select_index = node_row["select_index"]
                try:
                    messages = json.loads(messages_json)
                except (json.JSONDecodeError, TypeError):
                    messages = []

                if messages and 0 <= select_index < len(messages):
                    selected_msg = messages[select_index]
                else:
                    selected_msg = messages[0] if messages else None

                if selected_msg:
                    parsed = parse_ui_message(selected_msg)
                    parsed.branch_count = len(messages)
                    parsed.branch_index = select_index
                    conv.messages.append(parsed)

            conversations.append(conv)

    finally:
        conn.close()

    return conversations


def read_memories(db_path: str) -> list[Memory]:
    """读取 AI 记忆。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    memories = []
    try:
        cursor = conn.execute(
            "SELECT id, assistant_id, content FROM MemoryEntity"
        )
        for row in cursor.fetchall():
            memories.append(Memory(
                id=row["id"],
                assistant_id=row["assistant_id"],
                content=row["content"],
            ))
    except Exception:
        pass  # 表可能不存在
    finally:
        conn.close()
    return memories


def parse_ui_message(msg: dict) -> Message:
    """解析一条 UIMessage 为结构化数据。"""
    parts = []
    for part in msg.get("parts", []):
        parsed_part = parse_message_part(part)
        if parsed_part:
            parts.append(parsed_part)

    annotations = []
    for ann in msg.get("annotations", []):
        ann_type = ann.get("type", "")
        if ann_type == "url_citation":
            annotations.append({
                "type": "url_citation",
                "title": ann.get("title", ""),
                "url": ann.get("url", ""),
            })

    usage = None
    raw_usage = msg.get("usage")
    if raw_usage:
        usage = {
            "prompt_tokens": raw_usage.get("promptTokens", raw_usage.get("prompt_tokens", 0)),
            "completion_tokens": raw_usage.get("completionTokens", raw_usage.get("completion_tokens", 0)),
            "total_tokens": raw_usage.get("totalTokens", raw_usage.get("total_tokens", 0)),
        }

    return Message(
        role=msg.get("role", "unknown"),
        parts=parts,
        annotations=annotations,
        usage=usage,
        created_at=msg.get("createdAt", ""),
        finished_at=msg.get("finishedAt"),
        model_id=msg.get("modelId"),
        translation=msg.get("translation"),
    )


def parse_message_part(part: dict) -> MessagePart | None:
    """解析消息的各个部分。"""
    part_type = part.get("type", "")

    if part_type == "me.rerere.ai.ui.UIMessagePart.Text" or (
        "text" in part and "reasoning" not in part and "toolCallId" not in part
        and "toolName" not in part and "url" not in part and "fileName" not in part
    ):
        text = part.get("text", "")
        if not text and not part_type:
            return None
        return MessagePart(type="text", text=text)

    if part_type == "me.rerere.ai.ui.UIMessagePart.Reasoning" or "reasoning" in part:
        return MessagePart(
            type="reasoning",
            text=part.get("reasoning", ""),
            created_at=part.get("createdAt", ""),
            finished_at=part.get("finishedAt"),
        )

    if part_type == "me.rerere.ai.ui.UIMessagePart.Image" or (
        "url" in part and "fileName" not in part and "toolCallId" not in part
        and "reasoning" not in part
    ):
        if "toolCallId" in part or "toolName" in part or "reasoning" in part:
            return None
        return MessagePart(type="image", url=part.get("url", ""))

    if part_type == "me.rerere.ai.ui.UIMessagePart.Document" or "fileName" in part:
        return MessagePart(
            type="document",
            url=part.get("url", ""),
            file_name=part.get("fileName", ""),
            mime=part.get("mime", ""),
        )

    if part_type == "me.rerere.ai.ui.UIMessagePart.Video":
        return MessagePart(type="video", url=part.get("url", ""))

    if part_type == "me.rerere.ai.ui.UIMessagePart.Audio":
        return MessagePart(type="audio", url=part.get("url", ""))

    if part_type == "me.rerere.ai.ui.UIMessagePart.Tool" or "toolCallId" in part:
        output_parts = []
        for op in part.get("output", []):
            parsed = parse_message_part(op)
            if parsed:
                output_parts.append(parsed)
        return MessagePart(
            type="tool",
            tool_call_id=part.get("toolCallId", ""),
            tool_name=part.get("toolName", ""),
            input=part.get("input", ""),
            output=output_parts,
        )

    # Fallback
    if "text" in part and isinstance(part["text"], str):
        return MessagePart(type="text", text=part["text"])

    return None


def epoch_ms_to_str(ms: int) -> str:
    """将毫秒时间戳转为可读字符串。"""
    if not ms:
        return ""
    try:
        dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, ValueError):
        return str(ms)
