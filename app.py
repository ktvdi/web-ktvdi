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

load_dotenv()

app = Flask(__name__)
CORS(app)

# --- 1. KEAMANAN SESI (ANTI MENTAL) ---
app.secret_key = "KTVDI_OFFICIAL_SECRET_KEY_FINAL_PRO_2026"
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 86400 # 24 Jam

# --- 2. KONEKSI FIREBASE ---
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
    print("✅ Database KTVDI Terhubung Sempurna.")
except Exception as e:
    ref = None
    print(f"⚠️ Mode Offline (Database Error): {e}")

# --- 3. KONFIGURASI EMAIL ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME") 
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD") 
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")
mail = Mail(app)

# --- 4. AI GEMINI (KEY BARU & PROMPT PRO) ---
# API Key khusus KTVDI
GEMINI_KEY = "AIzaSyCqEFdnO3N0JBUBuaceTQLejepyDlK_eGU"

try:
    genai.configure(api_key=GEMINI_KEY)
    # Menggunakan model flash yang cepat dan stabil
    model = genai.GenerativeModel("gemini-1.5-flash") 
except: model = None

# Prompt Khusus Chatbot (Sopan & Solutif)
MODI_PROMPT = """
Anda adalah MODI, Asisten Virtual Resmi dari KTVDI (Komunitas TV Digital Indonesia).
Karakter: Sangat sopan, profesional, perhatian, ramah, dan menggunakan bahasa Indonesia yang baik namun tidak kaku (gunakan sapaan 'Kak' atau 'Sobat').
Tugas:
1. Menjawab pertanyaan seputar TV Digital (STB, Antena, Sinyal).
2. Membantu kendala teknis website (Login, Lupa Password).
3. Jika ditanya hal di luar topik, jawab dengan sopan dan arahkan kembali ke topik teknologi/kebaikan.
4. Selalu akhiri dengan pesan positif atau emoji semangat.
"""

# --- 5. HELPERS (BERITA & TANGGAL) ---
def hash_password(pw): return hashlib.sha256(pw.encode()).hexdigest()
def normalize_input(text): return text.strip().lower() if text else ""

def format_indo_date(time_struct):
    """Format tanggal Indonesia lengkap: Senin, 20 Januari 2026"""
    if not time_struct: return ""
    try:
        dt = datetime.fromtimestamp(time.mktime(time_struct))
        hari = ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu'][dt.weekday()]
        bulan = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'][dt.month - 1]
        return f"{hari}, {dt.day} {bulan} {dt.year} | {dt.strftime('%H:%M')} WIB"
    except: return "Baru saja"

