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
PROFILES_DIR = ROOT / "data" / "depth_profiles"

load_dotenv(ROOT / ".env")
load_dotenv(Path("/Users/harutakizawa/Desktop/claude code/my-hq-bot/.env"))

from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup
from lib.notion_api import NotionDiveClient

_ids = json.loads((ROOT / "data" / "notion_ids.json").read_text())
notion = NotionDiveClient(
    os.getenv("NOTION_TOKEN"), _ids["dive_log_db"], _ids["fish_db"], _ids["photo_db"],
    _ids.get("review_db"),
)

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
        "avg_depth":   _num(p, "平均水深"),
        "weight":      _num(p, "ウェイト"),
        "weather":     _select(p, "天気"),
        "wave_height": _num(p, "波の高さ(m)"),
        "water_temp":  _num(p, "水温(℃)"),
        "cost":        _num(p, "かかった金額"),
        "comment":     _txt(p, "コメント"),
        "video_links": _txt(p, "動画リンク"),
        "buddy":       _txt(p, "バディ"),
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


# ── 深度プロファイル ──────────────────────────────────────────────────────────
def load_depth_profiles() -> dict:
    """(date, start_time) → profile JSON"""
    if not PROFILES_DIR.exists():
        return {}
    result = {}
    for f in PROFILES_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            result[(data["date"], data["start_time"])] = data
        except Exception:
            pass
    return result


GRAPH_MAX_DEPTH    = 45   # y軸固定: 0〜45m
GRAPH_MAX_DURATION = 60   # x軸固定: 0〜60分
GRAPH_DEPTH_STEP   = 5    # y軸目盛り間隔

def generate_depth_svg(profile: list, avg_depth: float | None,
                       warning: str, uid: str, duration_mins: float | None = None) -> str:
    if not profile or len(profile) < 2:
        return ""

    W, H = 340, 145
    PL, PR, PT, PB = 38, 16, 10, 26
    pw = W - PL - PR
    ph = H - PT - PB

    y_scale = GRAPH_MAX_DEPTH
    n = len(profile)
    actual_mins = min(duration_mins or 38, GRAPH_MAX_DURATION)  # 60分上限

    # X軸は常に60分固定。プロファイルはその中に actual_mins 分だけ描画
    pts = [
        (PL + (i / (n - 1) * actual_mins / GRAPH_MAX_DURATION) * pw,
         PT + min(profile[i], y_scale) / y_scale * ph)
        for i in range(n)
    ]

    # 塗り: 左端(水面)→プロファイル→最終点の真上(水面)→閉じる
    last_x = pts[-1][0]
    fill_d = f"M {PL},{PT} " + " ".join(f"L {x:.1f},{y:.1f}" for x, y in pts) + f" L {last_x:.1f},{PT} Z"
    line_d = f"M {pts[0][0]:.1f},{pts[0][1]:.1f} " + " ".join(f"L {x:.1f},{y:.1f}" for x, y in pts[1:])

    # Y軸: 5m刻み（0〜45m）
    depth_labels = []
    for val in range(0, GRAPH_MAX_DEPTH + 1, GRAPH_DEPTH_STEP):
        y = PT + val / y_scale * ph
        depth_labels.append(
            f'<line x1="{PL}" y1="{y:.1f}" x2="{PL+pw}" y2="{y:.1f}" '
            f'stroke="#3d6b8a" stroke-width="{0.6 if val % 10 == 0 else 0.3}" '
            f'stroke-dasharray="{"2,3" if val % 10 != 0 else "3,4"}" opacity="{"0.35" if val % 10 == 0 else "0.18"}"/>'
        )
        if val % 10 == 0:  # 10m刻みでラベル表示
            depth_labels.append(
                f'<text x="{PL-4}" y="{y+3:.1f}" text-anchor="end" font-size="7" '
                f'fill="#999988" font-family="monospace">{val}m</text>'
            )

    # X軸: 固定60分・10分刻み
    time_labels = []
    for t in range(0, GRAPH_MAX_DURATION + 1, 10):
        x = PL + (t / GRAPH_MAX_DURATION) * pw
        time_labels.append(
            f'<line x1="{x:.1f}" y1="{PT}" x2="{x:.1f}" y2="{PT+ph}" '
            f'stroke="#3d6b8a" stroke-width="0.3" stroke-dasharray="2,4" opacity="0.2"/>'
        )
        time_labels.append(
            f'<text x="{x:.1f}" y="{PT+ph+14}" text-anchor="middle" font-size="7" '
            f'fill="#999988" font-family="monospace">{t}m</text>'
        )

    # 平均深度ライン
    avg_line = ""
    if avg_depth:
        ay = PT + min(avg_depth, y_scale) / y_scale * ph
        avg_line = (
            f'<line x1="{PL}" y1="{ay:.1f}" x2="{PL+pw}" y2="{ay:.1f}" '
            f'stroke="#8b3a1e" stroke-width="0.9" stroke-dasharray="3,3" opacity="0.6"/>'
            f'<text x="{PL+pw+2}" y="{ay+3:.1f}" font-size="6.5" fill="#8b3a1e" opacity="0.75" font-family="monospace">avg</text>'
        )

    # DECO警告
    deco = (f'<text x="{PL+pw}" y="{PT+6}" text-anchor="end" font-size="7.5" '
            f'fill="#8b3a1e" font-family="monospace" font-weight="bold">⚠ DECO</text>'
            if "DECO" in warning else "")

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="100%" style="display:block;">
  <defs>
    <linearGradient id="dg{uid}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#3d6b8a" stop-opacity="0.5"/>
      <stop offset="100%" stop-color="#1a3a50" stop-opacity="0.9"/>
    </linearGradient>
  </defs>
  <rect x="{PL}" y="{PT}" width="{pw}" height="{ph}" fill="#e8f0f5" opacity="0.3" rx="1"/>
  {''.join(depth_labels)}
  {''.join(time_labels)}
  <path d="{fill_d}" fill="url(#dg{uid})"/>
  <path d="{line_d}" fill="none" stroke="#deeaf3" stroke-width="1.4" stroke-linejoin="round"/>
  {avg_line}
  {deco}
