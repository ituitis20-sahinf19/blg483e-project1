"""
services/api_server.py
======================

HTTP REST API server for VibeCrawler.

Provides a Web API endpoint that allows searching the index via HTTP:
- Runs on localhost:3600
- Endpoint: GET /search?query=<word>&sortBy=relevance
- Returns results as JSON

This enables programmatic access to the search engine without using the CLI.
"""

import threading
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs


class SearchAPIHandler(BaseHTTPRequestHandler):
    """
    HTTP request handler for the search API.
    
    Handles GET requests to /search with query parameters.
    """
    
    # Reference to the coordinator (set by APIServer)
    coordinator = None
    
    def do_GET(self):
        """Handle GET requests."""
        # Parse URL and query parameters
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        query_params = parse_qs(parsed_url.query)
        
        # Route: /search endpoint
        if path == "/search":
            self._handle_search(query_params)
        # Route: /status endpoint (bonus)
        elif path == "/status":
            self._handle_status()
        # Route: /metrics endpoint (bonus)
        elif path == "/metrics":
            self._handle_metrics()
        else:
            self._send_error(404, "Not Found", {"error": "Endpoint not found"})
    
    def _handle_search(self, query_params):
        """
        Handle /search endpoint.
        
        Expected parameters:
        - query: The search keyword(s) (required)
        - sortBy: Sort order (optional, default: 'relevance')
        
        Returns:
            JSON response with results array
        """
        # Extract query parameter
        query_list = query_params.get('query', [])
        if not query_list or not query_list[0]:
            self._send_error(400, "Bad Request", {
                "error": "Missing required parameter: query"
            })
            return
        
        query = query_list[0]
        
        # Extract sortBy parameter (optional)
        sort_by_list = query_params.get('sortBy', ['relevance'])
        sort_by = sort_by_list[0] if sort_by_list else 'relevance'
        
        try:
            # Execute search via coordinator
            results = self.coordinator.search(query)
            
            # Format results as JSON-serializable list of objects
            formatted_results = [
                {
                    "url": url,
                    "origin_url": origin_url,
                    "depth": depth
                }
                for url, origin_url, depth in results
            ]
            
            # Send success response
            self._send_json(200, {
                "query": query,
                "sortBy": sort_by,
                "totalResults": len(formatted_results),
                "results": formatted_results
            })
        
        except Exception as e:
            self._send_error(500, "Internal Server Error", {
                "error": str(e)
            })
    
    def _handle_status(self):
        """
        Handle /status endpoint (bonus).
        
        Returns:
            JSON response with crawler status
        """
        try:
            is_active = self.coordinator.is_active()
            metrics = self.coordinator.get_metrics()
            
            self._send_json(200, {
                "status": "ACTIVE" if is_active else "INACTIVE",
                "urlsProcessed": metrics.urls_processed,
                "visitedCount": metrics.visited_count,
                "queueDepth": metrics.queue_depth,
                "indexSize": metrics.index_size,
                "backPressureEvents": metrics.back_pressure_events
            })
        
        except Exception as e:
            self._send_error(500, "Internal Server Error", {
                "error": str(e)
            })
    
    def _handle_metrics(self):
        """
        Handle /metrics endpoint (bonus).
        
        Returns:
            JSON response with detailed metrics
        """
        try:
            metrics = self.coordinator.get_metrics()
            elapsed = self.coordinator.metrics.get_elapsed_time()
            
            self._send_json(200, {
                "urlsProcessed": metrics.urls_processed,
                "currentMaxDepth": metrics.current_max_depth,
                "queueDepth": metrics.queue_depth,
                "visitedCount": metrics.visited_count,
                "indexSize": metrics.index_size,
                "backPressureEvents": metrics.back_pressure_events,
                "activeWorkers": metrics.active_workers,
                "elapsedSeconds": elapsed
            })
        
        except Exception as e:
            self._send_error(500, "Internal Server Error", {
                "error": str(e)
            })
    
    def _send_json(self, status_code, data):
        """Send a JSON response."""
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())
    
    def _send_error(self, status_code, reason, error_data):
        """Send an error response."""
        self._send_json(status_code, error_data)
    
    def log_message(self, format, *args):
        """Suppress default HTTP server logging."""
        pass  # Silent operation


class APIServer:
    """
    HTTP API server wrapper for VibeCrawler.
    
    Runs in a background thread on localhost:3600.
    
    Usage:
        api = APIServer(coordinator, port=3600)
        api.start()
        # ... server runs in background ...
        api.stop()
    """
    
    def __init__(self, coordinator, port=3600, host='127.0.0.1'):
        """
        Initialize the API server.
        
        Args:
            coordinator: CrawlerCoordinator instance
            port: Port to listen on (default 3600)
            host: Host to bind to (default 127.0.0.1 / localhost)
        """
        self.coordinator = coordinator
        self.port = port
        self.host = host
        self.server = None
        self.thread = None
    
    def start(self):
        """Start the API server in a background thread."""
        # Set the coordinator reference for the request handler
        SearchAPIHandler.coordinator = self.coordinator
        
        # Create HTTP server
        self.server = HTTPServer((self.host, self.port), SearchAPIHandler)
        
        # Run in background thread
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        
        print(f"[OK] API Server started on http://{self.host}:{self.port}")
        print(f"     Try: http://localhost:{self.port}/search?query=python&sortBy=relevance")
    
    def stop(self):
        """Stop the API server."""
        if self.server:
            self.server.shutdown()
            if self.thread:
                self.thread.join(timeout=5)
            print("[OK] API Server stopped")
