#!/usr/bin/env python

import re
import sys
import tempfile
import urllib.parse

import pypandoc

from aider import __version__, urls, utils
from aider.dump import dump  # noqa: F401

aider_user_agent = f"Aider/{__version__} +{urls.website}"

# Playwright is nice because it has a simple way to install dependencies on most
# platforms.


def check_env():
    try:
        from playwright.sync_api import sync_playwright

        has_pip = True
    except ImportError:
        has_pip = False

    try:
        with sync_playwright() as p:
            p.chromium.launch()
            has_chromium = True
    except Exception:
        has_chromium = False

    return has_pip, has_chromium


def has_playwright():
    has_pip, has_chromium = check_env()
    return has_pip and has_chromium


def install_playwright(io):
    has_pip, has_chromium = check_env()
    if has_pip and has_chromium:
        return True

    pip_cmd = utils.get_pip_install(["aider-chat[playwright]"])
    chromium_cmd = "-m playwright install --with-deps chromium"
    chromium_cmd = [sys.executable] + chromium_cmd.split()

    cmds = ""
    if not has_pip:
        cmds += " ".join(pip_cmd) + "\n"
    if not has_chromium:
        cmds += " ".join(chromium_cmd) + "\n"

    text = f"""For the best web scraping, install Playwright:

{cmds}
See {urls.enable_playwright} for more info.
"""

    io.tool_output(text)
    if not io.confirm_ask("Install playwright?", default="y"):
        return

    if not has_pip:
        success, output = utils.run_install(pip_cmd)
        if not success:
            io.tool_error(output)
            return

    success, output = utils.run_install(chromium_cmd)
    if not success:
        io.tool_error(output)
        return

    return True


class InteractiveBrowser:
    """
    Persistent browser session for multi-step interactions.
    Enables 'Computer Use' parity with Claude 3.5 Sonnet.
    """

    _instance = None

    def __init__(self, verify_ssl=True):
        self.verify_ssl = verify_ssl
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    @classmethod
    def get_instance(cls, verify_ssl=True):
        if cls._instance is None:
            cls._instance = cls(verify_ssl=verify_ssl)
        return cls._instance

    def _ensure_browser(self):
        from playwright.sync_api import sync_playwright

        if not self.playwright:
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.launch(headless=True)
            self.context = self.browser.new_context(ignore_https_errors=not self.verify_ssl)
            self.page = self.context.new_page()

    def navigate(self, url):
        self._ensure_browser()
        self.page.goto(url, wait_until="networkidle")
        return self.page.content()

    def click(self, selector):
        self._ensure_browser()
        self.page.click(selector)
        self.page.wait_for_load_state("networkidle")
        return self.page.content()

    def type(self, selector, text):
        self._ensure_browser()
        self.page.fill(selector, text)
        return self.page.content()

    def screenshot(self, path=None):
        self._ensure_browser()
        if not path:
            path = tempfile.mktemp(suffix=".png")
        self.page.screenshot(path=path)
        return path

    def shutdown(self):
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
        InteractiveBrowser._instance = None


