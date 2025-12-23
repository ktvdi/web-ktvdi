import os
import hashlib
import firebase_admin
import random
import re
import html
import requests
import feedparser
import google.generativeai as genai
from firebase_admin import credentials, db
from flask import Flask, request, render_template, redirect, url_for, session, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
from flask_mail import Mail
from datetime import datetime

# --- KONFIGURASI ---
load_dotenv() 
app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("SECRET_KEY", "rahasia_donk")

# --- FIREBASE ---
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
    print("✅ Firebase Terhubung!")
except Exception as e:
    print(f"⚠️ Peringatan Firebase: {e}")

# --- FUNGSI BERITA ---
def get_news_data():
    news_items = []
    
    # 1. PESAN NATARU (STATIS - MUNCUL PERTAMA/DISELIPKAN)
    news_items.append({
        'category': 'HIMBAUAN',
        'headline': 'SELAMAT MUDIK NATARU 2025. HATI-HATI DI JALAN, PASTIKAN GUNAKAN SABUK PENGAMAN DAN HELM SNI. PATUHI RAMBU LALU LINTAS.',
        'source': 'KORLANTAS POLRI'
    })

    # 2. SUMBER RSS LIVE
    sources = [
        {'cat': 'LALU LINTAS', 'src': 'JASA MARGA UPDATE', 'url': 'https://news.google.com/rss/search?q=jasa+marga+macet+tol&hl=id&gl=ID&ceid=ID:id'},
        {'cat': 'NASIONAL', 'src': 'ANTARA', 'url': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFZxYUdjU0FtdHZHZ0pMVWlnQVAB?hl=id&gl=ID&ceid=ID%3Aid'},
        {'cat': 'KEPOLISIAN', 'src': 'HUMAS POLRI', 'url': 'https://news.google.com/rss/search?q=polri+indonesia&hl=id&gl=ID&ceid=ID:id'},
        {'cat': 'TEKNOLOGI', 'src': 'INET', 'url': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtdHZHZ0pMVWlnQVAB?hl=id&gl=ID&ceid=ID%3Aid'},
        {'cat': 'DAERAH', 'src': 'REGIONAL', 'url': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGs0ZDNZU0FtdHZHZ0pMVWlnQVAB?hl=id&gl=ID&ceid=ID%3Aid'}
    ]

    try:
        for source in sources:
            feed = feedparser.parse(source['url'])
            # Ambil 3 berita per kategori
            for entry in feed.entries[:3]:
                clean_title = entry.title.split(' - ')[0] # Hapus nama media di judul
                source_name = entry.source.title if 'source' in entry else source['src']

                news_items.append({
                    'category': source['cat'],
                    'headline': clean_title.upper(),
                    'source': source_name.upper()
                })
        
        # Urutan Prioritas: Himbauan -> Lalin -> Nasional -> Polri
        priority = {'HIMBAUAN': 0, 'LALU LINTAS': 1, 'NASIONAL': 2, 'KEPOLISIAN': 3, 'DAERAH': 4, 'TEKNOLOGI': 5}
        news_items.sort(key=lambda x: priority.get(x['category'], 99))

    except Exception as e:
        print(f"RSS Error: {e}")
        # Tetap tampilkan himbauan meski error
        if not news_items:
            news_items.append({'category': 'INFO', 'headline': 'SISTEM SEDANG PEMBARUAN...', 'source': 'ADMIN'})
        
    return news_items

# --- ROUTES ---
@app.route('/api/news-live')
def api_news_live():
    data = get_news_data()
    return jsonify(data)

@app.route("/", methods=['GET', 'POST'])
def home():
    berita_awal = get_news_data()
    return render_template('maintenance.html', news_list=berita_awal)

# Route Dummy
@app.route("/dashboard")
def dashboard(): return redirect(url_for('home'))
@app.route("/login")
def login(): return render_template('login.html')

if __name__ == "__main__":
    app.run(debug=True)
