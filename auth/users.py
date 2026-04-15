"""
VeriaChain — Gestion des utilisateurs (Flask-Login + SQLAlchemy)
"""
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id            = db.Column(db.Integer, primary_key=True)
    email         = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name          = db.Column(db.String(150), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role          = db.Column(db.String(50), default="user")  # "user" | "admin"
    created_at    = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_login    = db.Column(db.DateTime, nullable=True)
    analyses_count       = db.Column(db.Integer, default=0)
    certifications_count = db.Column(db.Integer, default=0)

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<User {self.email}>"


class AnalysisLog(db.Model):
    __tablename__ = "analysis_logs"

    id             = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    filename       = db.Column(db.String(255))
    file_type      = db.Column(db.String(50))   # "image" | "document"
    sha256         = db.Column(db.String(64), index=True)
    ai_probability = db.Column(db.Float)
    label          = db.Column(db.String(100))
    mode           = db.Column(db.String(50))   # detection mode used
    created_at     = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


def init_db(app):
    db.init_app(app)
    with app.app_context():
        db.create_all()
