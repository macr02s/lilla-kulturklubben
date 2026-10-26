from unittest import TestCase
from unittest.mock import patch

from app import app
from event_months import month_range
import ticketmaster_events as ticketmaster
import visit_stockholm as visit


def tm_event(identifier, day):
    return {"id": identifier, "name": "Concert", "url": "https://www.ticketmaster.se/event/"+identifier,
            "_embedded": {"venues": [{"name": "Venue", "city": {"name": "Stockholm"}, "country": {"countryCode": "SE"}}]},
            "classifications": [{"segment": {"id": "music", "name": "Music"}}],
            "dates": {"start": {"localDate": day}}}


class EventMonthTests(TestCase):
    def setUp(self):
        visit._cache.clear()
        ticketmaster._cache.clear()
        self.client=app.test_client()

    def test_inclusive_month_boundaries_leap_year_and_year_crossing(self):
        self.assertEqual(month_range('2027-01','2027-03'),('2027-01-01','2027-03-31'))
        self.assertEqual(month_range('2028-02','2028-02'),('2028-02-01','2028-02-29'))
        self.assertEqual(month_range('2027-12','2028-01'),('2027-12-01','2028-01-31'))
        self.assertEqual(month_range(),('',''))

    @patch('app.get_events')
    @patch('app.ticketmaster.get_events')
    def test_invalid_ranges_rejected_before_either_provider(self, tm, vs):
        queries=('from_month=2027-01','to_month=2027-03','from_month=2027-04&to_month=2027-03',
                 'from_month=2027-13&to_month=2027-13','from_month=2027-1&to_month=2027-03',
                 'from_month=9999-01&to_month=9999-02','from_month=<script>&to_month=2027-03')
        for endpoint in ('/api/events','/api/ticketmaster/events'):
            for query in queries:
                self.assertEqual(self.client.get(endpoint+'?'+query).status_code,400)
        tm.assert_not_called();vs.assert_not_called()

    @patch.object(visit,'_fetch')
    def test_visit_dates_categories_and_page_forwarded_and_cached_separately(self, fetch):
        fetch.return_value={'meta':{'categories':[]},'results':[],'count':0,'next':None}
        url='/api/events?from_month=2027-07&to_month=2027-09&category=music&page=2'
        self.assertEqual(self.client.get(url).status_code,200)
        fetch.assert_called_once_with({'page':2,'size':9,'categories':'music','date_from':'2027-07-01','date_to':'2027-09-30'})
        self.client.get(url)
        self.assertEqual(fetch.call_count,1)
        self.client.get(url.replace('2027-07','2027-08'))
        self.assertEqual(fetch.call_count,2)

    @patch.object(ticketmaster,'_fetch')
    def test_ticketmaster_filters_before_pagination_and_preserves_last_day(self, fetch):
        days=['2026-12-31','2027-01-01','2027-03-31','2027-04-01',None]
        fetch.return_value={'page':{'totalPages':1},'_embedded':{'events':[tm_event(str(i),day) for i,day in enumerate(days)]}}
        data=ticketmaster.get_events('test-key',start_date='2027-01-01',end_date='2027-03-31')
        self.assertEqual(data['count'],2)
        self.assertEqual([e['start'] for e in data['events']],['2027-01-01','2027-03-31'])
        fetch.assert_called_once_with('test-key',0,'2027-01-01','2027-03-31')
        ticketmaster.get_events('test-key','music',page=2,start_date='2027-01-01',end_date='2027-03-31')
        self.assertEqual(fetch.call_count,1)
        ticketmaster.get_events('test-key',start_date='2027-07-01',end_date='2027-09-30')
        self.assertEqual(fetch.call_count,2)

    @patch.object(ticketmaster.requests,'get')
    def test_ticketmaster_uses_local_time_range_instead_of_current_date(self, get):
        get.return_value.status_code=200
        get.return_value.content=b'{}'
        get.return_value.json.return_value={'page':{'totalPages':0}}
        ticketmaster.get_events('test-key',start_date='2027-01-01',end_date='2027-03-31')
        params=get.call_args.kwargs['params']
        self.assertEqual(params['localStartDateTime'],'2027-01-01T00:00:00,2027-03-31T23:59:59')
        self.assertNotIn('startDateTime',params)
        self.assertEqual(params['city'],'Stockholm')
