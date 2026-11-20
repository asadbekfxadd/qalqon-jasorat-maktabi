"""Панель администратора."""
from collections import defaultdict
from datetime import timedelta, datetime, date
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort
from .models import *
from .core import *
from .ops import *

bp = Blueprint("admin", __name__, url_prefix="/admin")


def back(default="/admin"):
    ref = request.referrer or ""
    return redirect(ref if ref.startswith(request.host_url) else default)


def month_key(d):
    return f"{d.year}-{d.month:02d}"


def last_months(n=8):
    t = today().replace(day=1)
    out = []
    for i in range(n):
        y, m = t.year, t.month - i
        while m < 1:
            m += 12
            y -= 1
        out.append(f"{y}-{m:02d}")
    return out[::-1]


def month_label(k):
    y, m = k.split("-")
    return MONTHS[int(m) - 1][1 if lang() == "ru" else 0][:3].capitalize() + f" {y[2:]}"


def dash_stats(real):
    def f(q, model):
        return q.filter(model.is_demo == False) if real else q  # noqa: E712
    t = today()
    s_q = f(Student.query.filter_by(active=True), Student)
    total_students = s_q.count()
    att_today = {k: 0 for k in ATT_NAMES}
    q = db.session.query(Attendance.status, func.count()).filter(Attendance.day == t)
    if real:
        q = q.filter(Attendance.is_demo == False)  # noqa
    for s_, n in q.group_by(Attendance.status):
        att_today[s_] = n
    marked = sum(att_today.values())
    gq = db.session.query(func.avg(Grade.score)).filter(Grade.day >= school_year_start())
    if real:
        gq = gq.filter(Grade.is_demo == False)  # noqa
    avg_all = gq.scalar()
    months = last_months(8)
    first = date.fromisoformat(months[0] + "-01")
    # динамика успеваемости
    gm = defaultdict(list)
    gr = db.session.query(Grade.day, Grade.score).filter(Grade.day >= first)
    if real:
        gr = gr.filter(Grade.is_demo == False)  # noqa
    for d, sc in gr:
        gm[month_key(d)].append(sc)
    am = defaultdict(lambda: [0, 0])
    ar = db.session.query(Attendance.day, Attendance.status).filter(Attendance.day >= first)
    if real:
        ar = ar.filter(Attendance.is_demo == False)  # noqa
    for d, s_ in ar:
        am[month_key(d)][1] += 1
        if s_ in ("present", "late"):
            am[month_key(d)][0] += 1
    # классы
    cls_q = (db.session.query(SchoolClass.name, func.avg(Grade.score)).join(Student, Student.class_id == SchoolClass.id)
             .join(Grade, Grade.student_id == Student.id).group_by(SchoolClass.id, SchoolClass.name).order_by(SchoolClass.name))
    sub_q = (db.session.query(Subject, func.avg(Grade.score)).join(Grade, Grade.subject_id == Subject.id)
             .group_by(Subject.id).order_by(Subject.name))
    if real:
        cls_q, sub_q = cls_q.filter(Grade.is_demo == False), sub_q.filter(Grade.is_demo == False)  # noqa
    app_st = {k: 0 for k in STATUSES_}
    aq = db.session.query(Application.status, func.count())
    if real:
        aq = aq.filter(Application.is_demo == False)  # noqa
    for s_, n in aq.group_by(Application.status):
        app_st[s_] = n
    app_m = defaultdict(int)
    apq = db.session.query(Application.created).filter(Application.created >= datetime.combine(first, datetime.min.time()))
    if real:
        apq = apq.filter(Application.is_demo == False)  # noqa
    for (c,) in apq:
        app_m[month_key(c)] += 1
    return {
        "kpi": {
            "students": total_students,
            "teachers": f(User.query.filter_by(role="teacher", active=True), User).count(),
            "classes": f(SchoolClass.query, SchoolClass).count(),
            "new_apps": f(Application.query.filter_by(status="new"), Application).count(),
            "att_rate": round(100 * (att_today["present"] + att_today["late"]) / marked) if marked else None,
            "marked": marked, "absent": att_today["absent"] + att_today["excused"],
            "avg": round(float(avg_all), 2) if avg_all is not None else None,
        },
        "charts": {
            "months": [month_label(m) for m in months],
            "perf": [avg(gm[m]) for m in months],
            "att": [round(100 * am[m][0] / am[m][1]) if am[m][1] else None for m in months],
            "classes": [[n, round(float(a), 2)] for n, a in cls_q],
            "subjects": [[subj_name(s_), round(float(a), 2)] for s_, a in sub_q],
            "app_status": [[nm(STATUS_NAMES, k), app_st[k]] for k in STATUSES_],
            "app_months": [app_m[m] for m in months],
        },
    }


