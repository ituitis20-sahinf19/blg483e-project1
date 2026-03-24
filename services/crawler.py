"""
services/crawler.py
===================

Web crawler worker pool and fetching/parsing infrastructure.

Components:
- HTMLLinkExtractor: Native html.parser for link and text extraction
- tokenize_text(): Keyword extraction with stopword filtering
- fetch_page(): Native urllib page fetching
- Worker: Individual crawler worker thread (main crawling logic)
- WorkerPool: Orchestrates multiple worker threads
"""

import threading
import queue
import time
import re
import urllib.request
import urllib.parse
import urllib.error
from html.parser import HTMLParser
from typing import Optional, List, Set
from urllib.parse import urljoin

from services.index import (
    IndexEntry,
    QueueItem,
    VisitedSet,
    InvertedIndex,
    URLFrontier,
    MetricsTracker,
)


# ============================================================================
# HTML PARSING & LINK EXTRACTION (Native html.parser)
# ============================================================================

class HTMLLinkExtractor(HTMLParser):
    """
    Native HTML parser to extract links and text content.
    
    Uses html.parser (standard library, NO external dependencies).
    
    Purpose:
    - Extract all <a href="..."> links from HTML
    - Extract text content and title for keyword extraction
    - Handle relative URLs and normalize them to absolute
    
    Design:
    - Inherits from HTMLParser (stdlib)
    - Tracks <title>, <script>, <style> tags to skip irrelevant content
    - Uses urljoin() to normalize relative URLs
    - Filters out non-HTTP URLs (mailto, #anchors, ftp, etc.)
    """

    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.links: Set[str] = set()
        self.text_content: List[str] = []
        self.title: str = ""
        self._in_title = False
        self._in_script = False
        self._in_style = False

    def handle_starttag(self, tag: str, attrs: List[tuple]) -> None:
        """Process start tags."""
        if tag == "title":
            self._in_title = True
        elif tag == "script":
            self._in_script = True
        elif tag == "style":
            self._in_style = True
        elif tag == "a":
            # Extract href attribute
            for attr_name, attr_value in attrs:
                if attr_name == "href" and attr_value:
                    # Normalize relative URLs to absolute
                    try:
                        absolute_url = urljoin(self.base_url, attr_value)
                        # Only include http/https URLs; skip mailto, #anchors, etc.
                        if absolute_url.startswith("http"):
                            self.links.add(absolute_url)
                    except Exception:
                        pass  # Silently skip malformed URLs

    def handle_endtag(self, tag: str) -> None:
        """Process end tags."""
        if tag == "title":
            self._in_title = False
        elif tag == "script":
            self._in_script = False
        elif tag == "style":
            self._in_style = False

    def handle_data(self, data: str) -> None:
        """Extract text content."""
        # Skip text in script/style tags
        if self._in_script or self._in_style:
            return

        cleaned = data.strip()
        if cleaned:
            if self._in_title:
                self.title = cleaned
            self.text_content.append(cleaned)

    def get_links(self) -> Set[str]:
        """Return extracted links as absolute URLs."""
        return self.links

    def get_text(self) -> str:
        """Return full text content."""
        return " ".join(self.text_content)

    def get_title(self) -> str:
        """Return page title."""
        return self.title


# ============================================================================
# KEYWORD EXTRACTION
# ============================================================================

def tokenize_text(text: str) -> dict:
    """
    Extract keywords from text with frequency counts.

    Strategy:
    - Convert to lowercase
    - Split on whitespace and punctuation using regex
    - Filter short words (< 3 chars) to reduce noise
    - Remove common stopwords to avoid indexing noise
    - Count occurrences of each keyword

    Args:
        text: Raw text content from page

    Returns:
        Dict: {keyword: frequency, ...}
        Example: {"python": 3, "crawler": 2, "web": 5}

    Example:
        input:  "The quick brown fox jumps over the lazy dog. The quick fox"
        output: {"quick": 2, "brown": 1, "fox": 2, "jumps": 1, "lazy": 1, "dog": 1}
    """
    # Common English stopwords to filter
    stopwords = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
        "have", "has", "had", "do", "does", "did", "will", "would", "should",
        "could", "can", "may", "might", "must", "shall", "as", "if", "than",
        "that", "this", "these", "those", "i", "you", "he", "she", "it", "we",
        "they", "what", "which", "who", "where", "when", "why", "how"
    }

    # Simple tokenization: split on non-alphanumeric, lowercase
    tokens = re.findall(r'\b\w+\b', text.lower())

    # Count frequencies: filter stopwords + short words
    keyword_freq = {}
    for token in tokens:
        if len(token) >= 3 and token not in stopwords:
            keyword_freq[token] = keyword_freq.get(token, 0) + 1

    return keyword_freq


