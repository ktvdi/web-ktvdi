import os
import hashlib
import firebase_admin
import random
import re
import html
import requests
import feedparser
from firebase_admin import credentials, db
from flask import Flask, request, render_template, redirect, url_for, session, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
from datetime import datetime, timedelta
import time

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
except Exception as e:
    print(f"Firebase Warn: {e}")

# --- HELPER FORMAT WAKTU ---
def format_pub_date(published_parsed):
    if not published_parsed: return "BARU SAJA"
    # Convert struct_time ke datetime
    dt = datetime.fromtimestamp(time.mktime(published_parsed))
    # Tambah 7 jam untuk WIB (karena server biasanya UTC) atau sesuaikan
    # Disini kita asumsikan feed sudah ada timezonenya atau kita format simpel
    return dt.strftime("%d %b, %H:%M WIB").upper()

# --- FUNGSI BERITA ---
def get_news_data():
    news_items = []
    seen_titles = set() # Cegah duplikasi judul persis

    # 1. PESAN NATARU (URGENT)
    nataru_msg = 'SELAMAT MUDIK NATARU 2025. HATI-HATI DI JALAN, UTAMAKAN KESELAMATAN. GUNAKAN SABUK PENGAMAN & HELM SNI.'
    news_items.append({
        'category': 'HIMBAUAN',
        'headline': nataru_msg,
        'source': 'KORLANTAS POLRI',
        'date': datetime.now().strftime("%d %b, %H:%M WIB")
    })

    # 2. SUMBER RSS
    sources = [
        {'cat': 'LALU LINTAS', 'src': 'JASA MARGA', 'url': 'https://news.google.com/rss/search?q=info+tol+jasa+marga+macet&hl=id&gl=ID&ceid=ID%3Aid'},
        {'cat': 'KEPOLISIAN', 'src': 'HUMAS POLRI', 'url': 'https://news.google.com/rss/search?q=polri+indonesia&hl=id&gl=ID&ceid=ID:id'},
        {'cat': 'NASIONAL', 'src': 'ANTARA', 'url': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFZxYUdjU0FtdHZHZ0pMVWlnQVAB?hl=id&gl=ID&ceid=ID%3Aid'},
        {'cat': 'DAERAH', 'src': 'REGIONAL', 'url': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGs0ZDNZU0FtdHZHZ0pMVWlnQVAB?hl=id&gl=ID&ceid=ID%3Aid'},
        {'cat': 'TEKNOLOGI', 'src': 'INET', 'url': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtdHZHZ0pMVWlnQVAB?hl=id&gl=ID&ceid=ID%3Aid'}
    ]

    try:
        for source in sources:
            feed = feedparser.parse(source['url'])
            count = 0
            for entry in feed.entries:
                if count >= 3: break 
                
                # 1. BERSIHKAN JUDUL (Hapus nama media di belakang)
                # Contoh: "Macet di Tol Cikampek - Detikcom" -> "Macet di Tol Cikampek"
                raw_title = entry.title
                clean_title = raw_title.split(' - ')[0].strip()
                
                # Cek Duplikasi
                if clean_title in seen_titles: continue
                
                # 2. AMBIL SUMBER
                src_name = entry.source.title if 'source' in entry else source['src']
                
                # 3. AMBIL WAKTU
                pub_date = format_pub_date(entry.published_parsed)

                news_items.append({
                    'category': source['cat'],
                    'headline': clean_title.upper(), # Judul Kapital Saja (Tanpa Isi)
                    'source': src_name.upper(),
                    'date': pub_date
                })
                seen_titles.add(clean_title)
                count += 1
        
        # Urutan Prioritas
        prio = {'HIMBAUAN':0, 'LALU LINTAS':1, 'KEPOLISIAN':2, 'NASIONAL':3, 'DAERAH':4, 'TEKNOLOGI':5}
        news_items.sort(key=lambda x: prio.get(x['category'], 99))

    except Exception as e:
        if not news_items:
            news_items.append({'category': 'INFO', 'headline': 'SISTEM SEDANG OPTIMALISASI DATA...', 'source': 'ADMIN', 'date': 'NOW'})
        
    return news_items

@app.route('/api/news-live')
def api_news_live(): return jsonify(get_news_data())

@app.route("/", methods=['GET', 'POST'])
def home(): return render_template('maintenance.html', news_list=get_news_data())

@app.route("/dashboard")
def dashboard(): return redirect(url_for('home'))
@app.route("/login")
def login(): return render_template('login.html')

if __name__ == "__main__":
    app.run(debug=True)
