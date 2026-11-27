"""Вход, выход, профиль, восстановление пароля, уведомления, сообщения, файлы."""
import hashlib, os, secrets
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, g, abort, Response
from .models import *
from .core import *

bp = Blueprint("auth", __name__)


def home_for(u):
    return {"admin": "/admin", "teacher": "/teacher"}.get(u.role, "/cabinet")


@bp.route("/lang/<l>")
def set_lang(l):
    if l in ("ru", "uz"):
        session["lang"] = l
    nxt = request.args.get("next", "/")
    return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else "/")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user and request.method == "GET":
        return redirect(home_for(g.user))
    if request.method == "POST":
        name = request.form.get("username", "").strip().lower()
        key = f"{request.remote_addr}|{name}"
        if throttled(key):
            flash(L("Juda ko‘p urinish. 10 daqiqadan so‘ng qayta urining.", "Слишком много попыток. Повторите через 10 минут."), "bad")
            return render_template("auth/login.html"), 429
        u = User.query.filter(func.lower(User.username) == name).first()
        if u and u.active and u.check(request.form.get("password", "")):
            clear_attempts(key)
            lg = session.get("lang")
            session.clear()
            session["uid"] = u.id
            session["pv"] = pw_stamp(u)
            if lg:
                session["lang"] = lg
            session.permanent = True
            u.last_login = datetime.utcnow()
            db.session.commit()
            audit("login", f"role={u.role}", user=u)
            nxt = request.args.get("next") or ""
            if nxt.startswith("/") and not nxt.startswith("//") and not nxt.startswith("/login"):
                return redirect(nxt.rstrip("?"))
            return redirect(home_for(u))
        fail_attempt(key)
        audit("login_failed", f"user={name[:40]}")
        flash(L("Login yoki parol noto‘g‘ri.", "Неверный логин или пароль."), "bad")
    return render_template("auth/login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    if g.user:
        audit("logout")
    lg = session.get("lang")
    session.clear()
    if lg:
        session["lang"] = lg
    return redirect("/")


@bp.route("/account", methods=["GET", "POST"])
@login_required
def account():
    u = g.user
    if request.method == "POST":
        act = request.form.get("act")
        if act == "profile":
            u.full_name = request.form.get("full_name", u.full_name).strip()[:120] or u.full_name
            u.phone = request.form.get("phone", "").strip()[:30]
            u.email = request.form.get("email", "").strip()[:120]
            u.telegram_chat_id = re.sub(r"[^\d-]", "", request.form.get("telegram_chat_id", ""))[:40]
            db.session.commit()
            audit("profile_update")
            flash(L("Saqlandi.", "Сохранено."), "ok")
        elif act == "password":
            old, new = request.form.get("old", ""), request.form.get("new", "")
            if not u.check(old):
                flash(L("Joriy parol noto‘g‘ri.", "Текущий пароль неверен."), "bad")
            elif not valid_password(new):
                flash(L(*PW_HINT), "bad")
            elif new != request.form.get("new2", ""):
                flash(L("Parollar mos kelmadi.", "Пароли не совпадают."), "bad")
            else:
                u.set_password(new)
                u.must_change = False
                db.session.commit()
                session["pv"] = pw_stamp(u)  # текущий вход остаётся, остальные завершаются
                audit("password_change")
                flash(L("Parol almashtirildi.", "Пароль изменён."), "ok")
                return redirect(home_for(u))
        return redirect(url_for("auth.account"))
    return render_template("auth/account.html")


@bp.route("/forgot", methods=["GET", "POST"])
def forgot():
    if request.method == "POST":
        ident = request.form.get("ident", "").strip().lower()[:120]
        key = f"forgot|{request.remote_addr}"
        if not throttled(key, 5, 900) and ident:
            fail_attempt(key)
            u = User.query.filter(db.or_(func.lower(User.username) == ident,
                                         func.lower(User.email) == ident)).first()
            if u and u.active:
                tok = secrets.token_urlsafe(32)
                db.session.add(PasswordReset(user_id=u.id, token_hash=hashlib.sha256(tok.encode()).hexdigest(),
                                             expires=datetime.utcnow() + timedelta(hours=1)))
                db.session.commit()
                # адрес берём из настройки, а не из заголовка Host: иначе ссылку в письме можно подменить
                base = (os.environ.get("PUBLIC_URL") or request.host_url).rstrip("/")
                link = base + url_for("auth.reset", token=tok)
                if u.email:
                    from .core import _send_email
                    import threading
                    threading.Thread(target=_send_email, daemon=True, args=(
                        u.email, "Qalqon: parolni tiklash / Восстановление пароля",
                        f"Parolni tiklash havolasi (1 soat) / Ссылка для сброса пароля (1 час):\n{link}")).start()
                notify(admins(), "reset", f"Parolni tiklash so‘rovi: {u.username} ({u.full_name})",
                       f"Запрос на восстановление пароля: {u.username} ({u.full_name})", "/admin/users")
                db.session.commit()
                audit("password_reset_request", u.username, user=u)
        flash(L("Agar hisob topilsa, ko‘rsatmalar yuborildi (email yoki administrator orqali).",
                "Если учётная запись найдена, инструкции отправлены (на email или через администратора)."), "ok")
        return redirect(url_for("auth.login"))
    return render_template("auth/forgot.html")


@bp.route("/reset/<token>", methods=["GET", "POST"])
def reset(token):
    h = hashlib.sha256(token.encode()).hexdigest()
    pr = PasswordReset.query.filter_by(token_hash=h, used=False).first()
    if not pr or pr.expires < datetime.utcnow():
        flash(L("Havola yaroqsiz yoki muddati o‘tgan.", "Ссылка недействительна или устарела."), "bad")
        return redirect(url_for("auth.forgot"))
    if request.method == "POST":
        new = request.form.get("new", "")
        if not valid_password(new):
            flash(L(*PW_HINT), "bad")
        elif new != request.form.get("new2", ""):
            flash(L("Parollar mos kelmadi.", "Пароли не совпадают."), "bad")
        else:
            pr.user.set_password(new)
            pr.user.must_change = False
            pr.used = True
            db.session.commit()
            audit("password_reset_done", pr.user.username, user=pr.user)
            flash(L("Parol yangilandi. Kiring.", "Пароль обновлён. Войдите."), "ok")
            return redirect(url_for("auth.login"))
    return render_template("auth/reset.html", token=token)


# ───────── уведомления ─────────
@bp.route("/notifications")
@login_required
def notifications():
    items = Notification.query.filter_by(user_id=g.user.id).order_by(Notification.created.desc()).limit(100).all()
    return render_template("auth/notifications.html", items=items)


@bp.route("/notifications/go/<int:nid>")
@login_required
def notif_go(nid):
    n = Notification.query.filter_by(id=nid, user_id=g.user.id).first_or_404()
    n.read = True
    db.session.commit()
    return redirect(n.link if n.link.startswith("/") else "/notifications")


@bp.route("/notifications/read-all", methods=["POST"])
@login_required
def notif_all():
    Notification.query.filter_by(user_id=g.user.id, read=False).update({"read": True})
    db.session.commit()
    return redirect(url_for("auth.notifications"))


# ───────── сообщения ─────────
def recipients(u):
    """Кому пользователь может писать: список (User, Student|None)."""
    out = []
    if u.role == "teacher":
        for st in my_students(u):
            for p in st.parents:
                out.append((p, st))
    elif u.role == "parent":
        seen = set()
        for st in u.children:
            if st.class_id:
                ids = {a.teacher_id for a in Assignment.query.filter_by(class_id=st.class_id)}
                c = db.session.get(SchoolClass, st.class_id)
                if c and c.teacher_id:
                    ids.add(c.teacher_id)
                for t in User.query.filter(User.id.in_(ids or [0]), User.active == True):
                    out.append((t, st))
        for a in admins():
            out.append((a, None))
    elif u.role == "admin":
        for x in User.query.filter(User.role.in_(["parent", "teacher"]), User.active == True).order_by(User.full_name):
            out.append((x, None))
    return out


@bp.route("/messages", methods=["GET", "POST"])
@login_required
def messages():
    u = g.user
    if request.method == "POST":
        try:
            rid = int(request.form.get("rcpt", "0"))
            sid = int(request.form.get("student") or 0)
        except ValueError:
            abort(400)
        ok = [(r.id, s.id if s else 0) for r, s in recipients(u)]
        body = request.form.get("body", "").strip()
        if (rid, sid) not in ok and (rid, 0) not in ok:
            audit("denied", f"message to {rid}")
            abort(403)
        if not body:
            flash(L("Xabar matni bo‘sh.", "Пустое сообщение."), "bad")
            return redirect(url_for("auth.messages"))
        m = Message(sender_id=u.id, rcpt_id=rid, student_id=sid or None,
                    subject=request.form.get("subject", "").strip()[:200], body=body[:4000])
        db.session.add(m)
        notify(db.session.get(User, rid), "message", f"Yangi xabar: {u.full_name}",
               f"Новое сообщение: {u.full_name}", "/messages")
        db.session.commit()
        audit("message_send", f"to={rid}")
        flash(L("Xabar yuborildi.", "Сообщение отправлено."), "ok")
        return redirect(url_for("auth.messages", tab="sent"))
    tab = request.args.get("tab", "in")
    q = Message.query.filter(Message.sender_id == u.id if tab == "sent" else Message.rcpt_id == u.id)
    msgs = q.order_by(Message.created.desc()).limit(100).all()
    if tab != "sent":
        for m in msgs:
            m.read = True
        db.session.commit()
    rcpts = recipients(u) if u.role != "student" else []
    pre = request.args.get("to", "")
    return render_template("auth/messages.html", msgs=msgs, tab=tab, rcpts=rcpts, pre=pre)


# ───────── файлы ─────────
@bp.route("/file/<int:fid>")
def file(fid):
    f = db.session.get(File, fid)
    if not f or not can_view_file(g.user, f):
        abort(404 if f is None else 403)
    inline = f.mime in ("application/pdf", "image/jpeg", "image/png", "image/webp")
    r = Response(f.data, mimetype=f.mime)
    r.headers["Content-Disposition"] = f"{'inline' if inline else 'attachment'}; filename*=UTF-8''{urllib.parse.quote(f.name)}"
    r.headers["Cache-Control"] = "public, max-age=86400" if f.owner_type == "pub" else "private, no-store"
    if f.mime != "application/pdf":
        r.headers["Content-Security-Policy"] = "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:"
    if f.owner_type in ("app", "sub"):
        audit("file_view", f"{f.owner_type}:{f.id}")
    return r
