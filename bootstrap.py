import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent

FILES = {}

FILES["config/settings.py"] = '''
import os
from pathlib import Path
import dj_database_url
from django.contrib.messages import constants as msg

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-key")
DEBUG = os.environ.get("DEBUG", "False") == "True"

ALLOWED_HOSTS = ["localhost", "127.0.0.1", ".up.railway.app"]
ALLOWED_HOSTS += [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = ["https://*.up.railway.app"]
CSRF_TRUSTED_ORIGINS += [f"https://{h}" for h in ALLOWED_HOSTS if "." in h and not h.startswith(".")]
RAILWAY_DOMAIN = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
if RAILWAY_DOMAIN:
    ALLOWED_HOSTS.append(RAILWAY_DOMAIN)
    CSRF_TRUSTED_ORIGINS.append(f"https://{RAILWAY_DOMAIN}")
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    "jazzmin",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "import_export",
    "accounts",
    "website",
    "crm",
    "diary",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.debug",
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {"default": dj_database_url.config(
    default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}", conn_max_age=600)}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Asia/Tashkent"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/after-login/"
LOGOUT_REDIRECT_URL = "/"
MESSAGE_TAGS = {msg.ERROR: "danger"}

JAZZMIN_SETTINGS = {
    "site_title": "EduCenter CRM",
    "site_header": "EduCenter",
    "site_brand": "EduCenter",
    "welcome_sign": "Система учёта учебного центра",
    "show_sidebar": True,
    "navigation_expanded": True,
    "icons": {
        "accounts.user": "fas fa-user",
        "website.course": "fas fa-book",
        "website.teacher": "fas fa-chalkboard-teacher",
        "website.lead": "fas fa-user-plus",
        "website.news": "fas fa-newspaper",
        "crm.student": "fas fa-user-graduate",
        "crm.group": "fas fa-users",
        "crm.payment": "fas fa-money-bill-wave",
        "diary.lesson": "fas fa-calendar-day",
    },
}
'''

FILES["config/urls.py"] = '''
from django.contrib import admin
from django.urls import path, include
from accounts.views import after_login
from crm.views import dashboard

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("after-login/", after_login, name="after_login"),
    path("dashboard/", dashboard, name="dashboard"),
    path("", include("diary.urls")),
    path("", include("website.urls")),
]
'''

FILES["accounts/models.py"] = '''
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Администратор"
        MANAGER = "manager", "Менеджер"
        TEACHER = "teacher", "Преподаватель"
        PARENT = "parent", "Родитель"
        STUDENT = "student", "Студент"

    role = models.CharField("Роль", max_length=20, choices=Role.choices, default=Role.STUDENT)
    phone = models.CharField("Телефон", max_length=20, blank=True)

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"
'''

FILES["accounts/decorators.py"] = '''
from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(request, *args, **kwargs):
            u = request.user
            if u.is_superuser or u.is_staff or u.role in roles:
                return view(request, *args, **kwargs)
            raise PermissionDenied
        return wrapper
    return decorator
'''

FILES["accounts/views.py"] = '''
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


@login_required
def after_login(request):
    u = request.user
    if u.is_superuser or u.is_staff or u.role in ("admin", "manager"):
        return redirect("dashboard")
    if u.role == "teacher":
        return redirect("journal")
    return redirect("diary")
'''

FILES["accounts/admin.py"] = '''
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "first_name", "last_name", "role", "phone", "is_active")
    list_filter = ("role", "is_active", "is_staff")
    fieldsets = BaseUserAdmin.fieldsets + (("Дополнительно", {"fields": ("role", "phone")}),)
'''

FILES["website/models.py"] = '''
from django.conf import settings
from django.db import models


class Course(models.Model):
    title = models.CharField("Название", max_length=150)
    description = models.TextField("Описание", blank=True)
    monthly_price = models.DecimalField("Цена за месяц (сум)", max_digits=12, decimal_places=2)
    is_active = models.BooleanField("Показывать на сайте", default=True)

    class Meta:
        verbose_name = "Курс"
        verbose_name_plural = "Курсы"

    def __str__(self): return self.title


class Teacher(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, verbose_name="Аккаунт", null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="teacher_profile",
                                limit_choices_to={"role": "teacher"})
    full_name = models.CharField("ФИО", max_length=150)
    bio = models.TextField("О преподавателе", blank=True)
    courses = models.ManyToManyField(Course, verbose_name="Курсы", blank=True, related_name="teachers")

    class Meta:
        verbose_name = "Преподаватель"
        verbose_name_plural = "Преподаватели"

    def __str__(self): return self.full_name


class Lead(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "Новая"
        CONTACTED = "contacted", "Связались"
        ENROLLED = "enrolled", "Зачислен"
        REJECTED = "rejected", "Отказ"

    name = models.CharField("Имя", max_length=100)
    phone = models.CharField("Телефон", max_length=20)
    course = models.ForeignKey(Course, verbose_name="Курс", null=True, blank=True, on_delete=models.SET_NULL)
    comment = models.TextField("Комментарий", blank=True)
    status = models.CharField("Статус", max_length=10, choices=Status.choices, default=Status.NEW)
    created_at = models.DateTimeField("Создана", auto_now_add=True)

    class Meta:
        verbose_name = "Заявка"
        verbose_name_plural = "Заявки (новые студенты)"
        ordering = ["-created_at"]

    def __str__(self): return f"{self.name} ({self.phone})"


class News(models.Model):
    title = models.CharField("Заголовок", max_length=200)
    text = models.TextField("Текст")
    is_published = models.BooleanField("Опубликовано", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Новость"
        verbose_name_plural = "Новости"
        ordering = ["-created_at"]

    def __str__(self): return self.title
'''

