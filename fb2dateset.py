# coding=utf-8
import glob
from itertools import chain, imap
from lxml import etree
from optparse import OptionParser
import sys
import logging
from fb2tools import NotAFBZException, FB2_NSMAP, fb2tag
from fb2tools.book import Book as Fb2Book
from lxml.etree import DocumentInvalid
import os
from fantlab.author import Author

logger = logging.getLogger('fb2dateset')
frmttr = logging.Formatter('%(asctime)s %(name)s %(levelname)s %(message)s', '%Y-%m-%d %H:%M:%S')
shdlr = logging.StreamHandler(sys.stderr)
shdlr.setFormatter(frmttr)
logger.addHandler(shdlr)

parser = OptionParser()
parser.add_option('-a', '--author', dest='author', type='int', action='store')
parser.add_option('-s', '--strict', dest='strict', action='store_true', default=False)
parser.add_option('-v', '--verbose', dest='debug', action='store_true', default=False)
parser.add_option('-r', '--recursive', dest='recursive', action='store_true', default=False)

DS_INFO = etree.XPath('//f:description/*[contains(local-name(), "title-info")]', namespaces=FB2_NSMAP)
TAGS_BEFORE_DATE = map(fb2tag, ['genre', 'author', 'book-title', 'annotation', 'keywords'])

def prepare_args(rec, args):
    for arg in args:
        if os.path.isdir(arg):
            if rec:
                yield chain(
                    *map(
                        lambda x: imap(
                            lambda f: os.path.join(x[0], f),
                            x[2]),
                        os.walk(arg)
                    )
                )
            else:
                yield imap(lambda x: os.path.join(arg, x), os.listdir(arg))
        else:
            yield glob.iglob(arg)

def main(argv):
    options, args = parser.parse_args(args=argv)
    args = [x.decode(sys.stdin.encoding) for x in args]
    logger.setLevel(logging.DEBUG if options.debug else logging.INFO)

    a = Author(options.author)
    logger.info('Loading book list (%d)' % options.author)
    a.load()
    logger.info('%d books loaded' % len(a.books))

    for file in chain(*prepare_args(options.recursive, args)):
        if not os.path.isfile(file):
            logger.info('Skipping %s: not a file' % file)
            continue

        try:
            book = Fb2Book.fromFile(file, options.strict)
            if not book.isValid():
                logger.warn(u'Invalid file %s' % file)
        except NotAFBZException:
            logger.warning('Not a valid fbz file: ' + file)
            continue
        except DocumentInvalid, e:
            logger.error(u'Invalid file %s: %s' % (file, e))
            continue

        title = book.getTitle()
        b = a.findBook(title)
        if not b:
            logger.warn(u'No book %s found' % title)
            continue

        if not book.setYearAggressive(b.year):
            logger.debug(u'No changes are need to be made for «%s»' % title)
            continue
        else:
            logger.info(u'Book «%s» year is set to %d' % (title, b.year))

        book.save()

if __name__ == '__main__':
    main(sys.argv[1:])
