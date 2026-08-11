import hashlib
import mimetypes
import os

import boto3
from botocore.client import Config

from .settings import (
    PUBLIC_DIR,
    S3_ACCESS_KEY_ID,
    S3_ACL,
    S3_ASSET_CACHE_CONTROL,
    S3_BUCKET,
    S3_DELETE_ORPHANS,
    S3_ENDPOINT_URL,
    S3_EXCLUDE,
    S3_HTML_CACHE_CONTROL,
    S3_PREFIX,
    S3_REGION,
    S3_SECRET_ACCESS_KEY,
    require_s3_settings,
)

# Explicit types for everything the site actually serves — mimetypes' guesses
# vary by platform (and by whichever /etc/mime.types the base image ships),
# and a wrong Content-Type here means a browser refuses the stylesheet.
CONTENT_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}

# These get the short Cache-Control — they are rewritten on every refresh
GENERATED_EXTENSIONS = (".html", ".json")


def content_type_for(path: str) -> str:
    """
    Determine the Content-Type to serve a file as
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in CONTENT_TYPES:
        return CONTENT_TYPES[ext]
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


def cache_control_for(path: str) -> str:
    """
    Determine the Cache-Control to serve a file with
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in GENERATED_EXTENSIONS:
        return S3_HTML_CACHE_CONTROL
    return S3_ASSET_CACHE_CONTROL


def md5_of(path: str) -> str:
    """
    Hash a file, to compare against the object's ETag
    """
    # not a security hash — it only has to match how S3 computes an ETag
    digest = hashlib.md5(usedforsecurity=False)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def local_files(source_dir: str):
    """
    Map every publishable file under source_dir to its object key
    """
    files = {}
    for dirpath, dirnames, filenames in os.walk(source_dir):
        # don't descend into VCS/editor cruft
        dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__")]
        for filename in filenames:
            if filename in S3_EXCLUDE:
                continue
            path = os.path.join(dirpath, filename)
            relpath = os.path.relpath(path, source_dir).replace(os.sep, "/")
            key = f"{S3_PREFIX}/{relpath}" if S3_PREFIX else relpath
            files[key] = path
    return files


def remote_etags(client):
    """
    Map every object key already in the bucket to its ETag
    """
    etags = {}
    paginator = client.get_paginator("list_objects_v2")
    kwargs = {"Bucket": S3_BUCKET}
    if S3_PREFIX:
        kwargs["Prefix"] = f"{S3_PREFIX}/"
    for page in paginator.paginate(**kwargs):
        for obj in page.get("Contents", []):
            etags[obj["Key"]] = obj["ETag"].strip('"')
    return etags


def get_client():
    """
    Build an S3 client pointed at the configured endpoint
    """
    require_s3_settings()
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT_URL,
        region_name=S3_REGION,
        aws_access_key_id=S3_ACCESS_KEY_ID,
        aws_secret_access_key=S3_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4", retries={"max_attempts": 5}),
    )


def publish(source_dir: str = None):
    """
    Sync the generated site to the bucket, uploading only what changed and
    (optionally) removing objects that no longer exist locally
    """
    source_dir = source_dir or PUBLIC_DIR
    if not os.path.isdir(source_dir):
        raise Exception(f"nothing to publish, {source_dir} does not exist")

    client = get_client()
    files = local_files(source_dir)
    if not files:
        raise Exception(f"nothing to publish, {source_dir} is empty")
    etags = remote_etags(client)

    uploaded = skipped = deleted = 0
    for key, path in sorted(files.items()):
        # Every object is written with a single put_object, so the ETag is a
        # plain md5 of the body — that equivalence would NOT hold for a
        # multipart upload, where the ETag is a hash-of-hashes plus a part
        # count. Keep uploads single-part or this comparison silently
        # re-uploads everything on every run.
        digest = md5_of(path)
        if etags.get(key) == digest:
            skipped += 1
            continue
        with open(path, "rb") as body:
            kwargs = {
                "Bucket": S3_BUCKET,
                "Key": key,
                "Body": body,
                "ContentType": content_type_for(path),
                "CacheControl": cache_control_for(path),
            }
            # only sent when explicitly configured — a bucket with ACLs
            # disabled rejects the request outright rather than ignoring it
            if S3_ACL:
                kwargs["ACL"] = S3_ACL
            client.put_object(**kwargs)
        print(f"  ↑ {key}")
        uploaded += 1

    if S3_DELETE_ORPHANS:
        orphans = sorted(set(etags) - set(files))
        # delete_objects takes at most 1000 keys per call
        for batch_start in range(0, len(orphans), 1000):
            batch = orphans[batch_start : batch_start + 1000]
            client.delete_objects(
                Bucket=S3_BUCKET,
                Delete={"Objects": [{"Key": key} for key in batch]},
            )
            for key in batch:
                print(f"  ✗ {key}")
            deleted += len(batch)

    print(
        f"📦 published to {S3_BUCKET} "
        f"({uploaded} uploaded, {skipped} unchanged, {deleted} deleted)"
    )
    return {"uploaded": uploaded, "skipped": skipped, "deleted": deleted}
