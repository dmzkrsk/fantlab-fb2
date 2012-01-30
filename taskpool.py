# coding=utf-8
from PyQt4.QtCore import QThread, pyqtSignal, QObject
import sys
import Queue

class Task(QObject):
    def __init__(self):
        QObject.__init__(self)
        self._e = None
        self._r = None

    def setError(self, error):
        self._e = error
        self._r = None

    def setResult(self, result):
        self._e = None
        self._r = result

    def getResult(self):
        if self._e:
            raise self._e[1]
        return self._r

class Worker(QThread):
    taskDone = pyqtSignal(Task, object)
    taskStart = pyqtSignal(Task)

    def __init__(self, q):
        QThread.__init__(self)
        self.queue = q
        self._finished = False

    def finish(self):
        self._finished = True

    def run(self):
        while True:
            _g = self.queue.get()

            if self._finished or _g is None:
                self.queue.put(_g)
                break

            task, callback = _g

            #noinspection PyUnresolvedReferences
            self.taskStart.emit(task)
            try:
                task.setResult(task())
            except Exception:
                task.setError(sys.exc_info())
            #noinspection PyUnresolvedReferences
            self.taskDone.emit(task, callback)

class TaskPool(QObject):
    finished = pyqtSignal()

    def __init__(self, size, start_callback):
        QObject.__init__(self)

        self._pool = []
        self._queue = Queue.Queue()
        self._jobs = []
        self._start_callback = start_callback
        self._finishedWorkers = 0
        self._size = size

        for _ in xrange(size):
            t = Worker(self._queue)
            self._pool.append(t)
            #noinspection PyUnresolvedReferences
            t.taskDone.connect(self._done)
            #noinspection PyUnresolvedReferences
            t.taskStart.connect(self._start)
            t.finished.connect(self._finished)
            t.start()

    def put(self, task, callback=None):
        self._jobs.append(id(task))
        self._queue.put((task, callback))

    def _finished(self):
        self._finishedWorkers += 1
        if self._finishedWorkers == self._size:
            #noinspection PyUnresolvedReferences
            self.finished.emit()

    def finish(self):
        # Кладем в очередь пустой элемент, чтобы разблокировать .get в треде
        self._queue.put(None)

        for t in self._pool:
            t.finish()

    def _start(self, task):
        self._start_callback(task)

    def _done(self, task, callback):
        self._jobs.remove(id(task))
        if callback:
            callback(task)

    def tasksLeft(self):
        while True:
            try:
                _g = self._queue.get_nowait()
                if _g is None:
                    continue

                yield _g[0]
            except Queue.Empty:
                break
