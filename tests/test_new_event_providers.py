from copy import deepcopy
from datetime import datetime, timezone
from unittest import TestCase
from unittest.mock import Mock, patch

from app import app
import club_events as combined
import tickster_events as tickster
import kulturbiljetter_events as kultur


def response(data, status=200):
    result=Mock(status_code=status,content=b'{}')
    result.json.return_value=data
    return result


def tickster_event(city='Stockholm'):
    return {'id':'event1','name':'Concert','venue':{'name':'Venue','city':city,'country':'SE'},
            'startUtc':'2027-03-15T18:00:00Z','endUtc':'2027-03-15T20:00:00Z',
            'infoUrl':'https://www.tickster.com/sv/events/event1','state':'releasedForSale',
            'eventHierarchyType':'event','unknownFutureField':'ignored'}


def kultur_event(city='Stockholm'):
    stamp=int(datetime(2027,3,15,18,tzinfo=timezone.utc).timestamp())
    return {'title':'Concert','url_event_page':'https://kulturbiljetter.se/evenemang/123/concert/',
            'images':{'0':'https://kulturbiljetter.se/storage/image.jpg'},
            'locations':{'0':{'location_id':1,'name':'Venue','city':city}},
            'dates':{'0':{'date_id':1,'location_id':1,'unixtime_start':stamp,'date_only':False},
                     '1':{'date_id':2,'location_id':1,'unixtime_start':stamp+86400,'date_only':True}}}


class TicksterTests(TestCase):
    def setUp(self):
        tickster._cache.clear()

    def test_geography_states_timezone_and_parent_productions(self):
        event=tickster.normalize(tickster_event())
        self.assertEqual(event['time'],'19:00')
        self.assertEqual(event['start'],'2027-03-15')
        self.assertEqual(event['image'],'')
        for city in ('Solna','Johanneshov',None):
            self.assertIsNone(tickster.normalize(tickster_event(city)))
        for state in ('cancelled','releasedForNonPublicSale'):
            data=tickster_event();data['state']=state
            self.assertIsNone(tickster.normalize(data))
        data=tickster_event();data['eventHierarchyType']='production'
        self.assertIsNone(tickster.normalize(data))
        data=tickster_event();data['infoUrl']='https://evil.example/';data['shopUrl']='https://evil.example/'
        self.assertIsNone(tickster.normalize(data))

    @patch.object(tickster.requests,'get')
    def test_header_auth_actual_offset_pagination_and_shared_cache(self, get):
        get.side_effect=[response({'totalItems':3,'items':[tickster_event(),tickster_event()]}),
                         response({'totalItems':3,'items':[tickster_event()]})]
        data=tickster.get_catalog('test-key','2027-01-01','2027-03-31')
        self.assertEqual(len(data['events']),3)
        self.assertEqual(get.call_args.kwargs['params'],{'query':'city:Stockholm','take':100,'skip':2})
        self.assertEqual(get.call_args.kwargs['headers'],{'X-API-KEY':'test-key'})
        self.assertFalse(get.call_args.kwargs['allow_redirects'])
        self.assertEqual(tickster.get_catalog('test-key','2027-07-01','2027-09-30')['events'],[])
        self.assertEqual(get.call_count,2)

    @patch.object(tickster.requests,'get')
    def test_missing_key_and_denied_access(self, get):
        with self.assertRaises(tickster.SourceUnavailable):tickster.get_catalog('')
        get.assert_not_called()
        get.return_value=response({},401)
        with self.assertRaises(tickster.SourceUnavailable):tickster.get_catalog('private-test-key')


