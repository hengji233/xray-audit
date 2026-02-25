from __future__ import annotations

import os
from typing import List, Optional, Tuple


class LogTailer:
    def __init__(self, path: str, encoding: str = "utf-8") -> None:
        self.path = path
        self.encoding = encoding
        self._fh = None
        self._inode: Optional[int] = None
        self._offset: int = 0

    def set_state(self, inode: Optional[int], offset: int) -> None:
        self._inode = inode
        self._offset = max(0, offset)

    def state(self) -> Tuple[Optional[int], int]:
        return self._inode, self._offset

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def _open(self) -> bool:
        if not os.path.exists(self.path):
            return False

        stat = os.stat(self.path)
        self._fh = open(self.path, "r", encoding=self.encoding, errors="replace")
        self._inode = stat.st_ino

        if stat.st_size < self._offset:
            self._offset = 0
        self._fh.seek(self._offset)
        return True

    def _ensure_open(self) -> bool:
        if self._fh is not None:
            return True
        return self._open()

    def _check_rotation_or_truncate(self) -> None:
        if not os.path.exists(self.path):
            return

        stat = os.stat(self.path)
        if self._inode is not None and stat.st_ino != self._inode:
            self.close()
            self._offset = 0
            self._open()
            return

        if stat.st_size < self._offset and self._fh is not None:
            self._fh.seek(0)
            self._offset = 0

    def read_new_lines(self, max_lines: int = 4096) -> List[str]:
        if not self._ensure_open():
            return []

        out: List[str] = []
        while len(out) < max_lines:
            line = self._fh.readline()
            if not line:
                break
            self._offset = self._fh.tell()
            out.append(line)

        if not out:
            self._check_rotation_or_truncate()

        return out
