"""Serve Billetto banners from our own bounded disk cache, downloaded on demand."""
from concurrent.futures import Future
from hashlib import sha256
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from threading import Lock
from time import time
from urllib.parse import urlsplit

from flask import abort, current_app, send_file, url_for
from itsdangerous import BadSignature, URLSafeSerializer
import requests

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_CACHE_BYTES = 128 * 1024 * 1024
MAX_CACHE_FILES = 256
CACHE_SECONDS = 24 * 60 * 60
_lock, _disk_lock, _inflight = Lock(), Lock(), {}


class ImageUnavailable(Exception):
    pass


def image_url(value):
    if not isinstance(value, str) or len(value) > 4096:
        return ""
    try:
        parts = urlsplit(value)
        if (parts.scheme == "https" and parts.hostname == "billetto.imgix.net"
                and not parts.username and not parts.password and parts.port in {None, 443}
                and parts.path not in {"", "/"}):
            return value
    except ValueError:
        pass
    return ""


def _mime(header):
    header = bytes(header)
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    if header[:6] in {b"GIF87a", b"GIF89a"}:
        return "image/gif"
    raise ImageUnavailable()


def _cached(path):
    try:
        if path.is_symlink() or not 0 < path.stat().st_size <= MAX_IMAGE_BYTES or time() - path.stat().st_mtime >= CACHE_SECONDS:
            return None
        with path.open("rb") as file:
            return path, _mime(file.read(32))
    except (OSError, ImageUnavailable):
        return None


def _prune(folder, keep):
    """Only touch our own directly contained hash-named cache files."""
    files = []
    for candidate in folder.glob("*.img"):
        try:
            if candidate.is_symlink() or not re.fullmatch(r"[a-f0-9]{64}\.img", candidate.name):
                continue
            stat = candidate.stat()
            files.append((stat.st_mtime, stat.st_size, candidate))
        except OSError:
            continue
    size, count = sum(item[1] for item in files), len(files)
    for modified, length, candidate in sorted(files):
        if candidate == keep:
            continue
        if time() - modified < CACHE_SECONDS and size <= MAX_CACHE_BYTES and count <= MAX_CACHE_FILES:
            continue
        try:
            candidate.unlink()
            size, count = size - length, count - 1
        except OSError:
            pass


def get_image(value, folder):
    value = image_url(value)
    if not value:
        raise ImageUnavailable()
    folder = Path(folder).resolve()
    path = folder / (sha256(value.encode()).hexdigest() + ".img")
    cached = _cached(path)
    if cached:
        return cached
    key = str(path)
    with _lock:
        future = _inflight.get(key)
        owner = future is None
        if owner:
            future = _inflight[key] = Future()
    if not owner:
        return future.result()
    temporary = None
    try:
        body = bytearray()
        # No API key, browser cookies or redirects are sent to image hosts.
        with requests.get(value, headers={"Accept": "image/webp,image/jpeg,image/png,image/gif",
                                         "User-Agent": "LillaKulturklubben/1.0"},
                          timeout=(3, 5), stream=True, allow_redirects=False) as response:
            if response.status_code != 200:
                raise ImageUnavailable()
            length = response.headers.get("Content-Length", "")
            if length.isdecimal() and int(length) > MAX_IMAGE_BYTES:
                raise ImageUnavailable()
            for chunk in response.iter_content(64 * 1024):
                body.extend(chunk)
                if len(body) > MAX_IMAGE_BYTES:
                    raise ImageUnavailable()
        mime = _mime(body[:32])  # Reject HTML/SVG and trust bytes rather than a remote Content-Type.
        folder.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=folder, prefix=path.stem + ".", suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            file.write(body)
        with _disk_lock:
            os.replace(temporary, path)
            temporary = None
            _prune(folder, path)
        result = path, mime
        future.set_result(result)
        return result
    except BaseException as error:
        safe_error = ImageUnavailable() if isinstance(error, (requests.RequestException, OSError, ImageUnavailable)) else error
        future.set_exception(safe_error)
        raise safe_error from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass
        with _lock:
            if _inflight.get(key) is future:
                del _inflight[key]


def _serializer():
    return URLSafeSerializer(current_app.secret_key, salt="billetto-image-v1")


def prepare_images(payload):
    for event in payload.get("events", []):
        original = image_url(event.get("image"))
        if original:
            event["image"] = url_for("billetto_image", token=_serializer().dumps(original)) if current_app.secret_key else ""
    return payload


def init_images(app):
    @app.get("/images/billetto/<token>")
    def billetto_image(token):
        if not current_app.secret_key or len(token) > 8192:
            abort(404)
        try:
            original = _serializer().loads(token)
            if not image_url(original):
                raise ImageUnavailable()
            path, mime = get_image(original, Path(current_app.instance_path) / "event-images" / "billetto")
        except (BadSignature, ImageUnavailable):
            abort(404)
        response = send_file(path, mimetype=mime, conditional=True, max_age=CACHE_SECONDS)
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
