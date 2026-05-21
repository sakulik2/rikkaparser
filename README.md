# chatParser

解析 [RikkaHub](https://github.com/rikkahub/rikkahub) 备份文件，并支持 **Chatbox**（JSON）、**Open-WebUI**（JSON）以及 **Gemini Voyager**（Markdown）等导出文件的解析与查看，生成自适应且可浏览的 HTML / JSON / TXT 静态输出。

## 两种使用方式

### 1. 浏览器版（推荐）

直接打开 [`viewer.html`](viewer.html)，选择备份文件即可。

- 手机 / 电脑 / 平板通用
- 无需安装任何依赖
- 支持标题搜索和全文搜索
- 支持解析本地 RikkaHub 备份 zip、Chatbox 导出 json、Open-WebUI 导出 json 以及 Gemini 导出 md 文件

### 2. CLI 命令行版

CLI 解析器支持对备份/导出文件进行解析、筛选、搜索及多格式导出（支持 `.zip`、`.json`、`.md` 格式输入）：

```bash
# 1. 解析并生成静态 HTML 报告（默认输出为 rikkahub_chats.html，支持公式与代码高亮）
python -m cli.parser backup.zip
python -m cli.parser chatbox_export.json -o chatbox_chats.html
python -m cli.parser gemini_voyager.md -o gemini_chats.html

# 2. 搜索所有消息内容
python -m cli.parser backup.zip --search "关键词"

# 3. 导出为标准 JSON
python -m cli.parser backup.zip --export json -o output.json

# 4. 导出为纯文本（方便 grep）
python -m cli.parser backup.zip --export txt -o output.txt

# 5. 导出为 Chatbox 可导入的 JSON 格式
python -m cli.parser backup.zip --export chatbox -o chatbox_import.json

# 6. 条件筛选后生成静态 HTML
python -m cli.parser backup.zip --filter-assistant "智能助手"
python -m cli.parser backup.zip --filter-date 2025-01-01 2025-06-30

# 7. 列出所有对话的摘要列表
python -m cli.parser backup.zip --list
```

## 项目结构

```
├── viewer.html            # 纯前端浏览器（单文件，自包含，解析本地备份）
├── cli/
│   ├── parser.py          # CLI 解析入口
│   ├── models.py          # 数据模型定义
│   ├── db_reader.py       # 数据库读取与 json/md 文件分流解析层
│   ├── markdown.py        # 纯 Python 实现的 Markdown 渲染器（含高亮语言清洗）
│   └── html_gen.py        # 静态 HTML 生成（含 KaTeX & Prism.js 依赖注入）
└── templates/
    ├── style.css          # 全局样式模板（自适应双态设计）
    └── script.js          # 全局脚本模板（对话切换、搜索过滤、高亮绑定）
```

## 依赖关系

- Python 3.10+（标准库即可，无第三方依赖）
- 浏览器版无需 Python
