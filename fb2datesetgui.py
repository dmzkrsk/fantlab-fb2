# coding=utf-8
from PyQt4.QtCore import QDir, QAbstractItemModel, QVariant, Qt, QModelIndex, QThread, pyqtSignal, QSize, QDirIterator, QFileInfo
from PyQt4.QtGui import *
import sys
from fb2tools import NotAFBZException, ImageLoadException
from fb2tools.book import Book as Fb2Book
from fb2tools.formatter import SimpleAuthorFormatter
from urllib2 import URLError
import webbrowser
from fantlab.author import Author
from lxml.etree import DocumentInvalid
import subprocess
import os
from taskpool import Task, TaskPool

APP_TITLE = '.fb2 date tool'
MAX_THREADS = 4
FB2_MASKS = ["*.fb2", "*.fb2.zip", "*.fbz"]

#noinspection PyRedeclaration
class BookItem(object):
    def __init__(self, fileinfo):
        self.info = fileinfo
        self.author = None
        self.title = None
        self.original = None
        self.year = None
        self.book = None

        self._short = None
        self._message = None
        self._icon = None

    def setMeta(self, author, title, original, year, book):
        self.author = author
        self.title = title
        self.original = original
        self.year = year
        self.book = book

    def setMessage(self, icon, short, message=None):
        self._icon = icon
        self._short = short
        self._message = message

    def getLong(self):
        return self._message

    def getShort(self):
        return self._short

    def getIcon(self):
        return self._icon

