from unittest import TestCase
from unittest.mock import patch
from urllib.parse import urlencode

from app import app
import club_events as combined
from test_combined_events import raw


class EventSearchTests(TestCase):
    def setUp(self):
        combined._cache.clear()
        combined._provider_cache.clear()

    @patch.object(combined, '_visit_catalog')
    def test_search_filters_full_catalog_before_pagination_and_reuses_cache(self, visit):
        visit.return_value = {'events': [raw('Visit Stockholm', title='Other '+str(i)) for i in range(12)] +
                              [raw('Visit Stockholm', title='Bj\u00f6rk '+str(i), venue='G\u00f6ta Lejon') for i in range(12)]}
        options = {'selected_sources': ('Visit Stockholm',)}
        first = combined.get_events({}, search='BJORK gota', **options)
        self.assertEqual(first['count'], 12)
        self.assertEqual(len(first['events']), 9)
        self.assertEqual(first['next'], 2)
        second = combined.get_events({}, search='bjork gota', page=2, **options)
        self.assertEqual(len(second['events']), 3)
        self.assertIsNone(second['next'])
        self.assertEqual(combined.get_events({}, search='missing', **options)['count'], 0)
        self.assertEqual(combined.get_events({}, search='', **options)['count'], 24)
        visit.assert_called_once()

    @patch.object(combined, '_visit_catalog')
    def test_search_combines_category_venue_and_title_and_handles_punctuation(self, visit):
        visit.return_value = {'events': [raw('Visit Stockholm')]}
        options = {'selected_sources': ('Visit Stockholm',)}
        for query in ('kent 3arena', 'KENT', 'musik', 'Kent!', '3Arena'):
            self.assertEqual(combined.get_events({}, search=query, **options)['count'], 1)
        self.assertEqual(combined.get_events({}, search='kent other', **options)['count'], 0)
        self.assertEqual(combined.get_events({}, search='!!!', **options)['count'], 0)
        self.assertEqual(combined.get_events({}, category='stage', search='kent', **options)['count'], 0)

    @patch.object(combined, 'get_events')
    def test_route_preserves_source_month_page_and_search(self, fetch):
        fetch.return_value = {'events': []}
        response = app.test_client().get('/api/combined-events?' + urlencode({
            'q': '  Kent   3Arena  ', 'sources': 'visit-stockholm',
            'from_month': '2027-01', 'to_month': '2027-03', 'page': 2}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(fetch.call_args.args[1:], ('', '', 2, '2027-01-01', '2027-03-31'))
        self.assertEqual(fetch.call_args.kwargs, {'selected_sources': ('Visit Stockholm',), 'search': 'Kent 3Arena'})

    @patch.object(combined, 'get_events')
    def test_invalid_search_is_rejected_before_catalog_fetch(self, fetch):
        for query in ('x'*121, 'test\x00text', 'test\ntext'):
            response = app.test_client().get('/api/combined-events?' + urlencode({'q': query}))
            self.assertEqual(response.status_code, 400)
        fetch.assert_not_called()

    @patch.object(combined.visit, '_fetch')
    def test_preview_search_checks_whole_first_batch(self, fetch):
        fetch.return_value = {'meta': {'categories': []}, 'count': 11, 'next': None,
            'results': [{'id': str(i), 'title': 'Match' if i == 10 else 'Other '+str(i),
                         'href': '/event/concert-'+str(i)+'/', 'city': 'Stockholm', 'venue_name': 'Venue',
                         'category': {'title': 'Musik'}, 'start_date': '2027-03-15', 'end_date': '2027-03-15'}
                        for i in range(11)]}
        combined.visit._cache.clear()
        response = app.test_client().get('/api/combined-events?sources=visit-stockholm&preview=1&q=match')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['count'], 1)
        self.assertEqual(response.get_json()['events'][0]['title'], 'Match')
