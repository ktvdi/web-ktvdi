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

# --- HELPER TIME AGO ---
def get_time_ago(published_parsed):
    if not published_parsed: return "LIVE"
    try:
        dt_utc = datetime.fromtimestamp(time.mktime(published_parsed))
        now = datetime.now()
        diff = now - dt_utc
        seconds = diff.total_seconds()
        hours = int(seconds // 3600)
        minutes = int(seconds // 60)
        
        # Format Detail
        if hours >= 24: return dt_utc.strftime("%d %b").upper() # Tgl jika > 24 jam
        if hours > 0: return f"{hours} JAM LALU"
        if minutes > 0: return f"{minutes} MENIT LALU"
        return "BARU SAJA"
    except:
        return "LIVE"

# --- FUNGSI BERITA ---
def get_news_data():
    news_items = []
    seen_titles = set()

    # 1. PESAN NATARU (Wajib)
    news_items.append({
        'category': 'HIMBAUAN',
        'headline': 'SELAMAT MUDIK NATARU 2025. UTAMAKAN KESELAMATAN, GUNAKAN SABUK PENGAMAN & HELM SNI. KELUARGA MENANTI DI RUMAH.',
        'source': 'KORLANTAS POLRI',
        'time': 'LIVE'
    })

    # 2. SUMBER RSS (LENGKAP + FORCED UPDATE)
    # Tambahkan 'when:2d' di query search untuk memaksa berita 2 hari terakhir
    sources = [
        {'cat': 'LALU LINTAS', 'src': 'INFO TOL', 'url': 'https://news.google.com/rss/search?q=macet+tol+jasa+marga+when:2d&hl=id&gl=ID&ceid=ID%3Aid'},
        {'cat': 'KEPOLISIAN', 'src': 'HUMAS POLRI', 'url': 'https://news.google.com/rss/search?q=polri+indonesia+when:2d&hl=id&gl=ID&ceid=ID%3Aid'},
        {'cat': 'NASIONAL', 'src': 'ANTARA', 'url': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFZxYUdjU0FtdHZHZ0pMVWlnQVAB?hl=id&gl=ID&ceid=ID%3Aid'},
        {'cat': 'DAERAH', 'src': 'REGIONAL', 'url': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGs0ZDNZU0FtdHZHZ0pMVWlnQVAB?hl=id&gl=ID&ceid=ID%3Aid'},
        {'cat': 'OLAHRAGA', 'src': 'SPORT', 'url': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp1ZEdvU0FtdHZHZ0pMVWlnQVAB?hl=id&gl=ID&ceid=ID%3Aid'},
        {'cat': 'TEKNOLOGI', 'src': 'INET', 'url': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtdHZHZ0pMVWlnQVAB?hl=id&gl=ID&ceid=ID%3Aid'}
    ]

    try:
        for source in sources:
            feed = feedparser.parse(source['url'])
            
            # SORTIR MANUAL BY WAKTU (PENTING!)
            if feed.entries:
                feed.entries.sort(key=lambda x: x.published_parsed if x.get('published_parsed') else time.localtime(0), reverse=True)

            count = 0
            for entry in feed.entries:
                if count >= 5: break # Ambil 5 Berita per kategori (Banyak)
                
                # Clean Judul
                clean_title = entry.title.split(' - ')[0].strip()
                if clean_title in seen_titles: continue
                
                # Ambil Summary (Isi Berita) -> Clean HTML
                raw_sum = entry.get('summary', '') or entry.get('description', '')
                clean_sum = re.sub('<.*?>', '', html.unescape(raw_sum)).strip()
                # Ambil 1 kalimat pertama yang panjang
                sentences = clean_sum.split('.')
                first_sentence = sentences[0] if len(sentences) > 0 else ""
                
                # Gabung Judul + Isi (Supaya Panjang & Informatif)
                full_text = f"{clean_title}. {first_sentence}"
                
                src_name = entry.source.title if 'source' in entry else source['src']
                t_ago = get_time_ago(entry.published_parsed)

                news_items.append({
                    'category': source['cat'],
                    'headline': full_text.upper(),
                    'source': src_name.upper(),
                    'time': t_ago
                })
                seen_titles.add(clean_title)
                count += 1
        
        # Urutan Tampil
        prio = {'HIMBAUAN':0, 'LALU LINTAS':1, 'KEPOLISIAN':2, 'NASIONAL':3, 'DAERAH':4, 'OLAHRAGA':5, 'TEKNOLOGI':6}
        news_items.sort(key=lambda x: prio.get(x['category'], 99))

    except Exception as e:
        print(f"RSS Err: {e}")
        if not news_items:
            news_items.append({'category': 'INFO', 'headline': 'SISTEM SEDANG UPDATE DATA...', 'source': 'ADMIN', 'time': 'NOW'})
        
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
