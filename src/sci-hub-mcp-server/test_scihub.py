"""Quick verification script for sci-hub-mcp-server."""
import os

from requests.adapters import HTTPAdapter

try:
    from .sci_hub_search import (
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
except ImportError:
    from sci_hub_search import (
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
    print("✅ WORKING_SCIHUB_DOMAINS")

def test_dns_resolution():
    ip = resolve_domain(WORKING_SCIHUB_DOMAINS[0])
    assert isinstance(ip, str)
    parts = ip.split(".")
    assert len(parts) == 4
    print(f"✅ resolve_domain -> {ip}")

def test_proxy_config():
    # Returns None if no env vars are set (normal case)
    cfg = get_proxy_config()
    assert cfg is None or isinstance(cfg, dict)
    print(f"✅ get_proxy_config -> {cfg}")

def test_adapter():
    adapter = DNSOverHTTPSAdapter({"sci-hub.st": "186.2.163.201"})
    assert isinstance(adapter, HTTPAdapter)
    print("✅ DNSOverHTTPSAdapter instantiation")

def test_create_instance():
    sh = create_scihub_instance()
    assert sh is not None
    assert hasattr(sh, "session")
    print("✅ create_scihub_instance")

def test_search_by_doi():
    result = search_paper_by_doi("10.1002/jcad.12075")
    assert result["status"] in ("success", "not_found")
    if result["status"] == "success":
        assert result["pdf_url"].startswith("http")
    print(f"✅ search_paper_by_doi -> {result['status']}")

def test_search_by_title():
    result = search_paper_by_title(
        "Choosing Assessment Instruments for Posttraumatic Stress Disorder Screening"
    )
    assert result["status"] in ("success", "not_found")
    print(f"✅ search_paper_by_title -> {result['status']}")

def test_search_by_keyword():
    papers = search_papers_by_keyword("machine learning", num_results=2)
    assert isinstance(papers, list)
    print(f"✅ search_papers_by_keyword -> {len(papers)} papers")

def test_download():
    result = search_paper_by_doi("10.1002/jcad.12075")
    if result["status"] == "success":
        out = "_test_paper.pdf"
        ok = download_paper(result["pdf_url"], out)
        if ok and os.path.exists(out):
            size = os.path.getsize(out)
            assert size > 1024  # At least 1KB
            os.remove(out)
            print(f"✅ download_paper -> {size} bytes")
        else:
            print("⚠️ download_paper returned False (network/domain issue)")
    else:
        print("⚠️ Skipping download test — search failed")

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
    print("\n🎉 Verification complete!")