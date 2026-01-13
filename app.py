import os
import hashlib
import firebase_admin
import random
import re
import pytz
import time
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

# Muat variabel lingkungan
load_dotenv()

app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-ktvdi")

# --- Inisialisasi Firebase ---
try:
    # Cek apakah menggunakan Env Var (Vercel) atau File json (Local)
    if os.environ.get("FIREBASE_PRIVATE_KEY"):
        cred = credentials.Certificate({
            "type": "service_account",
            "project_id": os.environ.get("FIREBASE_PROJECT_ID"),
            "private_key_id": os.environ.get("FIREBASE_PRIVATE_KEY_ID"),
            "private_key": os.environ.get("FIREBASE_PRIVATE_KEY").replace('\\n', '\n'),
            "client_email": os.environ.get("FIREBASE_CLIENT_EMAIL"),
            "client_id": os.environ.get("FIREBASE_CLIENT_ID"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": os.environ.get("FIREBASE_CLIENT_X509_CERT_URL"),
            "universe_domain": "googleapis.com"
        })
    else:
        # Fallback untuk local dev jika ada file credential
        cred = credentials.Certificate("credentials.json")

    firebase_admin.initialize_app(cred, {
        'databaseURL': os.environ.get('DATABASE_URL')
    })

    ref = db.reference('/')
    print("✅ Firebase berhasil terhubung!")

except Exception as e:
    print("❌ Error initializing Firebase:", str(e))
    ref = None

# --- Inisialisasi Email ---
app.config['MAIL_SERVER'] = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
app.config['MAIL_PORT'] = int(os.environ.get("MAIL_PORT", 587))
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD")
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")

mail = Mail(app)

# --- Konfigurasi Gemini AI ---
genai.configure(api_key=os.environ.get("GEMINI_APP_KEY"))
model = genai.GenerativeModel("gemini-2.5-flash")

# --- Helper Functions ---
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def time_since_published(published_time):
    now = datetime.now()
    try:
        publish_time = datetime(*published_time[:6])
        delta = now - publish_time
        if delta.days >= 1: return f"{delta.days} hari lalu"
        if delta.seconds >= 3600: return f"{delta.seconds // 3600} jam lalu"
        return "Baru saja"
    except:
        return ""

# --- ROUTES ---

@app.route("/")
def home():
    # 1. Ambil Data Statistik TV Digital
    siaran_data = ref.child('siaran').get() if ref else {}
    stats = {'wilayah': 0, 'mux': 0, 'channel': 0}
    
    if siaran_data:
        for prov in siaran_data.values():
            if isinstance(prov, dict):
                stats['wilayah'] += len(prov)
                for wil in prov.values():
                    if isinstance(wil, dict):
                        stats['mux'] += len(wil)
                        for mux in wil.values():
                            if 'siaran' in mux:
                                stats['channel'] += len(mux['siaran'])

    # 2. Ambil Breaking News untuk Ticker (CNN Indonesia)
    breaking_news = []
    try:
        feed = feedparser.parse('https://www.cnnindonesia.com/nasional/rss')
        breaking_news = [entry.title for entry in feed.entries[:5]]
    except:
        breaking_news = ["Selamat Datang di KTVDI", "Cek Sinyal TV Digital Anda Sekarang"]

    return render_template('index.html', stats=stats, breaking_news=breaking_news)

@app.route('/', methods=['POST'])
def chatbot():
    data = request.get_json()
    prompt = data.get("prompt")
    try:
        # System instruction sederhana agar lebih terarah
        full_prompt = (
            "Anda adalah Asisten AI untuk Komunitas TV Digital Indonesia (KTVDI). "
            "Jawablah dengan singkat, padat, dan membantu terkait TV Digital (STB, Antena, Sinyal). "
            f"Pertanyaan user: {prompt}"
        )
        response = model.generate_content(full_prompt)
        return jsonify({"response": response.text})
    except Exception as e:
        return jsonify({"error": "Maaf, server AI sedang sibuk."})

# --- CCTV Route ---
@app.route("/cctv")
def cctv_page():
    return render_template("cctv.html")

# --- Jadwal Sholat Route ---
@app.route("/jadwal-sholat")
def jadwal_sholat_page():
    # Daftar 15 Kota Besar + Purwodadi + Semarang
    daftar_kota = [
        {"id": "1106", "nama": "Purwodadi (Grobogan)"},
        {"id": "1108", "nama": "Kota Semarang"},
        {"id": "1301", "nama": "DKI Jakarta"},
        {"id": "1630", "nama": "Kota Surabaya"},
        {"id": "1219", "nama": "Kota Bandung"},
        {"id": "0224", "nama": "Kota Medan"},
        {"id": "1221", "nama": "Kota Bekasi"},
        {"id": "2701", "nama": "Kota Makassar"},
        {"id": "0612", "nama": "Kota Palembang"},
        {"id": "1222", "nama": "Kota Depok"},
        {"id": "3006", "nama": "Kota Tangerang"},
        {"id": "3210", "nama": "Kota Batam"},
        {"id": "0412", "nama": "Kota Pekanbaru"},
        {"id": "1633", "nama": "Kota Malang"},
        {"id": "1130", "nama": "Kota Surakarta (Solo)"},
        {"id": "1009", "nama": "Kota Yogyakarta"},
        {"id": "1701", "nama": "Kota Denpasar"}
    ]
    # Urutkan nama kota secara alfabetis
    daftar_kota = sorted(daftar_kota, key=lambda x: x['nama'])
    return render_template("jadwal-sholat.html", daftar_kota=daftar_kota)

@app.route("/api/jadwal-sholat/<id_kota>")
def get_jadwal_api(id_kota):
    try:
        today = datetime.now().strftime("%Y/%m/%d")
        url = f"https://api.myquran.com/v2/sholat/jadwal/{id_kota}/{today}"
        r = requests.get(url, timeout=5)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# --- Berita Route ---
@app.route('/berita')
def berita():
    rss_url = 'https://www.cnnindonesia.com/teknologi/rss' # Menggunakan CNN Tech agar lebih relevan
    feed = feedparser.parse(rss_url)
    articles = feed.entries
    
    # Pagination Logic
    page = request.args.get('page', 1, type=int)
    per_page = 6
    start = (page - 1) * per_page
    end = start + per_page
    total_pages = (len(articles) + per_page - 1) // per_page
    
    current_articles = articles[start:end]
    for a in current_articles:
        if hasattr(a, 'published_parsed'):
            a.time_since_published = time_since_published(a.published_parsed)
        else:
            a.time_since_published = ""

    return render_template('berita.html', articles=current_articles, page=page, total_pages=total_pages)

# --- Auth & User System ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = request.form.get('username')
        pw = hash_password(request.form.get('password'))
        
        u_data = ref.child(f'users/{user}').get() if ref else None
        if u_data and u_data.get('password') == pw:
            session['user'] = user
            session['nama'] = u_data.get('nama')
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error="Username atau Password salah")
    return render_template('login.html')

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        if not ref: return "Database Error"
        user = request.form.get("username")
        email = request.form.get("email")
        
        # Cek duplikat sederhana
        if ref.child(f'users/{user}').get():
            flash("Username sudah dipakai", "error")
            return render_template("register.html")
            
        otp = str(random.randint(100000, 999999))
        hashed = hash_password(request.form.get("password"))
        
        # Simpan sementara
        ref.child(f'pending_users/{user}').set({
            "nama": request.form.get("nama"),
            "email": email,
            "password": hashed,
            "otp": otp
        })
        
        # Kirim Email
        try:
            msg = Message("Verifikasi KTVDI", recipients=[email])
            msg.body = f"Kode OTP Anda: {otp}"
            mail.send(msg)
            session['pending_username'] = user
            return redirect(url_for('verify_register'))
        except Exception as e:
            flash(f"Gagal kirim email: {e}", "error")
            
    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    user = session.get('pending_username')
    if not user: return redirect(url_for('register'))
    
    if request.method == "POST":
        input_otp = request.form.get("otp")
        pending = ref.child(f'pending_users/{user}').get()
        
        if pending and str(pending['otp']) == input_otp:
            # Pindahkan ke users aktif
            ref.child(f'users/{user}').set({
                "nama": pending['nama'],
                "email": pending['email'],
                "password": pending['password'],
                "points": 10 # Bonus daftar
            })
            ref.child(f'pending_users/{user}').delete()
            flash("Berhasil! Silakan login", "success")
            return redirect(url_for('login'))
        else:
            flash("OTP Salah", "error")
            
    return render_template("verify-register.html", username=user)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- Dashboard & CRUD ---

