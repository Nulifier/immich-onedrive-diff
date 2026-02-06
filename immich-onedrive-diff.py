#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.14"
# dependencies = ["requests", "tqdm", "dotenv"]
# ///

import os
import sys
import json
import requests
from pathlib import Path
from tqdm import tqdm
from dotenv import load_dotenv

# Load environment variables from a local .env file (if present)
load_dotenv()

# ===========================
# CONFIGURATION - EDIT THESE
# ===========================

# OneDrive / Microsoft Graph
# To get a token for testing, you can use the "Graph Explorer" at:
# https://developer.microsoft.com/en-us/graph/graph-explorer
GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
ONEDRIVE_ACCESS_TOKEN = os.getenv(
    "ONEDRIVE_ACCESS_TOKEN", "YOUR_GRAPH_ACCESS_TOKEN_HERE"
)
ONEDRIVE_CAMERA_ROLL_PATH = "/me/drive/root:/Pictures/Camera Roll:/children"

# OneDrive metadata cache
USE_ONEDRIVE_CACHE = True
ONEDRIVE_CACHE_FILE = Path("./onedrive_camera_roll_cache.json")

# --- Immich ---
IMMICH_BASE_URL = os.getenv("IMMICH_BASE_URL", "https://pics.example.com")
IMMICH_API_KEY = os.getenv("IMMICH_API_KEY", "YOUR_IMMICH_API_KEY_HERE")
IMMICH_PAGE_SIZE = int(os.getenv("IMMICH_PAGE_SIZE", "500"))

# Download folder
DOWNLOAD_FOLDER = Path("./immich_missing_files")


# ===========================
# IMMICH + ONEDRIVE HELPERS
# ===========================


def get_onedrive_camera_roll_files(refresh: bool = False):
    """
    Returns a list of OneDrive file metadata dicts in Camera Roll.

    - If caching is enabled and cache file exists (and refresh=False), load from cache.
    - Otherwise, fetch from Graph API and (optionally) write cache file.
    """
    if USE_ONEDRIVE_CACHE and not refresh and ONEDRIVE_CACHE_FILE.exists():
        try:
            print(f"Loading OneDrive metadata from cache: {ONEDRIVE_CACHE_FILE}")
            with ONEDRIVE_CACHE_FILE.open("r", encoding="utf-8") as f:
                items = json.load(f)
            # Filter only files (skip folders), just in case
            return [item for item in items if "file" in item]
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: failed to read cache ({e}), refetching from OneDrive...")

    print(
        "Fetching OneDrive Camera Roll metadata from Graph API (this may take a while)..."
    )
    headers = {"Authorization": f"Bearer {ONEDRIVE_ACCESS_TOKEN}"}
    url = GRAPH_API_BASE + ONEDRIVE_CAMERA_ROLL_PATH
    items = []

    while url:
        resp = requests.get(url, headers=headers)
        if resp.status_code != 200:
            print("Error querying OneDrive:", resp.status_code, resp.text)
            sys.exit(1)

        data = resp.json()
        items.extend(data.get("value", []))
        url = data.get("@odata.nextLink")

    if USE_ONEDRIVE_CACHE:
        try:
            print(f"Saving OneDrive metadata cache to {ONEDRIVE_CACHE_FILE}")
            with ONEDRIVE_CACHE_FILE.open("w", encoding="utf-8") as f:
                json.dump(items, f)
        except OSError as e:
            print(f"Warning: could not write cache file ({e})")

    return [i for i in items if "file" in i]


def get_immich_assets():
    """
    Returns a list of Immich assets using POST /search/metadata.

    - Sends JSON body with 'size' and 'page'
    - Follows pagination using 'assets.nextPage'
    - Collects data['assets']['items'][]
    """
    headers = {"x-api-key": IMMICH_API_KEY, "Content-Type": "application/json"}

    url = f"{IMMICH_BASE_URL}/api/search/metadata"
    assets = []
    page = 1

    while True:
        body = {"size": IMMICH_PAGE_SIZE, "page": page}
        resp = requests.post(url, headers=headers, json=body)
        if resp.status_code != 200:
            print("Error querying Immich:", resp.status_code, resp.text)
            sys.exit(1)

        data = resp.json()
        block = data.get("assets", {})
        items = block.get("items", [])

        if not items:
            break

        assets.extend(items)

        next_page = block.get("nextPage")
        if not next_page:
            break

        try:
            page = int(next_page)
        except (TypeError, ValueError):
            page += 1

    return assets


