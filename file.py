# Запуск:  python -m uvicorn file:app --host 127.0.0.1 --port 8000 --reload
import csv
import hashlib
import logging
import os
import re
import secrets
import time

from fastapi import FastAPI, Form, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.middleware.sessions import SessionMiddleware

# ---------- настройки ----------
USERS_FILE = 'users.csv'            # name, email (логин), password (хэш), role, avatar (путь к аватару)
DATA_FILE = 'data.csv'              # каталог предметов
LOG_FILE = 'logs'                   # журнал действий
SESSION_TIMEOUT = 300            # 5 минут без действий
IMAGES_DIR = 'static/items'
AVATARS_DIR = 'static/avatars'

USER_FIELDS = ['name', 'email', 'password', 'role', 'avatar']
ITEM_FIELDS = ['id', 'category', 'name', 'specs', 'description', 'image']

CATEGORIES = {'Оружие': '🔫', 'Броня': '🛡️', 'Обвесы': '💄', 'Техника': '🚜', 'Снаряжение': '🎒'}
ROLES = {'admin': 'Главнокомандующая 👑', 'reader': 'Рядовая блёстка 🎀'}

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8'), logging.StreamHandler()]
)

# ---------- приложение ----------
app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=secrets.token_hex(32), max_age=SESSION_TIMEOUT)
os.makedirs(IMAGES_DIR, exist_ok=True)
os.makedirs(AVATARS_DIR, exist_ok=True)
app.mount('/static', StaticFiles(directory='static'), name='static')
templates = Jinja2Templates(directory='templates')


@app.middleware('http')
async def log_requests(request: Request, call_next):
    # пишем в журнал каждый переход и действие: кто, что и чем закончилось
    response = await call_next(request)
    if not request.url.path.startswith('/static'):
        who = getattr(request.state, 'email', 'аноним')
        logging.info(f'{who} | {request.method} {request.url.path} | {response.status_code}')
        if response.headers.get('content-type', '').startswith('text/html'):
            response.headers['Cache-Control'] = 'no-store'
    return response


# ---------- csv-файлы ----------
def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def write_csv(path, fields, rows):
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def read_users():
    users = read_csv(USERS_FILE)
    for u in users:
        u['role'] = u.get('role') or 'reader'
        u['avatar'] = u.get('avatar') or ''
    return users


def find_user(email):
    for u in read_users():
        if u['email'] == email:
            return u
    return None


def read_items():
    items = read_csv(DATA_FILE)
    for i in items:
        for field in ITEM_FIELDS:
            i[field] = i.get(field) or ''
        # "Калибр, мм: 17|Масса, кг: 3,6" -> [("Калибр, мм", "17"), ("Масса, кг", "3,6")]
        i['spec_rows'] = [tuple(p.split(':', 1)) if ':' in p else ('', p) for p in i['specs'].split('|') if p.strip()]
        i['spec_rows'] = [(a.strip(), b.strip()) for a, b in i['spec_rows']]
    return items


# ---------- пароли ----------
def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(8)
    return salt + '$' + hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100_000).hex()


def check_password(password, saved):
    return secrets.compare_digest(hash_password(password, saved.split('$')[0]), saved)


def check_register(name, email, password, confirm):
    if not 2 <= len(name) <= 50:
        return 'Имя: от 2 до 50 символов'
    if len(email) > 100 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        return 'Некорректный email'
    if not 8 <= len(password) <= 64:
        return 'Пароль: от 8 до 64 символов'
    if not re.search(r'[A-Za-zА-Яа-яЁё]', password) or not re.search(r'\d', password):
        return 'В пароле нужны хотя бы одна буква и одна цифра'
    if password != confirm:
        return 'Пароли не совпадают'
    if find_user(email):
        return 'Такой email уже зарегистрирован'
    return None


# ---------- сессии ----------
sessions = {}       # номер сессии -> [email, время последнего действия]


def get_user(request):
    # возвращает вошедшего пользователя или None (если не входил или сессия просрочена)
    sid = request.session.get('sid')
    s = sessions.get(sid)
    if s is None:
        return None
    if time.time() - s[1] > SESSION_TIMEOUT:
        del sessions[sid]
        request.session.clear()
        request.state.expired = True
        logging.info(f'Сессия истекла (5 минут без действий) | email={s[0]}')
        return None
    s[1] = time.time()                  # любое действие продлевает сессию
    request.state.email = s[0]
    return find_user(s[0])


def access(request, admin=False):
    # пускает только вошедших (а если admin=True - только админов), иначе ошибка 401 / 403
    user = get_user(request)
    if user is None:
        raise HTTPException(status_code=401)
    if admin and user['role'] != 'admin':
        logging.warning(f'Попытка без прав | email={user["email"]} | {request.method} {request.url.path}')
        raise HTTPException(status_code=403)
    return user


def flash(request, text):
    request.session['flash'] = text


