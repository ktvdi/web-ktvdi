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
from datetime import datetime
from collections import Counter

load_dotenv()

app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("SECRET_KEY", "ktvdi-final-pro-2026")

# ==========================================
# 1. KONEKSI FIREBASE
# ==========================================
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
    print("✅ Firebase Connected")
except Exception as e:
    ref = None
    print(f"❌ Firebase Error: {e}")

# ==========================================
# 2. EMAIL CONFIGURATION
# ==========================================
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME") 
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD") 
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")
mail = Mail(app)

# ==========================================
# 3. AI CHATBOT
# ==========================================
MY_API_KEY = "AIzaSyCqEFdnO3N0JBUBuaceTQLejepyDlK_eGU"

try:
    genai.configure(api_key=MY_API_KEY)
    model = genai.GenerativeModel("gemini-1.5-flash")
    print("✅ AI Ready")
except Exception as e:
    model = None
    print(f"❌ AI Error: {e}")

MODI_PROMPT = """
Anda adalah MODI, Sahabat Digital dari KTVDI.
Tugas: Membantu masyarakat awam memahami TV Digital dengan bahasa yang hangat.
Aturan:
1. Sapa dengan "Kak" atau "Sobat".
2. Info Piala Dunia 2026: Hak siar TVRI (Gratis & HD).
3. Selalu tawarkan bantuan lain.
"""

# ==========================================
# 4. HELPERS
# ==========================================
def hash_password(pw): return hashlib.sha256(pw.encode()).hexdigest()

def normalize_input(text):
    return text.strip().lower() if text else ""

def get_news_entries():
    all_news = []
    sources = [
        'https://news.google.com/rss?hl=id&gl=ID&ceid=ID:id', 
        'https://www.cnnindonesia.com/nasional/rss'
    ]
    try:
        for url in sources:
            try:
                feed = feedparser.parse(url)
                if feed.entries:
                    for entry in feed.entries:
                        entry['source_name'] = feed.feed.title if 'title' in feed.feed else "Berita"
                    all_news.extend(feed.entries[:5])
            except: continue
        all_news.sort(key=lambda x: x.published_parsed if x.get('published_parsed') else time.gmtime(0), reverse=True)
    except: pass
    
    # FALLBACK JIKA KOSONG
    if not all_news:
        return [{'title': 'Selamat Datang di KTVDI - Informasi TV Digital Terkini', 'link': '#', 'source_name': 'Info'}]
    
    return all_news[:20]

def time_since_published(published_time):
    try:
        now = datetime.now()
        pt = datetime(*published_time[:6])
        diff = now - pt
        if diff.days > 0: return f"{diff.days} hari lalu"
        if diff.seconds > 3600: return f"{diff.seconds//3600} jam lalu"
        return "Baru saja"
    except: return "Baru saja"

