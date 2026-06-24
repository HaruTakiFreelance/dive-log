"""
inspect_db.py — Notionダイビングログ「詳細ログ」DBのプロパティ名・型を表示する
Usage: python scripts/inspect_db.py
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# ローカル .env を読み込み（NOTION_DIVE_DB_ID）
_local = Path(__file__).resolve().parent.parent / ".env"
if _local.exists():
    load_dotenv(_local)

# my-hq-bot .env をフォールバック（NOTION_TOKEN）
_fallback = Path("/Users/harutakizawa/Desktop/claude code/my-hq-bot/.env")
if _fallback.exists():
    load_dotenv(_fallback)  # 既にセット済みの値は上書きしない

TOKEN = os.getenv("NOTION_TOKEN")
DB_ID = os.getenv("NOTION_DIVE_DB_ID")

if not TOKEN:
    sys.exit("❌ NOTION_TOKEN が未設定です（my-hq-bot/.env を確認してください）")
if not DB_ID:
    sys.exit("❌ NOTION_DIVE_DB_ID が未設定です（dive-log/.env を確認してください）")

try:
    from notion_client import Client
except ImportError:
    sys.exit("❌ notion-client が未インストールです。`pip install notion-client` を実行してください")

notion = Client(auth=TOKEN)

try:
    db = notion.databases.retrieve(database_id=DB_ID)
except Exception as e:
    sys.exit(
        f"❌ DB取得失敗: {e}\n"
        "→ インテグレーションがDBにconnectされているか確認してください\n"
        "  Notionページ右上「…」→「コネクト」→ インテグレーション名を追加"
    )

title = db["title"][0]["plain_text"] if db.get("title") else "(タイトルなし)"
print(f"\n✅ DB接続成功: {title}")
print(f"   DB ID: {DB_ID}\n")
print(f"{'プロパティ名':<28} {'型':<20} {'備考'}")
print("-" * 72)

for name, prop in sorted(db["properties"].items(), key=lambda x: x[0]):
    ptype = prop["type"]
    note = ""
    if ptype == "select":
        opts = [o["name"] for o in prop["select"]["options"][:4]]
        note = "例: " + " / ".join(opts)
    elif ptype == "multi_select":
        opts = [o["name"] for o in prop["multi_select"]["options"][:4]]
        note = "例: " + " / ".join(opts)
    elif ptype == "relation":
        note = f"関連DB: {prop['relation']['database_id'][:8]}..."
    elif ptype == "formula":
        note = f"式: {prop['formula'].get('expression', '')[:30]}"
    print(f"{name:<28} {ptype:<20} {note}")

print("\n💡 次のステップ:")
print("   1. 上記プロパティ名をもとにマッピング設定を固める")
print("   2. 動画リンク用プロパティ（テキスト型）がなければ追加する")
print("   3. python scripts/fetch_notion.py でデータ取得へ進む")
