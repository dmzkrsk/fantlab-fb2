# coding=utf-8
from urllib2 import build_opener, Request
from urllib import urlencode

class WebClient(object):
    opener = build_opener()
    TIMEOUT = 15

    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/535.7 (KHTML, like Gecko) Chrome/16.0.912.75 Safari/535.7',
    }

    def open(self, url):
        r = Request(url, headers=self.HEADERS)
        return self.opener.open(r, timeout=self.TIMEOUT)

    def post(self, url, **data):
        post_data = urlencode(data)
        r = Request(url, post_data, self.HEADERS)
        return self.opener.open(r, timeout=self.TIMEOUT)
