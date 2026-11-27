import os, re, sys, tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture()
def app():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.environ["DATABASE_URL"] = f"sqlite:///{path}"
    os.environ.pop("PRODUCTION", None)
    from qalqon import create_app
    from qalqon.models import db, User, SchoolClass, Student, File

    from qalqon import core
    core._attempts.clear()  # счётчик попыток общий на процесс: чистим между тестами
    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        db.create_all()
        def user(name, role, pw="Passw0rd1"):
            u = User(username=name, role=role, full_name=name.title())
            u.set_password(pw)
            db.session.add(u)
            return u
        pa, pb, teacher = user("parent_a", "parent"), user("parent_b", "parent"), user("teacher_t", "teacher")
        klass = SchoolClass(name="5A")
        db.session.add(klass)
        db.session.flush()
        kid_a = Student(full_name="Kid A", class_id=klass.id)
        kid_b = Student(full_name="Kid B", class_id=klass.id)
        kid_a.parents.append(pa)
        kid_b.parents.append(pb)
        db.session.add_all([kid_a, kid_b])
        db.session.flush()
        photo = File(owner_type="photo", owner_id=kid_a.id, name="a.png", mime="image/png", size=4, data=b"\x89PNG")
        db.session.add(photo)
        db.session.flush()
        kid_a.photo_id = photo.id
        db.session.commit()
        app.config["_ids"] = {"photo_a": photo.id}
    yield app
    os.unlink(path)


def csrf_of(client, url="/login"):
    html = client.get(url).get_data(as_text=True)
    m = re.search(r'name="_csrf" value="([^"]+)"', html)
    assert m, "в форме нет csrf-токена"
    return m.group(1)


def login(client, name, pw="Passw0rd1"):
    return client.post("/login", data={"username": name, "password": pw, "_csrf": csrf_of(client)})