FILES["website/views.py"] = '''
from django.contrib import messages
from django.shortcuts import render, redirect
from .models import Course, Teacher, Lead, News


def home(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        phone = request.POST.get("phone", "").strip()
        if name and phone:
            Lead.objects.create(
                name=name, phone=phone,
                course_id=request.POST.get("course") or None,
                comment=request.POST.get("comment", ""),
            )
            messages.success(request, "Заявка отправлена! Мы свяжемся с вами.")
        else:
            messages.error(request, "Укажите имя и телефон.")
        return redirect("home")

    return render(request, "public/home.html", {
        "courses": Course.objects.filter(is_active=True),
        "teachers": Teacher.objects.prefetch_related("courses"),
        "news": News.objects.filter(is_published=True)[:3],
    })
'''

FILES["website/urls.py"] = '''
from django.urls import path
from . import views

urlpatterns = [path("", views.home, name="home")]
'''

FILES["website/admin.py"] = '''
from django.contrib import admin
from .models import Course, Teacher, Lead, News


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("title", "monthly_price", "is_active")
    list_editable = ("is_active",)
    search_fields = ("title",)


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ("full_name", "user")
    filter_horizontal = ("courses",)
    search_fields = ("full_name",)


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "course", "status", "created_at")
    list_filter = ("status", "course")
    list_editable = ("status",)
    search_fields = ("name", "phone")
    date_hierarchy = "created_at"


@admin.register(News)
class NewsAdmin(admin.ModelAdmin):
    list_display = ("title", "is_published", "created_at")
    list_editable = ("is_published",)
'''

FILES["crm/models.py"] = '''
from decimal import Decimal
from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.utils import timezone


class Student(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Активный"
        PAUSED = "paused", "Заморожен"
        ARCHIVED = "archived", "Архив"

    full_name = models.CharField("ФИО", max_length=150)
    phone = models.CharField("Телефон", max_length=20, blank=True)
    birth_date = models.DateField("Дата рождения", null=True, blank=True)
    parent = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Родитель", null=True, blank=True,
                               on_delete=models.SET_NULL, related_name="children",
                               limit_choices_to={"role": "parent"})
    user = models.OneToOneField(settings.AUTH_USER_MODEL, verbose_name="Аккаунт студента", null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="student_profile")
    status = models.CharField("Статус", max_length=10, choices=Status.choices, default=Status.ACTIVE)
    joined_at = models.DateField("Дата зачисления", default=timezone.localdate)
    monthly_fee = models.DecimalField("Индивидуальная цена/мес", max_digits=12, decimal_places=2,
                                      null=True, blank=True, help_text="Пусто — цена курса группы")
    note = models.TextField("Заметка", blank=True)

    class Meta:
        verbose_name = "Студент"
        verbose_name_plural = "Студенты"
        ordering = ["full_name"]

    def __str__(self): return self.full_name

    @property
    def fee(self):
        if self.monthly_fee is not None:
            return self.monthly_fee
        g = self.groups.select_related("course").first()
        return g.course.monthly_price if g else Decimal("0")

    @property
    def paid_total(self):
        return self.payments.aggregate(s=Sum("amount"))["s"] or Decimal("0")

    @property
    def months_active(self):
        t, j = timezone.localdate(), self.joined_at
        return max(1, (t.year - j.year) * 12 + t.month - j.month + 1)

    @property
    def balance(self):
        return self.paid_total - self.fee * self.months_active

    @property
    def debt(self):
        return -self.balance if self.balance < 0 else Decimal("0")


class Group(models.Model):
    name = models.CharField("Название", max_length=100)
    course = models.ForeignKey("website.Course", verbose_name="Курс", on_delete=models.CASCADE, related_name="groups")
    teacher = models.ForeignKey("website.Teacher", verbose_name="Преподаватель", null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="groups")
    students = models.ManyToManyField(Student, verbose_name="Студенты", blank=True, related_name="groups")
    room = models.CharField("Кабинет", max_length=50, blank=True)
    is_active = models.BooleanField("Активна", default=True)

    class Meta:
        verbose_name = "Группа"
        verbose_name_plural = "Группы"

    def __str__(self): return self.name


class Schedule(models.Model):
    WEEKDAYS = [(0, "Понедельник"), (1, "Вторник"), (2, "Среда"), (3, "Четверг"),
                (4, "Пятница"), (5, "Суббота"), (6, "Воскресенье")]
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="schedule")
    weekday = models.PositiveSmallIntegerField("День недели", choices=WEEKDAYS)
    start = models.TimeField("Начало")
    end = models.TimeField("Конец")

    class Meta:
        verbose_name = "Расписание"
        verbose_name_plural = "Расписание"
        ordering = ["weekday", "start"]

    def __str__(self):
        return f"{self.get_weekday_display()} {self.start:%H:%M}-{self.end:%H:%M}"


def month_start():
    return timezone.localdate().replace(day=1)


class Payment(models.Model):
    class Method(models.TextChoices):
        CASH = "cash", "Наличные"
        CARD = "card", "Карта (терминал)"
        PAYME = "payme", "Payme"
        CLICK = "click", "Click"
        TRANSFER = "transfer", "Перечисление"

    student = models.ForeignKey(Student, verbose_name="Студент", on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField("Сумма", max_digits=12, decimal_places=2)
    method = models.CharField("Способ", max_length=10, choices=Method.choices, default=Method.CASH)
    paid_for = models.DateField("За месяц", default=month_start)
    paid_at = models.DateTimeField("Дата оплаты", auto_now_add=True)
    comment = models.CharField("Комментарий", max_length=200, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Принял", null=True, blank=True,
                                   on_delete=models.SET_NULL)

    class Meta:
        verbose_name = "Оплата"
        verbose_name_plural = "Оплаты"
        ordering = ["-paid_at"]

    def __str__(self): return f"{self.student} - {self.amount}"
'''

