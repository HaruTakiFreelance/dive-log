"""
setup_review_db.py — セッション総評DBを新規作成し、notion_ids.jsonにIDを保存する

「その日のダイビングというかイベント全体についての総評」を
日付+場所単位で記録するための新規Notion DB。

Usage: python scripts/setup_review_db.py
"""

import json
import sys
from pathlib import Path

from dotenv import load_dotenv
import os

ROOT = Path(__file__).resolve().parent.parent
_local = ROOT / ".env"
if _local.exists():
    load_dotenv(_local)
load_dotenv(Path("/Users/harutakizawa/Desktop/claude code/my-hq-bot/.env"))

from notion_client import Client

TOKEN = os.getenv("NOTION_TOKEN")
if not TOKEN:
    sys.exit("❌ NOTION_TOKEN が未設定")

notion = Client(auth=TOKEN)

ids_path = ROOT / "data" / "notion_ids.json"
ids = json.loads(ids_path.read_text())
parent_page_id = ids["parent_page"]

print("セッション総評DB を作成...")
review_db = notion.databases.create(
    parent={"type": "page_id", "page_id": parent_page_id},
    title=[{"type": "text", "text": {"content": "📝 セッション総評"}}],
    properties={
        "名前": {"title": {}},
        "日付": {"date": {}},
        "場所": {"rich_text": {}},
        "総評": {"rich_text": {}},
    },
)
review_db_id = review_db["id"]
print(f"  作成完了: {review_db_id}")

ids["review_db"] = review_db_id
ids_path.write_text(json.dumps(ids, indent=2, ensure_ascii=False))
print(f"\n✅ notion_ids.json に review_db を保存しました")
