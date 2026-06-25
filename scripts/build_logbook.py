"""
Dive Logbook Builder
Notionから全データを取得して静的HTMLを生成する。

出力:
  docs/index.html              ← ホームページ（セッション一覧）
  docs/sessions/<日付_場所>.html ← 個別セッションページ
"""
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")
load_dotenv(Path("/Users/harutakizawa/Desktop/claude code/my-hq-bot/.env"))

from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup
from lib.notion_api import NotionDiveClient

_ids = json.loads((ROOT / "data" / "notion_ids.json").read_text())
notion = NotionDiveClient(
    os.getenv("NOTION_TOKEN"), _ids["dive_log_db"], _ids["fish_db"], _ids["photo_db"]
)

LOCATION_CACHE_PATH = ROOT / "data" / "locations_cache.json"
OUTPUT_DIR    = ROOT / "docs"
SESSIONS_DIR  = OUTPUT_DIR / "sessions"
FISH_THUMB_DIR = OUTPUT_DIR / "fish_thumbs"


# ── Notionプロパティ取得ヘルパー ──────────────────────────────────────────────
def _txt(props, key):
    p = props.get(key, {})
    rt = p.get("rich_text") or p.get("title") or []
    return rt[0]["plain_text"] if rt else ""

def _num(props, key):
    p = props.get(key)
    return p["number"] if p and p.get("number") is not None else None

def _date(props, key):
    p = props.get(key)
    return p["date"]["start"] if p and p.get("date") else None

def _select(props, key):
    p = props.get(key)
    return p["select"]["name"] if p and p.get("select") else None

def _relation_ids(props, key):
    return [r["id"] for r in props.get(key, {}).get("relation", [])]

def _files(props, key):
    out = []
    for f in props.get(key, {}).get("files", []):
        if f.get("type") == "external":
            out.append(f["external"]["url"])
        elif f.get("file"):
            out.append(f["file"]["url"])
    return out

def _page_url(page):
    return f"https://www.notion.so/{page['id'].replace('-', '')}"


# ── Jinja2フィルタ ────────────────────────────────────────────────────────────
def stars_to_html(stars: str) -> Markup:
    if not stars:
        return Markup("")
    html = stars.replace("★", '<span class="star filled">★</span>').replace(
        "☆", '<span class="star empty">☆</span>'
    )
    return Markup(html)


# ── 場所説明 (Claude Haiku, キャッシュ) ──────────────────────────────────────
def get_location_desc(location: str, cache: dict) -> str:
    if location in cache:
        return cache[location]
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": (
                    f"ダイビングスポット「{location}」について、"
                    "日本語で3〜4文の魅力的な紹介文を書いてください。"
                    "海の様子、地形、生き物の特徴などを含めてください。"
                    "マークダウンや記号は使わず、自然な文章で。"
                ),
            }],
        )
        desc = msg.content[0].text.strip()
        cache[location] = desc
        return desc
    except Exception as e:
        print(f"  [warn] 場所説明生成失敗 ({location}): {e}")
        return ""


# ── Notionページのパース ──────────────────────────────────────────────────────
def parse_dive(page: dict) -> dict:
    p = page["properties"]
    return {
        "id":          page["id"],
        "url":         _page_url(page),
        "date":        _date(p, "日付"),
        "number":      _num(p, "何本目か"),
        "location":    _txt(p, "場所"),
        "point":       _txt(p, "ポイント"),
        "start_time":  _txt(p, "開始時刻"),
        "end_time":    _txt(p, "終了時刻"),
        "duration":    _num(p, "潜水時間"),
        "max_depth":   _num(p, "Max Depth"),
        "weight":      _num(p, "ウェイト"),
        "weather":     _select(p, "天気"),
        "wave_height": _num(p, "波の高さ(m)"),
        "water_temp":  _num(p, "水温(℃)"),
        "cost":        _num(p, "かかった金額"),
        "comment":     _txt(p, "コメント"),
        "video_links": _txt(p, "動画リンク"),
        "fish_ids":    _relation_ids(p, "見れた魚"),
    }