FILES["crm/views.py"] = '''
from django.db.models import Sum
from django.shortcuts import render
from django.utils import timezone
from accounts.decorators import role_required
from website.models import Lead
from .models import Student, Group, Payment


@role_required("admin", "manager")
def dashboard(request):
    today = timezone.localdate()
    active = Student.objects.filter(status=Student.Status.ACTIVE)
    revenue = Payment.objects.filter(
        paid_at__year=today.year, paid_at__month=today.month
    ).aggregate(s=Sum("amount"))["s"] or 0
    debtors = sorted((s for s in active if s.balance < 0), key=lambda s: s.balance)

    return render(request, "dashboard.html", {
        "students_count": active.count(),
        "groups_count": Group.objects.filter(is_active=True).count(),
        "new_leads": Lead.objects.filter(status=Lead.Status.NEW).count(),
        "revenue": revenue,
        "debtors": debtors[:10],
        "leads": Lead.objects.select_related("course")[:8],
        "payments": Payment.objects.select_related("student")[:8],
    })
'''

FILES["crm/admin.py"] = '''
from django.contrib import admin
from import_export.admin import ImportExportModelAdmin
from .models import Student, Group, Schedule, Payment


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    fields = ("amount", "method", "paid_for", "comment")


@admin.register(Student)
class StudentAdmin(ImportExportModelAdmin):
    list_display = ("full_name", "phone", "parent", "status", "fee", "paid_total", "balance", "joined_at")
    list_filter = ("status", "groups")
    search_fields = ("full_name", "phone", "parent__first_name", "parent__last_name")
    autocomplete_fields = ("parent", "user")
    inlines = (PaymentInline,)


class ScheduleInline(admin.TabularInline):
    model = Schedule
    extra = 1


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("name", "course", "teacher", "room", "is_active")
    list_filter = ("course", "is_active")
    filter_horizontal = ("students",)
    inlines = (ScheduleInline,)


@admin.register(Payment)
class PaymentAdmin(ImportExportModelAdmin):
    list_display = ("student", "amount", "method", "paid_for", "paid_at", "created_by")
    list_filter = ("method", "paid_for")
    search_fields = ("student__full_name",)
    date_hierarchy = "paid_at"

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
'''

FILES["crm/management/__init__.py"] = ""
FILES["crm/management/commands/__init__.py"] = ""

FILES["crm/management/commands/ensure_admin.py"] = '''
import os
from django.core.management.base import BaseCommand
from accounts.models import User


class Command(BaseCommand):
    def handle(self, *args, **options):
        if User.objects.filter(is_superuser=True).exists():
            self.stdout.write("Админ уже существует")
            return
        password = os.environ.get("ADMIN_PASSWORD")
        if not password:
            self.stdout.write("ADMIN_PASSWORD не задан - админ не создан")
            return
        username = os.environ.get("ADMIN_USERNAME", "admin")
        User.objects.create_superuser(username, password=password, role="admin")
        self.stdout.write("Создан админ: " + username)
'''

FILES["diary/models.py"] = '''
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models


class Lesson(models.Model):
    group = models.ForeignKey("crm.Group", verbose_name="Группа", on_delete=models.CASCADE, related_name="lessons")
    date = models.DateField("Дата")
    topic = models.CharField("Тема урока", max_length=200, blank=True)
    homework = models.TextField("Домашнее задание", blank=True)
    homework_due = models.DateField("Сдать до", null=True, blank=True)

    class Meta:
        verbose_name = "Урок"
        verbose_name_plural = "Уроки"
        unique_together = ("group", "date")
        ordering = ["date"]

    def __str__(self): return f"{self.group} - {self.date:%d.%m.%Y}"


class Attendance(models.Model):
    class Status(models.TextChoices):
        PRESENT = "P", "Был"
        ABSENT = "A", "Отсутствовал"
        LATE = "L", "Опоздал"
        EXCUSED = "E", "Ув. причина"

    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="attendance")
    student = models.ForeignKey("crm.Student", verbose_name="Студент", on_delete=models.CASCADE, related_name="attendance")
    status = models.CharField("Статус", max_length=1, choices=Status.choices, default=Status.PRESENT)

    class Meta:
        verbose_name = "Посещаемость"
        verbose_name_plural = "Посещаемость"
        unique_together = ("lesson", "student")

    @property
    def mark(self):
        return {"P": "", "A": "Н", "L": "О", "E": "У"}[self.status]


class Grade(models.Model):
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="grades")
    student = models.ForeignKey("crm.Student", verbose_name="Студент", on_delete=models.CASCADE, related_name="grades")
    value = models.PositiveSmallIntegerField("Оценка", validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.CharField("Комментарий", max_length=200, blank=True)

    class Meta:
        verbose_name = "Оценка"
        verbose_name_plural = "Оценки"
        unique_together = ("lesson", "student")

    def __str__(self): return f"{self.student}: {self.value}"
'''

