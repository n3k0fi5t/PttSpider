from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import logging
import hashlib

logging.basicConfig(level=logging.DEBUG)

import PttSpider as Spider

TARGET_DIR = os.path.curdir

TARGET_LIST = [
    'https://www.ptt.cc/bbs/beauty/',
    'https://www.ptt.cc/bbs/Gossiping/index.html',
    'https://www.ptt.cc/bbs/aaa/',
]

def generate_result_filename(url):
    name = bytes(url, 'utf-8')
    return str(hashlib.sha256(name).hexdigest()) + '.txt'

def app(url, **kargs):
    spider = Spider.PttArticleSpider(url, rs=Spider.RequestWrapper() ,**kargs)
    spider.run()

    return spider.article

def main(board_urls):
    for board_url in board_urls:
        spider = Spider.PttArticleListSpider(board_url, max_fetch=2)
        spider.run()

        article_urls = spider.article_url_list

        with ThreadPoolExecutor(os.cpu_count()*3) as executor:
            futures = {executor.submit(app, url):url for url in article_urls}
            for future in as_completed(futures):
                url = futures[future]
                try:
                    article = future.result()

                    filename = generate_result_filename(url)
                    with open(os.path.join(TARGET_DIR, filename), 'w+') as fp:
                        fp.write(str(article))

                except Exception as e:
                    logging.debug(f'{url} generated an exception {e}')

if __name__ == '__main__':
    main(TARGET_LIST)
