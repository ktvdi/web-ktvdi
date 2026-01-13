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
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")

# --- 1. KONEKSI FIREBASE ---
try:
    if os.environ.get("FIREBASE_PRIVATE_KEY"):
        # Konfigurasi untuk Vercel (Production)
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
        # Konfigurasi untuk Localhost
        cred = credentials.Certificate("credentials.json")

    firebase_admin.initialize_app(cred, {
        'databaseURL': os.environ.get('DATABASE_URL')
    })
    ref = db.reference('/')
    print("✅ Firebase berhasil terhubung!")
except Exception as e:
    print("❌ Error initializing Firebase:", str(e))
    ref = None

# --- 2. KONFIGURASI EMAIL ---
app.config['MAIL_SERVER'] = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
app.config['MAIL_PORT'] = int(os.environ.get("MAIL_PORT", 587))
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD")
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")
mail = Mail(app)

# --- 3. KONFIGURASI GEMINI AI ---
genai.configure(api_key=os.environ.get("GEMINI_APP_KEY"))
model = genai.GenerativeModel("gemini-2.5-flash", system_instruction="Anda adalah Asisten KTVDI. Jawab singkat dan jelas seputar TV Digital.")

# --- HELPER FUNCTIONS ---
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
    except: return ""

# --- ROUTES UTAMA ---

@app.route("/")
def home():
    # 1. Logika Statistik (Manual Loop agar akurat)
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

    # 2. Breaking News untuk Ticker (CNN RSS)
    breaking_news = []
    try:
        feed = feedparser.parse('https://www.cnnindonesia.com/teknologi/rss')
        breaking_news = [entry.title for entry in feed.entries[:5]]
    except:
        breaking_news = ["Selamat Datang di KTVDI", "Gunakan STB Bersertifikat Kominfo", "Cek Arah Antena di Menu Database"]

    return render_template('index.html', stats=stats, breaking_news=breaking_news)

@app.route('/', methods=['POST'])
def chatbot():
    data = request.get_json()
    prompt = data.get("prompt")
    try:
        response = model.generate_content(prompt)
        return jsonify({"response": response.text})
    except Exception as e:
        return jsonify({"error": str(e)})

# --- FITUR CCTV ---
@app.route("/cctv")
def cctv_page():
    return render_template("cctv.html")

# --- FITUR JADWAL SHOLAT (30 KOTA + KAB. PEKALONGAN) ---
@app.route("/jadwal-sholat")
def jadwal_sholat_page():
    # ID Kota berdasarkan referensi API MyQuran
    daftar_kota = [
        {"id": "1107", "nama": "Kab. Pekalongan"}, # REQUEST KHUSUS
        {"id": "1108", "nama": "Kota Pekalongan"},
        {"id": "1106", "nama": "Kab. Grobogan (Purwodadi)"},
        {"id": "1133", "nama": "Kota Semarang"},
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
        {"id": "1701", "nama": "Kota Denpasar"},
        {"id": "2301", "nama": "Kota Balikpapan"},
        {"id": "2302", "nama": "Kota Samarinda"},
        {"id": "0102", "nama": "Kota Banda Aceh"},
        {"id": "2001", "nama": "Kota Banjarmasin"},
        {"id": "0801", "nama": "Kota Bandar Lampung"},
        {"id": "2201", "nama": "Kota Pontianak"},
        {"id": "2601", "nama": "Kota Manado"},
        {"id": "3301", "nama": "Kota Jayapura"},
        {"id": "1901", "nama": "Kota Kupang"},
        {"id": "1801", "nama": "Kota Mataram"},
        {"id": "0301", "nama": "Kota Padang"},
        {"id": "1128", "nama": "Kota Tegal"}
    ]
    # Urutkan Alfabetis
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

