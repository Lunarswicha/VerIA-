"""
VeriaChain — Application Flask principale
==========================================
Lancement : python app.py
             ou : flask run

Routes :
    /              Tableau de bord
    /login         Connexion
    /register      Inscription
    /logout        Déconnexion
    /detect        Analyse d'image ou de document
    /certify       Certification blockchain
    /verify        Vérification de certificat
    /history       Historique des analyses (utilisateur connecté)
    /api/detect    API JSON – analyse d'image/document
    /api/certify   API JSON – certification
    /api/verify    API JSON – vérification
"""
import io
import os
import logging
from pathlib import Path
from datetime import datetime, timezone
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for,
                   flash, jsonify, session)
from flask_login import (LoginManager, login_user, logout_user,
                         login_required, current_user)
from werkzeug.utils import secure_filename

from config import Config
from auth.users import db, User, AnalysisLog, init_db
from detection import VeriaDetector
from certification import VeriaStamp

# ──────────────────────────────────────────────────────────────────────────────
# Initialisation
# ──────────────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config.from_object(Config)

# Ensure upload and model dirs exist
Path(app.config["UPLOAD_FOLDER"]).mkdir(exist_ok=True)
Path(app.config["MODEL_CACHE_DIR"]).mkdir(exist_ok=True)

# Database
init_db(app)

# Login manager
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Connectez-vous pour accéder à cette page."
login_manager.login_message_category = "info"

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# Detection & certification services
detector = VeriaDetector(app.config)
stamp     = VeriaStamp(app.config)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def allowed_file(filename: str, types: set) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in types

def read_file_bytes(file_storage) -> bytes:
    file_storage.seek(0)
    data = file_storage.read()
    file_storage.seek(0)
    return data


# ──────────────────────────────────────────────────────────────────────────────
# Auth routes
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user     = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            user.last_login = datetime.now(timezone.utc)
            db.session.commit()
            login_user(user, remember=request.form.get("remember") == "on")
            flash("Connexion réussie.", "success")
            return redirect(request.args.get("next") or url_for("index"))
        flash("Email ou mot de passe incorrect.", "danger")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "POST":
        name     = request.form.get("name", "").strip()
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm  = request.form.get("confirm", "")
        if not all([name, email, password]):
            flash("Tous les champs sont requis.", "danger")
        elif password != confirm:
            flash("Les mots de passe ne correspondent pas.", "danger")
        elif len(password) < 8:
            flash("Le mot de passe doit contenir au moins 8 caractères.", "danger")
        elif User.query.filter_by(email=email).first():
            flash("Un compte existe déjà avec cet email.", "danger")
        else:
            user = User(name=name, email=email)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash(f"Bienvenue, {name}.", "success")
            return redirect(url_for("index"))
    return render_template("register.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Déconnecté.", "info")
    return redirect(url_for("login"))


# ──────────────────────────────────────────────────────────────────────────────
# Main pages
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    recent = AnalysisLog.query.filter_by(user_id=current_user.id)\
                              .order_by(AnalysisLog.created_at.desc())\
                              .limit(5).all()
    return render_template("index.html", recent=recent)


@app.route("/detect", methods=["GET"])
@login_required
def detect():
    return render_template("detect.html")


@app.route("/certify", methods=["GET"])
@login_required
def certify():
    return render_template("certify.html")


@app.route("/verify", methods=["GET"])
@login_required
def verify():
    return render_template("verify.html")


@app.route("/history")
@login_required
def history():
    logs = AnalysisLog.query.filter_by(user_id=current_user.id)\
                            .order_by(AnalysisLog.created_at.desc())\
                            .limit(50).all()
    return render_template("history.html", logs=logs)


# ──────────────────────────────────────────────────────────────────────────────
# API — Detection
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/detect", methods=["POST"])
@login_required
def api_detect():
    if "file" not in request.files:
        return jsonify({"error": "Aucun fichier fourni."}), 400

    f         = request.files["file"]
    filename  = secure_filename(f.filename or "upload")
    ext       = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    all_ext   = app.config["ALLOWED_IMAGE_EXT"] | app.config["ALLOWED_DOC_EXT"]

    if not allowed_file(filename, all_ext):
        return jsonify({"error": f"Format non supporté : .{ext}"}), 400

    file_bytes = read_file_bytes(f)

    try:
        if ext in app.config["ALLOWED_IMAGE_EXT"]:
            result = detector.analyze_image(file_bytes, filename)
            data   = {
                "type":           "image",
                "filename":        filename,
                "ai_probability":  result.ai_probability,
                "ai_pct":          round(result.ai_probability * 100, 1),
                "confidence":      result.confidence,
                "label":           result.label,
                "label_en":        result.label_en,
                "model_score":     result.model_score,
                "freq_score":      result.freq_score,
                "sha256":          result.sha256,
                "resolution":      result.resolution,
                "file_size_kb":    result.file_size_kb,
                "metrics": {
                    "fft_energy_ratio": round(result.metrics.fft_energy_ratio, 3),
                    "edge_sharpness":   round(result.metrics.edge_sharpness, 3),
                    "color_entropy":    round(result.metrics.color_entropy, 3),
                    "local_variance":   round(result.metrics.local_variance, 3),
                    "noise_level":      round(result.metrics.noise_level, 3),
                    "prnu_score":       round(result.metrics.prnu_score, 3),
                },
            }
            ai_probability = result.ai_probability
            label          = result.label
        else:
            data = detector.analyze_document(file_bytes, filename)
            data["type"] = "document"
            ai_probability = data.get("overall_ai_probability", 0.5)
            label = _label_from_score(ai_probability)
            data["label"] = label

        # Log to DB
        log = AnalysisLog(
            user_id        = current_user.id,
            filename       = filename,
            file_type      = data["type"],
            sha256         = data.get("sha256", ""),
            ai_probability = ai_probability,
            label          = label,
            mode           = app.config["DETECTION_MODE"],
        )
        db.session.add(log)
        current_user.analyses_count += 1
        db.session.commit()

        return jsonify(data)

    except Exception as exc:
        logger.error(f"Erreur de détection : {exc}", exc_info=True)
        return jsonify({"error": f"Erreur lors de l'analyse : {str(exc)}"}), 500


