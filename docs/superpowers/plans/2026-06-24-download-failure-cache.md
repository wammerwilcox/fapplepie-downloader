# Download Failure Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a durable download failure cache that skips permanent failures, retries transient failures, and periodically rechecks extractor/site failures.

**Architecture:** Extend the existing `processed_cache.json` shape with a `download_failures` map keyed by final download URL. Keep successful downloads in `downloaded_urls` exactly as today, and add small classifier/helper functions in `app/scraper.py` so the main `download_videos()` loop remains readable. Do not add database dependencies or change the scrape/redirect cache contract.

**Tech Stack:** Python standard library, current JSON cache file, `yt-dlp` subprocess stderr classification, existing `unittest`/`pytest` test suite.

---

## Upstream Findings

- Eporner `Unable to extract hash` has an open yt-dlp issue: https://github.com/yt-dlp/yt-dlp/issues/16277
  - Labels: `geo-blocked`, `site-bug`, `patch-available`.
  - Useful clue: maintainers reproduced this as an age-verification/geoblock page in some VPN regions. A proposed upstream patch would turn the confusing hash extraction failure into a login/cookies-required error.
  - Operational classification: `extractor_or_site`, not permanent. Retry after a cooldown or after a yt-dlp version change.
- `xvideos.red` has an open yt-dlp site request: https://github.com/yt-dlp/yt-dlp/issues/4831
  - Labels: `site-request`, `account-needed`, `can-share-account`.
  - A closed related issue proposed adding `xvideos.red` to the XVideos URL regex: https://github.com/yt-dlp/yt-dlp/issues/16216
  - Operational classification: `unsupported_url` until upstream support lands.
- `videosection.com` had no matching yt-dlp issue in issue search for `videosection`, `videosection.com`, or `videosection.com/video`.
  - Operational classification: `unsupported_url`.
- `pornhub.com/` root redirects are not actionable download targets.
  - Operational classification: `bad_redirect_target`.

## File Structure

- Modify `app/scraper.py`
  - Add failure classification helpers.
  - Add failure cache normalization so old cache files remain valid.
  - Teach `download_videos()` to skip active failures before invoking yt-dlp.
  - Record failure metadata after failed yt-dlp runs.
  - Clear failure metadata when a URL later downloads successfully.
- Modify `test_scraper.py`
  - Add focused unit tests for cache migration, classification, skip behavior, cooldown behavior, and success clearing.
- Modify `README.md`
  - Document failure cache behavior and environment controls.
- Modify `docs/DOCKER_SETUP.md`
  - Add operational notes for skipped permanent failures and extractor retry cooldowns.
- Optional after implementation: update `docs/superpowers/specs/2026-06-24-2.0.0-hardening-status.md`
  - Move downloader failure cache from remaining hardening to implemented checkpoint.

## Proposed Cache Shape

```json
{
  "resolved_urls": {},
  "downloaded_urls": [],
  "download_failures": {
    "https://www.eporner.com/video-Nk7C921iVHI/example/": {
      "category": "extractor_or_site",
      "reason": "eporner_hash",
      "message": "ERROR: [Eporner] Nk7C921iVHI: Unable to extract hash",
      "first_failed_at": "2026-06-24T12:34:56Z",
      "last_failed_at": "2026-06-24T12:34:56Z",
      "failure_count": 1,
      "yt_dlp_version": "2026.06.09",
      "next_retry_at": "2026-07-01T12:34:56Z"
    }
  }
}
```

Categories:

- `permanent`: retry only after manual cache clear.
- `unsupported_url`: retry only after manual cache clear or if future logic detects a newer yt-dlp version.
- `bad_redirect_target`: retry only after manual cache clear.
- `extractor_or_site`: retry after cooldown or when yt-dlp version changes.
- `transient`: retry on the next run.

Environment controls:

