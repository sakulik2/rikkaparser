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

from .db_reader import parse_backup_zip
from .html_gen import generate_html
from .models import Conversation, Message, ParseResult


def main():
    parser = argparse.ArgumentParser(
        description="RikkaHub 备份解析器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("zipfile", help="RikkaHub 备份 zip 文件路径")
    parser.add_argument("-o", "--output", help="输出文件路径")
    parser.add_argument(
        "--export",
        choices=["html", "json", "txt"],
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

    # 解析备份
    print(f"📦 正在解析: {args.zipfile}")
    data = parse_backup_zip(args.zipfile)
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


if __name__ == "__main__":
    main()
