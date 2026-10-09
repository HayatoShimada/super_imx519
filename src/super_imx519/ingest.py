"""エッジ（imx519_edge）から撮影セッションを取り込む。

1. エッジの API でセッションの一覧と manifest（ファイル名・サイズ・sha256）を取る
2. ファイルを .partial-<id> に落としながら sha256 を計り、manifest と照合する
3. 全部一致したら <dest>/<session_id> に移し、エッジに DELETE を送る（manifest の sha256 を添える）

85pi は空きが少ないので、取り込んだらエッジ側は消す（--keep で残す）。

usage:
    uv run python -m super_imx519.ingest --edge https://85pi.taila713c8.ts.net:12443
"""

import argparse
import hashlib
import json
import shutil
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_DEST = Path("~/data/super_imx519/sessions").expanduser()
CHUNK = 1 << 20


class IngestError(Exception):
    pass


class Edge:
    def __init__(self, url: str, opener=None, timeout_s: float = 60.0):
        self.url = url.rstrip("/")
        self.opener = opener or urllib.request.urlopen
        self.timeout_s = timeout_s

    def _open(self, path: str, method: str = "GET"):
        req = urllib.request.Request(f"{self.url}{path}", method=method)
        return self.opener(req, timeout=self.timeout_s)

    def json(self, path: str, method: str = "GET"):
        with self._open(path, method) as res:
            return json.loads(res.read())

    def sessions(self) -> list[dict]:
        return self.json("/api/sessions")

    def manifest(self, session_id: str) -> dict:
        return self.json(f"/api/sessions/{session_id}/manifest")

    def download(self, session_id: str, name: str, target: Path) -> tuple[int, str]:
        """ファイルを target に書き、(サイズ, sha256) を返す。"""
        h, size = hashlib.sha256(), 0
        path = f"/api/sessions/{session_id}/files/{urllib.parse.quote(name)}"
        with self._open(path) as res, target.open("wb") as f:
            for chunk in iter(lambda: res.read(CHUNK), b""):
                f.write(chunk)
                h.update(chunk)
                size += len(chunk)
        return size, h.hexdigest()

    def delete(self, session_id: str, manifest_sha256: str) -> None:
        q = urllib.parse.urlencode({"manifest_sha256": manifest_sha256})
        self.json(f"/api/sessions/{session_id}?{q}", method="DELETE")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def matches(directory: Path, manifest: dict) -> bool:
    return all(
        (directory / f["name"]).is_file()
        and (directory / f["name"]).stat().st_size == f["size"]
        and sha256_file(directory / f["name"]) == f["sha256"]
        for f in manifest["files"]
    )


def ingest_session(edge: Edge, session_id: str, dest: Path, keep: bool = False) -> Path:
    manifest = edge.manifest(session_id)
    final = dest / session_id
    if final.exists():
        # 前回、取り込んだあとに消せなかった場合。中身が同じなら消すだけにする
        if not matches(final, manifest):
            raise IngestError(f"{final} は既にあり、中身がエッジと違います")
    else:
        partial = dest / f".partial-{session_id}"
        shutil.rmtree(partial, ignore_errors=True)
        partial.mkdir(parents=True)
        try:
            for f in manifest["files"]:
                size, digest = edge.download(session_id, f["name"], partial / f["name"])
                if (size, digest) != (f["size"], f["sha256"]):
                    raise IngestError(f"{session_id}/{f['name']} が manifest と一致しません")
            files = {k: v for k, v in manifest.items() if k != "sha256"}
            (partial / "manifest.json").write_text(json.dumps(files, indent=1))
            partial.rename(final)
        except BaseException:
            shutil.rmtree(partial, ignore_errors=True)
            raise
    if not keep:
        edge.delete(session_id, manifest["sha256"])
    return final


def ingest(edge: Edge, dest: Path, keep: bool = False) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    done = []
    for s in edge.sessions():
        path = ingest_session(edge, s["session_id"], dest, keep)
        print(f"{s['session_id']}: {s['shots']} 枚 → {path}")
        done.append(path)
    return done


def main() -> None:
    ap = argparse.ArgumentParser(prog="super_imx519.ingest")
    ap.add_argument("--edge", default="https://85pi.taila713c8.ts.net:12443")
    ap.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    ap.add_argument("--keep", action="store_true", help="取り込んだあともエッジに残す")
    args = ap.parse_args()
    done = ingest(Edge(args.edge), args.dest.expanduser(), args.keep)
    print(f"{len(done)} 件を取り込みました")


if __name__ == "__main__":
    main()
