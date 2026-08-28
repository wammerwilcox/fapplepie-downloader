# Probe Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `--probe` mode that validates the production-working 1.1.0 scrape path without writing URL/cache state or downloading media.

**Architecture:** Keep the single-file app structure. Extract small helper functions from `scrape_videos` for first-page parsing and one sample redirect resolution, then build `probe_scraper()` on top of the same session, proxy, retry, robots, and transport logic used by the full scraper.

**Tech Stack:** Python 3.11+, `requests`, `curl_cffi`, BeautifulSoup, `unittest`/`pytest`, Docker Compose docs.

---

## File Map

- Modify `app/scraper.py`
  - Add `ProbeError` and `ProbeResult`.
  - Extract first-page link parsing into reusable helpers.
  - Add `probe_scraper(base_url: str) -> ProbeResult`.
  - Add `--probe` CLI dispatch.
- Modify `test_scraper.py`
  - Add probe unit tests using mocked sessions/responses.
  - Add CLI dispatch test using `runpy.run_path`.
- Modify `README.md`
  - Add a short probe-mode usage example.
- Modify `docs/DOCKER_SETUP.md`
  - Add Docker Compose / `docker exec` probe examples.

## Task 1: Probe Data Types

**Files:**
- Modify: `app/scraper.py`
- Test: `test_scraper.py`

- [ ] **Step 1: Write failing tests for probe errors and result shape**

Append these tests inside `ScraperTransportTests` in `test_scraper.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
/private/tmp/fapplepie-test-venv/bin/python -m unittest \
  test_scraper.ScraperTransportTests.test_probe_error_includes_phase_and_message \
  test_scraper.ScraperTransportTests.test_probe_result_formats_success_summary
```

Expected: fail with `AttributeError` for missing `ProbeError` / `ProbeResult`.

- [ ] **Step 3: Implement data types**

In `app/scraper.py`, update imports:

```python
from dataclasses import dataclass
```

Add below `ScrapeTransportState`:

```python
class ProbeError(Exception):
    """Probe failure annotated with the scrape phase that failed."""

    def __init__(self, phase: str, message: str):
        super().__init__(f"{phase}: {message}")
        self.phase = phase


@dataclass
class ProbeResult:
    working_base_url: str
    final_base_url: str
    video_count: int
    has_next_page: bool
    sample_url: str
    sample_final_url: str

    def format_success(self) -> str:
        return (
            "Probe successful: "
            f"working_base_url={self.working_base_url} "
            f"final_base_url={self.final_base_url} "
            f"videos_found={self.video_count} "
            f"has_next_page={self.has_next_page} "
            f"sample_url={self.sample_url} "
            f"sample_final_url={self.sample_final_url}"
        )
```

- [ ] **Step 4: Run tests to verify pass**

Run the same command from Step 2.

Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/scraper.py test_scraper.py
git commit -m "feat: add probe result types"
```

## Task 2: First Page Parsing Helpers

**Files:**
- Modify: `app/scraper.py`
- Test: `test_scraper.py`

- [ ] **Step 1: Write failing parser tests**

Add these tests:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
/private/tmp/fapplepie-test-venv/bin/python -m unittest \
  test_scraper.ScraperTransportTests.test_extract_video_links_from_first_page \
  test_scraper.ScraperTransportTests.test_extract_video_links_reports_no_next_page
```

Expected: fail with `AttributeError` for `_parse_video_links`.

- [ ] **Step 3: Implement parser helper**

Add near `_robots_disallow`:

```python
def _parse_video_links(response, working_origin: str) -> tuple[list[str], bool]:
    soup = BeautifulSoup(response.content, 'html.parser')
    video_urls: list[str] = []

    for h3 in soup.find_all('h3'):
        link = h3.find('a')
        if link and link.get('href'):
            full_url = link['href']
            if not full_url.startswith('http'):
                full_url = working_origin + full_url
            video_urls.append(full_url)

    has_next_page = soup.find('a', string='next ›') is not None
    return video_urls, has_next_page
```

- [ ] **Step 4: Reuse helper in `scrape_videos`**