STATUSES_ = ("new", "review", "interview", "docs", "accepted", "rejected")


@bp.route("/")
@roles("admin")
def home():
    real = request.args.get("real") == "1"
    st = dash_stats(real)
    events = AuditLog.query.filter(AuditLog.action.notin_(["login", "logout", "file_view"])).order_by(AuditLog.id.desc()).limit(10).all()
    latest_apps = Application.query.order_by(Application.created.desc()).limit(5).all()
    demo = demo_counts()
    return render_template("admin/home.html", st=st, real=real, events=events, latest_apps=latest_apps, demo=demo)


def demo_counts():
    return User.query.filter_by(is_demo=True).count() + Student.query.filter_by(is_demo=True).count() + \
        Application.query.filter_by(is_demo=True).count()


# ───────── заявки ─────────
def apps_query():
    q = Application.query
    s, st, grade = request.args.get("q", "").strip(), request.args.get("status", ""), request.args.get("grade", "")
    if s:
        like = f"%{s}%"
        q = q.filter(db.or_(Application.child_name.ilike(like), Application.parent_name.ilike(like),
                            Application.number.ilike(like), Application.phone.ilike(like)))
    if st in STATUS_NAMES:
        q = q.filter_by(status=st)
    if grade:
        q = q.filter_by(grade=grade)
    d1, d2 = request.args.get("from"), request.args.get("to")
    if d1:
        q = q.filter(Application.created >= datetime.combine(parse_day(d1), datetime.min.time()))
    if d2:
        q = q.filter(Application.created < datetime.combine(parse_day(d2) + timedelta(days=1), datetime.min.time()))
    return q.order_by(Application.created.desc())


@bp.route("/applications")
@roles("admin")
def applications():
    items = apps_query().limit(500).all()
    counts = dict(db.session.query(Application.status, func.count()).group_by(Application.status).all())
    return render_template("admin/applications.html", items=items, counts=counts)


@bp.route("/applications/export")
@roles("admin")
def applications_export():
    items = apps_query().all()
    audit("export_applications", f"{len(items)} rows")
    hdr = ["№", "Sana / Дата", "Bola / Ребёнок", "Tug‘ilgan / Дата рожд.", "Ota-ona / Родитель", "Telefon", "Email", "Manzil / Адрес",
           "Oldingi maktab / Пред. школа", "Sinf / Класс", "Holat / Статус", "Qo‘shimcha / Доп."]
    rows = [[a.number, a.created.strftime("%Y-%m-%d %H:%M"), a.child_name, a.birth_date.isoformat(), a.parent_name, a.phone,
             a.email, a.address, a.prev_school, a.grade, nm(STATUS_NAMES, a.status), a.extra] for a in items]
    return xlsx_response("qabul-arizalar", hdr, rows, "Arizalar")


@bp.route("/applications/<int:aid>", methods=["GET", "POST"])
@roles("admin")
def application(aid):
    a = db.get_or_404(Application, aid)
    if request.method == "POST":
        st = request.form.get("status")
        if st in STATUS_NAMES:
            if st != a.status:
                audit("application_status", f"{a.number}: {a.status}→{st}")
                if a.email:
                    import threading
                    from .core import _send_email
                    threading.Thread(target=_send_email, daemon=True, args=(
                        a.email, f"Qalqon: ariza {a.number}",
                        f"Holat / Статус: {STATUS_NAMES[st][0]} / {STATUS_NAMES[st][1]}")).start()
            a.status = st
        a.note = request.form.get("note", "")[:2000]
        a.updated = datetime.utcnow()
        db.session.commit()
        flash(L("Saqlandi.", "Сохранено."), "ok")
        return redirect(url_for("admin.application", aid=aid))
    return render_template("admin/application.html", a=a)


@bp.route("/applications/<int:aid>/delete", methods=["POST"])
@roles("admin")
def application_delete(aid):
    a = db.get_or_404(Application, aid)
    File.query.filter_by(owner_type="app", owner_id=a.id).delete()
    audit("application_delete", a.number)
    db.session.delete(a)
    db.session.commit()
    flash(L("Ariza o‘chirildi.", "Заявка удалена."), "ok")
    return redirect(url_for("admin.applications"))


# ───────── пользователи ─────────
def make_username(base):
    base = re.sub(r"[^a-z0-9._]", "", base.lower())[:20] or "user"
    u, i = base, 1
    while User.query.filter_by(username=u).first():
        i += 1
        u = f"{base}{i}"
    return u


