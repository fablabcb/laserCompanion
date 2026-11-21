import os
import sqlite3
import hmac
from contextlib import closing
from datetime import datetime, timedelta

from flask import (Flask, request, render_template, redirect, url_for, flash,
                   send_from_directory, abort, jsonify, session)
from werkzeug.utils import secure_filename

from dotenv import load_dotenv
load_dotenv()                      # muss vor dem Import von config stehen

from config import Config
app = Flask(__name__)
app.config.from_object(Config)

# ---------------------------------------------------------------- Konfiguration
ALLOWED_EXTENSIONS = {'svg', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'dxf'}
MAX_HOURS = 10                     # automatischer Logout nach dieser Zeit
TS_FORMAT = "%Y-%m-%d %H:%M:%S"


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ---------------------------------------------------------------- Datenbank
def get_db():
    conn = sqlite3.connect(app.config['DB_PATH'])
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with closing(get_db()) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS laser_sessions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            login_at    TEXT NOT NULL,
            logout_at   TEXT,
            auto_logout INTEGER NOT NULL DEFAULT 0
        )""")
        cols = [r["name"] for r in db.execute("PRAGMA table_info(laser_sessions)")]
        if "auto_logout" not in cols:
            db.execute("ALTER TABLE laser_sessions "
                       "ADD COLUMN auto_logout INTEGER NOT NULL DEFAULT 0")
        db.commit()


init_db()


def now():
    return datetime.now().strftime(TS_FORMAT)


def expire_old_sessions():
    """Beendet Sitzungen, die älter als MAX_HOURS sind (Logout-Zeit = Login + MAX_HOURS)."""
    cutoff = (datetime.now() - timedelta(hours=MAX_HOURS)).strftime(TS_FORMAT)
    with closing(get_db()) as db:
        db.execute(
            """UPDATE laser_sessions
               SET logout_at = datetime(login_at, ?), auto_logout = 1
               WHERE logout_at IS NULL AND login_at <= ?""",
            (f"+{MAX_HOURS} hours", cutoff),
        )
        db.commit()


@app.before_request
def _expire_sessions():
    if request.path.startswith(("/lasercompanion", "/db-data")):
        expire_old_sessions()


def active_sessions():
    with closing(get_db()) as db:
        return db.execute(
            "SELECT * FROM laser_sessions WHERE logout_at IS NULL ORDER BY login_at"
        ).fetchall()


def my_session():
    sid = session.get("laser_session_id")
    if not sid:
        return None
    with closing(get_db()) as db:
        row = db.execute(
            "SELECT * FROM laser_sessions WHERE id = ? AND logout_at IS NULL", (sid,)
        ).fetchone()
    if row is None:
        session.pop("laser_session_id", None)
    return row


def end_session(sid):
    with closing(get_db()) as db:
        db.execute(
            "UPDATE laser_sessions SET logout_at = ? WHERE id = ? AND logout_at IS NULL",
            (now(), sid),
        )
        db.commit()


# ---------------------------------------------------------------- Dateien
def list_files():
    folder = app.config['UPLOAD_FOLDER']
    if not os.path.isdir(folder):
        return []
    files = []
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            files.append({
                'name': name,
                'size_kb': round(os.path.getsize(path) / 1024, 1),
            })
    return sorted(files, key=lambda f: f['name'].lower())


# ---------------------------------------------------------------- Routen
@app.route('/')
def guck():
    return render_template('index.html')


@app.route('/lasercompanion', methods=['GET', 'POST'])
def lasercompanion():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('Kein Datei-Teil im Request')
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            flash('Keine Datei ausgewählt')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            flash(f'Datei {filename} erfolgreich im Samba-Share gespeichert')
            return redirect(url_for('lasercompanion'))      # war: 'upload_file'
        else:
            flash('Dateityp nicht erlaubt')
            return redirect(request.url)
    return render_template(
        'laser.html',
        files=list_files(),
        me=my_session(),
        active=active_sessions(),
        vnc_url=app.config['VNC_URL'],
    )


@app.route('/download/<path:filename>')
def download(filename):
    # send_from_directory schützt vor Path-Traversal (../)
    try:
        return send_from_directory(
            app.config['UPLOAD_FOLDER'], filename, as_attachment=True
        )
    except FileNotFoundError:
        abort(404)


@app.route('/lasercompanion/start', methods=['POST'])
def laser_start():
    name = (request.form.get('name') or '').strip()[:80]
    if not name:
        return jsonify(error='Bitte Namen eingeben'), 400
    old = session.pop('laser_session_id', None)
    if old:
        end_session(old)               # offene Sitzung dieses Browsers sauber schließen
    with closing(get_db()) as db:
        cur = db.execute(
            "INSERT INTO laser_sessions (name, login_at) VALUES (?, ?)", (name, now())
        )
        db.commit()
        session['laser_session_id'] = cur.lastrowid
    return jsonify(ok=True)


@app.route('/lasercompanion/stop', methods=['POST'])
def laser_stop():
    sid = session.pop('laser_session_id', None)
    if sid:
        end_session(sid)
    return jsonify(ok=True)


@app.route('/db-data/<key>')
def db_data(key):
    expected = app.config.get('DB_DATA_KEY', '')
    if not expected or not hmac.compare_digest(key.encode(), expected.encode()):
        abort(404)                     # 404 statt 403, damit die Seite nicht auffällt
    since = (datetime.now() - timedelta(days=30)).strftime(TS_FORMAT)
    with closing(get_db()) as db:
        raw = db.execute(
            "SELECT * FROM laser_sessions WHERE login_at >= ? ORDER BY login_at DESC",
            (since,),
        ).fetchall()
    rows = []
    for r in raw:
        d = dict(r)
        end = datetime.strptime(d['logout_at'], TS_FORMAT) if d['logout_at'] else datetime.now()
        minutes = int((end - datetime.strptime(d['login_at'], TS_FORMAT)).total_seconds() // 60)
        d['dauer'] = f"{minutes // 60} h {minutes % 60:02d} min"
        rows.append(d)
    return render_template('db_data.html', rows=rows)


if __name__ == '__main__':
    # Debug nur bewusst einschalten (FLASK_DEBUG=1), nie zusammen mit host 0.0.0.0 im Netz
    app.run(host='0.0.0.0', port=5000, debug=os.environ.get('FLASK_DEBUG') == '1')