class Filelist(QAbstractItemModel):
    COLUMNS = [
        '',
        u'Файл',
        u'Автор',
        u'Название',
        u'Год',
        u'Статус'
    ]

    STATE_WORKING = 1000

    processCompleted = pyqtSignal()
    rowsChanged = pyqtSignal(int)

    def __init__(self):
        QAbstractItemModel.__init__(self)

        self.ICON_ERROR = QPixmap('res/error.png')
        self.ICON_FB = QPixmap('res/fb2-16x16.png')
        self.data = []

        self.processThread = None

    def populateFiles(self, fileinfos):
        infos = []
        for fileinfo in fileinfos:
            if any(x.info.absoluteFilePath() == fileinfo.absoluteFilePath() for x in self.data):
                continue
            infos.append(BookItem(fileinfo))

        if not infos:
            return

        infos.sort(key=lambda x: x.info.absoluteFilePath())

        l = len(self.data)
        i = len(infos)
        self.beginInsertRows(QModelIndex(), l, l + i - 1)
        self.data.extend(infos)
        self.endInsertRows()
        #noinspection PyUnresolvedReferences
        self.rowsChanged.emit(len(self.data))

    def populateDir(self, dir, rec):
        it = QDirIterator(dir, FB2_MASKS, QDir.Files, QDirIterator.Subdirectories if rec else QDirIterator.NoIteratorFlags)
        fileinfos = self.qdIterator(it)
        self.populateFiles(fileinfos)

    @classmethod
    def qdIterator(cls, it):
        while it.hasNext():
            it.next()
            yield it.fileInfo()

    def parent(self, index=QModelIndex()):
        return QModelIndex()

    def index(self, row, col, parent=QModelIndex(), *args, **kwargs):
        if parent.isValid() and parent.column() != 0:
            return QModelIndex()

        if row >= len(self.data):
            return QModelIndex()

        return self.createIndex(row, col, id(self.data[row]))

    def rowCount(self, parent=QModelIndex(), *args, **kwargs):
        if parent.isValid():
            return 0
        return len(self.data)

    def columnCount(self, QModelIndex_parent=None, *args, **kwargs):
        return len(self.COLUMNS)

    def data(self, index, role):
        """
        :type index: QModelIndex
        :type role: int
        """
        if not index.isValid():
            return QVariant()

        if index.row() >= len(self.data):
            return QVariant()

        item = self.data[index.row()]

        if role == Qt.DisplayRole:
            if index.column() == 1:
                return item.info.fileName()
            elif index.column() == 2:
                return item.author or QVariant()
            elif index.column() == 3:
                return item.title or QVariant()
            elif index.column() == 4:
                return str(item.year) if item.year else QVariant()
            elif index.column() == 5:
                return item.getShort() or QVariant()
            else:
                return QVariant()
        elif role == Qt.DecorationRole:
            icon = item.getIcon()
            if index.column() == 0 and icon is not None:
                return icon
            else:
                return QVariant()
        elif role == Qt.ToolTipRole:
            if index.column() == 1:
                return item.info.absoluteFilePath()
            elif index.column() == 3:
                return item.original or ''
            elif index.column() == 5:
                return item.getLong() or QVariant()
            else:
                return QVariant()
        else:
            return QVariant()

    def headerData(self, section, orientation, role=None):
        """
        :type orientation Qt.Orientation
        """

        if role != Qt.DisplayRole:
            return QVariant()

        if orientation == Qt.Horizontal:
            return self.COLUMNS[section]
        else:
            return ''

    def removeRow(self, row, parent=QModelIndex(), *args, **kwargs):
        index = self.index(row, 0)

        item = index.internalPointer()
        pos = self.data.index(item)
        self.beginRemoveRows(QModelIndex(), pos, pos)
        self.data.remove(item)
        self.endRemoveRows()
        #noinspection PyUnresolvedReferences
        self.rowsChanged.emit(len(self.data))

    ############################################3

    def _dataAvailable(self, bf, data):
        self.beginResetModel()
        bf.setMeta(*data)
        self.endResetModel()

    def _bookFinished(self, task):
        self.beginResetModel()

        try:
            message = task.getResult()
            task.bf.setMessage(self.ICON_FB, message)
        except NotAFBZException:
            task.bf.setMessage(self.ICON_ERROR, u'Файл не является fbz-книгой')
        except DocumentInvalid, e:
            task.bf.setMessage(self.ICON_ERROR, u'Файл не является валидным xml-документом', unicode(e))
        except ProcessBook.Error, e:
            task.bf.setMessage(self.ICON_ERROR, u'Ошибка обработки', unicode(e))
        except Exception, e:
            task.bf.setMessage(self.ICON_ERROR, u'Неизвестная ошибка', unicode(e))

        self.endResetModel()

    def _bookStarted(self, task):
        self.beginResetModel()
        task.bf.setMessage(None, u'Файл обрабатывается')
        self.endResetModel()

    def stop(self):
        self.processThread.finish()

    def processComplete(self):
        self.beginResetModel()
        for t in self.processThread.tasksLeft:
            t.bf.setMessage(None, u'Остановлено')
        self.endResetModel()

        self.processThread = None
        #noinspection PyUnresolvedReferences
        self.processCompleted.emit()

    def process(self, author, strict, selection):
        if self.processThread is not None:
            return

        if not selection:
            #noinspection PyUnresolvedReferences
            self.processCompleted.emit()
            return

        self.processThread = ProcessBooks(author, strict)

        self.beginResetModel()
        for index in selection:
            bf = index.internalPointer()
            bf.setMessage(None, u'Подготавливаем файл')
            p = ProcessBook(bf, author, strict)
            #noinspection PyUnresolvedReferences
            p.dataAvailable.connect(self._dataAvailable)
            self.processThread.addTask(p)
        self.endResetModel()

        self.processThread.finished.connect(self.processComplete)
        #noinspection PyUnresolvedReferences
        self.processThread.taskDone.connect(self._bookFinished)
        #noinspection PyUnresolvedReferences
        self.processThread.taskStart.connect(self._bookStarted)
        self.processThread.start()

