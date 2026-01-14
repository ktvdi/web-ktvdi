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

# Muat variabel lingkungan
load_dotenv()

app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")

# --- 1. KONEKSI FIREBASE (SETUP) ---
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
    print("✅ Firebase berhasil terhubung!")
except Exception as e:
    print("❌ Error initializing Firebase:", str(e))
    ref = None

# --- 2. SETUP EMAIL ---
app.config['MAIL_SERVER'] = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
app.config['MAIL_PORT'] = int(os.environ.get("MAIL_PORT", 587))
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD")
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")
mail = Mail(app)

# --- 3. KONFIGURASI GEMINI AI (PERBAIKAN) ---
# 👇👇👇 TEMPEL KUNCI API DI SINI JIKA DI VERCEL BELUM DISET 👇👇👇
MANUAL_KEY = "TEMPEL_API_KEY_AIZA_DISINI" 

api_key = os.environ.get("GEMINI_APP_KEY") or (MANUAL_KEY if "AIza" in MANUAL_KEY else None)

if api_key:
    genai.configure(api_key=api_key)
    # Gunakan 1.5-flash (Lebih Cepat & Stabil)
    model = genai.GenerativeModel("gemini-1.5-flash")
else:
    model = None
    print("⚠️ API Key Gemini belum disetting!")

# Prompt System (Agar Ramah)
MODI_PROMPT = """
Anda adalah MODI, Chatbot AI KTVDI.
Karakter: Ramah, Ceria, Informatif, menggunakan Emoji (😊, 👋, 📺).
Tugas: Jawab seputar TV Digital, STB, Antena, dan Website KTVDI.
Aturan:
1. Sapa dengan "Kak" atau "Sobat".
2. Jawaban ringkas dan solutif.
3. Jika ditanya Piala Dunia 2026, jawab: Hak siar dipegang TVRI (Gratis & HD).
4. Akhiri chat dengan menawarkan bantuan lagi.
"""

# Safety Settings (Agar tidak bisu/error saat ditanya hal umum)
SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

# --- FUNGSI BANTUAN (HELPER) ---
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def time_since_published(published_time):
    try:
        now = datetime.now()
        pt = datetime(*published_time[:6])
        diff = now - pt
        if diff.days > 0: return f"{diff.days} hari lalu"
        if diff.seconds > 3600: return f"{diff.seconds//3600} jam lalu"
        if diff.seconds > 60: return f"{diff.seconds//60} menit lalu"
        return "Baru saja"
    except: return ""

def get_bmkg_weather():
    try:
        url = "https://data.bmkg.go.id/DataMKG/MEWS/DigitalForecast/DigitalForecast-DKIJakarta.xml"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            for area in root.findall(".//area[@description='Jakarta Pusat']"):
                for parameter in area.findall("parameter[@id='weather']"):
                    timerange = parameter.find("timerange")
                    if timerange:
                        val = timerange.find("value").text
                        codes = {"0":"Cerah ☀️","1":"Cerah Berawan 🌤️","3":"Berawan ☁️","60":"Hujan 🌧️"}
                        return f"Jakarta Pusat: {codes.get(val, 'Berawan ☁️')}"
        return "Cerah Berawan 🌤️"
    except: return "Cerah Berawan 🌤️"

def get_daily_news_summary_ai():
    try:
        feed = feedparser.parse('https://news.google.com/rss?hl=id&gl=ID&ceid=ID:id')
        titles = [e.title for e in feed.entries[:5]]
        text = "\n".join(titles)
        if model:
            prompt = f"Rangkum 3 berita utama ini menjadi poin-poin singkat dan santai:\n{text}"
            response = model.generate_content(prompt, safety_settings=SAFETY_SETTINGS)
            return response.text
        return "Cek halaman Berita untuk update terbaru."
    except: return "Gagal memuat berita."

def get_daily_tips():
    tips = [
        "Arahkan antena ke pemancar terdekat agar sinyal kuat 📡",
        "Pakai kabel kualitas tinggi (RG6) biar gambar jernih 📺",
        "Scan ulang STB secara berkala ya kak! 🔄",
        "Matikan STB kalau mau tidur biar awet ⚡",
        "Jaga etika di sosmed ya kak, damai itu indah 🤝"
    ]
    return random.choice(tips)

# --- ROUTES UTAMA ---