FILES["diary/services.py"] = '''
from .models import Lesson, Attendance, Grade


def build_journal(group, year, month):
    lessons = list(Lesson.objects.filter(group=group, date__year=year, date__month=month))
    students = list(group.students.order_by("full_name"))
    att = {(a.lesson_id, a.student_id): a for a in Attendance.objects.filter(lesson__in=lessons)}
    grades = {(g.lesson_id, g.student_id): g for g in Grade.objects.filter(lesson__in=lessons)}
    rows = []
    for s in students:
        cells = [{"lesson": l, "att": att.get((l.id, s.id)), "grade": grades.get((l.id, s.id))} for l in lessons]
        rows.append({"student": s, "cells": cells})
    return {"lessons": lessons, "rows": rows}
'''

FILES["diary/views.py"] = '''
from datetime import date, timedelta
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.shortcuts import redirect, render, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from crm.models import Group, Student
from .models import Lesson, Attendance, Grade
from .services import build_journal


def _teacher_groups(user):
    qs = Group.objects.filter(is_active=True).select_related("course", "teacher")
    if user.is_superuser or user.is_staff or user.role in ("admin", "manager"):
        return qs
    return qs.filter(teacher__user=user)


def _year_month(request):
    today = timezone.localdate()
    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
        if not 1 <= month <= 12:
            raise ValueError
    except ValueError:
        year, month = today.year, today.month
    current = date(year, month, 1)
    return current, current - timedelta(days=1), (current + timedelta(days=32)).replace(day=1)


@login_required
def journal(request, group_id=None):
    groups = list(_teacher_groups(request.user))
    if not groups:
        messages.info(request, "Вам пока не назначены группы.")
        return redirect("home")
    if group_id is None:
        return redirect("journal_group", groups[0].id)
    group = get_object_or_404(_teacher_groups(request.user), id=group_id)

    if request.method == "POST":
        d = request.POST.get("date", "")
        try:
            Lesson.objects.create(
                group=group, date=d,
                topic=request.POST.get("topic", ""),
                homework=request.POST.get("homework", ""),
                homework_due=request.POST.get("homework_due") or None,
            )
            messages.success(request, "Урок добавлен.")
            y, m, _ = d.split("-")
            return redirect(f"{reverse('journal_group', args=[group.id])}?year={y}&month={int(m)}")
        except (ValidationError, IntegrityError, ValueError):
            messages.error(request, "Проверьте дату: на одну дату один урок.")
        return redirect("journal_group", group.id)

    current, prev_m, next_m = _year_month(request)
    data = build_journal(group, current.year, current.month)
    return render(request, "diary/journal.html", {
        "group": group, "groups": groups, "current": current,
        "prev_month": prev_m, "next_month": next_m,
        "today": timezone.localdate(), **data,
    })


@login_required
def lesson(request, lesson_id):
    les = get_object_or_404(Lesson.objects.select_related("group"), id=lesson_id)
    get_object_or_404(_teacher_groups(request.user), id=les.group_id)
    students = list(les.group.students.order_by("full_name"))

    if request.method == "POST":
        les.topic = request.POST.get("topic", "")
        les.homework = request.POST.get("homework", "")
        les.homework_due = request.POST.get("homework_due") or None
        les.save()
        for s in students:
            Attendance.objects.update_or_create(
                lesson=les, student=s,
                defaults={"status": request.POST.get(f"att_{s.id}", "P")},
            )
            raw = request.POST.get(f"grade_{s.id}", "").strip()
            if raw:
                try:
                    Grade.objects.update_or_create(
                        lesson=les, student=s,
                        defaults={"value": min(5, max(1, int(raw)))},
                    )
                except ValueError:
                    pass
            else:
                Grade.objects.filter(lesson=les, student=s).delete()
        messages.success(request, "Сохранено.")
        return redirect(f"{reverse('journal_group', args=[les.group_id])}?year={les.date.year}&month={les.date.month}")

    att = {a.student_id: a for a in les.attendance.all()}
    grades = {g.student_id: g for g in les.grades.all()}
    rows = [{"student": s, "att": att.get(s.id), "grade": grades.get(s.id)} for s in students]
    return render(request, "diary/lesson.html", {"lesson": les, "rows": rows})


@login_required
def diary(request):
    u = request.user
    if u.role == "student":
        children = list(Student.objects.filter(user=u))
    else:
        children = list(u.children.all())
    if not children:
        messages.info(request, "К аккаунту не привязан ни один студент.")
        return redirect("home")

    child = next((c for c in children if str(c.id) == request.GET.get("child")), children[0])
    groups = list(child.groups.filter(is_active=True))
    group = next((g for g in groups if str(g.id) == request.GET.get("group")), groups[0] if groups else None)

    current, prev_m, next_m = _year_month(request)
    data = build_journal(group, current.year, current.month) if group else {"lessons": [], "rows": []}
    homework = Lesson.objects.filter(group=group).exclude(homework="").order_by("-date")[:6] if group else []

    return render(request, "diary/diary.html", {
        "child": child, "children": children, "group": group, "groups": groups,
        "current": current, "prev_month": prev_m, "next_month": next_m,
        "homework": homework,
        "payments": child.payments.all()[:10],
        "schedule": group.schedule.all() if group else [],
        **data,
    })
'''

