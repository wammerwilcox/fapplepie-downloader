# Probe Mode Design

## Context

Fapplepie Downloader `1.1.0` is working in production as of 2026-06-13 after switching fapplepie page fetches to `curl_cffi` with Chrome impersonation. That release is the behavioral baseline for the 2.0.0 hardening line.

The next likely scraper failures will probably happen at one of these boundaries:

- base URL reachability or www/non-www fallback
- robots.txt fetch or interpretation
- first directory page fetch
- first directory page parsing
- fapplepie watch URL redirect resolution

Probe mode should make those boundaries visible without writing runtime state or starting downloads.

## Goals

- Add a `--probe` command that validates scrape readiness without mutating `video_urls.txt`, cache state, downloads, or logs beyond normal process output.
- Reuse the existing 1.1.0 scrape transport, proxy selection, robots behavior, retry settings, and parser assumptions.
- Resolve exactly one sample fapplepie video URL to prove redirect resolution still reaches a final host.
- Exit non-zero when a required probe phase fails, with output that names the failing phase.
- Keep browser automation out of scope for this release slice.

## Non-Goals

- No Playwright, Selenium, or browser fallback.
- No CAPTCHA or challenge solving.
- No changes to yt-dlp download behavior.
- No cache writes during probe mode.
- No broad CLI redesign beyond adding the probe command and any small supporting options needed for clear output.

## User Flow

Running:

```bash
python3 app/scraper.py --probe
```

will:

1. Build the scrape session.
2. Log effective proxy routing.
3. Probe base URL candidates using the existing base URL logic.
4. Fetch and evaluate robots.txt using existing behavior.
5. Parse the first directory page for video links.
6. Report the first page video count and whether a next-page link exists.
7. Resolve one sample fapplepie video URL through redirects.
8. Print a compact success summary and exit `0`.

Probe mode must not call yt-dlp, write `video_urls.txt`, save cache changes, or create downloaded media.

## Failure Phases

Probe output should name one of these phases when it fails:

- `base_url`: no base URL candidate returned a usable page.
- `robots`: robots.txt disallows the target path.
- `first_page_fetch`: the first directory page could not be fetched after retries.
- `first_page_parse`: the first page fetched but yielded no video links.
- `sample_redirect`: a sample fapplepie video URL could not be resolved successfully.

Sample redirect failure is a hard failure. If redirect resolution is blocked, the full scrape is not useful even when the directory page still loads.

## Design Shape

The implementation should extract reusable helpers from `scrape_videos` rather than duplicate parsing logic:

- a first-page probe helper that returns the working base URL, response, parsed links, and next-page status
- a sample redirect helper that resolves one fapplepie URL without touching the cache
- a small probe result structure or straightforward dict for summary output

The current scrape flow should keep its behavior. Probe mode observes the same path and reports it; behavior changes to delays, diagnostics, or transport abstraction belong to later 2.0.0 branches.

## Testing

Add tests for:

- successful probe summary with one parsed video link and one resolved sample redirect
- base URL failure reports `base_url`
- no video links reports `first_page_parse`
- sample redirect failure reports `sample_redirect`
- probe mode does not save cache or write URL output
- CLI dispatch calls probe mode for `--probe`

Existing scrape and transport tests should continue to pass.

## Documentation

Update README and Docker docs with a short probe-mode example. Mention that probe mode is intended for production diagnostics and does not download or write URL/cache state.

## Follow-On 2.0.0 Slices

After probe mode is verified, continue in this order:

1. polite timing controls
2. phase-aware diagnostics
3. transport isolation

Docs and tests should move with each slice rather than waiting for a final documentation pass.
