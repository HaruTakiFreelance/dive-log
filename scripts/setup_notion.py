"""
setup_notion.py — Notionのダイビングログ環境を一括セットアップ
  1. 詳細ログDBにプロパティを追加
  2. 魚図鑑DBを新規作成
  3. 詳細ログ ↔ 魚図鑑 の双方向relationを設定
  4. memory/notion_ids.json にIDを保存

Usage: python scripts/setup_notion.py
"""

import os, sys, json
from pathlib import Path
from dotenv import load_dotenv

_local = Path(__file__).resolve().parent.parent / ".env"
if _local.exists():
    load_dotenv(_local)
load_dotenv(Path("/Users/harutakizawa/Desktop/claude code/my-hq-bot/.env"))

from notion_client import Client

TOKEN   = os.getenv("NOTION_TOKEN")
DIVE_DB = os.getenv("NOTION_DIVE_DB_ID")

if not TOKEN: sys.exit("❌ NOTION_TOKEN が未設定")
if not DIVE_DB: sys.exit("❌ NOTION_DIVE_DB_ID が未設定")

notion = Client(auth=TOKEN)

# ───────────────────────────────────────────
# Step 1: 詳細ログDBの親ページIDを取得
# ───────────────────────────────────────────
print("Step 1: 詳細ログDB の親ページを確認...")
dive_db = notion.databases.retrieve(database_id=DIVE_DB)
parent = dive_db["parent"]
if parent["type"] != "page_id":
    sys.exit("❌ 詳細ログDBの親がページではありません（block_idの場合はサポート外）")
parent_page_id = parent["page_id"]
print(f"  親ページID: {parent_page_id}")

# ───────────────────────────────────────────
# Step 2: 魚図鑑DBを作成
# ───────────────────────────────────────────
print("\nStep 2: 魚図鑑DB を作成...")
fish_db = notion.databases.create(
    parent={"type": "page_id", "page_id": parent_page_id},
    title=[{"type": "text", "text": {"content": "🐠 魚図鑑"}}],
    properties={
        "名前":         {"title": {}},
        "英名":         {"rich_text": {}},
        "学名":         {"rich_text": {}},
        "分類":         {"select": {"options": [
                            {"name": "魚類",     "color": "blue"},
                            {"name": "甲殻類",   "color": "orange"},
                            {"name": "軟体動物", "color": "purple"},
                            {"name": "棘皮動物", "color": "pink"},
                            {"name": "爬虫類",   "color": "green"},
                            {"name": "哺乳類",   "color": "gray"},
                            {"name": "その他",   "color": "default"},
                        ]}},
        "初目撃日":     {"date": {}},
        "メモ":         {"rich_text": {}},
        "サムネイルURL": {"url": {}},
    },
)
fish_db_id = fish_db["id"]
print(f"  魚図鑑DB作成完了: {fish_db_id}")

# ───────────────────────────────────────────
# Step 3: 詳細ログDBにプロパティを追加
#         （既存の「名前」は触らない）
# ───────────────────────────────────────────
print("\nStep 3: 詳細ログDB にプロパティを追加...")

new_props = {
    "日付":       {"date": {}},
    "何本目か":   {"number": {"format": "number"}},
    "場所":       {"rich_text": {}},
    "ポイント":   {"rich_text": {}},
    "開始時刻":   {"rich_text": {}},
    "終了時刻":   {"rich_text": {}},
    "潜水時間":   {"number": {"format": "number"}},
    "Max Depth":  {"number": {"format": "number"}},
    "ウェイト":   {"number": {"format": "number"}},
    "かかった金額": {"number": {"format": "yen"}},
    "天気":       {"select": {"options": [
                    {"name": "晴れ",   "color": "yellow"},
                    {"name": "曇り",   "color": "gray"},
                    {"name": "雨",     "color": "blue"},
                    {"name": "雪",     "color": "default"},
                  ]}},
    "波の高さ(m)": {"number": {"format": "number"}},
    "水温(℃)":    {"number": {"format": "number"}},
    "動画リンク": {"rich_text": {}},
    # relation は Step 4 で設定
}

notion.databases.update(database_id=DIVE_DB, properties=new_props)
print(f"  {len(new_props)} プロパティを追加しました")

# ───────────────────────────────────────────
# Step 4: 双方向 relation を設定
#   詳細ログ.見れた魚 → 魚図鑑
#   魚図鑑.目撃ダイブ → 詳細ログ（自動作成）
# ───────────────────────────────────────────
print("\nStep 4: relation を設定...")

notion.databases.update(
    database_id=DIVE_DB,
    properties={
        "見れた魚": {
            "relation": {
                "database_id": fish_db_id,
                "type": "dual_property",
                "dual_property": {},
            }
        }
    },
)
print("  詳細ログ ↔ 魚図鑑 の双方向relation設定完了")

# ───────────────────────────────────────────
# Step 5: IDをJSONに保存
# ───────────────────────────────────────────
ids_path = Path(__file__).resolve().parent.parent / "data" / "notion_ids.json"
ids_path.parent.mkdir(exist_ok=True)
ids = {}
if ids_path.exists():
    ids = json.loads(ids_path.read_text())

ids["dive_log_db"]  = DIVE_DB
ids["fish_db"]      = fish_db_id
ids["parent_page"]  = parent_page_id
ids_path.write_text(json.dumps(ids, indent=2, ensure_ascii=False))
print(f"\n✅ セットアップ完了。IDを {ids_path} に保存しました")
print(f"   詳細ログDB : {DIVE_DB}")
print(f"   魚図鑑DB   : {fish_db_id}")
print("\n次のステップ: python app.py でFlaskアプリを起動")
