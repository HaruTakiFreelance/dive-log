import re

import requests
from bs4 import BeautifulSoup

_SHINY_ACE_INDEX = "https://shiny-ace.com/sakuin.html"
_SHINY_ACE_BASE  = "https://shiny-ace.com/"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

# 索引は初回フェッチ後にメモリキャッシュ { 日本語名: 完全URL }
_index_cache: dict | None = None


def _fetch_index() -> dict:
    global _index_cache
    if _index_cache is not None:
        return _index_cache
    try:
        resp = requests.get(_SHINY_ACE_INDEX, timeout=10, headers=_HEADERS)
        soup = BeautifulSoup(resp.content, "html.parser")
        index: dict = {}
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            name = a.get_text(strip=True)
            if name and href.startswith("zukan/"):
                index[name] = _SHINY_ACE_BASE + href
        _index_cache = index
        return index
    except Exception:
        _index_cache = {}
        return {}


# ページ本文のキーワードからカテゴリを判定（URLフォルダ名は使わない）
_CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("軟体動物", ["軟体動物", "頭足綱", "腹足綱", "二枚貝綱", "タコ目", "イカ目"]),
    ("甲殻類",   ["甲殻類", "十脚目", "口脚目", "フジツボ"]),
    ("棘皮動物", ["棘皮動物", "ヒトデ綱", "ウニ綱", "ナマコ綱"]),
    ("爬虫類",   ["爬虫類", "ウミガメ科", "カメ目"]),
    ("哺乳類",   ["哺乳類", "クジラ目", "鯨偶蹄目"]),
]


def _category_from_text(text: str) -> str:
    for cat, keywords in _CATEGORY_KEYWORDS:
        if any(kw in text for kw in keywords):
            return cat
    return "魚類"


def _extract_fish_page(url: str) -> dict:
    resp = requests.get(url, timeout=10, headers=_HEADERS)
    soup = BeautifulSoup(resp.content, "html.parser")
    text = soup.get_text(separator="\n")

    def find_field(label: str) -> str:
        # ラベルの直後 or 改行をまたいで次行を取得
        m = re.search(rf"{label}[：:　\s]*([^\n]+)", text)
        return m.group(1).strip() if m else ""

    def find_stars(label: str) -> str:
        # ★☆が複数行にまたがるので、ラベル後の星文字をすべて結合する
        m = re.search(rf"{label}[：:　\s]*([★☆\n]+)", text)
        return m.group(1).replace("\n", "").strip() if m else ""

    english_name = find_field("英名")

    # 学名は「属名 種小名」形式の行として独立している（ラベルなし）
    sci_m = re.search(r"\n([A-Z][a-z]+ [a-z][a-z]+(?:\s+[a-z]+)?)\n", text)
    scientific_name = sci_m.group(1).strip() if sci_m else ""

    habitat      = find_field("生息")
    distribution = find_field("分布")
    rarity       = find_stars("レア度")
    popularity   = find_stars("人気")
    photo_ease   = find_stars("撮り易さ")

    order_m  = re.search(r"-\s*(.+目)\s*-", text)
    family_m = re.search(r"\n([^\n]+科)\n", text)
    genus_m  = re.search(r"-\s*(.+属)", text)
    order  = order_m.group(1).strip()  if order_m  else ""
    family = family_m.group(1).strip() if family_m else ""
    genus  = genus_m.group(1).strip()  if genus_m  else ""

    memo_parts = [p for p in [habitat, f"分布：{distribution}" if distribution else ""] if p]
    memo = "　".join(memo_parts)

    return {
        "english_name":    english_name,
        "scientific_name": scientific_name,
        "category":        _category_from_text(text),
        "order":           order,
        "family":          family,
        "genus":           genus,
        "memo":            memo,
        "rarity":          rarity,
        "popularity":      popularity,
        "photo_ease":      photo_ease,
    }


def get_fish_info(fish_name: str) -> dict:
    """shiny-ace.com の図鑑から魚情報を取得する。見つからなければ空欄を返す。"""
    empty = {"english_name": "", "scientific_name": "", "category": "魚類", "memo": ""}
    try:
        index = _fetch_index()

        # 完全一致 → 部分一致の順で探す
        url = index.get(fish_name)
        if not url:
            for name, u in index.items():
                if fish_name in name or name in fish_name:
                    url = u
                    break

        if not url:
            return empty

        return _extract_fish_page(url)
    except Exception:
        return empty
