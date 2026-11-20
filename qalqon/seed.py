"""Демо-данные (все записи помечены is_demo=True) и CLI-команды."""
import random
from datetime import timedelta, date
import click
from .models import *
from .core import today, gen_password
from .core import *

DEMO_PASSWORD = "Demo2026pass"

SUBJECTS = [("Matematika", "Математика"), ("Ona tili", "Родной язык"), ("Ingliz tili", "Английский язык"), ("Fizika", "Физика"),
            ("Tarix", "История"), ("Jismoniy tarbiya", "Физическая подготовка"), ("Saf tayyorgarligi", "Строевая подготовка")]
NAMES = [("Aliyev Jasur", "2014-03-12"), ("Karimov Sardor", "2014-07-02"), ("Rahimov Bekzod", "2013-11-23"), ("Tursunov Azizbek", "2014-01-30"),
         ("Yusupov Doston", "2012-05-17"), ("Ergashev Otabek", "2012-09-08"), ("Nazarov Timur", "2012-12-14"), ("Saidov Umid", "2011-04-04"),
         ("Qodirov Shohrux", "2011-08-21"), ("Mirzayev Abbos", "2011-10-10"), ("Xolmatov Ilyos", "2014-06-06"), ("Sobirov Jahongir", "2012-02-19")]


def demo_user(role, username, name, phone="+998 90 000 00 00"):
    u = User(username=username, role=role, full_name=name, phone=phone, is_demo=True)
    u.set_password(DEMO_PASSWORD)
    db.session.add(u)
    db.session.flush()
    return u


