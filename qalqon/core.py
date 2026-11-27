"""Общие помощники: язык, авторизация, CSRF, аудит, уведомления, файлы, отчёты."""
import os, re, secrets, threading, time, json, hashlib, smtplib, urllib.request, urllib.parse
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from functools import wraps
from flask import session, request, g, redirect, url_for, flash, abort, current_app
from sqlalchemy import func
from .models import *

TZ = timezone(timedelta(hours=5))


def today():
    return datetime.now(TZ).date()


# ───────── язык ─────────
def lang():
    return "ru" if session.get("lang") == "ru" else "uz"


def L(uz, ru):
    return ru if lang() == "ru" else uz


def pick(obj, field):
    """Значение поля с учётом языка (field_ru, при пустом — основное)."""
    if lang() == "ru":
        v = getattr(obj, field + "_ru", "")
        if v:
            return v
    return getattr(obj, field, "")


STATUS_NAMES = {
    "new": ("Yangi ariza", "Новая заявка"),
    "review": ("Ko‘rib chiqilmoqda", "На рассмотрении"),
    "interview": ("Suhbatga taklif qilindi", "Приглашён на собеседование"),
    "docs": ("Hujjatlar tekshirilmoqda", "Документы проверяются"),
    "accepted": ("Qabul qilindi", "Принят"),
    "rejected": ("Rad etildi", "Отказано"),
}
ATT_NAMES = {
    "present": ("Qatnashdi", "Присутствовал"), "late": ("Kechikdi", "Опоздал"),
    "absent": ("Qatnashmadi", "Отсутствовал"), "excused": ("Sababli", "Уважительная причина"),
}
WEEKDAYS = [("Dushanba", "Понедельник"), ("Seshanba", "Вторник"), ("Chorshanba", "Среда"),
            ("Payshanba", "Четверг"), ("Juma", "Пятница"), ("Shanba", "Суббота")]
MONTHS = [("yanvar", "январь"), ("fevral", "февраль"), ("mart", "март"), ("aprel", "апрель"), ("may", "май"),
          ("iyun", "июнь"), ("iyul", "июль"), ("avgust", "август"), ("sentabr", "сентябрь"),
          ("oktabr", "октябрь"), ("noyabr", "ноябрь"), ("dekabr", "декабрь")]
ACH_NAMES = {"sport": ("Sport", "Спорт"), "event": ("Tadbirlar", "Мероприятия"),
             "award": ("Mukofotlar", "Награды"), "study": ("O‘qish", "Учёба")}
ROLE_NAMES = {"admin": ("Administrator", "Администратор"), "teacher": ("O‘qituvchi", "Учитель"),
              "parent": ("Ota-ona", "Родитель"), "student": ("O‘quvchi", "Ученик")}
CATS = {"training": ("Mashg‘ulotlar", "Занятия"), "drill": ("Saf mashqlari", "Строевая"),
        "events": ("Tadbirlar", "Мероприятия"), "sport": ("Sport", "Спорт"), "study": ("Ta’lim", "Учёба")}
NEWS_CATS = {"news": ("Yangiliklar", "Новости"), "event": ("Tadbir", "Событие"),
             "achievement": ("Yutuq", "Достижение")}


def nm(table, key):
    d = table.get(key)
    return (d[1] if lang() == "ru" else d[0]) if d else key


def fmt_date(d, short=False):
    if not d:
        return ""
    if isinstance(d, datetime):
        d = d.astimezone(TZ).date() if d.tzinfo else d.date()
    if short:
        return d.strftime("%d.%m")
    return d.strftime("%d.%m.%Y")


def fmt_dt(d):
    return d.strftime("%d.%m.%Y %H:%M") if d else ""


def subj_name(s):
    return pick(s, "name") if s else ""


# ───────── настройки сайта ─────────
DEFAULT_SETTINGS = {
    "address": "Yangiyo‘l, Toshkent viloyati, O‘zbekiston",
    "address_ru": "Янгиюль, Ташкентская область, Узбекистан",
    "geo": "41.10261,69.09136",
    "phone": os.environ.get("SITE_PHONE", "+998 90 123 45 67"),
    "email": os.environ.get("SITE_EMAIL", "info@qalqon.uz"),
    "instagram": os.environ.get("SITE_INSTAGRAM", "https://www.instagram.com/qalqon.jasorat"),
    "telegram": os.environ.get("SITE_TELEGRAM", "https://t.me/qalqon"),
    "map_embed": "",
    "hours": "Du–Sha 08:00–18:00",
    "hours_ru": "Пн–Сб 08:00–18:00",
    "hero_image": "",
}


