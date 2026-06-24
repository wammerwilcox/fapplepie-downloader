#!/usr/bin/env python3
import requests
try:
    from curl_cffi import requests as curl_requests
except ImportError:  # pragma: no cover - exercised only when optional dependency is absent.
    curl_requests = None
from bs4 import BeautifulSoup
import sys
import subprocess
import os
import json
from pathlib import Path
import tempfile
import time
import logging
import shutil
import random
from urllib.parse import quote, urlparse, urlunparse
from urllib.robotparser import RobotFileParser
from dataclasses import dataclass
from functools import lru_cache

from datetime import datetime
import fcntl

CACHE_FILE = 'processed_cache.json'
DEFAULT_BASE_DIR = Path('/app')


def get_base_dir() -> Path:
    """Return the base directory used for all write operations."""
    if DEFAULT_BASE_DIR.exists():
        return DEFAULT_BASE_DIR
    # Fallback for local/dev runs outside Docker.
    return Path(__file__).parent


BASE_DIR = get_base_dir()
CACHE_DIR = BASE_DIR / "cache"
CACHE_PATH = CACHE_DIR / CACHE_FILE
LOCK_PATH = CACHE_DIR / f"{CACHE_FILE}.lock"

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
CURL_REQUEST_EXCEPTIONS = (
    (curl_requests.exceptions.RequestException,) if curl_requests is not None else ()
)
SCRAPE_REQUEST_EXCEPTIONS = (requests.RequestException, *CURL_REQUEST_EXCEPTIONS)

SCRAPE_TRANSPORT_CONFIGURED = "configured"
SCRAPE_TRANSPORT_DIRECT = "direct"
DEFAULT_SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/137.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
    "Referer": "https://fapplepie.com/",
    "Upgrade-Insecure-Requests": "1",
    "Connection": "keep-alive",
}


@dataclass
class ScrapeTransportState:
    """Tracks the chosen transport mode for fapplepie scrape requests."""

    mode: str = SCRAPE_TRANSPORT_CONFIGURED


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


def _redact_proxy_url(proxy_url: str) -> str:
    """Hide proxy password in logs while keeping host/port visible."""
    parsed = urlparse(proxy_url)
    if parsed.password is None:
        return proxy_url

    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = f":{parsed.port}" if parsed.port else ""
    username = parsed.username or ""
    redacted_netloc = f"{username}:***@{host}{port}"
    return urlunparse(parsed._replace(netloc=redacted_netloc))


def _normalize_proxy_url(proxy_raw: str) -> str:
    """Accept host:port or full URLs; default to socks5h:// for host:port."""
    normalized = proxy_raw.strip()
    if "://" not in normalized:
        normalized = f"socks5h://{normalized}"
    return normalized


def _inject_proxy_credentials(proxy_url: str, username: str, password: str) -> str:
    """Inject URL-escaped credentials into a proxy URL without shell escaping."""
    parsed = urlparse(proxy_url)
    host = parsed.hostname
    if not host:
        raise ValueError(f"Invalid NORDVPN_PROXY value: {proxy_url}")
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = f":{parsed.port}" if parsed.port else ""
    auth = f"{quote(username, safe='')}:{quote(password, safe='')}@"
    return urlunparse(parsed._replace(netloc=f"{auth}{host}{port}"))


@lru_cache(maxsize=1)
def _get_proxy_settings() -> tuple[str | None, dict | None]:
    """
    Build optional proxy config from environment.
    If NORDVPN_PROXY is unset, return no proxy.
    """
    proxy_raw = os.environ.get("NORDVPN_PROXY", "").strip()
    if not proxy_raw:
        logger.info(
            "No outbound proxy configured (NORDVPN_PROXY unset); using direct network routing."
        )
        return None, None

    proxy_url = _normalize_proxy_url(proxy_raw)
    parsed = urlparse(proxy_url)

    user = os.environ.get("NORDVPN_USER", "").strip()
    password = os.environ.get("NORDVPN_PASS", "").strip()
    has_embedded_auth = parsed.username is not None or parsed.password is not None

    if has_embedded_auth and (user or password):
        logger.warning(
            "NORDVPN_PROXY already contains credentials; ignoring NORDVPN_USER/NORDVPN_PASS."
        )
    elif user or password:
        if not user or not password:
            raise ValueError(
                "Both NORDVPN_USER and NORDVPN_PASS must be set when using credential-based proxy auth."
            )
        proxy_url = _inject_proxy_credentials(proxy_url, user, password)
    elif os.environ.get("NORD_TOKEN") or os.environ.get("NORDVPN_TOKEN"):
        logger.warning(
            "NORD_TOKEN/NORDVPN_TOKEN is not valid proxy auth. "
            "Use NORDVPN_USER/NORDVPN_PASS (service credentials) with NORDVPN_PROXY."
        )

    logger.info("Using outbound proxy: %s", _redact_proxy_url(proxy_url))
    return proxy_url, {"http": proxy_url, "https": proxy_url}


