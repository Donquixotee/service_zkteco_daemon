import json
import logging
import os
import tempfile

logger = logging.getLogger(__name__)


class CursorStore:

    def __init__(self, path):
        self.path = path
        self._cursors = self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, 'r', encoding='utf-8') as handle:
                return json.load(handle)
        except (ValueError, OSError) as error:
            logger.warning("Could not read cursor file %s, starting empty: %s", self.path, error)
            return {}

    def last_timestamp(self, serial_number):
        return self._cursors.get(serial_number)

    def advance(self, serial_number, timestamp):
        if not timestamp:
            return
        current = self._cursors.get(serial_number)
        if current and timestamp <= current:
            return
        self._cursors[serial_number] = timestamp
        self._persist()

    def _persist(self):
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        handle, temporary_path = tempfile.mkstemp(dir=directory, suffix='.tmp')
        try:
            with os.fdopen(handle, 'w', encoding='utf-8') as stream:
                json.dump(self._cursors, stream, indent=2, sort_keys=True)
            os.replace(temporary_path, self.path)
        except Exception:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)
            raise
