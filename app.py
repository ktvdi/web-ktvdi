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

# --- HELPER FORMAT WAKTU (WIB) ---
def format_pub_date(published_parsed):
    if not published_parsed: return "LIVE"
    try:
        # Konversi UTC struct_time ke datetime
        dt_utc = datetime.fromtimestamp(time.mktime(published_parsed))
        # Tambah 7 Jam (WIB) - sesuaikan jika server sudah WIB
        now = datetime.now()
        
        # Hitung selisih
        diff = now - dt_utc
        seconds = diff.total_seconds()
        minutes = int(seconds // 60)
        hours = int(seconds // 3600)
        
        if hours >= 24: return dt_utc.strftime("%d %b").upper()
        if hours > 0: return f"{hours} JAM LALU"
        if minutes > 0: return f"{minutes} MNT LALU"
        return "BARU SAJA"
    except:
        return "LIVE"

# --- FUNGSI BERITA ---
def get_news_data():
    news_items = []
    seen_titles = set() 

    # 1. PESAN NATARU (STATIS - TETAP PENTING)
    news_items.append({
        'category': 'HIMBAUAN',
        'headline': 'SELAMAT MUDIK NATARU 2025. HATI-HATI DI JALAN, PATUHI RAMBU LALU LINTAS. KELUARGA MENANTI DI RUMAH.',
        'source': 'KORLANTAS POLRI',
        'date': 'LIVE'
    })

    # 2. SUMBER RSS (Query Dipertajam & Disortir)
    sources = [
        # Gunakan query spesifik "Macet Tol" agar dapat info lalin, bukan berita saham
        {'cat': 'LALU LINTAS', 'src': 'INFO TOL', 'url': 'https://news.google.com/rss/search?q=macet+tol+terkini+indonesia&hl=id&gl=ID&ceid=ID%3Aid'},
        {'cat': 'KEPOLISIAN', 'src': 'HUMAS POLRI', 'url': 'https://news.google.com/rss/search?q=polri+terkini&hl=id&gl=ID&ceid=ID%3Aid'},
        {'cat': 'NASIONAL', 'src': 'ANTARA', 'url': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFZxYUdjU0FtdHZHZ0pMVWlnQVAB?hl=id&gl=ID&ceid=ID%3Aid'},
        {'cat': 'DAERAH', 'src': 'REGIONAL', 'url': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGs0ZDNZU0FtdHZHZ0pMVWlnQVAB?hl=id&gl=ID&ceid=ID%3Aid'},
        {'cat': 'TEKNOLOGI', 'src': 'INET', 'url': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtdHZHZ0pMVWlnQVAB?hl=id&gl=ID&ceid=ID%3Aid'}
    ]

    try:
        for source in sources:
            feed = feedparser.parse(source['url'])
            
            # --- WAJIB SORTIR BERDASARKAN WAKTU TERBARU ---
            # Google News kadang ngacak, kita paksa urutkan by published_parsed (Time)
            if feed.entries:
                feed.entries.sort(key=lambda x: x.published_parsed if x.get('published_parsed') else time.localtime(0), reverse=True)

            count = 0
            for entry in feed.entries:
                if count >= 3: break # Ambil 3 Teratas (Paling Baru)
                
                # Bersihkan Judul
                raw_title = entry.title
                clean_title = raw_title.split(' - ')[0].strip()
                
                if clean_title in seen_titles: continue
                
                # Sumber & Waktu
                src_name = entry.source.title if 'source' in entry else source['src']
                pub_date = format_pub_date(entry.published_parsed)

                news_items.append({
                    'category': source['cat'],
                    'headline': clean_title.upper(), 
                    'source': src_name.upper(),
                    'date': pub_date
                })
                seen_titles.add(clean_title)
                count += 1
        
        # Urutan Prioritas Tampil
        prio = {'HIMBAUAN':0, 'LALU LINTAS':1, 'KEPOLISIAN':2, 'NASIONAL':3, 'DAERAH':4, 'TEKNOLOGI':5}
        news_items.sort(key=lambda x: prio.get(x['category'], 99))

    except Exception as e:
        print(f"Error RSS: {e}")
        if not news_items:
            news_items.append({'category': 'INFO', 'headline': 'MENYINKRONKAN DATA TERBARU...', 'source': 'SYSTEM', 'date': 'LOADING'})
        
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