# --- AUTH SYSTEM (LOGIN/REGISTER) ---
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
        return render_template('login.html', error="Username atau Password salah")
    return render_template('login.html')

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        if not ref: return "Database Error"
        user = request.form.get("username")
        email = request.form.get("email")
        
        if ref.child(f'users/{user}').get():
            flash("Username sudah dipakai", "error")
            return render_template("register.html")
            
        otp = str(random.randint(100000, 999999))
        ref.child(f'pending_users/{user}').set({
            "nama": request.form.get("nama"), "email": email, "password": hash_password(request.form.get("password")), "otp": otp
        })
        try:
            mail.send(Message("OTP KTVDI", recipients=[email], body=f"Kode OTP Anda: {otp}"))
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
        if str(ref.child(f'pending_users/{user}/otp').get()) == request.form.get("otp"):
            d = ref.child(f'pending_users/{user}').get()
            ref.child(f'users/{user}').set({"nama": d['nama'], "email": d['email'], "password": d['password'], "points": 10})
            ref.child(f'pending_users/{user}').delete()
            flash("Berhasil! Silakan login", "success")
            return redirect(url_for('login'))
        flash("OTP Salah", "error")
    return render_template("verify-register.html", username=user)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- DASHBOARD & DATABASE ---
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
        p, w, m = request.form.get('provinsi'), request.form.get('wilayah').replace(' ', ''), request.form.get('mux')
        s = sorted([x.strip() for x in request.form.get('siaran').split(',') if x.strip()])
        ref.child(f'siaran/{p}/{w}/{m}').set({"siaran": s, "last_updated_by": session['user'], "last_updated_date": datetime.now().strftime("%d-%m-%Y")})
        return redirect(url_for('dashboard'))
    prov = ref.child('provinsi').get() if ref else {}
    return render_template('add_data_form.html', provinsi_list=list(prov.values()) if prov else [])

@app.route("/edit_data/<provinsi>/<wilayah>/<mux>", methods=["GET", "POST"])
def edit_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        s = sorted([x.strip() for x in request.form.get('siaran').split(',') if x.strip()])
        ref.child(f'siaran/{provinsi}/{wilayah}/{mux}').update({"siaran": s, "last_updated_date": datetime.now().strftime("%d-%m-%Y")})
        return redirect(url_for('dashboard'))
    return render_template('edit_data_form.html', provinsi=provinsi, wilayah=wilayah, mux=mux)

@app.route("/delete_data/<provinsi>/<wilayah>/<mux>", methods=["POST"])
def delete_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    ref.child(f'siaran/{provinsi}/{wilayah}/{mux}').delete()
    return redirect(url_for('dashboard'))

# --- API HELPER (Dropdowns) ---
@app.route("/get_wilayah")
def get_wilayah():
    d = ref.child(f"siaran/{request.args.get('provinsi')}").get() if ref else {}
    return jsonify({"wilayah": list(d.keys()) if d else []})

@app.route("/get_mux")
def get_mux():
    d = ref.child(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}").get() if ref else {}
    return jsonify({"mux": list(d.keys()) if d else []})

@app.route("/get_siaran")
def get_siaran():
    return jsonify(ref.child(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}/{request.args.get('mux')}").get() if ref else {})

# --- PAGE LAIN ---
@app.route('/berita')
def berita():
    feed = feedparser.parse('https://www.cnnindonesia.com/teknologi/rss')
    articles = feed.entries
    page = request.args.get('page', 1, type=int)
    per_page = 6
    start = (page - 1) * per_page
    end = start + per_page
    total_pages = (len(articles) + per_page - 1) // per_page
    current = articles[start:end]
    for a in current:
        if hasattr(a, 'published_parsed'): a.time_since_published = time_since_published(a.published_parsed)
    return render_template('berita.html', articles=current, page=page, total_pages=total_pages)

@app.route('/about')
def about(): return render_template('about.html')

@app.route('/sitemap.xml')
def sitemap(): return send_from_directory('static', 'sitemap.xml')

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password(): return render_template("forgot-password.html")

if __name__ == "__main__":
    app.run(debug=True)