class KulturbiljetterTests(TestCase):
    def setUp(self):
        with kultur._lock:
            kultur._indexes.clear();kultur._details.clear();kultur._attempts.clear();kultur._inflight.clear()

    def test_occurrences_location_matching_and_date_only(self):
        events=kultur.normalize(kultur_event(),'123')
        self.assertEqual(len(events),2)
        self.assertEqual(events[0]['time'],'19:00')
        self.assertEqual(events[1]['time'],'')
        self.assertNotEqual(events[0]['id'],events[1]['id'])
        self.assertEqual(kultur.normalize(kultur_event('Solna'),'123'),[])
        data=kultur_event();data['dates']['0']['location_id']=999
        self.assertEqual(len(kultur.normalize(data,'123')),1)
        data=kultur_event();data['url_event_page']='https://evil.example/'
        self.assertEqual(kultur.normalize(data,'123'),[])

    @patch.object(kultur.requests,'get')
    def test_index_details_etag_and_repeated_date_filters(self, get):
        get.side_effect=[response({'0':{'event_id':123,'ETag':'etag1'}}),response(kultur_event())]
        data=kultur.get_catalog('test-key','2027-01-01','2027-03-31')
        self.assertEqual(len(data['events']),2)
        self.assertFalse(data['pending'])
        self.assertEqual(get.call_args.kwargs['headers'],{'Authorization':'Token test-key'})
        self.assertFalse(get.call_args.kwargs['allow_redirects'])
        self.assertEqual(kultur.get_catalog('test-key','2027-07-01','2027-09-30')['events'],[])
        self.assertEqual(get.call_count,2)
        cache_key=next(iter(kultur._details));etag,stamp,raw=kultur._details[cache_key]
        kultur._details[cache_key]=(etag,stamp-3601,raw)
        get.side_effect=[response({},304)]
        again=kultur.get_catalog('test-key')
        self.assertEqual(len(again['events']),2)
        self.assertFalse(again['pending'])
        self.assertEqual(get.call_args.kwargs['headers']['If-None-Match'],'"etag1"')

    @patch.object(kultur.requests,'get')
    def test_large_index_is_loaded_in_bounded_batches_and_reports_partial_data(self, get):
        index={str(i):{'event_id':i+1,'ETag':'etag'} for i in range(45)}
        get.side_effect=lambda url,**kwargs: response(index if url==kultur.API else kultur_event())
        first=kultur.get_catalog('test-key')
        self.assertTrue(first['pending']);self.assertTrue(first['truncated'])
        self.assertEqual(get.call_count,41)
        second=kultur.get_catalog('test-key')
        self.assertFalse(second['pending']);self.assertFalse(second['truncated'])
        self.assertEqual(get.call_count,46)

    @patch.object(kultur.requests,'get')
    def test_missing_key_denied_access_and_malicious_event_id(self, get):
        with self.assertRaises(kultur.SourceUnavailable):kultur.get_catalog('')
        get.assert_not_called()
        get.return_value=response({},403)
        with self.assertRaises(kultur.SourceUnavailable):kultur.get_catalog('private-test-key')
        get.reset_mock();get.return_value=response({'0':{'event_id':'https://evil.example/','ETag':'x'}})
        self.assertEqual(kultur.get_catalog('different-key')['events'],[])
        self.assertEqual(get.call_count,1)


class NewProviderIntegrationTests(TestCase):
    def setUp(self):
        combined._cache.clear()

    @patch.object(combined,'_tickster_catalog')
    @patch.object(combined,'_kulturbiljetter_catalog')
    @patch.object(combined,'_visit_catalog')
    def test_new_sources_are_selectable_and_merge_to_one_event(self, visit, kultur_fetch, tickster_fetch):
        tickster_fetch.return_value={'events':[tickster.normalize(tickster_event())]}
        kultur_fetch.return_value={'events':kultur.normalize(kultur_event(),'123')[:1]}
        config={'TICKSTER_API_KEY':'test-tickster-key','KULTURBILJETTER_API_KEY':'test-kultur-key'}
        with patch.dict(app.config,config):
            client=app.test_client()
            page=client.get('/').get_data(as_text=True)
            self.assertIn('value="tickster" checked',page)
            self.assertIn('value="kulturbiljetter" checked',page)
            data=client.get('/api/combined-events?sources=tickster,kulturbiljetter&from_month=2027-01&to_month=2027-03').get_json()
            self.assertEqual(data['count'],1)
            self.assertEqual(set(data['events'][0]['sources']),{'Tickster','Kulturbiljetter'})
            self.assertEqual(data['events'][0]['link_source'],'Tickster')
            visit.assert_not_called()
            self.assertNotIn('test-tickster-key',page)
            self.assertNotIn('test-kultur-key',str(data))
