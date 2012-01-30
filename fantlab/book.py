# coding=utf-8
import re

class Book(object):
    BAD_CHARS = re.compile(ur'[, —\-.:]+')
    #noinspection PyRedeclaration
    def __init__(self, id, title, original, year):
        self._id = id
        self.title = title
        self.original = original
        self.alternative = []
        self.year = year

    def getUrl(self):
        return 'http://fantlab.ru/work%d' % self._id

    def addTitles(self, *titles):
        if self.title:
            self.alternative.extend(filter(lambda x: x.lower() != self.title.lower(), titles))
        else:
            self.alternative.extend(titles)

    @classmethod
    def compareTitle(cls, a, b):
        return cls._prepare(a) == cls._prepare(b)

    #noinspection PyRedeclaration
    @classmethod
    def _prepare(cls, title):
        title = title.lower()
        title = cls.BAD_CHARS.sub('', title)
        return title
