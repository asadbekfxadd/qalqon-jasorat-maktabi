"""Кабинеты родителя и ученика (один модуль, права разделены по роли)."""
from collections import defaultdict
from datetime import timedelta, datetime
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort, session
from .models import *
from .core import *
from .ops import *

bp = Blueprint("cabinet", __name__, url_prefix="/cabinet")


def child_view(f):
    """Определяет текущего ребёнка. Родитель видит только своих детей, ученик — только себя."""
    @wraps(f)
    @roles("parent", "student")
    def w(*a, **k):
        kids = my_students(g.user)
        if not kids:
            return render_template("cab/empty.html")
        want = request.args.get("c", type=int) or session.get("child")
        st = next((s for s in kids if s.id == want), kids[0])
        session["child"] = st.id
        g.st, g.kids = st, kids
        return f(*a, **k)
    return w


def render(tpl, **kw):
    return render_template(tpl, st=g.st, kids=g.kids, **kw)


@bp.route("/")
@child_view
def home():
    st, t = g.st, today()
    last = Grade.query.filter_by(student_id=st.id).order_by(Grade.day.desc(), Grade.id.desc()).limit(6).all()
    hw = []
    if st.class_id:
        hw = Homework.query.filter(Homework.class_id == st.class_id, Homework.due >= t).order_by(Homework.due).limit(4).all()
    anns = Announcement.query.filter(db.or_(Announcement.class_id == None, Announcement.class_id == st.class_id))\
        .order_by(Announcement.created.desc()).limit(3).all()  # noqa
    lessons = Lesson.query.filter_by(class_id=st.class_id, weekday=t.weekday()).order_by(Lesson.number).all() if st.class_id else []
    return render("cab/home.html", last=last, hw=hw, anns=anns, lessons=lessons, avg=student_avg(st.id, school_year_start()),
                  att=att_counts(st.id, school_year_start()), week=att_counts(st.id, t - timedelta(days=t.weekday())),
                  remarks=Remark.query.filter_by(student_id=st.id).order_by(Remark.day.desc()).limit(3).all(),
                  hws=lambda h: hw_status(h, st)[0])


@bp.route("/diary")
@child_view
def diary():
    st = g.st
    kind = request.args.get("p", "year")
    kind = kind if kind in PERIODS else "year"
    s, e = period_range(kind)
    grades = Grade.query.filter(Grade.student_id == st.id, Grade.day >= s, Grade.day <= e).order_by(Grade.day.desc(), Grade.id.desc()).all()
    by = defaultdict(list)
    for gr in grades:
        by[gr.subject].append(gr)
    subs = sorted(by.items(), key=lambda kv: subj_name(kv[0]))
    return render("cab/diary.html", subs=subs, avg=student_avg(st.id, s, e), kind=kind, s=s, e=e,
                  remarks=Remark.query.filter(Remark.student_id == st.id, Remark.day >= s, Remark.day <= e).order_by(Remark.day.desc()).all())


@bp.route("/attendance")
@child_view
def attendance():
    st = g.st
    kind = request.args.get("p", "year")
    kind = kind if kind in PERIODS else "year"
    s, e = period_range(kind)
    items = Attendance.query.filter(Attendance.student_id == st.id, Attendance.day >= s, Attendance.day <= e)\
        .order_by(Attendance.day.desc()).all()
    return render("cab/attendance.html", items=items, cnt=att_counts(st.id, s, e), kind=kind, s=s, e=e)


@bp.route("/homework")
@child_view
def homework():
    st = g.st
    items = Homework.query.filter_by(class_id=st.class_id).order_by(Homework.due.desc()).limit(60).all() if st.class_id else []
    rows = [(h,) + hw_status(h, st) for h in items]
    return render("cab/homework.html", rows=rows)


