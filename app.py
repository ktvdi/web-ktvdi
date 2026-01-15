import os
import hashlib
import firebase_admin
import random
import re
import pytz
import time
import requests
import feedparser
import xml.etree.ElementTree as ET
import google.generativeai as genai
from firebase_admin import credentials, db
from flask import Flask, request, render_template, redirect, url_for, session, flash, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
from flask_mail import Mail, Message
from datetime import datetime, timedelta
from collections import Counter

# --- KONFIGURASI AWAL ---
load_dotenv()

app = Flask(__name__)
CORS(app)

# 1. KONFIGURASI SESI (ANTI MENTAL)
# Kunci rahasia statis agar sesi login tidak hilang saat restart server
app.secret_key = "KTVDI_OFFICIAL_SECRET_KEY_FINAL_PRO_2026_SUPER_SECURE"
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 86400 # 24 Jam

# 2. KONEKSI FIREBASE (DATABASE)
try:
    if os.environ.get("FIREBASE_PRIVATE_KEY"):
        # Konfigurasi untuk Vercel (Environment Variable)
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
        # Konfigurasi Lokal
        cred = credentials.Certificate("credentials.json")
    
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred, {'databaseURL': os.environ.get('DATABASE_URL')})
    ref = db.reference('/')
    print("✅ STATUS: Database KTVDI Terhubung & Aman.")
except Exception as e:
    ref = None
    print(f"⚠️ STATUS: Mode Offline (Database Error: {e})")

# 3. KONFIGURASI EMAIL (SMTP GMAIL)
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME") 
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD") 
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")
mail = Mail(app)

# 4. KONFIGURASI AI (GEMINI)
GEMINI_KEY = "AIzaSyCqEFdnO3N0JBUBuaceTQLejepyDlK_eGU"
try:
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash") 
except: model = None

MODI_PROMPT = """
Anda adalah MODI, Asisten Virtual Resmi dari KTVDI (Komunitas TV Digital Indonesia).
Karakter: Profesional, Ramah, Solutif, dan Menggunakan Bahasa Indonesia Baku namun hangat.
Tugas: Menjawab pertanyaan seputar TV Digital, STB, Antena, dan Solusi Masalah Siaran.
"""

# ==========================================
# BAGIAN 5: FUNGSI BANTUAN (HELPERS)
# ==========================================

def hash_password(pw): 
    return hashlib.sha256(pw.encode()).hexdigest()

def normalize_input(text): 
    return text.strip().lower() if text else ""

def format_indo_date(time_struct):
    """Mengubah format waktu RSS menjadi format Indonesia Lengkap"""
    if not time_struct: 
        # Fallback ke waktu server saat ini
        return datetime.now().strftime("%A, %d %B %Y - %H:%M WIB")
    try:
        dt = datetime.fromtimestamp(time.mktime(time_struct))
        hari_list = ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu']
        bulan_list = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember']
        
        hari = hari_list[dt.weekday()]
        bulan = bulan_list[dt.month - 1]
        
        # Contoh: Jumat, 16 Januari 2026 - 10:30 WIB
        return f"{hari}, {dt.day} {bulan} {dt.year} - {dt.strftime('%H:%M')} WIB"
    except:
        return "Baru Saja"

def get_news_entries():
    """Mengambil berita dari berbagai sumber RSS dengan Header Anti-Blokir"""
    all_news = []
    
    # Header browser palsu agar tidak diblokir server berita
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    try:
        sources = [
            'https://news.google.com/rss/search?q=tv+digital+indonesia+kominfo&hl=id&gl=ID&ceid=ID:id',
            'https://www.cnnindonesia.com/nasional/rss',
            'https://www.antaranews.com/rss/tekno.xml',
            'https://www.suara.com/rss/tekno'
        ]
        
        for url in sources:
            try:
                # Request manual dengan headers
                response = requests.get(url, headers=headers, timeout=5)
                if response.status_code == 200:
                    feed = feedparser.parse(response.content)
                    if feed.entries:
                        for entry in feed.entries[:6]: # Batasi 6 berita per sumber
                            # Labeling Sumber Media Otomatis
                            if 'cnn' in url: entry['source_name'] = 'CNN Indonesia'
                            elif 'antara' in url: entry['source_name'] = 'Antara News'
                            elif 'suara' in url: entry['source_name'] = 'Suara.com'
                            else: entry['source_name'] = entry.get('source', {}).get('title', 'Google News')
                            
                            all_news.append(entry)
            except: continue
        
        # Sorting: Berita terbaru paling atas (Descending)
        all_news.sort(key=lambda x: x.published_parsed if x.get('published_parsed') else time.gmtime(0), reverse=True)
    except: pass
    
    if not all_news:
        t = datetime.now().timetuple()
        return [{'title': 'Selamat Datang di Portal Informasi KTVDI', 'link': '#', 'published_parsed': t, 'source_name': 'Info Resmi'}]
    
    return all_news[:24] # Tampilkan maksimal 24 berita