FILES["diary/urls.py"] = '''
from django.urls import path
from . import views

urlpatterns = [
    path("journal/", views.journal, name="journal"),
    path("journal/<int:group_id>/", views.journal, name="journal_group"),
    path("lesson/<int:lesson_id>/", views.lesson, name="lesson"),
    path("diary/", views.diary, name="diary"),
]
'''

FILES["diary/admin.py"] = '''
from django.contrib import admin
from .models import Lesson, Attendance, Grade


class AttendanceInline(admin.TabularInline):
    model = Attendance
    extra = 0


class GradeInline(admin.TabularInline):
    model = Grade
    extra = 0


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("group", "date", "topic")
    list_filter = ("group",)
    date_hierarchy = "date"
    inlines = (AttendanceInline, GradeInline)
'''

FILES["templates/base.html"] = '''
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}EduCenter{% endblock %}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
<nav class="navbar navbar-expand-lg navbar-dark bg-dark">
  <div class="container">
    <a class="navbar-brand fw-bold" href="/">EduCenter</a>
    <div class="navbar-nav me-auto">
      {% if user.is_authenticated %}
        {% if user.is_staff or user.role == 'admin' or user.role == 'manager' %}
          <a class="nav-link" href="{% url 'dashboard' %}">Дашборд</a>
          <a class="nav-link" href="/admin/">Управление</a>
        {% endif %}
        {% if user.is_staff or user.role == 'teacher' %}<a class="nav-link" href="{% url 'journal' %}">Журнал</a>{% endif %}
        {% if user.role == 'parent' or user.role == 'student' %}<a class="nav-link" href="{% url 'diary' %}">Дневник</a>{% endif %}
      {% endif %}
    </div>
    <div class="navbar-nav">
      {% if user.is_authenticated %}
        <span class="navbar-text me-3">{{ user.get_full_name|default:user.username }}
          <span class="badge bg-secondary">{{ user.get_role_display }}</span></span>
        <form method="post" action="{% url 'logout' %}" class="d-inline">{% csrf_token %}
          <button class="btn btn-outline-light btn-sm">Выйти</button></form>
      {% else %}<a class="nav-link" href="{% url 'login' %}">Войти</a>{% endif %}
    </div>
  </div>
</nav>
<main class="container py-4">
  {% for m in messages %}
    <div class="alert alert-{{ m.tags|default:'info' }} alert-dismissible fade show">{{ m }}
      <button class="btn-close" data-bs-dismiss="alert"></button></div>
  {% endfor %}
  {% block content %}{% endblock %}
</main>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''

FILES["templates/registration/login.html"] = '''
{% extends "base.html" %}
{% block title %}Вход{% endblock %}
{% block content %}
<div class="row justify-content-center"><div class="col-md-4">
  <div class="card shadow-sm"><div class="card-body">
    <h4 class="mb-3">Вход в систему</h4>
    {% if form.errors %}<div class="alert alert-danger">Неверный логин или пароль</div>{% endif %}
    <form method="post">{% csrf_token %}
      <div class="mb-3"><label class="form-label">Логин</label>
        <input name="username" class="form-control" autofocus required></div>
      <div class="mb-3"><label class="form-label">Пароль</label>
        <input type="password" name="password" class="form-control" required></div>
      <button class="btn btn-primary w-100">Войти</button>
    </form>
  </div></div>
</div></div>
{% endblock %}
'''

FILES["templates/public/home.html"] = '''
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <title>EduCenter — учебный центр</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark bg-dark sticky-top">
  <div class="container">
    <a class="navbar-brand fw-bold" href="/">EduCenter</a>
    <div class="navbar-nav ms-auto">
      <a class="nav-link" href="#courses">Курсы</a>
      <a class="nav-link" href="#teachers">Преподаватели</a>
      <a class="nav-link" href="#apply">Записаться</a>
      <a class="nav-link fw-bold" href="{% url 'login' %}">Войти</a>
    </div>
  </div>
</nav>
<header style="background:linear-gradient(135deg,#1e3a8a,#3b82f6)" class="text-white py-5">
  <div class="container py-5">
    <h1 class="display-4 fw-bold">Знания, которые меняют будущее</h1>
    <p class="lead col-md-7">Электронный дневник для родителей, контроль посещаемости и прозрачная оплата.</p>
    <a href="#apply" class="btn btn-warning btn-lg fw-bold">Оставить заявку</a>
  </div>
