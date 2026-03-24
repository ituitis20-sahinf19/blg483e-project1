"""
services/index.py
=================

Thread-safe shared data structures for the crawler system.

Components:
- IndexEntry: Entry in the inverted index
- QueueItem: Work item in the URL frontier
- CrawlMetrics: Real-time metrics snapshot
- VisitedSet: Thread-safe set for tracking visited URLs
- InvertedIndex: Thread-safe keyword->URL mapping
- URLFrontier: Thread-safe work queue with back pressure
- MetricsTracker: Thread-safe metrics collection
"""

import threading
import queue
import time
import json
import os
from dataclasses import dataclass, field
from typing import Optional, List, Set

from utils.locks import RWLock


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class IndexEntry:
    """
    A single entry in the inverted index.
    
    Represents a URL found for a keyword, tracking its origin and depth.
    """
    url: str
    origin_url: str    # Root seed URL from which this was discovered
    depth: int         # Depth in the crawl tree
    frequency: int = 0 # How many times keyword appeared on this page


@dataclass
class QueueItem:
    """
    A work item in the URL frontier queue.
    
    Tracks the URL to crawl, its discovery path (origin), and depth constraints.
    """
    url: str
    origin_url: str    # Root seed URL
    current_depth: int # Current position in recursion tree
    max_depth: int     # User-specified recursion limit


@dataclass
class CrawlMetrics:
    """
    Real-time metrics snapshot for dashboard and monitoring.
    
    Thread-safe snapshot of system state at a point in time.
    """
    urls_processed: int = 0        # Total URLs successfully indexed
    current_max_depth: int = 0     # Maximum depth reached so far
    queue_depth: int = 0           # Current frontier queue size
    visited_count: int = 0         # Total unique URLs discovered
    index_size: int = 0            # Total unique keywords indexed
    back_pressure_events: int = 0  # Times queue reached maxsize
    active_workers: int = 0        # Number of active worker threads
    start_time: float = field(default_factory=time.time)


# ============================================================================
# THREAD-SAFE VISITED SET
# ============================================================================

class VisitedSet:
    """
    Thread-safe set for tracking visited URLs.
    
    Purpose: Ensure no URL is crawled more than once (F.1.2 requirement).
    
    Lock Strategy: Simple exclusive lock (threading.Lock)
    Rationale: Set membership checks are O(1), lock contention is acceptable
              compared to network I/O overhead of actual crawling.
    """

    def __init__(self):
        self._visited: Set[str] = set()
        self._lock = threading.Lock()

    def add(self, url: str) -> bool:
        """
        Atomically add URL to visited set.
        
        Returns: 
            True if URL was added (not previously visited)
            False if URL was already in set
            
        Note: When False is returned, indicates potential race condition
              (another worker visited this URL between check and add).
              Caller should skip processing.
        """
        with self._lock:
            if url in self._visited:
                return False
            self._visited.add(url)
            return True

    def is_visited(self, url: str) -> bool:
        """
        Check if URL has been visited.
        
        Thread-safe read operation. Note that this is not atomic with respect to add().
        Use add() for atomic check-and-set semantics.
        """
        with self._lock:
            return url in self._visited

    def size(self) -> int:
        """Return number of visited URLs."""
        with self._lock:
            return len(self._visited)

    def clear(self) -> None:
        """Clear all visited URLs (useful for testing/reset)."""
        with self._lock:
            self._visited.clear()


# ============================================================================
# THREAD-SAFE INVERTED INDEX
# ============================================================================

