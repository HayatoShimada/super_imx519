import json
import threading

from fastapi.testclient import TestClient

from super_imx519.studio import Studio, create_app

SID = "2026-10-09_121401_c434"


def write_session(directory, session_id=SID, version=1, cms_id=434):
    path = directory / session_id
    path.mkdir(parents=True)
    session = {
        "session_id": session_id,
        "created_at": "2026-10-09T12:14:01+09:00",
        "shots": [{}] * 3,
    }
    if version:
        session.update(schema_version=version, product={"cms_id": cms_id, "title": "テスト"})
    (path / "session.json").write_text(json.dumps(session))
    return path


class FakeEdge:
    def __init__(self, sessions):
        self.list = sessions

    def sessions(self):
        return self.list


def fake_ingest(edge, session_id, dest, keep=False, progress=None):
    progress(50, 100, "取り込み 50 / 100 MB")
    if not (dest / session_id).exists():
        write_session(dest, session_id)
    edge.list = [s for s in edge.list if s["session_id"] != session_id]
    return dest / session_id


def make(tmp_path, edge=None, process=None):
    sessions, results = tmp_path / "sessions", tmp_path / "results"
    sessions.mkdir()
    results.mkdir()

    def default_process(session_dir, out, progress):
        progress(1, 2, "HDR の合成")
        out.mkdir(parents=True, exist_ok=True)
        (out / "preview.jpg").write_bytes(b"\xff\xd8preview")
        (out / "report.json").write_text(json.dumps({"final_size": [2048, 1538]}))
        (out / "final.jpg").write_bytes(b"\xff\xd8final")

    return Studio(sessions, results, edge, process=process or default_process, ingest=fake_ingest)


def test_cycle_ingests_then_processes(tmp_path):
    edge = FakeEdge([{"session_id": SID, "product": {"cms_id": 434}, "shots": 3}])
    studio = make(tmp_path, edge)
    studio.refresh_edge()
    [row] = studio.sessions(cms_id=434)
    assert row["state"] == "on_edge"

    studio.cycle()
    [row] = studio.sessions(cms_id=434)
    assert row["state"] == "done" and row["final_size"] == [2048, 1538]
    assert studio.sessions(cms_id=1) == []


def test_old_sessions_are_skipped_and_failures_are_kept(tmp_path):
    def broken(session_dir, out, progress):
        raise RuntimeError("DNG が足りません")

    studio = make(tmp_path, process=broken)
    write_session(studio.sessions_dir, "2026-10-08_120000", version=0)
    write_session(studio.sessions_dir, SID)
    assert studio.pending() == [SID]
    studio.cycle()
    states = {r["session_id"]: (r["state"], r["error"]) for r in studio.sessions()}
    assert states == {"2026-10-08_120000": ("skipped", None), SID: ("failed", "DNG が足りません")}
    assert studio.pending() == []  # 失敗したものは、やり直しを頼まれるまで処理しない


def test_progress_is_visible_while_processing(tmp_path):
    started, release = threading.Event(), threading.Event()

    def slow(session_dir, out, progress):
        progress(3, 10, "位置合わせと平均 EV+0")
        started.set()
        release.wait(5)
        out.mkdir(parents=True, exist_ok=True)
        (out / "final.jpg").write_bytes(b"x")

    studio = make(tmp_path, process=slow)
    write_session(studio.sessions_dir)
    worker = threading.Thread(target=studio.cycle)
    worker.start()
    started.wait(5)
    [row] = studio.sessions()
    assert row["state"] == "processing"
    assert row["progress"] == {"done": 3, "total": 10, "label": "位置合わせと平均 EV+0"}
    release.set()
    worker.join(5)
    assert studio.sessions()[0]["state"] == "done"


def test_api_serves_results_and_reprocess(tmp_path):
    studio = make(tmp_path)
    write_session(studio.sessions_dir)
    studio.cycle()
    client = TestClient(create_app(studio))
    assert client.get("/api/sessions", params={"cms_id": 434}).json()[0]["state"] == "done"
    assert client.get(f"/api/sessions/{SID}/preview.jpg").content == b"\xff\xd8preview"
    assert client.get(f"/api/sessions/{SID}/final.jpg").status_code == 200
    assert client.get("/api/sessions/../x/final.jpg").status_code == 404
    assert client.post(f"/api/sessions/{SID}/reprocess").json() == {"ok": True}
    assert client.get("/api/sessions").json()[0]["state"] == "queued"


def test_session_already_here_is_removed_from_edge(tmp_path):
    edge = FakeEdge([{"session_id": SID, "product": {"cms_id": 434}, "shots": 3}])
    studio = make(tmp_path, edge)
    write_session(studio.sessions_dir)  # --keep で取り込んであった
    studio.cycle()
    assert edge.list == []
    assert [r["state"] for r in studio.sessions()] == ["done"]