</header>
<main class="container py-5">
  {% for m in messages %}<div class="alert alert-{{ m.tags|default:'info' }}">{{ m }}</div>{% endfor %}
  <h2 id="courses" class="mb-4">Наши курсы</h2>
  <div class="row g-4 mb-5">
    {% for c in courses %}
    <div class="col-md-4"><div class="card h-100 shadow-sm">
      <div class="card-body"><h5 class="card-title">{{ c.title }}</h5>
        <p class="card-text text-muted">{{ c.description|linebreaksbr }}</p></div>
      <div class="card-footer bg-white d-flex justify-content-between align-items-center">
        <b>{{ c.monthly_price|floatformat:0 }} сум/мес</b>
        <a href="#apply" class="btn btn-primary btn-sm">Записаться</a></div>
    </div></div>
    {% empty %}<p class="text-muted">Курсы скоро появятся.</p>{% endfor %}
  </div>
  <h2 id="teachers" class="mb-4">Преподаватели</h2>
  <div class="row g-4 mb-5">
    {% for t in teachers %}
    <div class="col-md-4"><div class="card h-100"><div class="card-body">
      <h5>{{ t.full_name }}</h5><p class="text-muted">{{ t.bio }}</p>
      {% for c in t.courses.all %}<span class="badge bg-info text-dark">{{ c.title }}</span> {% endfor %}
    </div></div></div>
    {% endfor %}
  </div>
  {% if news %}
  <h2 class="mb-4">Новости</h2>
  <div class="row g-4 mb-5">
    {% for n in news %}
    <div class="col-md-4"><div class="card h-100"><div class="card-body">
      <small class="text-muted">{{ n.created_at|date:"d.m.Y" }}</small>
      <h5>{{ n.title }}</h5><p>{{ n.text|truncatechars:150 }}</p>
    </div></div></div>
    {% endfor %}
  </div>
  {% endif %}
  <div id="apply" class="row justify-content-center">
    <div class="col-md-6"><div class="card shadow"><div class="card-body p-4">
      <h3 class="mb-3">Записаться на курс</h3>
      <form method="post">{% csrf_token %}
        <div class="mb-3"><input name="name" class="form-control" placeholder="Ваше имя *" required></div>
        <div class="mb-3"><input name="phone" class="form-control" placeholder="+998 __ ___ __ __ *" required></div>
        <div class="mb-3"><select name="course" class="form-select">
          <option value="">Выберите курс</option>
          {% for c in courses %}<option value="{{ c.id }}">{{ c.title }}</option>{% endfor %}
        </select></div>
        <div class="mb-3"><textarea name="comment" class="form-control" placeholder="Комментарий"></textarea></div>
        <button class="btn btn-primary w-100 btn-lg">Отправить заявку</button>
      </form>
    </div></div></div>
  </div>
</main>
<footer class="bg-dark text-white py-4 mt-5">
  <div class="container d-flex flex-wrap justify-content-between">
    <span>© EduCenter, г. Ташкент</span><span>Telegram: @educenter</span>
  </div>
</footer>
</body>
</html>
'''

FILES["templates/dashboard.html"] = '''
{% extends "base.html" %}
{% block title %}Дашборд{% endblock %}
{% block content %}
<h3 class="mb-4">Панель управления</h3>
<div class="row g-3 mb-4">
  <div class="col-md-3"><div class="card text-bg-primary"><div class="card-body">
    <h6>Активных студентов</h6><h2>{{ students_count }}</h2></div></div></div>
  <div class="col-md-3"><div class="card text-bg-secondary"><div class="card-body">
    <h6>Групп</h6><h2>{{ groups_count }}</h2></div></div></div>
  <div class="col-md-3"><div class="card text-bg-warning"><div class="card-body">
    <h6>Новых заявок</h6><h2>{{ new_leads }}</h2>
    <a href="{% url 'admin:website_lead_changelist' %}" class="text-dark small">обработать</a></div></div></div>
  <div class="col-md-3"><div class="card text-bg-success"><div class="card-body">
    <h6>Выручка за месяц</h6><h2>{{ revenue|floatformat:0 }}</h2><small>сум</small></div></div></div>
</div>
<div class="row g-4">
  <div class="col-lg-6"><div class="card">
    <div class="card-header d-flex justify-content-between"><b>Должники</b>
      <a href="{% url 'admin:crm_student_changelist' %}">все студенты</a></div>
    <table class="table table-sm mb-0">
      <tr><th>Студент</th><th>Телефон</th><th class="text-end">Долг</th></tr>
      {% for s in debtors %}
      <tr><td><a href="{% url 'admin:crm_student_change' s.id %}">{{ s.full_name }}</a></td>
        <td>{{ s.phone|default:"-" }}</td>
        <td class="text-end text-danger fw-bold">{{ s.debt|floatformat:0 }} сум</td></tr>
      {% empty %}<tr><td colspan="3" class="text-muted">Должников нет</td></tr>{% endfor %}
    </table>
  </div></div>
  <div class="col-lg-6"><div class="card">
    <div class="card-header d-flex justify-content-between"><b>Последние оплаты</b>
      <a href="{% url 'admin:crm_payment_changelist' %}">все оплаты</a></div>
    <table class="table table-sm mb-0">
      <tr><th>Дата</th><th>Студент</th><th class="text-end">Сумма</th></tr>
      {% for p in payments %}
      <tr><td>{{ p.paid_at|date:"d.m.Y" }}</td><td>{{ p.student }}</td>
        <td class="text-end">{{ p.amount|floatformat:0 }}</td></tr>
      {% empty %}<tr><td colspan="3" class="text-muted">Оплат пока нет</td></tr>{% endfor %}
    </table>
  </div></div>
  <div class="col-12"><div class="card">
    <div class="card-header d-flex justify-content-between"><b>Заявки с сайта</b>
      <a href="{% url 'admin:website_lead_changelist' %}">все заявки</a></div>
    <table class="table table-sm mb-0">
      <tr><th>Дата</th><th>Имя</th><th>Телефон</th><th>Курс</th><th>Статус</th></tr>
      {% for l in leads %}
      <tr><td>{{ l.created_at|date:"d.m H:i" }}</td>
        <td><a href="{% url 'admin:website_lead_change' l.id %}">{{ l.name }}</a></td>
        <td>{{ l.phone }}</td><td>{{ l.course|default:"-" }}</td><td>{{ l.get_status_display }}</td></tr>
      {% empty %}<tr><td colspan="5" class="text-muted">Заявок пока нет</td></tr>{% endfor %}
    </table>
  </div></div>
