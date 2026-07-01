"""
ダイブコンピューターCSVをパースしてNotionログと照合・更新する。
深度プロファイルは data/depth_profiles/YYYY-MM-DD_HH-MM.json に保存。
"""
import ast
import csv
import io
import json
from datetime import datetime
from pathlib import Path

PROFILES_DIR = Path(__file__).parent.parent / "data" / "depth_profiles"


def parse_csv(file_bytes: bytes) -> list[dict]:
    """
    ダイコンCSVを読んでダイブ辞書のリストを返す。
    エンコーディングは cp932 → utf-8 の順で試みる。
    """
    for enc in ("cp932", "utf-8-sig", "utf-8"):
        try:
            text = file_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("CSVのエンコーディングを判別できませんでした")

    reader = csv.DictReader(io.StringIO(text))
    dives = []
    for row in reader:
        entry_str = row.get("エントリー時刻", "").strip()
        exit_str  = (row.get("エキジット時刻") or row.get("エグジット時刻") or "").strip()
        if not entry_str:
            continue

        entry_dt = _parse_dt(entry_str)
        exit_dt  = _parse_dt(exit_str) if exit_str else None
        duration = int((exit_dt - entry_dt).total_seconds() / 60) if exit_dt else None

        depth_raw = row.get("深度", "").strip()
        profile   = _parse_depth(depth_raw)

        dives.append({
            "computer_id":   row.get("ID", "").strip(),
            "date":          entry_dt.strftime("%Y-%m-%d"),
            "start_time":    entry_dt.strftime("%H:%M"),
            "end_time":      exit_dt.strftime("%H:%M") if exit_dt else "",
            "duration":      duration,
            "max_depth":     _float(row.get("最大水深")),
            "avg_depth":     _float(row.get("平均水深")),
            "water_temp":    _float(row.get("最深水温")),
            "warning":       row.get("警告", "").strip(),
            "depth_profile": profile,
            "location":      row.get("場所", "").strip(),
            "point":         row.get("ポイント名", "").strip(),
        })
    return dives


def save_profile(dive: dict) -> Path:
    """深度プロファイルをJSONファイルに保存してパスを返す。"""
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    key  = f"{dive['date']}_{dive['start_time'].replace(':', '-')}"
    path = PROFILES_DIR / f"{key}.json"
    payload = {
        "date":        dive["date"],
        "start_time":  dive["start_time"],
        "end_time":    dive["end_time"],
        "max_depth":   dive["max_depth"],
        "avg_depth":   dive["avg_depth"],
        "profile":     dive["depth_profile"],
        "warning":     dive["warning"],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return path


def match_and_update(dives: list[dict], notion_client) -> list[dict]:
    """
    Max Depthが空のNotionエントリを日付・本数順で並べ、
    同日のCSVデータと出現順で位置照合して更新する。
    """
    results = []

    # CSVを日付でグループ化（CSV内の出現順＝時刻順を維持）
    by_date: dict[str, list] = {}
    for dive in dives:
        by_date.setdefault(dive["date"], []).append(dive)

    for date, csv_dives in by_date.items():
        # Max Depthが空のNotionページを本数順で取得
        pages = notion_client.find_unmatched_dives_by_date(date)

        # 位置照合: CSVi本目 ↔ Notionのi本目（Max Depth空）
        for csv_dive, page in zip(csv_dives, pages):
            notion_client.update_dive_from_computer(page["id"], csv_dive)
            save_profile(csv_dive)
            results.append({
                "computer_id": csv_dive["computer_id"],
                "date":        csv_dive["date"],
                "start_time":  csv_dive["start_time"],
                "status":      "updated",
                "notion_name": _page_title(page),
            })

        # Notionエントリが足りずマッチできなかったCSV行
        for csv_dive in csv_dives[len(pages):]:
            results.append({
                "computer_id": csv_dive["computer_id"],
                "date":        csv_dive["date"],
                "start_time":  csv_dive["start_time"],
                "status":      "no_match",
                "notion_name": None,
            })

    return results


# ── private helpers ──────────────────────────────────────────

def _parse_dt(s: str) -> datetime:
    for fmt in ("%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"日時フォーマット不明: {s!r}")


def _parse_depth(raw: str) -> list[float]:
    if not raw:
        return []
    try:
        val = ast.literal_eval(raw)
        return [float(v) for v in val] if isinstance(val, list) else []
    except Exception:
        return []


def _float(s) -> float | None:
    try:
        return float(str(s).strip())
    except (TypeError, ValueError):
        return None


def _page_title(page: dict) -> str:
    title = page["properties"].get("名前", {}).get("title", [])
    return title[0]["plain_text"] if title else ""
