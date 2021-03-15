import re
import typing
import logging
from abc import abstractmethod
from enum import Enum

import requests
from requests import HTTPError, ConnectionError
from bs4 import BeautifulSoup as Soup

from .request_wrapper import RequestWrapper

logging.basicConfig(level=logging.WARNING)

PTT_HEAD = "https://www.ptt.cc"
        
PTT_MIDDLE = "bbs"

HTTP_ERROR_MSG = "HTTP error {res.status_code} - {res.reason}"

INVALID_USERID = "_@#$%"

def parse_image(soup):
    def compensate_url(img_url):
        default_url = ""
        reg = re.compile(r'https:\/\/(i\.)*imgur.com\/\w+(?P<suffix>\.\w+)*')
        image_formats = ['jpeg', 'jpg', 'png', 'bmp']

        res = reg.search(img_url)

        if res:
            suffix = None if res.group('suffix') is None else res.group('suffix').split('.')[-1]
            if suffix is None:
                return img_url + '.jpg'
            
            if suffix not in image_formats:
                return default_url

            return img_url

        else:
            return default_url

    def is_image_url(url):
        regex = re.compile(r'(?:http\:|https\:)?\/\/.*\.(?:png|jpg|bmp|jpeg)')

        if regex.match(url):
            return True
        return False

    img_list = []
    for img in soup.find_all('a', rel='nofollow'):
        url = compensate_url(img['href'])
        if is_image_url(url):
            img_list.append(url)

    return img_list

def parse_metadata(soup):
    def remove_metadata(soup):
        """
        <div id="main-content" class="bbs-screen bbs-content">
            <div class="article-metaline">
                <span class="article-meta-tag">作者</span>
                <span class="article-meta-value">vezlo (五嶽山第4面101號B1)</span>
            </div>
            <div class="article-metaline-right">
                <span class="article-meta-tag">看板</span>
                <span class="article-meta-value">Gossiping
                </span>
            </div>
            <div class="article-metaline">
                <span class="article-meta-tag">標題
                </span>
                <span class="article-meta-value">[問卦] 完全控制ptt八卦板　現實能影響幾%台灣人？
                </span>
                </div>
            <div class="article-metaline">
                <span class="article-meta-tag">時間
                </span>
                <span class="article-meta-value">Tue Aug 18 20:39:44 2020
                </span>
            </div>
        """

        for meta in soup.select('div.article-metaline'):
            meta.clear()

        for meta in soup.select('div.article-metaline-right'):
            meta.clear()

    metas = soup.select('div.article-metaline')

    try:
        author = metas[0].find(class_='article-meta-value').text
        title = metas[1].find(class_='article-meta-value').text
        date = metas[2].find(class_='article-meta-value').text
    except Exception as e:
        author = INVALID_USERID
        title = 'unKnown'
        date = 'unKnown'
        logging.debug(f'structure was broken {metas}', e)

    remove_metadata(soup)
    return {
        'author' : author,
        'title' : title,
        'date' : date,
    }

def parse_content(soup):
    """ parse content and image urls inside the content
    """
    content = soup.text
    img_urls = parse_image(soup)

    return {
        'content' : content,
        'image_urls' : img_urls,
    }

def parse_pushers(soup):
    """ parse pusher
    """
    def push_tag_to_type(tag):
        if tag == u'推 ':
            return PttPushType.UP
        elif tag == u'噓 ':
            return PttPushType.DOWN
        else:
            return PttPushType.ARROW

    push_list = []

    pushes = soup.find_all('div', class_='push')
    for push in pushes:
        try:
            push_info = push.find_all('span')
            
            push_type = push_tag_to_type(push_info[0].text)
            name = push_info[1].text
            content = push_info[2].text[2:]
            date = push_info[3].text

            item = Push(name=name, push_type=push_type, content=content, date=date)

        except Exception as e:
            item = Push()
            logging.debug(f'structure was broken {push}', e)

        finally:
            push_list.append(item)

        push.extract()

    return {'push_list' : push_list}

def check_over_18(rs, board, endpoint):
    data = {
        'from' : "/{}/{}/{}".format(PTT_MIDDLE, board, endpoint),
        'yes' : 'yes',
    }
    try:
        res = rs.post("{}/ask/over18".format(PTT_HEAD), verify=False, data=data)
        res.raise_for_status()
    except HTTPError as exc:
        logging.warning(HTTP_ERROR_MSG.format(res=exc.response))
        raise Exception("Website is something wrong")
    except ConnectionError:
        raise Exception("Connection error")