class InvertedIndex:
    """
    Thread-safe inverted index mapping keywords to URLs.
    
    Purpose: Enable real-time search while indexer is active (F.2.2 requirement).
    
    Lock Strategy: Read-Write Lock (RWLock)
    Rationale: 
    - Searcher threads will frequently READ keywords concurrently
    - Indexer workers will WRITE keywords (less frequent, exclusive)
    - RWLock allows multiple concurrent readers without blocking each other
    - This prevents searchers from blocking while indexer writes
    
    Data Structure:
        keyword (str) -> [IndexEntry, IndexEntry, ...]
    
    Each IndexEntry tracks:
    - url: The page where keyword was found
    - origin_url: The seed URL's root domain
    - depth: Crawl depth where found
    - frequency: How many times keyword appeared
    """

    def __init__(self):
        self._index: dict = {}  # keyword -> [IndexEntry, ...]
        self._rwlock = RWLock()

    def add_keyword(self, keyword: str, entry: IndexEntry) -> None:
        """
        Writer: Add a keyword -> URL mapping during indexing.
        
        Acquires exclusive write lock. If the same URL already exists
        for this keyword, increments its frequency instead of duplicating.
        """
        self._rwlock.acquire_write()
        try:
            if keyword not in self._index:
                self._index[keyword] = []
            
            # Check if URL already exists for this keyword (avoid duplicates)
            for existing_entry in self._index[keyword]:
                if existing_entry.url == entry.url:
                    existing_entry.frequency += 1
                    return
            
            # New URL for this keyword
            self._index[keyword].append(entry)
        finally:
            self._rwlock.release_write()

    def search(self, keyword: str) -> List[IndexEntry]:
        """
        Reader: Retrieve all entries for a given keyword.
        
        Acquires read lock; multiple concurrent readers allowed.
        
        Returns: List of IndexEntry objects, or empty list if not found.
                 Returns a copy to prevent external modification.
        """
        self._rwlock.acquire_read()
        try:
            return self._index.get(keyword, []).copy()
        finally:
            self._rwlock.release_read()

    def search_query(self, query: str) -> List[tuple]:
        """
        Reader: Search for multiple keywords and return ranked results.
        
        This is the main search interface used by the query engine (F.2.1 requirement).
        Uses RWLock read lock to allow concurrent readers without blocking writers.
        
        Ranking Heuristic (F.2.3 requirement):
        - Primary: Number of query keywords matched on the page
          (prefer URLs with more keyword matches)
        - Secondary: Sum of keyword frequencies within the page
          (prefer URLs where keywords appear more frequently)
        
        Args:
            query: Search query string (e.g., "python web crawler")
            
        Returns:
            List of tuples: [(relevant_url, origin_url, depth), ...]
            Sorted by relevance (keyword match count, then frequency).
            Empty list if no matches.
            
        Thread Safety:
        - Acquires read lock ✓ (allows concurrent searchers + writer)
        - Does NOT block worker threads ✓
        - Safe during concurrent indexing ✓
        """
        # Import here to avoid circular dependency with crawler module
        from services.crawler import tokenize_text
        
        # Tokenize query string using same stopword filtering as indexer
        query_keywords = tokenize_text(query)
        
        if not query_keywords:
            return []  # No valid keywords in query after filtering
        
        # Build results map: url -> (match_count, freq_sum, IndexEntry)
        # This allows us to aggregate results across multiple keywords for same URL
        results_map: dict = {}
        
        # Acquire read lock: allows concurrent readers, won't block writers
        self._rwlock.acquire_read()
        try:
            # For each keyword in query, retrieve and accumulate matching entries
            for keyword in query_keywords:
                entries = self._index.get(keyword, [])
                for entry in entries:
                    if entry.url not in results_map:
                        # First keyword matching this URL
                        results_map[entry.url] = (1, entry.frequency, entry)
                    else:
                        # Additional keyword matching this URL: increment match count
                        match_count, freq_sum, first_entry = results_map[entry.url]
                        results_map[entry.url] = (
                            match_count + 1,
                            freq_sum + entry.frequency,
                            first_entry
                        )
        finally:
            self._rwlock.release_read()
        
        # Rank by: (1) keyword match count (descending), (2) frequency sum (descending)
        sorted_results = sorted(
            results_map.values(),
            key=lambda x: (-x[0], -x[1])  # Negative for descending sort
        )
        
        # Convert IndexEntry objects to result tuples (url, origin_url, depth)
        ranked_tuples = [
            (entry.url, entry.origin_url, entry.depth)
            for _, _, entry in sorted_results
        ]
        
        return ranked_tuples

    def get_all_keywords(self) -> Set[str]:
        """
        Reader: Get set of all indexed keywords.
        
        Used for stats, dumps, and query validation.
        """
        self._rwlock.acquire_read()
        try:
            return set(self._index.keys())
        finally:
            self._rwlock.release_read()

    def size(self) -> int:
        """Return number of unique keywords indexed."""
        self._rwlock.acquire_read()
        try:
            return len(self._index)
        finally:
            self._rwlock.release_read()

    def clear(self) -> None:
        """Clear all indexed keywords (useful for testing/reset)."""
        self._rwlock.acquire_write()
        try:
            self._index.clear()
        finally:
            self._rwlock.release_write()

    def save_to_file(self, filepath: str) -> None:
        """
        Save inverted index to file (JSON format).
        
        Thread-safe: Acquires write lock to prevent concurrent modifications
        during serialization.
        
        Args:
            filepath: Path to save the index data
        """
        self._rwlock.acquire_read()
        try:
            # Convert IndexEntry objects to dictionaries for JSON serialization
            serializable_index = {}
            for keyword, entries in self._index.items():
                serializable_index[keyword] = [
                    {
                        "url": entry.url,
                        "origin_url": entry.origin_url,
                        "depth": entry.depth,
                        "frequency": entry.frequency
                    }
                    for entry in entries
                ]
            
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            
            # Write to file
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(serializable_index, f, indent=2)
        finally:
            self._rwlock.release_read()

    def load_from_file(self, filepath: str) -> None:
        """
        Load inverted index from file (JSON format).
        
        Thread-safe: Acquires write lock to prevent concurrent access
        during deserialization. Clears existing index first.
        
        Args:
            filepath: Path to load the index data from
            
        Returns: True if file loaded successfully, False if file doesn't exist
        """
        if not os.path.exists(filepath):
            return False
        
        self._rwlock.acquire_write()
        try:
            self._index.clear()
            
            with open(filepath, 'r', encoding='utf-8') as f:
                serializable_index = json.load(f)
            
            # Convert dictionaries back to IndexEntry objects
            for keyword, entries_data in serializable_index.items():
                self._index[keyword] = [
                    IndexEntry(
                        url=entry_dict["url"],
                        origin_url=entry_dict["origin_url"],
                        depth=entry_dict["depth"],
                        frequency=entry_dict.get("frequency", 0)
                    )
                    for entry_dict in entries_data
                ]
            
            return True
        finally:
            self._rwlock.release_write()


