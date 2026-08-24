import logging
import unittest
from unittest.mock import Mock, patch

from curl_cffi import requests as curl_requests
import requests

from app import scraper


class ScrapeRequestTests(unittest.TestCase):
    def setUp(self) -> None:
        scraper._get_proxy_settings.cache_clear()
        scraper._get_proxy_scope.cache_clear()

    def tearDown(self) -> None:
        scraper._get_proxy_settings.cache_clear()
        scraper._get_proxy_scope.cache_clear()

    @patch.dict(
        "os.environ",
        {
            "NORDVPN_PROXY": "socks5h://proxy.example:1080",
            "NORDVPN_USER": "proxy-user",
            "NORDVPN_PASS": "proxy-password",
        },
        clear=True,
    )
    def test_fapplepie_request_uses_http11_immediately(self) -> None:
        session = Mock()
        session.codex_supports_impersonate = True
        session.headers = dict(scraper.DEFAULT_SCRAPE_HEADERS)
        response = Mock(status_code=200, ok=True)
        observed_headers = []

        def get(*args, **kwargs):
            observed_headers.append(dict(session.headers))
            return response

        session.get.side_effect = get

        actual = scraper._request_with_retries(
            session,
            "https://fapplepie.com/videos",
            max_attempts=1,
            backoff_seconds=0,
        )

        self.assertIs(actual, response)
        self.assertEqual(session.get.call_count, 1)
        request_call = session.get.call_args
        self.assertEqual(request_call.kwargs["impersonate"], "chrome")
        self.assertEqual(request_call.kwargs["http_version"], "v1")
        self.assertEqual(observed_headers, [scraper.FAPPLEPIE_HTTP11_HEADERS])
        self.assertEqual(session.headers, scraper.DEFAULT_SCRAPE_HEADERS)

    def test_non_fapplepie_request_does_not_force_http11(self) -> None:
        session = Mock()
        session.codex_supports_impersonate = True
        session.headers = dict(scraper.DEFAULT_SCRAPE_HEADERS)
        response = Mock(status_code=200, ok=True)
        session.get.return_value = response

        actual = scraper._request_with_retries(
            session,
            "https://cdn.example.com/video.mp4",
            max_attempts=1,
            backoff_seconds=0,
        )

        self.assertIs(actual, response)
        self.assertEqual(session.get.call_count, 1)
        self.assertNotIn("http_version", session.get.call_args.kwargs)
        self.assertNotIn("impersonate", session.get.call_args.kwargs)

    @patch.dict(
        "os.environ",
        {
            "NORDVPN_PROXY": "socks5h://proxy.example:1080",
            "NORDVPN_USER": "proxy-user",
            "NORDVPN_PASS": "proxy-password",
        },
        clear=True,
    )
    def test_fapplepie_retries_remain_on_http11(self) -> None:
        session = Mock()
        session.codex_supports_impersonate = True
        session.headers = dict(scraper.DEFAULT_SCRAPE_HEADERS)
        response = Mock(status_code=200, ok=True)
        observed_headers = []

        def get(*args, **kwargs):
            observed_headers.append(dict(session.headers))
            if len(observed_headers) == 1:
                raise curl_requests.exceptions.ConnectionError("connection closed")
            return response

        session.get.side_effect = get

        with patch.object(scraper.time, "sleep") as sleep_mock:
            actual = scraper._request_with_retries(
                session,
                "https://fapplepie.com/videos",
                max_attempts=2,
                backoff_seconds=0.5,
            )

        self.assertIs(actual, response)
        self.assertEqual(session.get.call_count, 2)
        self.assertEqual(
            session.get.call_args_list[0].kwargs["http_version"],
            "v1",
        )
        self.assertEqual(
            session.get.call_args_list[1].kwargs["http_version"],
            "v1",
        )
        self.assertEqual(
            observed_headers,
            [
                scraper.FAPPLEPIE_HTTP11_HEADERS,
                scraper.FAPPLEPIE_HTTP11_HEADERS,
            ],
        )
        self.assertEqual(session.headers, scraper.DEFAULT_SCRAPE_HEADERS)
        sleep_mock.assert_called_once_with(0.5)

    @patch.dict(
        "os.environ",
        {
            "NORDVPN_PROXY_POOL": (
                "socks5h://chicago.example:1080,"
                "socks5h://amsterdam.example:1080"
            ),
            "NORDVPN_USER": "proxy-user",
            "NORDVPN_PASS": "proxy-password",
        },
        clear=True,
    )
    def test_proxy_pool_selects_one_sticky_proxy_per_process(self) -> None:
        selected = "socks5h://chicago.example:1080"

        with patch.object(scraper.random, "choice", return_value=selected) as choice:
            proxy_url, proxies = scraper._get_proxy_settings()
            cached_proxy_url, cached_proxies = scraper._get_proxy_settings()

        choice.assert_called_once_with(
            [
                "socks5h://chicago.example:1080",
                "socks5h://amsterdam.example:1080",
            ]
        )
        self.assertEqual(
            proxy_url,
            "socks5h://proxy-user:proxy-password@chicago.example:1080",
        )
        self.assertEqual(proxies, {"http": proxy_url, "https": proxy_url})
        self.assertEqual(cached_proxy_url, proxy_url)
        self.assertEqual(cached_proxies, proxies)

    @patch.dict(
        "os.environ",
        {
            "NORDVPN_PROXY": "socks5h://proxy.example:1080",
            "NORDVPN_USER": "proxy-user",
            "NORDVPN_PASS": "proxy-password",
        },
        clear=True,
    )
    def test_proxy_credentials_are_redacted_from_failure_logs(self) -> None:
        session = Mock()
        session.codex_supports_impersonate = True
        session.headers = dict(scraper.DEFAULT_SCRAPE_HEADERS)
        session.get.side_effect = requests.RequestException(
            "proxy failure via socks5h://proxy-user:proxy-password@proxy.example:1080"
        )

        with self.assertLogs(scraper.logger, level=logging.WARNING) as captured:
            with self.assertRaises(requests.RequestException):
                scraper._request_with_retries(
                    session,
                    "https://fapplepie.com/videos",
                    max_attempts=1,
                    backoff_seconds=0,
                )

        logs = "\n".join(captured.output)
        self.assertNotIn("proxy-user", logs)
        self.assertNotIn("proxy-password", logs)
        self.assertIn("***:***@proxy.example:1080", logs)


if __name__ == "__main__":
    unittest.main()
