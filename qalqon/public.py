"""Публичный сайт и электронная запись (Qabul)."""
import threading
from datetime import datetime, date
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort
from .models import *
from .core import *
from .core import _send_telegram, _send_email

bp = Blueprint("pub", __name__)


@bp.route("/")
def index():
    return render_template(
        "pub/index.html",
        staff=Staff.query.order_by(Staff.sort, Staff.id).all(),
        news=News.query.filter_by(published=True).order_by(News.day.desc(), News.id.desc()).limit(3).all(),
        gallery=GalleryItem.query.order_by(GalleryItem.created.desc()).limit(6).all(),
    )


@bp.route("/news")
def news():
    cat = request.args.get("cat", "")
    q = News.query.filter_by(published=True)
    if cat in NEWS_CATS:
        q = q.filter_by(category=cat)
    return render_template("pub/news.html", items=q.order_by(News.day.desc(), News.id.desc()).all(), cat=cat)


@bp.route("/news/<int:nid>")
def news_one(nid):
    n = News.query.filter_by(id=nid, published=True).first_or_404()
    return render_template("pub/news_one.html", n=n)


@bp.route("/gallery")
def gallery():
    cat = request.args.get("cat", "")
    q = GalleryItem.query
    if cat in CATS:
        q = q.filter_by(category=cat)
    return render_template("pub/gallery.html", items=q.order_by(GalleryItem.created.desc()).all(), cat=cat)


def norm_phone(p):
    return re.sub(r"\D", "", p or "")[-9:]


@bp.route("/qabul", methods=["GET", "POST"])
def qabul():
    f = request.form
    if request.method == "POST":
        if f.get("website"):  # honeypot
            return redirect(url_for("pub.index"))
        key = f"apply|{request.remote_addr}"
        errs = []
        child, parent = f.get("child_name", "").strip(), f.get("parent_name", "").strip()
        phone = f.get("phone", "").strip()
        grade = f.get("grade", "").strip()
        try:
            bd = date.fromisoformat(f.get("birth_date", ""))
            age = (today() - bd).days / 365.25
            if not 5 <= age <= 19:
                errs.append(L("Tug‘ilgan sana noto‘g‘ri.", "Проверьте дату рождения."))
        except ValueError:
            bd = None
            errs.append(L("Tug‘ilgan sanani kiriting.", "Укажите дату рождения."))
        if len(child) < 5:
            errs.append(L("Bolaning to‘liq F.I.Sh. ni kiriting.", "Укажите полные ФИО ребёнка."))
        if len(parent) < 5:
            errs.append(L("Ota-onaning to‘liq F.I.Sh. ni kiriting.", "Укажите полные ФИО родителя."))
        if len(norm_phone(phone)) < 9:
            errs.append(L("Telefon raqami noto‘g‘ri.", "Неверный номер телефона."))
        if not f.get("address", "").strip():
            errs.append(L("Yashash manzilini kiriting.", "Укажите адрес проживания."))
        if not grade:
            errs.append(L("Sinfni tanlang.", "Выберите класс."))
        if throttled(key, 6, 3600):
            errs.append(L("Juda ko‘p ariza. Keyinroq urinib ko‘ring.", "Слишком много заявок. Попробуйте позже."))
        if errs:
            for e in errs:
                flash(e, "bad")
            return render_template("pub/qabul.html", f=f), 400
        fail_attempt(key)
        a = Application(number="tmp" + secrets.token_hex(6), child_name=child[:120], birth_date=bd,
                        parent_name=parent[:120], phone=phone[:30], email=f.get("email", "").strip()[:120],
                        address=f.get("address", "").strip()[:250], prev_school=f.get("prev_school", "").strip()[:160],
                        grade=grade[:20], extra=f.get("extra", "").strip()[:2000])
        db.session.add(a)
        db.session.flush()
        a.number = f"QJ-{today().year}-{a.id:05d}"
        nfiles = 0
        for fs in request.files.getlist("docs")[:5]:
            if save_upload(fs, "app", a.id):
                nfiles += 1
        notify(admins(), "application", f"Yangi ariza {a.number}: {a.child_name}",
               f"Новая заявка {a.number}: {a.child_name}", f"/admin/applications/{a.id}")
        db.session.commit()
        audit("application_new", a.number)
        tg = os.environ.get("TG_CHAT_ID")
        if tg:
            threading.Thread(target=_send_telegram, daemon=True,
                             args=(tg, f"Yangi ariza {a.number}\n{a.child_name}\n{a.parent_name} {a.phone}")).start()
        if a.email:
            threading.Thread(target=_send_email, daemon=True, args=(
                a.email, f"Qalqon: ariza {a.number}",
                f"Arizangiz qabul qilindi. Raqam: {a.number}\nЗаявка принята. Номер: {a.number}")).start()
        return redirect(url_for("pub.done", number=a.number))
    return render_template("pub/qabul.html", f={})


@bp.route("/qabul/done/<number>")
def done(number):
    a = Application.query.filter_by(number=number).first_or_404()
    if (datetime.utcnow() - a.created).total_seconds() > 3600:
        abort(404)
    return render_template("pub/done.html", a=a)


@bp.route("/qabul/status", methods=["GET", "POST"])
def status():
    a = None
    if request.method == "POST":
        key = f"status|{request.remote_addr}"
        if throttled(key, 10, 600):
            flash(L("Juda ko‘p urinish.", "Слишком много попыток."), "bad")
        else:
            fail_attempt(key)
            num = request.form.get("number", "").strip().upper()
            a = Application.query.filter_by(number=num).first()
            if not a or norm_phone(a.phone) != norm_phone(request.form.get("phone")):
                a = None
                flash(L("Ariza topilmadi. Raqam va telefonni tekshiring.", "Заявка не найдена. Проверьте номер и телефон."), "bad")
    return render_template("pub/status.html", a=a)
