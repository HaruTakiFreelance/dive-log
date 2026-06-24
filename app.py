import json
import os
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, make_response, redirect, render_template, request, session, url_for

load_dotenv(Path(__file__).parent / ".env")
load_dotenv(Path("/Users/harutakizawa/Desktop/claude code/my-hq-bot/.env"))

from lib.ai import get_fish_info
from lib.notion_api import NotionDiveClient
from lib.weather import get_weather_and_marine

app = Flask(__name__)
app.secret_key = os.urandom(24)

_ids = json.loads((Path(__file__).parent / "data" / "notion_ids.json").read_text())
notion = NotionDiveClient(
    os.getenv("NOTION_TOKEN"), _ids["dive_log_db"], _ids["fish_db"], _ids["photo_db"]
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

    if not f.get("start_time") or not f.get("end_time") or not f.get("max_depth"):
        return "必須項目（開始時刻・終了時刻・Max Depth）が未入力です。", 400

    start_dt = datetime.strptime(f["start_time"], "%H:%M")
    end_dt   = datetime.strptime(f["end_time"],   "%H:%M")
    duration = int((end_dt - start_dt).total_seconds() / 60)

    weather = get_weather_and_marine(
        session["location"], session["date"], f["start_time"], f["end_time"]
    )

    fish_ids = [fid for fid in f.get("fish_ids", "").split(",") if fid.strip()]

    notion.add_dive_log({
        "date":        session["date"],
        "location":    session["location"],
        "point":       f.get("point", ""),
        "dive_number": session["current_dive_number"],
        "weight":      session["weight"],
        "start_time":  f["start_time"],
        "end_time":    f["end_time"],
        "duration":    duration,
        "max_depth":   float(f["max_depth"] or 0),
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


@app.route("/photo", methods=["POST"])
def save_photo():
    import uuid, re
    f = request.form
    files    = request.files.getlist("photo_file")
    captions = f.getlist("photo_caption")

    photos_dir = Path(__file__).parent / "docs" / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)

    lines = []
    for file, cap in zip(files, captions):
        if not file or not file.filename:
            continue
        # 安全なファイル名に変換
        ext = Path(file.filename).suffix.lower()
        safe_name = f"{f['date']}_{uuid.uuid4().hex[:8]}{ext}"
        file.save(photos_dir / safe_name)
        rel_path = f"photos/{safe_name}"
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


if __name__ == "__main__":
    print("🤿 Dive Log App — http://localhost:5001")
    print("   スマホからは http://<あなたのMacのIP>:5001 でアクセス可")
    app.run(host="0.0.0.0", port=5001, debug=False)
