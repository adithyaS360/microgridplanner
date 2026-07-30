from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.sql import func
import json

db = SQLAlchemy()

class Organization(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255))

    users = db.relationship('User', backref='organization', lazy=True)
    projects = db.relationship('Project', backref='organization', lazy=True)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    org_id = db.Column(db.Integer, db.ForeignKey('organization.id'))
    role = db.Column(db.String(20), default="member")  # admin/member

class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey('organization.id'))
    name = db.Column(db.String(255))
    lat = db.Column(db.Float)
    lon = db.Column(db.Float)
    created_at = db.Column(db.DateTime, server_default=func.now())

    analyses = db.relationship('Analysis', backref='project', lazy=True)

class Analysis(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'))
    inputs = db.Column(db.JSON)     # raw request payload
    results = db.Column(db.JSON)    # full size_system() output
    created_at = db.Column(db.DateTime, server_default=func.now())
