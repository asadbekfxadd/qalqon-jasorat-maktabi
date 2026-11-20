"""Qalqon Jasorat Maktabi — сайт, дневник и кабинеты (админ / учитель / родитель)."""
import os, re, secrets, threading, time, json, urllib.request
from urllib.parse import urlparse, parse_qs
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from flask import (Flask, render_template, request, redirect, url_for, session,
                   flash, abort, g)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
PROD = os.environ.get("PRODUCTION") == "1"
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or ("dev-only-" + secrets.token_hex(8) if not PROD else None),
    SQLALCHEMY_DATABASE_URI=re.sub(r"^postgres(ql)?://", "postgresql+psycopg2://", os.environ.get("DATABASE_URL") or "sqlite:///qalqon.db"),
    SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=PROD,
    PERMANENT_SESSION_LIFETIME=timedelta(days=14),
)
if not app.config["SECRET_KEY"]:
    raise RuntimeError("Задайте SECRET_KEY в переменных окружения")
if PROD:
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
db = SQLAlchemy(app)

SITE = dict(
    name="Qalqon Jasorat Maktabi",
    phone=os.environ.get("SITE_PHONE", "+998 90 123 45 67"),
    email=os.environ.get("SITE_EMAIL", "info@qalqon.uz"),
    instagram=os.environ.get("SITE_INSTAGRAM", "https://www.instagram.com/qalqon.jasorat"),
    telegram=os.environ.get("SITE_TELEGRAM", "https://t.me/qalqon"),
)
TZ = timezone(timedelta(hours=5))
def today(): return datetime.now(TZ).date()

# ───────────────────────── модели ─────────────────────────
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(60), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(10), nullable=False)          # admin | teacher | parent
    full_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(30), default="")
    active = db.Column(db.Boolean, default=True)
    must_change = db.Column(db.Boolean, default=False)
    def set_password(self, p): self.password_hash = generate_password_hash(p)

class Branch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    city = db.Column(db.String(80), nullable=False)
    area = db.Column(db.String(80), default="")
    address = db.Column(db.String(200), default="")
    schedule = db.Column(db.String(120), default="")
    ages = db.Column(db.String(40), default="")
    phone = db.Column(db.String(30), default="")
    map_url = db.Column(db.String(300), default="")

class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"))
    teacher_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    schedule = db.Column(db.String(120), default="")
    branch = db.relationship("Branch")
    teacher = db.relationship("User")
    students = db.relationship("Student", back_populates="group", order_by="Student.full_name")

class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    birth_year = db.Column(db.Integer)
    group_id = db.Column(db.Integer, db.ForeignKey("group.id"))
    parent_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    group = db.relationship("Group", back_populates="students")
    parent = db.relationship("User")
    attendance = db.relationship("Attendance", cascade="all, delete-orphan")
    grades = db.relationship("Grade", cascade="all, delete-orphan")

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False)
    day = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(10), nullable=False)        # present | late | absent
    __table_args__ = (db.UniqueConstraint("student_id", "day"),)

class Grade(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False)
    day = db.Column(db.Date, nullable=False)
    subject = db.Column(db.String(80), nullable=False)
    score = db.Column(db.Integer, nullable=False)            # 1..5
    comment = db.Column(db.String(300), default="")
    teacher_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    teacher = db.relationship("User")

class Homework(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("group.id"), nullable=False)
    day = db.Column(db.Date, nullable=False)
    title = db.Column(db.String(120), nullable=False)
    text = db.Column(db.String(1000), default="")
    due = db.Column(db.Date)

class Announcement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    text = db.Column(db.String(2000), default="")
    day = db.Column(db.Date, nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey("group.id"))   # пусто = всей школе

class Application(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created = db.Column(db.DateTime, default=lambda: datetime.now(TZ))
    child = db.Column(db.String(120), nullable=False)
    age = db.Column(db.Integer)
    parent = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"))
    note = db.Column(db.String(500), default="")
    status = db.Column(db.String(10), default="new")        # new | called | enrolled | rejected
    branch = db.relationship("Branch")

class Video(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), default="")
    url = db.Column(db.String(500), nullable=False)
    vertical = db.Column(db.Boolean, default=False)
    sort = db.Column(db.Integer, default=0)