# ---------- страницы ошибок ----------
@app.exception_handler(401)
async def error_401(request: Request, exc):
    # не вошла или сессия кончилась - отправляем на страницу входа
    expired = getattr(request.state, 'expired', False)
    return RedirectResponse(url='/login?expired=1' if expired else '/login?need=1', status_code=303)


@app.exception_handler(403)
async def error_403(request: Request, exc):
    return templates.TemplateResponse(request=request, name='403.html', status_code=403)


@app.exception_handler(404)
async def error_404(request: Request, exc):
    return templates.TemplateResponse(request=request, name='404.html', status_code=404)


@app.get('/403', response_class=HTMLResponse)
def page_403(request: Request):
    return templates.TemplateResponse(request=request, name='403.html', status_code=403)


@app.get('/404', response_class=HTMLResponse)
def page_404(request: Request):
    return templates.TemplateResponse(request=request, name='404.html', status_code=404)


# ---------- главная (каталог) ----------
@app.get('/', response_class=HTMLResponse)
@app.get('/home', response_class=HTMLResponse)
def home(request: Request):
    user = access(request)
    items = read_items()
    counts = {c: len([i for i in items if i['category'] == c]) for c in CATEGORIES}
    return templates.TemplateResponse(request=request, name='home.html', context={
        'user': user, 'username': user['name'], 'items': items, 'total': len(items),
        'counts': counts, 'categories': CATEGORIES})