def create_user(role, full_name, username="", password="", phone="", email="", demo=False):
    username = username.strip().lower() or make_username({"parent": "ota", "teacher": "ustoz", "student": "oquvchi", "admin": "admin"}[role])
    pw = password or gen_password()
    u = User(username=username, role=role, full_name=full_name.strip()[:120], phone=phone.strip()[:30],
             email=email.strip()[:120], must_change=True, is_demo=demo)
    u.set_password(pw)
    db.session.add(u)
    db.session.flush()
    return u, pw


@bp.route("/users", methods=["GET", "POST"])
@roles("admin")
def users():
    f = request.form
    if request.method == "POST":
        act = f.get("act")
        if act == "create":
            role, name, uname = f.get("role"), f.get("full_name", "").strip(), f.get("username", "").strip().lower()
            pw = f.get("password", "")
            if role not in ROLES or len(name) < 3:
                flash(L("Rol va ismni to‘ldiring.", "Укажите роль и имя."), "bad")
            elif uname and (not re.fullmatch(r"[a-z0-9._]{3,40}", uname) or User.query.filter_by(username=uname).first()):
                flash(L("Login band yoki noto‘g‘ri (a–z, 0–9, . _ , kamida 3).", "Логин занят или неверен (a–z, 0–9, . _ , минимум 3)."), "bad")
            elif pw and not valid_password(pw):
                flash(L(*PW_HINT), "bad")
            else:
                u, pw = create_user(role, name, uname, pw, f.get("phone", ""), f.get("email", ""))
                audit("user_create", f"{u.username} ({role})")
                db.session.commit()
                flash(L(f"Hisob yaratildi. Login: {u.username} · Parol: {pw} (bir marta ko‘rsatiladi)",
                        f"Учётная запись создана. Логин: {u.username} · Пароль: {pw} (показывается один раз)"), "secret")
        else:
            u = db.get_or_404(User, int(f.get("id", 0)))
            me = u.id == g.user.id
            if act == "save":
                u.full_name = f.get("full_name", u.full_name).strip()[:120] or u.full_name
                u.phone, u.email = f.get("phone", "").strip()[:30], f.get("email", "").strip()[:120]
                if not me and f.get("role") in ROLES and f.get("role") != u.role:
                    audit("role_change", f"{u.username}: {u.role}→{f['role']}")
                    u.role = f["role"]
                db.session.commit()
                audit("user_update", u.username)
                flash(L("Saqlandi.", "Сохранено."), "ok")
            elif act == "toggle" and not me:
                u.active = not u.active
                db.session.commit()
                audit("user_active", f"{u.username}={u.active}")
                flash(L("Holat o‘zgartirildi.", "Статус изменён."), "ok")
            elif act == "reset":
                pw = gen_password()
                u.set_password(pw)
                u.must_change = True
                db.session.commit()
                audit("password_reset_admin", u.username)
                flash(L(f"Yangi vaqtinchalik parol: {u.username} / {pw}", f"Новый временный пароль: {u.username} / {pw}"), "secret")
        return redirect(url_for("admin.users", **{k: v for k, v in request.args.items()}))
    q = User.query
    role, s = request.args.get("role", ""), request.args.get("q", "").strip()
    if role in ROLES:
        q = q.filter_by(role=role)
    if s:
        q = q.filter(db.or_(User.full_name.ilike(f"%{s}%"), User.username.ilike(f"%{s}%"), User.phone.ilike(f"%{s}%")))
    return render_template("admin/users.html", items=q.order_by(User.role, User.full_name).limit(500).all(), role=role)


# ───────── ученики ─────────
@bp.route("/students")
@roles("admin")
def students():
    q = Student.query
    s, cid = request.args.get("q", "").strip(), request.args.get("class", "")
    if s:
        q = q.filter(Student.full_name.ilike(f"%{s}%"))
    if cid.isdigit():
        q = q.filter_by(class_id=int(cid))
    return render_template("admin/students.html", items=q.order_by(Student.full_name).limit(500).all(),
                           classes=SchoolClass.query.order_by(SchoolClass.name).all())


