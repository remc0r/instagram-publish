"""Minimal client for the Instagram Content Publishing API."""
from __future__ import annotations

import os
import re
import tempfile
import time
import warnings
from pathlib import Path, PurePosixPath
from typing import Sequence, Union
from urllib.parse import urlparse

import requests

DEFAULT_API_VERSION = "v26.0"
HOSTS = {
    "instagram": "https://graph.instagram.com",  # Instagram Login: no Facebook Page needed
    "facebook": "https://graph.facebook.com",  # Facebook Login: needs a linked Page
}
VIDEO_EXTENSIONS = {".mp4", ".mov"}
CAROUSEL_MIN, CAROUSEL_MAX = 2, 10
_API_VERSION_RE = re.compile(r"v\d+\.\d+")
_NUMERIC_ID_RE = re.compile(r"\d+")


class InstagramError(Exception):
    """Raised when the Graph API or a container reports an error.

    `result` carries the API response when it matters (e.g. a refreshed token
    that could not be saved), so the caller does not lose it.
    """

    def __init__(self, message: str, result: dict | None = None) -> None:
        super().__init__(message)
        self.result = result


def _is_video(url: str) -> bool:
    return PurePosixPath(urlparse(url).path).suffix.lower() in VIDEO_EXTENSIONS


def _check_media_url(url: object) -> str:
    if not isinstance(url, str):
        raise InstagramError("Media must be given as URL strings.")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise InstagramError("Media must be public HTTPS URLs (Instagram downloads them itself).")
    return url


def _noop_auth(request):
    # Setting any session auth stops requests from reading ~/.netrc, which would
    # otherwise override our Authorization header.
    return request