class ProcessBook(Task):
    dataAvailable = pyqtSignal(BookItem, object)

    class Error(Exception):
        pass

    def __init__(self, bookf, author, strict):
        Task.__init__(self)

        self.bf = bookf
        self._author = author
        self._strict = strict
        self._path = unicode(self.bf.info.absoluteFilePath())

    def __call__(self):
        book = Fb2Book.fromFile(self._path, self._strict)

        title = book.getTitle()
        if not title:
            raise ProcessBook.Error(u'У книги отсутствует название')
        original = book.getTitle(True)
        sa = SimpleAuthorFormatter()
        author = ', '.join(map(sa.format, book.getAuthors()))

        b = self._author.findBook(title)
        if not b:
            #noinspection PyUnresolvedReferences
            self.dataAvailable.emit(self.bf, (author, title, original, book.getYearAggressive(), None))
            raise ProcessBook.Error(u'Книга с названием «%s» не найдена в библиографии' % title)
        else:
            #noinspection PyUnresolvedReferences
            self.dataAvailable.emit(self.bf, (author, title, b.original, b.year, b))

        if not book.setYearAggressive(b.year):
            return u'Изменений не требуется'

        book.save()

        return u'Файл сохранен'

class ProcessBooks(QThread):
    taskDone = pyqtSignal(Task)
    taskStart = pyqtSignal(Task)

    def __init__(self, author, strict):
        QThread.__init__(self)
        self._author = author
        self._strict = strict
        self._tasks = []

        self._pool = TaskPool(MAX_THREADS, self._taskStart)
        #noinspection PyUnresolvedReferences
        self._pool.finished.connect(self._poolFinished)
        self._finish = False
        self._tasksCount = 0

        self.tasksLeft = []

    def finish(self):
        self._pool.finish()

    def addTask(self, task):
        if self.isRunning() or self.isFinished():
            raise RuntimeError("Wrong state")

        self._tasks.append(task)
        self._tasksCount += 1

    def run(self):
        try:
            self._author.load()
        except Exception:
            for task in self._tasks:
                task.setError(sys.exc_info())
                self._taskCallback(task)
            return

        if self._finish:
            self.tasksLeft = self._tasks
            return

        for task in self._tasks:
            self._pool.put(task, self._taskCallback)

        while not self._finish:
            #noinspection PyArgumentList
            QApplication.processEvents()

        self.tasksLeft = list(self._pool.tasksLeft())

    def _taskCallback(self, task):
        #noinspection PyUnresolvedReferences
        self.taskDone.emit(task)

        self._tasksCount -= 1
        if not self._tasksCount:
            self._finish = True

    def _taskStart(self, task):
        #noinspection PyUnresolvedReferences
        self.taskStart.emit(task)

    def _poolFinished(self):
        self._finish = True

class AuthorSearch(QThread):
    taskDone = pyqtSignal(list)
    taskError = pyqtSignal(Exception)

    def __del__(self):
        self.wait()

    def __init__(self, arg):
        QThread.__init__(self)
        self._search = arg

    #noinspection PyUnresolvedReferences
    def run(self):
        try:
            self.taskDone.emit(list(Author.search(self._search)))
        except Exception, e:
            self.taskError.emit(e)

class CellDelegate(QItemDelegate):
    def paint(self, painter, option, index):
        """
        :type painter: QPainter
        """

        px = option.rect.x()
        py = option.rect.y()
        ph = option.rect.height()
        pw = option.rect.width()

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        #noinspection PyArgumentList
        painter.setPen(
            QPen(QBrush(option.palette.color(QPalette.Dark)), 1, style=Qt.DotLine, join=Qt.RoundJoin)
        )
        painter.drawLine(px, py + ph, px + pw, py + ph)
        painter.drawLine(px + pw, py, px + pw, py + ph)
        # painter.drawRect(px, py, pw, ph)
        painter.restore()

        QItemDelegate.paint(self, painter, option, index)

    def sizeHint(self, option, index):
        s = QItemDelegate.sizeHint(self, option, index)
        return QSize(s.width() + 10, s.height() + 4)

def centerOnScreen(w):
    resolution = QDesktopWidget().screenGeometry()
    w.move((resolution.width() / 2) - (w.frameSize().width() / 2),
        (resolution.height() / 2) - (w.frameSize().height() / 2))

class TextDialog(QDialog):
    def __init__(self):
        QWidget.__init__(self)

        self.text = QTextEdit()
        self.setWindowTitle(APP_TITLE)
        layout = QVBoxLayout()
        layout.addWidget(self.text)
        self.setLayout(layout)

    def setText(self, text):
        self.text.setText(text)