@app.route("/")
def home():
    # --- LOGIKA STATISTIK LAMA ANDA (DIPERTAHANKAN) ---
    ref_siaran = db.reference('siaran')
    siaran_data = ref_siaran.get() or {}

    jumlah_wilayah_layanan = 0
    jumlah_siaran = 0
    jumlah_penyelenggara_mux = 0
    siaran_counts = Counter()
    last_updated_time = None
    
    for provinsi, provinsi_data in siaran_data.items():
        if isinstance(provinsi_data, dict):
            jumlah_wilayah_layanan += len(provinsi_data)
            for wilayah, wilayah_data in provinsi_data.items():
                if isinstance(wilayah_data, dict):
                    jumlah_penyelenggara_mux += len(wilayah_data)
                    for penyelenggara, detail in wilayah_data.items():
                        if 'siaran' in detail:
                            jumlah_siaran += len(detail['siaran'])
                            for s in detail['siaran']: siaran_counts[s.lower()] += 1
                        
                        if 'last_updated_date' in detail:
                            try:
                                curr = datetime.strptime(detail['last_updated_date'], '%d-%m-%Y')
                                if last_updated_time is None or curr > last_updated_time:
                                    last_updated_time = curr
                            except: pass

    most_common = siaran_counts.most_common(1)
    most_common_name = most_common[0][0].upper() if most_common else None
    most_common_count = most_common[0][1] if most_common else 0
    last_update_str = last_updated_time.strftime('%d-%m-%Y') if last_updated_time else "-"

    return render_template('index.html', 
                           most_common_siaran_name=most_common_name,
                           most_common_siaran_count=most_common_count,
                           jumlah_wilayah_layanan=jumlah_wilayah_layanan,
                           jumlah_siaran=jumlah_siaran, 
                           jumlah_penyelenggara_mux=jumlah_penyelenggara_mux, 
                           last_updated_time=last_update_str)

# 🔹 ROUTE CHATBOT (DIPERBAIKI)
@app.route('/', methods=['POST'])
def chatbot_api():
    if not model:
        return jsonify({"response": "Maaf Kak, server AI Modi sedang gangguan (API Key Missing). 🙏"})
        
    data = request.get_json()
    user_msg = data.get("prompt")
    
    if not user_msg:
        return jsonify({"response": "Modi nggak denger, coba ketik ulang ya? 👂"})

    try:
        response = model.generate_content(
            f"{MODI_PROMPT}\nUser: {user_msg}\nModi:",
            safety_settings=SAFETY_SETTINGS
        )
        return jsonify({"response": response.text})
    except Exception as e:
        print(f"AI Error: {e}")
        return jsonify({"response": "Waduh, Modi lagi pusing (Server Busy). Coba tanya lagi nanti ya! 😅"})

# 🔹 ROUTE EMAIL BLAST (FITUR BARU)
@app.route("/api/cron/daily-blast", methods=['GET'])
def trigger_daily_blast():
    try:
        users = db.reference('users').get()
        if not users: return jsonify({"status": "No users"}), 200
        
        cuaca = get_bmkg_weather()
        berita = get_daily_news_summary_ai()
        tips = get_daily_tips()
        date = datetime.now().strftime("%d %B %Y")
        
        count = 0
        for uid, user in users.items():
            if user.get('email'):
                try:
                    msg = Message(f"🌙 Buletin Malam KTVDI - {date}", recipients=[user['email']])
                    msg.body = f"""Halo Kak {user.get('nama','Sobat')}!\n\nSemoga harimu menyenangkan.\n\n🌤️ Cuaca Besok (JKT): {cuaca}\n\n📰 Berita Hari Ini:\n{berita}\n\n💡 Tips Malam Ini:\n{tips}\n\nSalam,\nModi & Tim KTVDI"""
                    mail.send(msg)
                    count += 1
                except: pass
        return jsonify({"status": "Sent", "count": count}), 200
    except Exception as e: return jsonify({"error": str(e)}), 500

# 🔹 ROUTES LAINNYA
@app.route('/sitemap.xml')
def sitemap(): return send_from_directory('static', 'sitemap.xml')

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("identifier")
        users = db.reference("users").get() or {}
        found_uid, found_user = None, None
        for uid, user in users.items():
            if "email" in user and user["email"].lower() == email.lower():
                found_uid, found_user = uid, user
                break
        if found_uid:
            otp = str(random.randint(100000, 999999))
            db.reference(f"otp/{found_uid}").set({"email": email, "otp": otp})
            try:
                msg = Message("Permintaan Reset Password - KTVDI", recipients=[email])
                msg.body = f"""Yth. {found_user.get('nama','')},

Kami menerima permintaan reset password.
Kode OTP: {otp}

⚠️ Berlaku 1 menit. Jaga kerahasiaan akun Anda.
"""
                mail.send(msg)
                session["reset_uid"] = found_uid
                flash("OTP terkirim ke email.", "success")
                return redirect(url_for("verify_otp"))
            except: flash("Gagal kirim email.", "error")
        else: flash("Email tidak ditemukan.", "error")
    return render_template("forgot-password.html")