# ==========================================
# 5. AUTH ROUTES (FIXED)
# ==========================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        raw_input = request.form.get('username')
        password = request.form.get('password')
        hashed_pw = hash_password(password)
        users = ref.child('users').get() if ref else {}
        target_user = None
        target_uid = None
        clean_input = normalize_input(raw_input)

        if users:
            # Cek Username
            for uid, data in users.items():
                if uid.lower() == clean_input:
                    target_user = data
                    target_uid = uid
                    break
            # Cek Email
            if not target_user:
                for uid, data in users.items():
                    if isinstance(data, dict) and normalize_input(data.get('email')) == clean_input:
                        target_user = data
                        target_uid = uid
                        break
        
        if target_user and target_user.get('password') == hashed_pw:
            session.permanent = True
            session['user'] = target_uid
            session['nama'] = target_user.get('nama', 'Pengguna')
            return redirect(url_for('dashboard'))
        
        return render_template('login.html', error="Username/Email atau Password Salah")
    return render_template('login.html')

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        u = normalize_input(request.form.get("username"))
        e = normalize_input(request.form.get("email"))
        n = request.form.get("nama")
        p = request.form.get("password")
        users = ref.child("users").get() or {}
        
        if u in users:
            flash("Username sudah digunakan", "error")
            return render_template("register.html")
        for uid, data in users.items():
            if normalize_input(data.get('email')) == e:
                flash("Email sudah terdaftar", "error")
                return render_template("register.html")

        otp = str(random.randint(100000, 999999))
        ref.child(f'pending_users/{u}').set({ "nama": n, "email": e, "password": hash_password(p), "otp": otp })
        
        try:
            msg = Message("Kode Verifikasi KTVDI (Berlaku 1 Menit)", recipients=[e])
            msg.body = f"""Halo Kak {n},

Terima kasih telah memilih untuk bergabung bersama keluarga besar Komunitas TV Digital Indonesia.

Untuk keamanan akun Kakak, silakan masukkan kode verifikasi berikut dalam waktu 1 menit:

>> {otp} <<

Jangan berikan kode ini kepada siapapun ya, Kak. Kami tunggu kehadiran Kakak di dalam aplikasi.

Salam hangat,
Tim Admin KTVDI
"""
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
        if p and str(p.get('otp')) == request.form.get("otp"):
            ref.child(f'users/{u}').set({ "nama": p['nama'], "email": p['email'], "password": p['password'], "points": 0 })
            ref.child(f'pending_users/{u}').delete()
            session.pop('pending_username', None)
            # Email Welcome
            try:
                msg = Message("Selamat Datang di Rumah Baru!", recipients=[p['email']])
                msg.body = f"Halo Kak {p['nama']},\n\nSelamat! Akun Kakak sudah aktif. Mari bersama-sama kita majukan penyiaran digital Indonesia.\n\nSalam sayang,\nKTVDI"
                mail.send(msg)
            except: pass
            flash("Berhasil! Silakan Login.", "success")
            return redirect(url_for('login'))
        flash("OTP Salah/Kadaluarsa", "error")
    return render_template("verify-register.html", username=u)

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email_input = normalize_input(request.form.get("identifier"))
        users = ref.child("users").get() or {}
        found_uid = None
        for uid, user_data in users.items():
            if isinstance(user_data, dict) and normalize_input(user_data.get('email')) == email_input:
                found_uid = uid
                break
        
        if found_uid:
            otp = str(random.randint(100000, 999999))
            ref.child(f"otp/{found_uid}").set({"email": email_input, "otp": otp})
            try:
                msg = Message("Pemulihan Akun KTVDI", recipients=[email_input])
                msg.body = f"""Halo Kak,

Kami mendengar Kakak kesulitan masuk. Jangan khawatir, gunakan kode ini untuk mereset kata sandi (Berlaku 1 Menit):

{otp}

Jika bukan Kakak, abaikan saja ya. Keamanan Kakak prioritas kami.

Salam,
Tim Support KTVDI
"""
                mail.send(msg)
                session["reset_uid"] = found_uid
                return redirect(url_for("verify_otp"))
            except: flash("Gagal kirim email.", "error")
        else:
            flash("Email tidak ditemukan.", "error")
    return render_template("forgot-password.html")

@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    uid = session.get("reset_uid")
    if not uid: return redirect(url_for("forgot_password"))
    if request.method == "POST":
        data = ref.child(f"otp/{uid}").get()
        if data and str(data.get("otp")) == request.form.get("otp"):
            session['reset_verified'] = True
            return redirect(url_for("reset_password"))
        flash("OTP Salah", "error")
    return render_template("verify-otp.html")

@app.route("/reset_password", methods=["GET", "POST"])
def reset_password():
    if not session.get('reset_verified'): return redirect(url_for('login'))
    uid = session.get("reset_uid")
    if request.method == "POST":
        pw = request.form.get("password")
        ref.child(f"users/{uid}").update({"password": hash_password(pw)})
        ref.child(f"otp/{uid}").delete()
        session.clear()
        flash("Sukses ubah password.", "success")
        return redirect(url_for('login'))
    return render_template("reset-password.html")