def get_news_entries():
    """Mengambil berita terbaru (Multi-Source)"""
    all_news = []
    try:
        # Sumber berita variatif
        sources = [
            'https://news.google.com/rss/search?q=tv+digital+indonesia+kominfo&hl=id&gl=ID&ceid=ID:id',
            'https://www.cnnindonesia.com/nasional/rss',
            'https://www.antaranews.com/rss/tekno.xml',
            'https://www.suara.com/rss/tekno'
        ]
        
        for url in sources:
            try:
                feed = feedparser.parse(url)
                if feed.entries:
                    for entry in feed.entries[:5]: # Ambil 5 teratas per sumber
                        # Labeling Sumber
                        if 'cnn' in url: entry['source_name'] = 'CNN Indonesia'
                        elif 'antara' in url: entry['source_name'] = 'Antara News'
                        elif 'suara' in url: entry['source_name'] = 'Suara.com'
                        else: entry['source_name'] = entry.get('source', {}).get('title', 'Google News')
                        all_news.append(entry)
            except: continue
        
        # Sorting: Wajib yang paling baru di atas (Reverse Time)
        all_news.sort(key=lambda x: x.published_parsed if x.get('published_parsed') else time.gmtime(0), reverse=True)
    except: pass
    
    if not all_news:
        t = datetime.now().timetuple()
        return [{'title': 'Selamat Datang di KTVDI - Update Informasi Terkini', 'link': '#', 'published_parsed': t, 'source_name': 'Info KTVDI'}]
    
    return all_news

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
    quotes = {
        "muslim": [
            "Wahai orang-orang yang beriman! Jauhilah banyak dari prasangka, sesungguhnya sebagian prasangka itu dosa. (QS. Al-Hujurat: 12) 🤲",
            "Sholat adalah tiang agama. Barangsiapa menegakkannya, ia menegakkan agama. Semangat ibadahnya ya Kak! 🕌",
            "Kejujuran membawa ketenangan, sedangkan kebohongan membawa kegelisahan. (HR. Tirmidzi) ✨",
            "Dan janganlah sebagian kamu memakan harta sebagian yang lain dengan jalan yang batil. Hidup berkah tanpa korupsi. (QS. Al-Baqarah: 188) ❤️"
        ],
        "universal": [
            "Integritas adalah melakukan hal yang benar, bahkan ketika tidak ada orang yang melihat.",
            "Kebahagiaan bukan tentang mendapatkan semua yang kita inginkan, tapi mensyukuri apa yang kita miliki.",
            "Kebaikan yang kita tanam hari ini akan menjadi pohon peneduh di masa depan.",
            "Jadilah cahaya bagi sekitarmu dengan kejujuran dan ketulusan hati."
        ]
    }
    return quotes

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
        
        if not ref: return render_template('login.html', error="Maaf, Database sedang pemeliharaan.")
        
        users = ref.child('users').get() or {}
        target_user, target_uid = None, None
        
        for uid, data in users.items():
            if not isinstance(data, dict): continue
            if normalize_input(uid) == clean_input:
                target_user = data; target_uid = uid; break
            if normalize_input(data.get('email')) == clean_input:
                target_user = data; target_uid = uid; break
        
        if target_user and target_user.get('password') == hashed_pw:
            session.permanent = True
            session['user'] = target_uid
            session['nama'] = target_user.get('nama', 'Pengguna')
            return redirect(url_for('dashboard'))
        
        return render_template('login.html', error="Maaf Kak, Username atau Password salah.")
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
            flash("Maaf Kak, Username ini sudah ada yang punya.", "error"); return render_template("register.html")
        for uid, data in users.items():
            if normalize_input(data.get('email')) == e:
                flash("Email ini sudah terdaftar sebelumnya.", "error"); return render_template("register.html")

        otp = str(random.randint(100000, 999999))
        expiry = time.time() + 60 
        ref.child(f'pending_users/{u}').set({ "nama": n, "email": e, "password": hash_password(p), "otp": otp, "expiry": expiry })
        
        try:
            msg = Message("💌 Kode Rahasia KTVDI (Penting)", recipients=[e])
            msg.body = f"Halo Kak {n},\n\nTerima kasih sudah bergabung! Ini kode OTP Kakak (Berlaku 1 Menit): {otp}\n\nSalam hangat,\nKTVDI"
            mail.send(msg)
            session["pending_username"] = u
            return redirect(url_for("verify_register"))
        except: flash("Gagal kirim email", "error")
    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    u = session.get("pending_username")
    if not u: return redirect(url_for("register"))
    if request.method == "POST":
        p = ref.child(f'pending_users/{u}').get()
        if not p or time.time() > p.get('expiry', 0):
            flash("Kode kedaluwarsa. Silakan daftar ulang.", "error"); return redirect(url_for("register"))
        if str(p.get('otp')).strip() == request.form.get("otp").strip():
            ref.child(f'users/{u}').set({ "nama": p['nama'], "email": p['email'], "password": p['password'], "points": 0 })
            ref.child(f'pending_users/{u}').delete()
            session.pop('pending_username', None)
            try:
                msg = Message("Selamat Datang!", recipients=[p['email']])
                msg.body = f"Halo Kak {p['nama']}, Akun sudah aktif! Selamat bergabung di keluarga KTVDI."
                mail.send(msg)
            except: pass
            flash("Sukses! Silakan Login.", "success"); return redirect(url_for('login'))
        flash("Kode Salah.", "error")
    return render_template("verify-register.html", username=u)

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email_input = normalize_input(request.form.get("identifier"))
        users = ref.child("users").get() or {}
        found_uid = None
        target_name = "Sahabat"
        
        for uid, user_data in users.items():
            if isinstance(user_data, dict) and normalize_input(user_data.get('email')) == email_input:
                found_uid = uid; target_name = user_data.get('nama', 'Sahabat'); break
        
        if found_uid:
            otp = str(random.randint(100000, 999999))
            expiry = time.time() + 60
            ref.child(f"otp/{found_uid}").set({"email": email_input, "otp": otp, "expiry": expiry})
            try:
                msg = Message("🔑 Reset Password KTVDI", recipients=[email_input])
                msg.body = f"Halo Kak {target_name},\n\nIni kode reset password Kakak: {otp}\n\nJaga kerahasiaannya ya!"
                mail.send(msg)
                session["reset_uid"] = found_uid
                return redirect(url_for("verify_otp"))
            except: flash("Gagal kirim email.", "error")
        else: flash("Email tidak ditemukan.", "error")
    return render_template("forgot-password.html")

