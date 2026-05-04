from scihub import SciHub
import scihub
import re
import os
import urllib3
import requests
import sys
import socket
import json
import logging
from typing import Any
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

logger = logging.getLogger(__name__)

# =============================================================================
# PERMANENT DOMAIN SAFEGUARD - DO NOT REMOVE
# =============================================================================
# This is our "source of truth" for working Sci-Hub domains.
# The scihub package may revert to dead domains if reinstalled.
# This override ensures the MCP server continues working even after:
#   - pip install --force-reinstall scihub
#   - Package updates with outdated domain lists
#   - Fresh venv creation with old package versions
#
# Update this list when domains change. Test new domains before updating.
# Last verified: 2026-05-01
WORKING_SCIHUB_DOMAINS = [
    "sci-hub.st",  # 186.2.163.201 - primary
    "sci-hub.box",  # 190.115.31.76 - fallback
]
# =============================================================================

# =============================================================================
# DNS-OVER-HTTPS FALLBACK - BYPASS ISP DNS BLOCKING
# =============================================================================
# When ISP blocks DNS resolution for Sci-Hub domains, we use public DoH
# (DNS-over-HTTPS) to resolve domain names to IP addresses.
# This bypasses the ISP's DNS servers entirely.

# Cache for resolved IPs to avoid repeated lookups
_dns_cache = {}

def resolve_domain(hostname):
    """
    Resolve hostname with DNS-over-HTTPS fallback for ISP-blocked domains.
    
    Strategy:
    1. Try normal DNS resolution first (fastest if it works)
    2. If DNS fails (ISP blocking), fall back to Google DoH
    3. If Google fails, try Cloudflare DoH
    4. Raise ConnectionError if all methods fail
    
    Returns:
        str: Resolved IP address
    
    Raises:
        ConnectionError: If domain cannot be resolved
    """
    if hostname in _dns_cache:
        return _dns_cache[hostname]
    
    try:
        # Filter for IPv4 only (AF_INET) to avoid IPv6 addresses that requests can't handle
        addr = socket.getaddrinfo(hostname, 443, family=socket.AF_INET)[0][4][0]
        _dns_cache[hostname] = addr
        return addr
    except socket.gaierror:
        pass
    
    try:
        resp = requests.get(
            f"https://dns.google/resolve?name={hostname}&type=A",
            timeout=10
        )
        data = resp.json()
        if data.get("Answer"):
            for answer in data["Answer"]:
                if answer.get("type") == 1:
                    ip = answer["data"]
                    _dns_cache[hostname] = ip
                    return ip
    except Exception:
        pass
    
    try:
        resp = requests.get(
            f"https://cloudflare-dns.com/dns-query?name={hostname}&type=A",
            headers={"accept": "application/dns-json"},
            timeout=10
        )
        data = resp.json()
        if data.get("Answer"):
            for answer in data["Answer"]:
                if answer.get("type") == 1:
                    ip = answer["data"]
                    _dns_cache[hostname] = ip
                    return ip
    except Exception:
        pass
    
    raise ConnectionError(f"Cannot resolve {hostname}: DNS blocked and DoH fallback failed")


# =============================================================================
# PROXY SUPPORT
# =============================================================================
# Support for HTTP/HTTPS proxies via environment variables.
# Priority: SCIHUB_* > standard HTTP_PROXY/HTTPS_PROXY

def get_proxy_config():
    """
    Get proxy configuration from environment variables.
    
    Environment variables checked (in order):
    1. SCIHUB_HTTPS_PROXY
    2. SCIHUB_HTTP_PROXY
    3. HTTPS_PROXY
    4. HTTP_PROXY
    
    Returns:
        dict: Proxy config like {"https": "http://proxy:port", "http": "http://proxy:port"}
              or None if no proxy configured
    """
    proxy = (
        os.environ.get("SCIHUB_HTTPS_PROXY") or
        os.environ.get("SCIHUB_HTTP_PROXY") or
        os.environ.get("HTTPS_PROXY") or
        os.environ.get("HTTP_PROXY")
    )
    if proxy:
        return {"https": proxy, "http": proxy}
    return None


# =============================================================================
# CUSTOM HTTP ADAPTER FOR IP-BASED CONNECTIONS
# =============================================================================
# When DNS is blocked, we connect directly to the resolved IP address.
# This adapter replaces hostnames with IPs and sets the Host header
# so the server knows which domain we're requesting.

class DNSOverHTTPSAdapter(HTTPAdapter):
    """
    Custom HTTPAdapter that connects to resolved IPs instead of hostnames.
    
    This bypasses DNS blocking by:
    1. Pre-resolving domain names via DoH
    2. Replacing the hostname in the URL with the IP address
    3. Setting the Host header to the original hostname (required for virtual hosting)
    """
    
    def __init__(self, domain_ip_map, **kwargs):
        self.domain_ip_map = domain_ip_map
        kwargs['max_retries'] = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
        super().__init__(**kwargs)
    
    def send(self, request, **kwargs):
        from urllib.parse import urlparse
        
        parsed = urlparse(request.url)
        hostname = parsed.hostname
        
        if hostname and hostname in self.domain_ip_map:
            ip = self.domain_ip_map[hostname]
            new_url = request.url.replace(hostname, ip, 1)
            request.url = new_url
            
            port = parsed.port
            if port:
                request.headers['Host'] = f"{hostname}:{port}"
            else:
                request.headers['Host'] = hostname
        
        kwargs_copy = dict(kwargs)
        kwargs_copy['verify'] = False
        return super().send(request, **kwargs_copy)