def site():
    s = getattr(g, "_site", None)
    if s is None:
        s = dict(DEFAULT_SETTINGS)
        try:
            for r in Setting.query.all():
                if r.value:
                    s[r.key] = r.value
        except Exception:
            db.session.rollback()
        g._site = s
    return s


def set_setting(k, v):
    r = db.session.get(Setting, k)
    if r:
        r.value = v
    else:
        db.session.add(Setting(key=k, value=v))


# ───────── авторизация / права ─────────
def pw_stamp(u):
    """Отпечаток текущего пароля: лежит в сессии, и после смены/сброса пароля все старые входы перестают работать."""
    return hashlib.sha256(("pv:" + u.password_hash).encode()).hexdigest()[:16]


def load_user():
    g.user = None
    uid = session.get("uid")
    if uid:
        u = db.session.get(User, uid)
        if u and u.active and secrets.compare_digest(str(session.get("pv", "")), pw_stamp(u)):
            g.user = u
        else:
            session.pop("uid", None)
            session.pop("pv", None)


def login_required(f):
    @wraps(f)
    def w(*a, **k):
        if not g.user:
            flash(L("Avval tizimga kiring.", "Сначала войдите в систему."), "warn")
            return redirect(url_for("auth.login", next=request.full_path if request.method == "GET" else None))
        if g.user.must_change and request.endpoint not in ("auth.account", "auth.logout"):
            flash(L("Davom etish uchun parolni almashtiring.", "Для продолжения смените пароль."), "warn")
            return redirect(url_for("auth.account"))
        return f(*a, **k)
    return w


def roles(*rs):
    def deco(f):
        @wraps(f)
        @login_required
        def w(*a, **k):
            if g.user.role not in rs:
                audit("denied", f"{request.method} {request.path}")
                abort(403)
            return f(*a, **k)
        return w
    return deco


def audit(action, detail="", user=None):
    try:
        u = user or getattr(g, "user", None)
        db.session.add(AuditLog(user_id=u.id if u else None, username=u.username if u else "",
                                action=action, detail=detail[:400], ip=(request.remote_addr or "")[:45]))
        db.session.commit()
    except Exception:
        db.session.rollback()


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(24)
    return session["_csrf"]


_attempts = {}


def throttled(key, limit=8, window=600):
    now = time.time()
    lst = [t for t in _attempts.get(key, []) if now - t < window]
    _attempts[key] = lst
    return len(lst) >= limit


def fail_attempt(key):
    now = time.time()
    if len(_attempts) > 5000:  # не даём словарю расти бесконечно от подбора разных логинов
        for k in [k for k, v in _attempts.items() if not v or now - v[-1] > 3600]:
            _attempts.pop(k, None)
    _attempts.setdefault(key, []).append(now)


def clear_attempts(key):
    _attempts.pop(key, None)


def valid_password(p):
    return len(p) >= 8 and any(c.isalpha() for c in p) and any(c.isdigit() for c in p)


PW_HINT = ("Kamida 8 belgi, harf va raqam.", "Минимум 8 символов, буквы и цифры.")


def gen_password():
    al = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(al) for _ in range(9)) + str(secrets.randbelow(90) + 10)


# ───────── доступ учителя ─────────
def teacher_assignments(u):
    return Assignment.query.filter_by(teacher_id=u.id).all()


def teacher_class_ids(u):
    ids = {a.class_id for a in teacher_assignments(u)}
    ids |= {c.id for c in SchoolClass.query.filter_by(teacher_id=u.id)}
    return ids


def can_teach(u, class_id, subject_id):
    return Assignment.query.filter_by(teacher_id=u.id, class_id=class_id, subject_id=subject_id).first() is not None


def can_class(u, class_id):
    return u.role == "admin" or class_id in teacher_class_ids(u)


def my_students(u):
    """Ученики, которых видит пользователь (ключевая проверка прав на данные детей)."""
    if u.role == "admin":
        return Student.query.order_by(Student.full_name).all()
    if u.role == "teacher":
        ids = teacher_class_ids(u)
        return Student.query.filter(Student.class_id.in_(ids)).order_by(Student.full_name).all() if ids else []
    if u.role == "parent":
        return sorted(u.children, key=lambda s: s.full_name)
    if u.role == "student":
        return Student.query.filter_by(user_id=u.id).all()
    return []


def can_see_student(u, st):
    if u.role == "admin":
        return True
    if u.role == "teacher":
        return st.class_id in teacher_class_ids(u)
    if u.role == "parent":
        return st in u.children
    if u.role == "student":
        return st.user_id == u.id
    return False


