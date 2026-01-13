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
        # Konfigurasi Vercel
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
        # Konfigurasi Localhost
        cred = credentials.Certificate("credentials.json")

    firebase_admin.initialize_app(cred, {
        'databaseURL': os.environ.get('DATABASE_URL')
    })
    ref = db.reference('/')
    print("✅ Firebase Connected")
except Exception as e:
    print("❌ Firebase Error:", str(e))
    ref = None

# --- 2. CONFIG EMAIL ---
app.config['MAIL_SERVER'] = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
app.config['MAIL_PORT'] = int(os.environ.get("MAIL_PORT", 587))
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD")
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")
mail = Mail(app)

# --- 3. CONFIG GEMINI AI ---
genai.configure(api_key=os.environ.get("GEMINI_APP_KEY"))
model = genai.GenerativeModel("gemini-2.5-flash", system_instruction="Anda adalah Asisten KTVDI. Jawab singkat padat seputar TV Digital.")

# --- HELPER ---
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def time_since_published(published_time):
    now = datetime.now()
    try:
        pt = datetime(*published_time[:6])
        diff = now - pt
        if diff.days > 0: return f"{diff.days} hari lalu"
        if diff.seconds > 3600: return f"{diff.seconds//3600} jam lalu"
        return "Baru saja"
    except: return ""

# --- ROUTES ---

@app.route("/")
def home():
    # Logika Statistik Manual
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

    # Berita Ticker (CNN RSS)
    breaking_news = []
    try:
        feed = feedparser.parse('https://www.cnnindonesia.com/teknologi/rss')
        breaking_news = [e.title for e in feed.entries[:5]]
    except:
        breaking_news = ["Selamat Datang di KTVDI", "Pastikan STB Bersertifikat Kominfo"]

    return render_template('index.html', stats=stats, breaking_news=breaking_news)

@app.route('/', methods=['POST'])
def chatbot():
    data = request.get_json()
    try:
        res = model.generate_content(data.get("prompt"))
        return jsonify({"response": res.text})
    except: return jsonify({"error": "AI Busy"})

# --- FITUR CCTV ---
@app.route("/cctv")
def cctv_page(): return render_template("cctv.html")

# --- FITUR JADWAL SHOLAT (50 KOTA + IMSAK) ---
@app.route("/jadwal-sholat")
def jadwal_sholat_page():
    # Daftar 50 Kota Lengkap
    daftar_kota = [
        {"id": "1301", "nama": "DKI Jakarta"},
        {"id": "1107", "nama": "Kab. Pekalongan"},
        {"id": "1108", "nama": "Kota Pekalongan"},
        {"id": "1106", "nama": "Kab. Grobogan (Purwodadi)"},
        {"id": "1133", "nama": "Kota Semarang"},
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
        {"id": "1128", "nama": "Kota Tegal"},
        {"id": "1202", "nama": "Kab. Bogor (Cibinong)"},
        {"id": "1271", "nama": "Kota Bogor"},
        {"id": "1601", "nama": "Kab. Sidoarjo"},
        {"id": "1209", "nama": "Kab. Cirebon"},
        {"id": "1274", "nama": "Kota Cirebon"},
        {"id": "1121", "nama": "Kab. Demak"},
        {"id": "1122", "nama": "Kab. Semarang (Ungaran)"},
        {"id": "1110", "nama": "Kab. Batang"},
        {"id": "1125", "nama": "Kab. Pemalang"},
        {"id": "3101", "nama": "Kota Ambon"},
        {"id": "2401", "nama": "Kota Gorontalo"},
        {"id": "2801", "nama": "Kota Palu"},
        {"id": "2501", "nama": "Kota Kendari"},
        {"id": "0501", "nama": "Kota Jambi"},
        {"id": "0701", "nama": "Kota Bengkulu"},
        {"id": "0901", "nama": "Kota Pangkal Pinang"},
        {"id": "1001", "nama": "Kota Tanjung Pinang"},
        {"id": "1401", "nama": "Kota Serang"},
        {"id": "2901", "nama": "Kota Mamuju"}
    ]
    return render_template("jadwal-sholat.html", daftar_kota=sorted(daftar_kota, key=lambda x: x['nama']))

@app.route("/api/jadwal-sholat/<id_kota>")
def get_jadwal_api(id_kota):
    try:
        t = datetime.now().strftime("%Y/%m/%d")
        r = requests.get(f"https://api.myquran.com/v2/sholat/jadwal/{id_kota}/{t}", timeout=5)
        return jsonify(r.json())
    except Exception as e: return jsonify({"status": "error", "message": str(e)})

