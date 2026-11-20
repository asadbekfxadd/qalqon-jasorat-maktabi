"""Кабинет учителя: доступ только к назначенным классам и предметам."""
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort
from .models import *
from .core import *
from .ops import *

bp = Blueprint("teacher", __name__, url_prefix="/teacher")


def my_pairs():
    """[(класс, предмет)] назначенные учителю."""
    return [(a.klass, a.subject) for a in sorted(teacher_assignments(g.user), key=lambda a: (a.klass.name, a.subject.name))]


def my_classes():
    ids = teacher_class_ids(g.user)
    return SchoolClass.query.filter(SchoolClass.id.in_(ids or [0])).order_by(SchoolClass.name).all()


def class_or_403(cid):
    if not cid or cid not in teacher_class_ids(g.user):
        audit("denied", f"class {cid}")
        abort(403)
    return db.get_or_404(SchoolClass, cid)


def pair_or_403(cid, sid):
    if not (cid and sid and can_teach(g.user, cid, sid)):
        audit("denied", f"class {cid} subject {sid}")
        abort(403)
    return db.get_or_404(SchoolClass, cid), db.get_or_404(Subject, sid)


@bp.route("/")
@roles("teacher")
def home():
    u, t = g.user, today()
    pairs = my_pairs()
    cls = my_classes()
    n_students = Student.query.filter(Student.class_id.in_([c.id for c in cls] or [0])).count()
    lessons = Lesson.query.filter_by(teacher_id=u.id, weekday=t.weekday()).order_by(Lesson.number).all()
    now = datetime.now(TZ).strftime("%H:%M")
    upcoming = [l for l in lessons if l.end >= now][:3]
    hw_ids = [h.id for h in Homework.query.filter_by(teacher_id=u.id)]
    unchecked = Submission.query.filter(Submission.hw_id.in_(hw_ids or [0]), Submission.checked == False).count()  # noqa
    return render_template("teacher/home.html", pairs=pairs, cls=cls, n_students=n_students, lessons=lessons,
                           upcoming=upcoming, unchecked=unchecked)


@bp.route("/journal", methods=["GET", "POST"])
@roles("teacher")
def journal():
    pairs = my_pairs()
    cid, sid = request.values.get("class", type=int), request.values.get("subject", type=int)
    day = parse_day(request.values.get("day"))
    if not (cid and sid) and pairs:
        cid, sid = pairs[0][0].id, pairs[0][1].id
    if not pairs:
        return render_template("teacher/journal.html", pairs=[], kl=None)
    kl, sub = pair_or_403(cid, sid)
    f = request.form
    if request.method == "POST":
        n_g = n_a = 0
        for st in kl.students:
            s = f.get(f"att_{st.id}")
            if s:
                set_attendance(st, day, s, f.get(f"reason_{st.id}", ""), g.user)
                n_a += 1
            sc = f.get(f"score_{st.id}", "")
            if sc.isdigit() and 1 <= int(sc) <= 5:
                add_grade(st, sub, g.user, int(sc), f.get(f"comment_{st.id}", ""), day,
                          f.get("kind", "lesson") if f.get("kind") in ("lesson", "test", "quarter") else "lesson")
                n_g += 1
            if f.get(f"remark_{st.id}", "").strip():
                db.session.add(Remark(student_id=st.id, teacher_id=g.user.id, kind="remark" if f.get(f"rk_{st.id}") == "remark" else "praise",
                                      text=f[f"remark_{st.id}"].strip()[:400], day=day, is_demo=st.is_demo))
        db.session.commit()
        audit("journal_save", f"{kl.name}/{sub.name} {day}: att={n_a} grades={n_g}")
        flash(L(f"Saqlandi: {n_g} ta baho, {n_a} ta davomat belgisi.", f"Сохранено: оценок — {n_g}, отметок посещаемости — {n_a}."), "ok")
        return redirect(url_for("teacher.journal", **{"class": cid, "subject": sid, "day": day.isoformat()}))
    att = {a.student_id: a for a in Attendance.query.filter_by(day=day).all()}
    last = {}
    for st in kl.students:
        last[st.id] = Grade.query.filter_by(student_id=st.id, subject_id=sid).order_by(Grade.day.desc(), Grade.id.desc()).limit(6).all()
    avgs = {st.id: student_avg(st.id, subject_id=sid) for st in kl.students}
    return render_template("teacher/journal.html", pairs=pairs, kl=kl, sub=sub, day=day, att=att, last=last, avgs=avgs)


