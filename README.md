# RikkaHub Backup Parser

解析 [RikkaHub](https://github.com/rikkahub/rikkahub)（Android LLM 聊天应用）的备份文件，生成可浏览的 HTML / JSON / TXT 输出。

## 两种使用方式

### 1. 浏览器版（推荐）

直接打开 [`viewer.html`](viewer.html)，选择备份 zip 文件即可。

- 手机 / 电脑 / 平板通用
- 无需安装任何依赖
- 支持标题搜索和全文搜索

### 2. CLI 命令行版

```bash
# 生成 HTML 浏览器
python -m cli.parser backup.zip

# 搜索消息内容
python -m cli.parser backup.zip --search "关键词"

# 导出为 JSON
python -m cli.parser backup.zip --export json -o output.json

# 导出为纯文本（方便 grep）
python -m cli.parser backup.zip --export txt -o output.txt

# 按助手筛选
python -m cli.parser backup.zip --filter-assistant "智能助手"

# 按日期范围筛选
python -m cli.parser backup.zip --filter-date 2025-01-01 2025-06-30

# 列出所有对话
python -m cli.parser backup.zip --list
```

## 项目结构

```
├── rikkahub_viewer.html   # 纯前端浏览器（单文件，自包含）
├── cli/
│   ├── parser.py          # CLI 入口
│   ├── models.py          # 数据模型
│   ├── db_reader.py       # 数据库读取
│   ├── markdown.py        # Markdown 渲染器
│   └── html_gen.py        # HTML 生成
├── templates/
│   ├── style.css          # 样式模板
│   └── script.js          # 脚本模板
└── tests/
    ├── test_markdown.py   # Markdown 渲染测试
    └── test_parser.py     # 消息解析测试
```

## 依赖

- Python 3.10+（标准库即可，无第三方依赖）
- 浏览器版无需 Python
