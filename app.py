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

# --- 4. AI GEMINI (KEY BARU) ---
GEMINI_KEY = "AIzaSyCqEFdnO3N0JBUBuaceTQLejepyDlK_eGU"
try:
    genai.configure(api_key=GEMINI_KEY) 
    model = genai.GenerativeModel("gemini-1.5-flash") # Menggunakan 1.5 Flash (Stabil & Cepat)
except: model = None

MODI_PROMPT = """
Anda adalah MODI, Sahabat Digital KTVDI. 
Gaya bicara: Sangat ramah, peduli, menggunakan emoji, dan memanggil user dengan 'Kak'.
Fokus: TV Digital, Teknologi, dan Kebaikan.
"""

# --- 5. HELPERS ---
def hash_password(pw): return hashlib.sha256(pw.encode()).hexdigest()
def normalize_input(text): return text.strip().lower() if text else ""

def get_news_entries():
    all_news = []
    try:
        sources = ['https://news.google.com/rss?hl=id&gl=ID&ceid=ID:id', 'https://www.cnnindonesia.com/nasional/rss']
        for url in sources:
            try:
                feed = feedparser.parse(url)
                if feed.entries: all_news.extend(feed.entries[:5])
            except: continue
        all_news.sort(key=lambda x: x.published_parsed if x.get('published_parsed') else time.gmtime(0), reverse=True)
    except: pass
    if not all_news: return [{'title': 'Selamat Datang di Keluarga Besar KTVDI', 'link': '#'}]
    return all_news[:20]

def time_since_published(published_time):
    try:
        now = datetime.now()
        pt = datetime(*published_time[:6])
        diff = now - pt
        if diff.days > 0: return f"{diff.days} hari lalu"
        if diff.seconds > 3600: return f"{diff.seconds//3600} jam lalu"
        return "Baru saja"
    except: return ""