@bp.route("/student/<int:sid>", methods=["GET", "POST"])
@roles("teacher")
def student(sid):
    st = db.get_or_404(Student, sid)
    if not can_see_student(g.user, st):
        audit("denied", f"student {sid}")
        abort(403)
    my_subj = {a.subject_id for a in teacher_assignments(g.user) if a.class_id == st.class_id}
    if request.method == "POST":
        f = request.form
        if f.get("act") == "del_grade":
            gr = db.get_or_404(Grade, int(f["id"]))
            if gr.student_id == st.id and gr.subject_id in my_subj:
                db.session.delete(gr)
                db.session.commit()
                audit("grade_delete", f"{st.full_name}")
        elif f.get("act") == "remark" and f.get("text", "").strip():
            db.session.add(Remark(student_id=st.id, teacher_id=g.user.id, kind="remark" if f.get("kind") == "remark" else "praise",
                                  text=f["text"].strip()[:400], day=today(), is_demo=st.is_demo))
            db.session.commit()
            flash(L("Saqlandi.", "Сохранено."), "ok")
        return redirect(url_for("teacher.student", sid=sid))
    grades = Grade.query.filter(Grade.student_id == st.id, Grade.subject_id.in_(my_subj or [0])).order_by(Grade.day.desc()).all()
    per = [(s, student_avg(st.id, subject_id=s.id)) for s in Subject.query.filter(Subject.id.in_(my_subj or [0])).order_by(Subject.name)]
    return render_template("teacher/student.html", st=st, grades=grades, per=per, my_subj=my_subj,
                           att=att_counts(st.id, school_year_start()),
                           remarks=Remark.query.filter_by(student_id=st.id).order_by(Remark.day.desc()).limit(15).all())


@bp.route("/homework", methods=["GET", "POST"])
@roles("teacher")
def homework():
    pairs = my_pairs()
    f = request.form
    if request.method == "POST":
        try:
            cid, sid = [int(x) for x in f.get("pair", "").split(":")]
        except ValueError:
            abort(400)
        kl, sub = pair_or_403(cid, sid)
        title = f.get("title", "").strip()
        due = parse_day(f.get("due"), None) if f.get("due") else None
        if not title or not due:
            flash(L("Mavzu va muddatni kiriting.", "Укажите тему и срок."), "bad")
            return redirect(url_for("teacher.homework"))
        h = Homework(class_id=cid, subject_id=sid, teacher_id=g.user.id, title=title[:200], text=f.get("text", "")[:5000],
                     due=due, is_demo=any(s.is_demo for s in kl.students[:1]))
        db.session.add(h)
        db.session.flush()
        for fs in request.files.getlist("files")[:5]:
            save_upload(fs, "hw", h.id)
        targets = [u for s in kl.students for u in family_users(s)]
        notify(targets, "homework", f"Yangi uy vazifasi berildi: {sub.name} — {h.title} (muddat {fmt_date(due)})",
               f"Новое домашнее задание: {sub.name_ru or sub.name} — {h.title} (срок {fmt_date(due)})", "/cabinet/homework", demo=h.is_demo)
        db.session.commit()
        audit("homework_create", f"{kl.name}/{sub.name}: {h.title}")
        flash(L("Uy vazifasi yaratildi.", "Домашнее задание создано."), "ok")
        return redirect(url_for("teacher.homework_one", hid=h.id))
    items = Homework.query.filter_by(teacher_id=g.user.id).order_by(Homework.due.desc()).limit(100).all()
    info = {h.id: (len(h.subs), sum(1 for s in h.subs if not s.checked), len(h.klass.students)) for h in items}
    return render_template("teacher/homework.html", pairs=pairs, items=items, info=info)


@bp.route("/homework/<int:hid>", methods=["GET", "POST"])
@roles("teacher")
def homework_one(hid):
    h = db.get_or_404(Homework, hid)
    if h.teacher_id != g.user.id and not can_teach(g.user, h.class_id, h.subject_id):
        abort(403)
    if request.method == "POST":
        f = request.form
        sub = db.get_or_404(Submission, int(f.get("sub", 0)))
        if sub.hw_id != h.id:
            abort(403)
        sc = f.get("score", "")
        sub.feedback = f.get("feedback", "")[:300]
        sub.checked = True
        if sc.isdigit() and 1 <= int(sc) <= 5:
            sub.score = int(sc)
            add_grade(sub.student, h.subject, g.user, sub.score, f"{L('Uy vazifasi', 'ДЗ')}: {h.title}", today(), "homework")
        else:
            notify(family_users(sub.student), "homework", f"Uy vazifasi tekshirildi: {h.title}", f"Домашнее задание проверено: {h.title}",
                   "/cabinet/homework?c=%d" % sub.student_id, demo=sub.is_demo)
        db.session.commit()
        audit("homework_check", f"{h.title}: {sub.student.full_name}")
        flash(L("Tekshirildi.", "Проверено."), "ok")
        return redirect(url_for("teacher.homework_one", hid=hid))
    done = {s.student_id: s for s in h.subs}
    return render_template("teacher/homework_one.html", h=h, done=done, students=h.klass.students)


