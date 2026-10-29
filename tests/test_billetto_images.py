import base64
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch

from itsdangerous import URLSafeSerializer
from app import app
import billetto_events
import billetto_images as images
import club_events

URL='https://billetto.imgix.net/test-banner?w=1200&h=675&s=signed-image'
PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/lS0AAAAASUVORK5CYII=')


def remote(body=PNG,status=200,headers=None):
    response=MagicMock()
    response.__enter__.return_value=response
    response.status_code=status
    response.headers=headers or {'Content-Length':str(len(body))}
    response.iter_content.return_value=[body]
    return response


class BillettoImageTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        patcher=patch.object(app,'instance_path',self.temp.name);patcher.start();self.addCleanup(patcher.stop)
        patcher=patch.dict(app.config,{'SECRET_KEY':'test-image-signing-key'});patcher.start();self.addCleanup(patcher.stop)
        self.client=app.test_client()

    def token(self,url=URL):
        return URLSafeSerializer('test-image-signing-key',salt='billetto-image-v1').dumps(url)

    @patch.object(images.requests,'get')
    def test_public_json_rewrites_image_without_downloading_during_catalog_load(self,get):
        with patch.object(club_events,'get_events',return_value={'events':[{'image':URL}]}):
            data=self.client.get('/api/combined-events?sources=billetto').get_json()
        path=data['events'][0]['image']
        self.assertTrue(path.startswith('/images/billetto/'))
        self.assertEqual(URLSafeSerializer('test-image-signing-key',salt='billetto-image-v1').loads(path.rsplit('/',1)[1]),URL)
        get.assert_not_called()

    @patch.object(images.requests,'get')
    def test_image_is_cached_and_conditional_request_avoids_download(self,get):
        get.return_value=remote()
        path='/images/billetto/'+self.token()
        with self.client.get(path) as response:
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.mimetype,'image/png')
            self.assertEqual(response.data,PNG)
            self.assertEqual(response.headers['X-Content-Type-Options'],'nosniff')
            etag=response.headers['ETag']
        with self.client.get(path,headers={'If-None-Match':etag}) as response:
            self.assertEqual(response.status_code,304)
        get.assert_called_once()
        self.assertFalse(get.call_args.kwargs['allow_redirects'])
        self.assertTrue(get.call_args.kwargs['stream'])
        self.assertNotIn('Authorization',get.call_args.kwargs['headers'])
        self.assertNotIn('Api-Keypair',get.call_args.kwargs['headers'])
        self.assertEqual(images._inflight,{})

    @patch.object(images.requests,'get')
    def test_invalid_signature_and_untrusted_hosts_do_not_make_requests(self,get):
        for token in ('invalid-token',self.token('https://evil.example/image.jpg'),self.token('http://billetto.imgix.net/a'),
                      self.token('https://billetto.imgix.net.evil.example/a'),self.token('https://billetto.imgix.net@127.0.0.1/a')):
            self.assertEqual(self.client.get('/images/billetto/'+token).status_code,404)
        get.assert_not_called()

    @patch.object(images.requests,'get')
    def test_redirect_html_and_oversized_images_are_rejected(self,get):
        for response in (remote(status=302),remote(body=b'<html>not an image</html>'),
                         remote(headers={'Content-Length':str(images.MAX_IMAGE_BYTES+1)})):
            get.return_value=response
            self.assertEqual(self.client.get('/images/billetto/'+self.token()).status_code,404)
        self.assertEqual(list(Path(self.temp.name).rglob('*.img')),[])
        self.assertEqual(images._inflight,{})

    @patch.object(images.requests,'get')
    def test_streaming_limit_is_enforced_without_content_length(self,get):
        response=remote(headers={'Content-Type':'image/png'})
        response.iter_content.return_value=[PNG,b'x'*100]
        get.return_value=response
        with patch.object(images,'MAX_IMAGE_BYTES',len(PNG)+1):
            self.assertEqual(self.client.get('/images/billetto/'+self.token()).status_code,404)

    @patch.object(images.requests,'get')
    def test_disk_cleanup_only_removes_owned_cache_files(self,get):
        folder=Path(self.temp.name)/'event-images'/'billetto';folder.mkdir(parents=True)
        old=folder/(('a'*64)+'.img');old.write_bytes(b'x'*80)
        other=folder/'notes.txt';other.write_text('keep',encoding='utf-8')
        get.return_value=remote()
        with patch.object(images,'MAX_CACHE_BYTES',len(PNG)+1):
            with self.client.get('/images/billetto/'+self.token()) as response:
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.data,PNG)
        self.assertFalse(old.exists());self.assertTrue(other.exists())

    def test_billetto_image_can_fill_missing_image_on_ticketmaster_duplicate(self):
        common={'title':'Kent','venue':'3Arena','city':'Stockholm','start':'2027-03-15','end':'2027-03-15','time':'19:00','category':'Music'}
        ticket=club_events.normalize({**common,'url':'https://www.ticketmaster.se/event/123'},'Ticketmaster')
        billetto=club_events.normalize({**common,'url':'https://billetto.se/e/kent-123?utm_source=club','image':URL},'Billetto')
        merged=club_events.deduplicate([ticket,billetto])
        self.assertEqual(len(merged),1)
        self.assertEqual(merged[0]['link_source'],'Ticketmaster')
        with app.test_request_context('/'):
            data=images.prepare_images({'events':merged})
        self.assertTrue(data['events'][0]['image'].startswith('/images/billetto/'))
        self.assertEqual(data['events'][0]['sources'],['Billetto','Ticketmaster'])
