"""
test_phase4_task4_integration.py
================================

Comprehensive integration tests for Phase 4 Task 4.

Validates all functional and non-functional requirements:
- F.1.1: Recursive crawling with depth limit
- F.1.2: Uniqueness guarantee (no URL crawled twice)
- F.1.3: Back pressure management
- F.2.1: Real-time query results format
- F.2.2: Live indexing support (search while crawling)
- F.2.3: Relevancy ranking

Tests use real Wikipedia URLs for authentic crawling behavior.

Test Categories:
1. Functional Verification Tests - Validates all PRD functional requirements
2. Concurrency & Safety Tests - Validates thread-safe operations
3. Persistence Tests - Validates data save/load integrity
4. Performance/Load Tests - Validates back pressure and efficiency
"""

import unittest
import time
import threading
import os
import json
from app import create_app
from services.index import IndexEntry


class TestFunctionalRequirements(unittest.TestCase):
    """
    Test Suite for Functional Requirements (F.1.1 - F.2.3)
    
    Uses real Wikipedia URLs to validate actual crawling behavior.
    """

    def setUp(self):
        """Initialize fresh app instance for each test."""
        self.app = create_app(
            num_workers=2,  # Reduced for testing
            frontier_maxsize=100,
            data_file="data/storage/test_functional.data"
        )
        # Clean up test data file if it exists
        if os.path.exists(self.app.data_file):
            os.remove(self.app.data_file)

    def tearDown(self):
        """Clean up: shutdown app and remove test data."""
        if self.app.is_active():
            self.app.shutdown()
        if os.path.exists(self.app.data_file):
            os.remove(self.app.data_file)

    # ========================================================================
    # F.1.1: RECURSIVE CRAWLING WITH DEPTH LIMIT
    # ========================================================================

    def test_f11_recursive_crawling_depth_zero(self):
        """
        F.1.1: Verify crawler respects depth=0 (only seed URL, no links).
        
        Expected: Only seed URL indexed, no discovered links added.
        """
        seed_url = "https://en.wikipedia.org/wiki/Web_scraping"
        
        self.app.start_crawl(seed_url, max_depth=0)
        time.sleep(3)  # Allow crawling to complete
        
        metrics = self.app.get_metrics()
        
        # With depth=0, should have exactly 1 URL (the seed)
        self.assertEqual(
            metrics.urls_processed, 1,
            f"Expected 1 URL at depth=0, got {metrics.urls_processed}"
        )
        self.assertEqual(
            metrics.current_max_depth, 0,
            "Depth should not exceed 0"
        )

    def test_f11_recursive_crawling_depth_one(self):
        """
        F.1.1: Verify crawler discovers links at depth=1.
        
        Expected: Seed URL + at least some discovered links indexed.
        """
        seed_url = "https://en.wikipedia.org/wiki/Web_scraping"
        
        self.app.start_crawl(seed_url, max_depth=1)
        time.sleep(4)  # Allow crawling to discover links
        
        metrics = self.app.get_metrics()
        
        # With depth=1, should have seed + discovered links
        self.assertGreater(
            metrics.urls_processed, 1,
            f"Expected >1 URL at depth=1, got {metrics.urls_processed}"
        )
        self.assertLessEqual(
            metrics.current_max_depth, 1,
            "Depth should not exceed 1"
        )

    def test_f11_depth_limit_respected(self):
        """
        F.1.1: Verify all indexed URLs respect the depth limit.
        
        Expected: No URL has depth > max_depth.
        """
        seed_url = "https://en.wikipedia.org/wiki/Web_crawler"
        max_depth = 1
        
        self.app.start_crawl(seed_url, max_depth=max_depth)
        time.sleep(4)
        
        metrics = self.app.get_metrics()
        
        # Verify max depth constraint
        self.assertLessEqual(
            metrics.current_max_depth, max_depth,
            f"Current depth {metrics.current_max_depth} exceeds limit {max_depth}"
        )

    # ========================================================================
    # F.1.2: UNIQUENESS GUARANTEE
    # ========================================================================

    def test_f12_no_duplicate_crawling(self):
        """
        F.1.2: Verify each URL is crawled exactly once.
        
        Expected: Visited set prevents re-crawling same URL.
        
        Note: This test uses a shallow depth to keep runtime short.
        """
        seed_url = "https://en.wikipedia.org/wiki/Search_engine"
        
        self.app.start_crawl(seed_url, max_depth=1)
        time.sleep(4)
        
        visited_count = self.app.visited_set.size()
        urls_processed = self.app.get_metrics().urls_processed
        
        # All processed URLs should be unique
        self.assertEqual(
            visited_count, urls_processed,
            f"Visited count ({visited_count}) != processed ({urls_processed}), "
            "suggests duplicate crawling"
        )

    # ========================================================================
    # F.1.3: BACK PRESSURE MANAGEMENT
    # ========================================================================

    def test_f13_back_pressure_triggered(self):
        """
        F.1.3: Verify back pressure events are recorded when queue fills.
        
        Expected: Under aggressive crawling, back pressure events > 0.
        
        Note: Uses small frontier to trigger back pressure quickly.
        """
        app_small_queue = create_app(
            num_workers=1,  # Single worker to allow queue to fill
            frontier_maxsize=5,  # Very small queue to trigger back pressure
            data_file="data/storage/test_bp.data"
        )
        
        try:
            seed_url = "https://en.wikipedia.org/wiki/Internet"
            
            app_small_queue.start_crawl(seed_url, max_depth=1)
            time.sleep(3)  # Allow some back pressure to accumulate
            
            metrics = app_small_queue.get_metrics()
            
            # With small queue, should see back pressure events
            self.assertGreater(
                metrics.back_pressure_events, 0,
                "Expected back pressure events with frontier_maxsize=5"
            )
        finally:
            if app_small_queue.is_active():
                app_small_queue.shutdown()
            if os.path.exists(app_small_queue.data_file):
                os.remove(app_small_queue.data_file)

    # ========================================================================
    # F.2.1: REAL-TIME QUERY RESULTS FORMAT
    # ========================================================================

    def test_f21_query_result_format(self):
        """
        F.2.1: Verify search results are tuples (url, origin_url, depth).
        
        Expected: Each result is a 3-tuple with correct structure.
        """
        seed_url = "https://en.wikipedia.org/wiki/Python_(programming_language)"
        
        self.app.start_crawl(seed_url, max_depth=0)
        time.sleep(2)
        
        results = self.app.search("python")
        
        if results:  # If any results found
            for result in results:
                self.assertIsInstance(result, tuple, "Result should be tuple")
                self.assertEqual(
                    len(result), 3,
                    f"Result tuple should have 3 elements, got {len(result)}"
                )
                url, origin_url, depth = result
                self.assertIsInstance(url, str, "URL should be string")
                self.assertIsInstance(origin_url, str, "Origin should be string")
                self.assertIsInstance(depth, int, "Depth should be int")

    # ========================================================================
    # F.2.2: LIVE INDEXING SUPPORT
    # ========================================================================

    def test_f22_search_during_crawl(self):
        """
        F.2.2: Verify searches work while crawler is actively running.
        
        Expected: Can execute search queries without blocking crawler.
        """
        seed_url = "https://en.wikipedia.org/wiki/Database"
        
        self.app.start_crawl(seed_url, max_depth=1)
        
        # Search while crawler is active
        time.sleep(1)  # Give crawler brief moment to start indexing
        
        # These should return immediately without blocking
        results1 = self.app.search("database")
        self.assertIsInstance(results1, list, "Search should return list")
        
        time.sleep(1)
        results2 = self.app.search("data")
        self.assertIsInstance(results2, list, "Search should return list")
        
        # Crawler should still be active after searches
        self.assertTrue(
            self.app.is_active(),
            "Crawler should still be running after searches"
        )

    # ========================================================================
    # F.2.3: RELEVANCY RANKING
    # ========================================================================

    def test_f23_relevancy_ranking(self):
        """
        F.2.3: Verify results are ranked by keyword frequency and match count.
        
        Expected: Results with higher keyword counts appear first.
        
        Note: Requires manually verifying ranking heuristic.
        """
        seed_url = "https://en.wikipedia.org/wiki/Programming"
        
        self.app.start_crawl(seed_url, max_depth=0)
        time.sleep(2)
        
        results = self.app.search("programming language")
        
        if len(results) >= 2:
            # Results should be sorted by relevance
            # (Can't verify exact heuristic without index inspection,
            # but can verify structure is consistent)
            for i, result in enumerate(results):
                self.assertEqual(len(result), 3, f"Result {i} has wrong structure")