@bp.route("/students/new", methods=["GET", "POST"])
@bp.route("/students/<int:sid>", methods=["GET", "POST"])
@roles("admin")
def student(sid=None):
    st = db.get_or_404(Student, sid) if sid else None
    app_ = db.session.get(Application, request.args.get("app", type=int)) if request.args.get("app") else None
    f = request.form
    if request.method == "POST":
        act = f.get("act", "save")
        if act == "save":
            name = f.get("full_name", "").strip()
            if len(name) < 5:
                flash(L("To‘liq F.I.Sh. kiriting.", "Укажите полные ФИО."), "bad")
                return redirect(request.url)
            new = st is None
            if new:
                st = Student()
                db.session.add(st)
            st.full_name = name[:120]
            st.birth_date = parse_day(f.get("birth_date"), None) if f.get("birth_date") else None
            st.class_id = int(f["class_id"]) if f.get("class_id", "").isdigit() else None
            st.active = f.get("active", "1") == "1"
            st.application_no = f.get("application_no", "")[:20]
            db.session.flush()
            cred = []
            pids = [int(x) for x in f.getlist("parents") if x.isdigit()]
            st.parents = User.query.filter(User.id.in_(pids or [0]), User.role == "parent").all()
            if f.get("new_parent_name", "").strip():
                p, pw = create_user("parent", f["new_parent_name"], phone=f.get("new_parent_phone", ""), email=f.get("new_parent_email", ""))
                st.parents.append(p)
                cred.append(f"{L('Ota-ona', 'Родитель')}: {p.username} / {pw}")
            if f.get("make_login") == "1" and not st.account:
                u, pw = create_user("student", st.full_name)
                st.user_id = u.id
                cred.append(f"{L('O‘quvchi', 'Ученик')}: {u.username} / {pw}")
            ph = request.files.get("photo")
            if ph and ph.filename:
                fo = save_upload(ph, "photo", st.id, images_only=True)
                if fo:
                    st.photo_id = fo.id
            if new and f.get("app_id", "").isdigit():
                a = db.session.get(Application, int(f["app_id"]))
                if a:
                    a.status = "accepted"
            db.session.commit()
            audit("student_create" if new else "student_update", st.full_name)
            flash(L("Saqlandi.", "Сохранено."), "ok")
            if cred:
                flash(" · ".join(cred) + L(" (bir marta ko‘rsatiladi)", " (показывается один раз)"), "secret")
            return redirect(url_for("admin.student", sid=st.id))
        if not st:
            abort(404)
        if act == "delete":
            audit("student_delete", st.full_name)
            db.session.delete(st)
            db.session.commit()
            flash(L("O‘quvchi o‘chirildi.", "Ученик удалён."), "ok")
            return redirect(url_for("admin.students"))
        if act == "ach" and f.get("title", "").strip():
            db.session.add(Achievement(student_id=st.id, category=f.get("category", "sport"), title=f["title"].strip()[:200],
                                       day=parse_day(f.get("day")), is_demo=st.is_demo))
            notify(family_users(st), "achievement", f"Yangi yutuq: {st.full_name} — {f['title'][:100]}",
                   f"Новое достижение: {st.full_name} — {f['title'][:100]}", "/cabinet/achievements?c=%d" % st.id)
            db.session.commit()
            flash(L("Yutuq qo‘shildi.", "Достижение добавлено."), "ok")
        if act == "remark" and f.get("text", "").strip():
            db.session.add(Remark(student_id=st.id, teacher_id=g.user.id, kind="remark" if f.get("kind") == "remark" else "praise",
                                  text=f["text"].strip()[:400], day=parse_day(f.get("day")), is_demo=st.is_demo))
            db.session.commit()
            flash(L("Saqlandi.", "Сохранено."), "ok")
        return redirect(url_for("admin.student", sid=st.id))
    extra = {}
    if st:
        extra = dict(rep=student_report(st, request.args.get("p", "year")),
                     ach=Achievement.query.filter_by(student_id=st.id).order_by(Achievement.day.desc()).all(),
                     remarks=Remark.query.filter_by(student_id=st.id).order_by(Remark.day.desc()).limit(20).all())
    return render_template("admin/student.html", st=st, app=app_,
                           classes=SchoolClass.query.order_by(SchoolClass.name).all(),
                           parents=User.query.filter_by(role="parent", active=True).order_by(User.full_name).all(), **extra)