# ============================================================================
# PAGE FETCHING (Native urllib)
# ============================================================================

def fetch_page(url: str, timeout: int = 10) -> Optional[str]:
    """
    Fetch a single page using native urllib.

    Args:
        url: URL to fetch
        timeout: Connection timeout in seconds

    Returns:
        HTML content (str) if successful, None if network error

    Error Handling:
    - HTTP errors (404, 403, 500, etc.): Returns None
    - Network errors (DNS, timeout, refused): Returns None
    - Malformed URLs: Returns None
    - Unicode decode errors: Falls back to latin-1
    
    Note:
    - Uses urllib.request (native Python library)
    - Adds User-Agent to avoid being blocked by some sites
    - Handles connection errors gracefully
    - Respects timeout to prevent hanging on slow servers
    """
    try:
        # Set User-Agent to avoid 403 from some sites
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/91.0.4472.124 Safari/537.36'
        }
        req = urllib.request.Request(url, headers=headers)

        # Fetch with timeout
        with urllib.request.urlopen(req, timeout=timeout) as response:
            # Read and decode HTML
            html_bytes = response.read()
            # Try UTF-8 first, fallback to latin-1
            try:
                html_text = html_bytes.decode('utf-8')
            except UnicodeDecodeError:
                html_text = html_bytes.decode('latin-1', errors='ignore')
            return html_text

    except urllib.error.HTTPError as e:
        # HTTP errors (404, 403, 500, etc.)
        return None
    except urllib.error.URLError as e:
        # Network errors (DNS failure, connection refused, etc.)
        return None
    except Exception as e:
        # Any other error (malformed URL, timeout, etc.)
        return None


# ============================================================================
# WORKER THREAD
# ============================================================================

class Worker(threading.Thread):
    """
    Individual crawler worker thread.

    Purpose: Fetch URLs, extract links/keywords, update shared data structures.

    Responsibility:
    - Dequeue item from URLFrontier
    - Check VisitedSet (prevent re-crawl)
    - Fetch page via native urllib
    - Extract links and keywords via native html.parser
    - Update VisitedSet, Frontier, InvertedIndex, Metrics
    - Handle back pressure gracefully
    - Support graceful shutdown

    Thread Safety:
    - All shared data accessed through thread-safe wrappers
    - No direct synchronization needed in this class
    - All collaborators (frontier, visited_set, etc.) are thread-safe
    """

    def __init__(self,
                 worker_id: int,
                 frontier: URLFrontier,
                 visited_set: VisitedSet,
                 inverted_index: InvertedIndex,
                 metrics: MetricsTracker):
        super().__init__(daemon=False)
        self.worker_id = worker_id
        self.frontier = frontier
        self.visited_set = visited_set
        self.inverted_index = inverted_index
        self.metrics = metrics
        self._shutdown_event = threading.Event()
        self.name = f"Worker-{worker_id}"

    def run(self) -> None:
        """
        Main worker loop. Implements core crawling logic:
        1. Dequeue item from URLFrontier
        2. Check VisitedSet (prevent re-crawl)
        3. Fetch page via native urllib
        4. Extract links and keywords via native html.parser
        5. Add new links to frontier (respecting back pressure)
        6. Index keywords in InvertedIndex
        7. Update metrics
        8. Repeat until shutdown signal

        Back Pressure Handling:
        - If frontier.enqueue() times out (queue full), records event
        - Graceful shutdown: Check _shutdown_event between iterations
        
        Thread Safety:
        - All shared data accessed through thread-safe wrappers
        - VisitedSet.add() is atomic (prevents double-crawl)
        - InvertedIndex writes protected by RWLock
        - URLFrontier enqueue/dequeue are thread-safe
        - Metrics updates are atomic
        """
        while not self._shutdown_event.is_set():
            # STEP 1: Dequeue next URL from frontier
            item = self.frontier.dequeue(timeout=1.0)
            
            if item is None:
                # Timeout on dequeue: check for shutdown and continue
                continue
            
            # STEP 2: Check if already visited (pre-fetch optimization)
            if self.visited_set.is_visited(item.url):
                # Already visited by another worker, skip
                continue
            
            # STEP 3: Fetch HTML using native urllib
            html = None
            try:
                html = fetch_page(item.url, timeout=10)
            except Exception as e:
                # Unexpected error during fetch (should be caught by fetch_page)
                continue
            
            if html is None:
                # Network error or HTTP error: skip gracefully
                continue
            
            # STEP 4: Mark as visited (atomic - only first worker succeeds)
            was_added = self.visited_set.add(item.url)
            if not was_added:
                # Race condition: another worker visited this URL between
                # our check and our add. Skip to avoid indexed duplicates.
                continue
            
            # Update metrics: URLs successfully processed
            self.metrics.increment_urls_processed()
            self.metrics.set_current_depth(item.current_depth)
            
            # STEP 5: Parse HTML using native html.parser
            links = set()
            text = ""
            page_title = ""
            
            try:
                parser = HTMLLinkExtractor(base_url=item.url)
                parser.feed(html)
                links = parser.get_links()
                text = parser.get_text()
                page_title = parser.get_title()
            except Exception as e:
                # HTML parsing error: skip this page gracefully
                # This is expected for malformed HTML
                continue
            
            # STEP 6: Extract keywords from page content
            full_content = f"{page_title} {text}"
            keyword_frequencies = tokenize_text(full_content)  # Now returns dict: {keyword: freq, ...}
            
            # STEP 7: Index all keywords with their frequencies
            for keyword, freq in keyword_frequencies.items():
                entry = IndexEntry(
                    url=item.url,
                    origin_url=item.origin_url,
                    depth=item.current_depth,
                    frequency=freq,  # Actual occurrence count on this page
                )
                self.inverted_index.add_keyword(keyword, entry)
            
            # STEP 8: Enqueue discovered links (respecting depth limit + back pressure)
            links_discovered = 0
            links_enqueued = 0
            back_pressure_triggered = False
            
            for link in links:
                # Skip links already visited
                if self.visited_set.is_visited(link):
                    continue
                
                links_discovered += 1
                
                # Respect depth limit
                if item.current_depth + 1 <= item.max_depth:
                    new_item = QueueItem(
                        url=link,
                        origin_url=item.origin_url,
                        current_depth=item.current_depth + 1,
                        max_depth=item.max_depth,
                    )
                    
                    # Try to enqueue (non-blocking - if full, skip link)
                    try:
                        success = self.frontier.enqueue(new_item, timeout=0)
                        if success:
                            links_enqueued += 1
                        else:
                            # Queue full: skip this link (back pressure)
                            back_pressure_triggered = True
                            self.metrics.record_back_pressure_event()
                    except queue.Full:
                        # Queue full (shouldn't happen with timeout, but handle it)
                        back_pressure_triggered = True
                        self.metrics.record_back_pressure_event()
            
            # STEP 9: Update metrics for dashboard
            self.metrics.update_queue_depth(self.frontier.depth())
            self.metrics.update_visited_count(self.visited_set.size())
            self.metrics.update_index_size(self.inverted_index.size())

    def shutdown(self) -> None:
        """Signal worker to gracefully exit."""
        self._shutdown_event.set()