</svg>'''


# ── メインビルド ──────────────────────────────────────────────────────────────
def build():
    print("📥 Notionからデータ取得中...")
    raw_dives  = notion.get_all_dive_logs()
    raw_fish   = notion.get_all_fish()
    raw_photos = notion.get_all_photo_logs() if _ids.get("photo_db") else []

    dives         = [parse_dive(p) for p in raw_dives]
    depth_profiles = load_depth_profiles()

    # 深度プロファイルSVGを各ダイブに付与
    for d in dives:
        key  = (d["date"], d["start_time"])
        pdat = depth_profiles.get(key)
        if pdat and pdat.get("profile"):
            uid = f"{d['date'].replace('-','')}_{d['start_time'].replace(':','')}"
            svg = generate_depth_svg(
                pdat["profile"],
                d.get("avg_depth") or pdat.get("avg_depth"),
                pdat.get("warning", ""),
                uid,
                duration_mins=d.get("duration") or pdat.get("duration"),
            )
            d["depth_svg"] = Markup(svg)
        else:
            d["depth_svg"] = None
    fish_index = {f["id"]: f for f in [parse_fish(p) for p in raw_fish]}
    photos     = [parse_photo_log(p) for p in raw_photos]

    print(f"  ダイブ {len(dives)}本 / 魚 {len(fish_index)}種 / 写真ログ {len(photos)}件")

    # セッション総評読み込み
    session_reviews = notion.get_all_session_reviews()

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
        review = session_reviews.get((date_str, location), {}).get("text", "")

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
            "review":       review,
            "dive_range":   dive_range,
            "thumb":        thumb,
            "filename":     make_session_filename(date_str, location),
        })

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
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "localhost"
    record_url = f"http://{local_ip}:5001/"

    home_html = env.get_template("home.html").render(
        sessions=sessions,
        summary=summary,
        build_date=build_date,
        record_url=record_url,
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
    # fish.html は docs/ 直下なので ../fish_thumbs/ → fish_thumbs/ に修正
    fish_list_enc = [
        {**f, "thumbnail": f["thumbnail"].replace("../fish_thumbs/", "fish_thumbs/")}
        for f in fish_list
    ]
    fish_html = env.get_template("fish.html").render(
        fish_list=fish_list_enc,
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