# ───────── классы, предметы, назначения ─────────
@bp.route("/classes", methods=["GET", "POST"])
@roles("admin")
def classes():
    f = request.form
    if request.method == "POST":
        act = f.get("act")
        if act == "create" and f.get("name", "").strip():
            c = SchoolClass(name=f["name"].strip()[:20], teacher_id=int(f["teacher_id"]) if f.get("teacher_id", "").isdigit() else None)
            db.session.add(c)
            audit("class_create", c.name)
        elif act == "save":
            c = db.get_or_404(SchoolClass, int(f["id"]))
            c.name = f.get("name", c.name).strip()[:20] or c.name
            c.teacher_id = int(f["teacher_id"]) if f.get("teacher_id", "").isdigit() else None
            audit("class_update", c.name)
        elif act == "delete":
            c = db.get_or_404(SchoolClass, int(f["id"]))
            if c.students:
                flash(L("Sinfda o‘quvchilar bor.", "В классе есть ученики."), "bad")
                return back()
            audit("class_delete", c.name)
            db.session.delete(c)
        elif act == "assign":
            cid, sid, tid = f.get("class_id", ""), f.get("subject_id", ""), f.get("teacher_id", "")
            if cid.isdigit() and sid.isdigit() and tid.isdigit() and not Assignment.query.filter_by(
                    class_id=int(cid), subject_id=int(sid), teacher_id=int(tid)).first():
                db.session.add(Assignment(class_id=int(cid), subject_id=int(sid), teacher_id=int(tid)))
                audit("assign", f"class={cid} subj={sid} teacher={tid}")
        elif act == "unassign":
            Assignment.query.filter_by(id=int(f["id"])).delete()
            audit("unassign", f["id"])
        db.session.commit()
        flash(L("Saqlandi.", "Сохранено."), "ok")
        return back("/admin/classes")
    return render_template("admin/classes.html", items=SchoolClass.query.order_by(SchoolClass.name).all(),
                           teachers=User.query.filter_by(role="teacher", active=True).order_by(User.full_name).all(),
                           subjects=Subject.query.order_by(Subject.name).all(),
                           assigns=Assignment.query.all())


@bp.route("/subjects", methods=["GET", "POST"])
@roles("admin")
def subjects():
    f = request.form
    if request.method == "POST":
        act = f.get("act")
        if act == "create" and f.get("name", "").strip():
            db.session.add(Subject(name=f["name"].strip()[:80], name_ru=f.get("name_ru", "").strip()[:80]))
        elif act == "save":
            s = db.get_or_404(Subject, int(f["id"]))
            s.name, s.name_ru = f.get("name", s.name).strip()[:80] or s.name, f.get("name_ru", "").strip()[:80]
        elif act == "delete":
            s = db.get_or_404(Subject, int(f["id"]))
            db.session.delete(s)
        audit("subject_" + (act or ""), f.get("name", f.get("id", "")))
        db.session.commit()
        flash(L("Saqlandi.", "Сохранено."), "ok")
        return redirect(url_for("admin.subjects"))
    return render_template("admin/subjects.html", items=Subject.query.order_by(Subject.name).all())


# ───────── расписание ─────────
@bp.route("/schedule", methods=["GET", "POST"])
@roles("admin")
def schedule():
    f = request.form
    cid = request.values.get("class", type=int)
    if request.method == "POST":
        if f.get("act") == "add" and cid:
            try:
                db.session.add(Lesson(class_id=cid, subject_id=int(f["subject_id"]), weekday=int(f["weekday"]),
                                      number=int(f.get("number") or 1), start=f.get("start", "08:30")[:5], end=f.get("end", "09:15")[:5],
                                      teacher_id=int(f["teacher_id"]) if f.get("teacher_id", "").isdigit() else None,
                                      room=f.get("room", "")[:20]))
                db.session.commit()
                audit("lesson_add", f"class={cid}")
                flash(L("Dars qo‘shildi.", "Урок добавлен."), "ok")
            except (KeyError, ValueError):
                flash(L("Maydonlarni tekshiring.", "Проверьте поля."), "bad")
        elif f.get("act") == "del":
            Lesson.query.filter_by(id=int(f["id"])).delete()
            db.session.commit()
            audit("lesson_delete", f["id"])
        return redirect(url_for("admin.schedule", **{"class": cid}))
    classes_ = SchoolClass.query.order_by(SchoolClass.name).all()
    lessons = Lesson.query.filter_by(class_id=cid).order_by(Lesson.weekday, Lesson.number).all() if cid else []
    return render_template("admin/schedule.html", classes=classes_, cid=cid, lessons=lessons,
                           subjects=Subject.query.order_by(Subject.name).all(),
                           teachers=User.query.filter_by(role="teacher", active=True).order_by(User.full_name).all())


# ───────── посещаемость, оценки, ДЗ ─────────
@bp.route("/attendance", methods=["GET", "POST"])
@roles("admin")
def attendance():
    cid, day = request.values.get("class", type=int), parse_day(request.values.get("day"))
    kl = db.session.get(SchoolClass, cid) if cid else None
    if request.method == "POST" and kl:
        for st in kl.students:
            s = request.form.get(f"att_{st.id}")
            if s:
                set_attendance(st, day, s, request.form.get(f"reason_{st.id}", ""), g.user)
        db.session.commit()
        audit("attendance_admin", f"{kl.name} {day}")
        flash(L("Davomat saqlandi.", "Посещаемость сохранена."), "ok")
        return redirect(url_for("admin.attendance", **{"class": cid, "day": day.isoformat()}))
    att = {a.student_id: a for a in Attendance.query.filter_by(day=day).all()} if kl else {}
    return render_template("admin/attendance.html", classes=SchoolClass.query.order_by(SchoolClass.name).all(), kl=kl, day=day, att=att)


