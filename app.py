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
from collections import Counter

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

# --- FUNGSI PROSES BERITA ---
def process_news_content(entry):
    """Ambil summary, bersihkan HTML, ambil 2 kalimat, kapital."""
    # 1. Ambil konten (deskripsi atau summary)
    raw_text = entry.get('summary', '') or entry.get('description', '')
    
    # Jika deskripsi kosong/pendek, pakai judul saja tapi diperpanjang infonya
    if len(raw_text) < 20:
        return f"{entry.title}. BACA SELENGKAPNYA DI PORTAL BERITA RESMI.".upper()

    # 2. Bersihkan HTML
    text = html.unescape(raw_text)
    cleanr = re.compile('<.*?>')
    text = re.sub(cleanr, '', text)
    text = ' '.join(text.split()) # Hapus spasi ganda
    
    # 3. Ambil maksimal 2 Kalimat
    # Split berdasarkan tanda baca penutup kalimat
    sentences = re.split(r'(?<=[.!?]) +', text)
    final_text = ' '.join(sentences[:2]) 
    
    return final_text.upper()

def get_news_data():
    news_items = []
    # Sumber RSS Google News
    sources = [
        {'cat': 'NASIONAL', 'url': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFZxYUdjU0FtdHZHZ0pMVWlnQVAB?hl=id&gl=ID&ceid=ID%3Aid'},
        {'cat': 'TEKNOLOGI', 'url': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtdHZHZ0pMVWlnQVAB?hl=id&gl=ID&ceid=ID%3Aid'},
        {'cat': 'OLAHRAGA', 'url': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp1ZEdvU0FtdHZHZ0pMVWlnQVAB?hl=id&gl=ID&ceid=ID%3Aid'},
        {'cat': 'DAERAH', 'url': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGs0ZDNZU0FtdHZHZ0pMVWlnQVAB?hl=id&gl=ID&ceid=ID%3Aid'}
    ]

    try:
        for source in sources:
            feed = feedparser.parse(source['url'])
            # Ambil 3 berita per kategori
            for entry in feed.entries[:3]:
                processed_content = process_news_content(entry)
                news_items.append({
                    'category': source['cat'],
                    'content': processed_content 
                })
        
        # Urutkan agar tampil rapi per kategori
        priority = {'NASIONAL': 1, 'DAERAH': 2, 'OLAHRAGA': 3, 'TEKNOLOGI': 4}
        news_items.sort(key=lambda x: priority.get(x['category'], 99))

    except Exception as e:
        print(f"RSS Error: {e}")
        news_items = [{'category': 'SYSTEM', 'content': 'KONEKSI KE SERVER BERITA SEDANG DALAM PROSES SINKRONISASI...'}]
        
    return news_items

# --- ROUTES ---
@app.route('/api/news-live')
def api_news_live():
    data = get_news_data()
    return jsonify(data)

@app.route("/", methods=['GET', 'POST'])
def home():
    # 🔥 MODE MAINTENANCE 🔥
    berita_awal = get_news_data()
    return render_template('maintenance.html', news_list=berita_awal)

# (Route dummy lainnya agar tidak error jika diakses)
@app.route("/dashboard")
def dashboard(): return redirect(url_for('home'))
@app.route("/login")
def login(): return render_template('login.html')

if __name__ == "__main__":
    app.run(debug=True)
