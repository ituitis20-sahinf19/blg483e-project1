"""
app.py
======

Application entry point for VibeCrawler crawler.

Initializes all system components and provides the main orchestrator:
- CrawlerCoordinator: Main interface for starting crawls and retrieving metrics
- Dashboard: Real-time metrics display in background
"""

from typing import Optional
import os

from services.index import (
    VisitedSet,
    InvertedIndex,
    URLFrontier,
    MetricsTracker,
    QueueItem,
)
from services.crawler import WorkerPool
from services.dashboard import Dashboard
from services.api_server import APIServer


class CrawlerCoordinator:
    """
    Main coordinator that orchestrates the entire crawling system.

    Purpose:
    - Initialize all thread-safe services
    - Manage worker thread lifecycle
    - Coordinate crawling operations
    - Expose metrics to dashboard

    Responsibilities:
    - Create all data structures (Visited Set, Index, Frontier, Metrics)
    - Spawn and manage worker pool
    - Handle user input (seed URL, max depth)
    - Monitor and report status
    - Support graceful shutdown

    Thread Safety:
    - All components are thread-safe
    - No coordination needed between calls (asynchronous)
    """

    def __init__(self, 
                 num_workers: int = 5, 
                 frontier_maxsize: int = 1000,
                 data_file: str = "data/storage/p.data"):
        """
        Initialize crawler system with configurable parameters.

        Args:
            num_workers: Number of concurrent worker threads (default 5)
                        Higher = more concurrent fetches, higher resource usage
                        Lower = slower crawling, lower resource usage
                        
            frontier_maxsize: Maximum frontier queue depth (default 1000)
                             Larger = more URLs pending, higher memory usage
                             Smaller = tighter back pressure, slower discovery
                             This implements back pressure (F.1.3 requirement)
            
            data_file: Path to persistent storage file for crawled data
                      (default: data/storage/p.data)
        """
        self.num_workers = num_workers
        self.frontier_maxsize = frontier_maxsize
        self.data_file = data_file

        # Initialize thread-safe components
        self.visited_set = VisitedSet()
        self.inverted_index = InvertedIndex()
        self.frontier = URLFrontier(maxsize=frontier_maxsize)
        self.metrics = MetricsTracker()

        # Worker pool (initialized but not started yet)
        self.worker_pool: Optional[WorkerPool] = None
        
        # Load persisted index data if available
        if os.path.exists(data_file):
            self.inverted_index.load_from_file(data_file)
            print(f"[OK] Loaded persisted index from {data_file}")

    def start_crawl(self, seed_url: str, max_depth: int) -> None:
        """
        Start the crawling process with a seed URL.

        This method coordinates the entire crawl initialization:
        1. Validates input (seed_url must be HTTP/HTTPS)
        2. Resets all data structures to clean state
        3. Enqueues the seed URL to the frontier
        4. Spawns and starts worker threads
        5. Returns immediately (crawling proceeds asynchronously)

        Args:
            seed_url: Starting URL (must start with "http" or "https")
            max_depth: Maximum recursion depth (k)
                      e.g., max_depth=2 means seed + links + links-of-links

        Raises:
            ValueError: If seed_url doesn't start with "http"

        Thread Safety:
        - All initialization happens before worker threads start
        - No concurrent access to shared data during setup
        - Workers only begin after frontier is seeded

        Returns immediately and asynchronously:
        - CLI remains responsive for search queries
        - User can call get_metrics(), search(), or shutdown() anytime
        """
        # STEP 1: Validate input
        if not seed_url.startswith("http"):
            raise ValueError(
                f"Invalid seed_url: must start with 'http' or 'https'. "
                f"Got: {seed_url}"
            )

        if max_depth < 0:
            raise ValueError(
                f"Invalid max_depth: must be >= 0. Got: {max_depth}"
            )

        # STEP 2: Reset all data structures to clean state
        # This ensures a fresh crawl (even if called multiple times)
        self.visited_set.clear()        # Clear visited URLs from previous crawl
        self.inverted_index.clear()     # Clear indexed keywords
        self.metrics.reset()            # Reset all counters and timestamps

        # STEP 3: Create and enqueue initial work item
        # The seed URL becomes the origin for all discovered URLs
        initial_item = QueueItem(
            url=seed_url,
            origin_url=seed_url,        # Mark as origin (depth 0)
            current_depth=0,            # Start at depth 0
            max_depth=max_depth         # Apply depth limit
        )

        # Enqueue to frontier with back pressure handling
        # Uses timeout=1.0 per Phase 4 Task 1 specification
        enqueued = self.frontier.enqueue(initial_item, timeout=1.0)
        if not enqueued:
            raise RuntimeError(
                "Failed to enqueue seed URL (frontier queue full). "
                "Try again later."
            )

        # STEP 4: Create worker pool (if not already running)
        # Guard against multiple concurrent crawls
        if self.worker_pool is not None and self.worker_pool.is_running():
            raise RuntimeError(
                "Crawl already in progress. Call shutdown() first."
            )

        # STEP 5: Create and start worker pool
        # This spawns self.num_workers threads, each calling Worker.run()
        self.worker_pool = WorkerPool(
            num_workers=self.num_workers,
            frontier=self.frontier,
            visited_set=self.visited_set,
            inverted_index=self.inverted_index,
            metrics=self.metrics,
        )

        # Start all worker threads (non-blocking)
        self.worker_pool.start()

        # Crawling now proceeds asynchronously in background threads.
        # This method returns immediately, allowing CLI to remain responsive.

    def get_metrics(self):
        """
        Get current system metrics snapshot.

        Returns: CrawlMetrics object with current system state
                 - urls_processed: URLs indexed so far
                 - queue_depth: Pending work in frontier
                 - back_pressure_events: Times queue throttled producers
                 - active_workers: Number of running workers
                 - elapsed_time: Time since crawl started
        """
        metrics = self.metrics.get_metrics()
        # Update dynamic metrics from current state
        metrics.queue_depth = self.frontier.depth()
        metrics.visited_count = self.visited_set.size()
        metrics.index_size = self.inverted_index.size()
        return metrics

    def search(self, query: str) -> list:
        """
        Execute a search query against the live index.
        
        This method demonstrates live search (F.2.2 requirement):
        - Does NOT block the worker pool
        - Uses RWLock read access (concurrent with indexing)
        - Returns immediately with current results
        
        Args:
            query: Search query string (e.g., "python web crawler")
        
        Returns:
            List of tuples: [(relevant_url, origin_url, depth), ...]
            Sorted by relevance (keyword matches, then frequency).
            Empty list if no matches or no indexed content yet.
        
        Thread Safety:
        - Acquires only read lock on index ✓
        - Does NOT block writer threads ✓
        - Safe to call from main thread while workers crawl ✓
        """
        return self.inverted_index.search_query(query)

    def print_metrics(self) -> None:
        """Print metrics to console for real-time monitoring."""
        metrics = self.get_metrics()
        elapsed = self.metrics.get_elapsed_time()
        print(f"""
        ===== CRAWLER METRICS (Elapsed: {elapsed:.1f}s) =====
        URLs Processed:       {metrics.urls_processed}
        Current Max Depth:    {metrics.current_max_depth}
        Queue Depth:          {metrics.queue_depth}
        Visited URLs:         {metrics.visited_count}
        Indexed Keywords:     {metrics.index_size}
        Back Pressure Events: {metrics.back_pressure_events}
        Active Workers:       {metrics.active_workers}
        """)

    def shutdown(self) -> None:
        """
        Gracefully shutdown all components.

        Signals worker pool to stop and waits for threads to exit.
        Saves persisted index data to storage file.
        """
        if self.worker_pool is not None:
            self.worker_pool.shutdown()
        
        # Persist index data before shutdown
        self.inverted_index.save_to_file(self.data_file)
        print(f"[OK] Saved index to {self.data_file}")

    def is_active(self) -> bool:
        """Check if crawler is currently running."""
        if self.worker_pool is None:
            return False
        return self.worker_pool.is_running()