def video_info(url):
    """Разбирает ссылку и возвращает данные для плеера. Только разрешённые сервисы (без произвольных iframe)."""
    try: u = urlparse((url or "").strip())
    except ValueError: return None
    if u.scheme != "https" or not u.hostname: return None
    host, path = u.hostname.lower().removeprefix("www."), u.path
    if host in ("youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"):
        vid, vert = None, False
        if host == "youtu.be": m = re.match(r"^/([\w-]{11})", path); vid = m and m[1]
        else:
            m = re.match(r"^/(shorts|embed|live)/([\w-]{11})", path)
            if m: vid, vert = m[2], m[1] == "shorts"
            else:
                v = parse_qs(u.query).get("v", [""])[0]; vid = v if re.fullmatch(r"[\w-]{11}", v) else None
        if vid: return dict(kind="iframe", src=f"https://www.youtube.com/embed/{vid}?autoplay=1&rel=0&playsinline=1", thumb=f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg", vertical=vert)
    elif host == "instagram.com":
        m = re.match(r"^/(?:[\w.]+/)?(reel|reels|p|tv)/([\w-]+)", path)
        if m: return dict(kind="iframe", src=f"https://www.instagram.com/{'reel' if m[1] == 'reels' else m[1]}/{m[2]}/embed", thumb="", vertical=m[1] in ("reel", "reels"))
    elif host == "t.me":
        m = re.match(r"^/([A-Za-z0-9_]{4,})/(\d+)$", path)
        if m: return dict(kind="iframe", src=f"https://t.me/{m[1]}/{m[2]}?embed=1&mode=tme", thumb="", vertical=False)
    elif host == "vimeo.com":
        m = re.match(r"^/(\d+)", path)
        if m: return dict(kind="iframe", src=f"https://player.vimeo.com/video/{m[1]}?autoplay=1", thumb="", vertical=False)
    if path.lower().endswith((".mp4", ".webm", ".mov", ".m4v")):
        return dict(kind="file", src=url.strip(), thumb="", vertical=False)
    return None

# ───────────────────────── язык ─────────────────────────
def lang(): return session.get("lang", "ru")
@app.context_processor
def ctx():
    def L(ru, uz): return uz if lang() == "uz" else ru
    return dict(L=L, lang=lang(), SITE=SITE, me=g.get("me"), csrf=csrf_token, today=today,
                fmt=lambda d: d.strftime("%d.%m.%Y") if d else "")
def LL(ru, uz): return uz if lang() == "uz" else ru

@app.route("/lang/<l>")
def set_lang(l):
    if l in ("ru", "uz"): session["lang"] = l; session.permanent = True
    nxt = request.args.get("next", "/")
    return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else "/")

# ───────────────────────── безопасность ─────────────────────────
def csrf_token():
    if "csrf" not in session: session["csrf"] = secrets.token_urlsafe(24)
    return session["csrf"]

_attempts = {}
def too_many(ip):
    now = time.time(); lst = [t for t in _attempts.get(ip, []) if now - t < 600]
    _attempts[ip] = lst; return len(lst) >= 8

@app.before_request
def guard():
    g.me = db.session.get(User, session["uid"]) if "uid" in session else None
    if g.me and not g.me.active: session.clear(); g.me = None
    if request.method == "POST":
        if not secrets.compare_digest(request.form.get("_csrf", ""), session.get("csrf", "-")):
            flash(LL("Страница устарела. Попробуйте ещё раз.", "Sahifa eskirgan. Qayta urinib ko‘ring."), "err")
            ref = request.referrer or ""
            back = ref if ref.startswith(request.host_url) else url_for("login" if request.endpoint == "login" else "index")
            return redirect(back)
    if g.me and g.me.must_change and request.endpoint not in ("account", "logout", "static", "set_lang"):
        return redirect(url_for("account"))

@app.after_request
def headers(r):
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["X-Frame-Options"] = "DENY"
    r.headers["Referrer-Policy"] = "same-origin"
    return r

def need(*roles):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            if not g.me: return redirect(url_for("login", next=request.path))
            if roles and g.me.role not in roles: abort(403)
            return f(*a, **k)
        return w
    return deco

def home_for(u): return url_for({"admin": "a_home", "teacher": "t_home", "parent": "p_home"}[u.role])

def notify_tg(text):
    tok, chat = os.environ.get("TG_BOT_TOKEN"), os.environ.get("TG_CHAT_ID")
    if not (tok and chat): return
    def run():
        try:
            req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage",
                data=json.dumps({"chat_id": chat, "text": text}).encode(), headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=8)
        except Exception: pass
    threading.Thread(target=run, daemon=True).start()