def parse_fish(page: dict) -> dict:
    p = page["properties"]
    thumb = _files(p, "サムネイル")
    return {
        "id":              page["id"],
        "name":            _txt(p, "名前"),
        "english_name":    _txt(p, "英名"),
        "scientific_name": _txt(p, "学名"),
        "category":        _select(p, "分類"),
        "order":           _txt(p, "目"),
        "family":          _txt(p, "科"),
        "genus":           _txt(p, "属"),
        "memo":            _txt(p, "メモ"),
        "rarity":          _txt(p, "レア度"),
        "popularity":      _txt(p, "人気"),
        "photo_ease":      _txt(p, "撮りやすさ"),
        "first_seen":      _date(p, "初目撃日"),
        "thumbnail":       thumb[0] if thumb else "",
    }

def parse_photo_log(page: dict) -> dict:
    p = page["properties"]
    raw = _txt(p, "写真")
    entries = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if " | " in line:
            url, cap = line.split(" | ", 1)
            url = url.strip()
        else:
            url, cap = line, ""
        # photos/ で始まる = アップロード済みローカル画像
        # それ以外 = 外部リンク（Google Photos等）→ クリックで開くだけ
        is_local = url.startswith("photos/")
        entries.append({"url": url, "caption": cap.strip(), "is_local": is_local})
    return {
        "date":     _date(p, "日付"),
        "location": _txt(p, "場所"),
        "photos":   entries,
        "comment":  _txt(p, "コメント"),
    }


# ── 動画リンク処理 ────────────────────────────────────────────────────────────
def parse_video_links(raw: str) -> list:
    if not raw:
        return []
    return [u.strip() for u in re.split(r"[\n,]+", raw) if u.strip()]

def youtube_embed(url: str):
    m = re.search(r"(?:youtu\.be/|v=|shorts/)([A-Za-z0-9_-]{11})", url)
    return f"https://www.youtube.com/embed/{m.group(1)}" if m else None


# ── ファイル名生成（安全な文字のみ） ─────────────────────────────────────────
def download_fish_thumbnail(fish_id: str, url: str, thumb_dir: Path) -> str:
    """NotionのS3署名付きURLをローカルに保存して相対パスを返す"""
    if not url:
        return ""
    local_path = thumb_dir / f"{fish_id.replace('-', '')}.jpg"
    if local_path.exists():
        return f"../fish_thumbs/{local_path.name}"
    try:
        import urllib.request
        urllib.request.urlretrieve(url, local_path)
        return f"../fish_thumbs/{local_path.name}"
    except Exception as e:
        print(f"  [warn] サムネイル取得失敗 ({fish_id}): {e}")
        return ""


def make_session_filename(date_str: str, location: str) -> str:
    safe_loc = re.sub(r"[^\w぀-鿿]", "_", location)
    return f"{date_str}_{safe_loc}.html"


