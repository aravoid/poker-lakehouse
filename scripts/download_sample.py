"""Download a sample of REAL poker hand histories (PHH format) for the pipeline.

Source: the open PHH dataset from the University of Toronto Computer Poker Student Research
Group (https://github.com/uoftcprg/phh-dataset, MIT license; full data on Zenodo). The files
used here are anonymized PokerStars hand histories from July 2009 ($1/$2 no-limit hold'em,
about 1,000 hands per file).

    python scripts/download_sample.py --files 40 --out data/raw
"""
import argparse
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = ("https://raw.githubusercontent.com/uoftcprg/phh-dataset/main/data/handhq/"
        "PS-2009-07-01_2009-07-23_200NLH_OBFU/2/")


def fetch(i, out):
    name = f"ps NLH handhq_{i}-OBFUSCATED.phhs"
    dest = out / f"ps_{i:04d}.phhs"
    if dest.exists() and dest.stat().st_size > 1000:
        return dest
    for attempt in range(3):
        try:
            with urllib.request.urlopen(BASE + urllib.parse.quote(name), timeout=60) as r:
                dest.write_bytes(r.read())
            return dest
        except Exception as e:  # network hiccup: retry
            err = e
            time.sleep(2 * (attempt + 1))
    print(f"failed: {name}: {err}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", type=int, default=40, help="number of ~1,000-hand files")
    ap.add_argument("--out", default="data/raw")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(8) as ex:
        done = [p for p in ex.map(lambda i: fetch(i, out), range(1, a.files + 1)) if p]
    print(f"downloaded {len(done)} files to {out}")