- `DOWNLOAD_FAILURE_CACHE=1` enables the behavior by default.
- `DOWNLOAD_EXTRACTOR_RETRY_DAYS=7` sets cooldown for extractor/site failures.
- `DOWNLOAD_PERMANENT_FAILURE_CACHE=1` caches unsupported/dead/root failures.

## Task 1: Normalize Failure Cache Shape

**Files:**
- Modify: `app/scraper.py`
- Modify: `test_scraper.py`

- [ ] **Step 1: Write the failing cache migration test**

Add this test near the existing cache tests in `test_scraper.py`:

```python
def test_load_cache_adds_download_failures_for_old_cache_shape(self) -> None:
    with TemporaryDirectory() as tmp_dir:
        cache_path = Path(tmp_dir) / "processed_cache.json"
        lock_path = Path(tmp_dir) / "processed_cache.json.lock"
        cache_path.write_text(json.dumps({
            "resolved_urls": {},
            "downloaded_urls": [],
        }))

        with patch.object(scraper, "CACHE_PATH", cache_path):
            with patch.object(scraper, "LOCK_PATH", lock_path):
                cache = scraper.load_cache_locked()

    self.assertEqual(cache["download_failures"], {})
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
.venv/bin/python -m pytest test_scraper.py -k download_failures_for_old_cache_shape
```

Expected: fail because `load_cache_locked()` does not add `download_failures`.

- [ ] **Step 3: Implement cache normalization**

In `app/scraper.py`, add:

```python
def _normalize_cache(cache: dict) -> dict:
    cache.setdefault("resolved_urls", {})
    cache.setdefault("downloaded_urls", [])
    cache.setdefault("download_failures", {})
    return cache
```

Update every `load_cache_locked()` return path that returns a cache object:

```python
return _normalize_cache(json.load(f))
```

For fresh-cache return paths, use:

```python
return _normalize_cache({})
```

- [ ] **Step 4: Run the focused test and verify it passes**

Run:

```bash
.venv/bin/python -m pytest test_scraper.py -k download_failures_for_old_cache_shape
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add app/scraper.py test_scraper.py
git commit -m "test: normalize download failure cache"
```

## Task 2: Classify yt-dlp Failures

**Files:**
- Modify: `app/scraper.py`
- Modify: `test_scraper.py`

- [ ] **Step 1: Write failing classifier tests**

Add these tests to `test_scraper.py`:

```python
def test_classifies_permanent_download_failures(self) -> None:
    cases = [
        (
            "ERROR: Unsupported URL: https://videosection.com/video/383315475",
            "unsupported_url",
            "unsupported_url",
        ),
        (
            "ERROR: Unsupported URL: https://www.xvideos.red/video.uhlmudb5a90/example",
            "unsupported_url",
            "unsupported_url",
        ),
        (
            "ERROR: Unsupported URL: https://www.pornhub.com/",
            "bad_redirect_target",
            "site_root",
        ),
        (
            "ERROR: [XVideos] abc123: Unable to download webpage: HTTP Error 404: Not Found",
            "permanent",
            "http_404",
        ),
    ]

    for stderr, category, reason in cases:
        with self.subTest(stderr=stderr):
            failure = scraper._classify_download_failure(stderr)
            self.assertEqual(failure["category"], category)
            self.assertEqual(failure["reason"], reason)


def test_classifies_extractor_and_transient_download_failures(self) -> None:
    eporner = scraper._classify_download_failure(
        "ERROR: [Eporner] Nk7C921iVHI: Unable to extract hash"
    )
    self.assertEqual(eporner["category"], "extractor_or_site")
    self.assertEqual(eporner["reason"], "eporner_hash")

    timeout = scraper._classify_download_failure(
        "ERROR: Unable to download video data: timed out"
    )
    self.assertEqual(timeout["category"], "transient")
    self.assertEqual(timeout["reason"], "network")
```