@bp.route("/grades", methods=["GET", "POST"])
@roles("admin")
def grades():
    if request.method == "POST" and request.form.get("act") == "delete":
        Grade.query.filter_by(id=int(request.form["id"])).delete()
        db.session.commit()
        audit("grade_delete", request.form["id"])
        return back("/admin/grades")
    q = Grade.query.join(Student)
    a = request.args
    if a.get("class", "").isdigit():
        q = q.filter(Student.class_id == int(a["class"]))
    if a.get("subject", "").isdigit():
        q = q.filter(Grade.subject_id == int(a["subject"]))
    if a.get("q"):
        q = q.filter(Student.full_name.ilike(f"%{a['q']}%"))
    return render_template("admin/grades.html", items=q.order_by(Grade.day.desc(), Grade.id.desc()).limit(300).all(),
                           classes=SchoolClass.query.order_by(SchoolClass.name).all(), subjects=Subject.query.order_by(Subject.name).all())


@bp.route("/homework", methods=["GET", "POST"])
@roles("admin")
def homework():
    if request.method == "POST" and request.form.get("act") == "delete":
        h = db.get_or_404(Homework, int(request.form["id"]))
        File.query.filter_by(owner_type="hw", owner_id=h.id).delete()
        db.session.delete(h)
        db.session.commit()
        audit("homework_delete", request.form["id"])
        return back("/admin/homework")
    q = Homework.query
    if request.args.get("class", "").isdigit():
        q = q.filter_by(class_id=int(request.args["class"]))
    items = q.order_by(Homework.due.desc()).limit(200).all()
    counts = {h.id: (len(h.subs), len(h.klass.students)) for h in items}
    return render_template("admin/homework.html", items=items, counts=counts, classes=SchoolClass.query.order_by(SchoolClass.name).all())


@bp.route("/announcements", methods=["GET", "POST"])
@roles("admin")
def announcements():
    f = request.form
    if request.method == "POST":
        if f.get("act") == "create" and f.get("title", "").strip():
            cid = int(f["class_id"]) if f.get("class_id", "").isdigit() else None
            a = Announcement(title=f["title"].strip()[:200], text=f.get("text", "")[:4000], class_id=cid, author_id=g.user.id)
            db.session.add(a)
            if cid:
                targets = [u for s in Student.query.filter_by(class_id=cid) for u in family_users(s)]
            else:
                targets = User.query.filter(User.role != "admin", User.active == True).all()  # noqa
            notify(targets, "announcement", f"Maktabda yangi e’lon: {a.title}", f"Новое объявление в школе: {a.title}", "/cabinet/school")
            db.session.commit()
            audit("announcement", a.title)
            flash(L("E’lon e’lon qilindi.", "Объявление опубликовано."), "ok")
        elif f.get("act") == "delete":
            Announcement.query.filter_by(id=int(f["id"])).delete()
            db.session.commit()
        return redirect(url_for("admin.announcements"))
    return render_template("admin/announcements.html", items=Announcement.query.order_by(Announcement.created.desc()).limit(100).all(),
                           classes=SchoolClass.query.order_by(SchoolClass.name).all())


# ───────── отчёты ─────────
@bp.route("/reports")
@roles("admin")
def reports():
    kind = request.args.get("p", "month")
    kind = kind if kind in PERIODS else "month"
    cid, sid = request.args.get("class", type=int), request.args.get("student", type=int)
    classes_ = SchoolClass.query.order_by(SchoolClass.name).all()
    rep = srep = None
    if sid:
        srep = student_report(db.get_or_404(Student, sid), kind)
    elif cid:
        rep = class_report(db.get_or_404(SchoolClass, cid), kind)
        if request.args.get("xlsx"):
            audit("export_report", rep["klass"].name)
            return class_report_xlsx(rep, f"hisobot-{rep['klass'].name}")
    return render_template("admin/reports.html", classes=classes_, kind=kind, cid=cid, rep=rep, srep=srep,
                           students=Student.query.order_by(Student.full_name).all())