Replace the inline BeautifulSoup h3 parsing block in `scrape_videos` with:

```python
                page_video_urls, has_next_page = _parse_video_links(
                    response,
                    working_origin,
                )

                if not page_video_urls:
                    print(f"No videos found on page {page}. Stopping pagination.")
                    break

                all_video_urls.extend(page_video_urls)
                page_video_count = len(page_video_urls)

                print(f"  Found {page_video_count} videos on page {page}")

                if not has_next_page:
                    print(f"No next page link found. Stopping pagination.")
                    break
```

- [ ] **Step 5: Run targeted and existing parser-adjacent tests**

Run:

```bash
/private/tmp/fapplepie-test-venv/bin/python -m unittest \
  test_scraper.ScraperTransportTests.test_extract_video_links_from_first_page \
  test_scraper.ScraperTransportTests.test_extract_video_links_reports_no_next_page \
  test_scraper.ScraperTransportTests.test_stale_resolved_url_detection_flags_fapplepie_targets
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add app/scraper.py test_scraper.py
git commit -m "refactor: extract scrape link parsing"
```

## Task 3: Probe Workflow

**Files:**
- Modify: `app/scraper.py`
- Test: `test_scraper.py`

- [ ] **Step 1: Write failing success test**

Add this test:

```python
    def test_probe_scraper_resolves_one_sample_without_cache_or_output_writes(self) -> None:
        first_page = make_response(200, "https://www.fapplepie.com/videos")
        first_page._content = b'<h3><a href="/watch/abc">One</a></h3><a>next \xe2\x80\xba</a>'
        redirect = make_response(200, "https://www.eporner.com/video-abc/example/")
        session = Mock()
        session.headers = {"User-Agent": "test-agent"}

        with patch.object(scraper, "_build_scrape_session") as build_session:
            build_session.return_value.__enter__.return_value = session
            build_session.return_value.__exit__.return_value = None
            with patch.object(
                scraper,
                "_resolve_working_base_url",
                return_value=("https://www.fapplepie.com/videos", first_page),
            ):
                with patch.object(scraper, "_fetch_robots_txt", return_value=None):
                    with patch.object(scraper, "_request_for_scrape", return_value=redirect):
                        with patch.object(scraper, "load_cache_locked") as load_cache:
                            with patch.object(scraper, "save_cache_locked") as save_cache:
                                result = scraper.probe_scraper("https://fapplepie.com/videos")

        self.assertEqual(result.video_count, 1)
        self.assertTrue(result.has_next_page)
        self.assertEqual(result.sample_url, "https://www.fapplepie.com/watch/abc")
        self.assertEqual(result.sample_final_url, "https://www.eporner.com/video-abc/example/")
        load_cache.assert_not_called()
        save_cache.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
/private/tmp/fapplepie-test-venv/bin/python -m unittest \
  test_scraper.ScraperTransportTests.test_probe_scraper_resolves_one_sample_without_cache_or_output_writes
```

Expected: fail with `AttributeError` for `probe_scraper`.

- [ ] **Step 3: Implement `probe_scraper`**

Add near `scrape_videos`:

