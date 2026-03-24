# ---

**Product Requirements Document (PRD)**

**Project Name:** VibeCrawler

**Document Version:** 1.0

**Role / Persona:** System Architect (AI Orchestrator)

## **1\. Executive Summary**

"VibeCrawler" is an architectural challenge to build a functional web crawler and real-time search engine entirely from scratch. This project represents a paradigm shift: the primary development methodology moves away from manual coding to **System Architecture and AI Orchestration**. The developer will act as the Architect, steering AI agents (e.g., Cursor, Claude, VS Code) to generate, manage, and verify complex, concurrent software systems while maintaining strict "Human-in-the-Loop" oversight.

## **2\. Project Goals**

* **Demonstrate Architectural Sensibility:** Design a scalable, decoupled system where crawling and searching operate harmoniously.  
* **Master Concurrency Management:** Implement safe, lock-free, or appropriately synchronized data structures to handle simultaneous read/write operations.  
* **Validate Human-in-the-Loop Orchestration:** Successfully prompt, guide, and verify AI-generated code, ensuring it meets strict systemic constraints without hallucinating or defaulting to easy workarounds.

## **3\. Scope**

**In Scope:**

* A custom-built, recursive web crawler (Indexer).  
* A real-time query engine (Searcher) capable of searching while the indexer is active.  
* Thread-safe data storage mapping keywords to URLs.  
* Use of standard, language-native libraries only.

**Out of Scope:**

* Use of high-level scraping or crawling libraries (e.g., Scrapy, BeautifulSoup).  
* Production-grade distributed infrastructure (e.g., Kubernetes, external message brokers like Kafka—unless built natively).  
* Advanced NLP or PageRank algorithms for relevancy.

## ---

**4\. Functional Requirements**

### **4.1. Indexer (Web Crawler)**

The Indexer is responsible for discovering, fetching, and processing web pages.

* **F.1.1 Recursive Crawling:** The system must accept an origin URL and recursively crawl discovered links up to a user-defined maximum depth ($k$).  
* **F.1.2 Uniqueness Guarantee:** The system must implement a "Visited" data structure (e.g., a concurrent Set) to ensure no single URL is crawled or processed more than once.  
* **F.1.3 Back Pressure Management:** The crawler must regulate its own workload. It must implement mechanisms to manage load, such as enforcing a maximum rate of concurrent workers, connection pooling limits, or queue depth thresholds to prevent memory exhaustion and network rate-limiting.

### **4.2. Searcher (Query Engine)**

The Searcher is responsible for accepting user queries and returning ranked results from the live index.

* **F.2.1 Real-Time Querying:** The search engine must return a structured list of results formatted as a triple: (relevant\_url, origin\_url, depth).  
* **F.2.2 Live Indexing Support:** The query engine must be able to read from the index while the crawler is actively writing to it, without blocking the crawler or returning corrupted data.  
* **F.2.3 Relevancy Ranking:** The system must implement a baseline heuristic to rank search results. Acceptable heuristics include keyword frequency (Term Frequency) or HTML Title tag matching.

## ---

**5\. Technical & Non-Functional Requirements**

### **5.1. Concurrency and Thread Safety**

* **Constraint:** The system must be explicitly designed for concurrent execution.  
* **Implementation:** The Architect must direct the AI to utilize thread-safe data structures. Depending on the chosen language, this includes Mutexes/Read-Write Locks, Channels (e.g., in Go), or Concurrent Maps (e.g., ConcurrentHashMap in Java or sync.Map in Go).  
* **Goal:** Zero data races or corruption during simultaneous read/write operations on the core index and the "Visited" set.

### **5.2. Native Focus (Zero-Dependency Constraint)**

* **Constraint:** The core logic for networking and HTML parsing must rely exclusively on language-native functionality (e.g., net/http and html packages in Go, or urllib and html.parser in Python).  
* **Goal:** Prove the Architect's ability to instruct the AI to build foundational systems rather than relying on black-box external abstractions.

### **5.3. AI Orchestration Guidelines**

* **Prompting Strategy:** Prompts must explicitly state constraints (e.g., "Write a thread-safe inverted index using native Go maps and sync.RWMutex. Do not use external packages.").  
* **Verification:** The Architect must perform "Human-in-the-Loop" verification for every major component generated, reviewing for race conditions, memory leaks, and adherence to the native-only constraint.

## ---

**6\. High-Level Architecture Flow**

1. **Seed Input:** User provides an Origin URL and Depth $k$.  
2. **Frontier Queue:** URL is pushed to a thread-safe queue.  
3. **Worker Pool:** A limited pool of concurrent workers pulls from the queue (handling Back Pressure).  
4. **Fetch & Parse:** Workers fetch the HTML (Native libraries only), extract links, and extract text/titles.  
5. **Filter:** Extracted links are checked against the concurrent "Visited" set. New links are pushed to the Frontier Queue with depth \+ 1\.  
6. **Index:** Parsed text is tokenized and written to a concurrent Inverted Index.  
7. **Search API:** A separate thread/process accepts user queries, reads from the Inverted Index, calculates the Relevancy Heuristic, and returns the formatted Triples.

---

