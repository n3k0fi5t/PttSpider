import requests
import requests.packages.urllib3

from fake_useragent import UserAgent

requests.packages.urllib3.disable_warnings()

ua = UserAgent()

class RequestWrapper(object):
    def __init__(self):
        self._rs = requests.session()
        self._headers = {
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": ua.random,
        }

    def post(self, url, **kargs):
        kargs.update(headers=self._headers)

        return self._rs.post(url, **kargs)

    def get(self, url, **kargs):
        kargs.update(headers=self._headers)

        return self._rs.get(url, **kargs)
