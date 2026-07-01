from notion_client import Client


class NotionDiveClient:
    def __init__(self, token, dive_db_id, fish_db_id, photo_db_id=None, review_db_id=None):
        self.client    = Client(auth=token)
        self.dive_db   = dive_db_id
        self.fish_db   = fish_db_id
        self.photo_db  = photo_db_id
        self.review_db = review_db_id

    # ──────────────────────────────
    # 詳細ログ
    # ──────────────────────────────
    def get_last_entry(self):
        """最新ログから前回のウェイト・本数・場所を返す"""
        res = self.client.databases.query(
            database_id=self.dive_db,
            sorts=[{"property": "日付", "direction": "descending"}],
            page_size=1,
        )
        if not res["results"]:
            return {}
        props = res["results"][0]["properties"]
        return {
            "何本目か": self._num(props, "何本目か"),
            "ウェイト": self._num(props, "ウェイト"),
            "場所":     self._text(props, "場所"),
        }

    def add_dive_log(self, d):
        """詳細ログDBにダイブ記録を1件追加する"""
        weather = d.get("weather") or {}
        auto_name = f"{d['date']} {d.get('point') or d['location']} #{d['dive_number']}"

        props = {
            "名前":     {"title": [{"text": {"content": auto_name}}]},
            "日付":     {"date":  {"start": d["date"]}},
            "何本目か": {"number": d["dive_number"]},
            "場所":     {"rich_text": [{"text": {"content": d["location"]}}]},
            "ポイント": {"rich_text": [{"text": {"content": d.get("point") or ""}}]},
            "ウェイト": {"number": d.get("weight")},
        }

        if d.get("comment"):
            props["コメント"] = {"rich_text": [{"text": {"content": d["comment"]}}]}
        if d.get("cost"):
            props["かかった金額"] = {"number": d["cost"]}
        if d.get("buddy"):
            props["バディ"] = {"rich_text": [{"text": {"content": d["buddy"]}}]}
        if d.get("video_links"):
            props["動画リンク"] = {"rich_text": [{"text": {"content": d["video_links"]}}]}
        if d.get("fish_ids"):
            props["見れた魚"] = {"relation": [{"id": fid} for fid in d["fish_ids"]]}
        if d.get("start_time"):
            props["開始時刻"] = {"rich_text": [{"text": {"content": d["start_time"]}}]}
        if d.get("end_time"):
            props["終了時刻"] = {"rich_text": [{"text": {"content": d["end_time"]}}]}
        if d.get("duration") is not None:
            props["潜水時間"] = {"number": d["duration"]}
        if d.get("max_depth") is not None:
            props["Max Depth"] = {"number": d["max_depth"]}
        if weather.get("weather"):
            props["天気"] = {"select": {"name": weather["weather"]}}
        if weather.get("wave_height") is not None:
            props["波の高さ(m)"] = {"number": weather["wave_height"]}
        if weather.get("water_temp") is not None:
            props["水温(℃)"] = {"number": weather["water_temp"]}

        self.client.pages.create(
            parent={"database_id": self.dive_db},
            properties=props,
        )

    # ──────────────────────────────
    # 魚図鑑
    # ──────────────────────────────
    def search_fish(self, query):
        """名前の部分一致で魚図鑑を検索"""
        res = self.client.databases.query(
            database_id=self.fish_db,
            filter={"property": "名前", "title": {"contains": query}},
            page_size=20,
        )
        return [
            {
                "id":   p["id"],
                "name": p["properties"]["名前"]["title"][0]["plain_text"],
            }
            for p in res["results"]
            if p["properties"]["名前"]["title"]
        ]

    def add_fish(self, data):
        """魚図鑑に新規ページを作成してIDを返す"""
        props = {
            "名前": {"title": [{"text": {"content": data["name"]}}]},
        }
        if data.get("english_name"):
            props["英名"] = {"rich_text": [{"text": {"content": data["english_name"]}}]}
        if data.get("scientific_name"):
            props["学名"] = {"rich_text": [{"text": {"content": data["scientific_name"]}}]}
        if data.get("category"):
            props["分類"] = {"select": {"name": data["category"]}}
        if data.get("memo"):
            props["メモ"] = {"rich_text": [{"text": {"content": data["memo"]}}]}
        if data.get("order"):
            props["目"] = {"rich_text": [{"text": {"content": data["order"]}}]}
        if data.get("family"):
            props["科"] = {"rich_text": [{"text": {"content": data["family"]}}]}
        if data.get("genus"):
            props["属"] = {"rich_text": [{"text": {"content": data["genus"]}}]}
        if data.get("rarity"):
            props["レア度"] = {"rich_text": [{"text": {"content": data["rarity"]}}]}
        if data.get("popularity"):
            props["人気"] = {"rich_text": [{"text": {"content": data["popularity"]}}]}
        if data.get("photo_ease"):
            props["撮りやすさ"] = {"rich_text": [{"text": {"content": data["photo_ease"]}}]}
        if data.get("first_seen"):
            props["初目撃日"] = {"date": {"start": data["first_seen"]}}
        if data.get("thumbnail_url"):
            props["サムネイル"] = {
                "files": [{"type": "external", "name": "thumbnail",
                           "external": {"url": data["thumbnail_url"]}}]
            }

        page = self.client.pages.create(
            parent={"database_id": self.fish_db},
            properties=props,
        )
        return page["id"]

    # ──────────────────────────────
    # ログブック用 一括取得
    # ──────────────────────────────
    def _query_all(self, db_id: str, sorts: list | None = None) -> list:
        results, cursor = [], None
        while True:
            kw: dict = {"database_id": db_id, "page_size": 100}
            if sorts:
                kw["sorts"] = sorts
            if cursor:
                kw["start_cursor"] = cursor
            res = self.client.databases.query(**kw)
            results.extend(res["results"])
            if not res["has_more"]:
                break
            cursor = res["next_cursor"]
        return results

    def get_all_dive_logs(self) -> list:
        return self._query_all(self.dive_db, [
            {"property": "日付",    "direction": "ascending"},
            {"property": "何本目か", "direction": "ascending"},
        ])

    def get_all_fish(self) -> list:
        return self._query_all(self.fish_db)

    def get_all_photo_logs(self) -> list:
        return self._query_all(self.photo_db, [
            {"property": "日付", "direction": "ascending"},
        ])

    # ──────────────────────────────
    # 写真ログ
    # ──────────────────────────────
    def add_photo_log(self, d):
        """写真ログDBに1日分の記録を追加する"""
        auto_name = f"{d['date']} {d.get('location') or '写真'}"
        props = {
            "名前": {"title": [{"text": {"content": auto_name}}]},
            "日付": {"date": {"start": d["date"]}},
        }
        if d.get("location"):
            props["場所"] = {"rich_text": [{"text": {"content": d["location"]}}]}
        if d.get("photos"):
            props["写真"] = {"rich_text": [{"text": {"content": d["photos"]}}]}
        if d.get("comment"):
            props["コメント"] = {"rich_text": [{"text": {"content": d["comment"]}}]}
        self.client.pages.create(
            parent={"database_id": self.photo_db},
            properties=props,
        )

    # ──────────────────────────────
    # ダイコンCSVインポート用
    # ──────────────────────────────
    def get_recent_dive_logs(self, limit: int = 50) -> list:
        """最新のダイブログをlimit件返す（動画追加用）"""
        res = self.client.databases.query(
            database_id=self.dive_db,
            sorts=[
                {"property": "日付",    "direction": "descending"},
                {"property": "何本目か", "direction": "descending"},
            ],
            page_size=limit,
        )
        return res["results"]

    def append_fish_to_dive(self, page_id: str, new_fish_ids: list[str]):
        """既存の見れた魚リレーションに魚IDを追記する（重複は無視）"""
        page = self.client.pages.retrieve(page_id=page_id)
        existing = [
            r["id"].replace("-", "")
            for r in page["properties"].get("見れた魚", {}).get("relation", [])
        ]
        merged = existing[:]
        for fid in new_fish_ids:
            clean = fid.replace("-", "")
            if clean not in merged:
                merged.append(clean)
        self.client.pages.update(
            page_id=page_id,
            properties={"見れた魚": {"relation": [{"id": fid} for fid in merged]}},
        )

    def append_video_link(self, page_id: str, new_url: str):
        """既存の動画リンクにURLを追記する（重複は無視）"""
        page = self.client.pages.retrieve(page_id=page_id)
        rt = page["properties"].get("動画リンク", {}).get("rich_text", [])
        current = rt[0]["plain_text"] if rt else ""
        existing = [u.strip() for u in current.splitlines() if u.strip()]
        if new_url.strip() not in existing:
            existing.append(new_url.strip())
        merged = "\n".join(existing)
        self.client.pages.update(
            page_id=page_id,
            properties={"動画リンク": {"rich_text": [{"text": {"content": merged}}]}},
        )

    def find_dives_by_date(self, date_str: str) -> list:
        """指定日のダイブログを全件返す"""
        res = self.client.databases.query(
            database_id=self.dive_db,
            filter={"property": "日付", "date": {"equals": date_str}},
            page_size=20,
        )
        return res["results"]

    def find_unmatched_dives_by_date(self, date_str: str) -> list:
        """指定日の Max Depth が空のエントリを本数順で返す（CSV照合用）"""
        res = self.client.databases.query(
            database_id=self.dive_db,
            filter={
                "and": [
                    {"property": "日付", "date": {"equals": date_str}},
                    {"property": "Max Depth", "number": {"is_empty": True}},
                ]
            },
            sorts=[{"property": "何本目か", "direction": "ascending"}],
            page_size=20,
        )
        return res["results"]

    def update_dive_from_computer(self, page_id: str, d: dict):
        """ダイコンCSVデータでNotionページを上書き更新する"""
        props = {}
        if d.get("max_depth") is not None:
            props["Max Depth"] = {"number": d["max_depth"]}
        if d.get("avg_depth") is not None:
            props["平均水深"] = {"number": d["avg_depth"]}
        if d.get("duration") is not None:
            props["潜水時間"] = {"number": d["duration"]}
        if d.get("start_time"):
            props["開始時刻"] = {"rich_text": [{"text": {"content": d["start_time"]}}]}
        if d.get("end_time"):
            props["終了時刻"] = {"rich_text": [{"text": {"content": d["end_time"]}}]}
        if d.get("water_temp") is not None:
            props["水温(℃)"] = {"number": d["water_temp"]}
        if not props:
            return
        self.client.pages.update(page_id=page_id, properties=props)

    # ──────────────────────────────
    # セッション総評
    # ──────────────────────────────
    def get_dive_sessions(self, limit: int = 60) -> list:
        """日付＋場所でグループ化したセッション一覧を新しい順で返す"""
        pages = self.get_all_dive_logs()  # 日付asc, 何本目かasc
        order: list = []
        counts: dict = {}
        for p in pages:
            props = p["properties"]
            date_prop = props.get("日付", {}).get("date")
            date_str = date_prop["start"] if date_prop else None
            loc_rt = props.get("場所", {}).get("rich_text", [])
            location = loc_rt[0]["plain_text"] if loc_rt else ""
            if not date_str:
                continue
            key = (date_str, location)
            if key not in counts:
                order.append(key)
                counts[key] = 0
            counts[key] += 1
        order.reverse()
        return [
            {"date": d, "location": loc, "count": counts[(d, loc)]}
            for d, loc in order[:limit]
        ]

    def get_all_session_reviews(self) -> dict:
        """(日付, 場所) → {id, text} の辞書を返す"""
        pages = self._query_all(self.review_db)
        result = {}
        for p in pages:
            props = p["properties"]
            date_prop = props.get("日付", {}).get("date")
            date_str = date_prop["start"] if date_prop else None
            loc_rt = props.get("場所", {}).get("rich_text", [])
            location = loc_rt[0]["plain_text"] if loc_rt else ""
            text_rt = props.get("総評", {}).get("rich_text", [])
            text = text_rt[0]["plain_text"] if text_rt else ""
            if date_str:
                result[(date_str, location)] = {"id": p["id"], "text": text}
        return result

    def upsert_session_review(self, date_str: str, location: str, text: str):
        """指定セッションの総評を作成または更新する"""
        existing = self.client.databases.query(
            database_id=self.review_db,
            filter={"and": [
                {"property": "日付", "date": {"equals": date_str}},
                {"property": "場所", "rich_text": {"equals": location}},
            ]},
            page_size=1,
        )
        props = {
            "日付": {"date": {"start": date_str}},
            "場所": {"rich_text": [{"text": {"content": location}}]},
            "総評": {"rich_text": [{"text": {"content": text}}]},
        }
        if existing["results"]:
            self.client.pages.update(page_id=existing["results"][0]["id"], properties=props)
        else:
            props["名前"] = {"title": [{"text": {"content": f"{date_str} {location}"}}]}
            self.client.pages.create(parent={"database_id": self.review_db}, properties=props)

    # ──────────────────────────────
    # ヘルパー
    # ──────────────────────────────
    def _num(self, props, key):
        p = props.get(key)
        return p["number"] if p and p.get("number") is not None else None

    def _text(self, props, key):
        p = props.get(key)
        if not p:
            return ""
        rt = p.get("rich_text", [])
        return rt[0]["plain_text"] if rt else ""
