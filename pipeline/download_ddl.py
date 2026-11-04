"""Download the DDL eCourts data, keeping only the CSV copies.

DDL publishes one Dropbox folder holding every table twice (csv/ and dta/). Dropbox builds the
5.1 GB zip on the fly and ignores HTTP range requests, so it cannot be indexed remotely. Instead this
script reads the zip as a stream and writes only the members it wants, which roughly halves the disk
needed. A member is accepted only if its size and CRC-32 match the zip's data descriptor.

Usage: python -I -u pipeline/download_ddl.py [--out data/raw/ddl]
"""
from __future__ import annotations

import argparse
import json
import shutil
import struct
import sys
import time
import zlib
from pathlib import Path

import requests

URL = "https://www.dropbox.com/sh/hkcde3z2l1h9mq1/AADRe-BuBQ92ozAJiG7YERdCa?dl=1"
LOCAL_SIG = b"PK\x03\x04"
CENTRAL_SIG = b"PK\x01\x02"
DESC_SIG = b"PK\x07\x08"
CHUNK = 1 << 20
MIN_FREE_BYTES = 1_500_000_000  # stop before the disk is full, not after


def wanted(name: str) -> bool:
    return not name.endswith("/") and not name.startswith("dta/")


def is_complete(done: dict[str, dict]) -> bool:
    """True once every table we need is on disk, so the rest of the stream can be skipped."""
    return all(any(table in name for name in done) for table in ("cases", "acts_sections", "judges", "keys"))


class Stream:
    """Buffered reader over the HTTP body."""

    def __init__(self, response: requests.Response) -> None:
        self.it = response.iter_content(CHUNK)
        self.buf = bytearray()
        self.total = 0

    def fill(self, need: int) -> bool:
        while len(self.buf) < need:
            try:
                chunk = next(self.it)
            except StopIteration:
                return False
            self.total += len(chunk)
            self.buf += chunk
        return True

    def take(self, n: int) -> bytes:
        if not self.fill(n):
            raise EOFError("stream ended early")
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out


def read_member(s: Stream, sink, crc_seed: int = 0) -> tuple[int, int]:
    """Copy one stored member of unknown length to sink. Returns (size, crc).

    The member ends at the first data descriptor whose recorded size and CRC match what has been read
    and which is followed by another zip record. Those checks reject signature bytes that occur by
    chance inside the compressed payload.
    """
    size, crc = 0, crc_seed
    while True:
        s.fill(64 * 1024)
        pos = bytes(s.buf).find(DESC_SIG)
        if pos < 0:
            # Keep 3 bytes back in case the signature straddles this read and the next.
            n = max(0, len(s.buf) - 3)
            if n == 0:
                raise EOFError("stream ended inside a member")
            block = bytes(s.buf[:n])
            sink.write(block)
            crc = zlib.crc32(block, crc)
            size += n
            del s.buf[:n]
            continue
        if pos:
            block = bytes(s.buf[:pos])
            sink.write(block)
            crc = zlib.crc32(block, crc)
            size += pos
            del s.buf[:pos]
        s.fill(32)
        head = bytes(s.buf[:32])
        got_crc = struct.unpack("<I", head[4:8])[0]
        for fmt, width in (("<II", 8), ("<QQ", 16)):
            csize, usize = struct.unpack(fmt, head[8:8 + width])
            nxt = head[8 + width:12 + width]
            if csize == size and usize == size and got_crc == crc and nxt in (LOCAL_SIG, CENTRAL_SIG):
                del s.buf[:8 + width]
                return size, crc
        # False positive: this signature was payload data.
        sink.write(head[:4])
        crc = zlib.crc32(head[:4], crc)
        size += 4
        del s.buf[:4]


class Discard:
    def write(self, _: bytes) -> None:
        pass


def run(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "manifest.json"
    done: dict[str, dict] = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    r = requests.get(URL, stream=True, timeout=(30, 180))
    r.raise_for_status()
    total = int(r.headers.get("Content-Length", 0))
    print(f"archive size {total / 1e9:.2f} GB; already have {len(done)} members", flush=True)
    s = Stream(r)
    t0 = time.time()
    while True:
        if is_complete(done):
            print("all required tables present; ending the download early", flush=True)
            break
        sig = s.take(4)
        if sig == CENTRAL_SIG:
            break
        if sig != LOCAL_SIG:
            raise ValueError(f"unexpected record {sig!r} at byte {s.total}")
        _, flag, comp, _, _, _, _, _, nlen, elen = struct.unpack("<HHHHHIIIHH", s.take(26))
        name = s.take(nlen).decode()
        s.take(elen)
        if name.endswith("/"):
            continue  # directories carry no data (or descriptor when flag bit 3 is unset)
        if comp != 0 or not flag & 8:
            raise ValueError(f"{name}: expected a stored member with a data descriptor")
        keep = wanted(name) and name not in done
        print(f"[{time.time() - t0:7.0f}s] {s.total / 1e9:5.2f}/{total / 1e9:.2f} GB  "
              f"{'saving ' if keep else 'skipping'} {name}", flush=True)
        if keep:
            free = shutil.disk_usage(out).free
            if free < MIN_FREE_BYTES:
                sys.exit(f"only {free / 1e9:.1f} GB free; stopping before the disk fills")
            dest = out / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            part = dest.with_name(dest.name + ".part")
            with open(part, "wb", buffering=CHUNK) as fh:
                size, crc = read_member(s, fh)
            part.replace(dest)
            done[name] = {"bytes": size, "crc32": crc}
            manifest_path.write_text(json.dumps(done, indent=1))
            print(f"          ok {size / 1e6:,.0f} MB crc={crc:08x}", flush=True)
        else:
            read_member(s, Discard())
    r.close()
    print(f"done in {(time.time() - t0) / 60:.1f} min; {len(done)} members", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("data/raw/ddl"))
    run(ap.parse_args().out)
