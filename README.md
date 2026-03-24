# VibeCrawler 🕸️🔍

[Python](https://img.shields.io/badge/python-3.8+-blue.svg)  
[Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen.svg)

A high-performance, thread-safe web crawler and real-time search engine built entirely with Python's native standard library. No external dependencies required.

## Overview

VibeCrawler is a concurrent web crawler that recursively discovers and indexes web pages, enabling real-time full-text search on the indexed content. The system uses worker thread pools for concurrent fetching, implements automatic back pressure for memory safety, and provides thread-safe concurrent search capabilities while crawling continues.

****Key Innovation:**** Search queries can execute concurrently with active crawling without blocking either operation, utilizing a custom-built Read-Write Lock (RWLock) for efficient data access.

## Features

****Concurrent Recursive Crawling:**** Fetch and index pages up to a user-specified maximum depth using a worker pool.  
****Real-Time Search:**** Query indexed content at any time—even while the crawler is actively discovering new pages.  
****Real-Time Dashboard:**** View the crawled URLs in real-time, from a seperate window. 
****Smart Relevancy Ranking:**** Search results are ranked by keyword match count (primary) and term frequency (secondary).  
****Memory Safe (Back Pressure):**** Bounded work queues prevent memory exhaustion; workers automatically throttle discovery when the queue is full.  
****Zero Duplicate Crawling:**** A thread-safe visited set ensures URLs are only processed once.  
****Zero External Dependencies:**** Built purely with Python's standard library (threading, queue, urllib, html.parser).

## Prerequisites

\- ****Python 3.8+**** is required.  
\- No virtual environment or \`pip install\` required since there are no external dependencies\!

## Quickstart & Usage

1. **Clone the repository:**  
   bash  
   git clone \[https://github.com/yourusername/vibecrawler.git\](https://github.com/yourusername/vibecrawler.git)  
   cd vibecrawler

2. **Run the application:**  
   Launch the main interactive CLI orchestrator:  
   Bash  
   python app.py

3. **Using the CLI:**  
   Once the application is running, you can interact with the search engine and monitor the crawler using the following commands:  
   * search \<query\> \- Perform a real-time full-text search (e.g., search python web crawler).  
   * status \- Check if the crawler is active and view a quick snapshot of visited URLs and queue depth.  
   * metrics \- View detailed, real-time crawling metrics and performance data. Available in case dashboard breaks. 
   * quit / Ctrl+C \- Gracefully shut down the worker pool and exit.

## **Under the Hood**

VibeCrawler was designed with a heavy focus on concurrency and performance natively in Python.

* **Concurrency:** Fixed worker pool to avoid dynamic thread spawning overhead.  
* **Synchronization:** Custom RWLock allows multiple concurrent searchers (readers) without blocking, while ensuring exclusive access for the indexer (writer).  
* **Network & Parsing:** Native urllib for network I/O and standard html.parser for extracting links and text.

## **Troubleshooting**

* **No URLs Processing:** Check your network connectivity and verify the seed URL is accessible. Ensure the crawl is actually running using the status command.  
* **Memory Growing:** The built-in back pressure mechanism should prevent this. If it still occurs, try reducing frontier\_maxsize or the num\_workers in app.py.  
* **Index Data Seems Stale/Stuck:** If the index is loading outdated data, delete the persisted JSON file at data/storage/p.data to start fresh, then run a new crawl.

## **Project Structure**

blg483e-project1/  
├── app.py                          \# Main application & interactive CLI  
├── services/  
│   ├── crawler.py                  \# Worker threads, fetching, and parsing  
│   └── index.py                    \# Thread-safe core data structures  
├── utils/  
│   └── locks.py                    \# Custom RWLock implementation  
└── data/  
    └── storage/  
        └── p.data                  \# Persisted index (JSON)

