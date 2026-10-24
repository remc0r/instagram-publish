import pytest
import responses

from instagram_publish import InstagramClient, InstagramError

BASE = "https://graph.instagram.com/v26.0"


@pytest.fixture
def client():
    return InstagramClient(access_token="SECRET", user_id="42", poll_interval=0, poll_timeout=1)


def finished(cid):
    responses.add(responses.GET, f"{BASE}/{cid}", json={"status_code": "FINISHED"})


@responses.activate
def test_single_photo(client):
    responses.add(responses.POST, f"{BASE}/42/media", json={"id": "c1"})
    finished("c1")
    responses.add(responses.POST, f"{BASE}/42/media_publish", json={"id": "m1"})
    assert client.publish("https://x.test/a.jpg", "hi") == "m1"
    body = responses.calls[0].request.body
    assert "image_url=" in body and "caption=hi" in body
    assert responses.calls[0].request.headers["Authorization"] == "Bearer SECRET"
    assert "SECRET" not in responses.calls[0].request.url


@responses.activate
def test_single_video_is_reel(client):
    responses.add(responses.POST, f"{BASE}/42/media", json={"id": "c1"})
    finished("c1")
    responses.add(responses.POST, f"{BASE}/42/media_publish", json={"id": "m1"})
    client.publish("https://x.test/a.mp4")
    assert "media_type=REELS" in responses.calls[0].request.body


@responses.activate
def test_story(client):
    responses.add(responses.POST, f"{BASE}/42/media", json={"id": "c1"})
    finished("c1")
    responses.add(responses.POST, f"{BASE}/42/media_publish", json={"id": "m1"})
    assert client.publish("https://x.test/a.jpg", story=True) == "m1"
    body = responses.calls[0].request.body
    assert "media_type=STORIES" in body and "caption" not in body


def test_story_single_media(client):
    with pytest.raises(InstagramError):
        client.publish(["https://x.test/a.jpg", "https://x.test/b.jpg"], story=True)


@responses.activate
def test_carousel(client):
    for cid in ("i1", "i2", "car"):
        responses.add(responses.POST, f"{BASE}/42/media", json={"id": cid})
    for cid in ("i1", "i2", "car"):
        finished(cid)
    responses.add(responses.POST, f"{BASE}/42/media_publish", json={"id": "m1"})
    client.publish(["https://x.test/a.jpg", "https://x.test/b.jpg"], "c")
    assert "children=i1%2Ci2" in responses.calls[4].request.body


@responses.activate
def test_api_error_has_no_token(client):
    responses.add(
        responses.POST, f"{BASE}/42/media", status=400,
        json={"error": {"message": "Invalid image", "code": 9004}},
    )
    with pytest.raises(InstagramError, match="Invalid image") as exc:
        client.publish("https://x.test/a.jpg")
    assert "SECRET" not in str(exc.value)


@responses.activate
def test_container_error(client):
    responses.add(responses.POST, f"{BASE}/42/media", json={"id": "c1"})
    responses.add(responses.GET, f"{BASE}/c1", json={"status_code": "ERROR"})
    with pytest.raises(InstagramError, match="ERROR"):
        client.publish("https://x.test/a.jpg")


def test_carousel_size(client):
    with pytest.raises(InstagramError):
        client.publish(["https://x.test/a.jpg"] * 11)


def test_missing_credentials(monkeypatch):
    monkeypatch.delenv("IG_ACCESS_TOKEN", raising=False)
    with pytest.raises(InstagramError):
        InstagramClient()


@responses.activate
def test_refresh_token(client):
    responses.add(
        responses.GET, "https://graph.instagram.com/refresh_access_token",
        json={"access_token": "NEW", "token_type": "bearer", "expires_in": 5184000},
    )
    assert client.refresh_token()["access_token"] == "NEW"
    assert "grant_type=ig_refresh_token" in responses.calls[0].request.url


def test_refresh_token_facebook_login_refused():
    c = InstagramClient(access_token="T", user_id="42", login="facebook")
    with pytest.raises(InstagramError):
        c.refresh_token()


