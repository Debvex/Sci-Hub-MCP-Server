# Sci-Hub MCP Server

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/License-GPL%20v3+-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![MCP Server](https://img.shields.io/badge/MCP-Server-1e1e1e)](https://modelcontextprotocol.io)

A robust [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server and Python library that enables AI assistants and developers to search, retrieve metadata, and download academic papers directly from Sci-Hub. Built with resilience against DNS blocking, ISP censorship, and outdated domain lists.

**Key Features**

- **Permanent Domain Safeguard** — Hardcoded working Sci-Hub domains that survive package reinstalls
- **DNS-over-HTTPS Fallback** — Bypass ISP DNS blocking using Google & Cloudflare DoH
- **Proxy Support** — HTTP/HTTPS proxy via standard or `SCIHUB_*` environment variables
- **Custom HTTP Adapter** — IP-based connections when DNS is completely blocked
- **CrossRef Metadata Integration** — Enriches Sci-Hub results with real paper metadata
- **Async MCP Server** — Exposes 5 tools via FastMCP for AI assistant integration

---

## Table of Contents

1. [Installation](#installation)
2. [Environment Variables](#environment-variables)
3. [Python Library API](#python-library-api)
4. [MCP Server Tools](#mcp-server-tools)
5. [Running the MCP Server](#running-the-mcp-server)
6. [Testing & Verification](#testing--verification)
7. [Architecture](#architecture)
8. [Troubleshooting](#troubleshooting)

---

## Installation

```bash
pip install sci-hub-mcp-server
```

**Requirements:** Python 3.11 or higher.

### From Source

```bash
git clone https://github.com/Debvex/Sci-Hub-MCP-Server.git
cd Sci-Hub-MCP-Server
pip install -e ".[dev]"
```

---

## Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `SCIHUB_HTTPS_PROXY` | Preferred HTTPS proxy (highest priority) | `http://127.0.0.1:8080` |
| `SCIHUB_HTTP_PROXY` | Preferred HTTP proxy | `http://127.0.0.1:8080` |
| `HTTPS_PROXY` | Standard system HTTPS proxy | `http://proxy.corp:8080` |
| `HTTP_PROXY` | Standard system HTTP proxy | `http://proxy.corp:8080` |
| `PYTHONUTF8` | Set to `1` on Windows to avoid `cp1252` encoding errors | `1` |

**Proxy Priority:** `SCIHUB_HTTPS_PROXY` > `SCIHUB_HTTP_PROXY` > `HTTPS_PROXY` > `HTTP_PROXY`

---

## Python Library API

The package exposes a low-level search/download API that works independently of the MCP server.

### Module: `sci_hub_mcp_server.sci_hub_search`

#### `WORKING_SCIHUB_DOMAINS`

**Type:** `list[str]`

Hardcoded list of verified working Sci-Hub domains. Used as the source of truth when the upstream `scihub` package contains stale domains.

**Current values:**
```python
["sci-hub.st", "sci-hub.box"]
```

---

#### `resolve_domain(hostname: str) -> str`

Resolve a Sci-Hub domain to an IPv4 address with automatic fallback to public DNS-over-HTTPS resolvers.

**Resolution Strategy:**
1. Try standard `socket.getaddrinfo` (system DNS)
2. If blocked, query `https://dns.google/resolve`
3. If still blocked, query `https://cloudflare-dns.com/dns-query`
4. Raise `ConnectionError` if all methods fail

**Parameters:**
- `hostname` (`str`): Domain to resolve, e.g. `"sci-hub.st"`

**Returns:**
- `str`: Resolved IPv4 address

**Raises:**
- `ConnectionError`: If DNS and DoH both fail

**Example:**
```python
from sci_hub_mcp_server.sci_hub_search import resolve_domain

ip = resolve_domain("sci-hub.st")
print(ip)  # "186.2.163.201"
```

---

#### `get_proxy_config() -> dict | None`

Read proxy configuration from environment variables.

**Returns:**
- `dict`: `{"https": "...", "http": "..."}` if a proxy is configured
- `None`: If no proxy variables are set

**Example:**
```python
from sci_hub_mcp_server.sci_hub_search import get_proxy_config

proxy = get_proxy_config()
# proxy = {"https": "http://127.0.0.1:8080", "http": "http://127.0.0.1:8080"}
```

---

#### `class DNSOverHTTPSAdapter(HTTPAdapter)`

Custom `requests` adapter that transparently replaces hostnames with pre-resolved IP addresses and injects the correct `Host` header. Used to bypass DNS blocking at the transport layer.

**Constructor:**
```python
DNSOverHTTPSAdapter(domain_ip_map: dict[str, str], **kwargs)
```

**Parameters:**
- `domain_ip_map`: Mapping of hostname -> IP, e.g. `{"sci-hub.st": "186.2.163.201"}`
- `**kwargs`: Passed to `HTTPAdapter` (includes built-in retry: 3 attempts with 0.5s backoff for 5xx errors)

**Example:**
```python
import requests
from sci_hub_mcp_server.sci_hub_search import DNSOverHTTPSAdapter

session = requests.Session()
adapter = DNSOverHTTPSAdapter({"sci-hub.st": "186.2.163.201"})
session.mount("https://", adapter)
session.mount("http://", adapter)

# This request connects to the IP directly, but the server sees Host: sci-hub.st
resp = session.get("https://sci-hub.st/", verify=False)
```

> **Note:** `verify=False` is hardcoded in this adapter because Sci-Hub certificates typically do not match raw IP addresses.

---

#### `create_scihub_instance() -> SciHub`

Factory function that creates a fully configured `SciHub` object with:
- Domain list overridden to `WORKING_SCIHUB_DOMAINS`
- Browser-like HTTP headers
- Proxy settings (if environment variables are set)
- `DNSOverHTTPSAdapter` mounted on both `http://` and `https://`
- 30-second request timeout

**Returns:**
- `SciHub`: Configured instance ready for searching

**Example:**
```python
from sci_hub_mcp_server.sci_hub_search import create_scihub_instance

sh = create_scihub_instance()
# sh.session is a requests.Session with all safeguards applied
```

---

#### `search_paper_by_doi(doi: str) -> dict`

Search for a paper on Sci-Hub using its DOI. Tries each domain in `WORKING_SCIHUB_DOMAINS` sequentially until one succeeds.

**Parameters:**
- `doi` (`str`): DOI string, e.g. `"10.1038/nature09492"`

**Returns:**
```python
{
    "doi": "10.1038/nature09492",
    "pdf_url": "https://sci-hub.st/...",
    "status": "success",
    "title": "",
    "author": "",
    "year": ""
}
# or on failure:
{
    "doi": "10.1038/nature09492",
    "status": "not_found"
}
```

> **Note:** `title`, `author`, and `year` are intentionally left empty by Sci-Hub search. Use `search_paper_by_title()` or `get_paper_metadata()` for populated metadata via CrossRef.

**Example:**
```python
from sci_hub_mcp_server.sci_hub_search import search_paper_by_doi

result = search_paper_by_doi("10.1002/jcad.12075")
if result["status"] == "success":
    print(f"PDF URL: {result['pdf_url']}")
else:
    print("Paper not found")
```

---

#### `search_paper_by_title(title: str) -> dict`

Resolve a paper title to a DOI via the [CrossRef API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/), then fetch the PDF from Sci-Hub.

**Parameters:**
- `title` (`str`): Full or partial paper title

**Returns:**
```python
{
    "doi": "10.1002/jcad.12075",
    "pdf_url": "https://sci-hub.st/...",
    "status": "success",
    "title": "Actual paper title from CrossRef",
    "author": "Smith, J., Doe, A.",
    "year": "2023"
}
# or:
{
    "title": "User's query title",
    "status": "not_found"
}
```

**Example:**
```python
from sci_hub_mcp_server.sci_hub_search import search_paper_by_title

result = search_paper_by_title(
    "Choosing Assessment Instruments for Posttraumatic Stress Disorder Screening"
)
print(result.get("doi"), result.get("title"), result.get("author"))
```

---

#### `search_papers_by_keyword(keyword: str, num_results: int = 10) -> list[dict]`

Search CrossRef for papers matching a keyword, then attempt to fetch each PDF from Sci-Hub.

**Parameters:**
- `keyword` (`str`): Search term(s)
- `num_results` (`int`, default `10`): Maximum CrossRef results to check

**Returns:**
- `list[dict]`: Each dict has the same shape as `search_paper_by_title()` results

**Example:**
```python
from sci_hub_mcp_server.sci_hub_search import search_papers_by_keyword

papers = search_papers_by_keyword("artificial intelligence medicine 2023", num_results=3)
for p in papers:
    print(p["doi"], p["title"], p.get("pdf_url"))
```

---

#### `download_paper(pdf_url: str, output_path: str) -> bool`

Download a PDF from a direct URL using the fully configured Sci-Hub session (including DNS bypass, proxy, and headers).

**Parameters:**
- `pdf_url` (`str`): Direct PDF URL obtained from a search result
- `output_path` (`str`): Destination file path (should end in `.pdf`)

**Returns:**
- `bool`: `True` on success, `False` on failure

**Example:**
```python
from sci_hub_mcp_server.sci_hub_search import search_paper_by_doi, download_paper

result = search_paper_by_doi("10.1002/jcad.12075")
if result["status"] == "success":
    success = download_paper(result["pdf_url"], "paper.pdf")
    print("Downloaded!" if success else "Failed")
```

---

## MCP Server Tools

When you run `sci_hub_server`, it starts a FastMCP server exposing the following async tools. These are the endpoints AI assistants (Claude, Copilot, etc.) connect to.

### `search_scihub_by_doi(doi: str) -> dict`

MCP tool wrapper around `search_paper_by_doi()`.

**Input:** `{"doi": "10.1038/nature09492"}`
**Output:** Same return shape as the library function, plus `"error"` on exception.

---

### `search_scihub_by_title(title: str) -> dict`

MCP tool wrapper around `search_paper_by_title()`.

**Input:** `{"title": "Quantum entanglement in photosynthesis"}`
**Output:** Same return shape as the library function, plus `"error"` on exception.

---

### `search_scihub_by_keyword(keyword: str, num_results: int = 10) -> list[dict]`

MCP tool wrapper around `search_papers_by_keyword()`.

**Input:** `{"keyword": "CRISPR therapy", "num_results": 5}`
**Output:** List of paper dicts, or `[{"error": "..."}]` on exception.

---

### `download_scihub_pdf(pdf_url: str, output_path: str) -> str`

MCP tool wrapper around `download_paper()`.

**Input:** `{"pdf_url": "https://sci-hub.st/...", "output_path": "/tmp/paper.pdf"}`
**Output:** Human-readable status string.

---

### `get_paper_metadata(doi: str) -> dict`

Fetch metadata (title, author, year, pdf_url) for a known DOI. Internally calls `search_paper_by_doi()` and reshapes the response.

**Input:** `{"doi": "10.1038/nature09492"}`
**Output:**
```python
{
    "doi": "10.1038/nature09492",
    "title": "...",
    "author": "...",
    "year": "...",
    "pdf_url": "...",
    "status": "success"
}
# or:
{"error": "Could not find metadata for paper with DOI ..."}
```

---

## Running the MCP Server

### Stdio Transport (default — for Claude Desktop, etc.)

```bash
python -m sci_hub_mcp_server.sci_hub_server
```

Or if installed via pip:

```bash
sci-hub-mcp-server
```
*(Requires a `[project.scripts]` entry in `pyproject.toml` — see Contributing).*

### Claude Desktop Configuration

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "scihub": {
      "command": "python",
      "args": ["-m", "sci_hub_mcp_server.sci_hub_server"]
    }
  }
}
```

---

## Testing & Verification

### Quick Self-Test (built-in)

The module contains a `__main__` block with 3 integration tests. Run:

```bash
python -m sci_hub_mcp_server.sci_hub_search
```

This will:
1. Search by DOI (`10.1002/jcad.12075`)
2. Search by title (`"Choosing Assessment Instruments..."`)
3. Search by keyword (`"artificial intelligence medicine 2023"`, 3 results)

**Expected output on success:**
```
Sci-Hub

1. Search for a paper by DOI
Title: 
Author: 
Year: 
PDF URL: https://sci-hub.st/...
Paper downloaded to: paper_10.1002_jcad.12075.pdf

2. Search for a paper by title
DOI: 10.1002/jcad.12075
Author: ...
Year: ...
PDF URL: https://sci-hub.st/...

3. Search for papers by keyword
Paper 1:
Title: ...
DOI: ...
Author: ...
Year: ...
PDF URL: ...
```

> **Note:** Empty `title`/`author`/`year` in Test 1 is expected — Sci-Hub HTML does not expose metadata. Tests 2 & 3 show populated metadata thanks to CrossRef enrichment.

---

### Unit-Style Verification Script

Save this as `test_scihub.py` and run it to verify every API surface:

```python
"""Quick verification script for sci-hub-mcp-server."""
import os
from sci_hub_mcp_server.sci_hub_search import (
    WORKING_SCIHUB_DOMAINS,
    resolve_domain,
    get_proxy_config,
    create_scihub_instance,
    search_paper_by_doi,
    search_paper_by_title,
    search_papers_by_keyword,
    download_paper,
    DNSOverHTTPSAdapter,
)

def test_constants():
    assert isinstance(WORKING_SCIHUB_DOMAINS, list)
    assert len(WORKING_SCIHUB_DOMAINS) > 0
    print("WORKING_SCIHUB_DOMAINS is working...")

def test_dns_resolution():
    ip = resolve_domain(WORKING_SCIHUB_DOMAINS[0])
    assert isinstance(ip, str)
    parts = ip.split(".")
    assert len(parts) == 4
    print(f"resolve_domain -> {ip} is working...")

def test_proxy_config():
    # Returns None if no env vars are set (normal case)
    cfg = get_proxy_config()
    assert cfg is None or isinstance(cfg, dict)
    print(f"get_proxy_config -> {cfg} is working...")

def test_adapter():
    import requests
    adapter = DNSOverHTTPSAdapter({"sci-hub.st": "186.2.163.201"})
    assert isinstance(adapter, requests.adapters.HTTPAdapter)
    print("DNSOverHTTPSAdapter instantiation is working...")

def test_create_instance():
    sh = create_scihub_instance()
    assert sh is not None
    assert hasattr(sh, "session")
    print("create_scihub_instance is working...")

def test_search_by_doi():
    result = search_paper_by_doi("10.1002/jcad.12075")
    assert result["status"] in ("success", "not_found")
    if result["status"] == "success":
        assert result["pdf_url"].startswith("http")
    print(f"search_paper_by_doi -> {result['status']}")

def test_search_by_title():
    result = search_paper_by_title(
        "Choosing Assessment Instruments for Posttraumatic Stress Disorder Screening"
    )
    assert result["status"] in ("success", "not_found")
    print(f"search_paper_by_title -> {result['status']}")

def test_search_by_keyword():
    papers = search_papers_by_keyword("machine learning", num_results=2)
    assert isinstance(papers, list)
    print(f"search_papers_by_keyword -> {len(papers)} papers works...")

def test_download():
    result = search_paper_by_doi("10.1002/jcad.12075")
    if result["status"] == "success":
        out = "_test_paper.pdf"
        ok = download_paper(result["pdf_url"], out)
        if ok and os.path.exists(out):
            size = os.path.getsize(out)
            assert size > 1024  # At least 1KB
            os.remove(out)
            print(f"download_paper -> {size} bytes")
        else:
            print("download_paper returned False (network/domain issue)")
    else:
        print("Skipping download test — search failed")

if __name__ == "__main__":
    print("Running sci-hub-mcp-server verification...\n")
    test_constants()
    test_dns_resolution()
    test_proxy_config()
    test_adapter()
    test_create_instance()
    test_search_by_doi()
    test_search_by_title()
    test_search_by_keyword()
    test_download()
    print("\nVerification complete!")
```

Run it:

```bash
python test_scihub.py
```

---

### Manual Health Checks

**1. Check DNS resolution (no Sci-Hub session needed):**
```python
from sci_hub_mcp_server.sci_hub_search import resolve_domain
print(resolve_domain("sci-hub.st"))       # Should print an IP
print(resolve_domain("sci-hub.box"))      # Should print an IP
```

**2. Check proxy detection:**
```python
import os
os.environ["SCIHUB_HTTPS_PROXY"] = "http://127.0.0.1:8080"
from sci_hub_mcp_server.sci_hub_search import get_proxy_config
print(get_proxy_config())  # {'https': 'http://127.0.0.1:8080', 'http': '...'}
```

**3. Check session headers & adapter:**
```python
from sci_hub_mcp_server.sci_hub_search import create_scihub_instance
sh = create_scihub_instance()
print(sh.session.headers["User-Agent"])  # Mozilla/5.0 ...
print(sh.session.proxies)                # {} or proxy dict
```

---

## Architecture

```
sci_hub_mcp_server/
├── __init__.py              # Package exports
├── sci_hub_search.py        # Core library (DNS, proxy, search, download)
└── sci_hub_server.py        # FastMCP server (5 async tools)
```

**Data Flow**

```
User / AI Assistant
      |
      v
+---------------+     +------------------+     +-----------------+
|  MCP Server   | --> | sci_hub_search   | --> |  Sci-Hub /      |
|  (FastMCP)    |     | (DNS/Proxy/HTTP) |     |  CrossRef APIs  |
+---------------+     +------------------+     +-----------------+
      |
      v
  JSON Result
```

**Resilience Layers**

1. **Domain Safeguard** — `WORKING_SCIHUB_DOMAINS` overrides whatever the `scihub` package thinks is current
2. **DNS Bypass** — `resolve_domain()` + `DNSOverHTTPSAdapter` handles ISP-level blocking
3. **Proxy Layer** — `get_proxy_config()` picks up corporate/VPN proxies automatically
4. **Retry Logic** — `Retry(total=3, backoff_factor=0.5)` on 5xx errors inside the adapter
5. **Multi-Domain Fallback** — `search_paper_by_doi()` tries every domain before giving up

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| `ConnectionError: Cannot resolve sci-hub.st` | ISP blocks both DNS and DoH | Use a VPN or HTTP proxy (`SCIHUB_HTTPS_PROXY`) |
| Empty `title`/`author`/`year` from DOI search | Sci-Hub HTML lacks metadata | Use `search_paper_by_title()` or `get_paper_metadata()` |
| `CAPTCHA needed` exception | Sci-Hub flagged your IP | Add delays, use a proxy, or try a different network |
| SSL certificate errors | Connecting via IP instead of hostname | Expected — `verify=False` is used inside `DNSOverHTTPSAdapter` |
| `UnicodeDecodeError` on Windows | Terminal uses `cp1252` | Run with `PYTHONUTF8=1` or set `chcp 65001` |

---

## Publishing to PyPI / TestPyPI

This repository contains a GitHub Actions workflow (`.github/workflows/publish.yml`) that builds and publishes the package automatically using **trusted publishing** (OIDC) — no long-lived API tokens stored in GitHub secrets.

### How it works

| Trigger | Target | Environment |
|---------|--------|-------------|
| Push to `main` branch | **TestPyPI** | `testpypi` |
| Push a tag `v*.*.*` | **PyPI** | `pypi` |
| **GitHub Release published** | **PyPI + TestPyPI** | `pypi` / `testpypi` |
| Manual `workflow_dispatch` | You choose | `testpypi` or `pypi` |

### Setup (one-time)

You must configure **trusted publishing** on both PyPI and TestPyPI before the workflow can upload anything.

#### 1. TestPyPI

1. Create an account at https://test.pypi.org/
2. Go to **Account Settings → Publishing**
3. Click **Add a new pending publisher**
4. Fill in:
   - **PyPI Project Name**: `sci-hub-mcp-server`
   - **Owner**: `Debvex`
   - **Repository name**: `Sci-Hub-MCP-Server`
   - **Workflow name**: `publish.yml`
   - **Environment name**: `testpypi`
5. Click **Add**

#### 2. PyPI (production)

1. Create an account at https://pypi.org/
2. Go to **Account Settings → Publishing**
3. Click **Add a new pending publisher**
4. Fill in:
   - **PyPI Project Name**: `sci-hub-mcp-server`
   - **Owner**: `Debvex`
   - **Repository name**: `Sci-Hub-MCP-Server`
   - **Workflow name**: `publish.yml`
   - **Environment name**: `pypi`
5. Click **Add**

### Release process

**Staging release (TestPyPI):**
```bash
git commit -m "fix: improve DNS fallback"
git push origin main
```
The workflow uploads to TestPyPI automatically. Verify at https://test.pypi.org/project/sci-hub-mcp-server/

**Production release (PyPI):**
```bash
# Update version in __init__.py and pyproject.toml first
git add .
git commit -m "release: v0.1.1"
git tag v0.1.1
git push origin main --tags
```
The tag push triggers the PyPI job.

### Manual trigger

Go to **Actions → Publish Python Package → Run workflow** and select the target.

---

## License

GPL-3.0-or-later. See `LICENSE` for details.

---

## Author

**Debmalya Sett** — settdebmalya273@gmail.com
