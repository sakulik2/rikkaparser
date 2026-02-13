"""
HTML 生成模块。

从 templates/ 读取 CSS/JS 模板，结合解析数据生成静态 HTML 文件。
"""

import json
import os
from html import escape
from pathlib import Path

from .markdown import simple_markdown
from .models import Conversation, Message, MessagePart, ParseResult

# 模板目录
TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


def generate_html(data: ParseResult, output_path: str):
    """生成自包含的 HTML 文件。"""
    conversations = data.conversations
    assistants = data.assistants
    memories = data.memories

    css = _load_template("style.css")
    js = _load_template("script.js")

    html_parts = []
    html_parts.append(_build_head(css))
    html_parts.append(_build_sidebar(conversations, assistants))
    html_parts.append(_build_main(conversations, assistants, memories))
    html_parts.append(f"<script>\n{js}\n</script>")
    html_parts.append("</body></html>")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(html_parts))

    total_msgs = sum(len(c.messages) for c in conversations)
    print(f"✅ 已生成: {output_path}")
    print(f"   共 {len(conversations)} 条对话")
    print(f"   共 {total_msgs} 条消息")


def _load_template(name: str) -> str:
    """加载模板文件。"""
    path = TEMPLATE_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"模板文件不存在: {path}")
    return path.read_text(encoding="utf-8")


def _build_head(css: str) -> str:
    """构建 HTML 头部。"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RikkaHub 对话浏览器</title>
<style>
{css}
</style>
</head>
<body>"""


def _build_sidebar(conversations: list[Conversation], assistants: dict[str, str]) -> str:
    """构建侧边栏。"""
    parts = []
    parts.append('<div class="sidebar" id="sidebar">')
    parts.append('<div class="sidebar-header">')
    parts.append('<h2>🗂️ RikkaHub 对话</h2>')
    parts.append(f'<span class="conv-count">{len(conversations)} 条对话</span>')
    parts.append('</div>')
    parts.append('<input type="text" class="search-box" id="searchBox" placeholder="🔍 搜索对话..." oninput="filterConversations()">')
    parts.append('<div class="conv-list" id="convList">')

    for i, conv in enumerate(conversations):
        pinned = ' 📌' if conv.is_pinned else ''
        assistant_name = assistants.get(conv.assistant_id, "")
        badge = f' <span class="assistant-badge">{escape(assistant_name)}</span>' if assistant_name else ''
        msg_count = len(conv.messages)
        parts.append(
            f'<div class="conv-item" data-index="{i}" onclick="showConversation({i})" '
            f'data-title="{escape(conv.title)}">'
            f'<div class="conv-title">{pinned}{escape(conv.title)}{badge}</div>'
            f'<div class="conv-meta">{conv.update_at}  ·  {msg_count} 条消息</div>'
            f'</div>'
        )

    parts.append('</div></div>')
    return "\n".join(parts)


def _build_main(conversations: list[Conversation], assistants: dict, memories: list) -> str:
    """构建主内容区。"""
    parts = []
    parts.append('<div class="main" id="main">')
    parts.append('<button class="menu-btn" onclick="toggleSidebar()">☰</button>')

    # Welcome
    parts.append('<div class="welcome" id="welcome"><div class="welcome-inner">')
    parts.append('<h1>📱 RikkaHub 对话浏览器</h1>')
    parts.append(f'<p>共 {len(conversations)} 条对话记录</p>')
    if memories:
        parts.append(f'<p>🧠 {len(memories)} 条 AI 记忆</p>')
    parts.append('<p class="hint">← 从左侧选择一个对话开始浏览</p>')
    parts.append('</div></div>')

    # Conversation views
    for i, conv in enumerate(conversations):
        parts.append(f'<div class="conv-view" id="conv-{i}" style="display:none">')
        pin = '📌 ' if conv.is_pinned else ''
        parts.append(f'<div class="conv-header"><h2>{pin}{escape(conv.title)}</h2>')
        parts.append(f'<div class="conv-info">创建: {conv.create_at}  ·  更新: {conv.update_at}  ·  {len(conv.messages)} 条消息</div></div>')
        parts.append('<div class="messages">')

        for msg in conv.messages:
            parts.append(_render_message(msg))

        parts.append('</div></div>')

    parts.append('</div>')
    return "\n".join(parts)


