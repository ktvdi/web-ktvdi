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
app.secret_key = "KTVDI_OFFICIAL_SECRET_KEY_FINAL_PRO_2026_SUPER_SECURE"
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 86400 # 24 Jam

# 2. KONEKSI FIREBASE (DATABASE)
try:
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
# 5. FUNGSI BANTUAN (HELPERS)
# ==========================================

def hash_password(pw): 
    return hashlib.sha256(pw.encode()).hexdigest()

def normalize_input(text): 
    return text.strip().lower() if text else ""

def format_indo_date(time_struct):
    if not time_struct: 
        return datetime.now().strftime("%A, %d %B %Y - %H:%M WIB")
    try:
        dt = datetime.fromtimestamp(time.mktime(time_struct))
        hari_list = ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu']
        bulan_list = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember']
        hari = hari_list[dt.weekday()]
        bulan = bulan_list[dt.month - 1]
        return f"{hari}, {dt.day} {bulan} {dt.year} - {dt.strftime('%H:%M')} WIB"
    except:
        return "Baru Saja"

def get_news_entries():
    """Mengambil berita Google News (Top Stories Indonesia)"""
    all_news = []
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    try:
        sources = [
            'https://news.google.com/rss?hl=id&gl=ID&ceid=ID:id', 
            'https://www.cnnindonesia.com/nasional/rss',
            'https://www.antaranews.com/rss/top-news.xml'
        ]
        
        for url in sources:
            try:
                response = requests.get(url, headers=headers, timeout=5)
                if response.status_code == 200:
                    feed = feedparser.parse(response.content)
                    if feed.entries:
                        for entry in feed.entries[:8]: 
                            if 'cnn' in url: entry['source_name'] = 'CNN Indonesia'
                            elif 'antara' in url: entry['source_name'] = 'Antara News'
                            else: entry['source_name'] = entry.get('source', {}).get('title', 'Google News')
                            all_news.append(entry)
            except: continue
        
        all_news.sort(key=lambda x: x.published_parsed if x.get('published_parsed') else time.gmtime(0), reverse=True)
    except: pass
    
    if not all_news:
        t = datetime.now().timetuple()
        return [{'title': 'Selamat Datang di Portal Informasi KTVDI', 'link': '#', 'published_parsed': t, 'source_name': 'Info Resmi'}]
    
    return all_news[:24]

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
            "Maka dirikanlah shalat... (QS. An-Nisa: 103)",
            "Jauhi korupsi sekecil apapun..."
        ],
        "universal": [
            "Integritas adalah melakukan hal yang benar...",
            "Damai di dunia dimulai dari damai di hati..."
        ]
    }

