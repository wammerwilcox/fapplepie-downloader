import logging
import unittest
from unittest.mock import Mock, patch

from curl_cffi import CurlECode
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
    def test_fapplepie_protocol_error_falls_back_to_http11(self) -> None:
        session = Mock()
        session.codex_supports_impersonate = True
        response = Mock(status_code=200, ok=True)
        session.get.side_effect = [
            curl_requests.exceptions.RequestException(
                "curl: (92) HTTP/2 stream closed with PROTOCOL_ERROR",
                code=CurlECode.HTTP2_STREAM,
            ),
            response,
        ]

        actual = scraper._request_with_retries(
            session,
            "https://fapplepie.com/videos",
            max_attempts=1,
            backoff_seconds=0,
        )

        self.assertIs(actual, response)
        self.assertEqual(session.get.call_count, 2)
        initial_call, fallback_call = session.get.call_args_list
        self.assertEqual(initial_call.kwargs["impersonate"], "chrome")
        self.assertNotIn("http_version", initial_call.kwargs)
        self.assertEqual(fallback_call.kwargs["impersonate"], "chrome")
        self.assertEqual(fallback_call.kwargs["http_version"], "v1")
        self.assertEqual(
            fallback_call.kwargs["proxies"],
            initial_call.kwargs["proxies"],
        )

    def test_non_fapplepie_protocol_error_does_not_fall_back_to_http11(self) -> None:
        session = Mock()
        session.codex_supports_impersonate = True
        session.get.side_effect = curl_requests.exceptions.RequestException(
            "curl: (92) HTTP/2 stream closed with PROTOCOL_ERROR",
            code=CurlECode.HTTP2_STREAM,
        )

        with self.assertRaises(curl_requests.exceptions.RequestException):
            scraper._request_with_retries(
                session,
                "https://cdn.example.com/video.mp4",
                max_attempts=1,
                backoff_seconds=0,
            )

        self.assertEqual(session.get.call_count, 1)
        self.assertNotIn("http_version", session.get.call_args.kwargs)

    def test_other_http2_stream_error_does_not_fall_back_to_http11(self) -> None:
        session = Mock()
        session.codex_supports_impersonate = True
        session.get.side_effect = curl_requests.exceptions.RequestException(
            "curl: (92) HTTP/2 stream closed with INTERNAL_ERROR",
            code=CurlECode.HTTP2_STREAM,
        )

        with self.assertRaises(curl_requests.exceptions.RequestException):
            scraper._request_with_retries(
                session,
                "https://fapplepie.com/videos",
                max_attempts=1,
                backoff_seconds=0,
            )

        self.assertEqual(session.get.call_count, 1)
        self.assertNotIn("http_version", session.get.call_args.kwargs)

    @patch.dict(
        "os.environ",
        {
            "NORDVPN_PROXY": "socks5h://proxy.example:1080",
            "NORDVPN_USER": "proxy-user",
            "NORDVPN_PASS": "proxy-password",
        },
        clear=True,
    )
    def test_retries_remain_on_http11_after_protocol_fallback(self) -> None:
        session = Mock()
        session.codex_supports_impersonate = True
        response = Mock(status_code=200, ok=True)
        session.get.side_effect = [
            curl_requests.exceptions.RequestException(
                "curl: (92) HTTP/2 stream closed with PROTOCOL_ERROR",
                code=CurlECode.HTTP2_STREAM,
            ),
            curl_requests.exceptions.ConnectionError("connection closed"),
            response,
        ]

        with patch.object(scraper.time, "sleep") as sleep_mock:
            actual = scraper._request_with_retries(
                session,
                "https://fapplepie.com/videos",
                max_attempts=2,
                backoff_seconds=0.5,
            )

        self.assertIs(actual, response)
        self.assertEqual(session.get.call_count, 3)
        self.assertNotIn("http_version", session.get.call_args_list[0].kwargs)
        self.assertEqual(
            session.get.call_args_list[1].kwargs["http_version"],
            "v1",
        )
        self.assertEqual(
            session.get.call_args_list[2].kwargs["http_version"],
            "v1",
        )
        sleep_mock.assert_called_once_with(0.5)

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