def _render_message(msg: Message) -> str:
    """渲染一条消息。"""
    role = msg.role.lower()
    role_label = {"user": "👤 User", "assistant": "🤖 Assistant", "system": "⚙️ System"}.get(role, msg.role)

    parts = []
    parts.append(f'<div class="message {role}">')
    parts.append(f'<div class="msg-header"><span class="role-label">{role_label}</span>')

    extras = []
    if msg.created_at:
        extras.append(str(msg.created_at))
    if msg.branch_count > 1:
        extras.append(f'分支 {msg.branch_index+1}/{msg.branch_count}')
    if msg.usage:
        tokens = msg.usage.get("total_tokens", 0)
        if tokens:
            extras.append(f'{tokens} tokens')
    if extras:
        parts.append(f'<span class="msg-meta">{" · ".join(extras)}</span>')

    parts.append('</div><div class="msg-body">')

    # 非推理部分先渲染，推理部分放最后
    reasoning = [p for p in msg.parts if p.type == "reasoning"]
    other = [p for p in msg.parts if p.type != "reasoning"]
    for part in other:
        parts.append(_render_part(part))
    for part in reasoning:
        parts.append(_render_part(part))

    # Translation
    if msg.translation:
        parts.append(f'<div class="translation"><strong>翻译:</strong> {escape(msg.translation)}</div>')

    # Citations (collapsible)
    citations = [a for a in msg.annotations if a.get("type") == "url_citation"]
    if citations:
        parts.append(f'<details class="citations"><summary>🔗 {len(citations)} 条引用</summary><div class="citations-list">')
        for ann in citations:
            parts.append(f'<div class="annotation"><a href="{escape(ann["url"])}" target="_blank">{escape(ann.get("title") or ann["url"])}</a></div>')
        parts.append('</div></details>')

    parts.append('</div></div>')
    return "\n".join(parts)


def _render_part(part: MessagePart) -> str:
    """渲染消息的一个部分为 HTML。"""
    t = part.type

    if t == "text":
        if not part.text.strip():
            return ""
        return f'<div class="part-text">{simple_markdown(part.text)}</div>'

    if t == "reasoning":
        if not part.text.strip():
            return ""
        return (
            '<details class="reasoning">'
            '<summary>💭 思考过程</summary>'
            f'<div class="reasoning-content">{simple_markdown(part.text)}</div>'
            '</details>'
        )

    if t == "image":
        if part.url.startswith("data:"):
            return f'<div class="part-image"><img src="{part.url}" alt="image" loading="lazy"></div>'
        return f'<div class="part-image"><span class="file-ref">🖼️ 图片: {escape(part.url)}</span></div>'

    if t == "document":
        name = part.file_name or "文档"
        return f'<div class="part-file">📄 {escape(name)} <span class="mime">{escape(part.mime)}</span></div>'

    if t == "video":
        return f'<div class="part-file">🎬 视频: {escape(part.url)}</div>'

    if t == "audio":
        return f'<div class="part-file">🔊 音频: {escape(part.url)}</div>'

    if t == "tool":
        friendly_name = {
            "memory_tool": "🧠 记忆操作",
            "search_web": "🔍 网页搜索",
            "scrape_web": "🌐 网页抓取",
        }.get(part.tool_name, f"🔧 {part.tool_name}")

        try:
            input_obj = json.loads(part.input) if part.input.strip() else {}
            input_display = json.dumps(input_obj, indent=2, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            input_display = part.input

        output_html = ""
        if part.output:
            output_rendered = "".join(_render_part(op) for op in part.output)
            output_html = f'<div class="tool-output"><strong>输出:</strong>{output_rendered}</div>'

        return (
            '<details class="tool-call">'
            f'<summary>{friendly_name}</summary>'
            f'<div class="tool-body">'
            f'<pre class="tool-input">{escape(input_display)}</pre>'
            f'{output_html}'
            f'</div>'
            '</details>'
        )

    return ""