class DocCrawler:
    """
    Recursive documentation crawler for semantic indexing.
    Parity with Cursor's '@docs' feature.
    """

    def __init__(self, base_url, max_pages=50, max_depth=3):
        self.base_url = base_url.rstrip("/")
        self.domain = urllib.parse.urlparse(base_url).netloc
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.visited = set()
        self.queue = [(base_url, 0)]
        self.scraper = Scraper()

    def crawl(self):
        """Crawl the site and yield (url, markdown_content)."""
        pages_crawled = 0
        while self.queue and pages_crawled < self.max_pages:
            url, depth = self.queue.pop(0)
            if url in self.visited or depth > self.max_depth:
                continue

            self.visited.add(url)
            pages_crawled += 1

            try:
                content = self.scraper.scrape(url)
                if not content:
                    continue

                yield url, content

                # Extract links for further crawling
                if depth < self.max_depth:
                    links = self._extract_links(url)
                    for link in links:
                        if link not in self.visited:
                            self.queue.append((link, depth + 1))
            except Exception:
                continue

    def _extract_links(self, url):
        """Extract same-domain links from a page."""
        import httpx
        from bs4 import BeautifulSoup

        links = []
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(url)
                if resp.status_code != 200:
                    return []
                soup = BeautifulSoup(resp.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    full_url = urllib.parse.urljoin(url, href)
                    # Stay on same domain and avoid fragments
                    parsed = urllib.parse.urlparse(full_url)
                    if parsed.netloc == self.domain and not parsed.fragment:
                        links.append(full_url.split("#")[0])
        except Exception:
            pass
        return list(set(links))


class Scraper:
    pandoc_available = None
    playwright_available = None
    playwright_instructions_shown = False

    # Public API...
    def __init__(self, print_error=None, playwright_available=None, verify_ssl=True):
        """
        `print_error` - a function to call to print error/debug info.
        `verify_ssl` - if False, disable SSL certificate verification when scraping.
        """
        if print_error:
            self.print_error = print_error
        else:
            self.print_error = print

        self.playwright_available = playwright_available
        self.verify_ssl = verify_ssl

    def scrape(self, url):
        """
        Scrape a url and turn it into readable markdown if it's HTML.
        If it's plain text or non-HTML, return it as-is.

        `url` - the URL to scrape.
        """

        if self.playwright_available:
            content, mime_type = self.scrape_with_playwright(url)
        else:
            content, mime_type = self.scrape_with_httpx(url)

        if not content:
            self.print_error(f"Failed to retrieve content from {url}")
            return None

        # Check if the content is HTML based on MIME type or content
        if (mime_type and mime_type.startswith("text/html")) or (
            mime_type is None and self.looks_like_html(content)
        ):
            self.try_pandoc()
            content = self.html_to_markdown(content)

        return content

    def looks_like_html(self, content):
        """
        Check if the content looks like HTML.
        """
        if isinstance(content, str):
            # Check for common HTML tags
            html_patterns = [
                r"<!DOCTYPE\s+html",
                r"<html",
                r"<head",
                r"<body",
                r"<div",
                r"<p>",
                r"<a\s+href=",
            ]
            return any(re.search(pattern, content, re.IGNORECASE) for pattern in html_patterns)
        return False

    # Internals...
    def scrape_with_playwright(self, url):
        import playwright  # noqa: F401
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except Exception as e:
                self.playwright_available = False
                self.print_error(str(e))
                return None, None

            try:
                context = browser.new_context(ignore_https_errors=not self.verify_ssl)
                page = context.new_page()

                user_agent = page.evaluate("navigator.userAgent")
                user_agent = user_agent.replace("Headless", "")
                user_agent = user_agent.replace("headless", "")
                user_agent += " " + aider_user_agent

                page.set_extra_http_headers({"User-Agent": user_agent})

                response = None
                try:
                    response = page.goto(url, wait_until="networkidle", timeout=5000)
                except PlaywrightTimeoutError:
                    print(f"Page didn't quiesce, scraping content anyway: {url}")
                    response = None
                except PlaywrightError as e:
                    self.print_error(f"Error navigating to {url}: {str(e)}")
                    return None, None

                try:
                    content = page.content()
                    mime_type = None
                    if response:
                        content_type = response.header_value("content-type")
                        if content_type:
                            mime_type = content_type.split(";")[0]
                except PlaywrightError as e:
                    self.print_error(f"Error retrieving page content: {str(e)}")
                    content = None
                    mime_type = None
            finally:
                browser.close()

        return content, mime_type

    def scrape_with_httpx(self, url):
        import httpx

        headers = {"User-Agent": f"Mozilla/5.0 ({aider_user_agent})"}
        try:
            with httpx.Client(
                headers=headers, verify=self.verify_ssl, follow_redirects=True
            ) as client:
                response = client.get(url)
                response.raise_for_status()
                return response.text, response.headers.get("content-type", "").split(";")[0]
        except httpx.HTTPError as http_err:
            self.print_error(f"HTTP error occurred: {http_err}")
        except Exception as err:
            self.print_error(f"An error occurred: {err}")
        return None, None

    def try_pandoc(self):
        if self.pandoc_available:
            return

        try:
            pypandoc.get_pandoc_version()
            self.pandoc_available = True
            return
        except OSError:
            pass

        try:
            pypandoc.download_pandoc(delete_installer=True)
        except Exception as err:
            self.print_error(f"Unable to install pandoc: {err}")
            return

        self.pandoc_available = True

    def html_to_markdown(self, page_source):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(page_source, "html.parser")
        soup = slimdown_html(soup)
        page_source = str(soup)

        if not self.pandoc_available:
            return page_source

        try:
            md = pypandoc.convert_text(page_source, "markdown", format="html")
        except OSError:
            return page_source

        md = re.sub(r"</div>", "      ", md)
        md = re.sub(r"<div>", "     ", md)

        md = re.sub(r"\n\s*\n", "\n\n", md)

        return md


def slimdown_html(soup):
    for svg in soup.find_all("svg"):
        svg.decompose()

    if soup.img:
        soup.img.decompose()

    for tag in soup.find_all(href=lambda x: x and x.startswith("data:")):
        tag.decompose()

    for tag in soup.find_all(src=lambda x: x and x.startswith("data:")):
        tag.decompose()

    for tag in soup.find_all(True):
        for attr in list(tag.attrs):
            if attr != "href":
                tag.attrs.pop(attr, None)

    return soup


def main(url):
    scraper = Scraper(playwright_available=has_playwright())
    content = scraper.scrape(url)
    print(content)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python playw.py <URL>")
        sys.exit(1)
    main(sys.argv[1])