def get_quote_religi():
    """Pesan Penyejuk Hati (Updated: Jujur & Anti Korupsi)"""
    quotes = {
        "muslim": [
            "Dan janganlah sebagian kamu memakan harta sebagian yang lain dengan jalan yang batil. (QS. Al-Baqarah: 188) ✨",
            "Sholat adalah tiang agama. Barangsiapa menegakkannya, ia menegakkan agama. Istiqomah ya Kak! 🕌",
            "Kejujuran membawa ketenangan, sedangkan kebohongan membawa keraguan. (HR. Tirmidzi) 🤲",
            "Jauhi korupsi sekecil apapun, karena setiap daging yang tumbuh dari yang haram, neraka lebih pantas baginya. (HR. Tirmidzi) 🔥",
            "Sesungguhnya shalat itu mencegah dari (perbuatan-perbuatan) keji dan mungkar. (QS. Al-Ankabut: 45)"
        ],
        "universal": [
            "Integritas adalah melakukan hal yang benar, bahkan ketika tidak ada orang yang melihat. ❤️",
            "Kejujuran adalah bab pertama dalam buku kebijaksanaan. Hidup tenang tanpa beban. 🌱",
            "Rezeki yang berkah berawal dari cara yang bersih. Tetap semangat mencari yang halal! 💪",
            "Damai di hati dimulai dengan kejujuran pada diri sendiri dan orang lain. 🕊️"
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

# --- LOGIN (ROBUST) ---
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

# --- REGISTER (OTP 1 MENIT & PESAN PERHATIAN) ---
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
            flash("Maaf Kak, Username ini sudah ada yang punya.", "error")
            return render_template("register.html")
        for uid, data in users.items():
            if normalize_input(data.get('email')) == e:
                flash("Email ini sudah terdaftar sebelumnya.", "error")
                return render_template("register.html")

        otp = str(random.randint(100000, 999999))
        expiry = time.time() + 60 # 1 Menit dari sekarang
        
        ref.child(f'pending_users/{u}').set({
            "nama": n, "email": e, "password": hash_password(p), "otp": otp, "expiry": expiry
        })
        
        try:
            msg = Message("💌 Kode Rahasia KTVDI (Penting)", recipients=[e])
            msg.body = f"""Halo Kak {n} yang baik,

Terima kasih banyak sudah ingin menjadi bagian dari keluarga KTVDI. Kami sangat menghargai antusiasme Kakak.

Demi keamanan data Kakak, ini kode verifikasi rahasianya:
👉 {otp} 👈

⚠️ Perhatian: Kode ini hanya berlaku 1 MENIT ya Kak. Mohon segera dimasukkan agar tidak kedaluwarsa.

Jika butuh bantuan, jangan ragu hubungi kami.

Salam hangat dan sayang,
Tim KTVDI
"""
            mail.send(msg)
            session["pending_username"] = u
            return redirect(url_for("verify_register"))
        except Exception as err:
            print(f"Mail Error: {err}")
            flash("Gagal mengirim email. Pastikan alamat email benar ya Kak.", "error")
            
    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    u = session.get("pending_username")
    if not u: return redirect(url_for("register"))
    
    if request.method == "POST":
        p = ref.child(f'pending_users/{u}').get()
        if not p:
            flash("Sesi habis Kak, mohon daftar ulang ya.", "error")
            return redirect(url_for("register"))

        # Cek Waktu (1 Menit)
        if time.time() > p.get('expiry', 0):
            flash("Yah, kode OTP sudah kedaluwarsa (lewat 1 menit). Silakan daftar ulang.", "error")
            ref.child(f'pending_users/{u}').delete()
            return redirect(url_for("register"))

        if str(p.get('otp')).strip() == request.form.get("otp").strip():
            ref.child(f'users/{u}').set({
                "nama": p['nama'], "email": p['email'], "password": p['password'], "points": 0, "join_date": datetime.now().strftime("%d-%m-%Y")
            })
            ref.child(f'pending_users/{u}').delete()
            session.pop('pending_username', None)
            
            try:
                msg = Message("Selamat Datang di Rumah Baru! 🏠", recipients=[p['email']])
                msg.body = f"Halo Kak {p['nama']},\n\nAlhamdulillah! Akun Kakak sudah aktif sepenuhnya.\nSelamat datang di KTVDI. Mari bersama-sama kita majukan penyiaran digital Indonesia.\n\nJangan lupa jaga kesehatan ya Kak!\n\nSalam,\nKTVDI"
                mail.send(msg)
            except: pass
            
            flash("Hore! Akun berhasil dibuat. Silakan Login.", "success")
            return redirect(url_for('login'))
        else:
            flash("Kode OTP yang dimasukkan salah Kak.", "error")
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
                found_uid = uid
                target_name = user_data.get('nama', 'Sahabat')
                break
        
        if found_uid:
            otp = str(random.randint(100000, 999999))
            expiry = time.time() + 60
            ref.child(f"otp/{found_uid}").set({"email": email_input, "otp": otp, "expiry": expiry})
            try:
                msg = Message("🔑 Reset Password KTVDI", recipients=[email_input])
                msg.body = f"""Halo Kak {target_name},

Kami mendengar Kakak kesulitan masuk akun. Jangan panik ya, kami di sini membantu.

Gunakan kode ini untuk membuat kata sandi baru (Hanya 1 Menit):
👉 {otp}

Jika bukan Kakak yang meminta, abaikan saja email ini. Keamanan Kakak adalah prioritas kami.

Salam peduli,
Tim Support KTVDI
"""
                mail.send(msg)
                session["reset_uid"] = found_uid
                return redirect(url_for("verify_otp"))
            except: flash("Gagal kirim email.", "error")
        else:
            flash("Maaf Kak, email tersebut tidak ditemukan di data kami.", "error")
    return render_template("forgot-password.html")

@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    uid = session.get("reset_uid")
    if not uid: return redirect(url_for("forgot_password"))
    if request.method == "POST":
        data = ref.child(f"otp/{uid}").get()
        
        if not data or time.time() > data.get('expiry', 0):
            flash("Kode kedaluwarsa. Silakan minta ulang.", "error")
            return redirect(url_for("forgot_password"))

        if str(data.get("otp")).strip() == request.form.get("otp").strip():
            session['reset_verified'] = True
            return redirect(url_for("reset_password"))
        flash("Kode salah Kak.", "error")
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
        flash("Password berhasil diubah. Jangan lupa lagi ya Kak! 😊", "success")
        return redirect(url_for('login'))
    return render_template("reset-password.html")

# --- FITUR RELIGI & JADWAL SHOLAT (70 KOTA +) ---
@app.route("/jadwal-sholat")
def jadwal_sholat_page():
    kota = [
        "Ambon", "Balikpapan", "Banda Aceh", "Bandar Lampung", "Bandung", "Banjar", "Banjarbaru", "Banjarmasin", "Batam", "Batu",
        "Bau-Bau", "Bekasi", "Bengkulu", "Bima", "Binjai", "Bitung", "Blitar", "Bogor", "Bontang", "Bukittinggi",
        "Cilegon", "Cimahi", "Cirebon", "Denpasar", "Depok", "Dumai", "Gorontalo", "Gunungsitoli", "Jakarta", "Jambi",
        "Jayapura", "Kediri", "Kendari", "Kotamobagu", "Kupang", "Langsa", "Lhokseumawe", "Lubuklinggau", "Madiun", "Magelang",
        "Makassar", "Malang", "Manado", "Mataram", "Medan", "Metro", "Mojokerto", "Padang", "Padangpanjang", "Padangsidempuan",
        "Pagar Alam", "Palangkaraya", "Palembang", "Palopo", "Palu", "Pangkal Pinang", "Parepare", "Pariaman", "Pasuruan", "Payakumbuh",
        "Pekalongan", "Pekanbaru", "Pematangsiantar", "Pontianak", "Prabumulih", "Probolinggo", "Purwokerto", "Purwodadi", "Sabang", "Salatiga",
        "Samarinda", "Sawahlunto", "Semarang", "Serang", "Sibolga", "Singkawang", "Solok", "Sorong", "Subulussalam", "Sukabumi",
        "Surabaya", "Surakarta (Solo)", "Tangerang", "Tangerang Selatan", "Tanjungbalai", "Tanjungpinang", "Tarakan", "Tasikmalaya", "Tebing Tinggi", "Tegal",
        "Ternate", "Tidore Kepulauan", "Tomohon", "Tual", "Yogyakarta"
    ]
    
    quotes = get_quote_religi()
    return render_template("jadwal-sholat.html", daftar_kota=sorted(kota), quotes=quotes)

# --- EMAIL BLAST CERDAS (AI GENERATED) ---
# Endpoint ini dipanggil Cron Job setiap jam 19.00
@app.route("/api/cron/daily-blast", methods=['GET'])
def trigger_daily_blast():
    try:
        users = ref.child('users').get() or {}
        
        # 1. Ambil Berita RSS
        feed = get_news_entries()
        news_titles = [f"- {item['title']}" for item in feed[:3]]
        news_text = "\n".join(news_titles)
        
        # 2. Generate Konten via Gemini (Analisis Cuaca & Pesan Peduli)
        date_str = datetime.now().strftime("%d %B %Y")
        
        prompt = f"""
        Buatkan isi email harian yang hangat, peduli, dan menyentuh hati untuk pengguna "KTVDI" (Komunitas TV Digital Indonesia).
        
        Data Berita Hari Ini:
        {news_text}
        
        Instruksi:
        1. Buat rangkuman singkat dari berita di atas.
        2. Berikan prediksi cuaca umum untuk besok di kota-kota besar Indonesia (analisis singkat saja, misal: waspada hujan).
        3. Tambahkan pesan motivasi/religi tentang kejujuran, istirahat yang cukup, dan rasa syukur.
        4. Gunakan bahasa yang sangat personal, gunakan kata "Sobat KTVDI" atau "Kakak".
        5. Tutup dengan salam hangat.
        """
        
        email_content = "Konten sedang disiapkan..."
        if model:
            response = model.generate_content(prompt)
            email_content = response.text
        else:
            email_content = f"Halo Kak!\n\nBerikut berita hari ini:\n{news_text}\n\nJangan lupa istirahat ya!"

        # 3. Kirim ke Semua User
        count = 0
        for uid, user in users.items():
            if isinstance(user, dict) and user.get('email'):
                try:
                    nama = user.get('nama', 'Sahabat')
                    # Personalize sedikit di awal
                    final_body = f"Halo Kak {nama},\n\n" + email_content.replace("**", "")
                    
                    msg = Message(f"🌙 Rangkuman Hari Ini untuk Kak {nama} - {date_str}", recipients=[user['email']])
                    msg.body = final_body
                    mail.send(msg)
                    count += 1
                except: pass
                
        return jsonify({"status": "Success", "sent_count": count}), 200
    except Exception as e: return jsonify({"error": str(e)}), 500

# --- ROUTES LAIN ---
@app.route("/cctv")
def cctv_page(): return render_template("cctv.html")

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
            else: a['time_since_published'] = ""
            a['image'] = None
            if 'media_content' in a: a['image'] = a['media_content'][0]['url']
            elif 'links' in a:
                for link in a['links']:
                    if 'image' in link.get('type',''): a['image'] = link.get('href')
        return render_template('berita.html', articles=current, page=page, total_pages=(len(entries)//per_page)+1)
    except: return render_template('berita.html', articles=[], page=1, total_pages=1)

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

@app.route('/api/chat', methods=['POST'])
def chatbot_api():
    if not model: return jsonify({"response": "Maaf Kak, AI sedang istirahat."})
    data = request.get_json()
    try:
        response = model.generate_content(f"{MODI_PROMPT}\nUser: {data.get('prompt')}\nModi:")
        return jsonify({"response": response.text})
    except: return jsonify({"response": "Maaf Kak, Modi lagi sibuk."})

@app.route("/api/news-ticker")
def news_ticker():
    entries = get_news_entries()
    titles = [e.get('title', 'Info TV Digital') for e in entries]
    return jsonify(titles)

if __name__ == "__main__":
    app.run(debug=True)