def pdate(s, default=None):
    try: return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError): return default

def clean(name, n): return (request.form.get(name) or "").strip()[:n]

# ───────────────────────── публичный сайт ─────────────────────────
@app.route("/")
def index():
    vids = []
    for v in Video.query.order_by(Video.sort, Video.id).all():
        info = video_info(v.url)
        if info: info["vertical"] = bool(v.vertical or info["vertical"]); vids.append(dict(info, id=v.id, title=v.title))
    return render_template("index.html", branches=Branch.query.order_by(Branch.id).all(), videos=vids)

@app.post("/apply")
def apply():
    child, parent, phone = clean("child", 120), clean("parent", 120), clean("phone", 30)
    try: age = int(request.form.get("age", ""))
    except ValueError: age = 0
    digits = "".join(c for c in phone if c.isdigit())
    if len(child) < 2 or len(parent) < 2 or len(digits) < 9 or not 6 <= age <= 17:
        flash(LL("Проверьте поля формы: имена, возраст 6–17 и телефон.", "Forma maydonlarini tekshiring: ismlar, yosh 6–17 va telefon."), "err")
        return redirect(url_for("index") + "#signup")
    b = db.session.get(Branch, request.form.get("branch", type=int) or 0)
    a = Application(child=child, age=age, parent=parent, phone=phone, branch=b, note=clean("note", 500))
    db.session.add(a); db.session.commit()
    notify_tg(f"Новая заявка #{a.id}\n{child}, {age} лет\nРодитель: {parent}\nТел: {phone}\nФилиал: {b.city if b else '-'}")
    flash(LL("Заявка принята. Мы перезвоним в течение дня.", "Ariza qabul qilindi. Bir kun ichida qo‘ng‘iroq qilamiz."), "ok")
    return redirect(url_for("index") + "#signup")

# ───────────────────────── вход ─────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    if g.me: return redirect(home_for(g.me))
    if request.method == "POST":
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
        if too_many(ip):
            flash(LL("Слишком много попыток. Подождите 10 минут.", "Juda ko‘p urinish. 10 daqiqa kuting."), "err")
        else:
            u = User.query.filter(func.lower(User.username) == clean("username", 60).lower()).first()
            if u and u.active and check_password_hash(u.password_hash, request.form.get("password", "")):
                lg = session.get("lang"); session.clear(); session["lang"] = lg or "ru"
                session["uid"] = u.id; session.permanent = True
                nxt = request.args.get("next", "")
                return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else home_for(u))
            _attempts.setdefault(ip, []).append(time.time())
            flash(LL("Неверный логин или пароль.", "Login yoki parol noto‘g‘ri."), "err")
    return render_template("login.html")

@app.post("/logout")
def logout():
    lg = session.get("lang"); session.clear()
    if lg: session["lang"] = lg
    return redirect(url_for("index"))

@app.route("/account", methods=["GET", "POST"])
@need()
def account():
    if request.method == "POST":
        old, new = request.form.get("old", ""), request.form.get("new", "")
        if not check_password_hash(g.me.password_hash, old): flash(LL("Старый пароль неверен.", "Eski parol noto‘g‘ri."), "err")
        elif len(new) < 8: flash(LL("Новый пароль: минимум 8 символов.", "Yangi parol: kamida 8 belgi."), "err")
        elif new == old: flash(LL("Новый пароль должен отличаться.", "Yangi parol boshqacha bo‘lishi kerak."), "err")
        else:
            g.me.set_password(new); g.me.must_change = False
            g.me.phone = clean("phone", 30) or g.me.phone
            db.session.commit(); flash(LL("Пароль изменён.", "Parol o‘zgartirildi."), "ok")
            return redirect(home_for(g.me))
    return render_template("account.html")

# ───────────────────────── админ ─────────────────────────
@app.route("/admin")
@need("admin")
def a_home():
    c = dict(students=Student.query.count(), groups=Group.query.count(), teachers=User.query.filter_by(role="teacher").count(),
             parents=User.query.filter_by(role="parent").count(), new=Application.query.filter_by(status="new").count())
    apps = Application.query.order_by(Application.created.desc()).limit(5).all()
    return render_template("a_home.html", c=c, apps=apps)

