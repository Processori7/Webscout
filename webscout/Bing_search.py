from bs4 import BeautifulSoup
import requests
from typing import Dict, List, Optional, Union
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote, urlparse, parse_qs
import base64
import urllib3

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class BingS:
    """Bing search class to get search results from bing.com."""

    _executor: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=10)

    def __init__(
        self,
        headers: Optional[Dict[str, str]] = None,
        proxy: Optional[str] = None,
        timeout: Optional[int] = 10,
    ) -> None:
        """Initialize the BingS object."""
        self.proxy: Optional[str] = proxy
        self.headers = headers if headers else {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        self.headers["Referer"] = "https://www.bing.com/"
        self.client = requests.Session()
        self.client.headers.update(self.headers)
        self.client.proxies.update({"http": self.proxy, "https": self.proxy})
        self.timeout = timeout

    def __enter__(self) -> "BingS":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.client.close()

    def _get_url(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, str]] = None,
        data: Optional[Union[Dict[str, str], bytes]] = None,
    ) -> bytes:
        try:
            resp = self.client.request(method, url, params=params, data=data, timeout=self.timeout, verify=False)
        except Exception as ex:
            raise Exception(f"{url} {type(ex).__name__}: {ex}") from ex
        if resp.status_code == 200:
            return resp.content
        raise Exception(f"{resp.url} returned status code {resp.status_code}. {params=} {data=}")

    def extract_text_from_webpage(self, html_content, max_characters=None):
        """Extracts visible text from HTML content using BeautifulSoup."""
        soup = BeautifulSoup(html_content, "html.parser")
        # Remove unwanted tags
        for tag in soup(["script", "style", "header", "footer", "nav"]):
            tag.extract()
        # Get the remaining visible text
        visible_text = soup.get_text(separator=' ', strip=True)
        if max_characters:
            visible_text = visible_text[:max_characters]
        return visible_text

    def search(
        self,
        keywords: str,
        max_results: Optional[int] = 10,
        extract_webpage_text: bool = False,
        max_extract_characters: Optional[int] = 100,
    ) -> List[Dict[str, str]]:
        """Bing text search."""
        assert keywords, "keywords is mandatory"

        results = []
        futures = []
        start = 1
        while len(results) < max_results:
            params = {
                "q": keywords,
                "first": start
            }
            futures.append(self._executor.submit(self._get_url, "GET", "https://www.bing.com/search", params=params))
            start += 10

            for future in as_completed(futures):
                try:
                    resp_content = future.result()
                    soup = BeautifulSoup(resp_content, "html.parser")
                    result_block = soup.select('li.b_algo')

                    if not result_block:
                        break

                    for result in result_block:
                        try:
                            link = result.select_one('h2 a')
                            title = link.text if link else ""
                            url = link['href'] if link else ""
                            abstract = result.select_one('.b_caption p')
                            description = abstract.text if abstract else ""

                            # Remove "WEB" from the beginning of the description if it exists
                            if description.startswith("WEB"):
                                description = description[3:].strip()

                            visible_text = ""
                            if extract_webpage_text:
                                try:
                                    actual_url = self._decode_bing_url(url)
                                    page_content = self._get_url("GET", actual_url)
                                    visible_text = self.extract_text_from_webpage(
                                        page_content, max_characters=max_extract_characters
                                    )
                                except Exception as e:
                                    print(f"Error extracting text from {url}: {e}")

                            results.append({
                                "title": title,
                                "href": url,
                                "abstract": description,
                                "index": len(results),
                                "type": "web",
                                "visible_text": visible_text,
                            })

                            if len(results) >= max_results:
                                return results

                        except Exception as e:
                            print(f"Error extracting result: {e}")

                except Exception as e:
                    print(f"Error fetching URL: {e}")

        return results

    def _decode_bing_url(self, url):
        if 'bing.com/ck/a' in url:
            parsed_url = urlparse(url)
            query_params = parse_qs(parsed_url.query)
            if 'u' in query_params:
                encoded_url = query_params['u'][0]
                return base64.b64decode(encoded_url).decode('utf-8')
        return url

if __name__ == "__main__":
    from rich import print
    searcher = BingS()
    results = searcher.search("Python development tools", max_results=5, extract_webpage_text=True, max_extract_characters=2000)
    for result in results:
        print(result)