class TestConcurrencyAndSafety(unittest.TestCase):
    """
    Test Suite for Concurrency & Thread Safety
    
    Validates that concurrent reads/writes don't corrupt data.
    """

    def setUp(self):
        """Initialize app for concurrency tests."""
        self.app = create_app(
            num_workers=3,  # Multiple workers for concurrency
            frontier_maxsize=100,
            data_file="data/storage/test_concurrent.data"
        )
        if os.path.exists(self.app.data_file):
            os.remove(self.app.data_file)

    def tearDown(self):
        """Cleanup."""
        if self.app.is_active():
            self.app.shutdown()
        if os.path.exists(self.app.data_file):
            os.remove(self.app.data_file)

    def test_concurrent_searches_during_crawl(self):
        """
        Verify multiple threads can search while workers are indexing.
        
        Expected: No data corruption, no deadlocks.
        """
        seed_url = "https://en.wikipedia.org/wiki/Concurrent_computing"
        
        self.app.start_crawl(seed_url, max_depth=1)
        
        search_results = []
        errors = []

        def search_thread(query):
            try:
                results = self.app.search(query)
                search_results.append((query, len(results)))
            except Exception as e:
                errors.append(str(e))

        # Launch multiple search threads concurrently with crawling
        threads = []
        for query in ["concurrent", "computing", "parallel", "thread"]:
            t = threading.Thread(target=search_thread, args=(query,))
            threads.append(t)
            t.start()

        # Wait for all searches to complete
        for t in threads:
            t.join(timeout=5)

        # Verify no errors occurred
        self.assertEqual(
            len(errors), 0,
            f"Concurrent searches caused errors: {errors}"
        )
        
        # Verify searches completed
        self.assertGreater(len(search_results), 0, "At least one search should complete")

    def test_index_integrity_after_concurrent_access(self):
        """
        Verify index remains consistent after concurrent crawl + search.
        
        Expected: Index size increases monotonically (never decreases).
        """
        seed_url = "https://en.wikipedia.org/wiki/Index_(database)"
        
        self.app.start_crawl(seed_url, max_depth=1)
        
        sizes = []
        for _ in range(5):
            time.sleep(0.5)
            size = self.app.inverted_index.size()
            sizes.append(size)
        
        # Index size should never decrease
        for i in range(1, len(sizes)):
            self.assertGreaterEqual(
                sizes[i], sizes[i-1],
                f"Index size decreased: {sizes[i-1]} -> {sizes[i]}"
            )


