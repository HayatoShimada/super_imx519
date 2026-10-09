import hashlib
import io
import json
import urllib.parse

import pytest

from super_imx519.ingest import Edge, IngestError, ingest


class FakeEdge:
    """imx519_edge の取り込み用 API の代わり（urlopen と同じ形で呼ばれる）。"""

    def __init__(self, files: dict[str, bytes], session_id: str = "2026-10-09_120000_c42"):
        self.session_id = session_id
        self.files = files
        self.deleted = []
        entries = [
            {"name": n, "size": len(b), "sha256": hashlib.sha256(b).hexdigest()}
            for n, b in sorted(files.items())
        ]
        self.manifest = {"session_id": session_id, "files": entries}
        self.manifest_sha = hashlib.sha256(json.dumps(self.manifest).encode()).hexdigest()
        self.corrupt: str | None = None

    def __call__(self, req, timeout=None):
        url = urllib.parse.urlparse(req.full_url)
        path, query = url.path, urllib.parse.parse_qs(url.query)
        sid = self.session_id
        if req.get_method() == "DELETE":
            assert query["manifest_sha256"] == [self.manifest_sha]
            self.deleted.append(sid)
            return io.BytesIO(json.dumps({"deleted": sid}).encode())
        if path == "/api/sessions":
            return io.BytesIO(json.dumps([{"session_id": sid, "shots": 1}]).encode())
        if path == f"/api/sessions/{sid}/manifest":
            return io.BytesIO(json.dumps({**self.manifest, "sha256": self.manifest_sha}).encode())
        name = urllib.parse.unquote(path.rsplit("/", 1)[-1])
        data = self.files[name]
        if name == self.corrupt:
            data = data[:-1] + b"X"
        return io.BytesIO(data)


FILES = {"p00_ev+0.0_00.dng": b"dng" * 1000, "p00_ev+0.0_00.json": b"{}", "session.json": b"{}"}


def test_ingest_downloads_verifies_and_deletes(tmp_path):
    fake = FakeEdge(FILES)
    [path] = ingest(Edge("https://edge", opener=fake), tmp_path)
    assert path == tmp_path / fake.session_id
    assert {p.name for p in path.iterdir()} == {*FILES, "manifest.json"}
    assert (path / "p00_ev+0.0_00.dng").read_bytes() == FILES["p00_ev+0.0_00.dng"]
    assert fake.deleted == [fake.session_id]


def test_corrupt_file_is_not_kept_and_edge_is_not_deleted(tmp_path):
    fake = FakeEdge(FILES)
    fake.corrupt = "p00_ev+0.0_00.dng"
    with pytest.raises(IngestError):
        ingest(Edge("https://edge", opener=fake), tmp_path)
    assert list(tmp_path.iterdir()) == []
    assert fake.deleted == []


def test_keep_leaves_edge_and_rerun_only_deletes(tmp_path):
    fake = FakeEdge(FILES)
    ingest(Edge("https://edge", opener=fake), tmp_path, keep=True)
    assert fake.deleted == []
    ingest(Edge("https://edge", opener=fake), tmp_path)  # 既にあって中身が同じなら、消すだけ
    assert fake.deleted == [fake.session_id]