@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    uid = session.get("reset_uid")
    if not uid: return redirect(url_for("forgot_password"))
    if request.method == "POST":
        otp_in = request.form.get("otp")
        data = db.reference(f"otp/{uid}").get()
        if data and data["otp"] == otp_in:
            flash("OTP Benar.", "success")
            return redirect(url_for("reset_password"))
        flash("OTP Salah.", "error")
    return render_template("verify-otp.html")

@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    uid = session.get("reset_uid")
    if not uid: return redirect(url_for("forgot_password"))
    if request.method == "POST":
        pw = request.form.get("password")
        if len(pw) < 8:
            flash("Minimal 8 karakter.", "error")
            return render_template("reset-password.html")
        db.reference(f"users/{uid}").update({"password": hash_password(pw)})
        
        # Kirim notifikasi sukses
        try:
            udata = db.reference(f"users/{uid}").get()
            msg = Message("Password Berhasil Diubah", recipients=[udata['email']])
            msg.body = "Password akun KTVDI Anda telah diubah. Jika bukan Anda, segera lapor."
            mail.send(msg)
        except: pass

        db.reference(f"otp/{uid}").delete()
        session.pop("reset_uid", None)
        flash("Password diubah. Silakan login.", "success")
        return redirect(url_for('login'))
    return render_template("reset-password.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        nama = request.form.get("nama")
        email = request.form.get("email")
        username = request.form.get("username")
        password = request.form.get("password")
        
        if len(password) < 8:
            flash("Password min 8 karakter", "error"); return render_template("register.html")
        if not re.match(r"^[a-z0-9]+$", username):
            flash("Username huruf kecil & angka saja", "error"); return render_template("register.html")
        
        users = db.reference("users").get() or {}
        for uid, u in users.items():
            if u.get("email") == email: flash("Email terdaftar", "error"); return render_template("register.html")
        if username in users: flash("Username dipakai", "error"); return render_template("register.html")
        
        otp = str(random.randint(100000, 999999))
        db.reference(f"pending_users/{username}").set({
            "nama": nama, "email": email, "password": hash_password(password), "otp": otp
        })
        
        try:
            msg = Message("Verifikasi Pendaftaran KTVDI", recipients=[email])
            msg.body = f"""Yth. {nama},

Selamat datang di KTVDI.
Kode OTP: {otp}

⚠️ Berlaku 1 menit. Jaga kerahasiaan.
"""
            mail.send(msg)
            session["pending_username"] = username
            return redirect(url_for("verify_register"))
        except: flash("Gagal kirim email", "error")
    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    u = session.get("pending_username")
    if not u: return redirect(url_for("register"))
    if request.method == "POST":
        p = db.reference(f"pending_users/{u}").get()
        if p and p.get("otp") == request.form.get("otp"):
            db.reference(f"users/{u}").set({
                "nama": p["nama"], "email": p["email"], "password": p["password"], "points": 0
            })
            db.reference(f"pending_users/{u}").delete()
            session.pop("pending_username", None)
            
            try:
                msg = Message("Selamat Datang di KTVDI", recipients=[p['email']])
                msg.body = f"Halo {p['nama']}, Akun Anda aktif. Selamat berkontribusi!"
                mail.send(msg)
            except: pass
            
            flash("Berhasil! Silakan Login.", "success")
            return redirect(url_for('login'))
        flash("OTP Salah", "error")
    return render_template("verify-register.html", username=u)

@app.route("/daftar-siaran")
def daftar_siaran_page(): 
    data = db.reference("provinsi").get() or {}
    return render_template("daftar-siaran.html", provinsi_list=list(data.values()))

@app.route("/get_wilayah")
def get_wilayah(): return jsonify({"wilayah": list((db.reference(f"siaran/{request.args.get('provinsi')}").get() or {}).keys())})
@app.route("/get_mux")
def get_mux(): return jsonify({"mux": list((db.reference(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}").get() or {}).keys())})
@app.route("/get_siaran")
def get_siaran():
    p, w, m = request.args.get("provinsi"), request.args.get("wilayah"), request.args.get("mux")
    return jsonify(db.reference(f"siaran/{p}/{w}/{m}").get() or {})

@app.route('/berita')
def berita_page():
    feed = feedparser.parse('https://news.google.com/rss/search?q=tv+digital&hl=id&gl=ID&ceid=ID:id')
    page = request.args.get('page', 1, type=int)
    per_page = 5
    start = (page-1)*per_page
    end = start+per_page
    current = feed.entries[start:end]
    for a in current: 
        if hasattr(a,'published_parsed'): a.time_since_published = time_since_published(a.published_parsed)
    return render_template('berita.html', articles=current, page=page, total_pages=(len(feed.entries)//per_page)+1)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form['username'].strip()
        p = hash_password(request.form['password'].strip())
        udata = db.reference(f'users/{u}').get()
        if udata and udata.get('password') == p:
            session['user'] = u
            session['nama'] = udata.get('nama', 'Pengguna')
            return redirect(url_for('dashboard'))
        return render_template('login.html', error="Login Gagal")
    return render_template('login.html')

@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    data = db.reference("provinsi").get() or {}
    return render_template("dashboard.html", name=session.get('nama'), provinsi_list=list(data.values()))

@app.route("/add_data", methods=["GET", "POST"])
def add_data():
    if 'user' not in session: return redirect(url_for('login'))
    provs = list((db.reference("provinsi").get() or {}).values())
    if request.method == 'POST':
        p = request.form['provinsi']
        w = request.form['wilayah']
        m = request.form['mux']
        s = request.form['siaran']
        
        # Validasi Regex Lama Anda
        w_clean = re.sub(r'\s*-\s*', '-', w.strip())
        if not re.fullmatch(r"^[a-zA-Z\s]+-\d+$", w_clean):
            return render_template('add_data_form.html', error_message="Format Wilayah Salah", provinsi_list=provs)
        
        now = datetime.now(pytz.timezone('Asia/Jakarta'))
        db.reference(f"siaran/{p}/{w_clean}/{m.strip()}").set({
            "siaran": sorted([x.strip() for x in s.split(',') if x.strip()]),
            "last_updated_by_username": session.get('user'),
            "last_updated_by_name": session.get('nama'),
            "last_updated_date": now.strftime("%d-%m-%Y"),
            "last_updated_time": now.strftime("%H:%M:%S WIB")
        })
        return redirect(url_for('dashboard'))
    return render_template('add_data_form.html', provinsi_list=provs)

@app.route("/edit_data/<provinsi>/<wilayah>/<mux>", methods=["GET", "POST"])
def edit_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    
    # Clean URL params
    p = provinsi.replace('%20', ' ')
    w = wilayah.replace('%20', ' ')
    m = mux.replace('%20', ' ')

    if request.method == 'POST':
        s = request.form['siaran']
        now = datetime.now(pytz.timezone('Asia/Jakarta'))
        db.reference(f"siaran/{p}/{w}/{m}").update({
            "siaran": sorted([x.strip() for x in s.split(',') if x.strip()]),
            "last_updated_date": now.strftime("%d-%m-%Y"),
            "last_updated_time": now.strftime("%H:%M:%S WIB")
        })
        return redirect(url_for('dashboard'))
    return render_template('edit_data_form.html', provinsi=p, wilayah=w, mux=m)

@app.route("/delete_data/<provinsi>/<wilayah>/<mux>", methods=["POST"])
def delete_data(provinsi, wilayah, mux):
    if 'user' in session: 
        db.reference(f"siaran/{provinsi}/{wilayah}/{mux}").delete()
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout(): 
    session.pop('user', None)
    return redirect(url_for('login'))

@app.route("/cctv")
def cctv_page(): return render_template("cctv.html")

@app.route("/jadwal-sholat")
def jadwal_sholat_page():
    if 'user' in session and not session.get('sholat_sent'):
        try:
            u = db.reference(f"users/{session['user']}").get()
            msg = Message("Pengingat Ibadah - KTVDI", recipients=[u['email']])
            msg.body = f"""Assalamualaikum {u.get('nama')},

Pesat dari KTVDI:
"Jadikanlah sabar dan sholat sebagai penolongmu."
Jaga sholat 5 waktu, hindari maksiat, dan jujur dalam bekerja.

Untuk saudara non-muslim: Mari tebar kebaikan dan toleransi.

Salam,
Komunitas TV Digital Indonesia"""
            mail.send(msg)
            session['sholat_sent'] = True
        except: pass
    
    daftar_kota = ["Jakarta", "Surabaya", "Bandung", "Semarang", "Yogyakarta", "Medan", "Makassar", "Denpasar", "Palembang", "Pekalongan"]
    return render_template("jadwal-sholat.html", daftar_kota=sorted(daftar_kota))

if __name__ == "__main__":
    app.run(debug=True)