# ───────── уведомления ─────────
def _send_telegram(chat, text):
    tok = os.environ.get("TG_BOT_TOKEN")
    if not (tok and chat):
        return
    try:
        data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data, timeout=8)
    except Exception:
        pass


def _send_email(to, subject, text):
    host = os.environ.get("SMTP_HOST")
    if not (host and to):
        return
    try:
        m = EmailMessage()
        m["From"] = os.environ.get("SMTP_FROM", "noreply@qalqon.uz")
        m["To"] = to
        m["Subject"] = subject
        m.set_content(text)
        with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", 587)), timeout=10) as s:
            if os.environ.get("SMTP_USER"):
                s.starttls()
                s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASS", ""))
            s.send_message(m)
    except Exception:
        pass


def _push_hook(user_id, text):
    """Точка расширения для Push (FCM / Web Push / мобильное приложение)."""
    return None


def notify(users, kind, uz, ru="", link="", demo=False):
    """Единая отправка: в платформе + Email/Telegram/Push (если настроены)."""
    users = [u for u in (users if isinstance(users, (list, tuple, set)) else [users]) if u and u.active]
    out = []
    for u in {x.id: x for x in users}.values():
        db.session.add(Notification(user_id=u.id, kind=kind, text_uz=uz[:400], text_ru=(ru or uz)[:400],
                                    link=link, is_demo=demo))
        out.append((u.email, u.telegram_chat_id, u.id))
    for em, tg, uid in out:
        if tg or em:
            threading.Thread(target=lambda e=em, t=tg, i=uid: (
                _send_telegram(t, f"Qalqon: {uz}"), _send_email(e, "Qalqon Jasorat Maktabi", uz), _push_hook(i, uz)),
                daemon=True).start()


def parents_of(student):
    return list(student.parents)


def family_users(student):
    us = list(student.parents)
    if student.account:
        us.append(student.account)
    return us


def admins():
    return User.query.filter_by(role="admin", active=True).all()


# ───────── файлы ─────────
ALLOWED = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
           ".webp": "image/webp", ".doc": "application/msword",
           ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
           ".xls": "application/vnd.ms-excel",
           ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
           ".ppt": "application/vnd.ms-powerpoint",
           ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
           ".txt": "text/plain"}
MAGIC = {".pdf": b"%PDF", ".jpg": b"\xff\xd8", ".jpeg": b"\xff\xd8", ".png": b"\x89PNG", ".webp": b"RIFF"}
MAX_FILE = 5 * 1024 * 1024
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def save_upload(fs, owner_type, owner_id, images_only=False):
    """Сохранить загруженный файл. Возвращает File или None. Ошибки — flash."""
    if not fs or not fs.filename:
        return None
    name = os.path.basename(fs.filename.replace("\\", "/"))[:120]
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED or (images_only and ext not in IMG_EXT):
        flash(L(f"Fayl turi ruxsat etilmagan: {name}", f"Недопустимый тип файла: {name}"), "bad")
        return None
    data = fs.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        flash(L(f"Fayl 5 MB dan katta: {name}", f"Файл больше 5 МБ: {name}"), "bad")
        return None
    if not data:
        return None
    if ext in MAGIC and not data.startswith(MAGIC[ext]):
        flash(L(f"Fayl tarkibi kengaytmaga mos emas: {name}", f"Содержимое файла не соответствует типу: {name}"), "bad")
        return None
    f = File(owner_type=owner_type, owner_id=owner_id, name=re.sub(r"[^\w.\- ()]", "_", name),
             mime=ALLOWED[ext], size=len(data), data=data,
             uploader_id=g.user.id if getattr(g, "user", None) else None)
    db.session.add(f)
    db.session.flush()
    return f


def can_view_file(u, f):
    t = f.owner_type
    if t == "pub":
        return True
    if not u:
        return False
    if u.role == "admin":
        return True
    if t == "app":
        return False
    if t == "photo":
        st = Student.query.filter_by(photo_id=f.id).first()
        return bool(st and can_see_student(u, st))
    if t == "hw":
        hw = db.session.get(Homework, f.owner_id)
        return bool(hw and class_member(u, hw.class_id))
    if t == "mat":
        m = db.session.get(Material, f.owner_id)
        return bool(m and class_member(u, m.class_id))
    if t == "sub":
        s = db.session.get(Submission, f.owner_id)
        return bool(s and can_see_student(u, s.student))
    return False


def class_member(u, class_id):
    if u.role == "teacher":
        return class_id in teacher_class_ids(u)
    return any(s.class_id == class_id for s in my_students(u))