class InstagramClient:
    """Publish media on an Instagram Business/Creator account.

    Media must be given as public HTTPS URLs: Instagram downloads them itself.
    The token is read from IG_ACCESS_TOKEN and the account id from IG_USER_ID
    unless passed explicitly. The token is sent in an Authorization header, not
    in the URL, except for refresh_token(), which uses the query parameter
    documented by Meta (so that URL may show up in debug logs or proxies).

    `token_file` makes token storage automatic: if the file exists it is the
    source of truth (it wins over `access_token` and IG_ACCESS_TOKEN), and
    refresh_token() rewrites it (mode 600) with the new token.

    `login` selects the token flavour: "instagram" (default, token generated in
    the app dashboard) or "facebook" (token from the Graph API Explorer).

    Redirects are not followed. Proxy environment variables (HTTPS_PROXY,
    REQUESTS_CA_BUNDLE) are honoured as usual: the token goes through them.
    """

    def __init__(
        self,
        access_token: str | None = None,
        user_id: str | None = None,
        api_version: str = DEFAULT_API_VERSION,
        login: str = "instagram",
        token_file: str | os.PathLike | None = None,
        timeout: float = 30,
        poll_interval: float = 3,
        poll_timeout: float = 300,
    ) -> None:
        self.user_id = (user_id or os.environ.get("IG_USER_ID", "")).strip()
        self.token_file = Path(token_file).expanduser() if token_file else None
        token = (
            self._read_token_file()
            or (access_token or "").strip()
            or os.environ.get("IG_ACCESS_TOKEN", "").strip()
        )
        if not token or not self.user_id:
            raise InstagramError("Missing IG_ACCESS_TOKEN or IG_USER_ID (env var or argument).")
        if not _NUMERIC_ID_RE.fullmatch(self.user_id):
            raise InstagramError("IG_USER_ID must be numeric.")
        if not _API_VERSION_RE.fullmatch(api_version):
            raise InstagramError("api_version must look like 'v26.0'.")
        if login not in HOSTS:
            raise InstagramError(f"login must be one of {sorted(HOSTS)}.")
        self.login = login
        self.base_url = HOSTS[login]
        self.api_version = api_version
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout
        self.session = requests.Session()
        self.session.auth = _noop_auth
        self._set_token(token, persist=False)

    # -- public API ---------------------------------------------------------

    def publish(
        self,
        media: Union[str, Sequence[str]],
        caption: str = "",
        *,
        is_ai_generated: bool = False,
        story: bool = False,
    ) -> str:
        """Publish one URL (photo or Reel), 2-10 URLs (carousel) or one Story. Returns the media id."""
        urls = [media] if isinstance(media, str) else list(media)
        if not urls:
            raise InstagramError("No media given.")
        urls = [_check_media_url(u) for u in urls]
        if story and len(urls) != 1:
            raise InstagramError("A story takes exactly one photo or video.")
        if story and caption:
            raise InstagramError("A story cannot have a caption.")
        extra = {"is_ai_generated": "true"} if is_ai_generated else {}

        if story:
            url = urls[0]
            fields = {"video_url": url} if _is_video(url) else {"image_url": url}
            container = self._create_container({**fields, "media_type": "STORIES", **extra})
        elif len(urls) == 1:
            url = urls[0]
            fields = {"video_url": url, "media_type": "REELS"} if _is_video(url) else {"image_url": url}
            container = self._create_container({**fields, "caption": caption, **extra})
        else:
            if not CAROUSEL_MIN <= len(urls) <= CAROUSEL_MAX:
                raise InstagramError(f"A carousel needs {CAROUSEL_MIN} to {CAROUSEL_MAX} items.")
            children = []
            for url in urls:
                fields = {"video_url": url, "media_type": "VIDEO"} if _is_video(url) else {"image_url": url}
                child = self._create_container({**fields, "is_carousel_item": "true"})
                self._wait_until_ready(child)  # the parent fails with code 2 if a video child isn't ready
                children.append(child)
            container = self._create_container(
                {"media_type": "CAROUSEL", "children": ",".join(children), "caption": caption, **extra}
            )

        self._wait_until_ready(container)
        body = self._request("POST", f"{self.user_id}/media_publish", data={"creation_id": container})
        return self._field(body, "id")

    def refresh_token(self) -> dict:
        """Refresh a long-lived Instagram Login token (valid 60 more days).

        Returns {"access_token": ..., "token_type": ..., "expires_in": seconds}.
        The token must be older than 24h and not expired. The client uses the new
        token immediately. If `token_file` is set it is rewritten; if that fails,
        InstagramError is raised with the response in `.result` so nothing is lost.
        """
        if self.login != "instagram":
            raise InstagramError("Token refresh only exists for the Instagram Login flow.")
        result = self._request(
            "GET",
            "refresh_access_token",
            versioned=False,
            params={"grant_type": "ig_refresh_token", "access_token": self._token},
        )
        new_token = self._field(result, "access_token")
        self._set_token(new_token, persist=False)
        if self.token_file:
            try:
                self._write_token_file(new_token)
            except OSError as exc:
                raise InstagramError(
                    f"Token refreshed but could not be saved to {self.token_file}: {exc.strerror}", result
                ) from None
        return result

    # -- internals ----------------------------------------------------------

    def _read_token_file(self) -> str:
        path = self.token_file
        if not path or not path.is_file():
            return ""
        if os.name == "posix" and path.stat().st_mode & 0o077:
            warnings.warn(f"{path} is readable by other users: run chmod 600 on it.", stacklevel=3)
        token = path.read_text(encoding="utf-8").strip()
        if not token:
            warnings.warn(f"{path} is empty and was ignored.", stacklevel=3)
        return token

    def _write_token_file(self, token: str) -> None:
        # Resolve symlinks so the target is updated in place, then write a private
        # temp file in the same directory and swap it in atomically.
        target = self.token_file.resolve()
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")  # created with mode 600
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(token)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def _set_token(self, token: str, persist: bool = True) -> None:
        self._token = token
        self.session.headers["Authorization"] = f"Bearer {token}"
        if persist and self.token_file:
            self._write_token_file(token)

    @staticmethod
    def _field(body: dict, key: str) -> str:
        value = body.get(key)
        if not isinstance(value, str) or not value:
            raise InstagramError(f"Unexpected API response: missing '{key}'.")
        return value

    def _request(self, method: str, path: str, versioned: bool = True, **kwargs) -> dict:
        prefix = f"{self.api_version}/" if versioned else ""
        url = f"{self.base_url}/{prefix}{path}"
        try:
            response = self.session.request(
                method, url, timeout=self.timeout, allow_redirects=False, **kwargs
            )
        except requests.RequestException as exc:
            raise InstagramError(f"Network error on {path}: {type(exc).__name__}") from None
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            body = {}
        if response.status_code >= 300 or "error" in body:
            err = body.get("error")
            err = err if isinstance(err, dict) else {}
            raise InstagramError(
                f"{path} failed (HTTP {response.status_code}): "
                f"{err.get('message', 'unknown error')} (code {err.get('code')})"
            )
        return body

    def _create_container(self, fields: dict) -> str:
        return self._field(self._request("POST", f"{self.user_id}/media", data=fields), "id")

    def _wait_until_ready(self, container_id: str) -> None:
        deadline = time.monotonic() + self.poll_timeout
        while True:
            status = self._request("GET", container_id, params={"fields": "status_code,status"})
            code = status.get("status_code")
            if code == "FINISHED":
                return
            if code in ("ERROR", "EXPIRED"):
                raise InstagramError(f"Container {container_id} {code}: {status.get('status', '')}")
            if time.monotonic() >= deadline:
                raise InstagramError(f"Container {container_id} not ready after {self.poll_timeout}s.")
            time.sleep(self.poll_interval)
