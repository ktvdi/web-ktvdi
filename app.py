import os
import hashlib
import firebase_admin
import random
import re
import pytz
import time
import requests
import feedparser
import json 
import google.generativeai as genai
from firebase_admin import credentials, db
from flask import Flask, request, render_template, redirect, url_for, session, flash, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
from flask_mail import Mail, Message
from datetime import datetime
from collections import Counter

# --- 1. KONFIGURASI AWAL ---
load_dotenv()
app = Flask(__name__)
CORS(app)
# Secret key default agar session tidak crash jika env belum diset
app.secret_key = os.environ.get("SECRET_KEY", "fallback-secret-key-ktvdi-2026")

# --- 2. KONFIGURASI GEMINI AI ---
GOOGLE_API_KEY = os.environ.get("GEMINI_APP_KEY")
model = None

if GOOGLE_API_KEY:
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash")
        print("✅ Gemini AI Connected!")
    except Exception as e:
        print(f"❌ Gemini Error: {e}")
else:
    print("⚠️ Warning: GEMINI_APP_KEY belum diset di Vercel")

# --- 3. KONFIGURASI FIREBASE (SAFE MODE) ---
ref = None
try:
    # Cek apakah credential ada sebelum inisialisasi untuk mencegah crash 500
    private_key = os.environ.get("FIREBASE_PRIVATE_KEY")
    if private_key:
        # Perbaikan otomatis format private key untuk Vercel
        private_key = private_key.replace('\\n', '\n').replace('"', '')
    
    if os.environ.get("FIREBASE_PROJECT_ID") and private_key:
        cred = credentials.Certificate({
            "type": "service_account",
            "project_id": os.environ.get("FIREBASE_PROJECT_ID"),
            "private_key_id": os.environ.get("FIREBASE_PRIVATE_KEY_ID"),
            "private_key": private_key,
            "client_email": os.environ.get("FIREBASE_CLIENT_EMAIL"),
            "client_id": os.environ.get("FIREBASE_CLIENT_ID"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": os.environ.get("FIREBASE_CLIENT_X509_CERT_URL"),
            "universe_domain": "googleapis.com"
        })

        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred, {
                'databaseURL': os.environ.get('DATABASE_URL')
            })
        
        ref = db.reference('/')
        print("✅ Firebase Connected!")
    else:
        print("⚠️ Warning: Firebase Credentials belum lengkap di Vercel Environment Variables")

except Exception as e:
    print("❌ Firebase Init Error (App tetap jalan):", str(e))

# --- 4. KONFIGURASI EMAIL ---
app.config['MAIL_SERVER'] = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
app.config['MAIL_PORT'] = int(os.environ.get("MAIL_PORT", 587))
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME", "email@example.com")
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD", "password")
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME", "email@example.com")
mail = Mail(app)

# --- 5. HELPER FUNCTIONS ---

def get_google_news():
    """Mengambil berita dari Google News RSS dengan Error Handling"""
    news = []
    try:
        rss_url = 'https://news.google.com/rss/search?q=tv+digital+indonesia+teknologi+kominfo&hl=id&gl=ID&ceid=ID:id'
        feed = feedparser.parse(rss_url)
        for entry in feed.entries[:10]:
            news.append(entry.title)
    except Exception as e:
        print(f"RSS Error: {e}")
    
    if not news:
        news = [
            "Selamat Datang di KTVDI - Pusat Informasi TV Digital Indonesia",
            "Pastikan Perangkat STB Anda Bersertifikat Kominfo",
            "Update Frekuensi MUX Terbaru Tersedia di Database Kami"
        ]
    return news

def time_since_published(published_time):
    now = datetime.now()
    try:
        publish_time = datetime(*published_time[:6])
        delta = now - publish_time
        if delta.days >= 1: return f"{delta.days} hari lalu"
        if delta.seconds >= 3600: return f"{delta.seconds // 3600} jam lalu"
        return "Baru saja"
    except:
        return "-"

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# --- 6. ROUTES UTAMA ---