@app.route("/admin/applications")
@need("admin")
def a_apps():
    st = request.args.get("s", "")
    q = Application.query
    if st: q = q.filter_by(status=st)
    return render_template("a_apps.html", apps=q.order_by(Application.created.desc()).limit(300).all(), st=st)

@app.post("/admin/applications/<int:i>")
@need("admin")
def a_app_set(i):
    a = db.get_or_404(Application, i)
    if request.form.get("act") == "delete": db.session.delete(a)
    elif request.form.get("status") in ("new", "called", "enrolled", "rejected"): a.status = request.form["status"]
    db.session.commit(); return redirect(request.referrer or url_for("a_apps"))

@app.route("/admin/branches", methods=["GET", "POST"])
@need("admin")
def a_branches():
    if request.method == "POST":
        b = db.session.get(Branch, request.form.get("id", type=int) or 0) or Branch()
        if request.form.get("act") == "delete":
            if b.id:
                Group.query.filter_by(branch_id=b.id).update({"branch_id": None}); Application.query.filter_by(branch_id=b.id).update({"branch_id": None})
                db.session.delete(b)
        elif clean("city", 80):
            for f, n in (("city", 80), ("area", 80), ("address", 200), ("schedule", 120), ("ages", 40), ("phone", 30), ("map_url", 300)):
                setattr(b, f, clean(f, n))
            if b.map_url and not b.map_url.startswith("https://"): b.map_url = ""
            db.session.add(b)
        db.session.commit(); return redirect(url_for("a_branches"))
    return render_template("a_branches.html", branches=Branch.query.order_by(Branch.id).all())

@app.route("/admin/users", methods=["GET", "POST"])
@need("admin")
def a_users():
    if request.method == "POST":
        act = request.form.get("act")
        if act == "create":
            role, name, uname = request.form.get("role"), clean("full_name", 120), clean("username", 60).lower()
            if role not in ("teacher", "parent", "admin") or len(name) < 2 or len(uname) < 3:
                flash(LL("Заполните роль, имя и логин (от 3 символов).", "Rol, ism va login (kamida 3 belgi) kiriting."), "err")
            elif User.query.filter(func.lower(User.username) == uname).first():
                flash(LL("Такой логин уже есть.", "Bu login band."), "err")
            else:
                pw = request.form.get("password", "").strip() or secrets.token_urlsafe(6)
                if len(pw) < 8: pw = pw + secrets.token_urlsafe(6)
                u = User(username=uname, role=role, full_name=name, phone=clean("phone", 30), must_change=True); u.set_password(pw)
                db.session.add(u); db.session.commit()
                flash(LL(f"Создан: {uname} · временный пароль: {pw} — передайте его пользователю (показан один раз).",
                         f"Yaratildi: {uname} · vaqtinchalik parol: {pw} — foydalanuvchiga bering (bir marta ko‘rsatiladi)."), "ok")
        else:
            u = db.get_or_404(User, request.form.get("id", type=int) or 0)
            if u.id == g.me.id and act in ("delete", "toggle"): flash(LL("Нельзя изменить свою учётную запись здесь.", "O‘z hisobingizni bu yerda o‘zgartirib bo‘lmaydi."), "err")
            elif act == "reset":
                pw = secrets.token_urlsafe(7); u.set_password(pw); u.must_change = True; db.session.commit()
                flash(LL(f"Новый временный пароль для {u.username}: {pw}", f"{u.username} uchun yangi vaqtinchalik parol: {pw}"), "ok")
            elif act == "toggle": u.active = not u.active; db.session.commit()
            elif act == "delete":
                Group.query.filter_by(teacher_id=u.id).update({"teacher_id": None}); Student.query.filter_by(parent_id=u.id).update({"parent_id": None})
                db.session.delete(u); db.session.commit()
        return redirect(url_for("a_users", r=request.args.get("r", "")))
    r = request.args.get("r", "")
    q = User.query.filter_by(role=r) if r in ("admin", "teacher", "parent") else User.query
    return render_template("a_users.html", users=q.order_by(User.role, User.full_name).all(), r=r)

