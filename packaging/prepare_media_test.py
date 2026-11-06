"""Prepare the same noncommercial-compatible media packages used in releases."""
from concurrent.futures import ThreadPoolExecutor
from prepare_release_media import PACKAGES, install

if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(install, [("mac-arm64", name) for name in PACKAGES]))
    print("Use SUCAIYU_MEDIA_LIBS=.build/release-media-noncommercial/mac-arm64")
