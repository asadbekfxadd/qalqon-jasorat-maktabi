"""Правила, на которых держится школьный портал: вход, CSRF, доступ к данным детей, смена пароля."""
import re
from conftest import csrf_of, login


def test_login_ok_and_wrong_password(app):
    c = app.test_client()
    r = login(c, "parent_a", "wrong-password1")
    assert r.status_code == 200 and "uid" not in dict(c.session_transaction().__enter__())
    r = login(c, "parent_a")
    assert r.status_code == 302 and r.headers["Location"].endswith("/cabinet")


def test_post_without_csrf_is_rejected(app):
    c = app.test_client()
    r = c.post("/login", data={"username": "parent_a", "password": "Passw0rd1"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/login")
    with c.session_transaction() as s:
        assert "uid" not in s


def test_login_is_throttled(app):
    from qalqon import core
    core._attempts.clear()
    c = app.test_client()
    codes = [login(c, "parent_a", "bad-password1").status_code for _ in range(9)]
    assert codes[-1] == 429
    assert login(c, "parent_a").status_code == 429  # даже верный пароль после блокировки


def test_parent_sees_only_own_child_file(app):
    fid = app.config["_ids"]["photo_a"]
    a, b, anon = app.test_client(), app.test_client(), app.test_client()
    login(a, "parent_a"); login(b, "parent_b")
    assert a.get(f"/file/{fid}").status_code == 200
    assert b.get(f"/file/{fid}").status_code == 403
    assert anon.get(f"/file/{fid}").status_code == 403


def test_roles_cannot_open_foreign_areas(app):
    p, anon = app.test_client(), app.test_client()
    login(p, "parent_a")
    assert p.get("/admin/").status_code in (302, 403)
    assert p.get("/teacher/").status_code in (302, 403)
    assert anon.get("/admin/").status_code in (302, 403)
    assert anon.get("/cabinet/").status_code in (302, 403)


def test_password_change_ends_other_sessions(app):
    one, two = app.test_client(), app.test_client()
    login(one, "parent_a"); login(two, "parent_a")
    assert two.get("/cabinet/").status_code == 200
    r = one.post("/account", data={"act": "password", "old": "Passw0rd1", "new": "NewPassw0rd2", "new2": "NewPassw0rd2", "_csrf": csrf_of(one, "/account")})
    assert r.status_code == 302
    assert one.get("/cabinet/").status_code == 200  # текущая сессия сохранилась
    assert two.get("/cabinet/").status_code in (302, 403)  # вторая завершена


def test_reset_link_uses_public_url_not_host_header(app, monkeypatch):
    sent = []
    monkeypatch.setenv("PUBLIC_URL", "https://school.example")
    from qalqon import core
    monkeypatch.setattr(core, "_send_email", lambda to, subj, body: sent.append(body), raising=False)
    from qalqon.models import db, User
    with app.app_context():
        User.query.filter_by(username="parent_a").first().email = "a@example.com"
        db.session.commit()
    c = app.test_client()
    h = {"Host": "evil.example"}
    tok = re.search(r'name="_csrf" value="([^"]+)"', c.get("/forgot", headers=h).get_data(as_text=True)).group(1)
    c.post("/forgot", data={"ident": "parent_a", "_csrf": tok}, headers=h)
    import time; time.sleep(0.3)
    assert sent and "https://school.example/reset/" in sent[0] and "evil.example" not in sent[0]
