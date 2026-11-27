"""Qalqon Jasorat Maktabi — цифровая платформа школы (Flask)."""
import os, re, secrets
from datetime import timedelta
from markupsafe import Markup
from flask import Flask, session, request, g, redirect, flash, render_template, abort
from .models import db, User, Notification
from . import core
from .core import L, lang


def create_app():
    app = Flask(__name__, static_folder="../static", template_folder="../templates")
    prod = os.environ.get("PRODUCTION") == "1"
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY") or (None if prod else "dev-only-" + secrets.token_hex(8)),
        SQLALCHEMY_DATABASE_URI=re.sub(r"^postgres(ql)?://", "postgresql+psycopg2://",
                                       os.environ.get("DATABASE_URL") or "sqlite:///qalqon.db"),
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=prod,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        MAX_CONTENT_LENGTH=25 * 1024 * 1024,
        PROD=prod,
    )
    if not app.config["SECRET_KEY"]:
        raise RuntimeError("Задайте SECRET_KEY в переменных окружения")
    if prod:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.url_map.strict_slashes = False
    db.init_app(app)

    from .public import bp as pub
    from .auth import bp as auth
    from .admin import bp as admin
    from .teacher import bp as teacher
    from .cabinet import bp as cabinet
    for b in (pub, auth, admin, teacher, cabinet):
        app.register_blueprint(b)

    @app.before_request
    def guard():
        core.load_user()
        if request.method == "POST":
            tok = session.get("_csrf")
            if not tok or not secrets.compare_digest(tok, request.form.get("_csrf", "")):
                flash(L("Sahifa eskirgan. Qayta urinib ko‘ring.", "Страница устарела. Попробуйте ещё раз."), "warn")
                ref = request.referrer or ""
                if request.endpoint == "auth.login":
                    return redirect("/login")
                return redirect(ref if ref.startswith(request.host_url) else "/")

    @app.after_request
    def headers(r):
        r.headers["X-Content-Type-Options"] = "nosniff"
        r.headers["X-Frame-Options"] = "SAMEORIGIN"
        r.headers["Referrer-Policy"] = "same-origin"
        r.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if app.config["PROD"]:
            r.headers["Strict-Transport-Security"] = "max-age=31536000"
        if request.path.startswith(("/admin", "/teacher", "/cabinet", "/login", "/account", "/messages", "/file")):
            r.headers["Cache-Control"] = "no-store"
        return r

    from .ops import money as ops_money, METHODS as ops_methods

    @app.context_processor
    def ctx():
        unread = 0
        if g.get("user"):
            unread = Notification.query.filter_by(user_id=g.user.id, read=False).count()
        tok = lambda: Markup('<input type="hidden" name="_csrf" value="%s">' % core.csrf_token())
        return dict(tok=tok, L=L, lang=lang(), me=g.get("user"), csrf=core.csrf_token, site=core.site(), unread=unread,
                    today=core.today, fmt=core.fmt_date, fmtdt=core.fmt_dt, nm=core.nm, pick=core.pick,
                    STATUS=core.STATUS_NAMES, ATT=core.ATT_NAMES, WEEKDAYS=core.WEEKDAYS, MONTHS=core.MONTHS,
                    ACH=core.ACH_NAMES, ROLE=core.ROLE_NAMES, CATS=core.CATS, NEWS_CATS=core.NEWS_CATS,
                    PERIODS=core.PERIODS, money=ops_money, METHODS=ops_methods, HWS=core.HW_STATUS, subj=core.subj_name, video_info=core.video_info)

    def err(code, uz, ru):
        return render_template("error.html", code=code, msg=L(uz, ru)), code

    app.register_error_handler(403, lambda e: err(403, "Ruxsat yo‘q", "Доступ запрещён"))
    app.register_error_handler(404, lambda e: err(404, "Sahifa topilmadi", "Страница не найдена"))
    app.register_error_handler(413, lambda e: err(413, "Fayl juda katta", "Файл слишком большой"))
    app.register_error_handler(500, lambda e: err(500, "Server xatosi", "Ошибка сервера"))

    with app.app_context():
        try:
            db.create_all()
            ensure_admin(prod)
        except Exception as e:  # БД может быть недоступна при сборке
            app.logger.error("DB init failed: %s", e)

    from .seed import register_cli
    register_cli(app)
    return app


def ensure_admin(prod):
    if User.query.filter_by(role="admin").first():
        return
    name = os.environ.get("ADMIN_USERNAME", "admin")
    pw = os.environ.get("ADMIN_PASSWORD")
    if not pw:
        if prod:
            raise RuntimeError("Задайте ADMIN_PASSWORD в переменных окружения")
        pw = "admin12345"
    u = User(username=name, role="admin", full_name="Administrator", must_change=not prod)
    u.set_password(pw)
    db.session.add(u)
    db.session.commit()
