"""
services/dashboard.py
====================

Real-time metrics dashboard with separate window option.

Displays live crawler metrics in:
- Separate tkinter window (Windows/Linux/macOS) for clean UI
- Graceful fallback to terminal status bar if GUI unavailable

Features:
- No terminal UI conflicts
- Live updating metrics every 500ms
- Professional, clean display
- Cross-platform support
"""

import threading
import time
import os
import sys
from typing import Optional

# Try to import tkinter for GUI dashboard
try:
    import tkinter as tk
    from tkinter import font
    HAS_TKINTER = True
except (ImportError, ModuleNotFoundError):
    HAS_TKINTER = False

# Try to import curses for terminal UI
try:
    import curses
    HAS_CURSES = True
except (ImportError, ModuleNotFoundError):
    HAS_CURSES = False


class Dashboard:
    """
    Real-time metrics dashboard with GUI window or terminal fallback.
    
    Runs in background thread. If tkinter available, displays in separate window.
    Otherwise falls back to terminal status bar.
    """
    
    def __init__(self, coordinator):
        """
        Initialize dashboard.
        
        Args:
            coordinator: CrawlerCoordinator instance with get_metrics() method
        """
        self.coordinator = coordinator
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._update_interval = 0.5  # Update every 500ms
        self._root: Optional[tk.Tk] = None
        self._labels: dict = {}
        
    def start(self):
        """Start dashboard in background thread."""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=False)
        self._thread.start()
        
    def stop(self):
        """Stop dashboard thread."""
        self._running = False
        if self._root:
            try:
                self._root.quit()
            except:
                pass
        if self._thread:
            self._thread.join(timeout=2)
    
    def _run(self):
        """Main dashboard loop (runs in background thread)."""
        if HAS_TKINTER:
            try:
                self._run_gui_dashboard()
                return
            except Exception as e:
                print(f"[Dashboard] GUI failed: {e}", file=sys.stderr)
        
        # Fallback to terminal
        self._run_terminal_dashboard()
    
    def _run_gui_dashboard(self):
        """GUI dashboard using tkinter in separate window."""
        self._root = tk.Tk()
        self._root.title("Crawler Metrics")
        self._root.geometry("600x300")
        self._root.resizable(False, False)
        
        # Configure style
        self._root.configure(bg="#f0f0f0")
        
        # Title
        title_font = font.Font(family="Arial", size=14, weight="bold")
        title = tk.Label(self._root, text="VibeCrawler - Live Metrics", 
                        font=title_font, bg="#f0f0f0", fg="#333")
        title.pack(pady=10)
        
        # Metrics frame
        metrics_frame = tk.Frame(self._root, bg="#ffffff")
        metrics_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Create labels for each metric
        label_font = font.Font(family="Courier", size=10)
        
        metrics_info = [
            ("Elapsed Time", "elapsed"),
            ("URLs Processed", "urls_processed"),
            ("Current Max Depth", "current_max_depth"),
            ("Queue Depth", "queue_depth"),
            ("Visited URLs", "visited_count"),
            ("Indexed Keywords", "index_size"),
            ("Back Pressure Events", "back_pressure_events"),
            ("Active Workers", "active_workers"),
        ]
        
        for display_name, metric_key in metrics_info:
            row_frame = tk.Frame(metrics_frame, bg="#ffffff")
            row_frame.pack(fill=tk.X, padx=10, pady=5)
            
            label = tk.Label(row_frame, text=f"{display_name}:", 
                           font=label_font, bg="#ffffff", fg="#666", width=25, anchor="w")
            label.pack(side=tk.LEFT)
            
            value_label = tk.Label(row_frame, text="0", font=label_font, 
                                  bg="#ffffff", fg="#000", width=15, anchor="w")
            value_label.pack(side=tk.LEFT)
            
            self._labels[metric_key] = value_label
        
        # Start update loop
        self._update_gui()
        
        # Run the window event loop
        self._root.mainloop()
    
    def _update_gui(self):
        """Update GUI metrics display."""
        if not self._running or not self._root:
            return
        
        try:
            metrics = self.coordinator.get_metrics()
            elapsed = self.coordinator.metrics.get_elapsed_time()
            
            # Update each label
            if "elapsed" in self._labels:
                self._labels["elapsed"].config(text=f"{elapsed:.1f}s")
            if "urls_processed" in self._labels:
                self._labels["urls_processed"].config(text=str(metrics.urls_processed))
            if "current_max_depth" in self._labels:
                self._labels["current_max_depth"].config(text=str(metrics.current_max_depth))
            if "queue_depth" in self._labels:
                self._labels["queue_depth"].config(text=str(metrics.queue_depth))
            if "visited_count" in self._labels:
                self._labels["visited_count"].config(text=str(metrics.visited_count))
            if "index_size" in self._labels:
                self._labels["index_size"].config(text=str(metrics.index_size))
            if "back_pressure_events" in self._labels:
                self._labels["back_pressure_events"].config(text=str(metrics.back_pressure_events))
            if "active_workers" in self._labels:
                self._labels["active_workers"].config(text=str(metrics.active_workers))
            
            # Schedule next update
            self._root.after(int(self._update_interval * 1000), self._update_gui)
        except Exception:
            pass
    
    def _run_terminal_dashboard(self):
        """Fallback terminal status bar (Windows-friendly, no scrolling)."""
        
        print("\n" + "=" * 70, file=sys.stderr)
        print("LIVE METRICS (Terminal View)", file=sys.stderr)
        print("=" * 70 + "\n", file=sys.stderr)
        sys.stderr.flush()
        
        while self._running:
            try:
                metrics = self.coordinator.get_metrics()
                elapsed = self.coordinator.metrics.get_elapsed_time()
                
                status = (
                    f"[{elapsed:6.1f}s] "
                    f"URLs: {metrics.urls_processed:4d} | "
                    f"Queue: {metrics.queue_depth:4d} | "
                    f"Visited: {metrics.visited_count:4d} | "
                    f"Keywords: {metrics.index_size:5d} | "
                    f"BP Events: {metrics.back_pressure_events:4d}"
                )
                
                sys.stderr.write('\r' + status + ' ' * 10)
                sys.stderr.flush()
                
                time.sleep(self._update_interval)
            except Exception:
                pass
        
        sys.stderr.write('\n\n')
        sys.stderr.flush()