</div>
{% endblock %}
'''

FILES["templates/diary/_grid.html"] = '''
{% if lessons %}
<div class="table-responsive bg-white">
<table class="table table-bordered table-sm align-middle text-center">
  <thead class="table-light"><tr>
    <th class="text-start">Студент</th>
    {% for l in lessons %}
      <th>{% if editable %}<a href="{% url 'lesson' l.id %}" title="{{ l.topic }}">{{ l.date|date:"d.m" }}</a>
          {% else %}{{ l.date|date:"d.m" }}{% endif %}</th>
    {% endfor %}
  </tr></thead>
  <tbody>
  {% for row in rows %}
    <tr><td class="text-start">{{ row.student.full_name }}</td>
      {% for c in row.cells %}
      <td>
        {% if c.grade %}<span class="badge bg-{% if c.grade.value >= 4 %}success{% elif c.grade.value == 3 %}warning{% else %}danger{% endif %}">{{ c.grade.value }}</span>{% endif %}
        {% if c.att.mark %}<span class="text-danger fw-bold">{{ c.att.mark }}</span>{% endif %}
      </td>
      {% endfor %}
    </tr>
  {% empty %}<tr><td colspan="99" class="text-muted">В группе нет студентов</td></tr>{% endfor %}
  </tbody>
</table>
</div>
{% else %}<div class="alert alert-light border">В этом месяце уроков нет.</div>{% endif %}
'''

FILES["templates/diary/journal.html"] = '''
{% extends "base.html" %}
{% block title %}Журнал — {{ group.name }}{% endblock %}
{% block content %}
<div class="d-flex flex-wrap justify-content-between align-items-center mb-3">
  <h3>Журнал — {{ group.name }}</h3>
  <div class="btn-group">
    {% for g in groups %}
      <a href="{% url 'journal_group' g.id %}" class="btn btn-sm btn-outline-secondary {% if g.id == group.id %}active{% endif %}">{{ g.name }}</a>
    {% endfor %}
  </div>
</div>
<div class="d-flex justify-content-between align-items-center mb-3">
  <a class="btn btn-outline-primary btn-sm" href="?year={{ prev_month.year }}&month={{ prev_month.month }}">{{ prev_month|date:"F Y" }}</a>
  <h5 class="mb-0">{{ current|date:"F Y" }}</h5>
  <a class="btn btn-outline-primary btn-sm" href="?year={{ next_month.year }}&month={{ next_month.month }}">{{ next_month|date:"F Y" }}</a>
</div>
{% include "diary/_grid.html" with editable=1 %}
<p class="text-muted small">Н — отсутствие, О — опоздание, У — ув. причина. Нажмите на дату урока, чтобы выставить оценки.</p>
<div class="card mt-3"><div class="card-header"><b>Добавить урок</b></div><div class="card-body">
  <form method="post" class="row g-2">{% csrf_token %}
    <div class="col-md-2"><input type="date" name="date" class="form-control" required value="{{ today|date:'Y-m-d' }}"></div>
    <div class="col-md-3"><input name="topic" class="form-control" placeholder="Тема урока"></div>
    <div class="col-md-3"><input name="homework" class="form-control" placeholder="Домашнее задание"></div>
    <div class="col-md-2"><input type="date" name="homework_due" class="form-control" title="Срок сдачи ДЗ"></div>
    <div class="col-md-2"><button class="btn btn-success w-100">Добавить</button></div>
  </form>
</div></div>
{% endblock %}
'''

FILES["templates/diary/lesson.html"] = '''
{% extends "base.html" %}
{% block title %}Урок {{ lesson.date|date:"d.m.Y" }}{% endblock %}
{% block content %}
<h3>{{ lesson.group.name }} — {{ lesson.date|date:"d.m.Y" }}</h3>
<form method="post">{% csrf_token %}
  <div class="row g-2 mb-3">
    <div class="col-md-4"><label class="form-label">Тема</label>
      <input name="topic" value="{{ lesson.topic }}" class="form-control"></div>
    <div class="col-md-5"><label class="form-label">Домашнее задание</label>
      <input name="homework" value="{{ lesson.homework }}" class="form-control"></div>
    <div class="col-md-3"><label class="form-label">Сдать до</label>
      <input type="date" name="homework_due" value="{{ lesson.homework_due|date:'Y-m-d' }}" class="form-control"></div>
  </div>
  <table class="table table-bordered align-middle bg-white">
    <thead class="table-light"><tr><th>Студент</th><th style="width:220px">Посещаемость</th><th style="width:140px">Оценка (1-5)</th></tr></thead>
    <tbody>
    {% for r in rows %}
    <tr>
      <td>{{ r.student.full_name }}</td>
      <td><select name="att_{{ r.student.id }}" class="form-select form-select-sm">
        <option value="P" {% if r.att.status == 'P' or not r.att %}selected{% endif %}>Был</option>
        <option value="A" {% if r.att.status == 'A' %}selected{% endif %}>Отсутствовал</option>
        <option value="L" {% if r.att.status == 'L' %}selected{% endif %}>Опоздал</option>
        <option value="E" {% if r.att.status == 'E' %}selected{% endif %}>Ув. причина</option>
      </select></td>
      <td><input type="number" min="1" max="5" name="grade_{{ r.student.id }}"
                 value="{{ r.grade.value|default:'' }}" class="form-control form-control-sm"></td>
    </tr>
    {% endfor %}
    </tbody>
  </table>
  <button class="btn btn-primary">Сохранить</button>
  <a href="{% url 'journal_group' lesson.group_id %}?year={{ lesson.date.year }}&month={{ lesson.date.month }}"
     class="btn btn-outline-secondary">Назад к журналу</a>