@bp.route("/homework/<int:hid>", methods=["GET", "POST"])
@child_view
def homework_one(hid):
    st = g.st
    h = db.get_or_404(Homework, hid)
    if h.class_id != st.class_id:
        abort(403)
    status, sub = hw_status(h, st)
    if request.method == "POST":
        if g.user.role != "student":
            abort(403)  # сдавать работу может только ученик
        if sub and sub.checked:
            flash(L("Ish allaqachon tekshirilgan.", "Работа уже проверена."), "warn")
        else:
            if not sub:
                sub = Submission(hw_id=h.id, student_id=st.id, is_demo=st.is_demo)
                db.session.add(sub)
                db.session.flush()
            sub.text = request.form.get("text", "")[:5000]
            sub.created = datetime.utcnow()
            for fs in request.files.getlist("files")[:3]:
                save_upload(fs, "sub", sub.id)
            if h.teacher:
                notify(h.teacher, "homework", f"Uy vazifasi topshirildi: {st.full_name} — {h.title}",
                       f"Сдано домашнее задание: {st.full_name} — {h.title}", f"/teacher/homework/{h.id}", demo=st.is_demo)
            db.session.commit()
            audit("homework_submit", f"{h.title}")
            flash(L("Ish topshirildi.", "Работа сдана."), "ok")
        return redirect(url_for("cabinet.homework_one", hid=hid))
    return render("cab/homework_one.html", h=h, status=status, sub=sub)


@bp.route("/schedule")
@child_view
def schedule():
    st = g.st
    ls = Lesson.query.filter_by(class_id=st.class_id).order_by(Lesson.weekday, Lesson.number).all() if st.class_id else []
    by = defaultdict(list)
    for l in ls:
        by[l.weekday].append(l)
    return render("cab/schedule.html", by=by)


@bp.route("/achievements")
@child_view
def achievements():
    st = g.st
    items = Achievement.query.filter_by(student_id=st.id).order_by(Achievement.day.desc()).all()
    return render("cab/achievements.html", items=items)


@bp.route("/school")
@child_view
def school():
    st = g.st
    anns = Announcement.query.filter(db.or_(Announcement.class_id == None, Announcement.class_id == st.class_id))\
        .order_by(Announcement.created.desc()).limit(40).all()  # noqa
    return render("cab/school.html", anns=anns)


@bp.route("/materials")
@child_view
def materials():
    st = g.st
    items = Material.query.filter_by(class_id=st.class_id).order_by(Material.created.desc()).all() if st.class_id else []
    return render("cab/materials.html", items=items)


@bp.route("/progress")
@child_view
def progress():
    st = g.st
    gr = Grade.query.filter(Grade.student_id == st.id, Grade.day >= school_year_start()).order_by(Grade.day).all()
    bym = defaultdict(list)
    for x in gr:
        bym[f"{x.day.year}-{x.day.month:02d}"].append(x.score)
    keys = sorted(bym)
    per = [(subj_name(s_), round(float(a), 2)) for s_, a in
           db.session.query(Subject, func.avg(Grade.score)).join(Grade, Grade.subject_id == Subject.id)
           .filter(Grade.student_id == st.id, Grade.day >= school_year_start()).group_by(Subject.id).order_by(Subject.name)]
    klass_avg = None
    if st.class_id:
        v = db.session.query(func.avg(Grade.score)).join(Student, Student.id == Grade.student_id)\
            .filter(Student.class_id == st.class_id, Grade.day >= school_year_start()).scalar()
        klass_avg = round(float(v), 2) if v is not None else None
    chart = {"labels": [MONTHS[int(k[5:]) - 1][1 if lang() == "ru" else 0][:3].capitalize() for k in keys],
             "data": [avg(bym[k]) for k in keys], "subj": per}
    return render("cab/progress.html", chart=chart, avg=student_avg(st.id, school_year_start()), klass_avg=klass_avg,
                  att=att_counts(st.id, school_year_start()))


@bp.route("/report")
@child_view
def report():
    kind = request.args.get("p", "month")
    kind = kind if kind in PERIODS else "month"
    return render("cab/report.html", r=student_report(g.st, kind), kind=kind)