@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    uid = session.get("reset_uid")
    if not uid: return redirect(url_for("forgot_password"))
    if request.method == "POST":
        data = ref.child(f"otp/{uid}").get()
        if not data or time.time() > data.get('expiry', 0):
            flash("Kode kedaluwarsa.", "error"); return redirect(url_for("forgot_password"))
        if str(data.get("otp")).strip() == request.form.get("otp").strip():
            session['reset_verified'] = True
            return redirect(url_for("reset_password"))
        flash("Kode salah.", "error")
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
        flash("Password berhasil diubah. Silakan login kembali.", "success")
        return redirect(url_for('login'))
    return render_template("reset-password.html")

# --- ROUTE BERITA (PERBAIKAN TANGGAL & SUMBER) ---
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
            # 1. Format Tanggal Indo
            if isinstance(a, dict) and 'published_parsed' in a:
                 a['formatted_date'] = format_indo_date(a['published_parsed'])
                 a['time_since_published'] = time_since_published(a['published_parsed'])
            else:
                 a['formatted_date'] = datetime.now().strftime("%A, %d %B %Y")
                 a['time_since_published'] = "Baru saja"
            
            # 2. Gambar
            a['image'] = None
            if 'media_content' in a: a['image'] = a['media_content'][0]['url']
            elif 'links' in a:
                for link in a['links']:
                    if 'image' in link.get('type',''): a['image'] = link.get('href')
        
        total_pages = (len(entries)//per_page) + 1
        return render_template('berita.html', articles=current, page=page, total_pages=total_pages)
    except: return render_template('berita.html', articles=[], page=1, total_pages=1)

# --- JADWAL SHOLAT (NOTIF EMAIL OTOMATIS) ---
@app.route("/jadwal-sholat")
def jadwal_sholat_page():
    kota = ["Jakarta", "Bandung", "Semarang", "Yogyakarta", "Surabaya", "Pekalongan", "Purwodadi", "Serang", "Denpasar", "Medan", "Makassar", "Palembang"]
    quotes = get_quote_religi()
    
    # Fitur Notifikasi Email saat masuk halaman Religi (Hanya jika Login & Belum dikirim di sesi ini)
    if 'user' in session and not session.get('religi_notif_sent'):
        try:
            users = ref.child('users').get() or {}
            user_data = users.get(session['user'])
            if user_data and user_data.get('email'):
                nama = user_data.get('nama', 'Sahabat')
                msg = Message("🕌 Pengingat Kebaikan dari KTVDI", recipients=[user_data['email']])
                msg.body = f"""Assalamualaikum Kak {nama},

Terima kasih sudah meluangkan waktu untuk mengecek jadwal ibadah hari ini.

"Sesungguhnya shalat itu mencegah dari (perbuatan-perbuatan) keji dan mungkar." (QS. Al-Ankabut: 45)

Semoga hari Kakak penuh berkah, dimudahkan segala urusan, dan selalu dalam lindungan-Nya.
Jangan lupa jaga kesehatan dan tetap jujur dalam setiap langkah ya Kak.

Salam santun,
KTVDI
"""
                mail.send(msg)
                session['religi_notif_sent'] = True # Set flag agar tidak spam refresh
        except: pass

    return render_template("jadwal-sholat.html", daftar_kota=sorted(kota), quotes=quotes)

# --- EMAIL BLAST CERDAS (GEMINI AI) ---
@app.route("/api/cron/daily-blast", methods=['GET'])
def trigger_daily_blast():
    try:
        users = ref.child('users').get() or {}
        
        # Data untuk AI
        feed = get_news_entries()
        news_summary = "\n".join([f"- {i['title']}" for i in feed[:3]])
        date_str = datetime.now().strftime("%d %B %Y")
        
        # Prompt AI yang Lebih Personal & Profesional
        prompt = f"""
        Buatkan konten email harian (Daily Digest) untuk member komunitas "KTVDI".
        
        DATA BERITA:
        {news_summary}
        
        INSTRUKSI PENULISAN:
        1. Nada: Sangat sopan, profesional, hangat, penuh perhatian, dan memotivasi (seperti mentor yang peduli).
        2. Struktur:
           - Sapaan hangat (gunakan placeholder [NAMA_USER]).
           - Rangkuman berita singkat & padat (maksimal 2 paragraf).
           - Prakiraan Cuaca Singkat: Ingatkan untuk sedia payung/jaga kesehatan karena cuaca tak menentu.
           - Mutiara Hikmah: Pesan tentang kejujuran, anti-korupsi, dan pentingnya ibadah/istirahat.
           - Penutup yang mendoakan kebaikan.
        3. Jangan gunakan markdown bold/italic yang berlebihan.
        """
        
        email_body_template = "Mohon maaf, konten sedang disiapkan."
        if model:
            response = model.generate_content(prompt)
            email_body_template = response.text
        
        # Kirim ke Semua User
        count = 0
        for uid, user in users.items():
            if isinstance(user, dict) and user.get('email'):
                try:
                    nama = user.get('nama', 'Sahabat')
                    # Replace placeholder dengan nama asli
                    final_body = email_body_template.replace("[NAMA_USER]", nama).replace("[Nama User]", nama)
                    if "[NAMA_USER]" not in email_body_template: # Fallback jika AI lupa placeholder
                         final_body = f"Halo Kak {nama},\n\n" + final_body
                    
                    msg = Message(f"🌙 Kabar Malam & Inspirasi untuk Kak {nama} - {date_str}", recipients=[user['email']])
                    msg.body = final_body
                    mail.send(msg)
                    count += 1
                except: pass
                
        return jsonify({"status": "Success", "sent_count": count}), 200
    except Exception as e: return jsonify({"error": str(e)}), 500

# --- CHATBOT API (GEMINI) ---
@app.route('/api/chat', methods=['POST'])
def chatbot_api():
    data = request.get_json()
    if not model: return jsonify({"response": "Maaf Kak, sistem AI sedang offline."})
    try:
        # Prompt yang memaksa AI menjawab sopan & lengkap
        full_prompt = f"""
        {MODI_PROMPT}
        
        Pertanyaan User: {data.get('prompt')}
        
        Jawaban Modi (Lengkap, Sopan, Solutif):
        """
        response = model.generate_content(full_prompt)
        return jsonify({"response": response.text})
    except: return jsonify({"response": "Maaf Kak, Modi sedang banyak antrian. Boleh diulang pertanyaannya?"})

# --- ROUTE LAINNYA ---
@app.route("/cctv")
def cctv_page(): return render_template("cctv.html")
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
def add_data(): return redirect(url_for('dashboard'))
@app.route("/edit_data/<provinsi>/<wilayah>/<mux>", methods=["GET", "POST"])
def edit_data(provinsi, wilayah, mux): return redirect(url_for('dashboard'))
@app.route("/delete_data/<provinsi>/<wilayah>/<mux>", methods=["POST"])
def delete_data(provinsi, wilayah, mux):
    if 'user' in session: ref.child(f"siaran/{provinsi}/{wilayah}/{mux}").delete()
    return redirect(url_for('dashboard'))
@app.route("/get_wilayah")
def get_wilayah(): return jsonify({"wilayah": list((ref.child(f"siaran/{request.args.get('provinsi')}").get() or {}).keys())})
@app.route("/get_mux")
def get_mux(): return jsonify({"mux": list((ref.child(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}").get() or {}).keys())})
@app.route("/get_siaran")
def get_siaran(): return jsonify(ref.child(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}/{request.args.get('mux')}").get() or {})
@app.route('/about')
def about(): return render_template('about.html')
@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))
@app.route('/sitemap.xml')
def sitemap(): return send_from_directory('static', 'sitemap.xml')
@app.route("/api/news-ticker")
def news_ticker():
    entries = get_news_entries()
    titles = [e.get('title') for e in entries]
    return jsonify(titles)

if __name__ == "__main__":
    app.run(debug=True)
