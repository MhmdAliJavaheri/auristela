#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Download last 10 IMAGE posts from an Instagram professional account (Business/Creator)
using the official Instagram Graph API Business Discovery endpoint.

Usage:
    python ig_dl_last10.py --username TARGET_USERNAME [--limit 10] [--out ./downloads]

Env vars required:
    ACCESS_TOKEN : Long-lived Facebook Graph access token with instagram_basic, pages_show_list
    IG_USER_ID   : Your own IG Business/Creator user id (connected to your FB Page)
    DOWNLOAD_DIR : (optional) default output dir
"""

import os
import sys
import argparse
import pathlib
import mimetypes
import requests
from urllib.parse import urlencode
from datetime import datetime
from dotenv import load_dotenv

GRAPH_VERSION = "v19.0"  # update if needed
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"


def ensure_dir(p: pathlib.Path):
    p.mkdir(parents=True, exist_ok=True)


def infer_ext_from_ct(content_type: str) -> str:
    if not content_type:
        return ".jpg"
    ext = mimetypes.guess_extension(content_type.split(";")[0].strip())
    # fallback to jpg if unknown
    return ext or ".jpg"


def build_fields(username: str, limit: int):
    # Ask for up to 'limit' media; Graph may cap page size (often 25).
    # We'll request 50 to increase chance of getting 10 images without extra pagination.
    page_size = max(limit, 25)
    page_size = min(page_size, 50)
    media_fields = "id,media_type,media_url,permalink,timestamp,children{media_type,media_url,id,timestamp}"
    return f"business_discovery.username({username}){{media.limit({page_size}){{{media_fields}}}}}"


def download(url: str, out_path: pathlib.Path, session: requests.Session):
    r = session.get(url, timeout=30)
    r.raise_for_status()
    ext = infer_ext_from_ct(r.headers.get("Content-Type"))
    out_file = out_path.with_suffix(ext)
    with open(out_file, "wb") as f:
        f.write(r.content)
    return out_file


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Download last N Instagram images via Graph API (Business Discovery).")
    parser.add_argument("--username", required=True, help="Target Instagram username (Business/Creator, public).")
    parser.add_argument("--limit", type=int, default=10, help="Number of images to download.")
    parser.add_argument("--out", default=os.getenv("DOWNLOAD_DIR", "./downloads"), help="Output directory.")
    args = parser.parse_args()

    access_token = os.getenv("ACCESS_TOKEN")
    ig_user_id = os.getenv("IG_USER_ID")
    if not access_token or not ig_user_id:
        print("ERROR: Please set ACCESS_TOKEN and IG_USER_ID in environment or .env file.", file=sys.stderr)
        sys.exit(2)

    out_dir = pathlib.Path(args.out).expanduser().resolve()
    ensure_dir(out_dir)

    session = requests.Session()

    # Query Business Discovery for recent media
    fields = build_fields(args.username, max(args.limit, 25))
    params = {
        "fields": fields,
        "access_token": access_token
    }
    url = f"{GRAPH_BASE}/{ig_user_id}"
    try:
        resp = session.get(url, params=params, timeout=30)
        resp.raise_for_status()
    except requests.HTTPError as e:
        print("HTTP error from Graph API:", e, file=sys.stderr)
        print("Response:", getattr(e, "response", None).text if getattr(e, "response", None) else "", file=sys.stderr)
        sys.exit(1)

    data = resp.json()
    bd = data.get("business_discovery")
    if not bd or "media" not in bd:
        print("No media returned. Check that target is a public Business/Creator account and permissions are correct.",
              file=sys.stderr)
        sys.exit(1)

    media_items = bd["media"].get("data", [])
    saved = 0
    for m in media_items:
        if saved >= args.limit:
            break

        mtype = m.get("media_type")
        ts = m.get("timestamp") or ""
        ts_safe = ts.replace(":", "-") if ts else datetime.utcnow().isoformat()
        mid = m.get("id")

        # helper to save one image url
        def save_image(img_url, suffix=""):
            nonlocal saved
            if saved >= args.limit:
                return
            base_name = f"{args.username}_{ts_safe}_{mid}{suffix}"
            out_path = out_dir / base_name
            try:
                file_path = download(img_url, out_path, session)
                print(f"Saved: {file_path}")
                saved += 1
            except Exception as e:
                print(f"Failed to download {img_url}: {e}", file=sys.stderr)

        if mtype == "IMAGE":
            url_img = m.get("media_url")
            if url_img:
                save_image(url_img)
        elif mtype == "CAROUSEL_ALBUM":
            # Prefer children images (skip VIDEO children)
            children = (m.get("children") or {}).get("data", [])
            for idx, ch in enumerate(children):
                if saved >= args.limit:
                    break
                if ch.get("media_type") == "IMAGE" and ch.get("media_url"):
                    save_image(ch["media_url"], suffix=f"_{idx + 1}")
        else:
            # Skip VIDEO for this task
            continue

    if saved == 0:
        print("No images found on the first page of media. The account may have only videos or access is limited.",
              file=sys.stderr)
    else:
        print(f"Done. Total images saved: {saved}")


if __name__ == "__main__":
    main()
