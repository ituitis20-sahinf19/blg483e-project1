"""
utils/locks.py
==============

Thread-safe Read-Write Lock implementation using native Python threading.

Used by: InvertedIndex (for concurrent read-heavy search + exclusive writes)
"""

import threading


class RWLock:
    """
    A Read-Write Lock using native Python threading primitives.
    
    Concurrency Model:
    - Multiple readers can hold the lock simultaneously
    - Only one writer can hold the lock (exclusive access)
    - Writers are prioritized to prevent starvation
    
    Use Cases:
    - InvertedIndex: Multiple searchers read concurrently, indexer writes exclusively
    - Prevents searchers from blocking while indexer is writing
    """

    def __init__(self):
        self._readers = 0
        self._writers = 0
        self._writers_waiting = 0
        self._lock = threading.Lock()
        self._read_ready = threading.Condition(self._lock)
        self._write_ready = threading.Condition(self._lock)

    def acquire_read(self) -> None:
        """
        Acquire read lock. Multiple readers allowed.
        
        Waits if writers are active or waiting (writer priority prevents starvation).
        """
        self._lock.acquire()
        try:
            # Wait if writers are active or waiting (writer priority)
            while self._writers > 0 or self._writers_waiting > 0:
                self._read_ready.wait()
            self._readers += 1
        finally:
            self._lock.release()

    def release_read(self) -> None:
        """Release read lock and notify waiting writers."""
        self._lock.acquire()
        try:
            self._readers -= 1
            if self._readers == 0:
                # Last reader exiting: notify writers
                self._write_ready.notify_all()
        finally:
            self._lock.release()

    def acquire_write(self) -> None:
        """
        Acquire write lock. Exclusive access.
        
        Waits until no readers or writers hold the lock.
        """
        self._lock.acquire()
        try:
            self._writers_waiting += 1
            try:
                # Wait until no readers or writers
                while self._readers > 0 or self._writers > 0:
                    self._write_ready.wait()
            finally:
                self._writers_waiting -= 1
            self._writers += 1
        finally:
            self._lock.release()

    def release_write(self) -> None:
        """Release write lock and notify all waiting readers and writers."""
        self._lock.acquire()
        try:
            self._writers -= 1
            self._write_ready.notify_all()
            self._read_ready.notify_all()
        finally:
            self._lock.release()