# ============================================================================
# THREAD-SAFE URL FRONTIER QUEUE (Back Pressure)
# ============================================================================

class URLFrontier:
    """
    Thread-safe URL queue for work distribution with back pressure.
    
    Purpose: Distribute URLs to workers and implement back pressure
             (F.1.3 requirement).
    
    Back Pressure Strategy:
    - maxsize: Maximum queue depth (default 1000 pending URLs)
    - When full: Producers block on enqueue() -> prevents memory explosion
    - When emptied: Producers resume -> natural rate regulation
    - No explicit rejections or drops: just blocking
    
    Lock Strategy: Built-in queue.Queue (thread-safe by design).
    """

    def __init__(self, maxsize: int = 1000):
        """
        Initialize frontier queue.
        
        Args:
            maxsize: Maximum items in queue before back pressure engages.
                    When queue reaches this size, enqueue() blocks.
        """
        self._queue: queue.Queue = queue.Queue(maxsize=maxsize)
        self._maxsize = maxsize
        self._size_lock = threading.Lock()
        self._approximate_size = 0

    def enqueue(self, item: QueueItem, timeout: float = 2.0) -> bool:
        """
        Add URL to frontier queue.
        
        Args:
            item: QueueItem to enqueue (URL, origin, depth, max_depth)
            timeout: DEPRECATED - for back compat only. Now uses non-blocking
                    put_nowait() to prevent workers from blocking on full queue.
        
        Returns: 
            True if enqueued successfully
            False if queue is full (back pressure active)
        
        Back Pressure Mechanism (FIXED):
        - If queue is full: Immediately return False (NO BLOCKING)
        - Worker skips this link and moves to next URL
        - Result: Workers don't get stuck; they process other URLs
        - Queue naturally drains as other workers dequeue
        - Eventually back pressure subsides and new links get enqueued
        
        Note: Uses non-blocking put_nowait() to avoid deadlock where:
              - Worker discovers 100+ links
              - Each enqueue blocks for timeout seconds
              - Queue never drains because worker is blocked
        """
        try:
            self._queue.put_nowait(item)  # Non-blocking: fail immediately if full
            with self._size_lock:
                self._approximate_size += 1
            return True
        except queue.Full:
            # Back pressure engaged: queue is full
            return False

    def dequeue(self, timeout: float = 1.0) -> Optional[QueueItem]:
        """
        Remove and return next URL from frontier queue.
        
        Args:
            timeout: Maximum wait time. If no item available after this time,
                    returns None. Allows worker threads to check for
                    shutdown signals between items.
        
        Returns: 
            QueueItem if available
            None if timeout (no items in queue)
        """
        try:
            item = self._queue.get(block=True, timeout=timeout)
            with self._size_lock:
                self._approximate_size -= 1
            return item
        except queue.Empty:
            return None

    def depth(self) -> int:
        """
        Return approximate queue depth for metrics dashboard.
        
        Note: Approximate because queue size can change between lock release
              and return. Used for monitoring and is not meant to be exact.
        """
        with self._size_lock:
            return self._approximate_size

    def is_empty(self) -> bool:
        """Check if queue is empty (for shutdown detection)."""
        return self._queue.empty()

    def clear(self) -> None:
        """Clear all queued items (useful for testing/reset)."""
        # Extract all items
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        with self._size_lock:
            self._approximate_size = 0


