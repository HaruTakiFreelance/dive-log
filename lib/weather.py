import json
import requests
from pathlib import Path

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL   = "https://archive-api.open-meteo.com/v1/archive"
MARINE_URL    = "https://marine-api.open-meteo.com/v1/marine"

_cache_path = Path(__file__).parent.parent / "data" / "locations_cache.json"


def _load_cache():
    if _cache_path.exists():
        return json.loads(_cache_path.read_text(encoding="utf-8"))
    return {}


def _save_cache(cache):
    _cache_path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _geocode(location_name):
    cache = _load_cache()
    if location_name in cache:
        return cache[location_name]
    try:
        res = requests.get(
            GEOCODING_URL,
            params={"name": location_name, "count": 1, "language": "ja", "format": "json"},
            timeout=5,
        ).json()
        if res.get("results"):
            r = res["results"][0]
            coords = {"lat": r["latitude"], "lon": r["longitude"]}
            cache[location_name] = coords
            _save_cache(cache)
            return coords
    except Exception:
        pass
    return None


def _wmo_to_ja(code):
    """WMO天気コードを日本語テキストに変換"""
    if code is None:
        return None
    if code == 0:
        return "快晴"
    if code in (1, 2, 3):
        return ["晴れ", "晴れ時々曇り", "曇り"][code - 1]
    if 51 <= code <= 67 or 80 <= code <= 82:
        return "雨"
    if 71 <= code <= 77:
        return "雪"
    return "曇り"


def _avg_range(hourly, variable, start_h, end_h):
    times  = hourly.get("time", [])
    values = hourly.get(variable, [])
    vals   = [v for t, v in zip(times, values)
              if v is not None and start_h <= int(t[11:13]) <= end_h]
    return round(sum(vals) / len(vals), 1) if vals else None


def get_weather_and_marine(location, date, start_time, end_time):
    """天気・波高・水温を取得して辞書で返す。取得失敗時は空辞書。"""
    coords = _geocode(location)
    if not coords:
        return {}

    lat, lon = coords["lat"], coords["lon"]
    start_h  = int(start_time.split(":")[0])
    end_h    = int(end_time.split(":")[0])
    result   = {}

    try:
        w = requests.get(WEATHER_URL, params={
            "latitude": lat, "longitude": lon,
            "start_date": date, "end_date": date,
            "hourly": "weathercode",
            "timezone": "Asia/Tokyo",
        }, timeout=8).json()
        hourly = w.get("hourly", {})
        for t, c in zip(hourly.get("time", []), hourly.get("weathercode", [])):
            if start_h <= int(t[11:13]) <= end_h:
                result["weather"] = _wmo_to_ja(c)
                break
    except Exception:
        pass

    try:
        m = requests.get(MARINE_URL, params={
            "latitude": lat, "longitude": lon,
            "start_date": date, "end_date": date,
            "hourly": "wave_height,sea_surface_temperature",
            "timezone": "Asia/Tokyo",
        }, timeout=8).json()
        hourly = m.get("hourly", {})
        wh = _avg_range(hourly, "wave_height",             start_h, end_h)
        wt = _avg_range(hourly, "sea_surface_temperature", start_h, end_h)
        if wh is not None:
            result["wave_height"] = wh
        if wt is not None:
            result["water_temp"] = wt
    except Exception:
        pass

    return result
