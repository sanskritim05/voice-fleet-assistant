def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["reasoning"]["provider"] == "rules"
    assert body["voice"] == "browser"


def test_message_is_triaged_and_logged(client):
    res = client.post("/api/message", json={"transcript": "  My brakes are grinding  ", "truck_id": "truck-1"})
    assert res.status_code == 200
    body = res.json()
    assert body["transcript"] == "My brakes are grinding"
    assert body["decision"] == "STOP_SAFELY"
    assert body["audio_url"] is None

    issues = client.get("/api/issues").json()["issues"]
    assert len(issues) == 1
    assert issues[0]["issue_id"] == body["issue_id"]
    assert issues[0]["status"] == "open"


def test_blank_transcript_rejected(client):
    assert client.post("/api/message", json={"transcript": "   "}).status_code == 422


def test_issue_filters_and_order(client):
    client.post("/api/message", json={"transcript": "Check engine light is on"})
    client.post("/api/message", json={"transcript": "Smoke from the hood"})

    issues = client.get("/api/issues").json()["issues"]
    assert issues[0]["transcript"] == "Smoke from the hood"

    critical = client.get("/api/issues", params={"severity": "critical"}).json()["issues"]
    assert [issue["severity"] for issue in critical] == ["critical"]

    assert client.get("/api/issues", params={"severity": "bogus"}).status_code == 422


def test_status_update_and_stats(client):
    issue_id = client.post("/api/message", json={"transcript": "Smoke from the hood"}).json()["issue_id"]

    stats = client.get("/api/stats").json()
    assert stats["total"] == 1
    assert stats["open_critical"] == 1

    res = client.patch(f"/api/issues/{issue_id}", json={"status": "resolved"})
    assert res.status_code == 200
    assert res.json()["status"] == "resolved"

    stats = client.get("/api/stats").json()
    assert stats["open_critical"] == 0
    assert stats["resolved"] == 1


def test_status_update_unknown_issue(client):
    assert client.patch("/api/issues/nope", json={"status": "resolved"}).status_code == 404


def test_empty_log_file_is_tolerated(client, tmp_path):
    from app import config

    config.ISSUES_FILE.write_text("")
    assert client.get("/api/issues").json() == {"issues": []}


def test_demo_seed(client):
    seeded = client.post("/api/demo/seed").json()["seeded"]
    stats = client.get("/api/stats").json()
    assert stats["total"] == seeded
    assert stats["open_critical"] >= 1


def test_transcribe_requires_key(client):
    res = client.post("/api/transcribe", files={"audio": ("clip.webm", b"abc", "audio/webm")})
    assert res.status_code == 503


def test_transcribe_with_groq(client, monkeypatch):
    from app import config, transcribe

    monkeypatch.setattr(config, "GROQ_API_KEY", "test-key")
    calls = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"text": " My brakes are grinding. "}

    def fake_post(url, **kwargs):
        calls["file"] = kwargs["files"]["file"]
        return FakeResponse()

    monkeypatch.setattr(transcribe.requests, "post", fake_post)
    res = client.post("/api/transcribe", files={"audio": ("clip.mp4", b"abc", "audio/mp4")})
    assert res.json() == {"transcript": "My brakes are grinding."}
    assert calls["file"] == ("clip.mp4", b"abc", "audio/mp4")


def test_transcribe_rejects_empty(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "GROQ_API_KEY", "test-key")
    res = client.post("/api/transcribe", files={"audio": ("clip.webm", b"", "audio/webm")})
    assert res.status_code == 400


def test_role_pages_serve_the_app(client):
    for path in ["/", "/driver", "/dispatch"]:
        res = client.get(path)
        assert res.status_code == 200
        assert "Fleet Voice" in res.text