class QLabelExpand(QLabel):
    def mouseDoubleClickEvent(self, event):
        """
        :type event: QMouseEvent
        """
        # QLabel.mouseDoubleClickEvent(self, event)

        text = self.text()
        t = TextDialog()
        t.setText(text)
        t.setGeometry(0, 0, 600, 300)
        centerOnScreen(t)
        t.exec_()

class Launcher(object):
    def __init__(self, item):
        self._item = item

    def __call__(self):
        raise NotImplemented()

class LaunchFile(Launcher):
    def __call__(self):
        file = unicode(self._item.info.absoluteFilePath())
        if sys.platform == 'linux2':
            subprocess.call(["xdg-open", file])
        else:
            #noinspection PyUnresolvedReferences
            os.startfile(file)

class LaunchWeb(Launcher):
    def __call__(self):
        webbrowser.open(self._item.book.getUrl())

class BookListView(QTreeView):
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete:
            self.deleteItems()
        else:
            return QTreeView.keyPressEvent(self, event)

    def contextMenuEvent(self, event):
        """
        :type event: QContextMenuEvent
        """
        index = self.indexAt(event.pos())

        if not index.isValid():
            return

        item = index.internalPointer()

        menu = QMenu(self)
        w = menu.addAction(QIcon('res/delete.png'), u"Удалить", self.deleteItems)
        w.setIconVisibleInMenu(True)
        w.setEnabled(bool(self.selectionModel().selectedIndexes()))
        menu.addAction(QIcon('res/open.png'), u"Открыть файл", LaunchFile(item)).setIconVisibleInMenu(True)
        w = menu.addAction(QIcon('res/web.png'), u"Открыть страницу книги в браузере", LaunchWeb(item))
        w.setEnabled(bool(item.book))
        w.setIconVisibleInMenu(True)
        #noinspection PyArgumentList
        menu.popup(QCursor.pos())

    def deleteItems(self):
        indexes = self.currentSelection()
        rows = [x.row() for x in indexes]
        rows.sort(reverse=True)
        [self.model().removeRow(x) for x in rows]

        modelSize = self.model().rowCount()
        if not modelSize:
            return

        minRow = rows[-1]

        if minRow >= modelSize:
            minRow = modelSize - 1

        newSelection = self.model().index(minRow, 0)
        if newSelection.isValid():
            self.selectionModel().select(newSelection, QItemSelectionModel.Rows|QItemSelectionModel.Select)

    def currentSelection(self):
        return [
        x for x in
        self.selectionModel().selectedIndexes()
        if x.column() == 0
        ]


