import unittest
from unittest.mock import patch
import requests
from app import app
import ticketmaster_events as source


def event(identifier="one", city="Stockholm", url="https://www.ticketmaster.se/event/123"):
    return {"id": identifier, "name": "Concert", "url": url,
            "_embedded": {"venues": [{"name": "Venue", "city": {"name": city}, "country": {"countryCode": "SE"}}]},
            "classifications": [{"segment": {"id": "Music-ID", "name": "Music"}, "genre": {"id": "Rock-ID", "name": "Rock"}}],
            "dates": {"start": {"localDate": "2026-11-01", "localTime": "19:30:00"}},
            "images": [{"url": "https://s1.ticketm.net/image.jpg", "ratio": "16_9", "width": 640}]}


def payload(events=None, pages=1):
    return {"_embedded": {"events": events if events is not None else [event()]}, "page": {"totalPages": pages}}


class EventTests(unittest.TestCase):
    def setUp(self):
        source._cache.clear()
        self.previous_key = app.config.get("TICKETMASTER_API_KEY", "")
        app.config["TICKETMASTER_API_KEY"] = "test-api-key"
        self.addCleanup(app.config.update, TICKETMASTER_API_KEY=self.previous_key)
        self.client = app.test_client()

    def test_page_and_assets(self):
        page = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="evenemang"', page)
        self.assertIn('data-endpoint="/api/combined-events"', page)
        self.assertNotIn('test-api-key', page)
        for asset in ("events.js", "style.css"):
            with self.client.get("/static/" + asset) as response:
                self.assertEqual(response.status_code, 200)

    @patch.object(source, "_fetch")
    def test_filters_pagination_and_shared_cache(self, fetch):
        fetch.return_value = payload([event(str(i)) for i in range(12)])
        url = "/api/ticketmaster/events?category=music-id&subcategory=rock-id&page=1"
        data = self.client.get(url).get_json()
        self.assertEqual(data["categories"][0]["subcategories"], [{"slug": "rock-id", "title": "Rock"}])
        self.assertEqual(data["count"], 12)
        self.assertEqual(len(data["events"]), 9)
        self.assertEqual(data["events"][0]["time"], "19:30")
        self.assertEqual(data["next"], 2)
        next_page = self.client.get(url.replace("page=1", "page=2")).get_json()
        self.assertEqual(len(next_page["events"]), 3)
        self.assertIsNone(next_page["next"])
        fetch.assert_called_once_with("test-api-key", 0)

    @patch("app.get_events")
    @patch.object(source, "_fetch", side_effect=requests.ConnectionError("offline"))
    def test_ticketmaster_failure_does_not_replace_or_break_visit_stockholm(self, fetch, visit):
        visit.return_value = {"events": [{"title": "Visit event"}], "categories": [], "count": 1}
        page = self.client.get("/").get_data(as_text=True)
        self.assertEqual(page.count('data-events-widget'), 1)
        self.assertIn('data-endpoint="/api/combined-events"', page)
        self.assertEqual(self.client.get("/api/ticketmaster/events").status_code, 503)
        self.assertEqual(self.client.get("/api/events").get_json()["count"], 1)
        visit.assert_called_once_with("", "", 1)

    def test_without_ticketmaster_key_original_section_still_exists(self):
        app.config["TICKETMASTER_API_KEY"] = ""
        page = self.client.get("/").get_data(as_text=True)
        self.assertEqual(page.count('data-events-widget'), 1)
        self.assertIn('data-endpoint="/api/combined-events"', page)

    @patch.object(source, "_fetch")
    def test_strict_city_country_and_deduplication(self, fetch):
        missing = event("missing")
        missing.pop("_embedded")
        foreign = event("foreign")
        foreign["_embedded"]["venues"][0]["country"]["countryCode"] = "US"
        fetch.return_value = payload([event(), event(), event("solna", "Solna"), event("johanneshov", "Johanneshov"), missing, foreign])
        data = self.client.get("/api/ticketmaster/events").get_json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["events"][0]["city"], "Stockholm")

    @patch.object(source, "_fetch")
    def test_reads_multiple_api_pages(self, fetch):
        fetch.side_effect = [payload([event("one")], 2), payload([event("two")], 2)]
        self.assertEqual(self.client.get("/api/ticketmaster/events").get_json()["count"], 2)
        self.assertEqual([call.args[1] for call in fetch.call_args_list], [0, 1])

    @patch.object(source, "_fetch")
    def test_deep_paging_limit_is_reported(self, fetch):
        fetch.return_value = payload(pages=6)
        self.assertTrue(self.client.get("/api/ticketmaster/events").get_json()["truncated"])
        self.assertEqual(fetch.call_count, 5)

    @patch.object(source, "_fetch", side_effect=requests.ConnectionError("offline"))
    def test_outage_and_missing_key_do_not_expose_credentials(self, fetch):
        response = self.client.get("/api/ticketmaster/events")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("test-api-key", response.get_data(as_text=True))
        fetch.reset_mock()
        app.config["TICKETMASTER_API_KEY"] = ""
        self.assertEqual(self.client.get("/api/ticketmaster/events").status_code, 503)
        fetch.assert_not_called()

    @patch.object(source, "_fetch")
    def test_stale_fallback(self, fetch):
        fetch.return_value = payload()
        source.get_events("test-api-key")
        key = next(iter(source._cache))
        saved_at, data = source._cache[key]
        source._cache[key] = (saved_at - 601, data)
        fetch.side_effect = requests.ConnectionError("offline")
        self.assertTrue(source.get_events("test-api-key")["stale"])
        source._cache[key] = (saved_at - 3601, data)
        with self.assertRaises(source.SourceUnavailable):
            source.get_events("test-api-key")

    @patch.object(source, "_fetch")
    def test_invalid_inputs_never_reach_source(self, fetch):
        for query in ("page=0", "page=-1", "page=1001", "page=no", "page=" + "9" * 5000,
                      "category=https://example.com", "subcategory=%3Cscript%3E"):
            self.assertEqual(self.client.get("/api/ticketmaster/events?" + query).status_code, 400)
        fetch.assert_not_called()

    @patch.object(source, "_fetch")
    def test_empty_results_and_untrusted_links(self, fetch):
        fetch.return_value = payload([])
        self.assertEqual(self.client.get("/api/ticketmaster/events").get_json()["events"], [])
        for url in ("javascript:alert(1)", "https://evil.example/a", "//evil.example", "https://www.ticketmaster.se@evil.example/", "https://www.ticketmaster.se.evil.example/a"):
            self.assertEqual(source.source_url(url), "")
        self.assertEqual(source.source_url("http://www.ticketmaster.se/event/123"), "https://www.ticketmaster.se/event/123")

    @patch.object(source.requests, "get")
    def test_outbound_request_stockholm_and_secret_stays_server_side(self, get):
        get.return_value.status_code = 200
        get.return_value.content = b'{}'
        get.return_value.json.return_value = payload()
        data = self.client.get("/api/ticketmaster/events").get_json()
        params = get.call_args.kwargs["params"]
        self.assertEqual(params["city"], "Stockholm")
        self.assertEqual(params["countryCode"], "SE")
        self.assertNotIn("source", params)
        self.assertEqual(params["apikey"], "test-api-key")
        self.assertNotIn("test-api-key", str(data))
