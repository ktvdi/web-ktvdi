import os
import hashlib
import firebase_admin
import random
import re
import pytz
import requests
import feedparser
import google.generativeai as genai
from firebase_admin import credentials, db
from flask import Flask, request, render_template, redirect, url_for, session, flash, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
from flask_mail import Mail, Message
from datetime import datetime
from collections import Counter

# --- KONFIGURASI ---
load_dotenv() 
app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("SECRET_KEY", "rahasia_donk")

# --- KONEKSI FIREBASE ---
try:
    if not firebase_admin._apps:
        cred = credentials.Certificate({
            "type": "service_account",
            "project_id": os.environ.get("FIREBASE_PROJECT_ID"),
            "private_key_id": os.environ.get("FIREBASE_PRIVATE_KEY_ID"),
            "private_key": os.environ.get("FIREBASE_PRIVATE_KEY", "").replace('\\n', '\n'),
            "client_email": os.environ.get("FIREBASE_CLIENT_EMAIL"),
            "client_id": os.environ.get("FIREBASE_CLIENT_ID"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": os.environ.get("FIREBASE_CLIENT_X509_CERT_URL"),
            "universe_domain": "googleapis.com"
        })
        firebase_admin.initialize_app(cred, {'databaseURL': os.environ.get('DATABASE_URL')})
    ref = db.reference('/')
    print("✅ Firebase Terhubung!")
except Exception as e:
    print(f"⚠️ Peringatan Firebase: {e}")

# --- KONEKSI EMAIL ---
app.config['MAIL_SERVER'] = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
app.config['MAIL_PORT'] = int(os.environ.get("MAIL_PORT", 587))
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD")
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")
mail = Mail(app)

# --- AI CONFIG ---
if os.environ.get("GEMINI_APP_KEY"):
    genai.configure(api_key=os.environ.get("GEMINI_APP_KEY"))
    model = genai.GenerativeModel("gemini-2.5-flash")
else: model = None

# --- ROUTE API BERITA (PENTING UNTUK RUNNING TEXT) ---
@app.route('/api/news-live')
def api_news_live():
    try:
        # Tambahkan parameter random agar cache tidak nyangkut
        rss_url = f'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFZxYUdjU0FtdHZHZ0pMVWlnQVAB?hl=id&gl=ID&ceid=ID%3Aid&t={int(datetime.now().timestamp())}'
        feed = feedparser.parse(rss_url)
        # Ambil 15 berita
        news = [entry.title for entry in feed.entries[:15]]
        return jsonify(news)
    except:
        return jsonify(["Situs sedang maintenance (ISP NEXA)...", "Mohon bersabar..."])

# --- ROUTE UTAMA ---
@app.route("/", methods=['GET', 'POST'])
def home():
    # 🔥 MODE MAINTENANCE AKTIF 🔥
    
    # Ambil data awal
    berita_awal = ["Memuat berita terkini..."]
    try:
        rss_url = 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFZxYUdjU0FtdHZHZ0pMVWlnQVAB?hl=id&gl=ID&ceid=ID%3Aid'
        feed = feedparser.parse(rss_url)
        berita_awal = [entry.title for entry in feed.entries[:10]]
    except: pass

    # Render Maintenance
    return render_template('maintenance.html', news_list=berita_awal)

    # (Kode lama diabaikan)

# --- ROUTE STANDAR LAINNYA (Login, Logout, Dashboard dll tetap ada) ---
@app.route('/login', methods=['GET', 'POST'])
def login(): return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route("/dashboard")
def dashboard(): return redirect(url_for('home'))

if __name__ == "__main__":
    app.run(debug=True)
