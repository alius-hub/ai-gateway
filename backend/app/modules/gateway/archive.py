"""Best-effort, disk-spooled gateway call archives."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import shutil
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from sqlalchemy.exc import IntegrityError
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings
from app.db.models import GatewayLogSettings, RequestLog
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)
FILES = ("request.bin", "upstream_request.bin", "upstream_response.bin", "response.bin")


def headers(raw: list[tuple[bytes, bytes]]) -> list[list[str]]:
    # ASGI headers are bytes and can contain duplicates.
    return [[key.decode("latin-1"), value.decode("latin-1")] for key, value in raw]


class CallArchive:
    def __init__(self, scope: Scope, root: Path):
        self.request_id = f"req_{uuid4().hex}"
        self.directory = root / datetime.now(UTC).strftime("%Y/%m/%d") / self.request_id
        self.directory.mkdir(parents=True)
        self.files: dict[str, object] = {}
        self.failed = False
        self.manifest: dict = {
            "version": 1,
            "request_id": self.request_id,
            "created_at": datetime.now(UTC).isoformat(),
            "method": scope["method"],
            "path": scope["path"],
            "client_ip": scope["client"][0] if scope.get("client") else "unknown",
            "query_string": scope.get("query_string", b"").decode("latin-1"),
            "request_headers": headers(scope["headers"]),
            "files": [],
        }

    def write(self, name: str, data: bytes) -> None:
        if not data or self.failed:
            return
        try:
            if name not in self.files:
                self.files[name] = (self.directory / name).open("ab")
            self.files[name].write(data)
        except OSError:
            self.failed = True
            logger.exception("Gateway archive capture failed: %s", self.request_id)

    def upstream(self, request: httpx.Request, response: httpx.Response | None = None) -> None:
        self.manifest["upstream_url"] = str(request.url)
        self.manifest["upstream_request_headers"] = list(request.headers.multi_items())
        self.write("upstream_request.bin", request.content)
        if response is not None:
            self.upstream_response(response)

    def upstream_response(self, response: httpx.Response) -> None:
        self.manifest["upstream_status"] = response.status_code
        self.manifest["upstream_response_headers"] = list(response.headers.multi_items())

    def finish(self) -> None:
        for file in self.files.values():
            file.close()
        self.manifest["files"] = [
            name for name in FILES if (self.directory / name).exists()
        ]
        self.manifest["capture_complete"] = not self.failed
        (self.directory / "manifest.tmp").write_text(
            json.dumps(self.manifest, ensure_ascii=False), encoding="utf-8",
        )
        os.replace(self.directory / "manifest.tmp", self.directory / "manifest.pending")


class CallArchiveMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        settings = get_settings()
        if scope["type"] != "http" or not scope["path"].startswith(
            settings.gateway_api_prefix + "/"
        ) or not settings.log_archive_enabled:
            await self.app(scope, receive, send)
            return

        archive: CallArchive | None = None
        try:
            archive = CallArchive(scope, Path(settings.log_archive_spool_dir))
            scope["call_archive"] = archive
        except OSError:
            logger.exception("Unable to create gateway archive spool")

        async def captured_receive() -> Message:
            message = await receive()
            if archive and message["type"] == "http.request":
                try:
                    archive.write("request.bin", message.get("body", b""))
                except OSError:
                    logger.exception("Unable to spool request %s", archive.request_id)
            return message

        async def captured_send(message: Message) -> None:
            if archive:
                try:
                    if message["type"] == "http.response.start":
                        message["headers"] = [
                            *message["headers"],
                            (b"x-gateway-request-id", archive.request_id.encode()),
                        ]
                        archive.manifest["http_status"] = message["status"]
                        archive.manifest["response_headers"] = headers(message["headers"])
                    elif message["type"] == "http.response.body":
                        archive.write("response.bin", message.get("body", b""))
                except OSError:
                    logger.exception("Unable to spool response %s", archive.request_id)
            await send(message)

        try:
            await self.app(scope, captured_receive, captured_send)
        finally:
            if archive:
                try:
                    archive.manifest["db_recorded"] = scope.get("db_recorded", False)
                    archive.finish()
                except OSError:
                    logger.exception("Unable to finalize archive %s", archive.request_id)


def _image_urls(value: object, image_data: bool = False):
    if isinstance(value, dict):
        for key, item in value.items():
            if (key == "image_url" or key == "url" and image_data) and isinstance(
                item, str,
            ) and urlparse(item).scheme in {"http", "https"}:
                yield item
            else:
                yield from _image_urls(
                    item, image_data=(key in {"image_url", "data"} or image_data),
                )
    elif isinstance(value, list):
        for item in value:
            yield from _image_urls(item, image_data=image_data)


def _image_policy() -> str:
    with SessionLocal() as db:
        item = db.get(GatewayLogSettings, 1)
        return item.image_mode if item else "content_only"


def _allowed_image(url: str, hosts: list[str]) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname
    if not host or parsed.username or parsed.password or host == "localhost":
        return False
    try:
        address = ipaddress.ip_address(host)
        if address.is_loopback or address.is_link_local or address.is_unspecified:
            return False
    except ValueError:
        pass
    return not hosts or host in hosts


def s3_client():
    import boto3

    settings = get_settings()
    return boto3.client(
        "s3", endpoint_url=settings.log_archive_endpoint,
        aws_access_key_id=settings.log_archive_access_key,
        aws_secret_access_key=settings.log_archive_secret_key,
        region_name=settings.log_archive_region,
    )


def _record_unrouted(manifest: dict) -> None:
    if manifest.get("db_recorded") or not manifest.get("http_status"):
        return
    with SessionLocal() as db:
        if db.query(RequestLog.id).filter_by(request_id=manifest["request_id"]).first():
            return
        db.add(RequestLog(
            request_id=manifest["request_id"],
            public_model_name="(not routed)", model_type="unknown",
            endpoint=manifest["path"][:128], request_method=manifest["method"],
            requester_ip=manifest["client_ip"], http_status=manifest["http_status"],
        ))
        try:
            db.commit()
        except IntegrityError:
            # Another worker may have indexed the same spool directory.
            db.rollback()


def _upload(directory: Path, root: Path) -> None:
    from boto3.s3.transfer import TransferConfig

    settings = get_settings()
    manifest = json.loads((directory / "manifest.pending").read_text(encoding="utf-8"))
    client = s3_client()
    prefix = "/".join(filter(None, (
        settings.log_archive_prefix.strip("/"), directory.relative_to(root).as_posix(),
    )))
    transfer = TransferConfig(
        multipart_threshold=8 * 1024 * 1024, multipart_chunksize=8 * 1024 * 1024,
    )
    for name in manifest["files"]:
        client.upload_file(str(directory / name), settings.log_archive_bucket,
                           f"{prefix}/{name}", Config=transfer)
    manifest["image_mode"] = _image_policy()
    # Inline image bytes are already in raw files; fetch URLs only when enabled globally.
    urls: set[str] = set()
    if manifest["image_mode"] == "mirror_images":
        for name in ("request.bin", "upstream_response.bin"):
            source = directory / name
            if source.exists():
                with suppress(ValueError, UnicodeDecodeError):
                    urls.update(_image_urls(json.loads(source.read_bytes())))
    manifest["external_images"] = []
    with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as http:
        for index, url in enumerate(sorted(urls)):
            image = {"url": url, "saved": False}
            if not _allowed_image(url, settings.log_archive_image_hosts):
                image["error"] = "image URL is blocked"
                manifest["external_images"].append(image)
                continue
            try:
                with http.stream("GET", url) as response:
                    response.raise_for_status()
                    name = f"image_{index}.bin"
                    with (directory / name).open("wb") as output:
                        for chunk in response.iter_bytes():
                            output.write(chunk)
                client.upload_file(str(directory / name), settings.log_archive_bucket,
                                   f"{prefix}/{name}", Config=transfer)
                image["saved"] = True
                image["object"] = f"{prefix}/{name}"
            except Exception as exc:
                image["error"] = str(exc)
                logger.warning("Unable to archive external image for %s", prefix)
            manifest["external_images"].append(image)
    client.put_object(
        Bucket=settings.log_archive_bucket, Key=f"{prefix}/manifest.json",
        Body=json.dumps(manifest, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json",
    )
    _record_unrouted(manifest)
    shutil.rmtree(directory)


async def archive_worker() -> None:
    settings = get_settings()
    root = Path(settings.log_archive_spool_dir)
    root.mkdir(parents=True, exist_ok=True)
    while True:
        for pending in await asyncio.to_thread(lambda: list(root.rglob("manifest.pending"))):
            try:
                await asyncio.to_thread(_upload, pending.parent, root)
            except Exception:
                logger.exception("Gateway archive upload failed: %s", pending.parent)
        await asyncio.sleep(5)