def get_smart_fallback_response(text):
    """Template Jawaban Offline ala 'Ndan' yang Humanis"""
    text = text.lower()
    
    if any(x in text for x in ['pagi', 'siang', 'sore', 'malam', 'halo', 'hai', 'assalam']):
        return "<b>Siap! Selamat Pagi/Siang/Malam Ndan!</b> Monitor situasi aman terkendali. Ada yang bisa kami bantu seputar TV Digital atau sekadar teman ngobrol? <b>Ganti!</b> 👮‍♂️"
    
    if any(x in text for x in ['sepi', 'sendiri', 'teman', 'curhat', 'sedih', 'galau', 'bosan']):
        return "<b>Izin masuk Ndan!</b> Jangan merasa sendiri. Kami di sini standby 24 jam siap menemani. Tetap semangat, jaga hati tetap <b>86</b>! Cerita saja, kami monitor. Kopi mana kopi? ☕📻"
    
    if any(x in text for x in ['sabuk', 'belt', 'safety', 'aman', 'selamat']):
        return "<b>Siap! Izin mengingatkan Ndan.</b> Safety belt itu kebutuhan, bukan hiasan! <i>Klik</i>, aman, selamat sampai tujuan. Keluarga menunggu di rumah. Utamakan keselamatan sebagai kebutuhan. <b>Salam Presisi!</b> 🚗"
    
    if any(x in text for x in ['digital', 'analog', 'bersih', 'semut', 'pindah']):
        return "<b>Lapor!</b> TV Digital adalah masa depan Ndan. Gambar bersih, suara jernih, teknologi canggih. Segera migrasi, tinggalkan semut di masa lalu! Jangan lupa pasang STB kalau TV belum support. <b>Laksanakan!</b> 📺"
    
    if any(x in text for x in ['antena', 'sinyal', 'arah', 'hilang']):
        return "<b>Siap Ndan!</b> Untuk hasil maksimal, gunakan <b>Antena Luar (Outdoor)</b> dengan kabel berkualitas (RG6). Arahkan tegak lurus ke pemancar terdekat. Jangan pakai kaleng biskuit ya Ndan! <b>Ganti.</b> 📡"
    
    if any(x in text for x in ['kanal', 'mux', 'frekuensi', 'channel', 'siaran']):
        return "<b>Monitor!</b> Untuk data kanal/MUX lengkap, silakan cek menu <b>Database</b> di aplikasi ini Ndan. Pastikan scan ulang (Auto Scan) secara berkala untuk update frekuensi terbaru. <b>86?</b>"
    
    if any(x in text for x in ['modi', 'siapa', 'kamu', 'robot', 'admin']):
        return "<b>Siap!</b> Perkenalkan, saya <b>Modi</b>. Asisten Virtual KTVDI siap perintah! Tugas saya membantu Ndan mendapatkan informasi penyiaran yang akurat. <b>Salam hormat!</b> 🫡"

    if any(x in text for x in ['makasih', 'thanks', 'suwun', 'terima']):
        return "<b>Siap! Sama-sama Ndan.</b> Senang bisa membantu. Jaga kesehatan dan tetap patuhi protokol. Jika butuh bantuan lagi, panggil saja. <b>8-1-3</b> (Selamat bertugas/beraktivitas)! 👋"

    defaults = [
        "<b>Siap!</b> Mohon izin melaporkan Ndan, koneksi ke pusat komando AI sedang <b>8-1-0</b> (Offline). Mohon ulangi perintah atau cek menu manual. <b>Ganti!</b> 👮‍♂️",
        "<b>Lapor Ndan!</b> Jaringan monitor terpantau padat merayap. Sistem sedang istirahat di tempat. Ada hal lain yang bisa dibantu? <b>Siap 86!</b> 🫡",
        "<b>Mohon Izin Komandan.</b> Server sedang tidak monitor. Harap periksa frekuensi atau coba lagi nanti. <b>8-1-3!</b> (Selamat bertugas) 👮",
        "<b>Siap Salah!</b> Gagal terhubung ke Markas Besar Data. Mohon petunjuk lebih lanjut atau ulangi pertanyaan. <b>Kijang satu ganti.</b> 📻",
        "<b>Monitor!</b> Suara putus-putus, sinyal tidak tembus. Mohon izin periksa perangkat. <b>Salam Presisi!</b> 🇮🇩",
        "<b>Izin Ndan!</b> Situasi terkini server sedang dalam perbaikan rutin. Mohon bersabar, 8-6? 🚧"
    ]
    return random.choice(defaults)

# ==========================================
# 6. ROUTE UTAMA
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

# --- LOGIN ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        raw_input = request.form.get('username')
        password = request.form.get('password')
        hashed_pw = hash_password(password)
        clean_input = normalize_input(raw_input)
        
        if not ref: return render_template('login.html', error="Koneksi Database Terputus.")
        
        users = ref.child('users').get() or {}
        target_user = None; target_uid = None
        
        for uid, data in users.items():
            if not isinstance(data, dict): continue
            if normalize_input(uid) == clean_input: target_user = data; target_uid = uid; break
            if normalize_input(data.get('email')) == clean_input: target_user = data; target_uid = uid; break
        
        if target_user and target_user.get('password') == hashed_pw:
            session.permanent = True
            session['user'] = target_uid
            session['nama'] = target_user.get('nama', 'Pengguna')
            return redirect(url_for('dashboard'))
        return render_template('login.html', error="Identitas akun atau kata sandi tidak sesuai.")
    return render_template('login.html')

