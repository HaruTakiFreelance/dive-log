from notion_client import Client


class NotionDiveClient:
    def __init__(self, token, dive_db_id, fish_db_id, photo_db_id=None):
        self.client   = Client(auth=token)
        self.dive_db  = dive_db_id
        self.fish_db  = fish_db_id
        self.photo_db = photo_db_id

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
            "開始時刻": {"rich_text": [{"text": {"content": d.get("start_time") or ""}}]},
            "終了時刻": {"rich_text": [{"text": {"content": d.get("end_time") or ""}}]},
            "潜水時間": {"number": d.get("duration")},
            "Max Depth": {"number": d.get("max_depth")},
            "ウェイト": {"number": d.get("weight")},
        }

        if d.get("comment"):
            props["コメント"] = {"rich_text": [{"text": {"content": d["comment"]}}]}
        if d.get("cost"):
            props["かかった金額"] = {"number": d["cost"]}
        if d.get("video_links"):
            props["動画リンク"] = {"rich_text": [{"text": {"content": d["video_links"]}}]}
        if d.get("fish_ids"):
            props["見れた魚"] = {"relation": [{"id": fid} for fid in d["fish_ids"]]}
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
