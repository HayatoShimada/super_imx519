"""スタジオ（home-linux で常駐する）。

エッジから取り込み、完成画像を作り、撮影アプリに状態と画像を返す。

- 10 秒ごとにエッジのセッションを見て、新しいものを取り込む（照合したらエッジ側は消す）
- 取り込んだセッション（schema_version 1 で商品のあるもの）を 1 つずつ処理し、
  results/<id>/final.jpg を作る
- 撮影アプリ（imx519_edge）は /api/sessions で状態と進捗を、
  /api/sessions/<id>/preview.jpg で完成画像を読む

usage:
    uv run python -m super_imx519.studio --host 100.108.168.101 --port 8520
"""

import argparse
import contextlib
import json
import logging
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from .ingest import DEFAULT_DEST, Edge, ingest_session
from .pipeline.process import process_session

log = logging.getLogger("super_imx519.studio")
SESSION_ID = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{6}(_c[0-9]+)?$")
DEFAULT_RESULTS = Path("~/data/super_imx519/results").expanduser()
DEFAULT_EDGE = "https://85pi.taila713c8.ts.net:12443"


class Studio:
    def __init__(
        self,
        sessions_dir: Path,
        results_dir: Path,
        edge: Edge | None,
        interval_s: float = 10.0,
        process: Callable = process_session,
        ingest: Callable = ingest_session,
    ):
        self.sessions_dir, self.results_dir = sessions_dir, results_dir
        self.edge, self.interval_s = edge, interval_s
        self.process, self.ingest = process, ingest
        self.active: dict[str, dict] = {}  # 取り込み中・処理中のセッション → 進み具合
        self.edge_sessions: dict[str, dict] = {}
        self.edge_error: str | None = None
        self.checked_at: float | None = None
        self._wake = threading.Event()
        self._running = False
        self._thread: threading.Thread | None = None

    # --- 常駐 ---

    def start(self) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="studio", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while self._running:
            try:
                self.cycle()
            except Exception:
                log.exception("取り込み・処理の途中で止まりました")
            self._wake.wait(self.interval_s)
            self._wake.clear()

    def cycle(self) -> None:
        """1 回ぶん: エッジから取り込み、待っているセッションを処理する。"""
        if self.edge:
            self.refresh_edge()
            # 手元に同じものがあっても呼ぶ（中身を照合し、同じならエッジ側を消すだけになる）
            for session_id in sorted(self.edge_sessions):
                self._ingest(session_id)
        for session_id in self.pending():
            self._process(session_id)

    def refresh_edge(self) -> None:
        """エッジに残っているセッションの一覧を読み直す。"""
        try:
            self.edge_sessions = {s["session_id"]: s for s in self.edge.sessions()}
            self.edge_error = None
        except Exception as e:
            self.edge_error = f"エッジに届きません: {e}"
        self.checked_at = time.time()

    def _progress(self, session_id: str, state: str):
        def report(done: float, total: float, label: str) -> None:
            self.active[session_id] = {"state": state, "done": done, "total": total, "label": label}

        return report

    def _ingest(self, session_id: str) -> None:
        self.active[session_id] = {"state": "ingesting", "done": 0, "total": 1, "label": "取り込み"}
        try:
            self.ingest(
                self.edge,
                session_id,
                self.sessions_dir,
                progress=self._progress(session_id, "ingesting"),
            )
            self.edge_sessions.pop(session_id, None)
            log.info("取り込みました: %s", session_id)
        except Exception as e:
            log.error("取り込めません: %s: %s", session_id, e)
        finally:
            self.active.pop(session_id, None)

    def pending(self) -> list[str]:
        """処理を待っているセッション。

        schema_version 1 で商品があり、完成も失敗もしていないもの。
        """
        out = []
        for path in sorted(self.sessions_dir.iterdir()):
            session = _read_session(path)
            if not session or not _eligible(session):
                continue
            result = self.results_dir / path.name
            if not (result / "final.jpg").exists() and not (result / "error.txt").exists():
                out.append(path.name)
        return out

    def _process(self, session_id: str) -> None:
        out = self.results_dir / session_id
        self.active[session_id] = {
            "state": "processing",
            "done": 0,
            "total": 1,
            "label": "処理待ち",
        }
        try:
            self.process(
                self.sessions_dir / session_id, out, self._progress(session_id, "processing")
            )
            log.info("完成しました: %s", session_id)
        except Exception as e:
            log.exception("処理に失敗しました: %s", session_id)
            out.mkdir(parents=True, exist_ok=True)
            (out / "error.txt").write_text(str(e))
        finally:
            self.active.pop(session_id, None)

    def reprocess(self, session_id: str) -> None:
        out = self.results_dir / session_id
        for name in ("final.jpg", "preview.jpg", "error.txt", "report.json"):
            (out / name).unlink(missing_ok=True)
        self._wake.set()

    def wake(self) -> None:
        self._wake.set()

    # --- 状態 ---

    def sessions(self, cms_id: int | None = None) -> list[dict]:
        rows = []
        for path in sorted(self.sessions_dir.iterdir(), reverse=True):
            session = _read_session(path)
            if session is None:
                continue
            rows.append(self._row(path.name, session))
        local = {r["session_id"] for r in rows}
        for session_id, s in self.edge_sessions.items():
            if session_id not in local:
                rows.append(self._row(session_id, s, on_edge=True))
        if cms_id is not None:
            rows = [r for r in rows if (r["product"] or {}).get("cms_id") == cms_id]
        return sorted(rows, key=lambda r: r["session_id"], reverse=True)

    def _row(self, session_id: str, session: dict, on_edge: bool = False) -> dict:
        result = self.results_dir / session_id
        active = self.active.get(session_id)
        error = None
        if active:
            state = active["state"]
        elif on_edge:
            state = "on_edge"
        elif (result / "final.jpg").exists():
            state = "done"
        elif (result / "error.txt").exists():
            state, error = "failed", (result / "error.txt").read_text()[:500]
        elif _eligible(session):
            state = "queued"
        else:
            state = "skipped"  # 古い形式や商品の無いセッションは自動では処理しない
        report = _read_json(result / "report.json") if state == "done" else None
        return {
            "session_id": session_id,
            "created_at": session.get("created_at"),
            "product": session.get("product"),
            "shots": len(session["shots"])
            if isinstance(session.get("shots"), list)
            else session.get("shots"),
            "state": state,
            "progress": {k: active[k] for k in ("done", "total", "label")} if active else None,
            "error": error,
            "final_size": report.get("final_size") if report else None,
        }


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _read_session(path: Path) -> dict | None:
    if not path.is_dir() or not SESSION_ID.match(path.name):
        return None
    return _read_json(path / "session.json")


