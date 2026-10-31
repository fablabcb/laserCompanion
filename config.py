import os

class Config:
    # Fehlt eine Pflichtvariable, startet die App gar nicht (KeyError), statt mit Standardwert zu laufen
    SECRET_KEY    = os.environ["FLASK_SECRET"]
    DB_DATA_KEY   = os.environ["DB_DATA_KEY"]
    VNC_URL       = os.environ["VNC_URL"]

    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "/mnt/samba/uploads")
    DB_PATH       = os.environ.get(
        "DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "laser.db")
    )