# Fix Windows cp1252 encoding - use PYTHONUTF8=1 or reconfigure instead of
# TextIOWrapper which conflicts with FastMCP's stdio handling
if sys.platform == 'win32':
    try:
        import io
        if isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if isinstance(sys.stderr, io.TextIOWrapper):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _patch_dns_resolution(sh):
    domain_ip_map = {}
    for domain in sh.available_base_url_list:
        try:
            ip = resolve_domain(domain)
            domain_ip_map[domain] = ip
            logger.info(f"Resolved {domain} -> {ip}")
        except Exception as e:
            logger.warning(f"Failed to resolve {domain}: {e}")
    
    if domain_ip_map:
        adapter = DNSOverHTTPSAdapter(domain_ip_map)
        sh.session.mount("https://", adapter)
        sh.session.mount("http://", adapter)


def create_scihub_instance() -> Any:
    sh: Any = SciHub()
    sh.available_base_url_list = WORKING_SCIHUB_DOMAINS[:]
    sh.timeout = 30
    
    sh.session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Cache-Control': 'max-age=0',
    })
    
    proxy = get_proxy_config()
    if proxy:
        sh.session.proxies.update(proxy)
        logger.info(f"Using proxy: {proxy}")
    
    _patch_dns_resolution(sh)
    
    return sh

def _fetch_single_domain(sh: Any, identifier: str, domain: str) -> dict:
    """Fetch paper from a specific domain without retry logic."""
    from scihub import logger as scihub_logger
    import logging
    from urllib3.exceptions import IncompleteRead
    import re
    
    scihub_logger.setLevel(logging.WARNING)
    url = sh._get_direct_url(identifier)
    
    if url is None:
        raise Exception(f"No direct URL found for {identifier}")
    
    for retry in range(3):
        try:
            res = sh.session.get(url, verify=False, timeout=sh.timeout)
            res.raise_for_status()
            content = res.content
            text = res.text
            
            if res.headers.get('Content-Type', '').find('pdf') == -1 and not content.startswith(b'%PDF'):
                pdf_match = re.search(r'<meta[^>]*name=["\']citation_pdf_url["\'][^>]*content=["\']([^"\']*)["\']', text)
                if pdf_match:
                    pdf_path = pdf_match.group(1)
                    if pdf_path.startswith('/'):
                        pdf_url = f"https://{domain}{pdf_path}"
                    else:
                        pdf_url = pdf_path
                    logger.info(f"Found PDF URL in meta tag: {pdf_url}")
                    pdf_res = sh.session.get(pdf_url, verify=False, timeout=sh.timeout)
                    if pdf_res.status_code == 200 and pdf_res.content.startswith(b'%PDF'):
                        return {
                            'pdf': pdf_res.content,
                            'url': pdf_url,
                            'title': '',
                            'author': '',
                            'year': ''
                        }
                sh._set_captcha_url(url)
                raise Exception('CAPTCHA needed')
            
            return {
                'pdf': content,
                'url': url,
                'title': getattr(sh, '_title', ''),
                'author': getattr(sh, '_author', ''),
                'year': getattr(sh, '_year', '')
            }
        except (IncompleteRead, ConnectionError, ConnectionResetError) as e:
            if retry < 2:
                logger.warning(f"Retry {retry + 1} for {domain}: {type(e).__name__}")
                import time
                time.sleep(1)
            else:
                raise
    
    raise Exception("All retries exhausted")


def search_paper_by_doi(doi: str) -> dict:
    """Search for a paper on Sci-Hub by DOI."""
    sh: Any = create_scihub_instance()
    
    for domain_idx, domain in enumerate(WORKING_SCIHUB_DOMAINS, 1):
        try:
            sh.current_base_url_index = domain_idx - 1
            logger.info(f"Attempt {domain_idx}: Trying {domain} ({sh.base_url})")
            
            url = f"{sh.base_url}{doi}"
            logger.info(f"Requesting: {url}")
            resp = sh.session.get(url, verify=False, timeout=sh.timeout)
            
            if resp.status_code != 200:
                raise Exception(f"HTTP {resp.status_code}")
            
            text = resp.text
            import re
            pdf_match = re.search(r'<meta[^>]*name=["\']citation_pdf_url["\'][^>]*content=["\']([^"\']*)["\']', text)
            
            if pdf_match:
                pdf_path = pdf_match.group(1)
                if pdf_path.startswith('/'):
                    pdf_url = f"https://{domain}{pdf_path}"
                else:
                    pdf_url = pdf_path
                
                logger.info(f"Found PDF URL: {pdf_url}")
                pdf_resp = sh.session.get(pdf_url, verify=False, timeout=sh.timeout)
                
                if pdf_resp.status_code == 200 and pdf_resp.content.startswith(b'%PDF'):
                    logger.info(f"Successfully downloaded PDF ({len(pdf_resp.content)} bytes)")
                    return {
                        'doi': doi,
                        'pdf_url': pdf_url,
                        'status': 'success',
                        'title': '',
                        'author': '',
                        'year': ''
                    }
            
            raise Exception("No valid PDF found")
            
        except Exception as e:
            logger.warning(f"Attempt {domain_idx} with {domain} failed: {type(e).__name__}: {e}")
    
    logger.error(f"All {len(WORKING_SCIHUB_DOMAINS)} domains failed for DOI: {doi}")
    return {
        'doi': doi,
        'status': 'not_found'
    }

