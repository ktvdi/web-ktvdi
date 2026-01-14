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
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-ktvdi")

# --- KONEKSI FIREBASE ---
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

# --- EMAIL ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME") 
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD") 
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")
mail = Mail(app)

# --- AI GEMINI (FIXED) ---
# 👇👇👇 ISI API KEY ANDA DI SINI JIKA DI VERCEL MASIH ERROR 👇👇👇
API_KEY_MANUAL = "TEMPEL_API_KEY_DISINI" 

final_key = os.environ.get("GEMINI_APP_KEY") or (API_KEY_MANUAL if "AIza" in API_KEY_MANUAL else None)

if final_key:
    genai.configure(api_key=final_key)
    model = genai.GenerativeModel("gemini-1.5-flash")
    print("✅ AI Connected")
else:
    model = None
    print("⚠️ AI Key Missing!")

MODI_PROMPT = """
Kamu adalah MODI, Customer Service Profesional dari KTVDI.
Gaya bicara: Ramah, Sopan, Membantu, menggunakan Emoji yang pas.
Tugas: Menjawab pertanyaan seputar TV Digital, STB, Sinyal, dan Website KTVDI.
Aturan: 
1. Sapa user dengan "Kak" atau "Sobat".
2. Jawaban harus solutif dan tidak bertele-tele.
3. Selalu tawarkan bantuan tambahan di akhir.
"""

SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

# --- HELPERS ---
def hash_password(pw): return hashlib.sha256(pw.encode()).hexdigest()

def time_since_published(published_time):
    try:
        now = datetime.now()
        pt = datetime(*published_time[:6])
        diff = now - pt
        if diff.days > 0: return f"{diff.days} hari lalu"
        if diff.seconds > 3600: return f"{diff.seconds//3600} jam lalu"
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
                        codes = {"0":"Cerah ☀️","1":"Cerah Berawan 🌤️","3":"Berawan ☁️","60":"Hujan 🌧️","61":"Hujan 🌧️","95":"Badai ⛈️"}
                        return f"Jakarta Pusat: {codes.get(val, 'Berawan ☁️')}"
        return "Cerah Berawan 🌤️"
    except: return "Cerah Berawan 🌤️"

def get_daily_news_summary_ai():
    try:
        feed = feedparser.parse('https://news.google.com/rss/search?q=teknologi+indonesia&hl=id&gl=ID&ceid=ID:id')
        titles = [e.title for e in feed.entries[:5]]
        text = "\n".join(titles)
        if model:
            prompt = f"Buatlah rangkuman berita harian (3 poin utama) yang menarik dan informatif dari judul-judul berikut:\n{text}"
            response = model.generate_content(prompt, safety_settings=SAFETY_SETTINGS)
            return response.text
        return "Silakan cek halaman Berita untuk informasi terbaru."
    except: return "Gagal memuat berita."

def get_daily_tips():
    tips = [
        "Pastikan antena TV mengarah tepat ke pemancar (MUX) terdekat untuk sinyal maksimal 📡.",
        "Gunakan kabel koaksial RG6 berkualitas tinggi agar sinyal tidak bocor 🔌.",
        "Lakukan pencarian ulang (scan) STB secara berkala untuk mendapatkan channel baru 📺.",
        "Jaga kebersihan remote TV dan STB agar tombol tetap responsif ✨.",
        "Matikan STB saat tidak ditonton untuk menghemat listrik dan menjaga keawetan alat ⚡."
    ]
    return random.choice(tips)

# --- ROUTE UTAMA ---
@app.route("/")
def home():
    siaran_data = ref.child('siaran').get() if ref else {}
    stats = {'wilayah': 0, 'mux': 0, 'channel': 0}
    last_updated = None
    siaran_counts = Counter()

    if siaran_data:
        for prov in siaran_data.values():
            if isinstance(prov, dict):
                stats['wilayah'] += len(prov)
                for wil in prov.values():
                    if isinstance(wil, dict):
                        stats['mux'] += len(wil)
                        for detail in wil.values():
                            if 'siaran' in detail:
                                stats['channel'] += len(detail['siaran'])
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
        stats=stats,
        most_common_siaran_name=most_common_name,
        most_common_siaran_count=most_common_count,
        jumlah_wilayah_layanan=stats['wilayah'],
        jumlah_siaran=stats['channel'], 
        jumlah_penyelenggara_mux=stats['mux'], 
        last_updated_time=last_update_str
    )

# --- CHATBOT API (FIXED) ---
@app.route('/', methods=['POST'])
def chatbot_api():
    if not model:
        return jsonify({"response": "Maaf Kak, sistem Modi sedang gangguan (API Key belum terpasang). Mohon hubungi admin. 🙏"})
        
    data = request.get_json()
    user_msg = data.get("prompt")
    
    if not user_msg:
        return jsonify({"response": "Maaf Kak, Modi tidak mendengar pesan Kakak. Bisa diulangi? 👂"})

    try:
        response = model.generate_content(
            f"{MODI_PROMPT}\nUser: {user_msg}\nModi:",
            safety_settings=SAFETY_SETTINGS
        )
        return jsonify({"response": response.text})
    except Exception as e:
        print(f"AI Error: {e}")
        return jsonify({"response": "Waduh, Modi lagi pusing (Server Busy). Coba tanya lagi nanti ya! 😅"})

