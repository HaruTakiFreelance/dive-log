import json
import os
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, make_response, redirect, render_template, request, session, url_for

load_dotenv(Path(__file__).parent / ".env")
load_dotenv(Path("/Users/harutakizawa/Desktop/claude code/my-hq-bot/.env"))

from lib.ai import get_fish_info
from lib.csv_import import match_and_update, parse_csv
from lib.notion_api import NotionDiveClient
from lib.weather import get_weather_and_marine

app = Flask(__name__)
app.secret_key = os.urandom(24)

_ids = json.loads((Path(__file__).parent / "data" / "notion_ids.json").read_text())
notion = NotionDiveClient(
    os.getenv("NOTION_TOKEN"), _ids["dive_log_db"], _ids["fish_db"], _ids["photo_db"],
    _ids.get("review_db"),
)


# ────────────────────────────────────────
# トップ：モード選択
# ────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


# ────────────────────────────────────────
# ダイビングモード
# ────────────────────────────────────────
@app.route("/dive/setup")
def dive_setup():
    last = notion.get_last_entry()
    defaults = {
        "date":             date.today().isoformat(),
        "next_dive_number": (last.get("何本目か") or 0) + 1,
        "weight":           last.get("ウェイト") or "",
        "location":         last.get("場所") or "",
    }
    return render_template("session_start.html", defaults=defaults)


@app.route("/session", methods=["POST"])
def start_session():
    session["date"]                = request.form["date"]
    session["location"]            = request.form["location"]
    session["weight"]              = float(request.form["weight"] or 0)
    session["buddy"]               = request.form.get("buddy", "")
    session["current_dive_number"] = int(request.form["dive_number"])
    return redirect(url_for("dive_form"))


@app.route("/dive")
def dive_form():
    if "date" not in session:
        return redirect(url_for("index"))
    resp = make_response(render_template("dive_form.html",
        dive_number = session["current_dive_number"],
        location    = session["location"],
        date        = session["date"],
    ))
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/dive", methods=["POST"])
def save_dive():
    f = request.form

    weather = get_weather_and_marine(
        session["location"], session["date"], None, None
    )

    fish_ids = [fid for fid in f.get("fish_ids", "").split(",") if fid.strip()]

    notion.add_dive_log({
        "date":        session["date"],
        "location":    session["location"],
        "point":       f.get("point", ""),
        "dive_number": session["current_dive_number"],
        "weight":      session["weight"],
        "buddy":       session.get("buddy", ""),
        "cost":        int(f.get("cost") or 0),
        "fish_ids":    fish_ids,
        "comment":     f.get("comment", ""),
        "video_links": f.get("video_links", ""),
        "weather":     weather,
    })

    session["current_dive_number"] += 1

    if f.get("action") == "add_more":
        return redirect(url_for("dive_form"))
    return redirect(url_for("complete", mode="dive"))


# ────────────────────────────────────────
# 写真モード
# ────────────────────────────────────────
@app.route("/photo")
def photo_form():
    resp = make_response(render_template("photo_form.html",
        today=date.today().isoformat()
    ))
    resp.headers["Cache-Control"] = "no-store"
    return resp


TARGET_HEIGHT = 1280

def _normalize_photo(path: Path) -> Path:
    """HEIC→JPEG変換 + 縦1280px統一（アスペクト比維持）。変換後のパスを返す。"""
    import subprocess, re
    if path.suffix.lower() in (".heic", ".heif"):
        jpg_path = path.with_suffix(".jpg")
        subprocess.run(
            ["sips", "-s", "format", "jpeg", str(path), "--out", str(jpg_path)],
            check=True, capture_output=True,
        )
        path.unlink()
        path = jpg_path

    # 元の寸法を取得
    r = subprocess.run(
        ["sips", "-g", "pixelHeight", "-g", "pixelWidth", str(path)],
        capture_output=True, text=True, check=True,
    )
    h = int(re.search(r"pixelHeight: (\d+)", r.stdout).group(1))
    w = int(re.search(r"pixelWidth: (\d+)", r.stdout).group(1))

    if h > TARGET_HEIGHT:
        new_w = round(w * TARGET_HEIGHT / h)
        subprocess.run(
            ["sips", "-z", str(TARGET_HEIGHT), str(new_w), str(path)],
            check=True, capture_output=True,
        )
    return path


@app.route("/photo", methods=["POST"])
def save_photo():
    import uuid
    f = request.form
    files    = request.files.getlist("photo_file")
    captions = f.getlist("photo_caption")

    photos_dir = Path(__file__).parent / "docs" / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)

    lines = []
    for file, cap in zip(files, captions):
        if not file or not file.filename:
            continue
        ext = Path(file.filename).suffix.lower()
        stem = f"{f['date']}_{uuid.uuid4().hex[:8]}"
        tmp_path = photos_dir / f"{stem}{ext}"
        file.save(tmp_path)

        # HEIC変換 + リサイズ（動画はスキップ）
        if ext not in (".mp4", ".mov", ".avi", ".m4v"):
            tmp_path = _normalize_photo(tmp_path)

        rel_path = f"photos/{tmp_path.name}"
        lines.append(f"{rel_path} | {cap.strip()}" if cap.strip() else rel_path)

    notion.add_photo_log({
        "date":     f["date"],
        "location": f.get("location", ""),
        "photos":   "\n".join(lines),
        "comment":  f.get("comment", ""),
    })
    session["photo_date"]     = f["date"]
    session["photo_location"] = f.get("location", "")
    return redirect(url_for("complete", mode="photo"))