@responses.activate
def test_facebook_login_host():
    c = InstagramClient(access_token="T", user_id="42", login="facebook", poll_interval=0)
    responses.add(responses.POST, "https://graph.facebook.com/v26.0/42/media", json={"id": "c1"})
    responses.add(responses.GET, "https://graph.facebook.com/v26.0/c1", json={"status_code": "FINISHED"})
    responses.add(responses.POST, "https://graph.facebook.com/v26.0/42/media_publish", json={"id": "m1"})
    assert c.publish("https://x.test/a.jpg") == "m1"


@responses.activate
def test_token_file_refresh_roundtrip(tmp_path):
    f = tmp_path / "tok"
    c = InstagramClient(access_token="OLD", user_id="42", token_file=f)
    responses.add(
        responses.GET, "https://graph.instagram.com/refresh_access_token",
        json={"access_token": "NEW", "token_type": "bearer", "expires_in": 5184000},
    )
    c.refresh_token()
    assert f.read_text() == "NEW"
    assert f.stat().st_mode & 0o777 == 0o600
    assert c.session.headers["Authorization"] == "Bearer NEW"
    # a new client picks the file over the (stale) argument
    c2 = InstagramClient(access_token="OLD", user_id="42", token_file=f)
    assert c2.session.headers["Authorization"] == "Bearer NEW"


def test_token_file_missing_falls_back_to_arg(tmp_path):
    c = InstagramClient(access_token="ARG", user_id="42", token_file=tmp_path / "nope")
    assert c.session.headers["Authorization"] == "Bearer ARG"


def test_rejects_non_https_media(client):
    for bad in ("http://x.test/a.jpg", "file:///etc/passwd", "/tmp/a.jpg"):
        with pytest.raises(InstagramError, match="HTTPS"):
            client.publish(bad)


def test_story_with_caption_refused(client):
    with pytest.raises(InstagramError, match="caption"):
        client.publish("https://x.test/a.jpg", "text", story=True)


def test_rejects_bad_api_version_and_user_id():
    with pytest.raises(InstagramError):
        InstagramClient(access_token="T", user_id="42", api_version="../../x")
    with pytest.raises(InstagramError):
        InstagramClient(access_token="T", user_id="42/../x")


@responses.activate
def test_redirect_not_followed(client):
    responses.add(responses.POST, f"{BASE}/42/media", status=302, headers={"Location": "https://evil.test/"})
    with pytest.raises(InstagramError, match="HTTP 302"):
        client.publish("https://x.test/a.jpg")
    assert len(responses.calls) == 1


@responses.activate
def test_malformed_response_is_instagram_error(client):
    responses.add(responses.POST, f"{BASE}/42/media", json=None)
    with pytest.raises(InstagramError, match="missing 'id'"):
        client.publish("https://x.test/a.jpg")


@responses.activate
def test_refresh_save_failure_keeps_token(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    c = InstagramClient(access_token="OLD", user_id="42", token_file=blocker / "sub" / "tok")
    responses.add(
        responses.GET, "https://graph.instagram.com/refresh_access_token",
        json={"access_token": "NEW", "token_type": "bearer", "expires_in": 5184000},
    )
    with pytest.raises(InstagramError, match="could not be saved") as exc:
        c.refresh_token()
    assert exc.value.result["access_token"] == "NEW"
    assert c.session.headers["Authorization"] == "Bearer NEW"


def test_token_file_symlink_updated_in_place(tmp_path):
    real = tmp_path / "real"
    real.write_text("OLD")
    link = tmp_path / "link"
    link.symlink_to(real)
    c = InstagramClient(access_token="X", user_id="42", token_file=link)
    c._write_token_file("NEW")
    assert link.is_symlink() and real.read_text() == "NEW"
    assert not list(tmp_path.glob(".real.*"))


def test_world_readable_token_file_warns(tmp_path):
    f = tmp_path / "tok"
    f.write_text("T")
    f.chmod(0o644)
    with pytest.warns(UserWarning, match="chmod 600"):
        InstagramClient(user_id="42", token_file=f)


def test_env_token_is_stripped(monkeypatch):
    monkeypatch.setenv("IG_ACCESS_TOKEN", "TOK\n")
    monkeypatch.setenv("IG_USER_ID", "42")
    c = InstagramClient()
    assert c.session.headers["Authorization"] == "Bearer TOK"
