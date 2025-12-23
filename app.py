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
from flask import Flask, request, render_template, redirect, url_for, session, flash, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
from flask_mail import Mail, Message
from datetime import datetime
from collections import Counter

# --- 1. KONFIGURASI SISTEM ---
load_dotenv() 

app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("SECRET_KEY", "rahasia_donk")

# --- 2. KONEKSI FIREBASE ---
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

# --- 3. KONEKSI EMAIL ---
app.config['MAIL_SERVER'] = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
app.config['MAIL_PORT'] = int(os.environ.get("MAIL_PORT", 587))
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD")
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")
mail = Mail(app)

# --- 4. KONEKSI AI (GEMINI) ---
if os.environ.get("GEMINI_APP_KEY"):
    genai.configure(api_key=os.environ.get("GEMINI_APP_KEY"))
    model = genai.GenerativeModel("gemini-2.5-flash")
else:
    model = None

# --- 5. FUNGSI PENGAMBIL BERITA (LOGIKA BARU) ---
def get_news_data():
    """
    Mengambil berita dari Google News RSS.
    Fitur:
    - Kategori: Nasional, Kepolisian, Teknologi, Olahraga, Daerah.
    - Output: Judul (Kapital) & Sumber.
    """
    news_items = []
    
    # Daftar Sumber RSS (Google News Topics)
    sources = [
        {'cat': 'NASIONAL', 'src_default': 'ANTARA', 'url': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFZxYUdjU0FtdHZHZ0pMVWlnQVAB?hl=id&gl=ID&ceid=ID%3Aid'},
        {'cat': 'KEPOLISIAN', 'src_default': 'HUMAS POLRI', 'url': 'https://news.google.com/rss/search?q=polri+indonesia&hl=id&gl=ID&ceid=ID:id'},
        {'cat': 'TEKNOLOGI', 'src_default': 'INET/TEKNO', 'url': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtdHZHZ0pMVWlnQVAB?hl=id&gl=ID&ceid=ID%3Aid'},
        {'cat': 'OLAHRAGA', 'src_default': 'SPORT', 'url': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp1ZEdvU0FtdHZHZ0pMVWlnQVAB?hl=id&gl=ID&ceid=ID%3Aid'},
        {'cat': 'DAERAH', 'src_default': 'REGIONAL', 'url': 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGs0ZDNZU0FtdHZHZ0pMVWlnQVAB?hl=id&gl=ID&ceid=ID%3Aid'}
    ]

    try:
        for source in sources:
            feed = feedparser.parse(source['url'])
            
            # Ambil maksimal 3 berita per kategori agar variatif
            for entry in feed.entries[:3]:
                # BERSIHKAN JUDUL: Google News sering format "Judul Berita - Nama Media"
                # Kita pisahkan agar nama media bisa ditaruh di samping judul dengan rapi
                parts = entry.title.rsplit(' - ', 1)
                
                clean_title = parts[0].strip()
                source_name = parts[1].strip() if len(parts) > 1 else source['src_default']
                
                # Coba ambil nama sumber dari metadata feed jika ada
                if 'source' in entry and 'title' in entry.source:
                    source_name = entry.source.title

                news_items.append({
                    'category': source['cat'],
                    'headline': clean_title.upper(), # Judul Kapital
                    'source': source_name.upper()    # Sumber Kapital
                })
        
        # Urutan Prioritas Tampil di Running Text
        # 1. Nasional, 2. Kepolisian (Penting), 3. Daerah, 4. Tekno, 5. Sport
        priority = {'NASIONAL': 1, 'KEPOLISIAN': 2, 'DAERAH': 3, 'TEKNOLOGI': 4, 'OLAHRAGA': 5}
        news_items.sort(key=lambda x: priority.get(x['category'], 99))

    except Exception as e:
        print(f"RSS Error: {e}")
        # Data dummy jika error koneksi
        news_items = [{'category': 'INFO', 'headline': 'SISTEM SEDANG DALAM PENINGKATAN PERFORMA...', 'source': 'ADMIN KTVDI'}]
        
    return news_items

# --- FUNGSI BANTUAN LAIN ---
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def time_since_published(published_time):
    # (Opsional untuk halaman berita full)
    now = datetime.now()
    publish_time = datetime(*published_time[:6])
    delta = now - publish_time
    if delta.days >= 1: return f"{delta.days} hari lalu"
    if delta.seconds >= 3600: return f"{delta.seconds // 3600} jam lalu"
    return "Baru saja"

# --- 6. ROUTE API LIVE UPDATE (Dipanggil AJAX Frontend) ---
@app.route('/api/news-live')
def api_news_live():
    data = get_news_data()
    return jsonify(data)

# --- 7. ROUTE UTAMA (HOME) ---
@app.route("/", methods=['GET', 'POST'])
def home():
    # =================================================================
    # 🔥 MODE MAINTENANCE AKTIF 🔥
    # =================================================================
    
    # Ambil data awal agar saat loading pertama sudah ada isinya
    berita_awal = get_news_data()
    
    # Render template Maintenance (Tampilan Biru/Putih Official)
    return render_template('maintenance.html', news_list=berita_awal)
    
    # --- KODE DASHBOARD ASLI (TIDAK AKTIF SELAMA DI ATAS ADA RETURN) ---
    if request.method == 'POST':
        try:
            prompt = request.get_json().get("prompt")
            reply = model.generate_content(prompt).text if model else "AI belum aktif."
            return jsonify({"response": reply})
        except: return jsonify({"error": "Error"}), 500

    # Logic Dashboard standar...
    return render_template('index.html') # Placeholder

# --- 8. ROUTE LAINNYA (Login, Register, Dashboard, dll) ---
# Tetap disediakan agar struktur aplikasi utuh

@app.route("/daftar-siaran")
def daftar_siaran():
    return render_template("daftar-siaran.html", provinsi_list=[])

@app.route('/berita')
def berita():
    return render_template('berita.html', articles=[], page=1, total_pages=1)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # Logika login placeholder
        pass
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route("/register", methods=["GET", "POST"])
def register():
    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    return render_template("verify-register.html")

@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    return render_template("dashboard.html", name=session.get('nama'), provinsi_list=[])

@app.route("/add_data", methods=["GET", "POST"])
def add_data(): return redirect(url_for('dashboard')) 

@app.route("/edit_data/<provinsi>/<wilayah>/<mux>", methods=["GET", "POST"])
def edit_data(provinsi, wilayah, mux): return redirect(url_for('dashboard'))

@app.route("/delete_data/<provinsi>/<wilayah>/<mux>", methods=["POST"])
def delete_data(provinsi, wilayah, mux): return redirect(url_for('dashboard'))

# API Dummy untuk dashboard
@app.route("/get_wilayah")
def get_wilayah(): return jsonify({})
@app.route("/get_mux")
def get_mux(): return jsonify({})
@app.route("/get_siaran")
def get_siaran(): return jsonify({})

# Error Handlers
@app.errorhandler(404)
def not_found(e): return "<h1>404 - Halaman Tidak Ditemukan</h1>", 404

@app.errorhandler(500)
def server_error(e): return "<h1>500 - Server Error</h1>", 500

@app.route('/sitemap.xml')
def sitemap(): return send_from_directory('static', 'sitemap.xml')

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password(): return render_template("forgot-password.html")

@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp(): return render_template("verify-otp.html")

@app.route("/reset-password", methods=["GET", "POST"])
def reset_password(): return render_template("reset-password.html")

if __name__ == "__main__":
    app.run(debug=True)