def time_since_published(published_time):
    try:
        now = datetime.now()
        pt = datetime(*published_time[:6])
        diff = now - pt
        if diff.days > 0: return f"{diff.days} hari lalu"
        if diff.seconds > 3600: return f"{diff.seconds//3600} jam lalu"
        return "Baru saja"
    except: return "Baru saja"

def get_quote_religi():
    return {
        "muslim": [
            "Maka dirikanlah shalat, sesungguhnya shalat itu adalah kewajiban yang ditentukan waktunya. (QS. An-Nisa: 103) 🕌",
            "Dan janganlah kamu memakan harta sesamamu dengan jalan yang batil. Hidup jujur tanpa korupsi itu berkah. (QS. Al-Baqarah: 188) ✨",
            "Kejujuran membawa ketenangan, sedangkan kebohongan membawa keraguan. Tetap amanah ya Kak! (HR. Tirmidzi) 🤲",
            "Jauhi korupsi sekecil apapun, karena setiap daging yang tumbuh dari yang haram, neraka lebih pantas baginya. 🔥"
        ],
        "universal": [
            "Integritas adalah melakukan hal yang benar, bahkan ketika tidak ada orang yang melihat. ❤️",
            "Kebahagiaan sejati dimulai dari hati yang jujur dan pikiran yang bersih. 🌱",
            "Kebaikan yang Anda tanam hari ini akan menjadi pohon peneduh bagi Anda di masa depan.",
            "Damai di dunia dimulai dari damai di hati dan kejujuran dalam perbuatan."
        ]
    }

# ==========================================
# BAGIAN 6: HALAMAN UTAMA (HOME)
# ==========================================

@app.route("/", methods=['GET'])
def home():
    stats = {'wilayah': 0, 'mux': 0, 'channel': 0}
    last_str = "-"
    if ref:
        try:
            siaran = ref.child('siaran').get() or {}
            for prov in siaran.values():
                if isinstance(prov, dict):
                    stats['wilayah'] += len(prov)
                    for wil in prov.values():
                        if isinstance(wil, dict):
                            stats['mux'] += len(wil)
                            for d in wil.values():
                                if 'siaran' in d: stats['channel'] += len(d['siaran'])
            last_str = datetime.now().strftime('%d-%m-%Y')
        except: pass
    return render_template('index.html', stats=stats, last_updated_time=last_str)