@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    prov = ref.child('provinsi').get() if ref else {}
    return render_template("dashboard.html", name=session.get('nama'), provinsi_list=list(prov.values()) if prov else [])

@app.route("/daftar-siaran")
def daftar_siaran():
    prov = ref.child('provinsi').get() if ref else {}
    return render_template("daftar-siaran.html", provinsi_list=list(prov.values()) if prov else [])

@app.route("/add_data", methods=["GET", "POST"])
def add_data():
    if 'user' not in session: return redirect(url_for('login'))
    
    if request.method == 'POST':
        p = request.form.get('provinsi')
        w = request.form.get('wilayah').replace(' ', '') # Bersihkan spasi
        m = request.form.get('mux')
        s = request.form.get('siaran').split(',')
        s = [x.strip() for x in s if x.strip()]
        
        ref.child(f'siaran/{p}/{w}/{m}').set({
            "siaran": sorted(s),
            "last_updated_by": session['user'],
            "last_updated_date": datetime.now().strftime("%d-%m-%Y")
        })
        return redirect(url_for('dashboard'))
        
    prov = ref.child('provinsi').get() if ref else {}
    return render_template('add_data_form.html', provinsi_list=list(prov.values()) if prov else [])

# --- API Endpoints untuk Dropdown ---
@app.route("/get_wilayah")
def get_wilayah():
    p = request.args.get("provinsi")
    d = ref.child(f"siaran/{p}").get() if ref else {}
    return jsonify({"wilayah": list(d.keys()) if d else []})

@app.route("/get_mux")
def get_mux():
    p = request.args.get("provinsi")
    w = request.args.get("wilayah")
    d = ref.child(f"siaran/{p}/{w}").get() if ref else {}
    return jsonify({"mux": list(d.keys()) if d else []})

# --- Lainnya ---
@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/sitemap.xml')
def sitemap():
    return send_from_directory('static', 'sitemap.xml')

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    # Implementasi sederhana
    return render_template("forgot-password.html")

if __name__ == "__main__":
    app.run(debug=True)