def search_paper_by_title(title):
    try:
        url = f"https://api.crossref.org/works?query.title={title}&rows=1"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            if data['message']['items']:
                item = data['message']['items'][0]
                doi = item['DOI']
                result = search_paper_by_doi(doi)
                # Preserve CrossRef metadata since Sci-Hub search returns empty metadata
                if result['status'] == 'success':
                    result['doi'] = doi
                    result.setdefault('title', item.get('title', [''])[0] if isinstance(item.get('title'), list) else item.get('title', ''))
                    result.setdefault('author', ', '.join(
                        f"{a.get('given', '')} {a.get('family', '')}".strip()
                        for a in item.get('author', [])
                    ))
                    result.setdefault('year', str(item.get('published-print', {}).get('date-parts', [[None]])[0][0] or item.get('published-online', {}).get('date-parts', [[None]])[0][0] or ''))
                return result
    except Exception as e:
        logger.error(f"CrossRef search error: {e}")
    
    return {
        'title': title,
        'status': 'not_found'
    }

def search_papers_by_keyword(keyword, num_results=10):
    papers = []
    try:
        url = f"https://api.crossref.org/works?query={keyword}&rows={num_results}"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            for item in data['message']['items']:
                doi = item.get('DOI')
                if doi:
                    result = search_paper_by_doi(doi)
                    if result['status'] == 'success':
                        # Preserve CrossRef metadata since Sci-Hub returns empty metadata
                        result.setdefault('title', item.get('title', [''])[0] if isinstance(item.get('title'), list) else item.get('title', ''))
                        result.setdefault('author', ', '.join(
                            f"{a.get('given', '')} {a.get('family', '')}".strip()
                            for a in item.get('author', [])
                        ))
                        result.setdefault('year', str(item.get('published-print', {}).get('date-parts', [[None]])[0][0] or item.get('published-online', {}).get('date-parts', [[None]])[0][0] or ''))
                        papers.append(result)
    except Exception as e:
        logger.error(f"Search error: {e}")
    
    return papers

def download_paper(pdf_url: str, output_path: str) -> bool:
    sh: Any = create_scihub_instance()
    try:
        response = sh.session.get(pdf_url, verify=False, timeout=sh.timeout)
        response.raise_for_status()
        with open(output_path, 'wb') as f:
            f.write(response.content)
        return True
    except Exception as e:
        logger.error(f"Download error: {e}")
        return False


if __name__ == "__main__":
    print("Sci-Hub \n")

    print("1. Search for a paper by DOI")
    test_doi = "10.1002/jcad.12075" 
    result = search_paper_by_doi(test_doi)
    
    if result['status'] == 'success':
        print(f"Title: {result['title']}")
        print(f"Author: {result['author']}")
        print(f"Year: {result['year']}")
        print(f"PDF URL: {result['pdf_url']}")
        
        # Try to download the paper
        output_file = f"paper_{test_doi.replace('/', '_')}.pdf"
        if download_paper(result['pdf_url'], output_file):
            print(f"Paper downloaded to: {output_file}")
        else:
            print("Failed to download paper")
    else:
        print(f"No paper found for DOI {test_doi}")

    # 2. Title search test
    print("\n2. Search for a paper by title")
    test_title = "Choosing Assessment Instruments for Posttraumatic Stress Disorder Screening and Outcome Research"
    result = search_paper_by_title(test_title)
    
    if result['status'] == 'success':
        print(f"DOI: {result['doi']}")
        print(f"Author: {result['author']}")
        print(f"Year: {result['year']}")
        print(f"PDF URL: {result['pdf_url']}")
    else:
        print(f"No paper found with title '{test_title}'")

    # 3. Keyword search test
    print("\n3. Search for papers by keyword")
    test_keyword = "artificial intelligence medicine 2023"
    papers = search_papers_by_keyword(test_keyword, num_results=3)
    
    for i, paper in enumerate(papers, 1):
        print(f"\nPaper {i}:")
        print(f"Title: {paper['title']}")
        print(f"DOI: {paper['doi']}")
        print(f"Author: {paper['author']}")
        print(f"Year: {paper['year']}")
        if paper.get('pdf_url'):
            print(f"PDF URL: {paper['pdf_url']}")