# ==========================================
# BAGIAN 7: OTENTIKASI (LOGIN/REGISTER/LUPA PASS)
# ==========================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        raw_input = request.form.get('username')
        password = request.form.get('password')
        hashed_pw = hash_password(password)
        clean_input = normalize_input(raw_input)
        
        if not ref: return render_template('login.html', error="Koneksi Database Terputus. Silakan coba lagi.")
        
        users = ref.child('users').get() or {}
        target_user = None; target_uid = None
        
        # Cek apakah input adalah Username ATAU Email
        for uid, data in users.items():
            if not isinstance(data, dict): continue
            if normalize_input(uid) == clean_input: # Cek ID/Username
                target_user = data; target_uid = uid; break
            if normalize_input(data.get('email')) == clean_input: # Cek Email
                target_user = data; target_uid = uid; break
        
        if target_user and target_user.get('password') == hashed_pw:
            session.permanent = True
            session['user'] = target_uid
            session['nama'] = target_user.get('nama', 'Pengguna')
            return redirect(url_for('dashboard'))
        
        return render_template('login.html', error="Identitas akun atau kata sandi tidak sesuai.")
    return render_template('login.html')

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        u = normalize_input(request.form.get("username"))
        e = normalize_input(request.form.get("email"))
        n = request.form.get("nama")
        p = request.form.get("password")
        
        if not ref: return "Database Error", 500
        users = ref.child("users").get() or {}
        
        if u in users:
            flash("Maaf Kak, Username ini sudah digunakan pengguna lain.", "error")
            return render_template("register.html")
        for uid, data in users.items():
            if normalize_input(data.get('email')) == e:
                flash("Email ini sudah terdaftar dalam sistem kami.", "error")
                return render_template("register.html")

        otp = str(random.randint(100000, 999999))
        expiry = time.time() + 60 # 1 Menit
        
        ref.child(f'pending_users/{u}').set({
            "nama": n, "email": e, "password": hash_password(p), "otp": otp, "expiry": expiry
        })
        
        try:
            msg = Message("Verifikasi Pendaftaran Akun KTVDI", recipients=[e])
            msg.body = f"""Yth. Bapak/Ibu/Saudara {n},

Terima kasih atas keinginan Anda untuk bergabung dengan Komunitas TV Digital Indonesia (KTVDI).

Guna menjamin keamanan data dan menyelesaikan proses registrasi, mohon masukkan Kode Verifikasi (OTP) berikut:

👉 {otp}

⚠️ PENTING: Kode ini bersifat rahasia dan hanya berlaku selama 1 MENIT. Mohon tidak memberikannya kepada siapapun.

Hormat Kami,
Tim Admin KTVDI
"""
            mail.send(msg)
            session["pending_username"] = u
            return redirect(url_for("verify_register"))
        except: 
            flash("Gagal mengirim email verifikasi. Pastikan email Anda aktif.", "error")
            
    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    u = session.get("pending_username")
    if not u: return redirect(url_for("register"))
    
    if request.method == "POST":
        p = ref.child(f'pending_users/{u}').get()
        if not p:
            flash("Sesi pendaftaran habis. Silakan daftar ulang.", "error")
            return redirect(url_for("register"))

        if time.time() > p.get('expiry', 0):
            flash("Kode OTP telah kedaluwarsa (Lewat 1 Menit).", "error")
            ref.child(f'pending_users/{u}').delete()
            return redirect(url_for("register"))

        if str(p.get('otp')).strip() == request.form.get("otp").strip():
            ref.child(f'users/{u}').set({
                "nama": p['nama'], "email": p['email'], "password": p['password'], "points": 0, "join_date": datetime.now().strftime("%d-%m-%Y")
            })
            ref.child(f'pending_users/{u}').delete()
            session.pop('pending_username', None)
            
            # Kirim Email Sambutan
            try:
                msg = Message("Selamat Datang di Ekosistem KTVDI", recipients=[p['email']])
                msg.body = f"""Yth. Kak {p['nama']},

Selamat! Akun KTVDI Anda telah berhasil diaktifkan sepenuhnya.

Kami sangat bangga menyambut Anda sebagai bagian dari keluarga besar Komunitas TV Digital Indonesia. Mari bersama-sama kita wujudkan penyiaran yang lebih baik.

Salam persahabatan,
Tim Manajemen KTVDI
"""
                mail.send(msg)
            except: pass
            
            flash("Registrasi Berhasil. Silakan Login.", "success")
            return redirect(url_for('login'))
        else:
            flash("Kode OTP yang dimasukkan salah.", "error")
    return render_template("verify-register.html", username=u)

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email_input = normalize_input(request.form.get("identifier"))
        users = ref.child("users").get() or {}
        found_uid = None
        target_name = "Sahabat KTVDI"
        
        for uid, user_data in users.items():
            if isinstance(user_data, dict) and normalize_input(user_data.get('email')) == email_input:
                found_uid = uid
                target_name = user_data.get('nama', 'Sahabat')
                break
        
        if found_uid:
            otp = str(random.randint(100000, 999999))
            expiry = time.time() + 60 # 1 Menit
            ref.child(f"otp/{found_uid}").set({"email": email_input, "otp": otp, "expiry": expiry})
            try:
                msg = Message("Keamanan Akun: Kode Reset Kata Sandi", recipients=[email_input])
                msg.body = f"""Yth. Kak {target_name},

Kami menerima permintaan untuk mengatur ulang kata sandi akun KTVDI Anda.

Silakan gunakan kode berikut (Berlaku 1 Menit):
🔒 {otp}

Jika Anda tidak merasa melakukan permintaan ini, mohon abaikan email ini.

Hormat kami,
Tim Keamanan KTVDI
"""
                mail.send(msg)
                session["reset_uid"] = found_uid
                return redirect(url_for("verify_otp"))
            except: flash("Gagal kirim email.", "error")
        else:
            flash("Email tidak ditemukan dalam sistem kami.", "error")
    return render_template("forgot-password.html")