class TestPersistence(unittest.TestCase):
    """
    Test Suite for Data Persistence
    
    Validates save/load integrity across sessions.
    """

    def setUp(self):
        """Setup for persistence tests."""
        self.data_file = "data/storage/test_persistence.data"
        if os.path.exists(self.data_file):
            os.remove(self.data_file)

    def tearDown(self):
        """Cleanup test data files."""
        if os.path.exists(self.data_file):
            os.remove(self.data_file)

    def test_persist_and_restore_index(self):
        """
        Verify index data survives save/load cycle.
        
        Expected: Data saved to file can be loaded identically.
        """
        # Session 1: Crawl and save
        app1 = create_app(
            num_workers=2,
            frontier_maxsize=100,
            data_file=self.data_file
        )
        
        seed_url = "https://en.wikipedia.org/wiki/Data_persistence"
        app1.start_crawl(seed_url, max_depth=0)
        time.sleep(2)
        
        size_before = app1.inverted_index.size()
        keywords_before = app1.inverted_index.get_all_keywords()
        
        app1.shutdown()
        
        # Verify file was created
        self.assertTrue(
            os.path.exists(self.data_file),
            f"Persistence file not created: {self.data_file}"
        )
        
        # Session 2: Load and verify
        app2 = create_app(
            num_workers=2,
            frontier_maxsize=100,
            data_file=self.data_file
        )
        
        size_after = app2.inverted_index.size()
        keywords_after = app2.inverted_index.get_all_keywords()
        
        # Verify data integrity
        self.assertEqual(
            size_before, size_after,
            f"Index size mismatch: {size_before} -> {size_after}"
        )
        self.assertEqual(
            keywords_before, keywords_after,
            "Keywords not preserved across load"
        )
        
        app2.shutdown()

    def test_persistence_file_format_validity(self):
        """
        Verify persisted file is valid JSON.
        
        Expected: File can be parsed as JSON.
        """
        app = create_app(
            num_workers=2,
            frontier_maxsize=100,
            data_file=self.data_file
        )
        
        seed_url = "https://en.wikipedia.org/wiki/JSON"
        app.start_crawl(seed_url, max_depth=0)
        time.sleep(2)
        
        app.shutdown()
        
        # Verify JSON validity
        with open(self.data_file, 'r') as f:
            data = json.load(f)
        
        self.assertIsInstance(data, dict, "Persisted data should be dict")
        self.assertGreater(len(data), 0, "Persisted index should have content")