@lru_cache(maxsize=1)
def _get_proxy_scope() -> str:
    """
    Determine proxy scope.
    - fapplepie (default): proxy only fapplepie.com traffic
    - all: proxy all outbound traffic
    """
    scope = os.environ.get("NORDVPN_PROXY_SCOPE", "fapplepie").strip().lower()
    if scope not in {"fapplepie", "all"}:
        logger.warning(
            "Invalid NORDVPN_PROXY_SCOPE=%s, defaulting to 'fapplepie'",
            scope,
        )
        return "fapplepie"
    return scope


def _is_fapplepie_host(hostname: str | None) -> bool:
    if not hostname:
        return False
    host = hostname.lower()
    return host == "fapplepie.com" or host.endswith(".fapplepie.com")


def _proxy_url_for_target(url: str) -> str | None:
    proxy_url, _ = _get_proxy_settings()
    if not proxy_url:
        return None
    scope = _get_proxy_scope()
    if scope == "all":
        return proxy_url
    parsed = urlparse(url)
    if _is_fapplepie_host(parsed.hostname):
        return proxy_url
    return None


def _log_proxy_self_check() -> None:
    """Log effective proxy routing behavior at startup."""
    proxy_url, _ = _get_proxy_settings()
    if not proxy_url:
        logger.info("Proxy self-check: outbound proxy disabled")
        return

    scope = _get_proxy_scope()
    fapplepie_probe = "https://fapplepie.com/videos"
    sample_probe = os.environ.get(
        "PROXY_SELF_CHECK_SAMPLE_URL",
        "https://www.eporner.com/",
    )

    fapplepie_mode = "proxied" if _proxy_url_for_target(fapplepie_probe) else "direct"
    sample_mode = "proxied" if _proxy_url_for_target(sample_probe) else "direct"

    logger.info(
        "Proxy self-check: scope=%s fapplepie=%s sample(%s)=%s",
        scope,
        fapplepie_mode,
        sample_probe,
        sample_mode,
    )


def _scrape_direct_fallback_enabled() -> bool:
    raw_value = os.environ.get("SCRAPE_DIRECT_FALLBACK_ON_403", "1").strip().lower()
    return raw_value not in {"0", "false", "no", "off"}


def _build_scrape_session() -> requests.Session:
    if curl_requests is not None:
        session = curl_requests.Session()
        session.codex_supports_impersonate = True
    else:
        logger.warning(
            "curl_cffi is unavailable; falling back to standard requests for scraping."
        )
        session = requests.Session()
    session.headers.update(DEFAULT_SCRAPE_HEADERS)
    return session


def _request_impersonation_kwargs(session, url: str) -> dict:
    if (
        getattr(session, "codex_supports_impersonate", False)
        and _is_fapplepie_host(urlparse(url).hostname)
    ):
        return {"impersonate": "chrome"}
    return {}


def _sleep_with_jitter(
    *,
    base_seconds: float,
    jitter_seconds: float,
    reason: str,
) -> None:
    base_seconds = max(0.0, base_seconds)
    jitter_seconds = max(0.0, jitter_seconds)
    jitter = random.uniform(0, jitter_seconds) if jitter_seconds > 0 else 0.0
    sleep_seconds = base_seconds + jitter
    if sleep_seconds <= 0:
        return

    logger.info("%s: sleeping %.1fs", reason, sleep_seconds)
    time.sleep(sleep_seconds)


def _transport_proxies_for_request(
    url: str,
    transport_mode: str,
) -> tuple[dict | None, bool]:
    if transport_mode == SCRAPE_TRANSPORT_DIRECT:
        return None, False
    if transport_mode != SCRAPE_TRANSPORT_CONFIGURED:
        raise ValueError(f"Unsupported transport mode: {transport_mode}")

    target_proxy = _proxy_url_for_target(url)
    if not target_proxy:
        return None, False
    return {"http": target_proxy, "https": target_proxy}, True


def _annotate_response_transport(
    response,
    *,
    initial_transport_mode: str,
    initial_proxied: bool,
    fallback_attempted: bool,
):
    response.codex_initial_transport_mode = initial_transport_mode
    response.codex_initial_proxied = initial_proxied
    response.codex_transport_mode = getattr(
        response,
        "codex_transport_mode",
        initial_transport_mode,
    )
    response.codex_proxied = getattr(response, "codex_proxied", initial_proxied)
    response.codex_fallback_attempted = fallback_attempted
    return response