```python
def probe_scraper(base_url: str) -> ProbeResult:
    request_timeout = float(os.environ.get("SCRAPE_REQUEST_TIMEOUT_SECONDS", "10"))
    request_attempts = int(os.environ.get("SCRAPE_REQUEST_ATTEMPTS", "3"))
    retry_backoff = float(os.environ.get("SCRAPE_REQUEST_BACKOFF_SECONDS", "1"))
    transport_state = ScrapeTransportState()

    with _build_scrape_session() as session:
        try:
            working_base_url, first_page_response = _resolve_working_base_url(
                session=session,
                base_url=base_url,
                timeout=request_timeout,
                max_attempts=request_attempts,
                backoff_seconds=retry_backoff,
                transport_state=transport_state,
            )
        except SCRAPE_REQUEST_EXCEPTIONS as exc:
            raise ProbeError("base_url", str(exc)) from exc

        parsed_working = urlparse(working_base_url)
        working_origin = f"{parsed_working.scheme}://{parsed_working.netloc}"

        robots_text = _fetch_robots_txt(
            session,
            working_base_url,
            timeout=request_timeout,
            max_attempts=request_attempts,
            backoff_seconds=retry_backoff,
            transport_state=transport_state,
        )
        user_agent = session.headers.get("User-Agent", "*")
        if _robots_disallow(robots_text, working_base_url, user_agent):
            raise ProbeError("robots", "robots.txt disallows scraping this path")

        try:
            first_page_response.raise_for_status()
        except SCRAPE_REQUEST_EXCEPTIONS as exc:
            raise ProbeError("first_page_fetch", str(exc)) from exc

        video_urls, has_next_page = _parse_video_links(
            first_page_response,
            working_origin,
        )
        if not video_urls:
            raise ProbeError("first_page_parse", "no video links found on first page")

        sample_url = video_urls[0]
        try:
            redirect_response = _request_for_scrape(
                session,
                sample_url,
                timeout=request_timeout,
                allow_redirects=True,
                max_attempts=request_attempts,
                backoff_seconds=retry_backoff,
                transport_state=transport_state,
            )
            redirect_response.raise_for_status()
        except Exception as exc:
            raise ProbeError("sample_redirect", str(exc)) from exc

        return ProbeResult(
            working_base_url=working_base_url,
            final_base_url=first_page_response.url,
            video_count=len(video_urls),
            has_next_page=has_next_page,
            sample_url=sample_url,
            sample_final_url=redirect_response.url,
        )
```

- [ ] **Step 4: Run success test**

Run the command from Step 2.

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add app/scraper.py test_scraper.py
git commit -m "feat: add scraper probe workflow"
```

## Task 4: Probe Failure Cases

**Files:**
- Modify: `test_scraper.py`
- Modify: `app/scraper.py` only if tests reveal incorrect phase handling.

- [ ] **Step 1: Write failing failure-phase tests**

Add these tests:

```python
    def test_probe_scraper_reports_base_url_failure(self) -> None:
        session = Mock()
        session.headers = {"User-Agent": "test-agent"}

        with patch.object(scraper, "_build_scrape_session") as build_session:
            build_session.return_value.__enter__.return_value = session
            build_session.return_value.__exit__.return_value = None
            with patch.object(
                scraper,
                "_resolve_working_base_url",
                side_effect=requests.RequestException("blocked"),
            ):
                with self.assertRaises(scraper.ProbeError) as raised:
                    scraper.probe_scraper("https://fapplepie.com/videos")

        self.assertEqual(raised.exception.phase, "base_url")

    def test_probe_scraper_reports_first_page_parse_failure(self) -> None:
        first_page = make_response(200, "https://www.fapplepie.com/videos")
        first_page._content = b"<html></html>"
        session = Mock()
        session.headers = {"User-Agent": "test-agent"}

        with patch.object(scraper, "_build_scrape_session") as build_session:
            build_session.return_value.__enter__.return_value = session
            build_session.return_value.__exit__.return_value = None
            with patch.object(
                scraper,
                "_resolve_working_base_url",
                return_value=("https://www.fapplepie.com/videos", first_page),
            ):
                with patch.object(scraper, "_fetch_robots_txt", return_value=None):
                    with self.assertRaises(scraper.ProbeError) as raised:
                        scraper.probe_scraper("https://fapplepie.com/videos")

        self.assertEqual(raised.exception.phase, "first_page_parse")

    def test_probe_scraper_reports_sample_redirect_failure(self) -> None:
        first_page = make_response(200, "https://www.fapplepie.com/videos")
        first_page._content = b'<h3><a href="/watch/abc">One</a></h3>'
        session = Mock()
        session.headers = {"User-Agent": "test-agent"}

        with patch.object(scraper, "_build_scrape_session") as build_session:
            build_session.return_value.__enter__.return_value = session
            build_session.return_value.__exit__.return_value = None
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
                            scraper.probe_scraper("https://fapplepie.com/videos")

        self.assertEqual(raised.exception.phase, "sample_redirect")