@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    uid = session.get("reset_uid")
    if not uid: return redirect(url_for("forgot_password"))
    if request.method == "POST":
        data = ref.child(f"otp/{uid}").get()
        if not data or time.time() > data.get('expiry', 0):
            flash("Kode verifikasi telah kedaluwarsa.", "error")
            return redirect(url_for("forgot_password"))
        if str(data.get("otp")).strip() == request.form.get("otp").strip():
            session['reset_verified'] = True
            return redirect(url_for("reset_password"))
        flash("Kode OTP tidak valid.", "error")
    return render_template("verify-otp.html")

@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    if not session.get('reset_verified'): return redirect(url_for('login'))
    uid = session.get("reset_uid")
    if request.method == "POST":
        pw = request.form.get("password")
        ref.child(f"users/{uid}").update({"password": hash_password(pw)})
        ref.child(f"otp/{uid}").delete()
        session.clear()
        flash("Kata sandi berhasil diperbarui. Silakan login.", "success")
        return redirect(url_for('login'))
    return render_template("reset-password.html")

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ==========================================
# BAGIAN 8: FITUR UTAMA & BERITA (FIXED)
# ==========================================

@app.route('/berita')
def berita_page():
    try:
        # Ambil berita dengan fungsi helper yang sudah diperbaiki (headers, sorting, date format)
        entries = get_news_entries()
        
        # Pagination Logic
        page = request.args.get('page', 1, type=int)
        per_page = 9
        start = (page - 1) * per_page
        end = start + per_page
        current = entries[start:end]
        
        # Proses Data untuk Tampilan
        for a in current:
            # 1. Format Tanggal
            if isinstance(a, dict) and 'published_parsed' in a:
                 a['formatted_date'] = format_indo_date(a['published_parsed'])
                 a['time_since_published'] = time_since_published(a['published_parsed'])
            else:
                 # Fallback
                 a['formatted_date'] = datetime.now().strftime("%A, %d %B %Y - %H:%M WIB")
                 a['time_since_published'] = "Baru saja"
            
            # 2. Gambar
            a['image'] = None
            if 'media_content' in a: a['image'] = a['media_content'][0]['url']
            elif 'links' in a:
                for link in a['links']:
                    if 'image' in link.get('type',''): a['image'] = link.get('href')
        
        total_pages = (len(entries)//per_page) + 1
        return render_template('berita.html', articles=current, page=page, total_pages=total_pages)
    except Exception as e: 
        print(f"Error Berita: {e}")
        return render_template('berita.html', articles=[], page=1, total_pages=1)

@app.route("/jadwal-sholat")
def jadwal_sholat_page():
    kota = ["Ambon", "Balikpapan", "Banda Aceh", "Bandar Lampung", "Bandung", "Banjar", "Banjarbaru", "Banjarmasin", "Batam", "Batu",
        "Bau-Bau", "Bekasi", "Bengkulu", "Bima", "Binjai", "Bitung", "Blitar", "Bogor", "Bontang", "Bukittinggi",
        "Cilegon", "Cimahi", "Cirebon", "Denpasar", "Depok", "Dumai", "Garut", "Gorontalo", "Gunungsitoli", "Jakarta", "Jambi",
        "Jayapura", "Kediri", "Kendari", "Kotamobagu", "Kupang", "Langsa", "Lhokseumawe", "Lubuklinggau", "Madiun", "Magelang",
        "Makassar", "Malang", "Manado", "Mataram", "Medan", "Metro", "Mojokerto", "Padang", "Padangpanjang", "Padangsidempuan",
        "Pagar Alam", "Palangkaraya", "Palembang", "Palopo", "Palu", "Pangkal Pinang", "Parepare", "Pariaman", "Pasuruan", "Payakumbuh",
        "Pekalongan", "Pekanbaru", "Pematangsiantar", "Pontianak", "Prabumulih", "Probolinggo", "Purwokerto", "Purwodadi", "Sabang", "Salatiga",
        "Samarinda", "Sawahlunto", "Semarang", "Serang", "Sibolga", "Singkawang", "Solok", "Sorong", "Subulussalam", "Sukabumi",
        "Surabaya", "Surakarta (Solo)", "Tangerang", "Tangerang Selatan", "Tanjungbalai", "Tanjungpinang", "Tarakan", "Tasikmalaya", "Tebing Tinggi", "Tegal",
        "Ternate", "Tidore Kepulauan", "Tomohon", "Tual", "Yogyakarta"
    ]
    quotes = get_quote_religi()
    
    # Notifikasi Email Religi (Sekali per Sesi Login)
    if 'user' in session and not session.get('religi_notif_sent'):
        try:
            users = ref.child('users').get() or {}
            user_data = users.get(session['user'])
            if user_data and user_data.get('email'):
                nama = user_data.get('nama', 'Sahabat')
                msg = Message("🕌 Pengingat Kebaikan - KTVDI", recipients=[user_data['email']])
                msg.body = f"""Assalamualaikum Wr. Wb.
Yth. Kak {nama},

Terima kasih telah menggunakan fitur Religi KTVDI hari ini.

"Sesungguhnya shalat itu mencegah dari (perbuatan-perbuatan) keji dan mungkar." (QS. Al-Ankabut: 45)

Semoga hari Anda diberkahi dan dilancarkan rezekinya. Aamiin.

Salam santun,
Tim Religi KTVDI
"""
                mail.send(msg)
                session['religi_notif_sent'] = True
        except: pass

    return render_template("jadwal-sholat.html", daftar_kota=sorted(kota), quotes=quotes)

# ==========================================
# BAGIAN 9: DASHBOARD & CRUD (DATA CONTROL)
# ==========================================

@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    data = ref.child("provinsi").get() or {}
    # Jika kosong, tetap render halaman agar user bisa add data
    return render_template("dashboard.html", name=session.get('nama'), provinsi_list=list(data.values()))

@app.route("/daftar-siaran")
def daftar_siaran():
    data = ref.child("provinsi").get() or {}
    return render_template("daftar-siaran.html", provinsi_list=list(data.values()))

@app.route("/add_data", methods=["GET", "POST"])
def add_data():
    if 'user' not in session: return redirect(url_for('login'))
    
    # List Provinsi untuk Dropdown
    prov_data = ref.child("provinsi").get() or {}
    provinsi_list = list(prov_data.values()) if prov_data else ["DKI Jakarta", "Jawa Barat", "Jawa Tengah", "Jawa Timur"]

    if request.method == "POST":
        p = request.form.get("provinsi")
        w = request.form.get("wilayah")
        m = request.form.get("mux")
        s = request.form.get("siaran")
        
        if p and w and m and s:
            siaran_list = [ch.strip() for ch in s.split(',')]
            data_new = {
                "siaran": siaran_list,
                "last_updated_by_name": session.get('nama'),
                "last_updated_by_username": session.get('user'),
                "last_updated_date": datetime.now().strftime("%d-%m-%Y"),
                "last_updated_time": datetime.now().strftime("%H:%M:%S WIB")
            }
            
            # Simpan ke Firebase
            ref.child(f"siaran/{p}/{w}/{m}").set(data_new)
            # Pastikan provinsi tercatat
            ref.child(f"provinsi/{p}").set(p)
            
            flash("Data berhasil ditambahkan!", "success")
            return redirect(url_for('dashboard'))
        else:
            flash("Mohon lengkapi semua data.", "error")

    return render_template("add_data_form.html", provinsi_list=sorted(provinsi_list))

@app.route("/edit_data/<provinsi>/<wilayah>/<mux>", methods=["GET", "POST"])
def edit_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    
    # Ambil data lama
    curr_data = ref.child(f"siaran/{provinsi}/{wilayah}/{mux}").get()
    
    if request.method == "POST":
        s = request.form.get("siaran")
        siaran_list = [ch.strip() for ch in s.split(',')]
        
        ref.child(f"siaran/{provinsi}/{wilayah}/{mux}").update({
            "siaran": siaran_list,
            "last_updated_by_name": session.get('nama'),
            "last_updated_date": datetime.now().strftime("%d-%m-%Y"),
            "last_updated_time": datetime.now().strftime("%H:%M:%S WIB")
        })
        flash("Data berhasil diperbarui!", "success")
        return redirect(url_for('dashboard'))

    # Render form edit
    siaran_str = ", ".join(curr_data.get('siaran', [])) if curr_data else ""
    return render_template("add_data_form.html", 
                           edit_mode=True,
                           curr_provinsi=provinsi, curr_wilayah=wilayah, curr_mux=mux, curr_siaran=siaran_str,
                           provinsi_list=[provinsi]) 

@app.route("/delete_data/<provinsi>/<wilayah>/<mux>", methods=["POST"])
def delete_data(provinsi, wilayah, mux):
    if 'user' in session: 
        try:
            ref.child(f"siaran/{provinsi}/{wilayah}/{mux}").delete()
            return jsonify({"status": "success"}), 200
        except: return jsonify({"status": "error"}), 500
    return jsonify({"status": "unauthorized"}), 403

# API Helper untuk Dashboard (AJAX)
@app.route("/get_wilayah")
def get_wilayah(): return jsonify({"wilayah": list((ref.child(f"siaran/{request.args.get('provinsi')}").get() or {}).keys())})
@app.route("/get_mux")
def get_mux(): return jsonify({"mux": list((ref.child(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}").get() or {}).keys())})
@app.route("/get_siaran")
def get_siaran(): return jsonify(ref.child(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}/{request.args.get('mux')}").get() or {})

# ==========================================
# BAGIAN 10: FITUR AI & LAINNYA
# ==========================================

@app.route('/api/chat', methods=['POST'])
def chatbot_api():
    data = request.get_json()
    if not model: return jsonify({"response": "Maaf Kak, sistem AI sedang offline."})
    try:
        full_prompt = f"""
        {MODI_PROMPT}
        Pertanyaan User: {data.get('prompt')}
        Jawaban (Jelas, Sopan, Solutif):
        """
        response = model.generate_content(full_prompt)
        return jsonify({"response": response.text})
    except: return jsonify({"response": "Maaf Kak, Modi sedang sibuk."})

@app.route("/api/cron/daily-blast", methods=['GET'])
def trigger_daily_blast():
    try:
        users = ref.child('users').get() or {}
        news = get_news_entries()
        news_summary = "\n".join([f"- {i['title']} ({i['source_name']})" for i in news[:4]])
        date_str = datetime.now().strftime("%d %B %Y")
        
        prompt = f"""
        Buatkan konten EMAIL HARIAN (Newsletter) resmi untuk anggota komunitas KTVDI.
        DATA BERITA: {news_summary}
        INSTRUKSI:
        1. Nada: Profesional, Elegan, Peduli (Empatik).
        2. Struktur: Sapaan (Yth. [NAMA_USER]), Rangkuman Berita, Info Cuaca Umum, Pesan Integritas/Anti-Korupsi.
        3. Penutup resmi Tim Humas KTVDI.
        """
        
        email_content = "Konten sedang disiapkan."
        if model:
            try: email_content = model.generate_content(prompt).text
            except: pass
        
        count = 0
        for uid, user in users.items():
            if isinstance(user, dict) and user.get('email'):
                try:
                    nama = user.get('nama', 'Anggota KTVDI')
                    final_body = email_content.replace("[NAMA_USER]", nama).replace("[Nama User]", nama)
                    if "[NAMA_USER]" not in email_content: final_body = f"Yth. {nama},\n\n" + final_body
                    
                    msg = Message(f"🇮🇩 Warta Eksklusif KTVDI - {date_str}", recipients=[user['email']])
                    msg.body = final_body
                    mail.send(msg)
                    count += 1
                except: pass
        return jsonify({"status": "Success", "sent": count}), 200
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route("/api/news-ticker")
def news_ticker():
    entries = get_news_entries()
    titles = [e.get('title') for e in entries]
    return jsonify(titles)

@app.route('/about')
def about(): return render_template('about.html')
@app.route('/cctv')
def cctv_page(): return render_template("cctv.html")
@app.route('/sitemap.xml')
def sitemap(): return send_from_directory('static', 'sitemap.xml')

if __name__ == "__main__":
    app.run(debug=True)
