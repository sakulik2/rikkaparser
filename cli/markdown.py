"""
Markdown 渲染器（纯 Python 实现）。

支持语法：代码块、表格、标题 h1-h6、水平线、引用块、
有序/无序列表、粗体、斜体、删除线、行内代码、链接、图片。
"""

import re
from html import escape


def inline_format(text: str) -> str:
    """处理行内 Markdown 格式，按正确优先级。"""
    # 1. 先提取行内代码，防止内部内容被格式化
    code_spans = []

    def _save_code(m):
        code_spans.append(m.group(1))
        return f'\x00C{len(code_spans)-1}\x00'

    text = re.sub(r'`([^`]+)`', _save_code, text)

    # 2. 图片（在链接之前，防止 ![...] 被链接匹配）
    text = re.sub(
        r'!\[([^\]]*)\]\(([^)]+)\)',
        r'<img src="\2" alt="\1" style="max-width:360px;border-radius:6px">',
        text,
    )
    # 3. 链接
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank">\1</a>', text)

    # 4. 粗斜体 (***text***)
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<strong><em>\1</em></strong>', text)
    # 5. 粗体 (**text** 或 __text__)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'__(.+?)__', r'<strong>\1</strong>', text)
    # 6. 删除线
    text = re.sub(r'~~(.+?)~~', r'<del>\1</del>', text)
    # 7. 斜体 — 仅匹配不与 ** 相邻的单个 *
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<em>\1</em>', text)

    # 8. 还原行内代码
    for i, code in enumerate(code_spans):
        text = text.replace(f'\x00C{i}\x00', f'<code>{code}</code>')

    return text


def simple_markdown(text: str) -> str:
    """Markdown 渲染（纯 Python 实现，支持大多数常用语法）。"""
    lines = text.split("\n")
    result = []
    in_code_block = False
    code_lang = ""
    code_lines = []
    in_table = False
    table_rows = []

    def flush_table():
        nonlocal in_table, table_rows
        if not table_rows:
            return
        html = '<div class="md-table-wrap"><table>'
        for ri, row in enumerate(table_rows):
            cells = [c.strip() for c in row.split("|")]
            if cells and cells[0] == "":
                cells = cells[1:]
            if cells and cells[-1] == "":
                cells = cells[:-1]
            # 跳过分隔行 (|---|---|)
            if all(c.strip().replace("-", "").replace(":", "") == "" for c in cells):
                continue
            tag = "th" if ri == 0 else "td"
            html += "<tr>" + "".join(f"<{tag}>{inline_format(escape(c))}</{tag}>" for c in cells) + "</tr>"
        html += "</table></div>"
        result.append(html)
        table_rows = []
        in_table = False

    for line in lines:
        stripped = line.strip()

        # 代码块
        if stripped.startswith("```"):
            if in_table:
                flush_table()
            if in_code_block:
                code_content = escape("\n".join(code_lines))
                result.append(f'<pre><code class="lang-{escape(code_lang)}">{code_content}</code></pre>')
                code_lines = []
                in_code_block = False
            else:
                code_lang = stripped[3:].strip()
                in_code_block = True
            continue

        if in_code_block:
            code_lines.append(line)
            continue

        # 表格检测
        if "|" in stripped and stripped.startswith("|"):
            if not in_table:
                in_table = True
                table_rows = []
            table_rows.append(stripped)
            continue
        else:
            if in_table:
                flush_table()

        # 水平分割线
        if re.match(r'^(\s*[-*_]\s*){3,}$', stripped):
            result.append('<hr>')
            continue

        # 标题 (h1-h6)
        heading_match = re.match(r'^(#{1,6})\s+(.+)$', line)
        if heading_match:
            level = len(heading_match.group(1))
            tag = f"h{min(level + 1, 6)}"
            content = inline_format(escape(heading_match.group(2)))
            result.append(f"<{tag}>{content}</{tag}>")
            continue

        # 空行 — 直接跳过不渲染
        if not stripped:
            continue

        # 引用块
        if stripped.startswith("> "):
            quote_text = inline_format(escape(stripped[2:]))
            result.append(f'<blockquote>{quote_text}</blockquote>')
            continue
        if stripped == ">":
            result.append('<blockquote><br></blockquote>')
            continue

        # 行内格式
        escaped = escape(line)
        formatted = inline_format(escaped)

        # 无序列表
        ul_match = re.match(r'^(\s*)([-*+])\s+(.+)$', line)
        if ul_match:
            indent = len(ul_match.group(1))
            margin = indent * 12
            content = inline_format(escape(ul_match.group(3)))
            result.append(f'<div class="md-li" style="margin-left:{margin}px">• {content}</div>')
            continue

        # 有序列表
        ol_match = re.match(r'^(\s*)(\d+)[.)]\s+(.+)$', line)
        if ol_match:
            indent = len(ol_match.group(1))
            margin = indent * 12
            num = ol_match.group(2)
            content = inline_format(escape(ol_match.group(3)))
            result.append(f'<div class="md-li" style="margin-left:{margin}px">{num}. {content}</div>')
            continue

        result.append(f"<p>{formatted}</p>")

    # 未关闭的代码块
    if in_code_block and code_lines:
        code_content = escape("\n".join(code_lines))
        result.append(f'<pre><code>{code_content}</code></pre>')

    # 未关闭的表格
    if in_table:
        flush_table()

    return "\n".join(result)
