# coding=utf-8
from itertools import dropwhile, chain
from lxml import etree
from operator import itemgetter
import re
from book import Book
from common import ParseError
from web import WebClient

NOVEL = re.compile('(novel|(short|micro)?story|anth?ology|autorplans|documental|poem|article|essay|collection|other|notfinpub)_info')
CYCLE = re.compile('(cycle|mauthor)_info')

SEARCH_BLOCK = etree.XPath('//div/b[contains(text(), $key)]/following-sibling::p[a[contains(@href, "autor")] and following::b[preceding-sibling::b[position() = 1 and contains(text(), $key)]]]')

RE_WORK = re.compile('^/work(\d+)$')
YEAR_MATCH = re.compile('^\s*\((\d+)\).+')

def text_work(e):
    return not len(e) and 'href' in e.attrib and RE_WORK.match(e.attrib['href']) and e.text

def alt_text(e):
    return not len(e) and e.tag == 'font' and e.text and '[=' in e.text

def work_item(e):
    m = RE_WORK.match(e.attrib['href'])
    id = m.group(1)
    return int(id), e.text

class Author(object):
    URL = 'http://fantlab.ru/autor%(id)d'
    SEARCH = 'http://pda.fantlab.ru/search'

    web = WebClient()

    def __init__(self, id):
        self._id = id
        self.url = self.URL % {'id': id}
        self.books = []

        self._loaded = False

    def findBook(self, title):
        for b in self.books:
            for t in filter(None, chain([b.title], b.alternative)):
                if Book.compareTitle(t, title):
                    return b

        return None

    def load(self):
        if self._loaded:
            return

        page = self.web.open(self.url).read()
        tree = etree.HTML(page)

        self.books = []
        for body in tree.xpath('//tbody[@id]'):
            bodyID = body.attrib['id']
            if NOVEL.match(bodyID):
                parser = self._novel
            elif CYCLE.match(bodyID):
                parser = self._cycle
            else:
                raise ParseError('Unknown body: ' + bodyID)

            bookl = {}
            for book in parser(body):
                if book._id in bookl:
                    continue

                bookl[book._id] = book

            self.books.extend(bookl.itervalues())

        self._loaded = True

    @classmethod
    def _debug_x(cls, x):
        return etree.tostring(x, pretty_print=True, encoding='utf-8')

    def _cycle(self, body):
        for cell in body.xpath('./tr/td//div/span[a[contains(@href, "work")]]'):
            last_cell = dropwhile(lambda x: x.tag == 'nobr', reversed(cell)).next()
            m = YEAR_MATCH.match(last_cell.tail)
            if not m:
                continue

            year = int(m.group(1))

            yield self._make_book(cell, year)

    def _novel(self, body):
        for cell in body.xpath('./tr/td/div/span[a[contains(@href, "work")]]'):
            if cell[0].tail is None:
                continue
            # print self._debug_x(cell)
            assert cell[0].tag == 'img' and 'spacer' in cell[0].attrib['src']
            year = int(cell[0].tail)
            yield self._make_book(cell, year)

    def _make_book(self, cell, year):
        bookID, title, originalTitle = self._extract_titles(cell)

        book = Book(bookID, title, originalTitle, year)

        alt = filter(alt_text, cell)
        if alt:
            assert len(alt) == 1
            #noinspection PyUnresolvedReferences
            book.addTitles(*[x.strip() for x in re.split('\s*;\s+', alt[0].text.strip()[3:-1])])

        return book

    def _extract_titles(self, cell):
        titles = map(work_item, filter(text_work, cell))
        assert titles
        assert len(set(map(itemgetter(0), titles))) == 1
        bookID = titles[0][0]

        titles_text = tuple(map(itemgetter(1), titles))
        if len(titles_text) == 1:
            return bookID, None, titles_text[0]
        elif len(titles_text) == 2:
            return bookID, titles_text[0], titles_text[1]
        else:
            raise ParseError('Wrong title count')

    def getUrl(self):
        return 'http://fantlab.ru/autor%d' % self._id

    @classmethod
    def search(cls, str):
        """
        :type str: unicode
        """
        page = cls.web.post(cls.SEARCH, action='search', searchstr=str.encode('windows-1251')).read()
        tree = etree.HTML(page)

        for author_p in SEARCH_BLOCK(tree, key=u"Авторы"):
            aID = int(author_p.xpath('.//a/@href')[0][6:])
            yield Author(aID), cls.node_text(author_p)

    @classmethod
    def node_text(cls, node):
        return (node.text or '') + ''.join(map(cls.node_text, node)) + (node.tail or '')

if __name__ == '__main__':
    print list(Author.search(u'Энтони'))
