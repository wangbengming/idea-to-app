#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""管理后台骨架（方案 E：本地服务 + SQLite）——开发工程师以此为基础扩展。

双击 启动.bat 即用（bat 内容放在应用文件夹，同 app.py 一起交付）：
    @echo off
    chcp 65001 >nul
    cd /d "%~dp0"
    python app.py
    pause

已内置（扩展时不要删减）：
  - 登录 / 退出 / 修改密码；密码 pbkdf2 加盐哈希，绝不存明文
  - 会话（HttpOnly Cookie，内存级：重启服务需重新登录，单机场景够用）
  - 按角色的服务端权限校验（route(roles=...)），不是只靠界面藏菜单
  - 示例实体"条目"的增删改查 + 搜索 + 分页；用户管理（仅管理员）
  - "备份数据"：把 data.db 复制到 backups/（界面按钮 + /backup 路由）

约束与边界（写代码前读一遍 03-技术方案）：
  - 界面与文案全部中文；样式可直接改，但结构（校验点/备份）保留
  - 仅限本机或可信内网使用：未做 HTTPS 与 CSRF 防护，不能暴露到公网
  - 不引任何第三方库、不引 CDN 外链；新页面照 _page() + route() 的既有模式加
"""
import hashlib
import html
import http.cookies
import http.server
import secrets
import shutil
import sqlite3
import sys
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlparse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

APP_DIR = Path(__file__).resolve().parent
DB_FILE = APP_DIR / "data.db"
BACKUP_DIR = APP_DIR / "backups"
HOST = "127.0.0.1"  # 仅本机访问；要让同一 WiFi 的手机/电脑访问，改成 "0.0.0.0"（安全性自担）
PORT_START = 8000
SESSION_HOURS = 8
PAGE_SIZE = 10

# ---------- 数据库 ----------

def db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    first = not DB_FILE.exists()
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            pw_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'staff')""")
        conn.execute("""CREATE TABLE IF NOT EXISTS items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            note TEXT DEFAULT '',
            created_by TEXT,
            created_at TEXT)""")
    admin_pw = ""
    if first:
        admin_pw = secrets.token_hex(4)
        with db() as conn:
            conn.execute("INSERT INTO users(username, pw_hash, role) VALUES(?,?,?)",
                         ("admin", hash_password(admin_pw), "admin"))
    return first, admin_pw


def hash_password(pw: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), bytes.fromhex(salt), 100_000).hex()
    return f"{salt}${h}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        salt, h = stored.split("$", 1)
    except ValueError:
        return False
    calc = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), bytes.fromhex(salt), 100_000).hex()
    return secrets.compare_digest(calc, h)


# ---------- 会话（内存级；重启服务即全部失效，用户重新登录即可） ----------

SESSIONS = {}  # token -> {"username": str, "expire": float}


def session_get(token):
    s = SESSIONS.get(token)
    if not s:
        return None
    if s["expire"] < time.time():
        SESSIONS.pop(token, None)
        return None
    return s


def session_user(token):
    s = session_get(token)
    if not s:
        return None
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE username=?", (s["username"],)).fetchone()
    return row


def session_create(username):
    token = secrets.token_hex(16)
    SESSIONS[token] = {"username": username, "expire": time.time() + SESSION_HOURS * 3600}
    return token


# ---------- 请求对象与路由表 ----------

class Req:
    def __init__(self, handler):
        u = urlparse(handler.path)
        self.path = u.path
        self.query = {k: v[0] for k, v in parse_qs(u.query).items()}
        length = int(handler.headers.get("Content-Length") or 0)
        body = handler.rfile.read(length).decode("utf-8", errors="replace") if length else ""
        self.form = {k: v[0] for k, v in parse_qs(body).items()}
        cookie = http.cookies.SimpleCookie(handler.headers.get("Cookie", ""))
        self.token = cookie["sid"].value if "sid" in cookie else None
        self.user = session_user(self.token) if self.token else None

    @property
    def role(self):
        return self.user["role"] if self.user else None


ROUTES = {}