# --- REGISTER ---
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
            flash("Maaf Kak, Username ini sudah digunakan.", "error")
            return render_template("register.html")
        for uid, data in users.items():
            if normalize_input(data.get('email')) == e:
                flash("Email ini sudah terdaftar.", "error")
                return render_template("register.html")
        otp = str(random.randint(100000, 999999))
        expiry = time.time() + 60
        ref.child(f'pending_users/{u}').set({"nama": n, "email": e, "password": hash_password(p), "otp": otp, "expiry": expiry})
        try:
            msg = Message("Verifikasi Akun KTVDI", recipients=[e])
            msg.body = f"Kode OTP Anda: {otp}"
            mail.send(msg)
            session["pending_username"] = u
            return redirect(url_for("verify_register"))
        except: flash("Gagal kirim email.", "error")
    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    u = session.get("pending_username")
    if not u: return redirect(url_for("register"))
    if request.method == "POST":
        p = ref.child(f'pending_users/{u}').get()
        if not p: return redirect(url_for("register"))
        if str(p.get('otp')).strip() == request.form.get("otp").strip():
            ref.child(f'users/{u}').set({"nama": p['nama'], "email": p['email'], "password": p['password']})
            ref.child(f'pending_users/{u}').delete()
            session.pop('pending_username', None)
            flash("Registrasi Berhasil.", "success")
            return redirect(url_for('login'))
        flash("Kode OTP Salah.", "error")
    return render_template("verify-register.html", username=u)

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email_input = normalize_input(request.form.get("identifier"))
        users = ref.child("users").get() or {}
        found_uid = None
        
        for uid, user_data in users.items():
            if isinstance(user_data, dict) and normalize_input(user_data.get('email')) == email_input:
                found_uid = uid; break
        
        if found_uid:
            otp = str(random.randint(100000, 999999))
            expiry = time.time() + 60
            ref.child(f"otp/{found_uid}").set({"email": email_input, "otp": otp, "expiry": expiry})
            try:
                msg = Message("Reset Password", recipients=[email_input])
                msg.body = f"OTP: {otp}"
                mail.send(msg)
                session["reset_uid"] = found_uid
                return redirect(url_for("verify_otp"))
            except: pass
    return render_template("forgot-password.html")

@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    uid = session.get("reset_uid")
    if not uid: return redirect(url_for("forgot_password"))
    if request.method == "POST":
        data = ref.child(f"otp/{uid}").get()
        if not data: return redirect(url_for("forgot_password"))
        if str(data.get("otp")).strip() == request.form.get("otp").strip():
            session['reset_verified'] = True
            return redirect(url_for("reset_password"))
    return render_template("verify-otp.html")

@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    if not session.get('reset_verified'): return redirect(url_for('login'))
    if request.method == "POST":
        uid = session.get("reset_uid")
        pw = request.form.get("password")
        ref.child(f"users/{uid}").update({"password": hash_password(pw)})
        ref.child(f"otp/{uid}").delete()
        session.clear()
        return redirect(url_for('login'))
    return render_template("reset-password.html")

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

# ==========================================
# 8. BERITA (GOOGLE NEWS UMUM)
# ==========================================

