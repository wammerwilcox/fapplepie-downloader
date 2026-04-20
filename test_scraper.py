import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent / "app"))
import scraper  # noqa: E402


def make_response(status_code: int, url: str) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response.url = url
    response._content = b"<html></html>"
    response.encoding = "utf-8"
    return response


class ScraperTransportTests(unittest.TestCase):
    def test_proxied_403_retries_direct_and_pins_transport(self) -> None:
        session = Mock()
        session.get.side_effect = [
            make_response(403, "https://fapplepie.com/videos"),
            make_response(200, "https://fapplepie.com/videos"),
            make_response(200, "https://fapplepie.com/videos?page=2"),
        ]
        transport_state = scraper.ScrapeTransportState()

        with patch.object(
            scraper,
            "_proxy_url_for_target",
            return_value="socks5h://proxy.example:1080",
        ):
            response = scraper._request_for_scrape(
                session,
                "https://fapplepie.com/videos",
                max_attempts=1,
                transport_state=transport_state,
            )
            next_response = scraper._request_for_scrape(
                session,
                "https://fapplepie.com/videos?page=2",
                max_attempts=1,
                transport_state=transport_state,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(next_response.status_code, 200)
        self.assertEqual(transport_state.mode, scraper.SCRAPE_TRANSPORT_DIRECT)
        self.assertIsNotNone(session.get.call_args_list[0].kwargs["proxies"])
        self.assertIsNone(session.get.call_args_list[1].kwargs["proxies"])
        self.assertIsNone(session.get.call_args_list[2].kwargs["proxies"])

    def test_proxied_403_does_not_bypass_when_disabled(self) -> None:
        session = Mock()
        session.get.return_value = make_response(403, "https://fapplepie.com/videos")
        transport_state = scraper.ScrapeTransportState()

        with patch.dict("os.environ", {"SCRAPE_DIRECT_FALLBACK_ON_403": "0"}, clear=False):
            with patch.object(
                scraper,
                "_proxy_url_for_target",
                return_value="socks5h://proxy.example:1080",
            ):
                response = scraper._request_for_scrape(
                    session,
                    "https://fapplepie.com/videos",
                    max_attempts=1,
                    transport_state=transport_state,
                )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(transport_state.mode, scraper.SCRAPE_TRANSPORT_CONFIGURED)
        self.assertEqual(session.get.call_count, 1)
        self.assertIsNotNone(session.get.call_args.kwargs["proxies"])

    def test_resolve_working_base_url_reports_403_after_direct_retry(self) -> None:
        session = Mock()
        session.get.side_effect = [
            make_response(403, "https://fapplepie.com/videos"),
            make_response(403, "https://fapplepie.com/videos"),
        ]

        with patch.object(scraper, "_candidate_base_urls", return_value=["https://fapplepie.com/videos"]):
            with patch.object(
                scraper,
                "_proxy_url_for_target",
                return_value="socks5h://proxy.example:1080",
            ):
                with self.assertRaises(requests.RequestException) as raised:
                    scraper._resolve_working_base_url(
                        session=session,
                        base_url="https://fapplepie.com/videos",
                        timeout=10,
                        max_attempts=1,
                        backoff_seconds=0,
                        transport_state=scraper.ScrapeTransportState(),
                    )

        message = str(raised.exception)
        self.assertIn("status=403", message)
        self.assertIn("fallback_attempted=True", message)
        self.assertIn("final_transport=direct", message)

    def test_request_retries_non_http_failures(self) -> None:
        session = Mock()
        session.get.side_effect = [
            requests.ConnectionError("boom"),
            make_response(200, "https://fapplepie.com/videos"),
        ]

        with patch.object(scraper, "_proxy_url_for_target", return_value=None):
            with patch.object(scraper.time, "sleep") as sleep_mock:
                response = scraper._request_with_retries(
                    session,
                    "https://fapplepie.com/videos",
                    max_attempts=2,
                    backoff_seconds=0.5,
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(session.get.call_count, 2)
        sleep_mock.assert_called_once_with(0.5)

    def test_scrape_session_has_browser_headers(self) -> None:
        session = scraper._build_scrape_session()

        self.assertIn("User-Agent", session.headers)
        self.assertIn("Accept", session.headers)
        self.assertIn("Accept-Language", session.headers)
        self.assertIn("Referer", session.headers)
        self.assertIn("Upgrade-Insecure-Requests", session.headers)

    def test_stale_resolved_url_detection_flags_fapplepie_targets(self) -> None:
        self.assertTrue(
            scraper._is_stale_resolved_url(
                "https://fapplepie.com/watch/1vjEwGAb",
                "https://fapplepie.com/watch/1vjEwGAb",
            )
        )
        self.assertTrue(
            scraper._is_stale_resolved_url(
                "https://fapplepie.com/watch/1vjEwGAb",
                "https://fapplepie.com/videos/whatever",
            )
        )
        self.assertFalse(
            scraper._is_stale_resolved_url(
                "https://fapplepie.com/watch/1vjEwGAb",
                "https://www.eporner.com/video-abc/example/",
            )
        )

    def test_resolve_executable_uses_venv_bin_before_path_lookup(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            fake_bin = Path(tmp_dir) / "yt-dlp"
            fake_bin.write_text("#!/bin/sh\nexit 0\n")
            fake_bin.chmod(0o755)

            def fake_path(*args, **kwargs):
                if args == ("/venv/bin",):
                    return Path(tmp_dir)
                return Path(*args, **kwargs)

            with patch.object(scraper, "Path", side_effect=fake_path):
                with patch.object(scraper.shutil, "which", return_value=None):
                    resolved = scraper._resolve_executable("YT_DLP_PATH", "yt-dlp")

        self.assertEqual(resolved, str(fake_bin))

    def test_resolve_executable_rejects_untrusted_docker_override(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            fake_bin = Path(tmp_dir) / "yt-dlp"
            fake_bin.write_text("#!/bin/sh\nexit 0\n")
            fake_bin.chmod(0o755)

            with patch.dict("os.environ", {"RUNNING_IN_DOCKER": "1", "YT_DLP_PATH": str(fake_bin)}):
                with self.assertRaises(FileNotFoundError) as raised:
                    scraper._resolve_executable("YT_DLP_PATH", "yt-dlp")

        self.assertIn("outside trusted container paths", str(raised.exception))

    def test_resolve_executable_rejects_untrusted_docker_path_resolution(self) -> None:
        with patch.dict("os.environ", {"RUNNING_IN_DOCKER": "1"}, clear=False):
            with patch.object(scraper.shutil, "which", return_value="/tmp/yt-dlp"):
                with self.assertRaises(FileNotFoundError) as raised:
                    scraper._resolve_executable("YT_DLP_PATH", "yt-dlp")

        self.assertIn("outside trusted container paths", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
