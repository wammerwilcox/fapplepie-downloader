import io
import subprocess
import sys
import unittest
from contextlib import nullcontext
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
    probe_default_env = {
        "SCRAPE_REQUEST_TIMEOUT_SECONDS": "10",
        "SCRAPE_REQUEST_ATTEMPTS": "3",
        "SCRAPE_REQUEST_BACKOFF_SECONDS": "1",
    }

    def probe_scraper_with_default_env(self, base_url: str) -> scraper.ProbeResult:
        with patch.dict("os.environ", self.probe_default_env, clear=False):
            return scraper.probe_scraper(base_url)

    def test_probe_error_includes_phase_and_message(self) -> None:
        error = scraper.ProbeError("base_url", "no candidates worked")

        self.assertEqual(error.phase, "base_url")
        self.assertEqual(str(error), "base_url: no candidates worked")

    def test_probe_result_formats_success_summary(self) -> None:
        result = scraper.ProbeResult(
            working_base_url="https://fapplepie.com/videos",
            final_base_url="https://www.fapplepie.com/videos",
            video_count=2,
            has_next_page=True,
            sample_url="https://fapplepie.com/watch/abc",
            sample_final_url="https://www.eporner.com/video-abc/example/",
        )

        summary = result.format_success()

        self.assertIn("Probe successful", summary)
        self.assertIn("videos_found=2", summary)
        self.assertIn("has_next_page=True", summary)
        self.assertIn("sample_final_url=https://www.eporner.com/video-abc/example/", summary)

    def test_extract_video_links_from_first_page(self) -> None:
        html = b"""
        <html>
          <body>
            <h3><a href="/watch/abc">One</a></h3>
            <h3><a href="https://fapplepie.com/watch/def">Two</a></h3>
            <a>next \xe2\x80\xba</a>
          </body>
        </html>
        """
        response = make_response(200, "https://www.fapplepie.com/videos")
        response._content = html

        links, has_next_page = scraper._parse_video_links(
            response=response,
            working_origin="https://www.fapplepie.com",
        )

        self.assertEqual(
            links,
            [
                "https://www.fapplepie.com/watch/abc",
                "https://fapplepie.com/watch/def",
            ],
        )
        self.assertTrue(has_next_page)

    def test_extract_video_links_reports_no_next_page(self) -> None:
        response = make_response(200, "https://www.fapplepie.com/videos")
        response._content = b'<h3><a href="/watch/abc">One</a></h3>'

        links, has_next_page = scraper._parse_video_links(
            response=response,
            working_origin="https://www.fapplepie.com",
        )

        self.assertEqual(links, ["https://www.fapplepie.com/watch/abc"])
        self.assertFalse(has_next_page)

    def test_probe_scraper_resolves_one_sample_without_cache_or_output_writes(self) -> None:
        first_page = make_response(200, "https://www.fapplepie.com/videos")
        first_page._content = (
            b'<h3><a href="/watch/abc">One</a></h3><a>next \xe2\x80\xba</a>'
        )
        redirect = make_response(200, "https://www.eporner.com/video-abc/example/")
        session = Mock()
        session.headers = {"User-Agent": "test-agent"}

        with patch.object(
            scraper,
            "_build_scrape_session",
            return_value=nullcontext(session),
        ) as build_session:
            with patch.object(
                scraper,
                "_resolve_working_base_url",
                return_value=("https://www.fapplepie.com/videos", first_page),
            ) as resolve_working_base_url:
                with patch.object(
                    scraper,
                    "_fetch_robots_txt",
                    return_value=None,
                ) as fetch_robots_txt:
                    with patch.object(
                        scraper,
                        "_request_for_scrape",
                        return_value=redirect,
                    ) as request_for_scrape:
                        with patch.dict(
                            "os.environ",
                            self.probe_default_env,
                            clear=False,
                        ):
                            with patch.object(scraper, "load_cache_locked") as load_cache:
                                with patch.object(scraper, "save_cache_locked") as save_cache:
                                    result = scraper.probe_scraper(
                                        "https://fapplepie.com/videos"
                                    )

        self.assertEqual(result.video_count, 1)
        self.assertTrue(result.has_next_page)
        self.assertEqual(result.sample_url, "https://www.fapplepie.com/watch/abc")
        self.assertEqual(
            result.sample_final_url,
            "https://www.eporner.com/video-abc/example/",
        )
        build_session.assert_called_once_with()
        resolve_working_base_url.assert_called_once()
        resolve_kwargs = resolve_working_base_url.call_args.kwargs
        self.assertIs(resolve_kwargs["session"], session)
        self.assertEqual(resolve_kwargs["base_url"], "https://fapplepie.com/videos")
        self.assertEqual(resolve_kwargs["timeout"], 10.0)
        self.assertEqual(resolve_kwargs["max_attempts"], 3)
        self.assertEqual(resolve_kwargs["backoff_seconds"], 1.0)
        transport_state = resolve_kwargs["transport_state"]
        self.assertIsInstance(transport_state, scraper.ScrapeTransportState)

        fetch_robots_txt.assert_called_once()
        fetch_args = fetch_robots_txt.call_args.args
        fetch_kwargs = fetch_robots_txt.call_args.kwargs
        self.assertIs(fetch_args[0], session)
        self.assertEqual(fetch_args[1], "https://www.fapplepie.com/videos")
        self.assertEqual(fetch_kwargs["timeout"], 10.0)
        self.assertEqual(fetch_kwargs["max_attempts"], 3)
        self.assertEqual(fetch_kwargs["backoff_seconds"], 1.0)
        self.assertIs(fetch_kwargs["transport_state"], transport_state)

        request_for_scrape.assert_called_once()
        request_args = request_for_scrape.call_args.args
        request_kwargs = request_for_scrape.call_args.kwargs
        self.assertIs(request_args[0], session)
        self.assertEqual(request_args[1], "https://www.fapplepie.com/watch/abc")
        self.assertEqual(request_kwargs["timeout"], 10.0)
        self.assertTrue(request_kwargs["allow_redirects"])
        self.assertEqual(request_kwargs["max_attempts"], 3)
        self.assertEqual(request_kwargs["backoff_seconds"], 1.0)
        self.assertIs(request_kwargs["transport_state"], transport_state)
        load_cache.assert_not_called()
        save_cache.assert_not_called()

    def test_probe_scraper_reports_base_url_failure(self) -> None:
        session = Mock()
        session.headers = {"User-Agent": "test-agent"}

        with patch.object(
            scraper,
            "_build_scrape_session",
            return_value=nullcontext(session),
        ):
            with patch.object(
                scraper,
                "_resolve_working_base_url",
                side_effect=requests.RequestException("blocked"),
            ):
                with self.assertRaises(scraper.ProbeError) as raised:
                    self.probe_scraper_with_default_env(
                        "https://fapplepie.com/videos"
                    )

        self.assertEqual(raised.exception.phase, "base_url")

    def test_probe_scraper_reports_first_page_parse_failure(self) -> None:
        first_page = make_response(200, "https://www.fapplepie.com/videos")
        first_page._content = b"<html></html>"
        session = Mock()
        session.headers = {"User-Agent": "test-agent"}

        with patch.object(
            scraper,
            "_build_scrape_session",
            return_value=nullcontext(session),
        ):
            with patch.object(
                scraper,
                "_resolve_working_base_url",
                return_value=("https://www.fapplepie.com/videos", first_page),
            ):
                with patch.object(scraper, "_fetch_robots_txt", return_value=None):
                    with self.assertRaises(scraper.ProbeError) as raised:
                        self.probe_scraper_with_default_env(
                            "https://fapplepie.com/videos"
                        )

        self.assertEqual(raised.exception.phase, "first_page_parse")

    def test_probe_scraper_reports_sample_redirect_failure(self) -> None:
        first_page = make_response(200, "https://www.fapplepie.com/videos")
        first_page._content = b'<h3><a href="/watch/abc">One</a></h3>'
        session = Mock()
        session.headers = {"User-Agent": "test-agent"}

        with patch.object(
            scraper,
            "_build_scrape_session",
            return_value=nullcontext(session),
        ):
            with patch.object(
                scraper,
                "_resolve_working_base_url",
                return_value=("https://www.fapplepie.com/videos", first_page),
            ):
                with patch.object(scraper, "_fetch_robots_txt", return_value=None):
                    with patch.object(
                        scraper,
                        "_request_for_scrape",
                        side_effect=requests.ConnectionError("redirect blocked"),
                    ):
                        with self.assertRaises(scraper.ProbeError) as raised:
                            self.probe_scraper_with_default_env(
                                "https://fapplepie.com/videos"
                            )

        self.assertEqual(raised.exception.phase, "sample_redirect")

    def test_probe_scraper_reports_robots_failure(self) -> None:
        first_page = make_response(200, "https://www.fapplepie.com/videos")
        first_page._content = b'<h3><a href="/watch/abc">One</a></h3>'
        session = Mock()
        session.headers = {"User-Agent": "test-agent"}

        with patch.object(
            scraper,
            "_build_scrape_session",
            return_value=nullcontext(session),
        ):
            with patch.object(
                scraper,
                "_resolve_working_base_url",
                return_value=("https://www.fapplepie.com/videos", first_page),
            ):
                with patch.object(
                    scraper,
                    "_fetch_robots_txt",
                    return_value="User-agent: *\nDisallow: /videos",
                ):
                    with self.assertRaises(scraper.ProbeError) as raised:
                        self.probe_scraper_with_default_env(
                            "https://fapplepie.com/videos"
                        )

        self.assertEqual(raised.exception.phase, "robots")

    def test_sleep_with_jitter_uses_base_plus_random_jitter(self) -> None:
        with patch.object(scraper.random, "uniform", return_value=0.75) as uniform:
            with patch.object(scraper.time, "sleep") as sleep_mock:
                scraper._sleep_with_jitter(
                    base_seconds=1.0,
                    jitter_seconds=2.0,
                    reason="test delay",
                )

        uniform.assert_called_once_with(0, 2.0)
        sleep_mock.assert_called_once_with(1.75)

    def test_sleep_with_jitter_skips_zero_total_delay(self) -> None:
        with patch.object(scraper.random, "uniform") as uniform:
            with patch.object(scraper.time, "sleep") as sleep_mock:
                scraper._sleep_with_jitter(
                    base_seconds=0,
                    jitter_seconds=0,
                    reason="test delay",
                )

        uniform.assert_not_called()
        sleep_mock.assert_not_called()

    def test_cli_start_jitter_delays_only_scheduled_actions(self) -> None:
        result = scraper.ProbeResult(
            working_base_url="https://fapplepie.com/videos",
            final_base_url="https://www.fapplepie.com/videos",
            video_count=1,
            has_next_page=False,
            sample_url="https://fapplepie.com/watch/abc",
            sample_final_url="https://www.eporner.com/video-abc/example/",
        )

        with patch.object(scraper, "_get_proxy_settings", return_value=(None, None)):
            with patch.object(scraper, "_log_proxy_self_check"):
                with patch.object(scraper, "_sleep_with_jitter") as sleep_with_jitter:
                    with patch.object(scraper, "scrape_videos") as scrape_videos:
                        with patch.object(scraper, "download_videos"):
                            with patch.dict(
                                "os.environ",
                                {
                                    "SCRAPE_START_DELAY_SECONDS": "5",
                                    "SCRAPE_START_DELAY_JITTER_SECONDS": "10",
                                },
                                clear=False,
                            ):
                                scraper.main(["--scheduled", "--scrape"])
                                scraper.main(["--scrape"])

                    with patch.object(scraper, "probe_scraper", return_value=result):
                        scraper.main(["--probe"])

        sleep_with_jitter.assert_called_once_with(
            base_seconds=5.0,
            jitter_seconds=10.0,
            reason="scrape start delay",
        )
        self.assertEqual(scrape_videos.call_count, 2)

    def test_cron_marks_daily_download_run_as_scheduled(self) -> None:
        script_path = Path(__file__).resolve().parent / "app" / "daily_download.sh"
        entrypoint_path = Path(__file__).resolve().parent / "app" / "entrypoint.sh"

        daily_result = subprocess.run(
            ["bash", "-n", str(script_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        entrypoint_result = subprocess.run(
            ["bash", "-n", str(entrypoint_path)],
            capture_output=True,
            text=True,
            check=False,
        )

        daily_text = script_path.read_text()
        entrypoint_text = entrypoint_path.read_text()

        self.assertEqual(daily_result.returncode, 0, daily_result.stderr)
        self.assertEqual(entrypoint_result.returncode, 0, entrypoint_result.stderr)
        self.assertIn("APPLY_SCHEDULED_START_JITTER", daily_text)
        self.assertIn("SCRAPER_ARGS=(--scheduled", daily_text)
        self.assertIn('2>&1 | tee -a "${LOG_FILE}"', daily_text)
        self.assertIn("SCRAPER_EXIT_CODE=${PIPESTATUS[0]}", daily_text)
        self.assertIn("APPLY_SCHEDULED_START_JITTER=1 /app/daily_download.sh", entrypoint_text)

    def test_cli_probe_calls_probe_scraper_and_exits_successfully(self) -> None:
        result = scraper.ProbeResult(
            working_base_url="https://fapplepie.com/videos",
            final_base_url="https://www.fapplepie.com/videos",
            video_count=1,
            has_next_page=False,
            sample_url="https://fapplepie.com/watch/abc",
            sample_final_url="https://www.eporner.com/video-abc/example/",
        )

        with patch.object(scraper, "_get_proxy_settings", return_value=(None, None)):
            with patch.object(scraper, "_log_proxy_self_check"):
                with patch.object(
                    scraper,
                    "probe_scraper",
                    return_value=result,
                ) as probe_scraper:
                    with patch.object(scraper, "scrape_videos") as scrape_videos:
                        with patch.object(scraper, "download_videos") as download_videos:
                            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                                with patch("sys.stderr", new_callable=io.StringIO) as stderr:
                                    exit_code = scraper.main(["--probe"])

        self.assertEqual(exit_code, 0)
        probe_scraper.assert_called_once_with("https://fapplepie.com/videos")
        scrape_videos.assert_not_called()
        download_videos.assert_not_called()
        self.assertIn(result.format_success(), stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")

    def test_cli_probe_failure_exits_nonzero(self) -> None:
        error = scraper.ProbeError("base_url", "blocked")

        with patch.object(scraper, "_get_proxy_settings", return_value=(None, None)):
            with patch.object(scraper, "_log_proxy_self_check"):
                with patch.object(
                    scraper,
                    "probe_scraper",
                    side_effect=error,
                ) as probe_scraper:
                    with patch.object(scraper, "scrape_videos") as scrape_videos:
                        with patch.object(scraper, "download_videos") as download_videos:
                            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                                with patch("sys.stderr", new_callable=io.StringIO) as stderr:
                                    exit_code = scraper.main(["--probe"])

        self.assertEqual(exit_code, 4)
        probe_scraper.assert_called_once_with("https://fapplepie.com/videos")
        scrape_videos.assert_not_called()
        download_videos.assert_not_called()
        self.assertEqual(stdout.getvalue(), f"Fapplepie Downloader v{scraper.__version__}\n")
        self.assertEqual(stderr.getvalue(), f"Probe failed: {error}\n")

    def test_scrape_videos_paginates_after_malformed_h3_links(self) -> None:
        first_response = make_response(200, "https://www.fapplepie.com/videos")
        first_response._content = b"<h3><a>Broken</a></h3><a>next \xe2\x80\xba</a>"
        second_response = make_response(200, "https://www.fapplepie.com/videos?page=2")
        second_response._content = b'<h3><a href="/watch/abc">One</a></h3>'
        session = Mock()
        cache = {
            "resolved_urls": {
                "https://www.fapplepie.com/watch/abc": (
                    "https://www.eporner.com/video-abc/example/"
                ),
            },
            "downloaded_urls": [],
        }

        with TemporaryDirectory() as tmp_dir:
            with patch.object(scraper, "BASE_DIR", Path(tmp_dir)):
                with patch.object(scraper, "load_cache_locked", return_value=cache):
                    with patch.object(scraper, "save_cache_locked"):
                        with patch.object(
                            scraper,
                            "_build_scrape_session",
                            return_value=nullcontext(session),
                        ):
                            session.headers = {"User-Agent": "test-agent"}
                            with patch.object(
                                scraper,
                                "_resolve_working_base_url",
                                return_value=(
                                    "https://www.fapplepie.com/videos",
                                    first_response,
                                ),
                            ):
                                with patch.object(
                                    scraper,
                                    "_fetch_robots_txt",
                                    return_value=None,
                                ):
                                    with patch.object(
                                        scraper,
                                        "_request_for_scrape",
                                        return_value=second_response,
                                    ) as request_mock:
                                        with patch.dict(
                                            "os.environ",
                                            {"SCRAPE_DELAY_SECONDS": "0"},
                                            clear=False,
                                        ):
                                            with patch(
                                                "sys.stdout",
                                                new_callable=io.StringIO,
                                            ) as stdout:
                                                scraper.scrape_videos(
                                                    "https://www.fapplepie.com/videos",
                                                    "video_urls.txt",
                                                )

        output = stdout.getvalue()
        self.assertIn("  Found 0 videos on page 1", output)
        self.assertIn("Fetching page 2: https://www.fapplepie.com/videos?page=2", output)
        request_mock.assert_called_once()

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

    def test_scrape_videos_applies_jittered_page_and_redirect_delays(self) -> None:
        first_response = make_response(200, "https://www.fapplepie.com/videos")
        first_response._content = b'<h3><a href="/watch/abc">One</a></h3><a>next \xe2\x80\xba</a>'
        second_response = make_response(200, "https://www.fapplepie.com/videos?page=2")
        second_response._content = b'<h3><a href="/watch/def">Two</a></h3>'
        first_redirect = make_response(200, "https://www.eporner.com/video-abc/example/")
        second_redirect = make_response(200, "https://www.eporner.com/video-def/example/")
        session = Mock()
        session.headers = {"User-Agent": "test-agent"}
        cache = {"resolved_urls": {}, "downloaded_urls": []}

        with TemporaryDirectory() as tmp_dir:
            with patch.object(scraper, "BASE_DIR", Path(tmp_dir)):
                with patch.object(scraper, "load_cache_locked", return_value=cache):
                    with patch.object(scraper, "save_cache_locked"):
                        with patch.object(
                            scraper,
                            "_build_scrape_session",
                            return_value=nullcontext(session),
                        ):
                            with patch.object(
                                scraper,
                                "_resolve_working_base_url",
                                return_value=(
                                    "https://www.fapplepie.com/videos",
                                    first_response,
                                ),
                            ):
                                with patch.object(
                                    scraper,
                                    "_fetch_robots_txt",
                                    return_value=None,
                                ):
                                    with patch.object(
                                        scraper,
                                        "_request_for_scrape",
                                        side_effect=[
                                            second_response,
                                            first_redirect,
                                            second_redirect,
                                        ],
                                    ):
                                        with patch.object(
                                            scraper,
                                            "_sleep_with_jitter",
                                        ) as sleep_with_jitter:
                                            with patch.dict(
                                                "os.environ",
                                                {
                                                    "SCRAPE_DELAY_SECONDS": "1",
                                                    "SCRAPE_DELAY_JITTER_SECONDS": "2",
                                                    "SCRAPE_REDIRECT_DELAY_SECONDS": "3",
                                                    "SCRAPE_REDIRECT_DELAY_JITTER_SECONDS": "4",
                                                },
                                                clear=False,
                                            ):
                                                scraper.scrape_videos(
                                                    "https://www.fapplepie.com/videos",
                                                    "video_urls.txt",
                                                )

        self.assertEqual(
            sleep_with_jitter.call_args_list,
            [
                unittest.mock.call(
                    base_seconds=1.0,
                    jitter_seconds=2.0,
                    reason="next page delay",
                ),
                unittest.mock.call(
                    base_seconds=3.0,
                    jitter_seconds=4.0,
                    reason="redirect resolution delay",
                ),
            ],
        )

    def test_scrape_videos_walks_redirects_when_followed_response_hides_intermediate_target(self) -> None:
        first_response = make_response(200, "https://www.fapplepie.com/videos")
        first_response._content = b'<h3><a href="/watch/redtube-login">One</a></h3>'
        followed_response = make_response(200, "https://www.redtube.com/login")
        fapplepie_redirect = make_response(
            302,
            "https://www.fapplepie.com/watch/redtube-login",
        )
        fapplepie_redirect.headers["Location"] = "https://www.redtube.com/40157"
        redtube_login_redirect = make_response(302, "https://www.redtube.com/40157")
        redtube_login_redirect.headers["Location"] = "https://www.redtube.com/login"
        session = Mock()
        session.headers = {"User-Agent": "test-agent"}
        cache = {"resolved_urls": {}, "downloaded_urls": []}

        def request_for_scrape(*args, **kwargs):
            url = args[1]
            if kwargs["allow_redirects"]:
                self.assertEqual(url, "https://www.fapplepie.com/watch/redtube-login")
                return followed_response
            if url == "https://www.fapplepie.com/watch/redtube-login":
                return fapplepie_redirect
            if url == "https://www.redtube.com/40157":
                return redtube_login_redirect
            self.fail(f"unexpected redirect request: {url}")

        with TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            output_path = base_dir / "video_urls.txt"
            with patch.object(scraper, "BASE_DIR", base_dir):
                with patch.object(scraper, "load_cache_locked", return_value=cache):
                    with patch.object(scraper, "save_cache_locked"):
                        with patch.object(
                            scraper,
                            "_build_scrape_session",
                            return_value=nullcontext(session),
                        ):
                            with patch.object(
                                scraper,
                                "_resolve_working_base_url",
                                return_value=(
                                    "https://www.fapplepie.com/videos",
                                    first_response,
                                ),
                            ):
                                with patch.object(
                                    scraper,
                                    "_fetch_robots_txt",
                                    return_value=None,
                                ):
                                    with patch.object(
                                        scraper,
                                        "_request_for_scrape",
                                        side_effect=request_for_scrape,
                                    ):
                                        scraper.scrape_videos(
                                            "https://www.fapplepie.com/videos",
                                            "video_urls.txt",
                                        )

            written_urls = output_path.read_text().splitlines()

        self.assertEqual(written_urls, ["https://www.redtube.com/40157"])
        self.assertEqual(
            cache["resolved_urls"]["https://www.fapplepie.com/watch/redtube-login"],
            "https://www.redtube.com/40157",
        )

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

    @unittest.skipIf(scraper.curl_requests is None, "curl_cffi is not installed")
    def test_request_retries_curl_cffi_failures(self) -> None:
        session = Mock()
        session.codex_supports_impersonate = True
        session.get.side_effect = [
            scraper.curl_requests.exceptions.ConnectionError("boom"),
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
        self.assertIn("Chrome/137.0.0.0", session.headers["User-Agent"])

    def test_curl_cffi_scrape_session_uses_chrome_impersonation_for_fapplepie(self) -> None:
        session = Mock()
        session.get.return_value = make_response(200, "https://fapplepie.com/videos")
        session.codex_supports_impersonate = True

        with patch.object(scraper, "_proxy_url_for_target", return_value=None):
            scraper._request_with_retries(
                session,
                "https://fapplepie.com/videos",
                max_attempts=1,
            )

        self.assertEqual(session.get.call_args.kwargs["impersonate"], "chrome")

    def test_impersonation_is_not_sent_to_standard_requests_sessions(self) -> None:
        session = Mock()
        session.get.return_value = make_response(200, "https://example.com/")

        with patch.object(scraper, "_proxy_url_for_target", return_value=None):
            scraper._request_with_retries(
                session,
                "https://example.com/",
                max_attempts=1,
            )

        self.assertNotIn("impersonate", session.get.call_args.kwargs)

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

    def test_stale_resolved_url_detection_flags_bad_login_and_root_targets(self) -> None:
        self.assertTrue(
            scraper._is_stale_resolved_url(
                "https://fapplepie.com/watch/JvzZJXvG",
                "https://www.redtube.com/login",
            )
        )
        self.assertTrue(
            scraper._is_stale_resolved_url(
                "https://fapplepie.com/watch/gV5OjMAd",
                "https://www.pornhub.com/",
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

    def test_proxy_download_domains_route_selected_hosts_through_proxy(self) -> None:
        scraper._get_proxy_settings.cache_clear()
        scraper._get_proxy_scope.cache_clear()
        try:
            with patch.dict(
                "os.environ",
                {
                    "NORDVPN_PROXY": "socks5h://proxy.example:1080",
                    "NORDVPN_PROXY_SCOPE": "fapplepie",
                    "NORDVPN_PROXY_DOWNLOAD_DOMAINS": "xhamster.com",
                },
                clear=False,
            ):
                self.assertEqual(
                    scraper._proxy_url_for_target(
                        "https://xhamster.com/videos/cake-on-cake-xhNrd5M",
                    ),
                    "socks5h://proxy.example:1080",
                )
                self.assertEqual(
                    scraper._proxy_url_for_target(
                        "https://www.xhamster.com/videos/cake-on-cake-xhNrd5M",
                    ),
                    "socks5h://proxy.example:1080",
                )
                self.assertEqual(
                    scraper._proxy_url_for_target(
                        "https://de.xhamster.com/videos/cake-on-cake-xhNrd5M",
                    ),
                    "socks5h://proxy.example:1080",
                )
                self.assertIsNone(
                    scraper._proxy_url_for_target(
                        "https://www.youtube.com/watch?v=abc123",
                    )
                )
        finally:
            scraper._get_proxy_settings.cache_clear()
            scraper._get_proxy_scope.cache_clear()

    def test_download_videos_uses_selected_proxy_for_url_file_entry(self) -> None:
        scraper._get_proxy_settings.cache_clear()
        scraper._get_proxy_scope.cache_clear()
        url = "https://www.pornhub.com/view_video.php?viewkey=ph5b4a3c40922a9"
        with TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            urls_file = base_dir / "video_urls.txt"
            output_dir = base_dir / "downloads"
            urls_file.write_text(url + "\n")

            with patch.object(scraper, "BASE_DIR", base_dir):
                with patch.object(scraper, "load_cache_locked", return_value={"downloaded_urls": []}):
                    with patch.object(scraper, "save_cache_locked"):
                        with patch.object(scraper, "_resolve_executable") as resolve_executable:
                            resolve_executable.side_effect = [
                                "/venv/bin/yt-dlp",
                                "/usr/bin/aria2c",
                            ]
                            with patch.object(scraper, "_log_binary_version"):
                                with patch.object(scraper, "_running_in_docker", return_value=True):
                                    with patch.object(
                                        scraper.subprocess,
                                        "run",
                                        return_value=subprocess.CompletedProcess(
                                            args=[],
                                            returncode=0,
                                            stdout="",
                                            stderr="",
                                        ),
                                    ) as run:
                                        with patch.dict(
                                            "os.environ",
                                            {
                                                "NORDVPN_PROXY": "socks5h://proxy.example:1080",
                                                "NORDVPN_PROXY_SCOPE": "fapplepie",
                                                "NORDVPN_PROXY_DOWNLOAD_DOMAINS": "pornhub.com",
                                            },
                                            clear=False,
                                        ):
                                            scraper.download_videos(
                                                "video_urls.txt",
                                                str(output_dir),
                                            )

        cmd = run.call_args.args[0]
        self.assertIn("--proxy", cmd)
        self.assertIn("socks5h://proxy.example:1080", cmd)
        self.assertNotIn("--external-downloader", cmd)
        self.assertEqual(cmd[-1], url)
        scraper._get_proxy_settings.cache_clear()
        scraper._get_proxy_scope.cache_clear()

    def test_build_yt_dlp_command_includes_cookie_file_and_js_runtime(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            cookie_file = Path(tmp_dir) / "youtube.cookies.txt"
            cookie_file.write_text("# Netscape HTTP Cookie File\n")

            with patch.dict(
                "os.environ",
                {
                    "YT_DLP_COOKIES_FILE": str(cookie_file),
                    "YT_DLP_JS_RUNTIMES": "deno",
                },
                clear=False,
            ):
                cmd = scraper._build_yt_dlp_command(
                    yt_dlp_path="/venv/bin/yt-dlp",
                    aria2c_path="/usr/bin/aria2c",
                    output_template="/app/downloads/%(title)s.%(ext)s",
                    url="https://www.youtube.com/watch?v=abc123",
                    proxy_url=None,
                    use_aria2=True,
                )

        self.assertIn("--cookies", cmd)
        self.assertIn(str(cookie_file), cmd)
        self.assertIn("--js-runtimes", cmd)
        self.assertIn("deno", cmd)

    def test_build_yt_dlp_command_rejects_multiple_cookie_sources(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            cookie_file = Path(tmp_dir) / "youtube.cookies.txt"
            cookie_file.write_text("# Netscape HTTP Cookie File\n")

            with patch.dict(
                "os.environ",
                {
                    "YT_DLP_COOKIES_FILE": str(cookie_file),
                    "YT_DLP_COOKIES_FROM_BROWSER": "firefox",
                },
                clear=False,
            ):
                with self.assertRaises(ValueError) as raised:
                    scraper._build_yt_dlp_command(
                        yt_dlp_path="/venv/bin/yt-dlp",
                        aria2c_path="/usr/bin/aria2c",
                        output_template="/app/downloads/%(title)s.%(ext)s",
                        url="https://www.youtube.com/watch?v=abc123",
                        proxy_url=None,
                        use_aria2=True,
                    )

        self.assertIn("only one cookie source", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