@app.route("/")
def home():
    # Inisialisasi Data Default jika Firebase Gagal/Kosong
    stats = {
        "wilayah": 0, "mux": 0, "channel": 0, "kontribusi": 0
    }
    
    chart_labels = []
    chart_data = []
    
    # Ambil Data Firebase (Jika Terhubung)
    if ref:
        try:
            siaran_ref = db.reference('siaran')
            siaran_data = siaran_ref.get() or {}
            
            siaran_counts = Counter()
            
            for provinsi, provinsi_data in siaran_data.items():
                if isinstance(provinsi_data, dict):
                    jumlah_wilayah = len(provinsi_data)
                    chart_labels.append(provinsi)
                    chart_data.append(jumlah_wilayah)
                    stats["wilayah"] += jumlah_wilayah

                    for wilayah, wilayah_data in provinsi_data.items():
                        if isinstance(wilayah_data, dict):
                            stats["mux"] += len(wilayah_data)
                            for penyelenggara, details in wilayah_data.items():
                                if 'siaran' in details:
                                    stats["channel"] += len(details['siaran'])
                                    for s in details['siaran']:
                                        siaran_counts[s.lower()] += 1
                                        
            if siaran_counts:
                stats["kontribusi"] = siaran_counts.most_common(1)[0][1]
        except Exception as e:
            print(f"Data Fetch Error: {e}")

    # Ambil Berita
    breaking_news = get_google_news()

    return render_template('index.html', 
                           stats=stats,
                           chart_labels=json.dumps(chart_labels),
                           chart_data=json.dumps(chart_data),
                           breaking_news=breaking_news)

@app.route('/chatbot', methods=['POST'])
def chatbot_api(): # Diganti endpoint khusus biar rapi
    data = request.get_json()
    prompt = data.get("prompt")

    if not model:
        return jsonify({"error": "Offline Mode"}), 503

    try:
        sys_msg = "Anda adalah Asisten Virtual KTVDI. Jawab singkat dan ramah seputar TV Digital, STB, dan Bola."
        response = model.generate_content(f"{sys_msg}\nUser: {prompt}")
        return jsonify({"response": response.text})
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "Quota" in error_msg:
            return jsonify({"error": "Quota Exceeded"}), 429
        return jsonify({"error": str(e)}), 500

# Endpoint Catch-all untuk route '/' method POST (Legacy support)
@app.route('/', methods=['POST'])
def chatbot_legacy():
    return chatbot_api()

# --- HALAMAN LAIN ---

@app.route('/about')
def about():
    return render_template('about.html')

@app.route("/daftar-siaran")
def daftar_siaran():
    provinsi_list = []
    if ref:
        data = db.reference("provinsi").get() or {}
        provinsi_list = list(data.values())
    return render_template("daftar-siaran.html", provinsi_list=provinsi_list)

@app.route('/berita')
def berita():
    rss_url = 'https://news.google.com/rss/search?q=tv+digital+indonesia&hl=id&gl=ID&ceid=ID:id'
    try:
        feed = feedparser.parse(rss_url)
        articles = feed.entries
    except:
        articles = []
    
    page = request.args.get('page', 1, type=int)
    per_page = 6
    total_articles = len(articles)
    total_pages = (total_articles + per_page - 1) // per_page
    start = (page - 1) * per_page
    end = start + per_page
    
    return render_template('berita.html', articles=articles[start:end], page=page, total_pages=total_pages)

