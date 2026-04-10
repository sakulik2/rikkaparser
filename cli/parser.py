#!/usr/bin/env python3
"""
RikkaHub Backup Parser CLI
===========================
解析 RikkaHub (Android LLM Chat App) 的 zip 备份文件，
提取对话记录并生成 HTML / JSON / TXT 格式输出。

用法:
    python -m cli.parser <backup.zip> [-o output.html]
    python -m cli.parser <backup.zip> --search "关键词"
    python -m cli.parser <backup.zip> --export json -o output.json
    python -m cli.parser <backup.zip> --export txt -o output.txt
    python -m cli.parser <backup.zip> --filter-assistant "助手名"
    python -m cli.parser <backup.zip> --filter-date 2025-01-01 2025-06-30
"""

import argparse
import json
import sys
from datetime import datetime

from .db_reader import parse_backup_zip, epoch_ms_to_str
from .html_gen import generate_html
from .models import Conversation, Message, MessagePart, ParseResult


def main():
    parser = argparse.ArgumentParser(
        description="RikkaHub 备份解析器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("file", help="RikkaHub 备份 zip 文件或 Chatbox 导出的 JSON 文件")
    parser.add_argument("-o", "--output", help="输出文件路径")
    parser.add_argument(
        "--export",
        choices=["html", "json", "txt", "chatbox"],
        default="html",
        help="输出格式 (默认: html)",
    )
    parser.add_argument("--search", help="搜索消息内容关键词")
    parser.add_argument("--filter-assistant", help="按助手名称筛选")
    parser.add_argument(
        "--filter-date",
        nargs=2,
        metavar=("START", "END"),
        help="按日期范围筛选 (格式: YYYY-MM-DD)",
    )
    parser.add_argument("--list", action="store_true", help="列出所有对话")

    args = parser.parse_args()

    # 解析输入文件
    print(f"📦 正在解析: {args.file}")
    
    file_lower = args.file.lower()
    if file_lower.endswith(".json"):
        data = parse_json_file(args.file)
    elif file_lower.endswith(".md"):
        data = parse_gemini_md(args.file)
    else:
        data = parse_backup_zip(args.file)
        
    print(f"   发现 {len(data.conversations)} 条对话, {len(data.memories)} 条记忆")

    # 筛选
    if args.filter_assistant:
        data = _filter_by_assistant(data, args.filter_assistant)
        print(f"   助手筛选后: {len(data.conversations)} 条对话")

    if args.filter_date:
        data = _filter_by_date(data, args.filter_date[0], args.filter_date[1])
        print(f"   日期筛选后: {len(data.conversations)} 条对话")

    # 列出模式
    if args.list:
        _list_conversations(data)
        return

    # 搜索模式
    if args.search:
        _search_messages(data, args.search)
        return

    # 导出
    output = args.output
    if args.export == "html":
        if not output:
            output = "rikkahub_chats.html"
        generate_html(data, output)

    elif args.export == "json":
        if not output:
            output = "rikkahub_chats.json"
        _export_json(data, output)

    elif args.export == "txt":
        if not output:
            output = "rikkahub_chats.txt"
        _export_txt(data, output)

    elif args.export == "chatbox":
        if not output:
            output = "chatbox_export.json"
        _export_chatbox(data, output)


def _filter_by_assistant(data: ParseResult, name: str) -> ParseResult:
    """按助手名称筛选对话。"""
    # 找到匹配的 assistant_id
    matched_ids = set()
    for aid, aname in data.assistants.items():
        if name.lower() in aname.lower():
            matched_ids.add(aid)

    filtered = [c for c in data.conversations if c.assistant_id in matched_ids]
    return ParseResult(
        conversations=filtered,
        memories=data.memories,
        settings=data.settings,
        assistants=data.assistants,
    )


def _filter_by_date(data: ParseResult, start: str, end: str) -> ParseResult:
    """按日期范围筛选对话。"""
    try:
        start_dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
    except ValueError:
        print("❌ 日期格式错误，应为 YYYY-MM-DD", file=sys.stderr)
        sys.exit(1)

    start_ts = int(start_dt.timestamp() * 1000)
    end_ts = int(end_dt.timestamp() * 1000)

    filtered = [
        c for c in data.conversations
        if c.update_at_ts and start_ts <= c.update_at_ts <= end_ts
    ]
    return ParseResult(
        conversations=filtered,
        memories=data.memories,
        settings=data.settings,
        assistants=data.assistants,
    )


def _list_conversations(data: ParseResult):
    """列出所有对话。"""
    for i, conv in enumerate(data.conversations):
        pin = "📌 " if conv.is_pinned else "   "
        aname = data.assistants.get(conv.assistant_id, "")
        badge = f" [{aname}]" if aname else ""
        print(f"{pin}{i+1:3d}. {conv.title}{badge}  ({len(conv.messages)} 条)  {conv.update_at}")


def _search_messages(data: ParseResult, query: str):
    """搜索消息内容。"""
    query_lower = query.lower()
    found = 0

    for conv in data.conversations:
        matches = []
        for mi, msg in enumerate(conv.messages):
            for part in msg.parts:
                if part.text and query_lower in part.text.lower():
                    # 提取匹配上下文
                    idx = part.text.lower().index(query_lower)
                    start = max(0, idx - 40)
                    end = min(len(part.text), idx + len(query) + 40)
                    context = part.text[start:end].replace("\n", " ")
                    if start > 0:
                        context = "..." + context
                    if end < len(part.text):
                        context = context + "..."
                    matches.append((mi, msg.role, context))

        if matches:
            found += len(matches)
            aname = data.assistants.get(conv.assistant_id, "")
            badge = f" [{aname}]" if aname else ""
            print(f"\n📝 {conv.title}{badge}")
            print(f"   {conv.update_at}")
            for mi, role, ctx in matches:
                role_icon = {"user": "👤", "assistant": "🤖", "system": "⚙️"}.get(role.lower(), "❓")
                print(f"   {role_icon} #{mi+1}: {ctx}")

    if found:
        print(f"\n🔍 共找到 {found} 条匹配")
    else:
        print(f"🔍 未找到包含 \"{query}\" 的消息")


def _export_json(data: ParseResult, output: str):
    """导出为 JSON。"""
    result = {
        "conversations": [],
        "memories": [{"id": m.id, "content": m.content} for m in data.memories],
    }
    for conv in data.conversations:
        conv_dict = {
            "id": conv.id,
            "title": conv.title,
            "assistant": data.assistants.get(conv.assistant_id, ""),
            "create_at": conv.create_at,
            "update_at": conv.update_at,
            "is_pinned": conv.is_pinned,
            "messages": [],
        }
        for msg in conv.messages:
            msg_dict = {
                "role": msg.role,
                "created_at": msg.created_at,
                "parts": [],
            }
            for part in msg.parts:
                msg_dict["parts"].append({
                    "type": part.type,
                    "text": part.text if part.text else None,
                    "url": part.url if part.url else None,
                })
            if msg.usage:
                msg_dict["usage"] = msg.usage
            conv_dict["messages"].append(msg_dict)
        result["conversations"].append(conv_dict)

    with open(output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"✅ 已导出 JSON: {output}")


def _export_txt(data: ParseResult, output: str):
    """导出为纯文本。"""
    lines = []
    for conv in data.conversations:
        aname = data.assistants.get(conv.assistant_id, "")
        badge = f" [{aname}]" if aname else ""
        lines.append(f"{'='*60}")
        lines.append(f"{'📌 ' if conv.is_pinned else ''}{conv.title}{badge}")
        lines.append(f"创建: {conv.create_at}  更新: {conv.update_at}")
        lines.append(f"{'='*60}")
        lines.append("")

        for msg in conv.messages:
            role_label = {"user": "👤 User", "assistant": "🤖 Assistant", "system": "⚙️ System"}.get(
                msg.role.lower(), msg.role
            )
            lines.append(f"--- {role_label} ---")
            for part in msg.parts:
                if part.type in ("text", "reasoning"):
                    lines.append(part.text)
                elif part.type == "tool":
                    lines.append(f"[工具调用: {part.tool_name}]")
                elif part.type == "image":
                    lines.append(f"[图片: {part.url}]")
            lines.append("")

        lines.append("")

    with open(output, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"✅ 已导出 TXT: {output}")


def _export_chatbox(data: ParseResult, output: str):
    """导出为 Chatbox 所需的 JSON 格式。"""
    from datetime import datetime, timezone
    
    result = {
        "__exported_items": ["conversations"],
        "__exported_at": datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
        "chat-session-settings": {},
        "chat-sessions-list": []
    }
    
    for conv in data.conversations:
        session_id = conv.id
        result["chat-sessions-list"].append({
            "id": session_id,
            "name": conv.title,
            "starred": conv.is_pinned,
            "type": "chat"
        })
        
        c_messages = []
        for i, msg in enumerate(conv.messages):
            msg_parts = []
            for part in msg.parts:
                if part.type in ("text", "reasoning"):
                    msg_parts.append({"type": "text", "text": part.text})
                elif part.type == "image":
                    msg_parts.append({"type": "image", "storageKey": part.url})
                else:
                    msg_parts.append({"type": "text", "text": f"[{part.type}] {part.text or part.url}"})
            
            role = msg.role.lower()
            if role not in ("user", "assistant", "system"):
                role = "assistant"
                
            msg_id = f"{session_id}-msg-{i}"
            
            ts = conv.update_at_ts
            if msg.created_at:
                try:
                    dt = datetime.fromisoformat(msg.created_at.replace('Z', '+00:00'))
                    ts = int(dt.timestamp() * 1000)
                except ValueError:
                    pass
            
            c_messages.append({
                "id": msg_id,
                "role": role,
                "contentParts": msg_parts,
                "timestamp": ts,
            })
            
        result[f"session:{session_id}"] = {
            "name": conv.title,
            "type": "chat",
            "messages": c_messages,
            "settings": {},
            "id": session_id,
            "messageForksHash": {},
            "threadName": conv.title
        }

    with open(output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"✅ 已导出 Chatbox JSON: {output}")


def parse_json_file(json_path: str) -> ParseResult:
    """处理 JSON 文件的分发解析。"""
    from pathlib import Path
    
    json_path = Path(json_path)
    if not json_path.exists():
        print(f"错误: 文件不存在: {json_path}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        print(f"错误: 不是有效的 JSON 文件: {json_path}", file=sys.stderr)
        sys.exit(1)

    if isinstance(data, dict) and ("__exported_items" in data or "chat-sessions-list" in data):
        return parse_chatbox_export(data)
    elif isinstance(data, list):
        return parse_openwebui_export(data)
    else:
        print(f"警告: 未知的 JSON 格式: {json_path}", file=sys.stderr)
        return ParseResult()


def parse_chatbox_export(data: dict) -> ParseResult:
    """解析 Chatbox 导出的 JSON 数据结构。"""
    result = ParseResult()
    session_list = data.get("chat-sessions-list", [])

    for session_meta in session_list:
        session_id = session_meta.get("id")
        if not session_id:
            continue

        session_key = f"session:{session_id}"
        session_data = data.get(session_key)
        if not session_data:
            continue

        title = session_data.get("name", "(无标题)")
        is_pinned = session_meta.get("starred", False)
        messages_data = session_data.get("messages", [])

        conv = Conversation(
            id=session_id,
            title=title,
            is_pinned=is_pinned,
            source_type="chatbox"
        )

        min_ts = -1
        max_ts = -1

        for msg_idx, msg_data in enumerate(messages_data):
            role = msg_data.get("role", "unknown")
            timestamp = msg_data.get("timestamp", 0)
            
            if min_ts == -1 or timestamp < min_ts:
                min_ts = timestamp
            if timestamp > max_ts:
                max_ts = timestamp

            parts = []
            for part in msg_data.get("contentParts", []):
                part_type = part.get("type", "")
                
                if part_type == "text":
                    parts.append(MessagePart(type="text", text=part.get("text", "")))
                elif part_type == "reasoning":
                    parts.append(MessagePart(type="reasoning", text=part.get("text", "")))
                elif part_type == "image":
                    parts.append(MessagePart(type="image", url=part.get("storageKey", "")))
                else:
                    parts.append(MessagePart(type=part_type, text=part.get("text", "") or str(part)))
                    
            usage = None
            if "usage" in msg_data:
                u = msg_data["usage"]
                usage = {
                    "prompt_tokens": u.get("inputTokens", 0),
                    "completion_tokens": u.get("outputTokens", 0),
                    "total_tokens": u.get("totalTokens", 0),
                }

            msg = Message(
                role=role,
                parts=parts,
                usage=usage,
                created_at=epoch_ms_to_str(timestamp),
                model_id=msg_data.get("model", ""),
                branch_count=1,
                branch_index=0
            )
            conv.messages.append(msg)

        if min_ts != -1:
            conv.create_at_ts = min_ts
            conv.create_at = epoch_ms_to_str(min_ts)
        if max_ts != -1:
            conv.update_at_ts = max_ts
            conv.update_at = epoch_ms_to_str(max_ts)

        result.conversations.append(conv)

    # 按照更新时间排序倒序
    result.conversations.sort(key=lambda c: c.update_at_ts, reverse=True)

    return result


def parse_openwebui_export(data: list) -> ParseResult:
    """解析 Open-WebUI 导出的 JSON 记录数组。"""
    import re
    result = ParseResult()

    for item in data:
        try:
            chat = item.get("chat", {})
            history = chat.get("history", {})
            msg_map = history.get("messages", {})
            current_id = history.get("currentId")

            # 回溯主树干链条
            chain = []
            mid = current_id
            visited = set()
            while mid and mid not in visited:
                visited.add(mid)
                m = msg_map.get(mid)
                if not m:
                    break
                chain.append(m)
                mid = m.get("parentId")
            chain.reverse()

            created_ts = int((item.get("created_at") or chat.get("timestamp") or 0) * 1000)
            updated_ts = int((item.get("updated_at") or item.get("created_at") or 0) * 1000)
            
            conv = Conversation(
                id=item.get("id", ""),
                title=item.get("title") or chat.get("title") or "(无标题)",
                create_at=epoch_ms_to_str(created_ts),
                update_at=epoch_ms_to_str(updated_ts),
                create_at_ts=created_ts,
                update_at_ts=updated_ts,
                is_pinned=bool(item.get("pinned")),
                source_type="openwebui",
                models=chat.get("models", [])
            )

            for m in chain:
                role = m.get("role", "user")
                content = m.get("content", "")
                parts = []
                
                # 提取分离 reasoning 和 text (使用非贪婪正则)
                reasoning_pattern = re.compile(r'<details[^>]*type="reasoning"[^>]*>([\s\S]*?)<\/details>', re.IGNORECASE)
                
                def replace_reasoning(match):
                    inner = match.group(1)
                    # 去掉 <summary> 行
                    body = re.sub(r'<summary>[\s\S]*?<\/summary>\s*', '', inner, flags=re.IGNORECASE).strip()
                    if body:
                        parts.append(MessagePart("reasoning", text=body))
                    return ''
                
                content = reasoning_pattern.sub(replace_reasoning, content).strip()
                
                if content:
                    parts.insert(0, MessagePart("text", text=content))
                
                usage = None
                if m.get("usage"):
                    u = m["usage"]
                    usage = {
                        "prompt_tokens": u.get("prompt_tokens", 0),
                        "completion_tokens": u.get("completion_tokens", 0),
                        "total_tokens": u.get("total_tokens", u.get("prompt_tokens", 0) + u.get("completion_tokens", 0))
                    }

                msg_ts = int((m.get("timestamp") or 0) * 1000)
                msg = Message(
                    role=role,
                    parts=parts,
                    usage=usage,
                    created_at=epoch_ms_to_str(msg_ts) if msg_ts else "",
                    model_id=m.get("model") or m.get("modelName") or ""
                )
                conv.messages.append(msg)

            result.conversations.append(conv)
            
        except Exception as e:
            print(f"跳过无效对话: {item.get('id', '未知')} ({e})", file=sys.stderr)
            
    # 按更新时间倒序
    result.conversations.sort(key=lambda c: c.update_at_ts, reverse=True)
    return result


def parse_gemini_md(md_path: str) -> ParseResult:
    """提取分析 Gemini Voyager 导出的 Markdown 文件。"""
    import re
    from pathlib import Path
    import uuid

    md_path = Path(md_path)
    if not md_path.exists():
        print(f"错误: 文件不存在: {md_path}", file=sys.stderr)
        sys.exit(1)

    with open(md_path, "r", encoding="utf-8") as f:
        text = f.read()

    # 提取标题
    title_match = re.search(r'^#\s+(.+)$', text, flags=re.MULTILINE)
    title = title_match.group(1).strip() if title_match else md_path.stem

    # 提取日期
    date_match = re.search(r'\*\*Date\*\*:\s*([^\n]+)', text)
    date_str = date_match.group(1).strip() if date_match else ""

    # 提取源 URL
    source_match = re.search(r'\*\*Source\*\*:\s*\[.*?\]\(([^)]+)\)', text)
    source_url = source_match.group(1) if source_match else ""

    # 定位正文分隔符后
    parts = text.split('\n---\n', 1)
    body_text = parts[1] if len(parts) > 1 else text

    # 使用正则切分所有的 Turn
    turn_starts = [m.start() for m in re.finditer(r'^## Turn \d+', body_text, flags=re.MULTILINE)]
    
    messages = []
    USER_MARKER = '\n### 👤 User\n'
    ASST_MARKER = '\n### 🤖 Assistant\n'
    
    # 辅助查找严格匹配
    def find_strictly(substr, string, startpos=0):
        idx = string.find(substr, startpos)
        return idx if idx != -1 else len(string)

    for i in range(len(turn_starts)):
        sec_start = turn_starts[i]
        sec_end = turn_starts[i + 1] if i + 1 < len(turn_starts) else len(body_text)
        section = body_text[sec_start:sec_end]
        
        user_idx = section.find(USER_MARKER)
        asst_idx = section.find(ASST_MARKER)
        
        if user_idx != -1:
            content_end = asst_idx if asst_idx != -1 else len(section)
            user_content = section[user_idx + len(USER_MARKER):content_end].strip()
            if user_content:
                messages.append(Message(
                    role="user",
                    parts=[MessagePart("text", text=user_content)]
                ))
                
        if asst_idx != -1:
            asst_content = section[asst_idx + len(ASST_MARKER):].strip()
            if asst_content:
                messages.append(Message(
                    role="assistant",
                    parts=[MessagePart("text", text=asst_content)]
                ))

    conv = Conversation(
        id=f"gemini-{uuid.uuid4().hex[:8]}",
        title=title,
        create_at=date_str,
        update_at=date_str,
        source_type="gemini",
        source_url=source_url,
        messages=messages
    )

    result = ParseResult()
    result.conversations.append(conv)
    return result


if __name__ == "__main__":
    main()
