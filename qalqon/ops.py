"""Общие операции (используются админом и учителем) и Excel-экспорт."""
from io import BytesIO
from datetime import date, timedelta
from flask import Response
from .models import *
from .core import *


def set_attendance(st, day, status, reason="", by=None):
    if status not in ATT_NAMES:
        return False
    a = Attendance.query.filter_by(student_id=st.id, day=day).first()
    changed = (not a) or a.status != status
    if not a:
        a = Attendance(student_id=st.id, day=day, status=status)
        db.session.add(a)
    a.status, a.reason, a.marked_by, a.is_demo = status, reason[:200], by.id if by else None, st.is_demo
    if changed and status in ("absent", "late") and day == today():
        if status == "absent":
            uz, ru = f"Farzandingiz bugun darsga kelmadi: {st.full_name}", f"Ваш ребёнок сегодня не пришёл на занятия: {st.full_name}"
        else:
            uz, ru = f"Farzandingiz bugun kechikdi: {st.full_name}", f"Ваш ребёнок сегодня опоздал: {st.full_name}"
        notify(st.parents, "attendance", uz, ru, "/cabinet/attendance?c=%d" % st.id, demo=st.is_demo)
    return True


def add_grade(st, subject, teacher, score, comment, day, kind="lesson"):
    g_ = Grade(student_id=st.id, subject_id=subject.id, teacher_id=teacher.id if teacher else None, score=score,
               comment=comment[:300], day=day, kind=kind, is_demo=st.is_demo)
    db.session.add(g_)
    notify(family_users(st), "grade", f"Yangi baho qo‘yildi: {st.full_name} — {subject.name}: {score}",
           f"Новая оценка: {st.full_name} — {subject.name_ru or subject.name}: {score}",
           "/cabinet/diary?c=%d" % st.id, demo=st.is_demo)
    return g_


def parse_day(s, default=None):
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        return default or today()


def xlsx_response(name, headers, rows, title="Qalqon"):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    wb = Workbook()
    ws = wb.active
    ws.title = title[:30]
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="2B2B2B")
        c.alignment = Alignment(vertical="center", wrap_text=True)
    for r in rows:
        ws.append([("'" + v if isinstance(v, str) and v[:1] in "=+-@" else v) for v in r])
    for i, h in enumerate(headers, 1):
        w = max([len(str(h))] + [len(str(r[i - 1])) for r in rows[:200] if i - 1 < len(r)])
        ws.column_dimensions[ws.cell(1, i).column_letter].width = min(max(w + 2, 10), 50)
    ws.freeze_panes = "A2"
    buf = BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})


def class_report(klass, kind, subject_ids=None):
    """Сводка по классу: по ученикам — средний балл по предметам, общий, посещаемость."""
    s, e = period_range(kind)
    subs = Subject.query.order_by(Subject.name).all()
    if subject_ids is not None:
        subs = [x for x in subs if x.id in subject_ids]
    rows = []
    for st in klass.students:
        per = {}
        for sub in subs:
            per[sub.id] = student_avg(st.id, s, e, sub.id)
        rows.append({"st": st, "per": per, "avg": student_avg(st.id, s, e) if subject_ids is None else avg(list(per.values())),
                     "att": att_counts(st.id, s, e)})
    return {"klass": klass, "subjects": subs, "rows": rows, "start": s, "end": e, "kind": kind}


def class_report_xlsx(rep, name):
    hdr = ["O‘quvchi / Ученик"] + [subj_name(x) for x in rep["subjects"]] + ["O‘rtacha / Средний", "Davomat % / Посещ. %"]
    rows = [[r["st"].full_name] + [r["per"][x.id] for x in rep["subjects"]] + [r["avg"], r["att"]["rate"]] for r in rep["rows"]]
    return xlsx_response(name, hdr, rows, rep["klass"].name)


# ───────── оплаты ─────────
METHODS = {"cash": ("Naqd", "Наличные"), "card": ("Karta", "Карта"), "transfer": ("O‘tkazma", "Перевод")}


def months_elapsed(ref=None):
    """Сколько учебных месяцев (сентябрь–май) прошло к дате, включая текущий."""
    ref = ref or today()
    if ref.month >= 9:
        return ref.month - 8
    return 9 if ref.month >= 6 else ref.month + 4


def money(n):
    return f"{int(n or 0):,}".replace(",", " ")


def student_balance(st):
    t = Tuition.query.filter_by(student_id=st.id).first()
    fee = t.monthly_fee if t else 0
    paid = db.session.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
        Payment.student_id == st.id, Payment.day >= school_year_start()).scalar()
    due = fee * months_elapsed()
    return {"fee": fee, "due": due, "paid": int(paid), "debt": max(due - int(paid), 0), "credit": max(int(paid) - due, 0)}


# ───────── сетка «ученики × дни» ─────────
def grid_data(kl, subject_id, start, end):
    days = []
    d = start
    while d <= end:
        if d.weekday() < 6:
            days.append(d)
        d += timedelta(days=1)
    sids = [s.id for s in kl.students]
    grades = {}
    q = Grade.query.filter(Grade.student_id.in_(sids or [0]), Grade.day >= start, Grade.day <= end)
    if subject_id:
        q = q.filter(Grade.subject_id == subject_id)
    for g_ in q.order_by(Grade.id):
        grades.setdefault((g_.student_id, g_.day), []).append(g_.score)
    att = {(a.student_id, a.day): a.status for a in Attendance.query.filter(
        Attendance.student_id.in_(sids or [0]), Attendance.day >= start, Attendance.day <= end)}
    return {"days": days, "grades": grades, "att": att}
