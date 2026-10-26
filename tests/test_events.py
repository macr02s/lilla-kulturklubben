import unittest
from unittest.mock import patch
from urllib.error import URLError

from app import app
import visit_stockholm as source


def payload():
    return {"meta": {"categories": [{"slug": "music", "title": "Musik",
            "subcategories": [{"slug": "rock", "title": "Rock", "has_events": True},
                              {"slug": "reggae", "title": "Reggae", "has_events": False}]}]},
            "results": [{"title": "En konsert", "href": "/event/konsert/next/",
                         "category": {"title": "Musik"}, "start_date": "2026-11-01",
                         "end_date": "2026-11-01", "venue_name": "Scenen"}],
            "count": 12, "next": 2}


class EventTests(unittest.TestCase):
    def setUp(self):
        source._cache.clear()
        self.client = app.test_client()

    def test_page_and_assets(self):
        page = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="evenemang"', page)
        for asset in ("events.js", "style.css"):
            with self.client.get("/static/" + asset) as response:
                self.assertEqual(response.status_code, 200)

    @patch.object(source, "_fetch")
    def test_filters_pagination_and_cache(self, fetch):
        fetch.return_value = payload()
        url = "/api/events?category=music&subcategory=rock&page=1"
        data = self.client.get(url).get_json()
        self.assertEqual(data["categories"][0]["subcategories"], [{"slug": "rock", "title": "Rock"}])
        self.assertEqual(data["events"][0]["url"], source.BASE + "/event/konsert/next/")
        self.assertEqual(data["next"], 2)
        self.client.get(url)
        fetch.assert_called_once_with({"page": 1, "size": 9, "categories": "music", "subcategory": "rock"})
        self.client.get(url.replace("page=1", "page=2"))
        self.assertEqual(fetch.call_count, 2)

    @patch.object(source, "_fetch", side_effect=URLError("offline"))
    def test_outage(self, fetch):
        response = self.client.get("/api/events")
        self.assertEqual(response.status_code, 503)
        self.assertIn("error", response.get_json())

    @patch.object(source, "_fetch")
    def test_stale_fallback(self, fetch):
        fetch.return_value = payload()
        source.get_events()
        saved_at, data = source._cache[("", "", 1)]
        source._cache[("", "", 1)] = (saved_at - 601, data)
        fetch.side_effect = URLError("offline")
        self.assertTrue(source.get_events()["stale"])
        source._cache[("", "", 1)] = (saved_at - 3601, data)
        with self.assertRaises(source.SourceUnavailable):
            source.get_events()

    @patch.object(source, "_fetch")
    def test_invalid_inputs_never_reach_source(self, fetch):
        for query in ("page=0", "page=-1", "page=1001", "page=no", "page=" + "9" * 5000,
                      "category=https://example.com", "subcategory=%3Cscript%3E"):
            self.assertEqual(self.client.get("/api/events?" + query).status_code, 400)
        fetch.assert_not_called()

    @patch.object(source, "_fetch")
    def test_empty_results_and_untrusted_links(self, fetch):
        data = payload()
        data.update(results=[], count=0, next=None)
        fetch.return_value = data
        self.assertEqual(self.client.get("/api/events").get_json()["events"], [])
        for url in ("javascript:alert(1)", "https://evil.example/a", "//evil.example", "https://www.visitstockholm.se@evil.example/"):
            self.assertEqual(source.source_url(url), "")


if __name__ == "__main__":
    unittest.main()