# --- NEWS TICKER API ---
@app.route("/api/news-ticker")
def news_ticker():
    try:
        feed = feedparser.parse('https://news.google.com/rss/search?q=tv+digital+indonesia&hl=id&gl=ID&ceid=ID:id')
        news_list = []
        for entry in feed.entries[:10]:
            title = entry.title
            if ' - ' in title:
                parts = title.rsplit(' - ', 1)
                news_list.append(parts[0])
            else:
                news_list.append(title)
        return jsonify(news_list)
    except: return jsonify(["Selamat Datang di KTVDI", "Pantau Informasi TV Digital Terkini"])

# --- EMAIL BLAST CRON (PROFESIONAL) ---
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
                    msg = Message(f"📰 Buletin Harian KTVDI - {date}", recipients=[user['email']])
                    msg.body = f"""Yth. {user.get('nama','Anggota KTVDI')},

Selamat malam dan salam sejahtera.
Semoga hari ini menyenangkan bagi Anda dan keluarga. KTVDI hadir kembali untuk menyampaikan rangkuman informasi harian.

🌤️ **PRAKIRAAN CUACA BESOK**
{cuaca}
*Tetap jaga kesehatan dan persiapkan diri sebelum beraktivitas.*

📰 **RANGKUMAN BERITA HARI INI**
{berita}

💡 **TIPS & RENUNGAN DIGITAL**
"{tips}"
Mari kita senantiasa menjaga etika dalam bermedia sosial, serta memastikan perangkat siaran kita berfungsi optimal untuk mendapatkan informasi yang jernih.

📺 **INFO KOMUNITAS**
Kami mengimbau seluruh anggota untuk aktif melaporkan kondisi sinyal MUX di wilayah masing-masing melalui dashboard. Kontribusi Anda sangat berarti bagi pemerataan informasi.

Selamat beristirahat.

Hormat kami,
**Pengurus Pusat KTVDI**
Komunitas TV Digital Indonesia
"""
                    mail.send(msg)
                    count += 1
                except: pass
        return jsonify({"status": "Sent", "count": count}), 200
    except Exception as e: return jsonify({"error": str(e)}), 500

# --- HALAMAN BERITA ---
@app.route('/berita')
def berita_page():
    # Menggunakan Google News RSS Teknologi
    feed = feedparser.parse('https://news.google.com/rss/search?q=teknologi+indonesia&hl=id&gl=ID&ceid=ID:id')
    page = request.args.get('page', 1, type=int)
    per_page = 6
    start = (page - 1) * per_page
    end = start + per_page
    current = feed.entries[start:end]
    for a in current: 
        if hasattr(a,'published_parsed'): a.time_since_published = time_since_published(a.published_parsed)
    return render_template('berita.html', articles=current, page=page, total_pages=(len(feed.entries)//per_page)+1)

# --- ROUTES LAIN ---
@app.route("/cctv")
def cctv_page(): return render_template("cctv.html")

@app.route("/jadwal-sholat")
def jadwal_sholat_page():
    if 'user' in session and not session.get('sholat_sent'):
        try:
            u = ref.child(f"users/{session['user']}").get()
            if u and u.get('email'):
                msg = Message("🕋 Pengingat Ibadah - KTVDI", recipients=[u['email']])
                msg.body = f"Assalamualaikum {u.get('nama')},\n\nPesan KTVDI:\nMari laksanakan sholat tepat waktu. Kejujuran dan integritas adalah kunci keberkahan.\n\nSalam,\nKTVDI"
                mail.send(msg)
                session['sholat_sent'] = True
        except: pass
    return render_template("jadwal-sholat.html", daftar_kota=["Jakarta","Surabaya","Bandung","Semarang","Yogyakarta","Medan","Pekalongan"])

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
        users = ref.child("users").get() or {}
        if u in users: flash("Username dipakai", "error"); return render_template("register.html")
        
        otp = str(random.randint(100000, 999999))
        ref.child(f'pending_users/{u}').set({"nama": n, "email": e, "password": hash_password(p), "otp": otp})
        
        try:
            msg = Message("Verifikasi Pendaftaran KTVDI", recipients=[e])
            msg.body = f"Yth. {n},\n\nSelamat datang di KTVDI.\nKode OTP: {otp}\n\nJaga kerahasiaan akun Anda.\n\nSalam,\nAdmin KTVDI"
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
        if p and str(p['otp']) == request.form.get("otp"):
            ref.child(f'users/{u}').set({"nama":p['nama'], "email":p['email'], "password":p['password'], "points":0})
            ref.child(f'pending_users/{u}').delete()
            session.pop('pending_username', None)
            
            try:
                msg = Message("Selamat Datang Resmi di KTVDI", recipients=[p['email']])
                msg.body = f"Yth. {p['nama']},\n\nSelamat! Akun Anda aktif. Mari berkontribusi untuk penyiaran Indonesia.\n\nSalam,\nKetua KTVDI"
                mail.send(msg)
            except: pass
            
            flash("Berhasil!", "success")
            return redirect(url_for('login'))
        flash("OTP Salah", "error")
    return render_template("verify-register.html", username=u)

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password(): return render_template("forgot-password.html")
@app.route("/verify-reset", methods=["GET", "POST"])
def verify_reset(): return render_template("verify_reset.html")
@app.route("/reset-password", methods=["GET", "POST"])
def reset_password(): return render_template("reset_password.html")

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
def get_siaran():
    p, w, m = request.args.get("provinsi"), request.args.get("wilayah"), request.args.get("mux")
    return jsonify(ref.child(f"siaran/{p}/{w}/{m}").get() or {})

@app.route('/about')
def about(): return render_template('about.html')
@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))
@app.route('/sitemap.xml')
def sitemap(): return send_from_directory('static', 'sitemap.xml')

if __name__ == "__main__":
    app.run(debug=True)