# ---------- регистрация, вход, выход ----------
@app.get('/register', response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse(request=request, name='register.html')


@app.post('/register')
def register(request: Request, name: str = Form(...), email: str = Form(...),
                password: str = Form(...), confirm: str = Form(...)):
    name = name.strip()
    email = email.strip().lower()
    error = check_register(name, email, password, confirm)
    if error:
        return templates.TemplateResponse(request=request, name='register.html', status_code=400,
                                            context={'error': error, 'name': name, 'email': email})
    users = read_users()
    role = 'reader' if users else 'admin'        # первая зарегистрированная - админ
    users.append({'name': name, 'email': email, 'password': hash_password(password), 'role': role, 'avatar': ''})
    write_csv(USERS_FILE, USER_FIELDS, users)
    logging.info(f'Регистрация | email={email} | role={role}')
    return RedirectResponse(url='/login?registered=1', status_code=303)


@app.get('/login', response_class=HTMLResponse)
def login_page(request: Request, registered: str = None, need: str = None,
                expired: str = None, loggedout: str = None):
    notice = None
    if registered:
        notice = 'Аккаунт создан, теперь войди 💖'
    if need:
        notice = 'Сюда пускают только по розовому пропуску. Войди, пожалуйста 🎀'
    if expired:
        notice = 'Ты долго молчала (5 минут), и охрана закрыла сессию. Войди снова 💅'
    if loggedout:
        notice = 'Ты вышла из штаба. Возвращайся скорее 💖'
    return templates.TemplateResponse(request=request, name='login.html', context={'notice': notice})


@app.post('/login')
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    user = find_user(username.strip().lower())
    if user is None or not check_password(password, user['password']):
        logging.warning(f'Неудачный вход | email={username!r}')
        return templates.TemplateResponse(request=request, name='login.html', status_code=400,
                                            context={'error': 'Неверный email или пароль'})
    sid = secrets.token_hex(16)
    sessions[sid] = [user['email'], time.time()]
    request.session.clear()
    request.session['sid'] = sid
    request.state.email = user['email']
    logging.info(f'Вход | email={user["email"]} | role={user["role"]}')
    return RedirectResponse(url='/home', status_code=303)


@app.get('/logout')
def logout(request: Request):
    user = get_user(request)
    if user:
        logging.info(f'Выход | email={user["email"]}')
    sessions.pop(request.session.get('sid'), None)
    request.session.clear()
    return RedirectResponse(url='/login?loggedout=1', status_code=303)


# ---------- профиль и аватар ----------
def save_image(file, folder):
    # None - файл не выбран, ValueError - файл плохой, иначе имя сохранённого файла
    if not file or not getattr(file, 'filename', None):
        return None
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ('.png', '.jpg', '.jpeg', '.gif', '.webp'):
        raise ValueError('Нужна картинка: png, jpg, gif или webp')
    name = secrets.token_hex(8) + ext
    with open(os.path.join(folder, name), 'wb') as f:
        f.write(file.file.read())
    return name


def show_profile(request, user, message=None, status=200):
    return templates.TemplateResponse(request=request, name='profile.html', status_code=status, context={
        'user': user, 'role_label': ROLES[user['role']],
        'message': message or request.session.pop('flash', None)})


@app.get('/profile', response_class=HTMLResponse)
def profile(request: Request):
    return show_profile(request, access(request))


@app.post('/profile/avatar')
async def update_avatar(request: Request):
    user = access(request)
    form = await request.form()         # форму читаем сами, чтобы пустой выбор файла не давал ошибку 422
    try:
        name = save_image(form.get('file'), AVATARS_DIR)
    except ValueError as e:
        return show_profile(request, user, str(e), 400)
    if name is None:
        return show_profile(request, user, 'Файл не выбран', 400)

    users = read_users()
    for u in users:
        if u['email'] == user['email']:
            u['avatar'] = AVATARS_DIR + '/' + name
    write_csv(USERS_FILE, USER_FIELDS, users)
    logging.info(f'Аватар обновлён | email={user["email"]}')
    flash(request, 'Фото обновлено, красотка! 📸')
    return RedirectResponse(url='/profile', status_code=303)


# ---------- редактор каталога (только админ) ----------
def read_item_form(form):
    data = {k: str(form.get(k) or '').strip() for k in ('category', 'name', 'specs', 'description')}
    error = None
    if data['category'] not in CATEGORIES:
        error = 'Выбери категорию из списка'
    elif not 2 <= len(data['name']) <= 100:
        error = 'Название: от 2 до 100 символов'
    return data, error


def specs_for_csv(text):
    # строки из формы -> "строка1|строка2"
    return '|'.join(line.strip().replace('|', '/') for line in text.splitlines() if line.strip())


def show_edit(request, user, form=None, error=None, status=200):
    return templates.TemplateResponse(request=request, name='edit.html', status_code=status, context={
        'user': user, 'items': read_items(), 'users': read_users(), 'categories': CATEGORIES,
        'roles': ROLES, 'form': form or {}, 'error': error, 'message': request.session.pop('flash', None)})


def show_edit_item(request, user, item_id, form, error=None, status=200):
    return templates.TemplateResponse(request=request, name='edit_item.html', status_code=status, context={
        'user': user, 'item_id': item_id, 'form': form, 'categories': CATEGORIES, 'error': error})


@app.get('/edit', response_class=HTMLResponse)
def edit_page(request: Request):
    return show_edit(request, access(request, admin=True))


@app.post('/edit')
async def add_item(request: Request):
    user = access(request, admin=True)
    form = await request.form()
    data, error = read_item_form(form)
    image = None
    if not error:
        try:
            image = save_image(form.get('image'), IMAGES_DIR)
        except ValueError as e:
            error = str(e)
    if error:
        return show_edit(request, user, data, error, 400)

    items = read_items()
    items.append({'id': secrets.token_hex(4), 'category': data['category'], 'name': data['name'],
                'specs': specs_for_csv(data['specs']), 'description': data['description'], 'image': image or ''})
    write_csv(DATA_FILE, ITEM_FIELDS, items)
    logging.info(f'Предмет добавлен | by={user["email"]} | name={data["name"]}')
    flash(request, f'Предмет «{data["name"]}» принят на склад 💖')
    return RedirectResponse(url='/edit', status_code=303)


@app.get('/edit/{item_id}', response_class=HTMLResponse)
def edit_item_page(request: Request, item_id: str):
    user = access(request, admin=True)
    item = next((i for i in read_items() if i['id'] == item_id), None)
    if item is None:
        raise HTTPException(status_code=404)
    form = dict(item, specs=item['specs'].replace('|', '\n'))
    return show_edit_item(request, user, item_id, form)


@app.post('/edit/{item_id}/delete')
def delete_item(request: Request, item_id: str):
    user = access(request, admin=True)
    items = read_items()
    item = next((i for i in items if i['id'] == item_id), None)
    if item is None:
        raise HTTPException(status_code=404)
    write_csv(DATA_FILE, ITEM_FIELDS, [i for i in items if i['id'] != item_id])
    logging.info(f'Предмет удалён | by={user["email"]} | name={item["name"]}')
    flash(request, f'Предмет «{item["name"]}» списан со склада 🗑️')
    return RedirectResponse(url='/edit', status_code=303)


@app.post('/edit/{item_id}')
async def update_item(request: Request, item_id: str):
    user = access(request, admin=True)
    items = read_items()
    item = next((i for i in items if i['id'] == item_id), None)
    if item is None:
        raise HTTPException(status_code=404)

    form = await request.form()
    data, error = read_item_form(form)
    data['image'] = item['image']
    image = None
    if not error:
        try:
            image = save_image(form.get('image'), IMAGES_DIR)
        except ValueError as e:
            error = str(e)
    if error:
        return show_edit_item(request, user, item_id, data, error, 400)

    item.update(category=data['category'], name=data['name'], specs=specs_for_csv(data['specs']),
                description=data['description'], image=image or item['image'])
    write_csv(DATA_FILE, ITEM_FIELDS, items)
    logging.info(f'Предмет изменён | by={user["email"]} | name={data["name"]}')
    flash(request, f'Предмет «{data["name"]}» обновлён ✨')
    return RedirectResponse(url='/edit', status_code=303)