# ── メインビルド ──────────────────────────────────────────────────────────────
def build():
    print("📥 Notionからデータ取得中...")
    raw_dives  = notion.get_all_dive_logs()
    raw_fish   = notion.get_all_fish()
    raw_photos = notion.get_all_photo_logs() if _ids.get("photo_db") else []

    dives      = [parse_dive(p) for p in raw_dives]
    fish_index = {f["id"]: f for f in [parse_fish(p) for p in raw_fish]}
    photos     = [parse_photo_log(p) for p in raw_photos]

    print(f"  ダイブ {len(dives)}本 / 魚 {len(fish_index)}種 / 写真ログ {len(photos)}件")

    # 場所キャッシュ読み込み
    loc_cache = json.loads(LOCATION_CACHE_PATH.read_text()) if LOCATION_CACHE_PATH.exists() else {}

    # 写真を (日付, 場所) でグループ化
    photo_map = defaultdict(list)
    for pl in photos:
        photo_map[(pl["date"], pl["location"])].extend(pl["photos"])

    # セッション構築
    session_map = defaultdict(list)
    for d in dives:
        session_map[(d["date"], d["location"])].append(d)

    sessions = []
    for (date_str, location), dive_list in sorted(session_map.items()):
        dive_list.sort(key=lambda d: d["number"] or 0)

        seen_fish_ids = set()
        for d in dive_list:
            seen_fish_ids.update(d["fish_ids"])
        seen_fish = sorted(
            [fish_index[fid] for fid in seen_fish_ids if fid in fish_index],
            key=lambda f: f["name"]
        )

        # 写真パスをセッションページ用に調整（docs/sessions/ → ../photos/）
        session_photos = []
        for ph in photo_map.get((date_str, location), []):
            ph = dict(ph)
            if ph["is_local"]:
                ph["url"] = "../" + ph["url"]
            session_photos.append(ph)

        # 動画はダイブ単位で保持
        for d in dive_list:
            d["videos"] = [
                {"url": vl, "embed": youtube_embed(vl)}
                for vl in parse_video_links(d.get("video_links", ""))
            ]

        print(f"  → {date_str} {location} ({len(dive_list)}本)")
        loc_desc = get_location_desc(location, loc_cache)

        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            date_display = dt.strftime("%-m月%-d日")
            year = dt.strftime("%Y")
        except Exception:
            date_display = date_str
            year = date_str[:4]

        numbers = [d["number"] for d in dive_list if d["number"]]
        if numbers:
            dive_range = f"{min(numbers)}〜{max(numbers)}本目" if len(numbers) > 1 else f"{numbers[0]}本目"
        else:
            dive_range = ""

        # ホームページ用サムネイル（docs/ 基準なので ../不要）
        first_local = next((p for p in session_photos if p["is_local"]), None)
        thumb = first_local["url"].replace("../", "") if first_local else ""

        sessions.append({
            "date":         date_str,
            "date_display": date_display,
            "year":         year,
            "location":     location,
            "dives":        dive_list,
            "fish":         seen_fish,
            "photos":       session_photos,
            "loc_desc":     loc_desc,
            "dive_range":   dive_range,
            "thumb":        thumb,
            "filename":     make_session_filename(date_str, location),
        })

    # 場所キャッシュ保存
    LOCATION_CACHE_PATH.write_text(json.dumps(loc_cache, ensure_ascii=False, indent=2))

    # サマリー統計
    total_duration = sum(d["duration"] or 0 for d in dives)
    max_depth_ever = max((d["max_depth"] or 0 for d in dives), default=0)
    max_dive_number = max((d["number"] or 0 for d in dives), default=0)
    summary = {
        "total_dives":     max_dive_number,  # 通算本数（最大の何本目か）
        "total_species":   len(fish_index),
        "total_locations": len({d["location"] for d in dives if d["location"]}),
        "total_hours":     total_duration // 60,
        "total_mins":      total_duration % 60,
        "max_depth":       max_depth_ever,
        "first_date":      dives[0]["date"] if dives else "",
        "last_date":       dives[-1]["date"] if dives else "",
    }

    # 魚サムネイルをローカルにダウンロード（S3署名付きURLは期限切れになるため）
    print("\n🐠 魚サムネイルをダウンロード中...")
    FISH_THUMB_DIR.mkdir(exist_ok=True)
    for f in fish_index.values():
        if f["thumbnail"]:
            local_url = download_fish_thumbnail(f["id"], f["thumbnail"], FISH_THUMB_DIR)
            f["thumbnail"] = local_url  # ローカルパスに差し替え

    build_date = datetime.now().strftime("%Y年%-m月%-d日")

    # Jinja2環境
    OUTPUT_DIR.mkdir(exist_ok=True)
    SESSIONS_DIR.mkdir(exist_ok=True)
    env = Environment(
        loader=FileSystemLoader(str(ROOT / "output_templates")),
        autoescape=True
    )
    env.filters["stars_html"] = stars_to_html

    # ① ホームページ生成
    home_html = env.get_template("home.html").render(
        sessions=sessions,
        summary=summary,
        build_date=build_date,
    )
    (OUTPUT_DIR / "index.html").write_text(home_html, encoding="utf-8")
    print(f"\n✅ ホームページ → docs/index.html")

    # ② 個別セッションページ生成
    session_tmpl = env.get_template("session.html")
    for s in sessions:
        session_html = session_tmpl.render(s=s, build_date=build_date)
        out_path = SESSIONS_DIR / s["filename"]
        out_path.write_text(session_html, encoding="utf-8")
        print(f"   ✅ {s['date_display']} {s['location']} → docs/sessions/{s['filename']}")

    # ③ お魚図鑑ページ生成
    fish_list = sorted(fish_index.values(), key=lambda f: (f["category"] or "", f["name"]))
    categories = sorted({f["category"] for f in fish_list if f["category"]})
    fish_html = env.get_template("fish.html").render(
        fish_list=fish_list,
        categories=categories,
        total=len(fish_list),
        build_date=build_date,
    )
    (OUTPUT_DIR / "fish.html").write_text(fish_html, encoding="utf-8")
    print(f"✅ お魚図鑑 → docs/fish.html")

    print(f"\n合計 {2 + len(sessions)} ファイルを生成しました")
    return len(sessions)


if __name__ == "__main__":
    build()