@app.route('/berita')
def berita_page():
    try:
        entries = get_news_entries()
        page = request.args.get('page', 1, type=int)
        per_page = 9
        start = (page - 1) * per_page
        end = start + per_page
        current = entries[start:end]
        
        for a in current:
            if isinstance(a, dict) and 'published_parsed' in a:
                 a['formatted_date'] = format_indo_date(a['published_parsed'])
                 a['time_since_published'] = time_since_published(a['published_parsed'])
            else:
                 a['formatted_date'] = datetime.now().strftime("%A, %d %B %Y - %H:%M WIB")
                 a['time_since_published'] = "Baru saja"
            a['image'] = None
            if 'media_content' in a: a['image'] = a['media_content'][0]['url']
            elif 'links' in a:
                for link in a['links']:
                    if 'image' in link.get('type',''): a['image'] = link.get('href')
            if not a.get('source_name'): a['source_name'] = 'Berita Terkini'

        total_pages = (len(entries)//per_page) + 1
        return render_template('berita.html', articles=current, page=page, total_pages=total_pages)
    except: return render_template('berita.html', articles=[], page=1, total_pages=1)

# ==========================================
# 9. DASHBOARD & CRUD
# ==========================================

@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    data = ref.child("provinsi").get() or {}
    return render_template("dashboard.html", name=session.get('nama'), provinsi_list=list(data.values()))

@app.route("/daftar-siaran")
def daftar_siaran():
    data = ref.child("provinsi").get() or {}
    return render_template("daftar-siaran.html", provinsi_list=list(data.values()))

@app.route("/add_data", methods=["GET", "POST"])
def add_data():
    if 'user' not in session: return redirect(url_for('login'))
    prov_data = ref.child("provinsi").get() or {}
    provinsi_list = list(prov_data.values()) if prov_data else ["DKI Jakarta", "Jawa Barat", "Jawa Tengah", "Jawa Timur"]
    if request.method == "POST":
        p, w, m, s = request.form.get("provinsi"), request.form.get("wilayah"), request.form.get("mux"), request.form.get("siaran")
        if p and w and m and s:
            data_new = {
                "siaran": [ch.strip() for ch in s.split(',')],
                "last_updated_by_name": session.get('nama'),
                "last_updated_by_username": session.get('user'),
                "last_updated_date": datetime.now().strftime("%d-%m-%Y"),
                "last_updated_time": datetime.now().strftime("%H:%M:%S WIB")
            }
            ref.child(f"siaran/{p}/{w}/{m}").set(data_new)
            ref.child(f"provinsi/{p}").set(p)
            flash("Sukses", "success"); return redirect(url_for('dashboard'))
    return render_template("add_data_form.html", provinsi_list=sorted(provinsi_list))

@app.route("/edit_data/<provinsi>/<wilayah>/<mux>", methods=["GET", "POST"])
def edit_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    curr_data = ref.child(f"siaran/{provinsi}/{wilayah}/{mux}").get()
    if request.method == "POST":
        s = request.form.get("siaran")
        ref.child(f"siaran/{provinsi}/{wilayah}/{mux}").update({
            "siaran": [ch.strip() for ch in s.split(',')],
            "last_updated_by_name": session.get('nama'),
            "last_updated_date": datetime.now().strftime("%d-%m-%Y")
        })
        flash("Sukses Update", "success"); return redirect(url_for('dashboard'))
    siaran_str = ", ".join(curr_data.get('siaran', [])) if curr_data else ""
    return render_template("add_data_form.html", edit_mode=True, curr_provinsi=provinsi, curr_wilayah=wilayah, curr_mux=mux, curr_siaran=siaran_str, provinsi_list=[provinsi]) 

@app.route("/delete_data/<provinsi>/<wilayah>/<mux>", methods=["POST"])
def delete_data(provinsi, wilayah, mux):
    if 'user' in session: 
        try: ref.child(f"siaran/{provinsi}/{wilayah}/{mux}").delete(); return jsonify({"status": "success"})
        except: return jsonify({"status": "error"})
    return jsonify({"status": "unauthorized"})

# API Helper
@app.route("/get_wilayah")
def get_wilayah(): return jsonify({"wilayah": list((ref.child(f"siaran/{request.args.get('provinsi')}").get() or {}).keys())})
@app.route("/get_mux")
def get_mux(): return jsonify({"mux": list((ref.child(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}").get() or {}).keys())})
@app.route("/get_siaran")
def get_siaran(): return jsonify(ref.child(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}/{request.args.get('mux')}").get() or {})

# ==========================================
# 10. FITUR LAIN (AI SMART & JADWAL SHOLAT)
# ==========================================

@app.route('/api/chat', methods=['POST'])
def chatbot_api():
    data = request.get_json()
    user_msg = data.get('prompt', '')
    
    # 1. Cek Model AI Tersedia
    if not model: 
        return jsonify({"response": get_smart_fallback_response(user_msg)})
    
    try:
        # 2. Coba Generate dengan AI
        full_prompt = f"{MODI_PROMPT}\nUser: {user_msg}\nModi:"
        response = model.generate_content(full_prompt)
        
        if response.text:
            return jsonify({"response": response.text})
        else:
            return jsonify({"response": get_smart_fallback_response(user_msg)})
            
    except Exception as e:
        print(f"AI Error: {e}")
        # 3. Fallback ke Template Offline Smart
        return jsonify({"response": get_smart_fallback_response(user_msg)})

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
        "Surabaya", "Surakarta", "Tangerang", "Tangerang Selatan", "Tanjungbalai", "Tanjungpinang", "Tarakan", "Tasikmalaya", "Tebing Tinggi", "Tegal",
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