def create_app(num_workers: int = 5, 
               frontier_maxsize: int = 1000,
               data_file: str = "data/storage/p.data") -> CrawlerCoordinator:
    """
    Factory function to create and initialize the crawler application.

    Args:
        num_workers: Number of concurrent workers (default 5)
        frontier_maxsize: Max frontier queue size (default 1000)
        data_file: Path to persistent storage file (default: data/storage/p.data)

    Returns:
        CrawlerCoordinator instance ready for use
    """
    return CrawlerCoordinator(
        num_workers=num_workers,
        frontier_maxsize=frontier_maxsize,
        data_file=data_file,
    )


if __name__ == "__main__":
    """
    Interactive CLI for VibeCrawler web crawler.
    
    Features:
    - Start crawling from a seed URL in background
    - Execute search queries while crawling continues
    - View real-time metrics
    - Graceful shutdown
    
    Thread Safety Validation:
    - Worker threads crawl in background (WorkerPool via threading)
    - Main thread handles user input (CLI)
    - Dashboard runs in background thread (non-blocking)
    - Searches use RWLock read access (don't block crawlers)
    - All data structures thread-safe
    """
    import time
    import threading
    
    print("\n" + "=" * 60)
    print("  VibeCrawler - Web Crawler & Search Engine")
    print("=" * 60 + "\n")
    
    # Create app with configurable workers
    num_workers = 5
    frontier_max = 1000
    app = create_app(num_workers=num_workers, frontier_maxsize=frontier_max)
    print(f"[OK] Initialized coordinator")
    print(f"  - Workers: {num_workers}")
    print(f"  - Frontier capacity: {frontier_max}\n")
    
    # Start background crawl with seed URL
    app.start_crawl("https://google.com", max_depth=2)
    print("[OK] Crawl started in background\n")
    
    # Start real-time metrics dashboard
    dashboard = Dashboard(app)
    dashboard.start()
    print("[OK] Real-time dashboard started (separate window)\n")
    
    # Start REST API server on localhost:3600
    api_server = APIServer(app, port=3600)
    api_server.start()
    print()
    
    # Interactive CLI loop
    print("Commands:")
    print("  search <query>  - Search the index (non-blocking)")
    print("  metrics         - Show detailed metrics")
    print("  status          - Show crawler status")
    print("  quit            - Exit\n")
    
    try:
        while True:
            try:
                user_input = input("> ").strip()
                
                if not user_input:
                    continue
                
                # Parse command
                parts = user_input.split(maxsplit=1)
                command = parts[0].lower()
                
                if command == "quit":
                    print("\nShutting down...")
                    api_server.stop()
                    dashboard.stop()
                    app.shutdown()
                    print("[OK] Shutdown complete")
                    break
                
                elif command == "search":
                    if len(parts) < 2:
                        print("Usage: search <query>")
                        continue
                    
                    query = parts[1]
                    print(f"\nSearching for: '{query}'...\n")
                    
                    # Execute search (non-blocking, uses RWLock read access)
                    results = app.search(query)
                    
                    if not results:
                        print("No results found (index may still be building)\n")
                    else:
                        print(f"Found {len(results)} results:\n")
                        for i, (url, origin, depth) in enumerate(results[:10], 1):
                            print(f"  {i}. {url}")
                            print(f"     Origin: {origin} | Depth: {depth}\n")
                        
                        if len(results) > 10:
                            print(f"  ... and {len(results) - 10} more results\n")
                
                elif command == "metrics":
                    app.print_metrics()
                
                elif command == "status":
                    is_active = app.is_active()
                    status = "ACTIVE" if is_active else "INACTIVE"
                    print(f"\nCrawler Status: {status}")
                    if is_active:
                        metrics = app.get_metrics()
                        print(f"  Visited: {metrics.visited_count} URLs")
                        print(f"  Queue Depth: {metrics.queue_depth}")
                        print(f"  Indexed: {metrics.index_size} keywords\n")
                    else:
                        print("  (No crawl in progress)\n")
                
                else:
                    print(f"Unknown command: '{command}'\n")
            
            except KeyboardInterrupt:
                print("\n\nInterrupted by user")
                api_server.stop()
                dashboard.stop()
                app.shutdown()
                break
            except Exception as e:
                print(f"Error: {e}\n")
    
    finally:
        # Ensure graceful cleanup
        api_server.stop()
        dashboard.stop()
        if app.is_active():
            app.shutdown()