# ───────── контент сайта ─────────
@bp.route("/content", methods=["GET", "POST"])
@roles("admin")
def content():
    f = request.form
    if request.method == "POST":
        act = f.get("act")
        if act == "settings":
            for k in DEFAULT_SETTINGS:
                if k in f and k != "hero_image":
                    set_setting(k, f[k].strip()[:600])
            for k in ("instagram", "telegram"):
                if f.get(k) and not f[k].startswith("https://"):
                    set_setting(k, DEFAULT_SETTINGS[k])
            hf = save_upload(request.files.get("hero"), "pub", None, images_only=True)
            if hf:
                set_setting("hero_image", str(hf.id))
            elif f.get("clear_hero"):
                set_setting("hero_image", "")
            audit("settings_update")
        elif act == "news" and f.get("title", "").strip():
            n = News(title=f["title"].strip()[:200], title_ru=f.get("title_ru", "").strip()[:200], body=f.get("body", "")[:6000],
                     body_ru=f.get("body_ru", "")[:6000], category=f.get("category", "news") if f.get("category") in NEWS_CATS else "news",
                     day=parse_day(f.get("day")), video_url=f.get("video_url", "").strip()[:300] if video_info(f.get("video_url")) else "")
            db.session.add(n)
            db.session.flush()
            fo = save_upload(request.files.get("image"), "pub", None, images_only=True)
            if fo:
                n.image_id = fo.id
            audit("news_create", n.title)
        elif act == "staff" and f.get("full_name", "").strip():
            s = Staff(full_name=f["full_name"].strip()[:120], position=f.get("position", "")[:160], position_ru=f.get("position_ru", "")[:160],
                      specialty=f.get("specialty", "")[:160], specialty_ru=f.get("specialty_ru", "")[:160], bio=f.get("bio", "")[:2000],
                      bio_ru=f.get("bio_ru", "")[:2000], sort=int(f.get("sort") or 100))
            db.session.add(s)
            db.session.flush()
            fo = save_upload(request.files.get("photo"), "pub", None, images_only=True)
            if fo:
                s.photo_id = fo.id
            audit("staff_create", s.full_name)
        elif act == "gallery":
            vu = f.get("video_url", "").strip()
            gi = GalleryItem(title=f.get("title", "").strip()[:160], category=f.get("category") if f.get("category") in CATS else "training",
                             video_url=vu[:300] if video_info(vu) else "")
            db.session.add(gi)
            db.session.flush()
            fo = save_upload(request.files.get("image"), "pub", None, images_only=True)
            if fo:
                gi.image_id = fo.id
            if not gi.image_id and not gi.video_url:
                db.session.rollback()
                flash(L("Rasm yuklang yoki to‘g‘ri video havolasini kiriting.", "Загрузите фото или укажите корректную ссылку на видео."), "bad")
                return redirect(url_for("admin.content"))
            audit("gallery_add", gi.title)
        elif act in ("del_news", "del_staff", "del_gallery"):
            model = {"del_news": News, "del_staff": Staff, "del_gallery": GalleryItem}[act]
            o = db.get_or_404(model, int(f["id"]))
            for fld in ("image_id", "photo_id"):
                if getattr(o, fld, None):
                    File.query.filter_by(id=getattr(o, fld)).delete()
            db.session.delete(o)
            audit(act, f["id"])
        db.session.commit()
        flash(L("Saqlandi.", "Сохранено."), "ok")
        return redirect(url_for("admin.content") + ("#" + f["tab"] if f.get("tab") else ""))
    return render_template("admin/content.html", news=News.query.order_by(News.day.desc()).all(),
                           staff=Staff.query.order_by(Staff.sort).all(), gallery=GalleryItem.query.order_by(GalleryItem.created.desc()).all(),
                           S=site(), defaults=DEFAULT_SETTINGS)


# ───────── журнал действий, демо ─────────
@bp.route("/audit")
@roles("admin")
def audit_log():
    q = AuditLog.query
    a, u = request.args.get("action", ""), request.args.get("q", "")
    if a:
        q = q.filter_by(action=a)
    if u:
        q = q.filter(AuditLog.username.ilike(f"%{u}%"))
    actions = [r[0] for r in db.session.query(AuditLog.action).distinct().order_by(AuditLog.action)]
    return render_template("admin/audit.html", items=q.order_by(AuditLog.id.desc()).limit(300).all(), actions=actions)


@bp.route("/demo", methods=["GET", "POST"])
@roles("admin")
def demo():
    from .seed import load_demo, purge_demo, DEMO_PASSWORD
    if request.method == "POST":
        if request.form.get("act") == "load":
            if Student.query.filter_by(is_demo=True).count():
                flash(L("Demo ma’lumotlar allaqachon yuklangan.", "Демо-данные уже загружены."), "warn")
            else:
                load_demo()
                audit("demo_load")
                flash(L(f"Demo yuklandi. Hisoblar: demo_teacher, demo_parent, demo_student · parol: {DEMO_PASSWORD}",
                        f"Демо загружено. Аккаунты: demo_teacher, demo_parent, demo_student · пароль: {DEMO_PASSWORD}"), "ok")
        elif request.form.get("act") == "purge":
            purge_demo()
            audit("demo_purge")
            flash(L("Barcha demo ma’lumotlar o‘chirildi.", "Все демо-данные удалены."), "ok")
        return redirect(url_for("admin.demo"))
    counts = {
        "Users": User.query.filter_by(is_demo=True).count(), "Students": Student.query.filter_by(is_demo=True).count(),
        "Grades": Grade.query.filter_by(is_demo=True).count(), "Applications": Application.query.filter_by(is_demo=True).count(),
        "News": News.query.filter_by(is_demo=True).count(),
    }
    return render_template("admin/demo.html", counts=counts, pw=DEMO_PASSWORD)