# ============================================================================
# WORKER POOL MANAGER
# ============================================================================

class WorkerPool:
    """
    Manages a pool of crawler worker threads.

    Purpose:
    - Create and manage multiple worker threads
    - Start/stop workers
    - Monitor worker health (if needed)

    Responsibilities:
    - Spawn N worker threads at initialization
    - Provide start() to launch all workers
    - Provide shutdown() for graceful termination
    - Track worker lifecycle

    Thread Safety:
    - Uses threading primitives for coordination
    - Delegates actual work to thread-safe components (frontier, index, etc.)
    """

    def __init__(self,
                 num_workers: int,
                 frontier: URLFrontier,
                 visited_set: VisitedSet,
                 inverted_index: InvertedIndex,
                 metrics: MetricsTracker):
        """
        Initialize worker pool.

        Args:
            num_workers: Number of concurrent worker threads
            frontier: URLFrontier for work distribution
            visited_set: VisitedSet for duplicate prevention
            inverted_index: InvertedIndex for keyword indexing
            metrics: MetricsTracker for monitoring
        """
        self.num_workers = num_workers
        self.frontier = frontier
        self.visited_set = visited_set
        self.inverted_index = inverted_index
        self.metrics = metrics
        self.workers: List[Worker] = []

    def start(self) -> None:
        """
        Create and start all worker threads.

        Creates num_workers threads and marks them as daemon=False
        so they participate in graceful shutdown.
        """
        for i in range(self.num_workers):
            worker = Worker(
                worker_id=i,
                frontier=self.frontier,
                visited_set=self.visited_set,
                inverted_index=self.inverted_index,
                metrics=self.metrics,
            )
            self.workers.append(worker)
            worker.start()
        
        self.metrics.set_active_workers(self.num_workers)

    def shutdown(self) -> None:
        """
        Signal all workers to shutdown and wait for them to exit.

        Sends shutdown signal to each worker and joins all threads.
        """
        for worker in self.workers:
            worker.shutdown()

        for worker in self.workers:
            worker.join(timeout=5.0)  # Wait up to 5 seconds per worker

        self.metrics.set_active_workers(0)

    def is_running(self) -> bool:
        """Check if any workers are still alive."""
        return any(worker.is_alive() for worker in self.workers)