# ──────────────────────────────────────────────────────────────────────────────
# API — Certification
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/certify", methods=["POST"])
@login_required
def api_certify():
    if "file" not in request.files:
        return jsonify({"error": "Aucun fichier fourni."}), 400

    f           = request.files["file"]
    title       = request.form.get("title", "").strip()
    author      = request.form.get("author", current_user.name).strip()
    description = request.form.get("description", "").strip()

    if not title:
        return jsonify({"error": "Le titre est obligatoire."}), 400

    file_bytes = read_file_bytes(f)

    try:
        record = stamp.certify(
            image_bytes  = file_bytes,
            title        = title,
            author       = author,
            description  = description,
        )
        current_user.certifications_count += 1
        db.session.commit()

        return jsonify({
            "cert_id":     record.cert_id,
            "image_hash":  record.image_hash,
            "ipfs_hash":   record.ipfs_hash,
            "certifier":   record.certifier,
            "title":       record.title,
            "author":      record.author,
            "timestamp":   record.timestamp,
            "tx_hash":     record.tx_hash,
            "network":     record.network,
            "revoked":     record.revoked,
        })
    except Exception as exc:
        logger.error(f"Erreur de certification : {exc}", exc_info=True)
        return jsonify({"error": str(exc)}), 500


# ──────────────────────────────────────────────────────────────────────────────
# API — Verification
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/verify", methods=["POST"])
@login_required
def api_verify():
    cert_id    = request.form.get("cert_id", "").strip()
    image_hash = request.form.get("image_hash", "").strip()

    # Verify by uploaded file
    if "file" in request.files and request.files["file"].filename:
        file_bytes = read_file_bytes(request.files["file"])
        record = stamp.verify_by_image(file_bytes)
    elif cert_id:
        record = stamp.verify_by_cert_id(cert_id)
    elif image_hash:
        record = stamp.verify_by_hash(image_hash)
    else:
        return jsonify({"error": "Fournissez un fichier, un identifiant ou un hash SHA-256."}), 400

    if record is None:
        return jsonify({"found": False, "message": "Aucun certificat trouvé pour ce contenu."})

    return jsonify({
        "found":      True,
        "cert_id":    record.cert_id,
        "image_hash": record.image_hash,
        "title":      record.title,
        "author":     record.author,
        "timestamp":  record.timestamp,
        "tx_hash":    record.tx_hash,
        "network":    record.network,
        "revoked":    record.revoked,
    })


# ──────────────────────────────────────────────────────────────────────────────
# API — System info
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/status")
def api_status():
    return jsonify({
        "status":          "online",
        "version":         "1.0.0",
        "detection_mode":  app.config["DETECTION_MODE"],
        "blockchain":      "simulation" if not app.config["CONTRACT_ADDRESS"] else "polygon",
    })


# ──────────────────────────────────────────────────────────────────────────────
# Utils
# ──────────────────────────────────────────────────────────────────────────────

def _label_from_score(score: float) -> str:
    if score < 0.20: return "Authentique"
    if score < 0.40: return "Probablement authentique"
    if score < 0.60: return "Résultat incertain"
    if score < 0.75: return "Probablement IA"
    return "Très probablement IA"


@app.template_filter("pct")
def pct_filter(value):
    return f"{value * 100:.1f}%"

@app.template_filter("fmt_date")
def fmt_date_filter(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except Exception:
            return value
    return value.strftime("%d/%m/%Y %H:%M")


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "1") == "1"

    print("\n" + "="*60)
    print("  VeriaChain — Prototype M2 SMI")
    print(f"  http://localhost:{port}")
    print("  Mode détection :", app.config["DETECTION_MODE"])
    print("  Blockchain      :", "Simulation" if not app.config["CONTRACT_ADDRESS"] else "Polygon")
    print("="*60 + "\n")
    app.run(debug=debug, host=host, port=port)
