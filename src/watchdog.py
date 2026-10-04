import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

HUNG_EXIT_CODE = 3


class Watchdog:

    def __init__(self, limit_seconds, on_hang=None, clock=time.monotonic):
        self.limit_seconds = limit_seconds
        self.clock = clock
        self.on_hang = on_hang or self._abort
        self._last_progress = clock()
        self._lock = threading.Lock()
        self._thread = None
        self._stop = threading.Event()

    def progress(self):
        with self._lock:
            self._last_progress = self.clock()

    def seconds_since_progress(self):
        with self._lock:
            return self.clock() - self._last_progress

    def has_stalled(self):
        return self.seconds_since_progress() > self.limit_seconds

    def check(self):
        if not self.has_stalled():
            return False
        logger.error("No progress for %.0f seconds, limit is %s. Exiting so the service restarts.",
                     self.seconds_since_progress(), self.limit_seconds)
        self.on_hang()
        return True

    def start(self, interval_seconds=10):
        self._thread = threading.Thread(target=self._watch, args=(interval_seconds,), daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _watch(self, interval_seconds):
        while not self._stop.wait(interval_seconds):
            if self.check():
                return

    @staticmethod
    def _abort():
        logging.shutdown()
        os._exit(HUNG_EXIT_CODE)
