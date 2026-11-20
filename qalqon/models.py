"""Модели БД. Все таблицы с префиксом q_ (старые таблицы прототипа не затрагиваются)."""
from datetime import datetime, date
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import declared_attr
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class Base(db.Model):
    __abstract__ = True

    @declared_attr.directive
    def __tablename__(cls):
        return "q_" + cls.__name__.lower()


ROLES = ("admin", "teacher", "parent", "student")

parent_child = db.Table(
    "q_parent_child",
    db.Column("parent_id", db.Integer, db.ForeignKey("q_user.id", ondelete="CASCADE"), primary_key=True),
    db.Column("student_id", db.Integer, db.ForeignKey("q_student.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(60), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(10), nullable=False, index=True)
    full_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(30), default="")
    email = db.Column(db.String(120), default="")
    telegram_chat_id = db.Column(db.String(40), default="")
    active = db.Column(db.Boolean, default=True)
    must_change = db.Column(db.Boolean, default=False)
    is_demo = db.Column(db.Boolean, default=False, index=True)
    created = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    children = db.relationship("Student", secondary=parent_child, back_populates="parents")

    def set_password(self, p):
        self.password_hash = generate_password_hash(p)

    def check(self, p):
        return check_password_hash(self.password_hash, p)


class Subject(Base):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    name_ru = db.Column(db.String(80), default="")
    is_demo = db.Column(db.Boolean, default=False, index=True)


class SchoolClass(Base):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(20), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey("q_user.id", ondelete="SET NULL"))
    is_demo = db.Column(db.Boolean, default=False, index=True)
    teacher = db.relationship("User")
    students = db.relationship("Student", back_populates="klass", order_by="Student.full_name")


class Assignment(Base):
    """Учитель ↔ класс ↔ предмет (определяет доступ учителя)."""
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("q_user.id", ondelete="CASCADE"), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey("q_schoolclass.id", ondelete="CASCADE"), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey("q_subject.id", ondelete="CASCADE"), nullable=False)
    teacher = db.relationship("User")
    klass = db.relationship("SchoolClass")
    subject = db.relationship("Subject")
    __table_args__ = (db.UniqueConstraint("class_id", "subject_id", "teacher_id"),)


class Student(Base):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    birth_date = db.Column(db.Date)
    class_id = db.Column(db.Integer, db.ForeignKey("q_schoolclass.id", ondelete="SET NULL"), index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("q_user.id", ondelete="SET NULL"))
    photo_id = db.Column(db.Integer, db.ForeignKey("q_file.id", ondelete="SET NULL"))
    application_no = db.Column(db.String(20), default="")
    active = db.Column(db.Boolean, default=True)
    is_demo = db.Column(db.Boolean, default=False, index=True)
    created = db.Column(db.DateTime, default=datetime.utcnow)
    klass = db.relationship("SchoolClass", back_populates="students")
    account = db.relationship("User", foreign_keys=[user_id])
    parents = db.relationship("User", secondary=parent_child, back_populates="children")


class Lesson(Base):
    id = db.Column(db.Integer, primary_key=True)
    class_id = db.Column(db.Integer, db.ForeignKey("q_schoolclass.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("q_subject.id", ondelete="CASCADE"), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey("q_user.id", ondelete="SET NULL"))
    weekday = db.Column(db.Integer, nullable=False)  # 0=Mon
    number = db.Column(db.Integer, default=1)
    start = db.Column(db.String(5), default="08:30")
    end = db.Column(db.String(5), default="09:15")
    room = db.Column(db.String(20), default="")
    is_demo = db.Column(db.Boolean, default=False, index=True)
    klass = db.relationship("SchoolClass")
    subject = db.relationship("Subject")
    teacher = db.relationship("User")


class Attendance(Base):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("q_student.id", ondelete="CASCADE"), nullable=False, index=True)
    day = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(10), nullable=False)  # present|late|absent|excused
    reason = db.Column(db.String(200), default="")
    marked_by = db.Column(db.Integer, db.ForeignKey("q_user.id", ondelete="SET NULL"))
    is_demo = db.Column(db.Boolean, default=False, index=True)
    student = db.relationship("Student")
    __table_args__ = (db.UniqueConstraint("student_id", "day"),)


class Grade(Base):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("q_student.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("q_subject.id", ondelete="CASCADE"), nullable=False, index=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("q_user.id", ondelete="SET NULL"))
    score = db.Column(db.Integer, nullable=False)  # 1..5
    kind = db.Column(db.String(12), default="lesson")  # lesson|test|homework|quarter
    comment = db.Column(db.String(300), default="")
    day = db.Column(db.Date, nullable=False, index=True)
    is_demo = db.Column(db.Boolean, default=False, index=True)
    student = db.relationship("Student")
    subject = db.relationship("Subject")
    teacher = db.relationship("User")


class Remark(Base):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("q_student.id", ondelete="CASCADE"), nullable=False, index=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("q_user.id", ondelete="SET NULL"))
    kind = db.Column(db.String(8), default="praise")  # praise|remark
    text = db.Column(db.String(400), nullable=False)
    day = db.Column(db.Date, default=date.today)
    is_demo = db.Column(db.Boolean, default=False, index=True)
    student = db.relationship("Student")
    teacher = db.relationship("User")