</form>
{% endblock %}
'''

FILES["templates/diary/diary.html"] = '''
{% extends "base.html" %}
{% block title %}Дневник — {{ child.full_name }}{% endblock %}
{% block content %}
<div class="d-flex flex-wrap justify-content-between align-items-center mb-3">
  <h3>Дневник — {{ child.full_name }}</h3>
  {% if children|length > 1 %}
  <div class="btn-group">
    {% for c in children %}
      <a class="btn btn-sm btn-outline-secondary {% if c.id == child.id %}active{% endif %}" href="?child={{ c.id }}">{{ c.full_name }}</a>
    {% endfor %}
  </div>
  {% endif %}
</div>
{% if child.balance < 0 %}
  <div class="alert alert-danger">Задолженность: <b>{{ child.debt|floatformat:0 }} сум</b>.
    Оплата за месяц: {{ child.fee|floatformat:0 }} сум.</div>
{% else %}
  <div class="alert alert-success">Задолженности нет. Баланс: {{ child.balance|floatformat:0 }} сум.</div>
{% endif %}
{% if group %}
  {% if groups|length > 1 %}
  <div class="btn-group mb-3">
    {% for g in groups %}
      <a class="btn btn-sm btn-outline-primary {% if g.id == group.id %}active{% endif %}"
         href="?child={{ child.id }}&group={{ g.id }}">{{ g.name }}</a>
    {% endfor %}
  </div>
  {% endif %}
  <div class="d-flex justify-content-between align-items-center mb-3">
    <a class="btn btn-outline-primary btn-sm"
       href="?child={{ child.id }}&group={{ group.id }}&year={{ prev_month.year }}&month={{ prev_month.month }}">{{ prev_month|date:"F Y" }}</a>
    <h5 class="mb-0">{{ group.name }} · {{ current|date:"F Y" }}</h5>
    <a class="btn btn-outline-primary btn-sm"
       href="?child={{ child.id }}&group={{ group.id }}&year={{ next_month.year }}&month={{ next_month.month }}">{{ next_month|date:"F Y" }}</a>
  </div>
  {% include "diary/_grid.html" %}
  <p class="text-muted small">Н — отсутствие, О — опоздание, У — ув. причина.</p>
  <div class="row g-4 mt-1">
    <div class="col-lg-4"><div class="card">
      <div class="card-header"><b>Расписание</b></div>
      <ul class="list-group list-group-flush">
        {% for s in schedule %}
          <li class="list-group-item">{{ s.get_weekday_display }}: {{ s.start|time:"H:i" }}-{{ s.end|time:"H:i" }}
            {% if group.room %}<small class="text-muted">({{ group.room }})</small>{% endif %}</li>
        {% empty %}<li class="list-group-item text-muted">Не задано</li>{% endfor %}
      </ul>
    </div></div>
    <div class="col-lg-4"><div class="card">
      <div class="card-header"><b>Домашние задания</b></div>
      <ul class="list-group list-group-flush">
        {% for l in homework %}
          <li class="list-group-item"><b>{{ l.date|date:"d.m" }}:</b> {{ l.homework }}
            {% if l.homework_due %}<br><small class="text-muted">сдать до {{ l.homework_due|date:"d.m" }}</small>{% endif %}</li>
        {% empty %}<li class="list-group-item text-muted">Пока пусто</li>{% endfor %}
      </ul>
    </div></div>
    <div class="col-lg-4"><div class="card">
      <div class="card-header"><b>Оплаты</b></div>
      <table class="table table-sm mb-0">
        <tr><th>Дата</th><th>Сумма</th><th>Способ</th></tr>
        {% for p in payments %}
          <tr><td>{{ p.paid_at|date:"d.m.Y" }}</td><td>{{ p.amount|floatformat:0 }}</td><td>{{ p.get_method_display }}</td></tr>
        {% empty %}<tr><td colspan="3" class="text-muted">Оплат нет</td></tr>{% endfor %}
      </table>
    </div></div>
  </div>
{% else %}
  <div class="alert alert-info">Студент пока не зачислен в группу.</div>
{% endif %}
{% endblock %}
'''


def write(rel, text):
    path = BASE / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def sh(cmd):
    print(">>", cmd, flush=True)
    subprocess.run(cmd, shell=True, check=True, cwd=BASE)


def main():
    if not (BASE / "manage.py").exists():
        sh("django-admin startproject config .")
        for app in ("accounts", "website", "crm", "diary"):
            sh(f"{sys.executable} manage.py startapp {app}")
    for rel, text in FILES.items():
        write(rel, text)
    print(f"Проект создан: {len(FILES)} файлов", flush=True)


if __name__ == "__main__":
    main()