@bp.route("/materials", methods=["GET", "POST"])
@roles("teacher")
def materials():
    pairs = my_pairs()
    f = request.form
    if request.method == "POST":
        if f.get("act") == "delete":
            m = db.get_or_404(Material, int(f["id"]))
            if m.teacher_id == g.user.id:
                File.query.filter_by(owner_type="mat", owner_id=m.id).delete()
                db.session.delete(m)
                db.session.commit()
        else:
            try:
                cid, sid = [int(x) for x in f.get("pair", "").split(":")]
            except ValueError:
                abort(400)
            kl, sub = pair_or_403(cid, sid)
            link = f.get("link", "").strip()
            if not f.get("title", "").strip():
                flash(L("Nomini kiriting.", "Укажите название."), "bad")
                return redirect(url_for("teacher.materials"))
            m = Material(class_id=cid, subject_id=sid, teacher_id=g.user.id, title=f["title"].strip()[:200], text=f.get("text", "")[:3000],
                         link=link[:300] if link.startswith("https://") else "", is_demo=any(s.is_demo for s in kl.students[:1]))
            db.session.add(m)
            db.session.flush()
            for fs in request.files.getlist("files")[:5]:
                save_upload(fs, "mat", m.id)
            db.session.commit()
            audit("material_add", m.title)
            flash(L("Material qo‘shildi.", "Материал добавлен."), "ok")
        return redirect(url_for("teacher.materials"))
    return render_template("teacher/materials.html", pairs=pairs, items=Material.query.filter_by(teacher_id=g.user.id).order_by(Material.created.desc()).all())


@bp.route("/stats")
@roles("teacher")
def stats():
    pairs = my_pairs()
    out = []
    for kl, sub in pairs:
        rows = [(st, student_avg(st.id, subject_id=sub.id), att_counts(st.id, school_year_start())["rate"]) for st in kl.students]
        vals = [r[1] for r in rows if r[1] is not None]
        dist = {k: Grade.query.join(Student).filter(Student.class_id == kl.id, Grade.subject_id == sub.id, Grade.score == k).count() for k in range(1, 6)}
        out.append({"kl": kl, "sub": sub, "rows": rows, "avg": avg(vals), "dist": dist})
    return render_template("teacher/stats.html", out=out)


@bp.route("/reports")
@roles("teacher")
def reports():
    kind = request.args.get("p", "month")
    kind = kind if kind in PERIODS else "month"
    cid = request.args.get("class", type=int)
    rep = None
    if cid:
        kl = class_or_403(cid)
        subs = {a.subject_id for a in teacher_assignments(g.user) if a.class_id == cid}
        rep = class_report(kl, kind, subs)
        if request.args.get("xlsx"):
            audit("export_report", kl.name)
            return class_report_xlsx(rep, f"hisobot-{kl.name}")
    return render_template("teacher/reports.html", classes=my_classes(), cid=cid, kind=kind, rep=rep)


@bp.route("/announce", methods=["GET", "POST"])
@roles("teacher")
def announce():
    f = request.form
    if request.method == "POST":
        cid = int(f.get("class_id", 0) or 0)
        kl = class_or_403(cid)
        if f.get("title", "").strip():
            a = Announcement(title=f["title"].strip()[:200], text=f.get("text", "")[:4000], class_id=cid, author_id=g.user.id)
            db.session.add(a)
            notify([u for s in kl.students for u in family_users(s)], "announcement", f"Maktabda yangi e’lon: {a.title}",
                   f"Новое объявление: {a.title}", "/cabinet/school")
            db.session.commit()
            audit("announcement", f"{kl.name}: {a.title}")
            flash(L("E’lon yuborildi.", "Объявление отправлено."), "ok")
        return redirect(url_for("teacher.announce"))
    cls = my_classes()
    items = Announcement.query.filter(Announcement.author_id == g.user.id).order_by(Announcement.created.desc()).limit(50).all()
    return render_template("teacher/announce.html", classes=cls, items=items)


@bp.route("/schedule")
@roles("teacher")
def schedule():
    ls = Lesson.query.filter_by(teacher_id=g.user.id).order_by(Lesson.weekday, Lesson.number).all()
    return render_template("teacher/schedule.html", lessons=ls)
