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
from datetime import datetime, timedelta
import time # Import time untuk parsing struct_time

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

# --- HELPER TIME AGO ---
def get_time_ago(published_parsed):
    """Mengubah struct_time menjadi string 'x menit lalu'"""
    if not published_parsed: return "BARU SAJA"
    
    pub_dt = datetime.fromtimestamp(time.mktime(published_parsed))
    now = datetime.now()
    diff = now - pub_dt
    
    seconds = diff.total_seconds()
    minutes = int(seconds // 60)
    hours = int(seconds // 3600)
    
    if hours > 24: return pub_dt.strftime("%d/%m")
    if hours > 0: return f"{hours} JAM LALU"
    if minutes > 0: return f"{minutes} MENIT LALU"
    return "BARU SAJA"

# --- FUNGSI BERITA ---
def get_news_data():
    news_items = []
    
    # 1. HIMBAUAN NATARU (Wajib Ada)
    news_items.append({
        'category': 'HIMBAUAN',
        'headline': 'SELAMAT MUDIK NATARU 2025. UTAMAKAN KESELAMATAN, GUNAKAN SABUK PENGAMAN DAN HELM SNI. KELUARGA MENANTI DI RUMAH.',
        'source': 'KORLANTAS POLRI',
        'time': 'LIVE'
    })

    # 2. SUMBER RSS
    sources = [
        {'cat': 'LALU LINTAS', 'src': 'JASA MARGA', 'url': 'https://news.google.com/rss/search?q=macet+tol+jasa+marga&hl=id&gl=ID&ceid=ID:id'},
        {'cat': 'NASIONAL', 'src': 'ANTARA', 'url': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFZxYUdjU0FtdHZHZ0pMVWlnQVAB?hl=id&gl=ID&ceid=ID%3Aid'},
        {'cat': 'KEPOLISIAN', 'src': 'HUMAS POLRI', 'url': 'https://news.google.com/rss/search?q=polri+indonesia&hl=id&gl=ID&ceid=ID:id'},
        {'cat': 'DAERAH', 'src': 'REGIONAL', 'url': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGs0ZDNZU0FtdHZHZ0pMVWlnQVAB?hl=id&gl=ID&ceid=ID%3Aid'},
        {'cat': 'TEKNOLOGI', 'src': 'INET', 'url': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtdHZHZ0pMVWlnQVAB?hl=id&gl=ID&ceid=ID%3Aid'}
    ]

    try:
        for source in sources:
            feed = feedparser.parse(source['url'])
            # Ambil 3 berita terbaru
            for entry in feed.entries[:3]:
                # Bersihkan Judul
                clean_title = entry.title.split(' - ')[0]
                
                # Ambil Summary (Isi Berita Pendek)
                raw_summary = entry.get('summary', '') or entry.get('description', '')
                clean_summary = re.sub('<.*?>', '', html.unescape(raw_summary))
                # Ambil kalimat pertama saja untuk digabung ke headline jika judul terlalu pendek
                first_sentence = clean_summary.split('.')[0] if clean_summary else ""
                
                # Gabung Judul + Kalimat Pertama agar panjang & informatif
                full_text = f"{clean_title}. {first_sentence}"
                
                source_name = entry.source.title if 'source' in entry else source['src']
                time_ago = get_time_ago(entry.published_parsed)

                news_items.append({
                    'category': source['cat'],
                    'headline': full_text.upper(), # Uppercase semua
                    'source': source_name.upper(),
                    'time': time_ago
                })
        
        # Urutan Prioritas
        priority = {'HIMBAUAN':0, 'LALU LINTAS':1, 'NASIONAL':2, 'KEPOLISIAN':3, 'DAERAH':4, 'TEKNOLOGI':5}
        news_items.sort(key=lambda x: priority.get(x['category'], 99))

    except Exception as e:
        print(f"RSS Error: {e}")
        if not news_items:
            news_items.append({'category': 'INFO', 'headline': 'SISTEM SEDANG PEMBARUAN DATA...', 'source': 'ADMIN', 'time': 'NOW'})
        
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
