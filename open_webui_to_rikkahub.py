#!/usr/bin/env python3
import os
import sys
import json
import uuid
import sqlite3
import zipfile
import tempfile
import shutil
import argparse
from datetime import datetime, timezone

DEFAULT_ASSISTANT_ID = "0950e2dc-9bd5-4801-afa3-aa887aa36b4e"

def parse_args():
    parser = argparse.ArgumentParser(
        description="将 Open-WebUI 导出的聊天记录合并并导入至 RikkaHub 的备份 ZIP 文件中。"
    )
    parser.add_argument(
        "-i", "--input-zip",
        required=True,
        help="RikkaHub 的备份 ZIP 原始文件路径 (例如 rikkahub_backup.zip)"
    )
    parser.add_argument(
        "-w", "--webui-json",
        required=True,
        help="Open-WebUI 导出的聊天记录 JSON 文件路径"
    )
    parser.add_argument(
        "-o", "--output-zip",
        help="生成的包含导入聊天的新备份 ZIP 文件路径 (默认在原文件名后加 _imported)"
    )
    parser.add_argument(
        "-a", "--assistant-id",
        default=DEFAULT_ASSISTANT_ID,
        help=f"导入的会话关联的助手 ID (UUID 格式，默认: {DEFAULT_ASSISTANT_ID})"
    )
    return parser.parse_args()

def generate_stable_uuid(*parts):
    # 生成稳定的 UUID，保证重复运行脚本不会产生重复数据
    namespace = uuid.NAMESPACE_DNS
    name = ":".join(str(p) for p in parts)
    return str(uuid.uuid5(namespace, name))

def format_local_datetime(timestamp_s):
    # 格式化本地时间 (RikkaHub 使用的 LocalDateTime 格式为 ISO-8601，如 'YYYY-MM-DDTHH:MM:SS')
    dt = datetime.fromtimestamp(timestamp_s)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")