# ────────────────────────────────────────
# 完了
# ────────────────────────────────────────
@app.route("/complete")
def complete():
    mode = request.args.get("mode", "dive")
    return render_template("complete.html",
        mode     = mode,
        date     = session.get("date") if mode == "dive" else session.get("photo_date"),
        location = session.get("location") if mode == "dive" else session.get("photo_location"),
        dives    = session.get("current_dive_number", 1) - 1,
    )


# ────────────────────────────────────────
# 魚API
# ────────────────────────────────────────
@app.route("/fish/search")
def fish_search():
    q = request.args.get("q", "").strip()
    return jsonify(notion.search_fish(q) if q else [])


@app.route("/fish/suggest", methods=["POST"])
def fish_suggest():
    name = (request.json or {}).get("name", "")
    return jsonify(get_fish_info(name))


@app.route("/fish/add", methods=["POST"])
def fish_add():
    data    = request.json or {}
    fish_id = notion.add_fish(data)
    return jsonify({"id": fish_id, "name": data.get("name", "")})


# ────────────────────────────────────────
# 見れた魚 後付け追加
# ────────────────────────────────────────
@app.route("/dive/fish")
def dive_fish_form():
    pages = notion.get_recent_dive_logs(limit=60)
    dives = []
    for p in pages:
        props = p["properties"]
        title_list = props.get("名前", {}).get("title", [])
        title = title_list[0]["plain_text"] if title_list else "—"
        fish_count = len(props.get("見れた魚", {}).get("relation", []))
        dives.append({
            "id":         p["id"],
            "title":      title,
            "fish_count": fish_count,
        })
    return render_template("dive_fish_form.html", dives=dives)


@app.route("/dive/fish", methods=["POST"])
def dive_fish_save():
    page_id  = request.form.get("page_id", "").strip()
    fish_ids = [fid.strip() for fid in request.form.get("fish_ids", "").split(",") if fid.strip()]
    if not page_id or not fish_ids:
        return jsonify({"ok": False, "message": "ダイブと魚を指定してください"}), 400
    try:
        notion.append_fish_to_dive(page_id, fish_ids)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


# ────────────────────────────────────────
# 動画リンク後付け追加
# ────────────────────────────────────────
@app.route("/video")
def video_form():
    pages = notion.get_recent_dive_logs(limit=60)
    dives = []
    for p in pages:
        props = p["properties"]
        title_list = props.get("名前", {}).get("title", [])
        title = title_list[0]["plain_text"] if title_list else "—"
        rt = props.get("動画リンク", {}).get("rich_text", [])
        existing = rt[0]["plain_text"] if rt else ""
        dives.append({
            "id":       p["id"],
            "title":    title,
            "existing": [u.strip() for u in existing.splitlines() if u.strip()],
        })
    return render_template("video_form.html", dives=dives)


@app.route("/video", methods=["POST"])
def video_save():
    page_id = request.form.get("page_id", "").strip()
    url     = request.form.get("url", "").strip()
    if not page_id or not url:
        return jsonify({"ok": False, "message": "ダイブとURLを指定してください"}), 400
    try:
        notion.append_video_link(page_id, url)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


# ────────────────────────────────────────
# ダイコンCSVインポート
# ────────────────────────────────────────
@app.route("/import/csv")
def import_csv_form():
    return render_template("import_csv.html")


@app.route("/import/csv", methods=["POST"])
def import_csv_post():
    f = request.files.get("csv_file")
    if not f or not f.filename:
        return jsonify({"ok": False, "message": "ファイルが選択されていません"}), 400
    try:
        dives   = parse_csv(f.read())
        results = match_and_update(dives, notion)
        updated  = [r for r in results if r["status"] == "updated"]
        no_match = [r for r in results if r["status"] == "no_match"]
        return jsonify({"ok": True, "results": results,
                        "updated": len(updated), "no_match": len(no_match)})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


# ────────────────────────────────────────
# セッション総評
# ────────────────────────────────────────
@app.route("/session/review")
def session_review_form():
    sessions = notion.get_dive_sessions(limit=60)
    reviews  = notion.get_all_session_reviews()
    for s in sessions:
        r = reviews.get((s["date"], s["location"]))
        s["existing_text"] = r["text"] if r else ""
    return render_template("session_review_form.html", sessions=sessions)


@app.route("/session/review", methods=["POST"])
def session_review_save():
    date_str = request.form.get("date", "").strip()
    location = request.form.get("location", "").strip()
    text     = request.form.get("text", "").strip()
    if not date_str or not location:
        return jsonify({"ok": False, "message": "セッションを選択してください"}), 400
    try:
        notion.upsert_session_review(date_str, location, text)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


# ────────────────────────────────────────
# ログブック生成
# ────────────────────────────────────────
@app.route("/build", methods=["POST"])
def build_logbook():
    import subprocess, sys
    script = Path(__file__).parent / "scripts" / "build_logbook.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode == 0:
        last_line = result.stdout.strip().splitlines()[-1]
        return jsonify({"ok": True, "message": last_line})
    return jsonify({"ok": False, "message": result.stderr.strip()[-400:]}), 500


@app.route("/push", methods=["POST"])
def git_push():
    import subprocess
    repo = str(Path(__file__).parent)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    cmds = [
        ["git", "-C", repo, "add", "docs/"],
        ["git", "-C", repo, "commit", "--allow-empty", "-m", f"update logbook {now}"],
        ["git", "-C", repo, "push"],
    ]
    for cmd in cmds:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode != 0 and "nothing to commit" not in r.stdout:
            return jsonify({"ok": False, "message": r.stderr.strip()[-400:]}), 500
    return jsonify({"ok": True, "message": "GitHub Pages に公開しました"})


if __name__ == "__main__":
    print("🤿 Dive Log App — http://localhost:5001")
    print("   スマホからは http://<あなたのMacのIP>:5001 でアクセス可")
    app.run(host="0.0.0.0", port=5001, debug=False)