def get_immich_filenames(asset_list):
    """
    Extract filenames from Immich assets.
    Prefers 'originalFileName', falls back to path tail.
    """
    names = set()
    for a in asset_list:
        name = (
            a.get("originalFileName")
            or a.get("fileName")
            or a.get("originalPath", "").split("/")[-1]
        )
        if name:
            names.add(name)
    return names


def list_missing_files(onedrive_files, immich_filenames):
    """
    Compare sets and return list of OneDrive file metadata for items missing in Immich.
    """
    onedrive_names = set(f["name"] for f in onedrive_files)
    missing_names = onedrive_names - immich_filenames
    return [f for f in onedrive_files if f["name"] in missing_names]


# ===========================
# DOWNLOADER WITH TQDM
# ===========================


def download_onedrive_file(item, dest_folder, overall_pbar=None):
    """
    Download a single OneDrive file to dest_folder, using the 'content' endpoint.
    Uses tqdm for per-file and overall progress.
    """
    file_id = item["id"]
    name = item["name"]
    size = int(item.get("size", 0) or 0)

    dest_folder.mkdir(parents=True, exist_ok=True)
    dest_path = dest_folder / name

    if dest_path.exists():
        # File already downloaded; bump the overall bar as if we immediately had it
        if overall_pbar and size > 0:
            overall_pbar.update(size)
        return

    headers = {"Authorization": f"Bearer {ONEDRIVE_ACCESS_TOKEN}"}
    url = f"{GRAPH_API_BASE}/me/drive/items/{file_id}/content"

    with requests.get(url, headers=headers, stream=True) as r:
        if r.status_code not in (200, 302):
            print(f"Failed to download {name}: {r.status_code} {r.text}")
            if overall_pbar and size > 0:
                overall_pbar.update(size)
            return

        total = size if size > 0 else None

        with (
            open(dest_path, "wb") as f,
            tqdm(
                total=total,
                unit="B",
                unit_scale=True,
                desc=f"Downloading {name}",
                leave=False,
            ) as file_pbar,
        ):
            for chunk in r.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                f.write(chunk)
                chunk_len = len(chunk)
                file_pbar.update(chunk_len)
                if overall_pbar:
                    overall_pbar.update(chunk_len)


# ===========================
# MAIN
# ===========================


def main():
    if "YOUR_GRAPH_ACCESS_TOKEN_HERE" in ONEDRIVE_ACCESS_TOKEN:
        print(
            "ERROR: Set ONEDRIVE_TOKEN (or edit ONEDRIVE_ACCESS_TOKEN in the script)."
        )
        sys.exit(1)
    if "YOUR_IMMICH_API_KEY_HERE" in IMMICH_API_KEY:
        print("ERROR: Set IMMICH_API_KEY (or edit IMMICH_API_KEY in the script).")
        sys.exit(1)

    # Simple CLI flag to force-refresh OneDrive cache
    refresh_onedrive = "--refresh-onedrive" in sys.argv

    print("Getting OneDrive Camera Roll metadata...")
    onedrive_files = get_onedrive_camera_roll_files(refresh=refresh_onedrive)
    print(f"Found {len(onedrive_files)} files in OneDrive Camera Roll.")

    print(f"Fetching Immich assets in batches of {IMMICH_PAGE_SIZE}...")
    immich_assets = get_immich_assets()
    print(f"Found {len(immich_assets)} assets in Immich.")

    immich_names = get_immich_filenames(immich_assets)

    print("Comparing OneDrive vs Immich filenames...")
    missing_files = list_missing_files(onedrive_files, immich_names)

    if not missing_files:
        print("✅ No missing files! All Camera Roll filenames appear in Immich.")
        return

    print(f"⚠ Found {len(missing_files)} file(s) in OneDrive that are not in Immich:")
    for f in missing_files:
        print(" -", f["name"])

    answer = (
        input(
            f"\nDo you want to download these missing files to {DOWNLOAD_FOLDER.resolve()}? [y/N]: "
        )
        .strip()
        .lower()
    )

    if answer != "y":
        print("Okay, not downloading anything.")
        return

    total_size = 0
    for f in missing_files:
        try:
            total_size += int(f.get("size", 0) or 0)
        except (TypeError, ValueError):
            pass

    print("\nStarting downloads...\n")
    with tqdm(
        total=total_size if total_size > 0 else None,
        unit="B",
        unit_scale=True,
        desc="Overall Progress",
    ) as overall_pbar:
        for item in missing_files:
            download_onedrive_file(item, DOWNLOAD_FOLDER, overall_pbar)

    print("\n✅ All downloads complete.")


if __name__ == "__main__":
    main()