```

- [ ] **Step 2: Run tests**

Run:

```bash
/private/tmp/fapplepie-test-venv/bin/python -m unittest \
  test_scraper.ScraperTransportTests.test_probe_scraper_reports_base_url_failure \
  test_scraper.ScraperTransportTests.test_probe_scraper_reports_first_page_parse_failure \
  test_scraper.ScraperTransportTests.test_probe_scraper_reports_sample_redirect_failure
```

Expected: pass if Task 3 phase handling is complete; otherwise fail with the incorrect phase and fix `probe_scraper`.

- [ ] **Step 3: Add robots failure test**

Add:

```python
    def test_probe_scraper_reports_robots_failure(self) -> None:
        first_page = make_response(200, "https://www.fapplepie.com/videos")
        first_page._content = b'<h3><a href="/watch/abc">One</a></h3>'
        session = Mock()
        session.headers = {"User-Agent": "test-agent"}

        with patch.object(scraper, "_build_scrape_session") as build_session:
            build_session.return_value.__enter__.return_value = session
            build_session.return_value.__exit__.return_value = None
            with patch.object(
                scraper,
                "_resolve_working_base_url",
                return_value=("https://www.fapplepie.com/videos", first_page),
            ):
                with patch.object(scraper, "_fetch_robots_txt", return_value="User-agent: *\nDisallow: /videos"):
                    with self.assertRaises(scraper.ProbeError) as raised:
                        scraper.probe_scraper("https://fapplepie.com/videos")

        self.assertEqual(raised.exception.phase, "robots")
```

- [ ] **Step 4: Run all probe failure tests**

Run:

```bash
/private/tmp/fapplepie-test-venv/bin/python -m unittest \
  test_scraper.ScraperTransportTests.test_probe_scraper_reports_base_url_failure \
  test_scraper.ScraperTransportTests.test_probe_scraper_reports_first_page_parse_failure \
  test_scraper.ScraperTransportTests.test_probe_scraper_reports_sample_redirect_failure \
  test_scraper.ScraperTransportTests.test_probe_scraper_reports_robots_failure
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add app/scraper.py test_scraper.py
git commit -m "test: cover scraper probe failures"
```

## Task 5: CLI Dispatch

**Files:**
- Modify: `app/scraper.py`
- Test: `test_scraper.py`

- [ ] **Step 1: Write failing CLI tests**

Import `runpy` and `io` at the top of `test_scraper.py`:

```python
import io
import runpy
```

Add:

```python
    def test_cli_probe_calls_probe_scraper_and_exits_successfully(self) -> None:
        result = scraper.ProbeResult(
            working_base_url="https://fapplepie.com/videos",
            final_base_url="https://www.fapplepie.com/videos",
            video_count=1,
            has_next_page=False,
            sample_url="https://fapplepie.com/watch/abc",
            sample_final_url="https://www.eporner.com/video-abc/example/",
        )

        with patch.object(sys, "argv", ["scraper.py", "--probe"]):
            with patch.object(scraper, "_get_proxy_settings"):
                with patch.object(scraper, "_log_proxy_self_check"):
                    with patch.object(scraper, "probe_scraper", return_value=result) as probe:
                        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                            runpy.run_path(str(Path(__file__).resolve().parent / "app" / "scraper.py"), run_name="__main__")

        probe.assert_called_once_with("https://fapplepie.com/videos")
        self.assertIn("Probe successful", stdout.getvalue())

    def test_cli_probe_failure_exits_nonzero(self) -> None:
        with patch.object(sys, "argv", ["scraper.py", "--probe"]):
            with patch.object(scraper, "_get_proxy_settings"):
                with patch.object(scraper, "_log_proxy_self_check"):
                    with patch.object(scraper, "probe_scraper", side_effect=scraper.ProbeError("base_url", "blocked")):
                        with patch("sys.stderr", new_callable=io.StringIO) as stderr:
                            with self.assertRaises(SystemExit) as raised:
                                runpy.run_path(str(Path(__file__).resolve().parent / "app" / "scraper.py"), run_name="__main__")

        self.assertEqual(raised.exception.code, 4)
        self.assertIn("Probe failed: base_url: blocked", stderr.getvalue())
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
/private/tmp/fapplepie-test-venv/bin/python -m unittest \
  test_scraper.ScraperTransportTests.test_cli_probe_calls_probe_scraper_and_exits_successfully \
  test_scraper.ScraperTransportTests.test_cli_probe_failure_exits_nonzero