- [ ] **Step 2: Run classifier tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest test_scraper.py -k "classifies_permanent_download_failures or classifies_extractor"
```

Expected: fail because `_classify_download_failure()` does not exist.

- [ ] **Step 3: Implement the classifier**

Add to `app/scraper.py`:

```python
def _classify_download_failure(stderr: str) -> dict[str, str]:
    message = stderr.strip()
    lower_message = message.lower()

    if "unsupported url:" in lower_message:
        if "pornhub.com/" in lower_message and lower_message.rstrip().endswith("pornhub.com/"):
            return {"category": "bad_redirect_target", "reason": "site_root"}
        return {"category": "unsupported_url", "reason": "unsupported_url"}

    if "http error 404" in lower_message or "404: not found" in lower_message:
        return {"category": "permanent", "reason": "http_404"}

    if "[eporner]" in lower_message and "unable to extract hash" in lower_message:
        return {"category": "extractor_or_site", "reason": "eporner_hash"}

    if "no video formats found" in lower_message:
        return {"category": "extractor_or_site", "reason": "no_formats"}

    if any(token in lower_message for token in [
        "timed out",
        "timeout",
        "connection reset",
        "connection refused",
        "temporarily unavailable",
        "http error 429",
        "http error 500",
        "http error 502",
        "http error 503",
        "http error 504",
    ]):
        return {"category": "transient", "reason": "network"}

    return {"category": "extractor_or_site", "reason": "unknown"}
```

- [ ] **Step 4: Run classifier tests and verify they pass**

Run:

```bash
.venv/bin/python -m pytest test_scraper.py -k "classifies_permanent_download_failures or classifies_extractor"
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add app/scraper.py test_scraper.py
git commit -m "feat: classify downloader failures"
```

## Task 3: Add Failure Cache Skip Rules

**Files:**
- Modify: `app/scraper.py`
- Modify: `test_scraper.py`

- [ ] **Step 1: Write failing skip-rule tests**

Add these tests:

```python
def test_download_failure_cache_skips_permanent_failures(self) -> None:
    failure = {
        "category": "unsupported_url",
        "reason": "unsupported_url",
        "last_failed_at": "2026-06-24T12:00:00Z",
        "failure_count": 1,
        "yt_dlp_version": "2026.06.09",
    }

    should_skip, reason = scraper._should_skip_failed_download(
        failure,
        current_yt_dlp_version="2026.06.09",
    )

    self.assertTrue(should_skip)
    self.assertEqual(reason, "unsupported_url")


def test_download_failure_cache_retries_extractor_after_version_change(self) -> None:
    failure = {
        "category": "extractor_or_site",
        "reason": "eporner_hash",
        "last_failed_at": "2026-06-24T12:00:00Z",
        "failure_count": 1,
        "yt_dlp_version": "2026.06.09",
        "next_retry_at": "2026-07-01T12:00:00Z",
    }

    should_skip, reason = scraper._should_skip_failed_download(
        failure,
        current_yt_dlp_version="2026.07.01",
    )

    self.assertFalse(should_skip)
    self.assertEqual(reason, "yt_dlp_version_changed")
```

- [ ] **Step 2: Run skip-rule tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest test_scraper.py -k "download_failure_cache_skips or retries_extractor_after_version_change"
```

Expected: fail because `_should_skip_failed_download()` does not exist.

- [ ] **Step 3: Implement skip-rule helper**

Add to `app/scraper.py`:

```python
def _should_skip_failed_download(
    failure: dict,
    *,
    current_yt_dlp_version: str,
    now: datetime | None = None,
) -> tuple[bool, str]:
    category = failure.get("category", "")

    if category in {"permanent", "unsupported_url", "bad_redirect_target"}:
        return True, failure.get("reason", category)

    if category == "extractor_or_site":
        if failure.get("yt_dlp_version") != current_yt_dlp_version:
            return False, "yt_dlp_version_changed"
        next_retry_raw = failure.get("next_retry_at")
        if not next_retry_raw:
            return False, "missing_retry_time"
        check_time = now or datetime.utcnow()
        next_retry = datetime.fromisoformat(next_retry_raw.replace("Z", "+00:00")).replace(tzinfo=None)
        return check_time < next_retry, failure.get("reason", "extractor_or_site")

    return False, "retry_allowed"
```