def _eligible(session: dict) -> bool:
    return session.get("schema_version", 0) >= 1 and bool(session.get("product"))


def create_app(studio: Studio, manage: bool = False) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        if manage:
            studio.start()
        try:
            yield
        finally:
            if manage:
                studio.stop()

    app = FastAPI(title="super_imx519 studio", lifespan=lifespan)

    def result_file(session_id: str, name: str) -> Path:
        path = studio.results_dir / session_id / name
        if not SESSION_ID.match(session_id) or not path.is_file():
            raise HTTPException(404, "まだ完成していません")
        return path

    @app.get("/api/health")
    def health():
        return {
            "edge": {"ok": studio.edge_error is None, "error": studio.edge_error},
            "checked_at": studio.checked_at,
            "active": studio.active,
        }

    @app.get("/api/sessions")
    def sessions(cms_id: int | None = None):
        return studio.sessions(cms_id)

    @app.get("/api/sessions/{session_id}/preview.jpg")
    def preview(session_id: str):
        return FileResponse(result_file(session_id, "preview.jpg"), media_type="image/jpeg")

    @app.get("/api/sessions/{session_id}/final.jpg")
    def final(session_id: str):
        return FileResponse(
            result_file(session_id, "final.jpg"),
            media_type="image/jpeg",
            filename=f"{session_id}.jpg",
            content_disposition_type="inline",
        )

    @app.post("/api/sessions/{session_id}/reprocess")
    def reprocess(session_id: str):
        if not SESSION_ID.match(session_id) or not (studio.sessions_dir / session_id).is_dir():
            raise HTTPException(404, "セッションがありません")
        studio.reprocess(session_id)
        return {"ok": True}

    @app.post("/api/wake")
    def wake():
        """撮影が終わったときに撮影アプリが呼ぶ（次の確認を待たずに取り込む）。"""
        studio.wake()
        return {"ok": True}

    return app


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser(prog="super_imx519.studio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8520)
    ap.add_argument("--edge", default=DEFAULT_EDGE)
    ap.add_argument("--sessions", type=Path, default=DEFAULT_DEST)
    ap.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    ap.add_argument("--interval", type=float, default=10.0)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    studio = Studio(
        args.sessions.expanduser(), args.results.expanduser(), Edge(args.edge), args.interval
    )
    uvicorn.run(create_app(studio, manage=True), host=args.host, port=args.port, workers=1)


if __name__ == "__main__":
    main()
