import os
import json
import hashlib
import firebase_admin
import random
import re
import pytz
import requests
import feedparser
import google.generativeai as genai
import csv
import io
from bs4 import BeautifulSoup
from newsapi import NewsApiClient
from firebase_admin import credentials, db
from flask import Flask, request, render_template, redirect, url_for, session, flash, jsonify, send_file
from flask_cors import CORS
from dotenv import load_dotenv
from flask_mail import Mail, Message
from datetime import datetime
from collections import Counter

# Muat environment local jika ada
load_dotenv()

app = Flask(__name__)
CORS(app)

# Secret Key
app.secret_key = os.getenv('SECRET_KEY', 'b/g5n!o0?hs&dm!fn8md7')

# --- BAGIAN KRUSIAL: KONEKSI FIREBASE (VERCEL FRIENDLY) ---
try:
    if not firebase_admin._apps:
        # 1. Coba ambil dari Environment Variable Vercel (Prioritas Utama)
        firebase_creds_json = os.getenv('FIREBASE_CREDENTIALS')
        
        if firebase_creds_json:
            # Bersihkan string jika ada karakter aneh akibat copy-paste
            cred_dict = json.loads(firebase_creds_json)
            cred = credentials.Certificate(cred_dict)
            print("✅ Menggunakan Kredensial dari Environment Variable")
        
        # 2. Jika tidak ada Env, cari file fisik (Hanya untuk Localhost)
        elif os.path.exists('credentials.json'):
            cred = credentials.Certificate('credentials.json')
            print("✅ Menggunakan File credentials.json (Local Mode)")
        
        else:
            raise ValueError("Kredensial Firebase tidak ditemukan (Cek Env Var / File)")

        # Inisialisasi App
        firebase_admin.initialize_app(cred, {
            'databaseURL': 'https://website-ktvdi-default-rtdb.firebaseio.com/'
        })

    ref = db.reference('/')

except Exception as e:
    print(f"❌ DATABASE ERROR: {e}")
    # Jangan crash app, set ref None agar web tetap nyala menampilkan pesan error
    ref = None

# --- KONFIGURASI EMAIL ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'kom.tvdigitalid@gmail.com'
app.config['MAIL_PASSWORD'] = 'lvjo uwrj sbiy ggkg'
app.config['MAIL_DEFAULT_SENDER'] = 'kom.tvdigitalid@gmail.com'

try:
    mail = Mail(app)
except:
    mail = None

# API Keys
NEWS_API_KEY = os.getenv('NEWS_API_KEY')
try:
    newsapi = NewsApiClient(api_key=NEWS_API_KEY) if NEWS_API_KEY else None
except:
    newsapi = None

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
try:
    model = genai.GenerativeModel("gemini-2.5-flash")
except:
    model = None

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
    except:
        return ""

def get_actual_url_from_google_news(link):
    try:
        response = requests.get(link, timeout=2)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            a = soup.find('a', {'class': 'DY5T1d'})
            return a['href'] if a else link
    except:
        pass
    return link

# --- ROUTES ---

@app.route("/")
def home():
    # Jika database error, tampilkan pesan jelas bukan 500
    if not ref:
        return """
        <div style="font-family:sans-serif; text-align:center; padding:50px;">
            <h1>⚠️ Database Belum Terhubung</h1>
            <p>Aplikasi berjalan, tapi gagal akses Firebase.</p>
            <p><strong>Solusi:</strong> Masukkan isi file <code>credentials.json</code> ke Environment Variables Vercel dengan nama <code>FIREBASE_CREDENTIALS</code>.</p>
        </div>
        """, 200

    # Logika normal
    try:
        siaran_data = ref.child('siaran').get() or {}
        wilayah_count = 0
        mux_count = 0
        siaran_count = 0
        
        for prov in siaran_data.values():
            if isinstance(prov, dict):
                wilayah_count += len(prov)
                for wil in prov.values():
                    if isinstance(wil, dict):
                        mux_count += len(wil)
                        for mux in wil.values():
                            if 'siaran' in mux:
                                siaran_count += len(mux['siaran'])
        
        return render_template('index.html', stats={'wilayah': wilayah_count, 'mux': mux_count, 'channel': siaran_count})
    except Exception as e:
        return f"Render Error: {e}", 200

@app.route('/', methods=['POST'])
def chatbot():
    data = request.get_json()
    try:
        if model:
            response = model.generate_content(data.get("prompt"))
            return jsonify({"response": response.text})
        return jsonify({"error": "AI belum siap"})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/cctv")
def cctv_page():
    return render_template("cctv.html")

