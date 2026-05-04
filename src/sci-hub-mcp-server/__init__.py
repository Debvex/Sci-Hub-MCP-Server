"""Sci-Hub MCP Server — A robust library and MCP server for searching and downloading academic papers."""

__version__ = "0.1.1"

from sci_hub_mcp_server.sci_hub_search import (
    WORKING_SCIHUB_DOMAINS,
    resolve_domain,
    get_proxy_config,
    DNSOverHTTPSAdapter,
    create_scihub_instance,
    search_paper_by_doi,
    search_paper_by_title,
    search_papers_by_keyword,
    download_paper,
)

__all__ = [
    "__version__",
    "WORKING_SCIHUB_DOMAINS",
    "resolve_domain",
    "get_proxy_config",
    "DNSOverHTTPSAdapter",
    "create_scihub_instance",
    "search_paper_by_doi",
    "search_paper_by_title",
    "search_papers_by_keyword",
    "download_paper",
]
