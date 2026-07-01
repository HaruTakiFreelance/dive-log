"""
patch_dive_db_buddy.py — ダイブログDBに「バディ」(rich_text型)プロパティを追加
"""

import os, json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
load_dotenv(Path("/Users/harutakizawa/Desktop/claude code/my-hq-bot/.env"))

from notion_client import Client

notion = Client(auth=os.getenv("NOTION_TOKEN"))

ids_path = Path(__file__).resolve().parent.parent / "data" / "notion_ids.json"
dive_db_id = json.loads(ids_path.read_text())["dive_log_db"]

notion.databases.update(
    database_id=dive_db_id,
    properties={"バディ": {"rich_text": {}}},
)
print("✅ 「バディ」(rich_text型) プロパティをダイブログDBに追加しました")