class Achievement(Base):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("q_student.id", ondelete="CASCADE"), nullable=False, index=True)
    category = db.Column(db.String(10), default="sport")  # sport|event|award|study
    title = db.Column(db.String(200), nullable=False)
    day = db.Column(db.Date, default=date.today)
    is_demo = db.Column(db.Boolean, default=False, index=True)
    student = db.relationship("Student")


class Homework(Base):
    id = db.Column(db.Integer, primary_key=True)
    class_id = db.Column(db.Integer, db.ForeignKey("q_schoolclass.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("q_subject.id", ondelete="CASCADE"), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey("q_user.id", ondelete="SET NULL"))
    title = db.Column(db.String(200), nullable=False)
    text = db.Column(db.Text, default="")
    assigned = db.Column(db.Date, default=date.today)
    due = db.Column(db.Date, nullable=False)
    is_demo = db.Column(db.Boolean, default=False, index=True)
    klass = db.relationship("SchoolClass")
    subject = db.relationship("Subject")
    teacher = db.relationship("User")
    files = db.relationship("File", primaryjoin="and_(File.owner_type=='hw', foreign(File.owner_id)==Homework.id)",
                            viewonly=True)
    subs = db.relationship("Submission", cascade="all, delete-orphan", back_populates="hw")


class Submission(Base):
    id = db.Column(db.Integer, primary_key=True)
    hw_id = db.Column(db.Integer, db.ForeignKey("q_homework.id", ondelete="CASCADE"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("q_student.id", ondelete="CASCADE"), nullable=False)
    text = db.Column(db.Text, default="")
    created = db.Column(db.DateTime, default=datetime.utcnow)
    score = db.Column(db.Integer)
    feedback = db.Column(db.String(300), default="")
    checked = db.Column(db.Boolean, default=False)
    is_demo = db.Column(db.Boolean, default=False, index=True)
    hw = db.relationship("Homework", back_populates="subs")
    student = db.relationship("Student")
    files = db.relationship("File", primaryjoin="and_(File.owner_type=='sub', foreign(File.owner_id)==Submission.id)",
                            viewonly=True)
    __table_args__ = (db.UniqueConstraint("hw_id", "student_id"),)


class Material(Base):
    id = db.Column(db.Integer, primary_key=True)
    class_id = db.Column(db.Integer, db.ForeignKey("q_schoolclass.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("q_subject.id", ondelete="CASCADE"), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey("q_user.id", ondelete="SET NULL"))
    title = db.Column(db.String(200), nullable=False)
    text = db.Column(db.Text, default="")
    link = db.Column(db.String(300), default="")
    created = db.Column(db.DateTime, default=datetime.utcnow)
    is_demo = db.Column(db.Boolean, default=False, index=True)
    klass = db.relationship("SchoolClass")
    subject = db.relationship("Subject")
    files = db.relationship("File", primaryjoin="and_(File.owner_type=='mat', foreign(File.owner_id)==Material.id)",
                            viewonly=True)


class Announcement(Base):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    text = db.Column(db.Text, default="")
    class_id = db.Column(db.Integer, db.ForeignKey("q_schoolclass.id", ondelete="CASCADE"))  # NULL = вся школа
    author_id = db.Column(db.Integer, db.ForeignKey("q_user.id", ondelete="SET NULL"))
    created = db.Column(db.DateTime, default=datetime.utcnow)
    is_demo = db.Column(db.Boolean, default=False, index=True)
    klass = db.relationship("SchoolClass")
    author = db.relationship("User")


class Message(Base):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("q_user.id", ondelete="CASCADE"), nullable=False)
    rcpt_id = db.Column(db.Integer, db.ForeignKey("q_user.id", ondelete="CASCADE"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("q_student.id", ondelete="SET NULL"))
    subject = db.Column(db.String(200), default="")
    body = db.Column(db.Text, nullable=False)
    created = db.Column(db.DateTime, default=datetime.utcnow)
    read = db.Column(db.Boolean, default=False)
    is_demo = db.Column(db.Boolean, default=False, index=True)
    sender = db.relationship("User", foreign_keys=[sender_id])
    rcpt = db.relationship("User", foreign_keys=[rcpt_id])
    student = db.relationship("Student")


class Notification(Base):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("q_user.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = db.Column(db.String(20), default="info")
    text_uz = db.Column(db.String(400), nullable=False)
    text_ru = db.Column(db.String(400), default="")
    link = db.Column(db.String(200), default="")
    read = db.Column(db.Boolean, default=False, index=True)
    created = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    is_demo = db.Column(db.Boolean, default=False)


class Application(Base):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(20), unique=True, nullable=False, index=True)
    child_name = db.Column(db.String(120), nullable=False)
    birth_date = db.Column(db.Date, nullable=False)
    parent_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    email = db.Column(db.String(120), default="")
    address = db.Column(db.String(250), default="")
    prev_school = db.Column(db.String(160), default="")
    grade = db.Column(db.String(20), default="")
    extra = db.Column(db.Text, default="")
    status = db.Column(db.String(12), default="new", index=True)
    note = db.Column(db.Text, default="")  # внутренняя заметка администратора
    created = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated = db.Column(db.DateTime, default=datetime.utcnow)
    is_demo = db.Column(db.Boolean, default=False, index=True)
    files = db.relationship("File", primaryjoin="and_(File.owner_type=='app', foreign(File.owner_id)==Application.id)",
                            viewonly=True)


STATUSES = ("new", "review", "interview", "docs", "accepted", "rejected")


class News(Base):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    title_ru = db.Column(db.String(200), default="")
    body = db.Column(db.Text, default="")
    body_ru = db.Column(db.Text, default="")
    category = db.Column(db.String(12), default="news")  # news|event|achievement
    day = db.Column(db.Date, default=date.today)
    image_id = db.Column(db.Integer, db.ForeignKey("q_file.id", ondelete="SET NULL"))
    video_url = db.Column(db.String(300), default="")
    published = db.Column(db.Boolean, default=True)
    is_demo = db.Column(db.Boolean, default=False, index=True)


class Staff(Base):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    position = db.Column(db.String(160), default="")
    position_ru = db.Column(db.String(160), default="")
    specialty = db.Column(db.String(160), default="")
    specialty_ru = db.Column(db.String(160), default="")
    bio = db.Column(db.Text, default="")
    bio_ru = db.Column(db.Text, default="")
    photo_id = db.Column(db.Integer, db.ForeignKey("q_file.id", ondelete="SET NULL"))
    sort = db.Column(db.Integer, default=100)
    is_demo = db.Column(db.Boolean, default=False, index=True)


class GalleryItem(Base):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), default="")
    category = db.Column(db.String(12), default="training")  # training|drill|events|sport|study
    video_url = db.Column(db.String(300), default="")
    image_id = db.Column(db.Integer, db.ForeignKey("q_file.id", ondelete="SET NULL"))
    created = db.Column(db.DateTime, default=datetime.utcnow)
    is_demo = db.Column(db.Boolean, default=False, index=True)


class Setting(Base):
    key = db.Column(db.String(40), primary_key=True)
    value = db.Column(db.Text, default="")


class File(Base):
    """Файлы хранятся в БД (переживают деплои на Railway). Доступ — только через проверку прав."""
    id = db.Column(db.Integer, primary_key=True)
    owner_type = db.Column(db.String(10), nullable=False, index=True)  # pub|app|hw|sub|mat|photo
    owner_id = db.Column(db.Integer, index=True)
    name = db.Column(db.String(200), nullable=False)
    mime = db.Column(db.String(80), default="application/octet-stream")
    size = db.Column(db.Integer, default=0)
    data = db.deferred(db.Column(db.LargeBinary, nullable=False))
    uploader_id = db.Column(db.Integer)
    created = db.Column(db.DateTime, default=datetime.utcnow)


class AuditLog(Base):
    id = db.Column(db.Integer, primary_key=True)
    created = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    user_id = db.Column(db.Integer)
    username = db.Column(db.String(60), default="")
    action = db.Column(db.String(40), nullable=False)
    detail = db.Column(db.String(400), default="")
    ip = db.Column(db.String(45), default="")


class PasswordReset(Base):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("q_user.id", ondelete="CASCADE"), nullable=False)
    token_hash = db.Column(db.String(64), unique=True, nullable=False)
    expires = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)
    user = db.relationship("User")


class Tuition(Base):
    """Ежемесячная плата за обучение (сум) для ученика."""
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("q_student.id", ondelete="CASCADE"), unique=True, nullable=False)
    monthly_fee = db.Column(db.Integer, default=0)
    is_demo = db.Column(db.Boolean, default=False, index=True)
    student = db.relationship("Student")


class Payment(Base):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("q_student.id", ondelete="CASCADE"), nullable=False, index=True)
    amount = db.Column(db.Integer, nullable=False)
    day = db.Column(db.Date, default=date.today, index=True)
    method = db.Column(db.String(10), default="cash")  # cash|card|transfer
    note = db.Column(db.String(200), default="")
    created_by = db.Column(db.Integer)
    is_demo = db.Column(db.Boolean, default=False, index=True)
    student = db.relationship("Student")