# --- AUTHENTICATION ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()
        hashed_pw = hash_password(password)
        
        if ref:
            user_data = db.reference(f'users/{username}').get()
            if user_data and user_data.get('password') == hashed_pw:
                session['user'] = username
                session['nama'] = user_data.get("nama", "User")
                return redirect(url_for('dashboard'))
        
        return render_template('login.html', error="Login Gagal")
    return render_template('login.html')

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        nama = request.form.get("nama")
        email = request.form.get("email")
        username = request.form.get("username")
        password = request.form.get("password")

        if ref:
            users = db.reference("users").get() or {}
            if username in users:
                flash("Username terpakai", "error")
                return render_template("register.html")
            
            hashed_pw = hash_password(password)
            otp = str(random.randint(100000, 999999))
            
            db.reference(f"pending_users/{username}").set({
                "nama": nama, "email": email, "password": hashed_pw, "otp": otp
            })
            
            # Simulasi kirim email jika mail server belum setup
            print(f"OTP untuk {email}: {otp}") 
            
            session["pending_username"] = username
            return redirect(url_for("verify_register"))
            
    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    uname = session.get("pending_username")
    if not uname: return redirect(url_for("register"))
    
    if request.method == "POST":
        otp = request.form.get("otp")
        pending = db.reference(f"pending_users/{uname}").get()
        
        if pending and pending.get("otp") == otp:
            db.reference(f"users/{uname}").set({
                "nama": pending["nama"], "email": pending["email"],
                "password": pending["password"], "points": 0
            })
            db.reference(f"pending_users/{uname}").delete()
            session.pop("pending_username", None)
            return redirect(url_for("login"))
        else:
            flash("OTP Salah", "error")
            
    return render_template("verify-register.html", username=uname)

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    return render_template("forgot-password.html")

@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    return render_template("verify-otp.html")

@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    return render_template("reset-password.html")

# --- DASHBOARD & CRUD ---

@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    data = db.reference("provinsi").get() or {} if ref else {}
    return render_template("dashboard.html", name=session.get('nama'), provinsi_list=list(data.values()))

@app.route("/add_data", methods=["GET", "POST"])
def add_data():
    if 'user' not in session: return redirect(url_for('login'))
    data = db.reference("provinsi").get() or {} if ref else {}
    if request.method == 'POST':
        p = request.form['provinsi']
        w = request.form['wilayah']
        m = request.form['mux']
        s = request.form['siaran'].split(',')
        if ref:
            db.reference(f"siaran/{p}/{w}/{m}").set({"siaran": [x.strip() for x in s]})
        return redirect(url_for('dashboard'))
    return render_template('add_data_form.html', provinsi_list=list(data.values()))

@app.route("/edit_data/<provinsi>/<wilayah>/<mux>", methods=["GET", "POST"])
def edit_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        s = request.form['siaran'].split(',')
        if ref:
            db.reference(f"siaran/{provinsi}/{wilayah}/{mux}").update({"siaran": [x.strip() for x in s]})
        return redirect(url_for('dashboard'))
    return render_template('edit_data_form.html', provinsi=provinsi, wilayah=wilayah, mux=mux)

@app.route("/delete_data/<provinsi>/<wilayah>/<mux>", methods=["POST"])
def delete_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    if ref:
        db.reference(f"siaran/{provinsi}/{wilayah}/{mux}").delete()
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

@app.route('/sitemap.xml')
def sitemap_file():
    return send_from_directory('static', 'sitemap.xml')

# API Helpers for Frontend JS
@app.route("/get_wilayah")
def get_wilayah():
    p = request.args.get("provinsi")
    d = db.reference(f"siaran/{p}").get() or {} if ref else {}
    return jsonify({"wilayah": list(d.keys())})

@app.route("/get_mux")
def get_mux():
    p = request.args.get("provinsi")
    w = request.args.get("wilayah")
    d = db.reference(f"siaran/{p}/{w}").get() or {} if ref else {}
    return jsonify({"mux": list(d.keys())})

@app.route("/get_siaran")
def get_siaran():
    p = request.args.get("provinsi")
    w = request.args.get("wilayah")
    m = request.args.get("mux")
    d = db.reference(f"siaran/{p}/{w}/{m}").get() or {} if ref else {}
    return jsonify(d)

if __name__ == "__main__":
    app.run(debug=True)