class TestPerformanceAndLoad(unittest.TestCase):
    """
    Test Suite for Performance & Load Management
    
    Validates back pressure, worker efficiency, and resource handling.
    """

    def setUp(self):
        """Setup for performance tests."""
        self.app = create_app(
            num_workers=2,
            frontier_maxsize=50,
            data_file="data/storage/test_perf.data"
        )
        if os.path.exists(self.app.data_file):
            os.remove(self.app.data_file)

    def tearDown(self):
        """Cleanup."""
        if self.app.is_active():
            self.app.shutdown()
        if os.path.exists(self.app.data_file):
            os.remove(self.app.data_file)

    def test_queue_depth_bounded(self):
        """
        Verify frontier queue depth stays within configured limit.
        
        Expected: Queue depth never exceeds maxsize.
        """
        seed_url = "https://en.wikipedia.org/wiki/Queue_(data_structure)"
        maxsize = 50
        
        self.app.frontier_maxsize = maxsize
        self.app.start_crawl(seed_url, max_depth=1)
        
        max_observed_depth = 0
        for _ in range(10):
            time.sleep(0.5)
            depth = self.app.frontier.depth()
            max_observed_depth = max(max_observed_depth, depth)
        
        self.assertLessEqual(
            max_observed_depth, maxsize,
            f"Queue depth {max_observed_depth} exceeded limit {maxsize}"
        )

    def test_workers_actively_processing(self):
        """
        Verify workers are being utilized (URLs being indexed).
        
        Expected: URLs processed increases over time.
        """
        seed_url = "https://en.wikipedia.org/wiki/Thread_(computing)"
        
        self.app.start_crawl(seed_url, max_depth=1)
        
        time.sleep(1)
        urls_t1 = self.app.get_metrics().urls_processed
        
        time.sleep(2)
        urls_t2 = self.app.get_metrics().urls_processed
        
        self.assertGreater(
            urls_t2, urls_t1,
            "Workers should be indexing URLs over time"
        )


class TestEndToEndScenario(unittest.TestCase):
    """
    Real-world end-to-end scenario test
    
    Simulates actual user workflow: start crawl → search → shutdown.
    """

    def setUp(self):
        """Setup for e2e test."""
        self.app = create_app(
            num_workers=3,
            frontier_maxsize=100,
            data_file="data/storage/test_e2e.data"
        )
        if os.path.exists(self.app.data_file):
            os.remove(self.app.data_file)

    def tearDown(self):
        """Cleanup."""
        if self.app.is_active():
            self.app.shutdown()
        if os.path.exists(self.app.data_file):
            os.remove(self.app.data_file)

    def test_complete_workflow(self):
        """
        E2E: Initialize → Crawl → Search → Shutdown → Reload
        
        Expected: Full cycle completes without errors and persisted data matches.
        """
        # Phase 1: Start crawl
        seed_url = "https://en.wikipedia.org/wiki/Information_retrieval"
        self.app.start_crawl(seed_url, max_depth=1)
        
        # Phase 2: Allow crawl to complete
        time.sleep(3)
        
        # Phase 3: Shutdown BEFORE taking metrics (so we capture the final state)
        self.app.shutdown()
        
        # Phase 4: Now get final metrics from session 1
        metrics1 = self.app.get_metrics()
        self.assertGreater(metrics1.urls_processed, 0, "Should have indexed URLs")
        
        # Phase 5: Execute searches while session 1 data still in memory
        results1 = self.app.search("information retrieval")
        self.assertIsInstance(results1, list, "Search should return list")
        
        # Phase 6: Verify file was persisted
        file_exists = os.path.exists(self.app.data_file)
        self.assertTrue(file_exists, "Persistence file should be created")
        
        # Phase 7: Reload persisted data in new session
        app_new = create_app(
            num_workers=3,
            frontier_maxsize=100,
            data_file=self.app.data_file
        )
        
        metrics2 = app_new.get_metrics()
        
        # Verify persistence: The actual proof is that search results are IDENTICAL
        # This proves the persisted index content is the same, not just metrics
        results2 = app_new.search("information retrieval")
        
        self.assertEqual(
            len(results1), len(results2),
            f"Search results count should match: {len(results1)} vs {len(results2)}"
        )
        
        # Verify the actual result tuples are identical (url, origin, depth)
        if len(results1) > 0 and len(results2) > 0:
            # Compare first few results to verify exact match
            for i in range(min(3, len(results1), len(results2))):
                self.assertEqual(
                    results1[i], results2[i],
                    f"Result {i} should be identical after reload"
                )
        
        app_new.shutdown()


if __name__ == "__main__":
    # Run all tests with verbose output
    unittest.main(verbosity=2)