# --- AUTH ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user, pw = request.form.get('username'), hash_password(request.form.get('password'))
        u = ref.child(f'users/{user}').get() if ref else None
        if u and u.get('password') == pw:
            session['user'], session['nama'] = user, u.get('nama')
            return redirect(url_for('dashboard'))
        return render_template('login.html', error="Gagal Login")
    return render_template('login.html')

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        u, e, p = request.form.get("username"), request.form.get("email"), request.form.get("password")
        if ref.child(f'users/{u}').get():
            flash("Username dipakai", "error"); return render_template("register.html")
        otp = str(random.randint(100000, 999999))
        ref.child(f'pending_users/{u}').set({"nama":request.form.get("nama"), "email":e, "password":hash_password(p), "otp":otp})
        try:
            mail.send(Message("OTP KTVDI", recipients=[e], body=f"OTP: {otp}"))
            session['pending_username'] = u
            return redirect(url_for("verify_register"))
        except: flash("Gagal email", "error")
    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    u = session.get('pending_username')
    if not u: return redirect(url_for('register'))
    if request.method == "POST":
        p = ref.child(f'pending_users/{u}').get()
        if p and str(p['otp']) == request.form.get("otp"):
            ref.child(f'users/{u}').set({"nama":p['nama'], "email":p['email'], "password":p['password'], "points":0})
            ref.child(f'pending_users/{u}').delete()
            return redirect(url_for('login'))
        flash("OTP Salah", "error")
    return render_template("verify-register.html", username=u)

# --- DASHBOARD & DATABASE ---
@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    return render_template("dashboard.html", name=session.get('nama'), provinsi_list=list((ref.child('provinsi').get() or {}).values()))

@app.route("/daftar-siaran")
def daftar_siaran():
    return render_template("daftar-siaran.html", provinsi_list=list((ref.child('provinsi').get() or {}).values()))

@app.route("/add_data", methods=["GET", "POST"])
def add_data():
    if 'user' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        p, w, m, s = request.form['provinsi'], request.form['wilayah'].replace(' ', ''), request.form['mux'], request.form['siaran']
        sl = sorted([x.strip() for x in s.split(',') if x.strip()])
        ref.child(f'siaran/{p}/{w}/{m}').set({"siaran": sl, "last_updated_by": session['user'], "last_updated_date": datetime.now().strftime("%d-%m-%Y")})
        return redirect(url_for('dashboard'))
    return render_template('add_data_form.html', provinsi_list=list((ref.child('provinsi').get() or {}).values()))

@app.route("/edit_data/<provinsi>/<wilayah>/<mux>", methods=["GET", "POST"])
def edit_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        sl = sorted([x.strip() for x in request.form['siaran'].split(',') if x.strip()])
        ref.child(f'siaran/{provinsi}/{wilayah}/{mux}').update({"siaran": sl, "last_updated_date": datetime.now().strftime("%d-%m-%Y")})
        return redirect(url_for('dashboard'))
    return render_template('edit_data_form.html', provinsi=provinsi, wilayah=wilayah, mux=mux)

@app.route("/delete_data/<provinsi>/<wilayah>/<mux>", methods=["POST"])
def delete_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    ref.child(f'siaran/{provinsi}/{wilayah}/{mux}').delete()
    return redirect(url_for('dashboard'))

# --- API HELPER ---
@app.route("/get_wilayah")
def get_wilayah(): return jsonify({"wilayah": list((ref.child(f"siaran/{request.args.get('provinsi')}").get() or {}).keys())})
@app.route("/get_mux")
def get_mux(): return jsonify({"mux": list((ref.child(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}").get() or {}).keys())})
@app.route("/get_siaran")
def get_siaran(): return jsonify(ref.child(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}/{request.args.get('mux')}").get() or {})

# --- PAGE LAIN ---
@app.route('/berita')
def berita():
    feed = feedparser.parse('https://www.cnnindonesia.com/teknologi/rss')
    curr = feed.entries[:10]
    for a in curr: 
        if hasattr(a,'published_parsed'): a.time_since_published = time_since_published(a.published_parsed)
    return render_template('berita.html', articles=curr, page=1, total_pages=1)

@app.route('/about')
def about(): return render_template('about.html')

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

@app.route('/sitemap.xml')
def sitemap(): return send_from_directory('static', 'sitemap.xml')

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password(): return render_template("forgot-password.html")

if __name__ == "__main__":
    app.run(debug=True)