def _format_probe_failure(candidate: str, response) -> str:
    initial_transport = getattr(response, "codex_initial_transport_mode", "unknown")
    initial_proxied = getattr(response, "codex_initial_proxied", False)
    final_transport = getattr(response, "codex_transport_mode", initial_transport)
    final_proxied = getattr(response, "codex_proxied", initial_proxied)
    fallback_attempted = getattr(response, "codex_fallback_attempted", False)
    return (
        f"{candidate} -> status={response.status_code} "
        f"initial_transport={initial_transport} initial_proxied={initial_proxied} "
        f"final_transport={final_transport} final_proxied={final_proxied} "
        f"fallback_attempted={fallback_attempted}"
    )


def _is_stale_resolved_url(source_url: str, resolved_url: str | None) -> bool:
    if not resolved_url:
        return True
    if resolved_url == source_url:
        return True
    return _is_fapplepie_host(urlparse(resolved_url).hostname)


def _ensure_under_base(path_value: str | Path, kind: str) -> Path:
    """Resolve a path and ensure it stays under BASE_DIR."""
    candidate = Path(path_value)
    resolved = candidate.resolve() if candidate.is_absolute() else (BASE_DIR / candidate).resolve()
    base_resolved = BASE_DIR.resolve()
    if not resolved.is_relative_to(base_resolved):
        raise ValueError(f"{kind} must be under {base_resolved} (got {resolved})")
    return resolved


def _running_in_docker() -> bool:
    return Path('/.dockerenv').exists() or os.environ.get('RUNNING_IN_DOCKER') == '1'


def _is_trusted_docker_binary(path_value: str | Path) -> bool:
    resolved = Path(path_value).resolve()
    trusted_dirs = (
        Path("/venv/bin"),
        Path("/usr/local/bin"),
        Path("/usr/bin"),
        Path("/bin"),
    )
    return any(resolved.is_relative_to(base_dir) for base_dir in trusted_dirs)


def _resolve_executable(env_var: str, binary_name: str) -> str:
    override = os.environ.get(env_var)
    if override:
        if Path(override).exists() and os.access(override, os.X_OK):
            if _running_in_docker() and not _is_trusted_docker_binary(override):
                raise FileNotFoundError(
                    f"{env_var} points outside trusted container paths: {override}"
                )
            return override
        raise FileNotFoundError(f"{env_var} is set but not executable: {override}")

    venv_candidate = Path("/venv/bin") / binary_name
    if venv_candidate.exists() and os.access(venv_candidate, os.X_OK):
        return str(venv_candidate)

    resolved = shutil.which(binary_name)
    if not resolved:
        raise FileNotFoundError(f"{binary_name} not found in PATH")
    if _running_in_docker() and not _is_trusted_docker_binary(resolved):
        raise FileNotFoundError(
            f"{binary_name} resolved outside trusted container paths: {resolved}"
        )
    return resolved