@app.route("/admin/groups", methods=["GET", "POST"])
@need("admin")
def a_groups():
    if request.method == "POST":
        gr = db.session.get(Group, request.form.get("id", type=int) or 0) or Group()
        if request.form.get("act") == "delete":
            if gr.id:
                Student.query.filter_by(group_id=gr.id).update({"group_id": None}); Homework.query.filter_by(group_id=gr.id).delete(); Announcement.query.filter_by(group_id=gr.id).delete()
                db.session.delete(gr)
        elif clean("name", 80):
            gr.name = clean("name", 80); gr.schedule = clean("schedule", 120)
            gr.branch_id = request.form.get("branch_id", type=int) or None; gr.teacher_id = request.form.get("teacher_id", type=int) or None
            db.session.add(gr)
        db.session.commit(); return redirect(url_for("a_groups"))
    return render_template("a_groups.html", groups=Group.query.order_by(Group.name).all(), branches=Branch.query.all(),
                           teachers=User.query.filter_by(role="teacher", active=True).order_by(User.full_name).all())

@app.route("/admin/students", methods=["GET", "POST"])
@need("admin")
def a_students():
    if request.method == "POST":
        s = db.session.get(Student, request.form.get("id", type=int) or 0) or Student()
        if request.form.get("act") == "delete":
            if s.id: db.session.delete(s)
        elif clean("full_name", 120):
            s.full_name = clean("full_name", 120); s.birth_year = request.form.get("birth_year", type=int)
            s.group_id = request.form.get("group_id", type=int) or None; s.parent_id = request.form.get("parent_id", type=int) or None
            db.session.add(s)
        db.session.commit(); return redirect(url_for("a_students", g=request.args.get("g", "")))
    gid = request.args.get("g", type=int)
    q = Student.query.filter_by(group_id=gid) if gid else Student.query
    return render_template("a_students.html", students=q.order_by(Student.full_name).all(), groups=Group.query.order_by(Group.name).all(),
                           parents=User.query.filter_by(role="parent", active=True).order_by(User.full_name).all(), gid=gid)

@app.route("/admin/news", methods=["GET", "POST"])
@need("admin", "teacher")
def a_news():
    if request.method == "POST":
        if request.form.get("act") == "delete":
            n = db.get_or_404(Announcement, request.form.get("id", type=int) or 0)
            if g.me.role == "admin": db.session.delete(n)
        elif clean("title", 120):
            gid = request.form.get("group_id", type=int) or None
            if g.me.role == "teacher":
                if not gid or not Group.query.filter_by(id=gid, teacher_id=g.me.id).first(): abort(403)
            db.session.add(Announcement(title=clean("title", 120), text=clean("text", 2000), day=today(), group_id=gid))
        db.session.commit(); return redirect(url_for("a_news"))
    groups = Group.query.order_by(Group.name).all() if g.me.role == "admin" else Group.query.filter_by(teacher_id=g.me.id).all()
    return render_template("a_news.html", news=Announcement.query.order_by(Announcement.day.desc(), Announcement.id.desc()).limit(100).all(), groups=groups)


@app.route("/admin/videos", methods=["GET", "POST"])
@need("admin")
def a_videos():
    if request.method == "POST":
        act = request.form.get("act")
        if act == "add":
            url = clean("url", 500)
            if not video_info(url): flash(LL("Ссылка не подходит. Нужна https-ссылка на YouTube, Instagram (reel/post), Telegram-пост, Vimeo или файл .mp4.", "Havola mos emas. YouTube, Instagram (reel/post), Telegram posti, Vimeo yoki .mp4 fayl uchun https-havola kerak."), "err")
            else:
                last = db.session.query(func.max(Video.sort)).scalar() or 0
                db.session.add(Video(title=clean("title", 120), url=url, vertical=bool(request.form.get("vertical")), sort=last + 1))
                db.session.commit(); flash(LL("Видео добавлено.", "Video qo‘shildi."), "ok")
        else:
            items = Video.query.order_by(Video.sort, Video.id).all()
            v = next((x for x in items if x.id == request.form.get("id", type=int)), None)
            if v and act == "delete": db.session.delete(v)
            elif v and act in ("up", "down"):
                i = items.index(v); j = i - 1 if act == "up" else i + 1
                if 0 <= j < len(items): items[i], items[j] = items[j], items[i]
                for n, x in enumerate(items): x.sort = n
            db.session.commit()
        return redirect(url_for("a_videos"))
    rows = [(v, video_info(v.url)) for v in Video.query.order_by(Video.sort, Video.id).all()]
    return render_template("a_videos.html", rows=rows)

# ───────────────────────── учитель ─────────────────────────
def my_group(gid):
    gr = db.get_or_404(Group, gid)
    if g.me.role != "admin" and gr.teacher_id != g.me.id: abort(403)
    return gr

