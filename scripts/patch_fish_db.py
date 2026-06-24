"""
patch_fish_db.py — 魚図鑑DBに「サムネイル」(files型)プロパティを追加
"""

import os, json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
load_dotenv(Path("/Users/harutakizawa/Desktop/claude code/my-hq-bot/.env"))

from notion_client import Client

notion = Client(auth=os.getenv("NOTION_TOKEN"))

ids_path = Path(__file__).resolve().parent.parent / "data" / "notion_ids.json"
fish_db_id = json.loads(ids_path.read_text())["fish_db"]

notion.databases.update(
    database_id=fish_db_id,
    properties={"サムネイル": {"files": {}}},
)
print("✅ 「サムネイル」(files型) プロパティを追加しました")
