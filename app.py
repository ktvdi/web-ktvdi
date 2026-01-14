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
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-ktvdi")

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
        cred = credentials.Certificate("credentials.json") # Fallback untuk lokal

    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred, {'databaseURL': os.environ.get('DATABASE_URL')})

    ref = db.reference('/')
    print("✅ Firebase Connected")
except Exception as e:
    print(f"❌ Firebase Error: {e}")
    ref = None

# ==========================================
# 2. KONFIGURASI EMAIL
# ==========================================
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD")
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")
mail = Mail(app)

# ==========================================
# 3. KONFIGURASI AI CHATBOT (MODI)
# ==========================================

# 👇👇👇 GANTI TULISAN DI BAWAH INI DENGAN API KEY ANDA AGAR CHATBOT JALAN 👇👇👇
API_KEY_DIRECT = "TEMPEL_API_KEY_GEMINI_DISINI" 

# Logika: Cek Environment Variable dulu, kalau kosong pakai yang ditempel langsung
final_api_key = os.environ.get("GEMINI_APP_KEY")
if not final_api_key or final_api_key == "None":
    final_api_key = API_KEY_DIRECT

if final_api_key and final_api_key != "TEMPEL_API_KEY_GEMINI_DISINI":
    genai.configure(api_key=final_api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")
    print("✅ Gemini AI Connected")
else:
    model = None
    print("⚠️ API Key Gemini KOSONG/SALAH. Chatbot tidak akan merespons.")

# System Prompt (Karakter Modi)
MODI_PROMPT = """
Kamu adalah MODI, Customer Service & Asisten Virtual dari Komunitas TV Digital Indonesia (KTVDI).
Karaktermu:
1. SANGAT RAMAH, CERIA, dan SUPORTIF. Anggap pengguna adalah teman dekat.
2. Selalu gunakan sapaan "Kak", "Sobat", atau "Bestie".
3. WAJIB menggunakan emoji di setiap kalimat agar tidak kaku (contoh: 😊, 👋, 📺, ✨).
4. Jawab pertanyaan seputar TV Digital, STB, Antena, Sinyal, dan Website KTVDI.
5. Jika ditanya Piala Dunia 2026, jawab: Hak siar dipegang TVRI (Gratis & HD).
6. Akhiri chat dengan menawarkan bantuan lagi.
"""

# Safety Settings (Agar tidak sensitif/bisu)
SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

# ==========================================
# 4. FUNGSI BANTUAN (HELPER)
# ==========================================
def hash_password(pw): return hashlib.sha256(pw.encode()).hexdigest()

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
    """Mengambil Data Cuaca BMKG"""
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
                        codes = {"0":"Cerah ☀️","1":"Cerah Berawan 🌤️","3":"Berawan ☁️","60":"Hujan 🌧️","61":"Hujan 🌧️","95":"Badai ⛈️"}
                        return f"Jakarta Pusat: {codes.get(val, 'Berawan ☁️')}"
        return "Cerah Berawan 🌤️"
    except: return "Cerah Berawan 🌤️"

def get_daily_news_summary_ai():
    """Rangkuman Berita AI"""
    try:
        feed = feedparser.parse('https://news.google.com/rss?hl=id&gl=ID&ceid=ID:id')
        titles = [e.title for e in feed.entries[:5]]
        text = "\n".join(titles)
        if model:
            prompt = f"Buatlah rangkuman berita harian singkat (3 poin) yang santai:\n{text}"
            response = model.generate_content(prompt, safety_settings=SAFETY_SETTINGS)
            return response.text
        return "Cek halaman Berita untuk update terbaru."
    except: return "Gagal memuat berita."

def get_daily_tips():
    tips = [
        "Arahkan antena ke pemancar (MUX) terdekat agar sinyal kuat 📡",
        "Pakai kabel koaksial RG6 berkualitas tinggi 🔌",
        "Scan ulang STB secara berkala 📺",
        "Jaga kebersihan remote TV dan STB ✨",
        "Matikan STB saat tidak ditonton ⚡"
    ]
    return random.choice(tips)

# ==========================================
# 5. ROUTES (HALAMAN & API)
# ==========================================

@app.route("/")
def home():
    # --- LOGIKA STATISTIK ---
    siaran_data = ref.child('siaran').get() if ref else {}
    jumlah_wilayah, jumlah_siaran, jumlah_mux = 0, 0, 0
    siaran_counts = Counter()
    last_updated = None
    
    if siaran_data:
        for prov_data in siaran_data.values():
            if isinstance(prov_data, dict):
                jumlah_wilayah += len(prov_data)
                for wil_data in prov_data.values():
                    if isinstance(wil_data, dict):
                        jumlah_mux += len(wil_data)
                        for detail in wil_data.values():
                            if 'siaran' in detail:
                                jumlah_siaran += len(detail['siaran'])
                                for s in detail['siaran']: siaran_counts[s.lower()] += 1
                            if 'last_updated_date' in detail:
                                try:
                                    curr = datetime.strptime(detail['last_updated_date'], '%d-%m-%Y')
                                    if last_updated is None or curr > last_updated: last_updated = curr
                                except: pass

    most_common = siaran_counts.most_common(1)
    most_common_name = most_common[0][0].upper() if most_common else None
    most_common_count = most_common[0][1] if most_common else 0
    last_update_str = last_updated.strftime('%d-%m-%Y') if last_updated else "-"

    return render_template('index.html', 
        stats={'wilayah': jumlah_wilayah, 'mux': jumlah_mux, 'channel': jumlah_siaran},
        most_common_siaran_name=most_common_name,
        most_common_siaran_count=most_common_count,
        jumlah_wilayah_layanan=jumlah_wilayah,
        jumlah_siaran=jumlah_siaran, 
        jumlah_penyelenggara_mux=jumlah_mux, 
        last_updated_time=last_update_str
    )

# 🔹 API CHATBOT (FIXED)
@app.route('/', methods=['POST'])
def chatbot_api():
    if not model:
        return jsonify({"response": "Maaf Kak, server AI Modi belum terhubung kuncinya. Hubungi admin ya! 🔑"})
        
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

# 🔹 API NEWS TICKER
@app.route("/api/news-ticker")
def news_ticker():
    try:
        feed = feedparser.parse('https://news.google.com/rss?hl=id&gl=ID&ceid=ID:id')
        return jsonify([e.title for e in feed.entries[:15]])
    except: return jsonify([])

# 🔹 API EMAIL BLAST (CRON)
@app.route("/api/cron/daily-blast", methods=['GET'])
def trigger_daily_blast():
    try:
        if not ref: return jsonify({"error": "No Database"}), 500
        users = ref.child('users').get()
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
                    msg.body = f"Halo Kak {user.get('nama','Sobat')}!\n\n🌤️ Cuaca Besok: {cuaca}\n\n📰 Berita:\n{berita}\n\n💡 Tips: {tips}\n\nSalam,\nModi KTVDI"
                    mail.send(msg)
                    count += 1
                except: pass
        return jsonify({"status": "Sent", "count": count}), 200
    except Exception as e: return jsonify({"error": str(e)}), 500

# 🔹 ROUTES HALAMAN LAIN
@app.route("/cctv")
def cctv_page(): return render_template("cctv.html")

@app.route("/jadwal-sholat")
def jadwal_sholat_page():
    if 'user' in session and not session.get('sholat_sent'):
        try:
            u = ref.child(f"users/{session['user']}").get()
            if u and u.get('email'):
                msg = Message("Pengingat Ibadah - KTVDI", recipients=[u['email']])
                msg.body = f"Assalamualaikum {u.get('nama')},\nMari sholat tepat waktu dan tebar kebaikan.\n\nKTVDI"
                mail.send(msg)
                session['sholat_sent'] = True
        except: pass
    return render_template("jadwal-sholat.html", daftar_kota=["Jakarta","Surabaya","Bandung","Semarang","Yogyakarta","Medan","Pekalongan"])

@app.route('/berita')
def berita_page():
    feed = feedparser.parse('https://news.google.com/rss/search?q=tv+digital&hl=id&gl=ID&ceid=ID:id')
    page = request.args.get('page', 1, type=int)
    per_page = 6
    start = (page-1)*per_page
    end = start+per_page
    current = feed.entries[start:end]
    for a in current: 
        if hasattr(a,'published_parsed'): a.time_since_published = time_since_published(a.published_parsed)
    return render_template('berita.html', articles=current, page=page, total_pages=(len(feed.entries)//per_page)+1)

@app.route('/about')
def about(): return render_template('about.html')

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

@app.route('/sitemap.xml')
def sitemap(): return send_from_directory('static', 'sitemap.xml')

# ==========================================
# 6. AUTH & CRUD (FITUR LAMA DIPERTAHANKAN)
# ==========================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form.get('username')
        p = hash_password(request.form.get('password'))
        udata = ref.child(f'users/{u}').get() if ref else None
        if udata and udata.get('password') == p:
            session['user'] = u
            session['nama'] = udata.get('nama', 'Pengguna')
            return redirect(url_for('dashboard'))
        return render_template('login.html', error="Login Gagal")
    return render_template('login.html')

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        u, e, n, p = request.form.get("username"), request.form.get("email"), request.form.get("nama"), request.form.get("password")
        if len(p) < 8: flash("Password min 8 karakter", "error"); return render_template("register.html")
        if not re.match(r"^[a-z0-9]+$", u): flash("Username huruf kecil & angka", "error"); return render_template("register.html")
        
        users = ref.child("users").get() or {}
        if u in users: flash("Username dipakai", "error"); return render_template("register.html")
        
        otp = str(random.randint(100000, 999999))
        ref.child(f'pending_users/{u}').set({"nama": n, "email": e, "password": hash_password(p), "otp": otp})
        
        try:
            msg = Message("Verifikasi KTVDI", recipients=[e])
            msg.body = f"Halo {n},\nKode OTP: {otp}\n\nKTVDI"
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
        if p and p.get("otp") == request.form.get("otp"):
            ref.child(f'users/{u}').set({"nama":p['nama'], "email":p['email'], "password":p['password'], "points":0})
            ref.child(f'pending_users/{u}').delete()
            session.pop('pending_username', None)
            try:
                msg = Message("Selamat Datang!", recipients=[p['email']])
                msg.body = f"Halo {p['nama']}, Akun aktif.\n\nKTVDI"
                mail.send(msg)
            except: pass
            flash("Berhasil!", "success")
            return redirect(url_for('login'))
        flash("OTP Salah", "error")
    return render_template("verify-register.html", username=u)

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("identifier")
        users = ref.child("users").get() or {}
        found_uid = next((uid for uid, v in users.items() if v.get('email')==email), None)
        
        if found_uid:
            otp = str(random.randint(100000, 999999))
            ref.child(f"otp/{found_uid}").set({"email": email, "otp": otp})
            try:
                msg = Message("Reset Password", recipients=[email])
                msg.body = f"Kode OTP: {otp}"
                mail.send(msg)
                session["reset_uid"] = found_uid
                return redirect(url_for("verify_otp"))
            except: flash("Gagal kirim email", "error")
        else: flash("Email tidak ditemukan", "error")
    return render_template("forgot-password.html")

@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    uid = session.get("reset_uid")
    if not uid: return redirect(url_for("forgot_password"))
    if request.method == "POST":
        data = ref.child(f"otp/{uid}").get()
        if data and data["otp"] == request.form.get("otp"):
            session['reset_verified'] = True
            return redirect(url_for("reset_password"))
        flash("OTP Salah", "error")
    return render_template("verify-otp.html")

@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    if not session.get('reset_verified'): return redirect(url_for('login'))
    uid = session.get("reset_uid")
    if request.method == "POST":
        pw = request.form.get("password")
        if len(pw) < 8: flash("Min 8 karakter", "error"); return render_template("reset-password.html")
        ref.child(f"users/{uid}").update({"password": hash_password(pw)})
        ref.child(f"otp/{uid}").delete()
        
        # Email Sukses
        try:
            udata = ref.child(f"users/{uid}").get()
            msg = Message("Password Berhasil Diubah", recipients=[udata['email']])
            msg.body = "Password akun Anda telah diubah. Jika bukan Anda, lapor admin."
            mail.send(msg)
        except: pass
        
        session.clear()
        flash("Sukses", "success")
        return redirect(url_for('login'))
    return render_template("reset-password.html")

@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    data = ref.child("provinsi").get() or {}
    return render_template("dashboard.html", name=session.get('nama'), provinsi_list=list(data.values()))

@app.route("/daftar-siaran")
def daftar_siaran_page():
    data = ref.child("provinsi").get() or {}
    return render_template("daftar-siaran.html", provinsi_list=list(data.values()))

@app.route("/add_data", methods=["GET", "POST"])
def add_data():
    if 'user' not in session: return redirect(url_for('login'))
    provs = list((ref.child("provinsi").get() or {}).values())
    
    if request.method == 'POST':
        p, w, m, s = request.form['provinsi'], request.form['wilayah'], request.form['mux'], request.form['siaran']
        
        # Validasi Regex Asli Anda
        w_clean = re.sub(r'\s*-\s*', '-', w.strip())
        if not re.fullmatch(r"^[a-zA-Z\s]+-\d+$", w_clean):
            return render_template('add_data_form.html', error_message="Format Wilayah Salah (Contoh: Jawa Tengah-1)", provinsi_list=provs)
        if not re.fullmatch(r"^UHF\s+\d{1,3}\s*-\s*.+$", m.strip()):
            return render_template('add_data_form.html', error_message="Format MUX Salah (Contoh: UHF 27 - Metro TV)", provinsi_list=provs)

        now = datetime.now(pytz.timezone('Asia/Jakarta'))
        ref.child(f"siaran/{p}/{w_clean}/{m.strip()}").set({
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
    
    # URL Decode manual
    p, w, m = provinsi.replace('%20',' '), wilayah.replace('%20',' '), mux.replace('%20',' ')
    
    if request.method == 'POST':
        s = request.form['siaran']
        now = datetime.now(pytz.timezone('Asia/Jakarta'))
        ref.child(f"siaran/{p}/{w}/{m}").update({
            "siaran": sorted([x.strip() for x in s.split(',') if x.strip()]),
            "last_updated_date": now.strftime("%d-%m-%Y"),
            "last_updated_time": now.strftime("%H:%M:%S WIB")
        })
        return redirect(url_for('dashboard'))
    return render_template('edit_data_form.html', provinsi=p, wilayah=w, mux=m)

@app.route("/delete_data/<provinsi>/<wilayah>/<mux>", methods=["POST"])
def delete_data(provinsi, wilayah, mux):
    if 'user' in session: ref.child(f"siaran/{provinsi}/{wilayah}/{mux}").delete()
    return redirect(url_for('dashboard'))

@app.route("/get_wilayah")
def get_wilayah(): return jsonify({"wilayah": list((ref.child(f"siaran/{request.args.get('provinsi')}").get() or {}).keys())})
@app.route("/get_mux")
def get_mux(): return jsonify({"mux": list((ref.child(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}").get() or {}).keys())})
@app.route("/get_siaran")
def get_siaran():
    p, w, m = request.args.get("provinsi"), request.args.get("wilayah"), request.args.get("mux")
    return jsonify(ref.child(f"siaran/{p}/{w}/{m}").get() or {})

if __name__ == "__main__":
    app.run(debug=True)