def format_utc_instant(timestamp_s):
    # 格式化 UTC Instant 格式，带 Z 结尾
    dt = datetime.fromtimestamp(timestamp_s, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def extract_text(message_obj):
    content = message_obj.get("content", "")
    if content and str(content).strip():
        return str(content)
    
    # 尝试从 output 数组中提取
    output_list = message_obj.get("output", [])
    if isinstance(output_list, list):
        texts = []
        for out in output_list:
            if isinstance(out, dict) and out.get("type") == "message":
                sub_content = out.get("content", [])
                if isinstance(sub_content, list):
                    for sub in sub_content:
                        if isinstance(sub, dict) and "text" in sub:
                            texts.append(sub["text"])
        if texts:
            return "".join(texts).strip()
    return ""

def parse_parts(message_obj, msg_timestamp):
    parts = []
    output_list = message_obj.get("output", [])
    
    if isinstance(output_list, list) and len(output_list) > 0:
        for out in output_list:
            if not isinstance(out, dict):
                continue
            out_type = out.get("type")
            sub_content = out.get("content", [])
            if not isinstance(sub_content, list):
                continue
            
            text_parts = []
            for sub in sub_content:
                if isinstance(sub, dict) and "text" in sub:
                    text_parts.append(sub["text"])
            text = "".join(text_parts)
            
            if not text.strip():
                continue
                
            if out_type == "reasoning":
                parts.append({
                    "type": "reasoning",
                    "reasoning": text,
                    "createdAt": format_utc_instant(msg_timestamp),
                    "finishedAt": format_utc_instant(msg_timestamp),
                    "metadata": None
                })
            elif out_type == "message":
                parts.append({
                    "type": "text",
                    "text": text,
                    "metadata": None
                })
                
    if not parts:
        content = message_obj.get("content", "")
        if content and str(content).strip():
            parts.append({
                "type": "text",
                "text": str(content),
                "metadata": None
            })
            
    return parts

def parse_usage(usage_obj):
    if not isinstance(usage_obj, dict):
        return None
    prompt_tokens = usage_obj.get("prompt_tokens") or usage_obj.get("input_tokens") or 0
    completion_tokens = usage_obj.get("completion_tokens") or usage_obj.get("output_tokens") or 0
    total_tokens = usage_obj.get("total_tokens") or (prompt_tokens + completion_tokens)
    return {
        "promptTokens": prompt_tokens,
        "completionTokens": completion_tokens,
        "totalTokens": total_tokens
    }

def process_openwebui_chat(chat_entry, assistant_id):
    chat_id = chat_entry.get("id")
    if not chat_id:
        return None
    
    title = chat_entry.get("title") or "Open-WebUI 导入的会话"
    chat_payload = chat_entry.get("chat", {})
    history = chat_payload.get("history", {})
    current_id = history.get("currentId")
    messages_map = history.get("messages", {})
    
    if not current_id or current_id not in messages_map:
        return None
        
    # 从叶子节点 currentId 开始溯源重建消息链
    chain = []
    temp_id = current_id
    visited = set()
    while temp_id and temp_id not in visited:
        visited.add(temp_id)
        msg_obj = messages_map.get(temp_id)
        if not isinstance(msg_obj, dict):
            break
        chain.append(msg_obj)
        temp_id = msg_obj.get("parentId")
    
    # 反转为按时间由远及近的顺序 (从 Root 到 Leaf)
    chain.reverse()
    if not chain:
        return None
        
    # 提取系统提示词 (会话开始前的系统提示词)
    custom_system_prompt_parts = []
    reached_conversation = False
    
    conversation_messages = []
    
    for msg in chain:
        role = msg.get("role")
        if role == "system" and not reached_conversation:
            sys_text = extract_text(msg).strip()
            if sys_text:
                custom_system_prompt_parts.append(sys_text)
            continue
        
        reached_conversation = True
        conversation_messages.append(msg)
        
    custom_system_prompt = "\n\n".join(custom_system_prompt_parts) if custom_system_prompt_parts else ""
    
    # 转换会话节点
    nodes = []
    min_timestamp = None
    max_timestamp = None
    
    for index, msg in enumerate(conversation_messages):
        msg_id = msg.get("id") or f"{chat_id}_msg_{index}"
        role = msg.get("role")
        if role not in ["user", "assistant", "system", "tool"]:
            continue
            
        timestamp = msg.get("timestamp") or int(datetime.now().timestamp())
        # 有些时间戳是毫秒，有些是秒，进行规范化
        if timestamp > 99999999999:
            timestamp_s = timestamp / 1000.0
        else:
            timestamp_s = float(timestamp)
            
        if min_timestamp is None or timestamp_s < min_timestamp:
            min_timestamp = timestamp_s
        if max_timestamp is None or timestamp_s > max_timestamp:
            max_timestamp = timestamp_s
            
        parts = parse_parts(msg, timestamp_s)
        if not parts:
            continue # 跳过空白节点
            
        ui_msg = {
            "id": generate_stable_uuid("openwebui", "message", msg_id),
            "role": role,
            "parts": parts,
            "annotations": [],
            "createdAt": format_local_datetime(timestamp_s),
            "finishedAt": None,
            "modelId": None,
            "usage": parse_usage(msg.get("usage")),
            "translation": None
        }
        
        nodes.append({
            "id": generate_stable_uuid("openwebui", "node", chat_id, msg_id),
            "messages": [ui_msg],
            "select_index": 0
        })
        
    if not nodes:
        return None
        
    create_at_ms = int((min_timestamp or datetime.now().timestamp()) * 1000)
    update_at_ms = int((max_timestamp or datetime.now().timestamp()) * 1000)
    
    conv_id = generate_stable_uuid("openwebui", "session", chat_id)
    
    return {
        "id": conv_id,
        "assistant_id": assistant_id,
        "title": title,
        "create_at": create_at_ms,
        "update_at": update_at_ms,
        "custom_system_prompt": custom_system_prompt,
        "nodes": nodes
    }

def main():
    args = parse_args()
    
    if not os.path.exists(args.input_zip):
        print(f"错误: 找不到 RikkaHub 备份 ZIP 文件 {args.input_zip}")
        sys.exit(1)
    if not os.path.exists(args.webui_json):
        print(f"错误: 找不到 Open-WebUI 导出文件 {args.webui_json}")
        sys.exit(1)
        
    output_zip = args.output_zip
    if not output_zip:
        base, ext = os.path.splitext(args.input_zip)
        output_zip = f"{base}_imported{ext}"
        
    # 1. 解析 Open-WebUI 聊天记录
    print(f"正在解析 Open-WebUI 导出文件: {args.webui_json}")
    try:
        with open(args.webui_json, "r", encoding="utf-8") as f:
            webui_data = json.load(f)
    except Exception as e:
        print(f"错误: 读取 JSON 文件失败 - {e}")
        sys.exit(1)
        
    if not isinstance(webui_data, list):
        print("错误: Open-WebUI 导出数据格式不正确，期望是一个包含 chat 会话的数组 []")
        sys.exit(1)
        
    parsed_conversations = []
    for entry in webui_data:
        res = process_openwebui_chat(entry, args.assistant_id)
        if res:
            parsed_conversations.append(res)
            
    print(f"成功解析出 {len(parsed_conversations)} 个有效会话。")
    if not parsed_conversations:
        print("警告: 没有解析到任何有效会话。")
        sys.exit(0)
        
    # 2. 解压并修改 RikkaHub 数据库
    temp_dir = tempfile.mkdtemp(prefix="rikkahub_import_")
    try:
        print("解压原 RikkaHub 备份 ZIP...")
        with zipfile.ZipFile(args.input_zip, "r") as z:
            z.extractall(temp_dir)
            
        db_path = os.path.join(temp_dir, "rikka_hub.db")
        if not os.path.exists(db_path):
            print(f"错误: 备份包内找不到 rikka_hub.db 数据库文件！")
            sys.exit(1)
            
        print("开始向 SQLite 数据库插入数据...")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 确认表结构存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ConversationEntity';")
        if not cursor.fetchone():
            print("错误: 数据库中未找到 ConversationEntity 表，请确保备份文件正确。")
            sys.exit(1)
            
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='message_node';")
        if not cursor.fetchone():
            print("错误: 数据库中未找到 message_node 表，请确保备份文件正确。")
            sys.exit(1)
            
        inserted_conv_count = 0
        inserted_node_count = 0
        skipped_count = 0
        
        for conv in parsed_conversations:
            conv_id = conv["id"]
            
            # 检查会话是否已存在
            cursor.execute("SELECT 1 FROM ConversationEntity WHERE id = ?", (conv_id,))
            if cursor.fetchone():
                skipped_count += 1
                continue
                
            # 插入 ConversationEntity
            # id, assistant_id, title, nodes, create_at, update_at, suggestions, is_pinned, custom_system_prompt, mode_injection_ids, lorebook_ids, workspace_cwd, folder_id
            cursor.execute(
                """
                INSERT INTO ConversationEntity 
                (id, assistant_id, title, nodes, create_at, update_at, suggestions, is_pinned, custom_system_prompt, mode_injection_ids, lorebook_ids, workspace_cwd, folder_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conv_id,
                    conv["assistant_id"],
                    conv["title"],
                    "[]",  # nodes
                    conv["create_at"],
                    conv["update_at"],
                    "[]",  # suggestions
                    0,     # is_pinned
                    conv["custom_system_prompt"],
                    "[]",  # mode_injection_ids
                    "[]",  # lorebook_ids
                    "",    # workspace_cwd
                    ""     # folder_id
                )
            )
            inserted_conv_count += 1
            
            # 插入 message_node
            # id, conversation_id, node_index, messages, select_index
            for node_idx, node in enumerate(conv["nodes"]):
                cursor.execute(
                    """
                    INSERT INTO message_node (id, conversation_id, node_index, messages, select_index)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        node["id"],
                        conv_id,
                        node_idx,
                        json.dumps(node["messages"], ensure_ascii=False),
                        node["select_index"]
                    )
                )
                inserted_node_count += 1
                
        conn.commit()
        conn.close()
        print(f"数据插入完成：导入了 {inserted_conv_count} 个会话，共计 {inserted_node_count} 个消息节点。(跳过了 {skipped_count} 个已存在的会话)")
        
        # 3. 打包生成新的备份 ZIP
        print(f"正在打包并生成新备份文件: {output_zip}")
        # 清除任何存在的旧合并文件
        if os.path.exists(output_zip):
            os.remove(output_zip)
            
        with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as z:
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, temp_dir)
                    # 避免把数据库的临时或缓存文件打包
                    if file in ["rikka_hub-wal", "rikka_hub-shm", "rikka_hub.db-wal", "rikka_hub.db-shm"]:
                        continue
                    z.write(full_path, rel_path)
            
            # 写入 0 字节的 WAL 和 SHM 文件，强制在 App 恢复时覆盖并清除设备上的旧缓存，防止冲突闪退
            z.writestr("rikka_hub-wal", b"")
            z.writestr("rikka_hub-shm", b"")
                    
        print(f"\n成功！新生成的备份包已保存至: {output_zip}")
        print("使用步骤:")
        print("1. 将此新备份包发送到您的手机。")
        print("2. 打开 RikkaHub -> 设置 -> 备份与恢复 -> 本地备份恢复 -> 点击「备份文件导入」 -> 选择该 ZIP 文件导入即可。")
        
    finally:
        shutil.rmtree(temp_dir)

if __name__ == "__main__":
    main()