@app.route("/teacher")
@need("teacher", "admin")
def t_home():
    groups = Group.query.filter_by(teacher_id=g.me.id).all() if g.me.role == "teacher" else Group.query.all()
    return render_template("t_home.html", groups=groups)

@app.route("/teacher/group/<int:gid>")
@need("teacher", "admin")
def t_group(gid):
    gr = my_group(gid); day = pdate(request.args.get("d"), today())
    att = {a.student_id: a.status for a in Attendance.query.filter(Attendance.day == day, Attendance.student_id.in_([s.id for s in gr.students] or [0]))}
    ids = [s.id for s in gr.students] or [0]
    grades = Grade.query.filter(Grade.student_id.in_(ids)).order_by(Grade.day.desc(), Grade.id.desc()).limit(40).all()
    hw = Homework.query.filter_by(group_id=gid).order_by(Homework.day.desc(), Homework.id.desc()).limit(15).all()
    return render_template("t_group.html", gr=gr, day=day, att=att, grades=grades, hw=hw)

@app.post("/teacher/group/<int:gid>/attendance")
@need("teacher", "admin")
def t_att(gid):
    gr = my_group(gid); day = pdate(request.form.get("day"), today())
    for s in gr.students:
        st = request.form.get(f"s{s.id}")
        if st not in ("present", "late", "absent"): continue
        a = Attendance.query.filter_by(student_id=s.id, day=day).first() or Attendance(student_id=s.id, day=day)
        a.status = st; db.session.add(a)
    db.session.commit(); flash(LL("Посещаемость сохранена.", "Davomat saqlandi."), "ok")
    return redirect(url_for("t_group", gid=gid, d=day.isoformat()))

@app.post("/teacher/group/<int:gid>/grade")
@need("teacher", "admin")
def t_grade(gid):
    gr = my_group(gid); s = db.session.get(Student, request.form.get("student", type=int) or 0)
    score = request.form.get("score", type=int); subj = clean("subject", 80)
    if not s or s.group_id != gr.id or not subj or not score or not 1 <= score <= 5:
        flash(LL("Выберите ученика, предмет и оценку 1–5.", "O‘quvchi, fan va 1–5 baho tanlang."), "err")
    else:
        db.session.add(Grade(student_id=s.id, day=pdate(request.form.get("day"), today()), subject=subj, score=score, comment=clean("comment", 300), teacher_id=g.me.id))
        db.session.commit(); flash(LL("Оценка добавлена.", "Baho qo‘shildi."), "ok")
    return redirect(url_for("t_group", gid=gid, d=request.form.get("day", "")))

@app.post("/teacher/grade/<int:i>/delete")
@need("teacher", "admin")
def t_grade_del(i):
    gd = db.get_or_404(Grade, i)
    s = db.session.get(Student, gd.student_id)
    if g.me.role != "admin" and not (s and s.group and s.group.teacher_id == g.me.id): abort(403)
    db.session.delete(gd); db.session.commit(); return redirect(request.referrer or url_for("t_home"))

@app.post("/teacher/group/<int:gid>/homework")
@need("teacher", "admin")
def t_hw(gid):
    gr = my_group(gid)
    if request.form.get("act") == "delete":
        h = Homework.query.filter_by(id=request.form.get("id", type=int) or 0, group_id=gr.id).first()
        if h: db.session.delete(h)
    elif clean("title", 120):
        db.session.add(Homework(group_id=gr.id, day=today(), title=clean("title", 120), text=clean("text", 1000), due=pdate(request.form.get("due"))))
        flash(LL("Задание добавлено.", "Topshiriq qo‘shildi."), "ok")
    db.session.commit(); return redirect(url_for("t_group", gid=gid))

# ───────────────────────── родитель ─────────────────────────
@app.route("/parent")
@need("parent")
def p_home():
    kids = Student.query.filter_by(parent_id=g.me.id).all()
    if len(kids) == 1: return redirect(url_for("p_child", sid=kids[0].id))
    return render_template("p_home.html", kids=kids)