- [ ] **Step 4: Run skip-rule tests and verify they pass**

Run:

```bash
.venv/bin/python -m pytest test_scraper.py -k "download_failure_cache_skips or retries_extractor_after_version_change"
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add app/scraper.py test_scraper.py
git commit -m "feat: add downloader failure skip rules"
```

## Task 4: Record Failures and Clear on Success

**Files:**
- Modify: `app/scraper.py`
- Modify: `test_scraper.py`

- [ ] **Step 1: Write failing metadata tests**

Add:

```python
def test_record_download_failure_sets_retry_for_extractor_failures(self) -> None:
    cache = {"download_failures": {}}

    scraper._record_download_failure(
        cache,
        "https://www.eporner.com/video-Nk7C921iVHI/example/",
        "ERROR: [Eporner] Nk7C921iVHI: Unable to extract hash",
        yt_dlp_version="2026.06.09",
        now=datetime(2026, 6, 24, 12, 0, 0),
        extractor_retry_days=7,
    )

    failure = cache["download_failures"]["https://www.eporner.com/video-Nk7C921iVHI/example/"]
    self.assertEqual(failure["category"], "extractor_or_site")
    self.assertEqual(failure["reason"], "eporner_hash")
    self.assertEqual(failure["failure_count"], 1)
    self.assertEqual(failure["next_retry_at"], "2026-07-01T12:00:00Z")


def test_clear_download_failure_removes_failure_entry(self) -> None:
    cache = {
        "download_failures": {
            "https://example.com/video": {"category": "transient"}
        }
    }

    scraper._clear_download_failure(cache, "https://example.com/video")

    self.assertEqual(cache["download_failures"], {})
```

