import os
from flask import Flask, request, render_template_string, render_template, redirect, url_for, flash, send_from_directory, abort
from werkzeug.utils import secure_filename

from dotenv import load_dotenv
load_dotenv()                      # liest .env, falls vorhanden (für die lokale Entwicklung)

from config import Config
app = Flask(__name__)
app.config.from_object(Config)

# Konfiguration
ALLOWED_EXTENSIONS = {'svg', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'dxf'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


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

@app.route('/')
def guck():
    return render_template('index.html')
    

@app.route('/lasercompanion', methods=['GET', 'POST'])
def lasercompanion():
    if request.method == 'POST':
        # Prüfen, ob die Datei im Request ist
        if 'file' not in request.files:
            flash('Kein Datei-Teil im Request')
            return redirect(request.url)
        file = request.files['file']
        # Wenn kein Dateiname ausgewählt wurde
        if file.filename == '':
            flash('Keine Datei ausgewählt')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            flash(f'Datei {filename} erfolgreich im Samba-Share gespeichert')
            return redirect(url_for('upload_file'))
        else:
            flash('Dateityp nicht erlaubt')
            return redirect(request.url)
    return render_template('laser.html', files=list_files())


@app.route('/download/<path:filename>')
def download(filename):
    # send_from_directory schützt vor Path-Traversal (../)
    try:
        return send_from_directory(
            UPLOAD_FOLDER, filename, as_attachment=True
        )
    except FileNotFoundError:
        abort(404)

if __name__ == '__main__':
    # host='0.0.0.0' macht die App auch von außen erreichbar
    app.run(host='0.0.0.0', port=5000, debug=True)