class PttSpider(object):
    def __init__(self, url: str, **kargs):
        self.url = PttUrl(url=url)
        self.rs = kargs.get('rs', RequestWrapper())

    @abstractmethod
    def run(self):
        raise NotImplementedError()


class PttArticleListSpider(PttSpider):
    def __init__(self, url: str, **kargs):
        super().__init__(url, **kargs)
        self.max_fetch = kargs.get('max_fetch', 100)

        self._board_context = ""
        self._article_list = []

    def run(self):
        if self.url.type is not PttUrlType.BOARD:
            logging.warning(f"{self.url.url} is not a valid board url\n")
            return

        check_over_18(self.rs, self.url.board, self.url.endpoint)
        self._board_context = self.crawl_board_context()
        self._article_list = self.crawl_article_urls()

    def crawl_board_context(self):
        context = ""

        try:
            res = self.rs.get(self.url.url)
            res.raise_for_status()

            context = res.text
        except HTTPError as exc:
            logging.warning(HTTP_ERROR_MSG.format(res=exc.response))
            raise Exception("Website is something wrong")
        except ConnectionError:
            raise Exception("Connection error")

        return context

    def board_urls(self):
        reg = re.compile(r"index(?P<page_index>\d{0,6})")
        ep = reg.search(self.url.endpoint)

        if ep:
            page_index = ep.group('page_index')
            try:
                max_idx = int(page_index, 10)
            except ValueError:
                page_info = Soup(self._board_context, 'html.parser').select('.btn.wide')
                if len(page_info) < 2:
                    yield None
                    
                lastest_page = page_info[1]['href']
                res = reg.search(lastest_page)
                max_idx = int(res.group('page_index'), 10) + 1

            for idx in range(max_idx, 0, -1):
                yield f"{PTT_HEAD}/{PTT_MIDDLE}/{self.url.board}/index" + str(idx) + ".html"

            yield None
        else:
            yield None

    def crawl_article_urls(self):
        url_generator = self.board_urls()
        url = next(url_generator)
        article_urls = []

        while url is not None and len(article_urls) <= self.max_fetch:
            try:
                res = self.rs.get(url)
                res.raise_for_status()

                article_urls.extend(self.parse_per_article_url(res.text))

                url = next(url_generator)
            except HTTPError as exc:
                logging.warning(HTTP_ERROR_MSG.format(res=exc.response))
                raise Exception("Website is something wrong")
            except ConnectionError:
                raise Exception("Connection error")

        return article_urls[:self.max_fetch]

    @staticmethod
    def parse_per_article_url(context):
        logging.debug("Parse article urls")
        soup = Soup(context, "html.parser")
        urls = []

        for entry in soup.find_all(class_="r-ent"):
            try:
                url = entry.find('a')['href']
                if not url:
                    continue
                urls.append(PTT_HEAD + url)
            except Exception as e:
                logging.info("Article is deleted")
                logging.info(e)

        return urls

    @property
    def article_url_list(self):
        return self._article_list


class PttArticleSpider(PttSpider):
    PARSE_HANDLER = [
        parse_metadata,
        parse_pushers,
        parse_content,
    ]

    def __init__(self, url: str, **kargs):
        super().__init__(url, **kargs)

        self._article = ArticleInfo()

    def run(self):
        if self.url.type is not PttUrlType.ARTICLE:
            logging.warning(f"{self.url.url} is not a valid article url\n")
            return

        check_over_18(self.rs, self.url.board, self.url.endpoint)

        self.crawl_article()
        self.analyze_article()

    def crawl_article(self):
        url = self.url.url

        try:
            res = self.rs.get(url)
            res.raise_for_status()

            self._article = ArticleInfo(
                url=url, res=res)

        except HTTPError as exc:
            logging.warning(HTTP_ERROR_MSG.format(res=exc.response))
            raise Exception("Website is something wrong")

        except ConnectionError:
            raise Exception("Connection error")

    def analyze_article(self):
        info = {'url': self.url}

        res = self._article.res
        soup = Soup(res.text, 'html.parser')

        main_content = soup.find(id='main-content')
        for handler in PttArticleSpider.PARSE_HANDLER:
            info.update(handler(main_content))

        for key, val in info.items():
            if self._article is None:
                self._article = ArticleInfo()
            setattr(self._article, key, val)

    @property
    def article(self):
        return self._article


