# Immich OneDrive Diff

A small utility to compare an Immich media library against a OneDrive camera
roll export and collect files that are present in OneDrive but missing from
Immich.

## Features
- Compare an Immich export to a OneDrive camera roll
- Collect missing files into a target directory for review or re-import
- Cache metadata from OneDrive rather than requesting it each time

## Requirements

- Python 3.14 or newer (Didn't test with lower versions)
- [UV](https://docs.astral.sh/uv/guides/scripts/) for dependencies (Or add them
  manually)

## Usage

Run the script with the system Python interpreter:

```sh
./immich-onedrive-diff.py
# OR
uv run immich-onedrive-diff.py
```

The utility downloads the OneDrive metadata (unless
`onedrive_camera_roll_cache.json` exists or a refresh is explicity requested
with the `--refresh-onedrive` CLI option) and writes any detected missing files
into the `immich_missing_files/` directory.

I find sometimes downloading the images from OneDrive fails but just run it a
couple times or look at those files individually to figure out what the issue
is. The intent of this script was to manage moving thousands of pictures, so a
couple manual steps wasn't too bad.