# ============================================================================
# THREAD-SAFE METRICS TRACKER
# ============================================================================

class MetricsTracker:
    """
    Thread-safe metrics collector for real-time monitoring and dashboard.
    
    Purpose: Expose system state safely while crawler is running
             (system visibility requirement).
    
    Lock Strategy: Simple exclusive lock (threading.Lock)
    Rationale: Metrics are small objects, updates are atomic, 
              contention is low, dashboard reads are infrequent.
    
    Metrics Tracked:
    - urls_processed: URLs successfully crawled and indexed
    - current_max_depth: Deepest recursion reached so far
    - queue_depth: Current frontier queue size
    - visited_count: Unique URLs discovered
    - index_size: Unique keywords indexed
    - back_pressure_events: Times queue forced producer to wait
    - active_workers: Number of running worker threads
    - start_time: When crawl started (for elapsed time calculation)
    """

    def __init__(self):
        self._metrics = CrawlMetrics()
        self._lock = threading.Lock()

    def increment_urls_processed(self) -> None:
        """Called when a URL is successfully indexed."""
        with self._lock:
            self._metrics.urls_processed += 1

    def set_current_depth(self, depth: int) -> None:
        """Update maximum depth reached so far."""
        with self._lock:
            if depth > self._metrics.current_max_depth:
                self._metrics.current_max_depth = depth

    def update_queue_depth(self, depth: int) -> None:
        """Update frontier queue size."""
        with self._lock:
            self._metrics.queue_depth = depth

    def update_visited_count(self, count: int) -> None:
        """Update total unique URLs discovered."""
        with self._lock:
            self._metrics.visited_count = count

    def update_index_size(self, size: int) -> None:
        """Update total unique keywords indexed."""
        with self._lock:
            self._metrics.index_size = size

    def record_back_pressure_event(self) -> None:
        """Called when queue maxsize is reached (back pressure triggered)."""
        with self._lock:
            self._metrics.back_pressure_events += 1

    def set_active_workers(self, count: int) -> None:
        """Update number of active workers."""
        with self._lock:
            self._metrics.active_workers = count

    def get_metrics(self) -> CrawlMetrics:
        """
        Return atomic snapshot of current metrics.
        
        Safe for dashboard polling and logging.
        Returns a copy to prevent external modification of internal state.
        """
        with self._lock:
            return CrawlMetrics(
                urls_processed=self._metrics.urls_processed,
                current_max_depth=self._metrics.current_max_depth,
                queue_depth=self._metrics.queue_depth,
                visited_count=self._metrics.visited_count,
                index_size=self._metrics.index_size,
                back_pressure_events=self._metrics.back_pressure_events,
                active_workers=self._metrics.active_workers,
                start_time=self._metrics.start_time,
            )

    def get_elapsed_time(self) -> float:
        """Return elapsed time since start (in seconds)."""
        with self._lock:
            return time.time() - self._metrics.start_time

    def reset(self) -> None:
        """Reset all metrics (useful for testing/new crawl session)."""
        with self._lock:
            self._metrics = CrawlMetrics()