@app.route("/parent/child/<int:sid>")
@need("parent", "admin")
def p_child(sid):
    s = db.get_or_404(Student, sid)
    if g.me.role == "parent" and s.parent_id != g.me.id: abort(403)
    since = today() - timedelta(days=90)
    att = Attendance.query.filter(Attendance.student_id == s.id, Attendance.day >= since).order_by(Attendance.day.desc()).all()
    grades = Grade.query.filter_by(student_id=s.id).order_by(Grade.day.desc(), Grade.id.desc()).limit(60).all()
    cnt = {k: sum(1 for a in att if a.status == k) for k in ("present", "late", "absent")}
    total = len(att); pct = round(100 * (cnt["present"] + cnt["late"]) / total) if total else None
    avg = round(sum(x.score for x in grades) / len(grades), 2) if grades else None
    by_subj = {}
    for x in grades: by_subj.setdefault(x.subject, []).append(x.score)
    subj = sorted(((k, round(sum(v) / len(v), 1), len(v)) for k, v in by_subj.items()), key=lambda t: t[0])
    hw = Homework.query.filter_by(group_id=s.group_id).order_by(Homework.day.desc(), Homework.id.desc()).limit(10).all() if s.group_id else []
    news = Announcement.query.filter((Announcement.group_id == None) | (Announcement.group_id == s.group_id)).order_by(Announcement.day.desc(), Announcement.id.desc()).limit(8).all()
    return render_template("p_child.html", s=s, att=att[:30], grades=grades[:25], cnt=cnt, pct=pct, avg=avg, subj=subj, hw=hw, news=news)

# ───────────────────────── запуск ─────────────────────────
def ensure_admin():
    if User.query.filter_by(role="admin").first(): return
    pw = os.environ.get("ADMIN_PASSWORD")
    if not pw:
        if PROD: raise RuntimeError("Задайте ADMIN_PASSWORD для первого запуска")
        pw = "admin12345"; print("DEV: создан admin / admin12345")
    u = User(username=os.environ.get("ADMIN_USERNAME", "admin").lower(), role="admin", full_name="Администратор"); u.set_password(pw)
    db.session.add(u); db.session.commit()

with app.app_context():
    db.create_all(); ensure_admin()

@app.cli.command("seed-demo")
def seed_demo():
    """Демо-данные для проверки (НЕ запускать на боевой базе)."""
    import random
    if Branch.query.count(): print("Уже есть данные"); return
    bs = [Branch(city="Ташкент", area="Юнусабад", address="ул. Амира Темура, 15 (пример)", schedule="Пн, Ср, Пт 17:00–19:00", ages="6–17", phone="+998 90 111 22 33"),
          Branch(city="Янгиюль", area="Центр", address="ул. Самарканд, 8 (пример)", schedule="Вт, Чт, Сб 16:00–18:00", ages="6–16", phone="+998 90 222 33 44")]
    db.session.add_all(bs); db.session.flush()
    t = User(username="teacher", role="teacher", full_name="Рустам Каримов"); t.set_password("teacher123")
    p = User(username="parent", role="parent", full_name="Дилшод Алиев"); p.set_password("parent123")
    db.session.add_all([t, p]); db.session.flush()
    gr = Group(name="Группа А (6–9 лет)", branch_id=bs[0].id, teacher_id=t.id, schedule="Пн, Ср, Пт 17:00"); db.session.add(gr); db.session.flush()
    ss = [Student(full_name=n, birth_year=2014, group_id=gr.id, parent_id=p.id if i == 0 else None) for i, n in enumerate(["Азиз Алиев", "Бекзод Саидов", "Жасур Тошев", "Умар Рахимов"])]
    db.session.add_all(ss); db.session.flush()
    for s in ss:
        for d in range(12):
            day = today() - timedelta(days=d * 2 + 1)
            db.session.add(Attendance(student_id=s.id, day=day, status=random.choice(["present"] * 7 + ["late", "absent"])))
            if d % 3 == 0: db.session.add(Grade(student_id=s.id, day=day, subject=random.choice(["Строевая", "Физподготовка", "Знания"]), score=random.choice([3, 4, 4, 5, 5]), teacher_id=t.id))
    db.session.add(Homework(group_id=gr.id, day=today(), title="Подтягивания", text="Отработать хват и технику, 3 подхода.", due=today() + timedelta(days=3)))
    db.session.add(Announcement(title="Сбор в субботу", text="Выезд в горы, сбор в 07:30 у школы.", day=today()))
    db.session.commit(); print("Готово. teacher/teacher123, parent/parent123, admin/admin12345")

if __name__ == "__main__":
    app.run(debug=not PROD, port=int(os.environ.get("PORT", 5000)))