# --- AUTH ROUTES ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if not ref: return render_template('login.html', error="DB Error")
        user = request.form.get('username', '').strip()
        pw = hashlib.sha256(request.form.get('password', '').strip().encode()).hexdigest()
        
        try:
            udata = ref.child(f'users/{user}').get()
            if udata and udata.get('password') == pw:
                session['user'] = user
                session['nama'] = udata.get('nama')
                return redirect(url_for('dashboard'))
            error = "Username/Password salah."
        except:
            error = "Gagal koneksi."
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        if not ref: return "DB Error", 500
        nama = request.form.get("nama")
        email = request.form.get("email")
        username = request.form.get("username")
        password = request.form.get("password")

        users = ref.child('users').get() or {}
        if username in users:
            flash("Username sudah ada", "error")
            return render_template("register.html")

        otp = str(random.randint(100000, 999999))
        hashed = hash_password(password)
        
        ref.child(f'pending_users/{username}').set({
            "nama": nama, "email": email, "password": hashed, "otp": otp
        })

        try:
            msg = Message("Kode Verifikasi", recipients=[email])
            msg.body = f"Kode OTP: {otp}"
            mail.send(msg)
            session['pending_username'] = username
            return redirect(url_for('verify_register'))
        except:
            flash("Gagal kirim email", "error")
    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    user = session.get('pending_username')
    if not user: return redirect(url_for('register'))
    if request.method == "POST":
        otp = request.form.get("otp")
        pending = ref.child(f'pending_users/{user}').get()
        if pending and str(pending['otp']) == str(otp):
            ref.child(f'users/{user}').set({
                "nama": pending['nama'], "email": pending['email'],
                "password": pending['password'], "points": 0
            })
            ref.child(f'pending_users/{user}').delete()
            session.pop('pending_username', None)
            flash("Berhasil!", "success")
            return redirect(url_for('login'))
        flash("OTP Salah", "error")
    return render_template("verify-register.html", username=user)

# --- FORGOT PASSWORD ---
@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("identifier")
        users = ref.child('users').get() or {}
        uid = next((k for k, v in users.items() if v.get('email') == email), None)
        
        if uid:
            otp = str(random.randint(100000, 999999))
            ref.child(f'otp/{uid}').set({"email": email, "otp": otp})
            try:
                msg = Message("Reset Password", recipients=[email])
                msg.body = f"OTP: {otp}"
                mail.send(msg)
                session['reset_uid'] = uid
                return redirect(url_for('verify_otp'))
            except:
                flash("Gagal email", "error")
        else:
            flash("Email tidak ditemukan", "error")
    return render_template("forgot-password.html")

@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    uid = session.get('reset_uid')
    if not uid: return redirect(url_for('forgot_password'))
    if request.method == "POST":
        if request.form.get("otp") == str(ref.child(f'otp/{uid}/otp').get()):
            return redirect(url_for('reset_password'))
        flash("OTP Salah", "error")
    return render_template("verify-otp.html")

@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    uid = session.get('reset_uid')
    if not uid: return redirect(url_for('forgot_password'))
    if request.method == "POST":
        pw = hash_password(request.form.get("password"))
        ref.child(f'users/{uid}').update({"password": pw})
        ref.child(f'otp/{uid}').delete()
        session.pop('reset_uid', None)
        flash("Sukses", "success")
        return redirect(url_for('login'))
    return render_template("reset-password.html")

# --- DASHBOARD & CRUD ---
@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    prov = ref.child('provinsi').get() or {} if ref else {}
    return render_template("dashboard.html", name=session.get('nama'), provinsi_list=list(prov.values()))

@app.route("/daftar-siaran")
def daftar_siaran():
    prov = ref.child('provinsi').get() or {} if ref else {}
    return render_template("daftar-siaran.html", provinsi_list=list(prov.values()))

@app.route('/berita')
def berita():
    try:
        feed = feedparser.parse('https://news.google.com/rss/search?q=tv+digital&hl=id&gl=ID&ceid=ID:id')
        return render_template('berita.html', articles=feed.entries[:10], page=1, total_pages=1)
    except:
        return render_template('berita.html', articles=[])

@app.route("/add_data", methods=["GET", "POST"])
def add_data():
    if 'user' not in session: return redirect(url_for('login'))
    provs = list((ref.child('provinsi').get() or {}).values()) if ref else []
    
    if request.method == 'POST':
        p, w, m = request.form['provinsi'], request.form['wilayah'], request.form['mux']
        s = sorted([x.strip() for x in request.form['siaran'].split(',') if x.strip()])
        w = re.sub(r'\s*-\s*', '-', w.strip())
        
        if all([p, w, m, s]):
            ref.child(f'siaran/{p}/{w}/{m.strip()}').set({
                "siaran": s,
                "last_updated_by": session.get('user'),
                "last_updated_date": datetime.now().strftime("%d-%m-%Y")
            })
            return redirect(url_for('dashboard'))
    return render_template('add_data_form.html', provinsi_list=provs)

# API Helpers
@app.route("/get_wilayah")
def get_wilayah():
    d = ref.child(f"siaran/{request.args.get('provinsi')}").get() or {} if ref else {}
    return jsonify({"wilayah": list(d.keys())})

@app.route("/get_mux")
def get_mux():
    d = ref.child(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}").get() or {} if ref else {}
    return jsonify({"mux": list(d.keys())})

@app.route("/get_siaran")
def get_siaran():
    d = ref.child(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}/{request.args.get('mux')}").get() or {} if ref else {}
    return jsonify(d)

if __name__ == "__main__":
    app.run(debug=True)
