"""The downloader reads a Dropbox zip as a stream, finding where each member ends without knowing its length."""
import io
import struct
import sys
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from download_ddl import CENTRAL_SIG, DESC_SIG, LOCAL_SIG, Stream, is_complete, read_member, wanted  # noqa: E402


class FakeResponse:
    def __init__(self, data: bytes, chunk: int = 1000):
        self.data, self.chunk = data, chunk

    def iter_content(self, _size):
        for i in range(0, len(self.data), self.chunk):
            yield self.data[i:i + self.chunk]


def descriptor(payload: bytes, wide: bool = False) -> bytes:
    crc = zlib.crc32(payload)
    sizes = struct.pack("<QQ", len(payload), len(payload)) if wide else struct.pack("<II", len(payload), len(payload))
    return DESC_SIG + struct.pack("<I", crc) + sizes


@pytest.mark.parametrize("wide", [False, True])
@pytest.mark.parametrize("chunk", [7, 1000, 1 << 20])
def test_member_is_recovered_exactly(wide, chunk):
    payload = bytes(range(256)) * 500
    stream = payload + descriptor(payload, wide) + LOCAL_SIG + b"\0" * 100
    sink = io.BytesIO()
    size, crc = read_member(Stream(FakeResponse(stream, chunk)), sink)
    assert sink.getvalue() == payload
    assert size == len(payload)
    assert crc == zlib.crc32(payload)


def test_signature_bytes_inside_the_payload_are_not_mistaken_for_the_end():
    # Compressed data can contain these four bytes by chance, so size and CRC must also match.
    payload = b"before" + DESC_SIG + b"\x01\x02\x03\x04" * 8 + b"after" + DESC_SIG + b"x" * 200
    stream = payload + descriptor(payload) + CENTRAL_SIG + b"\0" * 100
    sink = io.BytesIO()
    size, _ = read_member(Stream(FakeResponse(stream, 16)), sink)
    assert sink.getvalue() == payload
    assert size == len(payload)


def test_truncated_stream_raises():
    with pytest.raises(EOFError):
        read_member(Stream(FakeResponse(b"no descriptor anywhere" * 10)), io.BytesIO())


def test_only_csv_members_are_kept():
    assert wanted("csv/cases/cases.tar.gz")
    assert wanted("license.txt")
    assert not wanted("dta/cases/cases.tar.gz")
    assert not wanted("csv/")


def test_download_stops_once_every_table_is_saved():
    done = {"csv/cases/cases.tar.gz": {}, "csv/keys/keys.tar.gz": {}, "csv/judges_clean.tar.gz": {}}
    assert not is_complete(done)
    done["csv/acts_sections.tar.gz"] = {}
    assert is_complete(done)