class MainWindow(QWidget):
    COVER_W, COVER_H = 250, 300

    def __init__(self):
        QWidget.__init__(self)

        self._prevDir = None

        self.showBookButton = QPushButton(QIcon('res/web.png'), '')
        self.showBookButton.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        self.showBookButton.clicked.connect(self.showBook)

        self.launchButton = QPushButton(QIcon('res/open.png'), '')
        self.launchButton.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        self.launchButton.clicked.connect(self.launchSelected)

        self.deleteButton = QPushButton(QIcon('res/delete.png'), '')
        self.deleteButton.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)

        self.processButton = QPushButton(QIcon('res/run.png'), u"Обработать файлы")
        self.processButton.clicked.connect(self.process)
        self.processButton.setEnabled(False)

        self.stopButton = QPushButton(QIcon('res/stop.png'), u"Отмена обработки")
        self.stopButton.hide()
        self.stopButton.clicked.connect(self.stop)

        self.strict = QCheckBox(u"Строгая обработка")
        self.strict.setChecked(True)

        self.filelist = Filelist()
        self.booklist = BookListView()

        font = QFont()
        font.setPixelSize(13)
        self.booklist.setFont(font)
        self.booklist.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.MinimumExpanding)
        self.booklist.setModel(self.filelist)
        self.booklist.setItemDelegate(CellDelegate())
        self.booklist.activated.connect(self.launch)
        self.booklist.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.booklist.selectionModel().selectionChanged.connect(self.selection)

        #noinspection PyUnresolvedReferences
        self.filelist.rowsChanged.connect(self.rowsChanged)

        self.deleteButton.clicked.connect(self.booklist.deleteItems)

        self.itemStatus = QLabelExpand()
        self.itemStatus.setWordWrap(True)
        self.itemStatus.setFixedHeight(36)
        self.itemStatus.setFrameStyle(QFrame.Panel | QFrame.Sunken)
        self.itemStatus.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Preferred)
        self.itemStatus.setTextInteractionFlags(Qt.TextSelectableByKeyboard|Qt.TextSelectableByMouse)

        self.searchBox = QLineEdit()
        self.searchBox.setMaximumWidth(250)
        self.searchBox.textChanged.connect(self.searchTextChanged)
        self.searchBox.returnPressed.connect(self.searchButtonClicked)

        self.searchButton = QPushButton(QIcon('res/search.png'), u'Поиск')
        self.searchButton.setEnabled(False)
        self.searchButton.clicked.connect(self.searchButtonClicked)

        self.searchResults = QComboBox()
        self.searchResults.setMinimumWidth(300)
        self.searchResults.setEnabled(False)
        self.searchResults.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Preferred)
        self.searchResults.currentIndexChanged.connect(self.authorSelectionChanged)

        self.authorWeb = QPushButton(QIcon('res/web.png'), '')
        self.authorWeb.setEnabled(False)
        self.authorWeb.clicked.connect(self.openAuthorWeb)

        self.fbuttons = QHBoxLayout()
        self.fbuttons.addStretch(1)

        self._nocover = QPixmap('res/nocover.png')

        self.bookCover = QLabel()
        self.bookCover.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.bookCover.setFixedSize(self.COVER_W, self.COVER_H)

        f = QFont()
        f.setBold(True)

        self.bookAuthor = QLabel()
        self.bookAuthor.setMaximumWidth(self.COVER_W)
        self.bookAuthor.setMaximumHeight(100)
        self.bookAuthor.setWordWrap(True)
        self.bookAuthor.setAlignment(Qt.AlignHCenter)
        f.setPointSize(18)
        self.bookAuthor.setFont(f)

        self.bookTitle = QLabel()
        self.bookTitle.setMaximumWidth(self.COVER_W)
        self.bookAuthor.setMaximumHeight(200)
        self.bookTitle.setWordWrap(True)
        self.bookTitle.setAlignment(Qt.AlignHCenter)
        f.setPointSize(14)
        self.bookTitle.setFont(f)

        h = self.booklist.header()
        h.setResizeMode(QHeaderView.ResizeToContents)

        self.searchThread = None

        self.initUI()
        self.resetNoSelection()

    def resetNoSelection(self):
        self.launchButton.setEnabled(False)
        self.deleteButton.setEnabled(False)
        self.showBookButton.setEnabled(False)
        self.itemStatus.setText('')

        self.bookAuthor.setText('')
        self.bookTitle.setText('')
        self.bookCover.setPixmap(self._nocover)

    #noinspection PyUnusedLocal
    def selection(self, set, unset):
        curSel = [x for x in self.booklist.currentSelection() if x.isValid()]
        if not curSel:
            self.resetNoSelection()
            return

        cur = curSel[0]

        self.launchButton.setEnabled(True)
        self.deleteButton.setEnabled(True)
        self.showBookButton.setEnabled(any(x.isValid() and x.internalPointer().book is not None for x in self.booklist.currentSelection()))
        self.itemStatus.setText((cur.internalPointer().getLong() or cur.internalPointer().getShort()) or '')

        path = unicode(cur.internalPointer().info.absoluteFilePath())
        book = Fb2Book.fromFile(path)

        sa = SimpleAuthorFormatter(False)
        author = ', '.join(map(sa.format, book.getAuthors()))
        self.bookAuthor.setText(author)
        self.bookTitle.setText(book.getTitle())

        cover = book.getCover()
        try:
            coverData = book.getImageData(cover)
        except ImageLoadException:
            coverData = None

        if not coverData:
            self.bookCover.setPixmap(self._nocover)
            return

        coverImage = QPixmap()
        coverImage.loadFromData(coverData)
        coverScaled = coverImage.scaled(self.COVER_W, self.COVER_H, Qt.KeepAspectRatio)
        self.bookCover.setPixmap(coverScaled)

    def showBook(self):
        for index in self.booklist.currentSelection():
            if index.isValid():
                LaunchWeb(index.internalPointer())()

    def launchSelected(self):
        for index in self.booklist.currentSelection():
            if index.isValid():
                self.launch(index)

    def launch(self, index):
        LaunchFile(index.internalPointer())()

    #noinspection PyCallByClass,PyTypeChecker
    def addDir(self, rec=False):
        dir = QFileDialog.getExistingDirectory(self, u"Укажите начальную папку",
            directory=self._prevDir or ''
        )

        self.booklist.setFocus()

        if dir is None:
            return

        self._prevDir = dir

        self.filelist.populateDir(dir, rec)
        self.booklist.setFocus()

    def addDirRec(self):
        self.addDir(True)

    def addFiles(self):
        #noinspection PyTypeChecker,PyCallByClass
        fileinfos = map(QFileInfo,
            QFileDialog.getOpenFileNames(self,
                u"Выберите файлы",
                directory=self._prevDir or '',
                filter=u"Книги (%s)" % ' '.join(FB2_MASKS),
                options=QFileDialog.ReadOnly)
        )

        self.booklist.setFocus()

        if not fileinfos:
            return

        self._prevDir = fileinfos[0].absoluteDir().absolutePath()

        self.filelist.populateFiles(fileinfos)

    def initUI(self):
        searchLabel = QLabel(u'Автор')

        authorbox = QHBoxLayout()
        authorbox.addWidget(searchLabel)
        authorbox.addWidget(self.searchBox)
        authorbox.addWidget(self.searchButton)
        authorbox.addWidget(self.searchResults)
        authorbox.addWidget(self.authorWeb)

        b = QPushButton(QIcon('res/folder.png'), u'Добавить папку')
        b.clicked.connect(self.addDir)
        self.fbuttons.addWidget(b)
        b = QPushButton(QIcon('res/folder-r.png'), u'Добавить папку (рекурсивно)')
        b.clicked.connect(self.addDirRec)
        self.fbuttons.addWidget(b)
        b = QPushButton(QIcon('res/fb2-16x16.png'), u'Добавить файлы')
        b.clicked.connect(self.addFiles)
        self.fbuttons.addWidget(b)

        vbox = QVBoxLayout()
        vbox.addLayout(authorbox)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)

        vbox.addWidget(line)

        vbox.addLayout(self.fbuttons)

        bookActions = QHBoxLayout()
        bookActions.setAlignment(Qt.AlignHCenter)
        bookActions.addWidget(self.launchButton)
        bookActions.addWidget(self.deleteButton)
        bookActions.addWidget(self.showBookButton)

        bkinfobox = QVBoxLayout()
        bkinfobox.addWidget(self.bookCover)
        bkinfobox.addLayout(bookActions)
        bkinfobox.addWidget(self.bookAuthor)
        bkinfobox.addWidget(self.bookTitle)
        bkinfobox.addStretch(1)

        bklbox = QHBoxLayout()
        bklbox.addLayout(bkinfobox)

        line = QFrame()
        line.setFrameShape(QFrame.VLine)
        line.setFrameShadow(QFrame.Sunken)

        bklbox.addWidget(line)

        bksbox = QVBoxLayout()
        bksbox.addWidget(self.booklist)
        bksbox.addWidget(self.itemStatus)
        bklbox.addLayout(bksbox)

        vbox.addLayout(bklbox)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)

        vbox.addWidget(line)

        sbuttons = QHBoxLayout()
        sbuttons.addStretch(1)

        sbuttons.addWidget(self.strict)
        sbuttons.addWidget(self.processButton)
        sbuttons.addWidget(self.stopButton)

        vbox.addLayout(sbuttons)

        self.setLayout(vbox)
        self.setGeometry(0, 0, 1000, 600)
        centerOnScreen(self)
        self.setWindowTitle(APP_TITLE)

        self.show()

    def searchTextChanged(self, str):
        self.searchButton.setEnabled(bool(str))

    def searchButtonClicked(self):
        if self.searchThread is not None:
            return

        search = self.searchBox.text()
        if not search:
            return
        self.searchThread = AuthorSearch(unicode(search))

        self.searchResults.clear()
        self.searchResults.setEnabled(False)
        self.searchBox.setEnabled(False)
        self.searchButton.setEnabled(False)

        #noinspection PyUnresolvedReferences
        self.searchThread.finished.connect(self.searchFinished)
        #noinspection PyUnresolvedReferences
        self.searchThread.taskDone.connect(self.searchSuccessful)
        #noinspection PyUnresolvedReferences
        self.searchThread.taskError.connect(self.searchFailed)

        self.searchThread.start()

    def searchSuccessful(self, found):
        self.searchResults.clear()
        self.searchResults.setEnabled(bool(found))

        if found:
            self.searchResults.addItem(u'[Выберите автора]', None)
        else:
            #noinspection PyTypeChecker,PyCallByClass
            QMessageBox.information(self, u'Information', u'Не найдено авторов', QMessageBox.Ok)

        for authorInstance, authorName in found:
            self.searchResults.addItem(authorName, authorInstance)


    def searchFailed(self, _e):
        try:
            raise _e
        except URLError:
            #noinspection PyTypeChecker,PyCallByClass
            QMessageBox.warning(self, u'Error', u'Ошибка сети', QMessageBox.Ok)
        except Exception, e:
            #noinspection PyTypeChecker,PyCallByClass
            QMessageBox.warning(self, u'Error', unicode(e), QMessageBox.Ok)

    def searchFinished(self):
        self.searchThread = None
        self.searchBox.setEnabled(True)
        self.searchButton.setEnabled(bool(self.searchBox.text()))

    def authorSelectionChanged(self, index):
        if index >= self.searchResults.count() or self.searchResults.itemData(index).toPyObject() is None:
            self.processButton.setEnabled(False)
            self.authorWeb.setEnabled(False)
        else:
            self.processButton.setEnabled(True)
            self.authorWeb.setEnabled(True)

    def openAuthorWeb(self):
        author = self.searchResults.itemData(self.searchResults.currentIndex()).toPyObject()
        webbrowser.open(author.getUrl())

    def process(self):
        self.processButton.hide()
        self.stopButton.show()
        self.stopButton.setEnabled(True)

        self.enableLayout(self.fbuttons, False)

        strict = self.strict.isChecked()

        #noinspection PyUnresolvedReferences
        self.filelist.processCompleted.connect(self.processCompleted)
        author = self.searchResults.itemData(self.searchResults.currentIndex()).toPyObject()

        indexes = self.booklist.currentSelection()
        if not len(indexes):
            indexes = [self.filelist.index(row, 0) for row in xrange(self.filelist.rowCount())]
        self.filelist.process(author, strict, indexes)

    def stop(self):
        self.stopButton.setEnabled(False)
        self.filelist.stop()

    def processCompleted(self):
        #noinspection PyUnresolvedReferences
        self.filelist.processCompleted.disconnect(self.processCompleted)
        self.processButton.show()
        self.stopButton.hide()

        self.enableLayout(self.fbuttons, True)

    def rowsChanged(self, rows):
        self.processButton.setEnabled(bool(rows))

    @classmethod
    def enableLayout(cls, layout, state):
        """
        :type layout: QLayout
        """
        for i in xrange(layout.count()):
            w = layout.itemAt(i).widget()
            if w is None:
                continue
            w.setEnabled(bool(state))

#noinspection PyUnusedLocal
def main():
    app = QApplication(sys.argv)
    i = QIcon()
    i.addFile('res/fb2-16x16.png')
    i.addFile('res/fb2-32x32.png')
    i.addFile('res/fb2-48x48.png')
    app.setWindowIcon(i)
    w = MainWindow()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