def load_demo():
    rnd = random.Random(7)
    subs = []
    for uz, ru in SUBJECTS:
        s = Subject(name=uz, name_ru=ru, is_demo=True)
        db.session.add(s)
        subs.append(s)
    t1 = demo_user("teacher", "demo_teacher", "Demo O‘qituvchi (Matematika/Fizika)")
    t2 = demo_user("teacher", "demo_teacher2", "Demo O‘qituvchi (Tarix/Saf)")
    t3 = demo_user("teacher", "demo_teacher3", "Demo O‘qituvchi (Tillar)")
    db.session.flush()
    classes = []
    for nm_, tr in (("5-A", t1), ("6-A", t3), ("7-A", t2)):
        c = SchoolClass(name=nm_, teacher_id=tr.id, is_demo=True)
        db.session.add(c)
        classes.append(c)
    db.session.flush()
    # учитель ↔ класс ↔ предмет
    amap = {t1.id: (0, 3), t2.id: (4, 6), t3.id: (1, 2)}
    for c in classes:
        for tr, idxs in ((t1, (0, 3)), (t2, (4, 5, 6)), (t3, (1, 2))):
            for i in idxs:
                db.session.add(Assignment(teacher_id=tr.id, class_id=c.id, subject_id=subs[i].id))
    # ученики (по 4 в каждом классе)
    studs = []
    for i, (n, bd) in enumerate(NAMES):
        st = Student(full_name=n, birth_date=date.fromisoformat(bd), class_id=classes[i // 4].id, is_demo=True)
        db.session.add(st)
        studs.append(st)
    db.session.flush()
    p1 = demo_user("parent", "demo_parent", "Demo Ota-ona (2 farzand)")
    p2 = demo_user("parent", "demo_parent2", "Demo Ota-ona 2")
    s_user = demo_user("student", "demo_student", studs[0].full_name)
    studs[0].user_id = s_user.id
    studs[0].parents = [p1]
    studs[8].parents = [p1]
    studs[1].parents = [p2]
    for i in range(2, 12):
        if i not in (8,):
            p = demo_user("parent", f"demo_p{i}", f"Demo Ota-ona {i}")
            studs[i].parents = [p]
    db.session.flush()
    # расписание
    for c in classes:
        for wd in range(5):
            order = list(range(7))
            rnd.shuffle(order)
            for n in range(4):
                s_ = subs[order[n]]
                tr = next(t for t, ix in ((t1, (0, 3)), (t2, (4, 5, 6)), (t3, (1, 2))) if order[n] in ix)
                h = 8 + n
                db.session.add(Lesson(class_id=c.id, subject_id=s_.id, teacher_id=tr.id, weekday=wd, number=n + 1,
                                      start=f"{h:02d}:30", end=f"{h + 1:02d}:15", room=str(100 + n + c.id), is_demo=True))
    # посещаемость и оценки за ~90 дней
    d = today() - timedelta(days=90)
    teacher_for = {i: tr for tr, ix in ((t1, (0, 3)), (t2, (4, 5, 6)), (t3, (1, 2))) for i in ix}
    strength = {st.id: rnd.choice([3.4, 3.9, 4.3, 4.7]) for st in studs}
    while d <= today():
        if d.weekday() < 5:
            for st in studs:
                r = rnd.random()
                status = "present" if r < .88 else "late" if r < .93 else "excused" if r < .96 else "absent"
                db.session.add(Attendance(student_id=st.id, day=d, status=status, is_demo=True,
                                          reason="Kasallik / Болезнь" if status == "excused" else ""))
                if rnd.random() < .30:
                    si = rnd.randrange(7)
                    sc = max(2, min(5, round(rnd.gauss(strength[st.id], .8))))
                    db.session.add(Grade(student_id=st.id, subject_id=subs[si].id, teacher_id=teacher_for[si].id, score=sc, day=d,
                                         kind=rnd.choice(["lesson", "lesson", "test"]), is_demo=True,
                                         comment=rnd.choice(["", "", "Faol qatnashdi", "Yaxshi ish", "Takrorlash kerak"])))
        d += timedelta(days=1)
    # домашние задания
    for c in classes:
        for i, (title, si, off) in enumerate((("1–3 masalalar / Задачи 1–3", 0, 3), ("Insho / Сочинение", 1, 5), ("Strelba tarixi / История", 4, -2))):
            h = Homework(class_id=c.id, subject_id=subs[si].id, teacher_id=teacher_for[si].id, title=title,
                         text="Darslikdan bajaring. / Выполните по учебнику.", assigned=today() - timedelta(days=3),
                         due=today() + timedelta(days=off), is_demo=True)
            db.session.add(h)
            db.session.flush()
            if off < 0:
                for st in c.students[:3]:
                    db.session.add(Submission(hw_id=h.id, student_id=st.id, text="Bajarildi", checked=(st.id % 2 == 0),
                                              score=5 if st.id % 2 == 0 else None, is_demo=True))
    db.session.add(Announcement(title="[DEMO] Ota-onalar yig‘ilishi / Родительское собрание", text="Juma kuni soat 17:00 da.", is_demo=True, author_id=1))
    db.session.add(Announcement(title="[DEMO] 5-A sinf: sport musobaqasi", text="Chorshanba kuni.", class_id=classes[0].id, is_demo=True, author_id=t1.id))
    for st, cat, ti in ((studs[0], "sport", "Viloyat kross musobaqasi — 2-o‘rin / Областной кросс — 2 место"),
                        (studs[0], "study", "Matematika olimpiadasi / Олимпиада по математике"),
                        (studs[8], "award", "Oy o‘quvchisi / Ученик месяца")):
        db.session.add(Achievement(student_id=st.id, category=cat, title=ti, day=today() - timedelta(days=10), is_demo=True))
    db.session.add(Remark(student_id=studs[0].id, teacher_id=t2.id, kind="praise", text="Saf mashqlarida namunali intizom.", day=today() - timedelta(days=2), is_demo=True))
    db.session.add(Remark(student_id=studs[1].id, teacher_id=t2.id, kind="remark", text="Darsga kechikish.", day=today() - timedelta(days=4), is_demo=True))
    # контент
    db.session.add(News(title="[DEMO] Yangi o‘quv yili boshlandi", title_ru="[DEMO] Начался новый учебный год",
                        body="Bu demo yangilik. Haqiqiy yangiliklarni admin panelda qo‘shing.",
                        body_ru="Это демо-новость. Добавьте реальные новости в админ-панели.", category="news", is_demo=True))
    db.session.add(News(title="[DEMO] Sport musobaqasi g‘oliblari", title_ru="[DEMO] Победители спортивных соревнований",
                        body="Demo matn.", body_ru="Демо-текст.", category="achievement", is_demo=True))
    for i, (n, p, pr, sp) in enumerate((("Demo Direktor", "Maktab direktori", "Директор школы", "Boshqaruv"),
                                        ("Demo O‘quv ishlari bo‘yicha o‘rinbosar", "O‘rinbosar", "Заместитель директора", "Ta’lim"),
                                        ("Demo Harbiy tayyorgarlik ustozi", "Tarbiyachi-ofitser", "Офицер-воспитатель", "Saf va intizom"))):
        db.session.add(Staff(full_name=n, position=p, position_ru=pr, specialty=sp, bio="Demo ma’lumot — admin paneldan almashtiring.",
                             bio_ru="Демо-данные — замените в админ-панели.", sort=i, is_demo=True))
    for i, (st, cn) in enumerate((("new", "Demo Ariza Bola"), ("review", "Demo Review Bola"), ("interview", "Demo Intervyu Bola"), ("accepted", "Demo Qabul Bola"))):
        a = Application(number=f"DEMO-{i + 1:03d}", child_name=cn, birth_date=date(2014, 5, 1), parent_name="Demo Ota-ona", phone="+998 90 111 22 3%d" % i,
                        address="Toshkent", grade="5", status=st, is_demo=True, created=datetime.utcnow() - timedelta(days=i * 20))
        db.session.add(a)
    db.session.commit()
    # уведомление-пример
    notify(p1, "info", "Maktabda yangi e’lon: Ota-onalar yig‘ilishi", "Новое объявление: Родительское собрание", "/cabinet/school", demo=True)
    db.session.commit()


def purge_demo():
    sid = [s.id for s in Student.query.filter_by(is_demo=True)]
    uid = [u.id for u in User.query.filter_by(is_demo=True)]
    cid = [c.id for c in SchoolClass.query.filter_by(is_demo=True)]
    hw = [h.id for h in Homework.query.filter(db.or_(Homework.is_demo == True, Homework.class_id.in_(cid or [0])))]  # noqa
    subm = [s.id for s in Submission.query.filter(db.or_(Submission.is_demo == True, Submission.hw_id.in_(hw or [0])))]  # noqa
    mats = [m.id for m in Material.query.filter(db.or_(Material.is_demo == True, Material.class_id.in_(cid or [0])))]  # noqa
    apps = [a.id for a in Application.query.filter_by(is_demo=True)]
    S = db.session
    S.query(File).filter(File.owner_type == "sub", File.owner_id.in_(subm or [0])).delete(False)
    S.query(File).filter(File.owner_type == "hw", File.owner_id.in_(hw or [0])).delete(False)
    S.query(File).filter(File.owner_type == "mat", File.owner_id.in_(mats or [0])).delete(False)
    S.query(File).filter(File.owner_type == "app", File.owner_id.in_(apps or [0])).delete(False)
    S.query(Submission).filter(Submission.id.in_(subm or [0])).delete(False)
    S.query(Homework).filter(Homework.id.in_(hw or [0])).delete(False)
    S.query(Material).filter(Material.id.in_(mats or [0])).delete(False)
    for M in (Grade, Attendance, Remark, Achievement):
        S.query(M).filter(db.or_(M.student_id.in_(sid or [0]), M.is_demo == True)).delete(False)  # noqa
    S.query(Lesson).filter(db.or_(Lesson.is_demo == True, Lesson.class_id.in_(cid or [0]))).delete(False)  # noqa
    S.query(Announcement).filter(db.or_(Announcement.is_demo == True, Announcement.class_id.in_(cid or [0]))).delete(False)  # noqa
    S.query(Message).filter(db.or_(Message.is_demo == True, Message.sender_id.in_(uid or [0]), Message.rcpt_id.in_(uid or [0]))).delete(False)  # noqa
    S.query(Notification).filter(db.or_(Notification.is_demo == True, Notification.user_id.in_(uid or [0]))).delete(False)  # noqa
    S.query(Assignment).filter(db.or_(Assignment.teacher_id.in_(uid or [0]), Assignment.class_id.in_(cid or [0]))).delete(False)
    S.execute(parent_child.delete().where(db.or_(parent_child.c.student_id.in_(sid or [0]), parent_child.c.parent_id.in_(uid or [0]))))
    S.query(Student).filter(Student.id.in_(sid or [0])).delete(False)
    S.query(Application).filter(Application.id.in_(apps or [0])).delete(False)
    S.query(News).filter_by(is_demo=True).delete(False)
    S.query(Staff).filter_by(is_demo=True).delete(False)
    S.query(GalleryItem).filter_by(is_demo=True).delete(False)
    S.query(SchoolClass).filter(SchoolClass.id.in_(cid or [0])).delete(False)
    S.query(Subject).filter_by(is_demo=True).delete(False)
    S.query(PasswordReset).filter(PasswordReset.user_id.in_(uid or [0])).delete(False)
    S.query(User).filter(User.id.in_(uid or [0])).delete(False)
    S.commit()


def register_cli(app):
    @app.cli.command("seed-demo")
    def seed_demo():
        """Загрузить демо-данные."""
        load_demo()
        click.echo(f"Демо загружено. Пароль демо-аккаунтов: {DEMO_PASSWORD}")

    @app.cli.command("purge-demo")
    def purge_demo_cmd():
        """Удалить все демо-данные."""
        purge_demo()
        click.echo("Демо-данные удалены.")