# ───────── оценки и отчёты ─────────
def avg(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def student_avg(st_id, start=None, end=None, subject_id=None):
    q = db.session.query(func.avg(Grade.score)).filter(Grade.student_id == st_id)
    if start:
        q = q.filter(Grade.day >= start)
    if end:
        q = q.filter(Grade.day <= end)
    if subject_id:
        q = q.filter(Grade.subject_id == subject_id)
    v = q.scalar()
    return round(float(v), 2) if v is not None else None


def att_counts(st_id, start=None, end=None):
    q = db.session.query(Attendance.status, func.count()).filter(Attendance.student_id == st_id)
    if start:
        q = q.filter(Attendance.day >= start)
    if end:
        q = q.filter(Attendance.day <= end)
    c = {k: 0 for k in ATT_NAMES}
    for s, n in q.group_by(Attendance.status):
        c[s] = n
    c["total"] = sum(c.values())
    c["rate"] = round(100 * (c["present"] + c["late"]) / c["total"]) if c["total"] else None
    return c


def school_year_start(d=None):
    d = d or today()
    return date(d.year if d.month >= 9 else d.year - 1, 9, 1)


def period_range(kind, ref=None):
    ref = ref or today()
    if kind == "week":
        s = ref - timedelta(days=ref.weekday())
        return s, s + timedelta(days=6)
    if kind == "month":
        s = ref.replace(day=1)
        e = (s.replace(year=s.year + 1, month=1) if s.month == 12 else s.replace(month=s.month + 1)) - timedelta(days=1)
        return s, e
    ys = school_year_start(ref)
    if kind == "quarter":
        Q = [(date(ys.year, 9, 1), date(ys.year, 11, 2)), (date(ys.year, 11, 3), date(ys.year, 12, 31)),
             (date(ys.year + 1, 1, 1), date(ys.year + 1, 3, 20)), (date(ys.year + 1, 3, 21), date(ys.year + 1, 5, 31))]
        for s, e in Q:
            if s <= ref <= e:
                return s, e
        return Q[-1] if ref > Q[-1][1] else Q[0]
    return ys, date(ys.year + 1, 8, 31)


PERIODS = {"week": ("Hafta", "Неделя"), "month": ("Oy", "Месяц"), "quarter": ("Chorak", "Четверть"),
           "year": ("O‘quv yili", "Учебный год")}


def student_report(st, kind="month"):
    s, e = period_range(kind)
    rows = []
    q = (db.session.query(Subject, func.avg(Grade.score), func.count(Grade.id))
         .join(Grade, Grade.subject_id == Subject.id)
         .filter(Grade.student_id == st.id, Grade.day >= s, Grade.day <= e).group_by(Subject.id).order_by(Subject.name))
    for sub, a, n in q:
        rows.append({"subject": sub, "avg": round(float(a), 2), "n": n})
    hw_total = hw_done = hw_checked = 0
    if st.class_id:
        hws = Homework.query.filter(Homework.class_id == st.class_id, Homework.due >= s, Homework.due <= e).all()
        hw_total = len(hws)
        subs = {x.hw_id: x for x in Submission.query.filter(Submission.student_id == st.id,
                Submission.hw_id.in_([h.id for h in hws] or [0]))}
        hw_done = len(subs)
        hw_checked = sum(1 for x in subs.values() if x.checked)
    return {
        "student": st, "start": s, "end": e, "kind": kind, "subjects": rows,
        "avg": student_avg(st.id, s, e), "att": att_counts(st.id, s, e),
        "remarks": Remark.query.filter(Remark.student_id == st.id, Remark.day >= s, Remark.day <= e).order_by(Remark.day.desc()).all(),
        "ach": Achievement.query.filter(Achievement.student_id == st.id, Achievement.day >= s, Achievement.day <= e).all(),
        "hw": {"total": hw_total, "done": hw_done, "checked": hw_checked},
    }


def hw_status(hw, st):
    """Статус домашнего задания для ученика: todo|late|submitted|checked."""
    sub = Submission.query.filter_by(hw_id=hw.id, student_id=st.id).first()
    if sub:
        return ("checked" if sub.checked else "submitted"), sub
    return ("late" if hw.due < today() else "todo"), None


HW_STATUS = {"todo": ("Bajarilishi kerak", "К выполнению"), "late": ("Muddati o‘tgan", "Просрочено"),
             "submitted": ("Topshirildi", "Сдано"), "checked": ("Tekshirildi", "Проверено")}


def video_info(url):
    """Разбирает ссылку и возвращает данные для плеера. Только разрешённые сервисы (без произвольных iframe)."""
    try: u = urllib.parse.urlparse((url or "").strip())
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
                v = urllib.parse.parse_qs(u.query).get("v", [""])[0]; vid = v if re.fullmatch(r"[\w-]{11}", v) else None
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