# ───────── оплаты ─────────
@bp.route("/payments", methods=["GET", "POST"])
@roles("admin")
def payments():
    f = request.form
    if request.method == "POST":
        act = f.get("act")
        st = db.session.get(Student, int(f.get("student_id", 0) or 0))
        if not st:
            abort(404)
        if act == "fee":
            t = Tuition.query.filter_by(student_id=st.id).first() or Tuition(student_id=st.id, is_demo=st.is_demo)
            t.monthly_fee = max(int(f.get("fee", "0").replace(" ", "") or 0), 0)
            db.session.add(t)
            audit("tuition_fee", f"{st.full_name}={t.monthly_fee}")
        elif act == "pay":
            try:
                amt = int(f.get("amount", "0").replace(" ", ""))
            except ValueError:
                amt = 0
            if amt <= 0:
                flash(L("Summani kiriting.", "Укажите сумму."), "bad")
                return back("/admin/payments")
            db.session.add(Payment(student_id=st.id, amount=amt, day=parse_day(f.get("day")),
                                   method=f.get("method") if f.get("method") in METHODS else "cash",
                                   note=f.get("note", "")[:200], created_by=g.user.id, is_demo=st.is_demo))
            notify(st.parents, "payment", f"To‘lov qabul qilindi: {st.full_name} — {money(amt)} so‘m",
                   f"Платёж получен: {st.full_name} — {money(amt)} сум", "/cabinet/payments?c=%d" % st.id, demo=st.is_demo)
            audit("payment", f"{st.full_name}: {amt}")
        elif act == "del_pay":
            Payment.query.filter_by(id=int(f["id"]), student_id=st.id).delete()
            audit("payment_delete", f"{st.full_name}")
        db.session.commit()
        flash(L("Saqlandi.", "Сохранено."), "ok")
        return back("/admin/payments")
    cid = request.args.get("class", type=int)
    q = Student.query.filter_by(active=True)
    if cid:
        q = q.filter_by(class_id=cid)
    rows = [(s, student_balance(s)) for s in q.order_by(Student.full_name)]
    if request.args.get("debt"):
        rows = [r for r in rows if r[1]["debt"] > 0]
    if request.args.get("xlsx"):
        audit("export_payments", f"{len(rows)} rows")
        return xlsx_response("tolovlar", ["O‘quvchi / Ученик", "Sinf / Класс", "Oylik / В месяц", "Hisoblangan / Начислено", "To‘langan / Оплачено", "Qarz / Долг"],
                             [[s.full_name, s.klass.name if s.klass else "", b["fee"], b["due"], b["paid"], b["debt"]] for s, b in rows], "To‘lovlar")
    ids = [s.id for s, _ in rows]
    recent = Payment.query.filter(Payment.student_id.in_(ids or [0])).order_by(Payment.day.desc(), Payment.id.desc()).limit(30).all()
    m_start = today().replace(day=1)
    month_total = db.session.query(func.coalesce(func.sum(Payment.amount), 0)).filter(Payment.day >= m_start).scalar()
    return render_template("admin/payments.html", rows=rows, recent=recent, METHODS=METHODS, money=money,
                           classes=SchoolClass.query.order_by(SchoolClass.name).all(), cid=cid,
                           month_total=int(month_total), total_debt=sum(b["debt"] for _, b in rows))


@bp.route("/grid")
@roles("admin")
def grid():
    cid, sid = request.args.get("class", type=int), request.args.get("subject", type=int)
    ym = request.args.get("m") or today().strftime("%Y-%m")
    try:
        start = date.fromisoformat(ym + "-01")
    except ValueError:
        start = today().replace(day=1)
    end = period_range("month", start)[1]
    kl = db.session.get(SchoolClass, cid) if cid else None
    data = grid_data(kl, sid, start, end) if kl else None
    return render_template("admin/grid.html", classes=SchoolClass.query.order_by(SchoolClass.name).all(),
                           subjects=Subject.query.order_by(Subject.name).all(), kl=kl, sid=sid, ym=start.strftime("%Y-%m"), data=data)