class PttUrl(object):
    PATTERN = rf"(?<={PTT_HEAD})*(?<={PTT_MIDDLE})/(?P<board>\w+)/(?P<endpoint>\S*)$"
    REGEX = re.compile(PATTERN)

    def __init__(self, url):
        self.info = {'url' : url}

        self.extract_url_info()

    def extract_url_info(self):
        res = self.parse_url(self.url)
        self.info.update(res)

    @classmethod
    def urlify(cls, board, endpoint="index.html"):
        paths = [PTT_HEAD, PTT_MIDDLE, board, endpoint]

        url = "/".join(path.strip('/') for path in paths)

        return url

    @staticmethod
    def parse_url(url: str) -> dict:
        res = PttUrl.REGEX.search(url)
        if (res):
            board = res.group("board")
            endpoint = res.group("endpoint") or "index.html"
            return {
                    "board" : board,
                    "endpoint" : endpoint,
                    "type" : PttUrl.url_type(endpoint),
                }
        else:
            return {
                    "type" : PttUrlType.UNKNOWN,
                }

    @staticmethod
    def url_type(endpoint):
        nr_dot = endpoint.count('.')

        """
            0: Article, others article list
            example:
                post:
                    https://www.ptt.cc/bbs/Gossiping/M.1600494295.A.ED9.html
                board:
                    https://www.ptt.cc/bbs/Gossiping/index39533.html
                    https://www.ptt.cc/bbs/Gossiping/index.html
                    https://www.ptt.cc/bbs/Gossiping/
        """
        if nr_dot <= 1:
            return PttUrlType.BOARD
        else:
            return PttUrlType.ARTICLE

    @staticmethod
    def verify_url(url: str) -> bool:
        res = PttUrl.parse_url(url)
        return res.get('type') is not PttUrlType.UNKNOWN

    @property
    def url(self):
        return self.info.get("url", "")

    @property
    def board(self):
        return self.info.get("board", "")
    
    @property
    def endpoint(self):
        return self.info.get("endpoint", "")

    @property
    def type(self):
        return self.info.get('type')

    def __str__(self):
        repr = f"{self.board} {self.endpoint}"
        print(self.board)
        print(self.endpoint)
        return repr


class PttUrlType(Enum):
    ARTICLE = 0
    BOARD = 1
    UNKNOWN = 2


class PttPushType(Enum):
    DOWN = -1
    ARROW = 0
    UP = 1


class Push(object):
    """Doc of Push """
    def __init__(self, **kargs):
        self.name = kargs.get("name", INVALID_USERID)
        self.content = kargs.get("content", "")
        self.push_type = kargs.get("push_type", PttPushType.ARROW)
        self.date = kargs.get("date", "")

        self.article_url = kargs.get("url", "")

    def update_to_db(self):
        pass

    def __str__(self):
        return "{} {}: {}".format(self.push_type, self.name, self.content)


class ArticleInfo(object):
    def __init__(self, **kargs):
        self.title = kargs.get("title", "")
        self.author = kargs.get("author", INVALID_USERID)
        self.content = kargs.get("content", "")
        self.date = kargs.get("date", "")

        self.url = kargs.get("url", PttUrl(""))
        self.res = kargs.get("res", None)

        self.push_list = []
        self.image_urls = []

    def update_to_db(self, engine):
        pass

    def __str__(self):
        repr = ""
        repr += "Title: {}\n".format(self.title)
        repr += "Author: {}\n".format(self.author)
        repr += "Content: {}\n".format(self.content)

        for pusher in self.push_list:
            repr += "{}\n".format(pusher)
        for url in self.image_urls:
            repr += "image url: {}\n".format(url)

        return repr
        
#c = PttArticleSpider(url="https://www.ptt.cc/bbs/Gossiping/M.1597754386.A.81A.html")
#c = PttArticleSpider(url="https://www.ptt.cc/bbs/Beauty/M.1600532955.A.C7F.html")
#c = PttArticleListSpider(url="https://www.ptt.cc/bbs/Gossiping/index.html")
#c = PttArticleListSpider(url="https://www.ptt.cc/bbs/jersey/index1.html")
#c = PttArticleListSpider(url="https://www.ptt.cc/bbs/Beauty/index.html")