def _log_binary_version(binary_path: str, binary_name: str) -> None:
    try:
        result = subprocess.run(
            [binary_path, "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        first_line = (result.stdout or result.stderr).splitlines()[:1]
        if first_line:
            logger.info("%s version: %s", binary_name, first_line[0])
    except Exception:
        logger.warning("Unable to determine %s version", binary_name)


def _yt_dlp_cookie_args() -> list[str]:
    cookies_file = os.environ.get("YT_DLP_COOKIES_FILE", "").strip()
    cookies_from_browser = os.environ.get("YT_DLP_COOKIES_FROM_BROWSER", "").strip()

    if cookies_file and cookies_from_browser:
        raise ValueError(
            "Configure only one cookie source: YT_DLP_COOKIES_FILE or "
            "YT_DLP_COOKIES_FROM_BROWSER."
        )

    if cookies_file:
        cookies_path = Path(cookies_file).expanduser()
        if not cookies_path.exists():
            raise FileNotFoundError(
                f"YT_DLP_COOKIES_FILE is set but does not exist: {cookies_file}"
            )
        return ["--cookies", str(cookies_path)]

    if cookies_from_browser:
        return ["--cookies-from-browser", cookies_from_browser]

    return []


def _yt_dlp_js_runtime_args() -> list[str]:
    js_runtimes = os.environ.get("YT_DLP_JS_RUNTIMES", "").strip()
    if not js_runtimes:
        return []
    return ["--js-runtimes", js_runtimes]


def _build_yt_dlp_command(
    yt_dlp_path: str,
    aria2c_path: str,
    output_template: str,
    url: str,
    proxy_url: str | None,
    use_aria2: bool,
) -> list[str]:
    cmd = [
        yt_dlp_path,
        "-o", output_template,
        "--concurrent-fragments", "4",
        "-q",
        *_yt_dlp_js_runtime_args(),
        *_yt_dlp_cookie_args(),
    ]

    if use_aria2:
        aria2_args = "aria2c:-x 16 -k 1M --max-connection-per-server=16 --split=16"
        if proxy_url:
            aria2_args = f"{aria2_args} --all-proxy={proxy_url}"
        cmd.extend([
            "--external-downloader", aria2c_path,
            "--external-downloader-args", aria2_args,
        ])

    if proxy_url:
        cmd.extend(["--proxy", proxy_url])

    cmd.append(url)
    return cmd


def _fetch_robots_txt(
    session: requests.Session,
    base_url: str,
    timeout: float = 10.0,
    max_attempts: int = 3,
    backoff_seconds: float = 1.0,
    transport_state: ScrapeTransportState | None = None,
) -> str | None:
    try:
        parsed = urlparse(base_url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        response = _request_for_scrape(
            session,
            robots_url,
            timeout=timeout,
            allow_redirects=True,
            max_attempts=max_attempts,
            backoff_seconds=backoff_seconds,
            transport_state=transport_state,
        )
        if response.status_code == 404:
            logger.info("robots.txt not found at %s; continuing", robots_url)
            return None
        response.raise_for_status()
        return response.text
    except Exception as exc:
        logger.info("Unable to fetch robots.txt (%s); continuing", exc)
        return None


def _request_with_retries(
    session: requests.Session,
    url: str,
    headers: dict | None = None,
    timeout: float = 10.0,
    allow_redirects: bool = True,
    max_attempts: int = 3,
    backoff_seconds: float = 1.0,
    transport_mode: str = SCRAPE_TRANSPORT_CONFIGURED,
):
    """Issue a GET request with simple retries and linear backoff."""
    request_proxies, proxied = _transport_proxies_for_request(url, transport_mode)
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            logger.info(
                "HTTP GET %s via transport=%s proxied=%s attempt=%d/%d",
                url,
                transport_mode,
                proxied,
                attempt,
                max_attempts,
            )
            response = session.get(
                url,
                headers=headers,
                timeout=timeout,
                allow_redirects=allow_redirects,
                proxies=request_proxies,
                **_request_impersonation_kwargs(session, url),
            )
            response.codex_transport_mode = transport_mode
            response.codex_proxied = proxied
            return response
        except SCRAPE_REQUEST_EXCEPTIONS as exc:
            last_error = exc
            if attempt < max_attempts:
                sleep_seconds = backoff_seconds * attempt
                logger.warning(
                    "Request failed (attempt %d/%d transport=%s proxied=%s): %s - retrying in %.1fs",
                    attempt,
                    max_attempts,
                    transport_mode,
                    proxied,
                    exc,
                    sleep_seconds,
                )
                time.sleep(sleep_seconds)
            else:
                logger.warning(
                    "Request failed (attempt %d/%d transport=%s proxied=%s): %s",
                    attempt,
                    max_attempts,
                    transport_mode,
                    proxied,
                    exc,
                )
    raise last_error


def _request_for_scrape(
    session: requests.Session,
    url: str,
    timeout: float = 10.0,
    allow_redirects: bool = True,
    max_attempts: int = 3,
    backoff_seconds: float = 1.0,
    transport_state: ScrapeTransportState | None = None,
):
    transport_state = transport_state or ScrapeTransportState()
    is_fapplepie_request = _is_fapplepie_host(urlparse(url).hostname)
    initial_transport_mode = (
        transport_state.mode if is_fapplepie_request else SCRAPE_TRANSPORT_CONFIGURED
    )

    response = None
    initial_proxied = False
    fallback_allowed = _scrape_direct_fallback_enabled()
    proxy_failed = False
    proxy_error: BaseException | None = None

    try:
        response = _request_with_retries(
            session,
            url,
            timeout=timeout,
            allow_redirects=allow_redirects,
            max_attempts=max_attempts,
            backoff_seconds=backoff_seconds,
            transport_mode=initial_transport_mode,
        )
        initial_proxied = getattr(response, "codex_proxied", False)
    except SCRAPE_REQUEST_EXCEPTIONS as exc:
        proxy_failed = True
        proxy_error = exc
        if not (
            is_fapplepie_request
            and initial_transport_mode == SCRAPE_TRANSPORT_CONFIGURED
            and fallback_allowed
        ):
            raise
        logger.warning(
            "Fapplepie request via proxy failed: %s; retrying direct: %s",
            exc,
            url,
        )

    if response is not None:
        response = _annotate_response_transport(
            response,
            initial_transport_mode=initial_transport_mode,
            initial_proxied=initial_proxied,
            fallback_attempted=False,
        )

    should_retry_direct = (
        (proxy_failed or (response is not None and response.status_code == 403))
        and is_fapplepie_request
        and initial_transport_mode == SCRAPE_TRANSPORT_CONFIGURED
        and fallback_allowed
    )
    if not should_retry_direct:
        if response is None:
            if (
                is_fapplepie_request
                and initial_transport_mode == SCRAPE_TRANSPORT_CONFIGURED
                and not fallback_allowed
            ):
                logger.warning(
                    "Fapplepie request via proxy failed and direct fallback is disabled: %s",
                    url,
                )
            return response
        if (
            is_fapplepie_request
            and response.status_code == 403
            and initial_transport_mode == SCRAPE_TRANSPORT_CONFIGURED
            and initial_proxied
            and not fallback_allowed
        ):
            logger.warning(
                "Fapplepie request returned 403 via proxy and direct fallback is disabled: %s",
                url,
            )
        return response

    logger.warning(
        "Fapplepie request via proxy failed; retrying direct: %s",
        url,
    )
    direct_response = _request_with_retries(
        session,
        url,
        timeout=timeout,
        allow_redirects=allow_redirects,
        max_attempts=max_attempts,
        backoff_seconds=backoff_seconds,
        transport_mode=SCRAPE_TRANSPORT_DIRECT,
    )
    direct_response = _annotate_response_transport(
        direct_response,
        initial_transport_mode=initial_transport_mode,
        initial_proxied=initial_proxied,
        fallback_attempted=True,
    )

    if direct_response.ok:
        transport_state.mode = SCRAPE_TRANSPORT_DIRECT
        logger.warning("Pinned direct scrape transport after proxied 403: %s", url)
    else:
        logger.warning(
            "Direct scrape fallback failed with status %s: %s",
            direct_response.status_code,
            url,
        )
    return direct_response


def _candidate_base_urls(base_url: str) -> list[str]:
    """Return unique base URL candidates, including www/non-www fallback."""
    parsed = urlparse(base_url)
    host = parsed.netloc
    candidates = [base_url]
    if not host:
        return candidates

    alt_host = host[4:] if host.startswith("www.") else f"www.{host}"
    if alt_host != host:
        alt_url = parsed._replace(netloc=alt_host).geturl()
        if alt_url not in candidates:
            candidates.append(alt_url)
    return candidates


def _resolve_working_base_url(
    session: requests.Session,
    base_url: str,
    timeout: float,
    max_attempts: int,
    backoff_seconds: float,
    transport_state: ScrapeTransportState,
):
    """
    Probe candidate base URLs and return (working_base_url, first_page_response).
    Raises RequestException if all candidates fail.
    """
    failures: list[str] = []
    for candidate in _candidate_base_urls(base_url):
        logger.info("Probing base URL: %s", candidate)
        try:
            response = _request_for_scrape(
                session,
                candidate,
                timeout=timeout,
                allow_redirects=True,
                max_attempts=max_attempts,
                backoff_seconds=backoff_seconds,
                transport_state=transport_state,
            )
            if response.status_code >= 400:
                failure = _format_probe_failure(candidate, response)
                failures.append(failure)
                logger.warning("Base URL probe failed: %s", failure)
                continue
            if candidate != base_url:
                logger.warning(
                    "Using fallback base URL %s (original %s)",
                    candidate,
                    base_url,
                )
            return candidate, response
        except SCRAPE_REQUEST_EXCEPTIONS as exc:
            failures.append(f"{candidate} -> {exc}")
            logger.warning("Base URL probe failed: %s", exc)

    details = " | ".join(failures)
    raise requests.RequestException(
        f"Unable to reach any base URL candidate. {details}"
    )


def _robots_disallow(
    robots_text: str | None,
    target_url: str,
    user_agent: str = "*",
) -> bool:
    if not robots_text:
        return False
    try:
        parser = RobotFileParser()
        parser.parse(robots_text.splitlines())
        is_allowed = parser.can_fetch(user_agent, target_url)
    except Exception as exc:
        logger.warning("Unable to parse robots.txt (%s); continuing", exc)
        return False

    if not is_allowed:
        logger.warning(
            "robots.txt disallows user-agent '%s' for %s",
            user_agent,
            target_url,
        )
    return not is_allowed


def _has_video_headings(response: requests.Response) -> bool:
    soup = BeautifulSoup(response.content, 'html.parser')
    return soup.find('h3') is not None


def _parse_video_links(
    response: requests.Response,
    working_origin: str,
) -> tuple[list[str], bool]:
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


# Read version from VERSION file
def get_version():
    """Get version from VERSION file in project root"""
    candidates = [
        Path(__file__).parent.parent / 'VERSION',
        Path(__file__).parent / 'VERSION',
        Path('/app/VERSION'),
    ]
    for candidate in candidates:
        try:
            if candidate.exists():
                return candidate.read_text().strip()
        except Exception:
            continue
    return 'unknown'

__version__ = get_version()

def load_cache():
    """Load the processing cache from file"""
    if CACHE_PATH.exists():
        try:
            with open(CACHE_PATH, 'r') as f:
                return json.load(f)
        except Exception:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            backup_path = CACHE_PATH.with_suffix(f".bad.{timestamp}.json")
            try:
                CACHE_PATH.rename(backup_path)
                logger.warning(
                    "Cache parse failed. Backed up to %s and starting fresh.",
                    backup_path,
                )
            except Exception:
                logger.warning(
                    "Cache parse failed. Unable to back up %s; starting fresh.",
                    CACHE_PATH,
                )
            return {'resolved_urls': {}, 'downloaded_urls': []}
    return {'resolved_urls': {}, 'downloaded_urls': []}

def save_cache(cache):
    """Save the processing cache to file"""
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        'w',
        delete=False,
        dir=str(CACHE_PATH.parent),
        prefix=f"{CACHE_FILE}.",
        suffix=".tmp",
    ) as tmp_file:
        json.dump(cache, tmp_file, indent=2)
        tmp_file.flush()
        os.fsync(tmp_file.fileno())
    os.replace(tmp_file.name, CACHE_PATH)


def _acquire_lock(timeout_seconds: float = 10.0, poll_interval: float = 0.1):
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_file = open(LOCK_PATH, 'a')
    start = time.monotonic()
    while True:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return lock_file
        except BlockingIOError:
            if time.monotonic() - start >= timeout_seconds:
                lock_file.close()
                raise TimeoutError("Timed out waiting for cache lock")
            time.sleep(poll_interval)


def _release_lock(lock_file) -> None:
    try:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
    finally:
        lock_file.close()


def load_cache_locked():
    lock_file = _acquire_lock()
    try:
        return load_cache()
    finally:
        _release_lock(lock_file)


def save_cache_locked(cache) -> None:
    lock_file = _acquire_lock()
    try:
        save_cache(cache)
    finally:
        _release_lock(lock_file)


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
        except SCRAPE_REQUEST_EXCEPTIONS as exc:
            raise ProbeError("sample_redirect", str(exc)) from exc

        return ProbeResult(
            working_base_url=working_base_url,
            final_base_url=first_page_response.url,
            video_count=len(video_urls),
            has_next_page=has_next_page,
            sample_url=sample_url,
            sample_final_url=redirect_response.url,
        )


def scrape_videos(base_url, output_file):
    """
    Scrape video URLs from fapplepie.com across all pages
    Extracts URLs from h3 tags within video-info divs
    Follows redirects to get final URLs
    Uses cache to avoid re-resolving known URLs
    """
    cache = load_cache_locked()
    output_path = _ensure_under_base(output_file, "URLs file")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        request_timeout = float(os.environ.get("SCRAPE_REQUEST_TIMEOUT_SECONDS", "10"))
        request_attempts = int(os.environ.get("SCRAPE_REQUEST_ATTEMPTS", "3"))
        retry_backoff = float(os.environ.get("SCRAPE_REQUEST_BACKOFF_SECONDS", "1"))
        delay_seconds = float(os.environ.get("SCRAPE_DELAY_SECONDS", "1.0"))
        delay_jitter_seconds = float(os.environ.get("SCRAPE_DELAY_JITTER_SECONDS", "0"))
        redirect_delay_seconds = float(os.environ.get("SCRAPE_REDIRECT_DELAY_SECONDS", "1.0"))
        redirect_delay_jitter_seconds = float(
            os.environ.get("SCRAPE_REDIRECT_DELAY_JITTER_SECONDS", "1.0")
        )
        transport_state = ScrapeTransportState()
        with _build_scrape_session() as session:
            working_base_url, first_page_response = _resolve_working_base_url(
                session=session,
                base_url=base_url,
                timeout=request_timeout,
                max_attempts=request_attempts,
                backoff_seconds=retry_backoff,
                transport_state=transport_state,
            )
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
                print("robots.txt disallows scraping this path. Exiting.")
                sys.exit(1)

            all_video_urls = []
            page = 1
            max_pages = 100  # Safety limit to prevent infinite loops

            while page <= max_pages:
                # Construct page URL
                if page == 1:
                    url = working_base_url
                else:
                    url = f"{working_base_url}?page={page}"

                print(f"Fetching page {page}: {url}")

                try:
                    if page == 1:
                        response = first_page_response
                        first_page_response = None
                    else:
                        response = _request_for_scrape(
                            session,
                            url,
                            timeout=request_timeout,
                            allow_redirects=True,
                            max_attempts=request_attempts,
                            backoff_seconds=retry_backoff,
                            transport_state=transport_state,
                        )
                    response.raise_for_status()
                except SCRAPE_REQUEST_EXCEPTIONS as e:
                    print(f"Could not fetch page {page}: {e}")
                    if page == 1:
                        print("Page 1 could not be fetched after retries. Exiting with error.")
                        sys.exit(2)
                    break

                page_video_urls, has_next_page = _parse_video_links(
                    response,
                    working_origin,
                )

                if not page_video_urls and not _has_video_headings(response):
                    print(f"No videos found on page {page}. Stopping pagination.")
                    break

                all_video_urls.extend(page_video_urls)
                page_video_count = len(page_video_urls)

                print(f"  Found {page_video_count} videos on page {page}")

                if not has_next_page:
                    print(f"No next page link found. Stopping pagination.")
                    break

                _sleep_with_jitter(
                    base_seconds=delay_seconds,
                    jitter_seconds=delay_jitter_seconds,
                    reason="next page delay",
                )

                page += 1
        
            print(f"\nCollected {len(all_video_urls)} video URLs from {page} pages")
            if not all_video_urls:
                print("No video URLs were collected. Exiting with error.", file=sys.stderr)
                sys.exit(3)

            # Resolve redirects for URLs not in cache
            new_urls = 0
            cached_urls = 0
            resolved_urls = []

            print(f"Resolving redirects (skipping cached URLs)...\n")

            for i, fapplepie_url in enumerate(all_video_urls, 1):
                cached_final_url = cache['resolved_urls'].get(fapplepie_url)
                resolved_via_network = False
                if cached_final_url and not _is_stale_resolved_url(
                    fapplepie_url,
                    cached_final_url,
                ):
                    final_url = cached_final_url
                    resolved_urls.append(final_url)
                    cached_urls += 1
                else:
                    if cached_final_url:
                        logger.info(
                            "Refreshing stale cached resolved URL: %s -> %s",
                            fapplepie_url,
                            cached_final_url,
                        )
                    try:
                        redirect_response = _request_for_scrape(
                            session,
                            fapplepie_url,
                            timeout=request_timeout,
                            allow_redirects=True,
                            max_attempts=request_attempts,
                            backoff_seconds=retry_backoff,
                            transport_state=transport_state,
                        )
                        redirect_response.raise_for_status()
                        final_url = redirect_response.url
                        resolved_urls.append(final_url)
                        cache['resolved_urls'][fapplepie_url] = final_url
                        resolved_via_network = True
                        new_urls += 1
                    except Exception as e:
                        print(f"Warning: Could not fetch {fapplepie_url}: {e}", file=sys.stderr)
                        resolved_urls.append(fapplepie_url)  # Fallback to original URL

                if i % 50 == 0:
                    print(f"Resolved {i}/{len(all_video_urls)} redirects (cached: {cached_urls}, new: {new_urls})...")
                if i < len(all_video_urls) and resolved_via_network:
                    _sleep_with_jitter(
                        base_seconds=redirect_delay_seconds,
                        jitter_seconds=redirect_delay_jitter_seconds,
                        reason="redirect resolution delay",
                    )
        
        # Write URLs to file
        with open(output_path, 'w') as f:
            for url in resolved_urls:
                f.write(url + '\n')
        
        # Save cache
        save_cache_locked(cache)
        
        print(f"\n{'='*60}")
        print(f"Successfully processed {len(resolved_urls)} video URLs")
        print(f"  New URLs resolved: {new_urls}")
        print(f"  URLs from cache: {cached_urls}")
        print(f"URLs written to: {output_path}")
        print(f"Cache saved to: {CACHE_PATH}")
        print(f"{'='*60}")
        
    except SCRAPE_REQUEST_EXCEPTIONS as e:
        print(f"Error fetching the page: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error processing page: {e}", file=sys.stderr)
        sys.exit(1)

def download_videos(urls_file='video_urls.txt', output_dir='downloads'):
    """
    Download videos from URLs using yt-dlp
    Uses cache to avoid re-downloading known videos
    """
    yt_dlp_path = _resolve_executable("YT_DLP_PATH", "yt-dlp")
    aria2c_path = _resolve_executable("ARIA2C_PATH", "aria2c")
    _log_binary_version(yt_dlp_path, "yt-dlp")
    _log_binary_version(aria2c_path, "aria2c")
    _get_proxy_settings()

    cache = load_cache_locked()
    
    if _running_in_docker():
        urls_path = BASE_DIR / 'video_urls.txt'
    else:
        urls_path = _ensure_under_base(urls_file, "URLs file")

    if not urls_path.exists():
        print(f"Error: {urls_path} not found", file=sys.stderr)
        sys.exit(1)

    # Create output directory if it doesn't exist
    output_path = _ensure_under_base(output_dir, "Output directory")
    os.makedirs(output_path, exist_ok=True)
    
    # Read URLs from file
    with open(urls_path, 'r') as f:
        urls = [line.strip() for line in f if line.strip()]

    print(f"Downloading {len(urls)} videos to {output_path}/\n")
    
    downloaded = 0
    skipped = 0
    failed = 0
    
    for i, url in enumerate(urls, 1):
        # Check if URL is already in downloaded cache
        if url in cache['downloaded_urls']:
            print(f"[{i}/{len(urls)}] Skipping (already downloaded): {url}")
            skipped += 1
            continue
        
        try:
            print(f"[{i}/{len(urls)}] Downloading: {url}")
            target_proxy_url = _proxy_url_for_target(url)
            target_proxy_scheme = (
                urlparse(target_proxy_url).scheme.lower()
                if target_proxy_url
                else ""
            )
            use_aria2_for_url = True

            # aria2c's --all-proxy only accepts HTTP proxy format, not SOCKS.
            if target_proxy_url and target_proxy_scheme.startswith("socks"):
                use_aria2_for_url = False
                print(
                    "Proxy required for this URL uses SOCKS; using yt-dlp native downloader "
                    "(aria2c proxy format is incompatible)."
                )
            
            cmd = _build_yt_dlp_command(
                yt_dlp_path=yt_dlp_path,
                aria2c_path=aria2c_path,
                output_template=os.path.join(output_path, "%(title)s.%(ext)s"),
                url=url,
                proxy_url=target_proxy_url,
                use_aria2=use_aria2_for_url,
            )
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                print(f"✓ Downloaded successfully")
                cache['downloaded_urls'].append(url)
                downloaded += 1
            else:
                print(f"✗ Failed to download: {result.stderr}")
                failed += 1
                
        except Exception as e:
            print(f"✗ Error downloading {url}: {e}")
            failed += 1
        
        print()
    
    # Save cache
    save_cache_locked(cache)
    
    print(f"\n{'='*60}")
    print(f"Download complete!")
    print(f"  Downloaded: {downloaded}")
    print(f"  Skipped (cached): {skipped}")
    print(f"  Failed: {failed}")
    print(f"Cache saved to: {CACHE_PATH}")
    print(f"{'='*60}")

def main(argv: list[str] | None = None) -> int:
    """CLI entry point for scraper actions."""
    import argparse

    parser = argparse.ArgumentParser(description='Scrape and download videos from fapplepie.com')
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    parser.add_argument('--scrape', action='store_true', default=False, help='Scrape videos from fapplepie.com')
    parser.add_argument('--download', action='store_true', default=False, help='Download videos from URLs')
    parser.add_argument('--probe', action='store_true', default=False, help='Probe scraper connectivity without writing files')
    parser.add_argument('--scheduled', action='store_true', default=False, help=argparse.SUPPRESS)
    parser.add_argument('--all', action='store_true', default=False, help='Both scrape and download')
    parser.add_argument('--urls-file', default='video_urls.txt', help='File containing URLs (default: video_urls.txt)')
    parser.add_argument('--output-dir', default='downloads', help='Output directory for downloads (default: downloads)')
    parser.add_argument('--clear-cache', action='store_true', help='Clear the processing cache and start fresh')

    args = parser.parse_args(argv)

    # Handle --clear-cache flag
    if args.clear_cache:
        try:
            lock_file = _acquire_lock()
            if CACHE_PATH.exists():
                CACHE_PATH.unlink()
                print(f"Cache cleared: {CACHE_PATH}")
        finally:
            if 'lock_file' in locals():
                _release_lock(lock_file)
        return 0

    print(f"Fapplepie Downloader v{__version__}")
    try:
        _get_proxy_settings()
        _log_proxy_self_check()
    except ValueError as e:
        print(f"Proxy configuration error: {e}", file=sys.stderr)
        return 2

    # If no arguments specified, default to scraping only
    if not args.scrape and not args.download and not args.probe and not args.all:
        args.scrape = True

    # Handle --all flag
    if args.all:
        args.scrape = True
        args.download = True

    url = 'https://fapplepie.com/videos'

    if args.scheduled and (args.scrape or args.download):
        start_delay = float(os.environ.get("SCRAPE_START_DELAY_SECONDS", "0"))
        start_delay_jitter = float(
            os.environ.get("SCRAPE_START_DELAY_JITTER_SECONDS", "1800")
        )
        _sleep_with_jitter(
            base_seconds=start_delay,
            jitter_seconds=start_delay_jitter,
            reason="scrape start delay",
        )

    if args.probe:
        try:
            result = probe_scraper(url)
        except ProbeError as e:
            print(f"Probe failed: {e}", file=sys.stderr)
            return 4
        print(result.format_success())

    urls_file = args.urls_file
    if _running_in_docker():
        urls_file = str(BASE_DIR / 'video_urls.txt')

    if args.scrape:
        scrape_videos(url, urls_file)
        print()

    if args.download:
        download_videos(urls_file, args.output_dir)

    return 0


if __name__ == '__main__':
    sys.exit(main())
