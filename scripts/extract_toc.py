"""
PDFの目次から「〇〇科 → ページ番号」を抽出するスクリプト。

使い方:
  python3 scripts/extract_toc.py

出力:
  - コンソールに生の目次テキスト（確認用）
  - data/guidebook_toc.json（修正後に guidebook.html に使う）

注意:
  PAGE_OFFSET = 6 (表紙・索引6ページ分のズレ)
  書籍のp.N → PDF実ページ p.N+6
"""
import json
import re
import sys
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).parent.parent
PDF_PATH = ROOT / "ネイチャーウォッチングガイドブック 海水魚.pdf"
OUTPUT_PATH = ROOT / "data" / "guidebook_toc.json"
PAGE_OFFSET = 6
TOC_PAGES = 10  # 目次は最初の10ページ以内にあるはず


def extract_toc_text(pdf_path: Path, num_pages: int) -> str:
    text = ""
    with pdfplumber.open(str(pdf_path)) as pdf:
        for i, page in enumerate(pdf.pages[:num_pages]):
            page_text = page.extract_text() or ""
            if page_text.strip():
                text += f"\n=== PDF page {i+1} ===\n"
                text += page_text
    return text


def parse_toc(raw_text: str) -> list[dict]:
    # パターン1: 「スズキ科 ........... 45」
    # パターン2: 「スズキ科　45」（全角スペース区切り）
    # パターン3: 「スズキ科...45」（ドット区切り）
    patterns = [
        r"([^\s\n]+科)\s*[・\.…\s]+\s*(\d{1,3})\b",
        r"([^\s\n]+科)\s{1,10}(\d{1,3})\b",
    ]
    seen = set()
    results = []
    for pattern in patterns:
        for name, pg_str in re.findall(pattern, raw_text):
            name = name.strip()
            pg = int(pg_str)
            key = (name, pg)
            if key not in seen and 1 <= pg <= 400:
                seen.add(key)
                results.append({
                    "name": name,
                    "book_page": pg,
                    "page": pg + PAGE_OFFSET,
                })
    results.sort(key=lambda x: x["book_page"])
    return results


def main():
    if not PDF_PATH.exists():
        print(f"[ERROR] PDFが見つかりません: {PDF_PATH}", file=sys.stderr)
        sys.exit(1)

    print(f"PDF を読み込み中: {PDF_PATH.name}")
    print(f"最初の {TOC_PAGES} ページをスキャン...\n")

    raw_text = extract_toc_text(PDF_PATH, TOC_PAGES)

    print("=" * 60)
    print("【生の抽出テキスト（目視確認用）】")
    print("=" * 60)
    print(raw_text)
    print("=" * 60)

    toc = parse_toc(raw_text)

    print(f"\n【抽出された科リスト（{len(toc)}件）】")
    print("※ book_page = 書籍ページ番号、page = PDF実ページ（+{PAGE_OFFSET}）\n")
    for entry in toc:
        print(f"  {entry['name']:15s}  書籍p.{entry['book_page']:3d}  →  PDFp.{entry['page']:3d}")

    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(toc, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n✅ 保存しました: {OUTPUT_PATH}")
    print("内容を確認・修正してから次のステップへ進んでください。")


if __name__ == "__main__":
    main()