```

Expected: fail because CLI has no `--probe` argument.

- [ ] **Step 3: Add CLI argument and dispatch**

In `app/scraper.py`, add the argument:

```python
    parser.add_argument('--probe', action='store_true', default=False, help='Probe scraper readiness without writing URL/cache state or downloading')
```

Update the default behavior check:

```python
    if not args.probe and not args.scrape and not args.download and not args.all:
        args.scrape = True
```

Before `if args.scrape`, add:

```python
    if args.probe:
        try:
            result = probe_scraper(url)
            print(result.format_success())
        except ProbeError as e:
            print(f"Probe failed: {e}", file=sys.stderr)
            sys.exit(4)
```

- [ ] **Step 4: Run CLI tests**

Run the command from Step 2.

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add app/scraper.py test_scraper.py
git commit -m "feat: add probe CLI"
```

## Task 6: Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/DOCKER_SETUP.md`
- Test: none beyond grep and compose config.

- [ ] **Step 1: Update README usage**

In `README.md`, add under `## Usage`:

```markdown
# Probe scraper readiness without writing URL/cache state or downloading
python3 app/scraper.py --probe
```

Add one sentence near proxy controls:

```markdown
Use `--probe` after proxy or transport changes to check base URL access, first-page parsing, and one sample redirect without starting downloads.
```

- [ ] **Step 2: Update Docker docs**

In `docs/DOCKER_SETUP.md`, add a command example near the one-time execution section:

```bash
docker compose run --rm fapplepie-downloader python3 scraper.py --probe
```

Also add:

```bash
docker exec fapplepie-downloader python3 scraper.py --probe
```

near troubleshooting / validation examples.

- [ ] **Step 3: Verify docs contain probe examples**

Run:

```bash
rg -n -- "--probe|Probe scraper" README.md docs/DOCKER_SETUP.md
```

Expected: README and Docker setup both contain probe examples.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/DOCKER_SETUP.md
git commit -m "docs: document probe mode"
```

## Task 7: Full Verification

**Files:**
- No edits expected unless verification reveals a defect.

- [ ] **Step 1: Run full tests**

Run:

```bash
/private/tmp/fapplepie-test-venv/bin/python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Compile scraper**

Run:

```bash
python3 -m py_compile app/scraper.py
```

Expected: no output and exit code `0`.

- [ ] **Step 3: Run compose config**

Run:

```bash
docker compose config
```

Expected: compose file renders successfully.

- [ ] **Step 4: Run local live probe**

Run:

```bash
/private/tmp/fapplepie-test-venv/bin/python app/scraper.py --probe
```

Expected: prints `Probe successful` and exits `0` when the current network can reach fapplepie.

- [ ] **Step 5: Run Docker image build**

Run:

```bash
docker build -t fapplepie-downloader-public-test .
```

Expected: image builds successfully.

- [ ] **Step 6: Commit any fixes from verification**

If no edits were needed, skip this step. If edits were needed:

```bash
git add app/scraper.py test_scraper.py README.md docs/DOCKER_SETUP.md
git commit -m "fix: stabilize probe mode"
```

## Self-Review

- Spec coverage:
  - `--probe` command: Task 5
  - no URL/cache/download mutation: Task 3 tests
  - one sample redirect: Task 3
  - failure phases: Task 4
  - docs: Task 6
  - browser automation excluded: no task adds browser dependencies
- Placeholder scan: no `TBD`, `TODO`, or deferred implementation steps.
- Type consistency: `ProbeError`, `ProbeResult`, `_parse_video_links`, and `probe_scraper` names are consistent across tasks.