def route(method, path, roles=None):
    """roles=None 任意登录用户可用；roles=("admin",) 仅指定角色；登录页本身用 public=True。"""
    def deco(fn):
        ROUTES[(method, path)] = (fn, roles)
        return fn
    return deco


# ---------- 页面骨架（样式可改，结构保留） ----------

def _page(title, body, user=None, msg=""):
    nav_admin = '<a href="/users">用户管理</a>' if user and user["role"] == "admin" else ""
    msg_html = f'<div class="msg">{html.escape(msg)}</div>' if msg else ""
    who = f'<span class="who">{html.escape(user["username"])}（{"管理员" if user["role"]=="admin" else "员工"}）</span>' if user else ""
    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
*{{box-sizing:border-box}} body{{margin:0;font-family:system-ui,"Microsoft YaHei",sans-serif;background:#f5f6f8;color:#222}}
.wrap{{display:flex;min-height:100vh}}
.side{{width:200px;background:#1f2937;color:#cbd5e1;padding:18px 0;flex-shrink:0}}
.side a{{display:block;color:#cbd5e1;text-decoration:none;padding:12px 20px;font-size:15px}}
.side a:hover{{background:#374151;color:#fff}}
.main{{flex:1;padding:24px;max-width:960px}}
h1{{font-size:22px;margin:0 0 16px}}
.btn{{display:inline-block;background:#2563eb;color:#fff;border:0;border-radius:8px;padding:10px 18px;font-size:15px;cursor:pointer;text-decoration:none}}
.btn.red{{background:#dc2626}} .btn.gray{{background:#6b7280}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
th,td{{padding:10px 12px;text-align:left;border-bottom:1px solid #eee;font-size:14px}}
tr:hover td{{background:#f0f6ff}}
.msg{{background:#dcfce7;border:1px solid #86efac;color:#166534;padding:10px 14px;border-radius:8px;margin-bottom:14px}}
.card{{background:#fff;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.08);padding:20px;margin-bottom:16px}}
input,select{{padding:9px 10px;border:1px solid #cbd5e1;border-radius:6px;font-size:15px;width:100%;max-width:360px}}
label{{display:block;margin:12px 0 4px;font-size:14px}}
.pages a,.pages span{{margin-right:8px;text-decoration:none;color:#2563eb}}
.who{{margin-left:8px;color:#94a3b8;font-size:13px}}
@media(max-width:640px){{.wrap{{flex-direction:column}}.side{{width:100%;padding:6px 0}}.side a{{display:inline-block;padding:10px 14px}}.main{{padding:14px}}}}
</style></head><body>
<div class="wrap"><div class="side">
<a href="/">工作台</a><a href="/items">内容管理</a>{nav_admin}
<a href="/password">修改密码</a>
<form method="post" action="/backup" style="display:inline"><button class="btn gray" style="width:100%;text-align:left">备份数据</button></form>
<a href="/logout">退出登录</a></div>
<div class="main">{msg_html}{body}</div></div></body></html>"""


def _login_page(msg="", username=""):
    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>登录</title><style>
body{{font-family:system-ui,"Microsoft YaHei",sans-serif;background:#f5f6f8;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}}
.box{{background:#fff;padding:32px;border-radius:12px;box-shadow:0 2px 12px rgba(0,0,0,.1);width:320px}}
h1{{font-size:20px;margin:0 0 16px;text-align:center}}
input{{width:100%;padding:10px;margin:6px 0 12px;border:1px solid #cbd5e1;border-radius:6px;font-size:15px}}
button{{width:100%;padding:11px;background:#2563eb;color:#fff;border:0;border-radius:8px;font-size:15px;cursor:pointer}}
.err{{background:#fee2e2;color:#991b1b;padding:8px 12px;border-radius:6px;font-size:14px;margin-bottom:10px}}
</style></head><body><div class="box"><h1>管理后台登录</h1>
{f'<div class="err">{html.escape(msg)}</div>' if msg else ''}
<form method="post" action="/login">
<input name="username" placeholder="账号" value="{html.escape(username)}" required>
<input name="password" type="password" placeholder="密码" required>
<button>登 录</button></form></div></body></html>"""


def _deny(req):
    return 403, _page("无权限", '<div class="card">你的账号没有权限使用这个功能。如需开通，请联系管理员。</div>', req.user), []


# ---------- 登录 / 账号 ----------

@route("GET", "/login", roles="public")
def login_page(req):
    if req.user:
        return redirect("/")
    return 200, _login_page(req.query.get("msg", ""), req.query.get("u", ""))


@route("POST", "/login", roles="public")
def login_post(req):
    username = req.form.get("username", "").strip()
    password = req.form.get("password", "")
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if row and verify_password(password, row["pw_hash"]):
        token = session_create(username)
        return 302, "", [("Location", "/"), ("Set-Cookie", f"sid={token}; HttpOnly; Path=/")]
    return 302, "", [("Location", "/login?" + urlencode({"msg": "账号或密码不对，再试一次", "u": username}))]


@route("GET", "/logout")
def logout(req):
    SESSIONS.pop(req.token, None)
    return 302, "", [("Location", "/login"), ("Set-Cookie", "sid=; HttpOnly; Path=/; Max-Age=0")]


@route("GET", "/password")
def password_page(req):
    return 200, _page("修改密码", """<div class="card"><h1>修改密码</h1>
<form method="post" action="/password">
<label>当前密码</label><input name="old" type="password" required>
<label>新密码（至少 6 位）</label><input name="new" type="password" required minlength="6">
<label>再输一遍新密码</label><input name="new2" type="password" required>
<p><button class="btn">保存新密码</button></p></form></div>""", req.user)


@route("POST", "/password")
def password_post(req):
    old, new, new2 = (req.form.get(k, "") for k in ("old", "new", "new2"))
    if not verify_password(old, req.user["pw_hash"]):
        return redirect("/password")
    if len(new) < 6 or new != new2:
        return redirect("/password")
    with db() as conn:
        conn.execute("UPDATE users SET pw_hash=? WHERE id=?", (hash_password(new), req.user["id"]))
    return redirect("/?msg=密码已修改")


@route("GET", "/users", roles=("admin",))
def users_page(req):
    with db() as conn:
        rows = conn.execute("SELECT id, username, role FROM users ORDER BY id").fetchall()
    trs = []
    for r in rows:
        if r["username"] == req.user["username"]:
            action = "（当前账号）"
        else:
            action = ('<form method="post" action="/users/del" style="display:inline">'
                      f'<input type="hidden" name="id" value="{r["id"]}">'
                      '<button class="btn red">删除</button></form>')
        trs.append(f"<tr><td>{html.escape(r['username'])}</td>"
                   f"<td>{'管理员' if r['role'] == 'admin' else '员工'}</td>"
                   f"<td>{action}</td></tr>")
    return 200, _page("用户管理", f"""<div class="card"><h1>用户管理</h1>
<table><tr><th>账号</th><th>角色</th><th>操作</th></tr>{''.join(trs)}</table></div>
<div class="card"><h1>新增用户</h1><form method="post" action="/users/add">
<label>账号</label><input name="username" required>
<label>初始密码（至少 6 位）</label><input name="password" required minlength="6">
<label>角色</label><select name="role"><option value="staff">员工</option><option value="admin">管理员</option></select>
<p><button class="btn">新增</button></p></form></div>""", req.user)


@route("POST", "/users/add", roles=("admin",))
def users_add(req):
    username = req.form.get("username", "").strip()
    password = req.form.get("password", "")
    role = req.form.get("role", "staff")
    if not username or len(password) < 6 or role not in ("admin", "staff"):
        return redirect("/users")
    try:
        with db() as conn:
            conn.execute("INSERT INTO users(username, pw_hash, role) VALUES(?,?,?)",
                         (username, hash_password(password), role))
    except sqlite3.IntegrityError:
        return redirect("/users")
    return redirect("/users")


@route("POST", "/users/del", roles=("admin",))
def users_del(req):
    try:
        uid = int(req.form.get("id", "0"))
    except ValueError:
        uid = 0
    with db() as conn:
        row = conn.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone()
        if row and row["username"] != req.user["username"]:
            conn.execute("DELETE FROM users WHERE id=?", (uid,))
    return redirect("/users")


# ---------- 示例实体：条目（增删改查 + 搜索 + 分页），照这个模式加新实体 ----------

@route("GET", "/")
def dashboard(req):
    with db() as conn:
        n_items = conn.execute("SELECT COUNT(*) c FROM items").fetchone()["c"]
        n_users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    return 200, _page("工作台", f"""<h1>工作台</h1>
<div class="card">已录入条目：<b>{n_items}</b> 条　|　账号：<b>{n_users}</b> 个</div>
<div class="card"><a class="btn" href="/items/new">新增一条</a> <a class="btn gray" href="/items">查看全部</a></div>""",
                      req.user, req.query.get("msg", ""))


@route("GET", "/items")
def items_page(req):
    q = req.query.get("q", "").strip()
    try:
        page = max(1, int(req.query.get("page", "1")))
    except ValueError:
        page = 1
    where, params = ("WHERE title LIKE ?", [f"%{q}%"]) if q else ("", [])
    with db() as conn:
        total = conn.execute(f"SELECT COUNT(*) c FROM items {where}", params).fetchone()["c"]
        rows = conn.execute(f"SELECT * FROM items {where} ORDER BY id DESC LIMIT ? OFFSET ?",
                            params + [PAGE_SIZE, (page - 1) * PAGE_SIZE]).fetchall()
    pages = max(1, -(-total // PAGE_SIZE))
    pager = ""
    if pages > 1:
        links = []
        for i in range(1, pages + 1):
            href = "/items?" + urlencode({"q": q, "page": i})
            links.append(f'<a href="{href}">{i}</a>' if i != page else f"<span><b>{i}</b></span>")
        pager = '<div class="pages">' + " ".join(links) + "</div>"
    trs = "".join(
        f"<tr><td>{html.escape(r['title'])}</td><td>{html.escape(r['note'] or '')}</td>"
        f"<td>{html.escape(r['created_at'] or '')}</td>"
        f"<td><a href='/items/edit?id={r['id']}'>改</a> "
        f"<form method=post action=/items/del style='display:inline'>"
        f"<input type=hidden name=id value={r['id']}>"
        f"<button class='btn red'>删</button></form></td></tr>"
        for r in rows)
    empty = '<p>还没有数据，点右上角"新增一条"开始记录。</p>' if not rows else ""
    return 200, _page("内容管理", f"""<h1>内容管理</h1>
<form method="get" action="/items" style="margin-bottom:12px;display:flex;gap:8px">
<input name="q" placeholder="搜标题…" value="{html.escape(q)}" style="max-width:240px"><button class="btn gray">搜索</button>
<a class="btn" href="/items/new" style="margin-left:auto">新增一条</a></form>
{empty}<table><tr><th>标题</th><th>备注</th><th>时间</th><th>操作</th></tr>{trs}</table>{pager}""",
                      req.user, req.query.get("msg", ""))


@route("GET", "/items/new")
def item_new(req):
    return 200, _page("新增", """<div class="card"><h1>新增条目</h1>
<form method="post" action="/items/new">
<label>标题（必填）</label><input name="title" required>
<label>备注</label><input name="note">
<p><button class="btn">保存</button> <a class="btn gray" href="/items">取消</a></p></form></div>""", req.user)


@route("POST", "/items/new")
def item_new_post(req):
    title = req.form.get("title", "").strip()
    if not title:
        return redirect("/items/new")
    with db() as conn:
        conn.execute("INSERT INTO items(title, note, created_by, created_at) VALUES(?,?,?,?)",
                     (title, req.form.get("note", "").strip(), req.user["username"],
                      time.strftime("%Y-%m-%d %H:%M")))
    return redirect("/items?msg=已新增一条")


@route("GET", "/items/edit")
def item_edit(req):
    try:
        iid = int(req.query.get("id", "0"))
    except ValueError:
        return _deny(req)
    with db() as conn:
        r = conn.execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()
    if not r:
        return _deny(req)
    return 200, _page("修改", f"""<div class="card"><h1>修改条目</h1>
<form method="post" action="/items/edit">
<input type="hidden" name="id" value="{r['id']}">
<label>标题</label><input name="title" value="{html.escape(r['title'])}" required>
<label>备注</label><input name="note" value="{html.escape(r['note'] or '')}">
<p><button class="btn">保存</button> <a class="btn gray" href="/items">取消</a></p></form></div>""", req.user)


@route("POST", "/items/edit")
def item_edit_post(req):
    try:
        iid = int(req.form.get("id", "0"))
    except ValueError:
        return _deny(req)
    title = req.form.get("title", "").strip()
    if not title:
        return redirect("/items")
    with db() as conn:
        conn.execute("UPDATE items SET title=?, note=? WHERE id=?",
                     (title, req.form.get("note", "").strip(), iid))
    return redirect("/items?msg=已保存修改")


@route("POST", "/items/del", roles=("admin",))
def item_del(req):
    """演示：删除仅管理员可执行（服务端校验，员工账号直接 POST 也会被拒）。"""
    try:
        iid = int(req.form.get("id", "0"))
    except ValueError:
        return _deny(req)
    with db() as conn:
        conn.execute("DELETE FROM items WHERE id=?", (iid,))
    return redirect("/items?msg=已删除")


# ---------- 备份 ----------

@route("POST", "/backup")
def backup(req):
    BACKUP_DIR.mkdir(exist_ok=True)
    dest = BACKUP_DIR / f"data-{time.strftime('%Y%m%d-%H%M%S')}.db"
    shutil.copy2(DB_FILE, dest)
    return redirect("/?msg=已备份到 backups 文件夹：" + dest.name)


# ---------- HTTP 服务 ----------

def redirect(loc):
    """Location 头只允许 ASCII，中文提示必须 URL 编码（浏览器会自动解码显示）。"""
    return 302, "", [("Location", quote(loc, safe="/?&=%+"))]


class Handler(http.server.BaseHTTPRequestHandler):
    def _handle(self):
        req = Req(self)
        entry = ROUTES.get((self.command, req.path))
        if not entry:
            body = _page("页面不存在", '<div class="card">页面不存在，<a href="/">回工作台</a>。</div>', req.user)
            self._send(404, body, [])
            return
        fn, roles = entry
        if roles != "public" and req.user is None:
            self._send(*redirect("/login"))
            return
        if isinstance(roles, tuple) and req.role not in roles:
            status, body, _ = _deny(req)
            self._send(status, body, [])
            return
        result = fn(req)
        if len(result) == 2:  # 处理器可返回 (status, body) 或 (status, body, headers)
            status, body, extra = result[0], result[1], []
        else:
            status, body, extra = result
        self._send(status, body, extra)

    def _send(self, status, body, extra_headers):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        for k, v in extra_headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        try:
            self._handle()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        self.do_GET()

    def log_message(self, *args):
        pass


def find_port():
    import socket
    for port in range(PORT_START, PORT_START + 20):
        with socket.socket() as s:
            try:
                s.bind((HOST, port))
                return port
            except OSError:
                continue
    return PORT_START


def main():
    first, admin_pw = init_db()
    port = find_port()
    url = f"http://{'localhost' if HOST == '127.0.0.1' else HOST}:{port}"
    print("=" * 46)
    print(" 后台系统已启动！")
    print(f" 浏览器打开：{url}（应该已自动打开）")
    if first:
        print(f" 管理员账号：admin    初始密码：{admin_pw}")
        print(" ★ 请登录后立刻点左侧「修改密码」换掉初始密码")
    else:
        print(" 账号密码是你之前设置的那个")
    print(f" 数据保存在：{DB_FILE.name}（复制它就是备份）")
    print(" 关闭本窗口 = 关闭系统")
    print("=" * 46)
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    server = http.server.ThreadingHTTPServer((HOST, port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已关闭。")


if __name__ == "__main__":
    main()