- [ ] **Step 2: Run metadata tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest test_scraper.py -k "record_download_failure or clear_download_failure"
```

Expected: fail because helpers do not exist.

- [ ] **Step 3: Implement metadata helpers**

Add:

```python
def _utc_timestamp(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat() + "Z"


def _record_download_failure(
    cache: dict,
    url: str,
    stderr: str,
    *,
    yt_dlp_version: str,
    now: datetime | None = None,
    extractor_retry_days: int = 7,
) -> None:
    failure_time = now or datetime.utcnow()
    existing = cache.setdefault("download_failures", {}).get(url, {})
    classified = _classify_download_failure(stderr)
    failure = {
        "category": classified["category"],
        "reason": classified["reason"],
        "message": stderr.strip().splitlines()[0] if stderr.strip() else "",
        "first_failed_at": existing.get("first_failed_at", _utc_timestamp(failure_time)),
        "last_failed_at": _utc_timestamp(failure_time),
        "failure_count": int(existing.get("failure_count", 0)) + 1,
        "yt_dlp_version": yt_dlp_version,
    }
    if classified["category"] == "extractor_or_site":
        retry_at = failure_time + timedelta(days=extractor_retry_days)
        failure["next_retry_at"] = _utc_timestamp(retry_at)
    cache["download_failures"][url] = failure


def _clear_download_failure(cache: dict, url: str) -> None:
    cache.setdefault("download_failures", {}).pop(url, None)
```

Also add `timedelta` to the `datetime` import:

```python
from datetime import datetime, timedelta
```

- [ ] **Step 4: Run metadata tests and verify they pass**

Run:

```bash
.venv/bin/python -m pytest test_scraper.py -k "record_download_failure or clear_download_failure"
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add app/scraper.py test_scraper.py
git commit -m "feat: record downloader failure metadata"
```

## Task 5: Wire Failure Cache into Download Loop

**Files:**
- Modify: `app/scraper.py`
- Modify: `test_scraper.py`

- [ ] **Step 1: Write failing integration-style loop test**

Add a test that uses a temporary `video_urls.txt`, a temporary cache path, and patches `subprocess.run`:

```python
def test_download_videos_skips_cached_permanent_failure(self) -> None:
    with TemporaryDirectory() as tmp_dir:
        base = Path(tmp_dir)
        urls_file = base / "video_urls.txt"
        output_dir = base / "downloads"
        cache_path = base / "processed_cache.json"
        lock_path = base / "processed_cache.json.lock"
        failed_url = "https://videosection.com/video/383315475"
        urls_file.write_text(failed_url + "\n")
        cache_path.write_text(json.dumps({
            "resolved_urls": {},
            "downloaded_urls": [],
            "download_failures": {
                failed_url: {
                    "category": "unsupported_url",
                    "reason": "unsupported_url",
                    "last_failed_at": "2026-06-24T12:00:00Z",
                    "failure_count": 1,
                    "yt_dlp_version": "2026.06.09",
                }
            },
        }))

        with patch.object(scraper, "BASE_DIR", base):
            with patch.object(scraper, "CACHE_PATH", cache_path):
                with patch.object(scraper, "LOCK_PATH", lock_path):
                    with patch.object(scraper, "_resolve_executable", side_effect=["/venv/bin/yt-dlp", "/usr/bin/aria2c"]):
                        with patch.object(scraper, "_get_binary_version", return_value="2026.06.09"):
                            with patch.object(scraper.subprocess, "run") as run:
                                scraper.download_videos(str(urls_file), str(output_dir))

    run.assert_not_called()
```

- [ ] **Step 2: Run the integration-style test and verify it fails**

Run:

```bash
.venv/bin/python -m pytest test_scraper.py -k skips_cached_permanent_failure
```

Expected: fail because the current loop still invokes yt-dlp.

- [ ] **Step 3: Add `_get_binary_version()` helper**

Change `_log_binary_version()` from a log-only helper into two helpers:

```python
def _get_binary_version(binary_path: str) -> str:
    result = subprocess.run(
        [binary_path, "--version"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode == 0:
        return result.stdout.strip().splitlines()[0]
    return "unknown"


def _log_binary_version(binary_path: str, binary_name: str) -> None:
    try:
        logger.info("%s version: %s", binary_name, _get_binary_version(binary_path))
    except Exception as exc:
        logger.warning("Unable to determine %s version at %s: %s", binary_name, binary_path, exc)
```

- [ ] **Step 4: Wire skip and record behavior into `download_videos()`**

In `download_videos()`, after binary resolution:

```python
yt_dlp_version = _get_binary_version(yt_dlp_path)
logger.info("yt-dlp version: %s", yt_dlp_version)
_log_binary_version(aria2c_path, "aria2c")
failure_cache_enabled = os.environ.get("DOWNLOAD_FAILURE_CACHE", "1").strip().lower() not in {"0", "false", "no", "off"}
extractor_retry_days = int(os.environ.get("DOWNLOAD_EXTRACTOR_RETRY_DAYS", "7"))
```

Before invoking yt-dlp for each URL:

```python
if failure_cache_enabled:
    failure = cache.get("download_failures", {}).get(url)
    if failure:
        should_skip, skip_reason = _should_skip_failed_download(
            failure,
            current_yt_dlp_version=yt_dlp_version,
        )
        if should_skip:
            print(f"[{i}/{len(urls)}] Skipping (cached failed: {skip_reason}): {url}")
            skipped += 1
            continue
```

On success:

```python
_clear_download_failure(cache, url)
```

On non-zero yt-dlp result:

```python
if failure_cache_enabled:
    _record_download_failure(
        cache,
        url,
        result.stderr,
        yt_dlp_version=yt_dlp_version,
        extractor_retry_days=extractor_retry_days,
    )
```

- [ ] **Step 5: Run focused integration-style test and verify it passes**

Run:

```bash
.venv/bin/python -m pytest test_scraper.py -k skips_cached_permanent_failure
```

Expected: pass.

- [ ] **Step 6: Run full test suite**

Run:

```bash
.venv/bin/python -m pytest
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add app/scraper.py test_scraper.py
git commit -m "feat: skip cached permanent download failures"
```

## Task 6: Document Operational Behavior

**Files:**
- Modify: `README.md`
- Modify: `docs/DOCKER_SETUP.md`
- Modify: `docs/superpowers/specs/2026-06-24-2.0.0-hardening-status.md`

- [ ] **Step 1: Add README section**

Add under the downloader/proxy operational docs:

```markdown
### Download Failure Cache

The downloader records failed yt-dlp URLs in `app/cache/processed_cache.json` under `download_failures`.

- Permanent failures such as `404 Not Found`, unsupported URLs, and site-root redirects are skipped on later runs.
- Extractor/site failures such as Eporner `Unable to extract hash` are retried after `DOWNLOAD_EXTRACTOR_RETRY_DAYS` or when the bundled yt-dlp version changes.
- Transient network failures are retried on the next run.

Controls:

- `DOWNLOAD_FAILURE_CACHE=1` enables failure caching.
- `DOWNLOAD_EXTRACTOR_RETRY_DAYS=7` controls extractor/site retry cooldown.
- `DOWNLOAD_PERMANENT_FAILURE_CACHE=1` caches permanent unsupported/dead URL failures.

To retry all cached failures, clear `download_failures` from `app/cache/processed_cache.json` or run the existing cache clear command if you want to rebuild all state.
```

- [ ] **Step 2: Add Docker setup note**

Add the same env controls to `docs/DOCKER_SETUP.md` near other environment settings.

- [ ] **Step 3: Update hardening status doc**

Move the failure-cache bullet from remaining hardening to implemented checkpoints in `docs/superpowers/specs/2026-06-24-2.0.0-hardening-status.md`.

- [ ] **Step 4: Verify docs mention env controls**

Run:

```bash
rg -n "DOWNLOAD_FAILURE_CACHE|DOWNLOAD_EXTRACTOR_RETRY_DAYS|download_failures" README.md docs
```

Expected: README and Docker docs mention all controls.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/DOCKER_SETUP.md docs/superpowers/specs/2026-06-24-2.0.0-hardening-status.md
git commit -m "docs: document downloader failure cache"
```

## Task 7: Final Verification

**Files:**
- No source edits expected.

- [ ] **Step 1: Run Python compile check**

```bash
.venv/bin/python -m py_compile app/scraper.py
```

Expected: exit 0.

- [ ] **Step 2: Run full tests**

```bash
.venv/bin/python -m pytest
```

Expected: all tests pass.

- [ ] **Step 3: Run compose validation**

```bash
docker compose config
docker compose -f docker-compose.dev.yml config
```

Expected: both commands exit 0.

- [ ] **Step 4: Run diff whitespace check**

```bash
git diff --check
```

Expected: no output, exit 0.

- [ ] **Step 5: Search staged changes for likely secrets before final commit or publish**

```bash
git diff --staged | grep -E "(password|api[_-]?key|secret|token|bearer)" -i
```

Expected: no credential values. Documentation words may match, but no secrets or cookie contents should appear.

## Self-Review

- Spec coverage: covers old cache compatibility, classification, skip rules, metadata write/clear, loop integration, docs, and final verification.
- Placeholder scan: every implementation task includes concrete code and commands.
- Type consistency: helper names are consistent across tasks: `_normalize_cache`, `_classify_download_failure`, `_should_skip_failed_download`, `_record_download_failure`, `_clear_download_failure`, `_get_binary_version`.