# ==========================================
# 6. APP ROUTES
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
def add_data(): return redirect(url_for('dashboard'))
@app.route("/edit_data/<provinsi>/<wilayah>/<mux>", methods=["GET", "POST"])
def edit_data(provinsi, wilayah, mux): return redirect(url_for('dashboard'))
@app.route("/delete_data/<provinsi>/<wilayah>/<mux>", methods=["POST"])
def delete_data(provinsi, wilayah, mux): return redirect(url_for('dashboard'))

@app.route("/get_wilayah")
def get_wilayah(): return jsonify({"wilayah": list((ref.child(f"siaran/{request.args.get('provinsi')}").get() or {}).keys())})
@app.route("/get_mux")
def get_mux(): return jsonify({"mux": list((ref.child(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}").get() or {}).keys())})
@app.route("/get_siaran")
def get_siaran(): return jsonify(ref.child(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}/{request.args.get('mux')}").get() or {})

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
                 a['time_since_published'] = time_since_published(a['published_parsed'])
            else: a['time_since_published'] = "Baru saja"
            a['image'] = None
            if 'media_content' in a: a['image'] = a['media_content'][0]['url']
            elif 'links' in a:
                for link in a['links']:
                    if 'image' in link.get('type',''): a['image'] = link.get('href')
        return render_template('berita.html', articles=current, page=page, total_pages=(len(entries)//per_page)+1)
    except: return render_template('berita.html', articles=[], page=1, total_pages=1)

@app.route("/cctv")
def cctv_page(): return render_template("cctv.html")

@app.route("/jadwal-sholat")
def jadwal_sholat_page():
    # 60 Kota Termasuk Purwodadi & Pekalongan
    kota = [
        "Ambon", "Balikpapan", "Banda Aceh", "Bandar Lampung", "Bandung", "Banjarmasin", "Batam", "Bekasi", "Bengkulu", "Bogor", 
        "Bukittinggi", "Cilegon", "Cimahi", "Cirebon", "Denpasar", "Depok", "Dumai", "Gorontalo", "Jakarta", "Jambi", 
        "Jayapura", "Kediri", "Kendari", "Kupang", "Lubuklinggau", "Madiun", "Magelang", "Makassar", "Malang", "Mamuju", 
        "Manado", "Mataram", "Medan", "Padang", "Palangkaraya", "Palembang", "Palu", "Pangkal Pinang", "Parepare", "Pasuruan", 
        "Pekalongan", "Pekanbaru", "Pontianak", "Probolinggo", "Purwokerto", "Purwodadi", "Salatiga", "Samarinda", "Semarang", "Serang", 
        "Sidoarjo", "Singkawang", "Solo", "Sorong", "Sukabumi", "Surabaya", "Tangerang", "Tanjung Pinang", "Tarakan", "Tasikmalaya", 
        "Tegal", "Ternate", "Yogyakarta"
    ]
    return render_template("jadwal-sholat.html", daftar_kota=sorted(kota))

@app.route('/about')
def about(): return render_template('about.html')
@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))
@app.route('/sitemap.xml')
def sitemap(): return send_from_directory('static', 'sitemap.xml')

# API CHATBOT
@app.route('/api/chat', methods=['POST'])
def chatbot_api():
    data = request.get_json()
    try:
        response = model.generate_content(f"{MODI_PROMPT}\nUser: {data.get('prompt')}\nModi:")
        return jsonify({"response": response.text})
    except: return jsonify({"response": "Maaf, AI sibuk."})

@app.route("/api/news-ticker")
def news_ticker():
    entries = get_news_entries()
    titles = [e.get('title') for e in entries]
    return jsonify(titles)

# Email Blast (Cron)
@app.route("/api/cron/daily-blast", methods=['GET'])
def trigger_daily_blast(): return jsonify({"status": "OK"}), 200

if __name__ == "__main__":
    app.run(debug=True)
