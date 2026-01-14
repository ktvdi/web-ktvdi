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

# --- 1. KONEKSI FIREBASE ---
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

# --- 2. EMAIL CONFIG ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME") 
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD") 
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")
mail = Mail(app)

# --- 3. AI CHATBOT (KEY TANAM) ---
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
Tugas: Membantu masyarakat awam memahami TV Digital dengan bahasa yang sangat ramah, sabar, dan jelas.
Gaya: Menggunakan Emoji (😊, 👋, 📺), tidak kaku, seperti teman curhat teknologi.
Aturan:
1. Sapa dengan "Kak" atau "Sobat".
2. Jika tanya Piala Dunia 2026: Jawab hak siar dipegang TVRI (Nasional & Sport), Gratis, HD, pakai STB.
3. Selalu tawarkan bantuan lain di akhir.
"""

SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
]

# --- 4. HELPERS ---
def get_news_entries():
    """Mengambil 20+ Berita Terbaru dari Google News & CNN"""
    all_news = []
    sources = [
        'https://news.google.com/rss/search?q=tv+digital+indonesia&hl=id&gl=ID&ceid=ID:id',
        'https://www.cnnindonesia.com/teknologi/rss',
        'https://www.antaranews.com/rss/tekno.xml'
    ]
    for url in sources:
        try:
            feed = feedparser.parse(url)
            if feed.entries:
                # Tambahkan source name untuk variasi
                for entry in feed.entries:
                    entry['source_name'] = feed.feed.title if 'title' in feed.feed else "News"
                all_news.extend(feed.entries)
        except: continue
    
    # Sortir berdasarkan waktu terbaru (Descending)
    all_news.sort(key=lambda x: x.published_parsed if x.get('published_parsed') else time.gmtime(0), reverse=True)
    
    # Ambil 25 teratas dan hapus duplikat judul
    seen_titles = set()
    unique_news = []
    for news in all_news:
        if news.title not in seen_titles:
            unique_news.append(news)
            seen_titles.add(news.title)
            if len(unique_news) >= 25: break
            
    return unique_news

def get_bmkg_weather():
    try:
        url = "https://data.bmkg.go.id/DataMKG/MEWS/DigitalForecast/DigitalForecast-DKIJakarta.xml"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            root = ET.fromstring(r.content)
            for area in root.findall(".//area[@description='Jakarta Pusat']"):
                for p in area.findall("parameter[@id='weather']"):
                    t = p.find("timerange")
                    if t:
                        val = t.find("value").text
                        codes = {"0":"Cerah ☀️","1":"Cerah Berawan 🌤️","3":"Berawan ☁️","60":"Hujan 🌧️","95":"Badai ⛈️"}
                        return f"Jakarta Pusat: {codes.get(val, 'Berawan ☁️')}"
        return "Cerah Berawan 🌤️"
    except: return "Cerah Berawan 🌤️"

def get_daily_news_summary_ai():
    entries = get_news_entries()
    if not entries: return "Berita sedang diperbarui."
    titles = [e.title for e in entries[:5]]
    text = "\n".join(titles)
    if model:
        try:
            response = model.generate_content(f"Buat cerita singkat menarik dari berita ini:\n{text}", safety_settings=SAFETY_SETTINGS)
            return response.text
        except: pass
    return "Cek halaman Berita untuk update terbaru."

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

# --- 5. ROUTES ---
@app.route("/")
def home():
    siaran_data = ref.child('siaran').get() if ref else {}
    stats = {'wilayah': 0, 'mux': 0, 'channel': 0}
    last_updated = None
    if siaran_data:
        for prov in siaran_data.values():
            if isinstance(prov, dict):
                stats['wilayah'] += len(prov)
                for wil in prov.values():
                    if isinstance(wil, dict):
                        stats['mux'] += len(wil)
                        for detail in wil.values():
                            if 'siaran' in detail: stats['channel'] += len(detail['siaran'])
                            if 'last_updated_date' in detail:
                                try:
                                    curr = datetime.strptime(detail['last_updated_date'], '%d-%m-%Y')
                                    if last_updated is None or curr > last_updated: last_updated = curr
                                except: pass
    
    last_str = last_updated.strftime('%d-%m-%Y') if last_updated else "-"
    return render_template('index.html', stats=stats, last_updated_time=last_str)

@app.route('/', methods=['POST'])
def chatbot_api():
    if not model: return jsonify({"response": "Sistem AI sedang inisialisasi. Mohon tunggu sebentar ya Kak. 🙏"})
    data = request.get_json()
    try:
        response = model.generate_content(f"{MODI_PROMPT}\nUser: {data.get('prompt')}\nModi:", safety_settings=SAFETY_SETTINGS)
        return jsonify({"response": response.text})
    except: return jsonify({"response": "Maaf Kak, Modi lagi banyak yang tanya. Coba lagi ya? 😅"})

@app.route("/api/news-ticker")
def news_ticker():
    entries = get_news_entries()
    titles = [e.title for e in entries] # Ambil semua (20-25)
    if not titles: titles = ["Selamat Datang di KTVDI", "Pantau Info TV Digital Terkini", "Siaran Jernih, Canggih, Gratis"]
    return jsonify(titles)

# EMAIL STORYTELLING
@app.route("/api/cron/daily-blast", methods=['GET'])
def trigger_daily_blast():
    try:
        users = ref.child('users').get() if ref else {}
        if not users: return jsonify({"status": "No users"}), 200
        cuaca = get_bmkg_weather()
        berita = get_daily_news_summary_ai()
        date = datetime.now().strftime("%d %B %Y")
        
        for uid, user in users.items():
            if user.get('email'):
                try:
                    msg = Message(f"Surat Senja KTVDI - {date}", recipients=[user['email']])
                    msg.body = f"""Halo Kak {user.get('nama','Sahabat')},

Apa kabar hari ini? Semoga lelah Kakak terbayar dengan istirahat yang nyenyak malam ini.

Kami di KTVDI ingin sedikit bercerita tentang apa yang terjadi di dunia teknologi hari ini, khusus untuk Kakak:

{berita}

Oiya, untuk besok, langit Jakarta diprediksi: {cuaca}. Jangan lupa siapkan payung atau jas hujan jika perlu ya, Kak. Kesehatan Kakak nomor satu.

"Teknologi ada untuk memudahkan hidup, bukan menggantikan kehangatan sapaan antar manusia."

Selamat beristirahat, Kak.

Salam hangat,
Keluarga Besar KTVDI
"""
                    mail.send(msg)
                except: pass
        return jsonify({"status": "Sent"}), 200
    except Exception as e: return jsonify({"error": str(e)}), 500

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
            if hasattr(a,'published_parsed'): 
                dt = datetime(*a.published_parsed[:6])
                diff = datetime.now() - dt
                if diff.days > 0: a.time_since_published = f"{diff.days} hari lalu"
                else: a.time_since_published = f"{diff.seconds//3600} jam lalu"
            a.image = None
            if 'media_content' in a: a.image = a.media_content[0]['url']
            elif 'links' in a:
                for link in a.links:
                    if 'image' in link.type: a.image = link.href
        return render_template('berita.html', articles=current, page=page, total_pages=(len(entries)//per_page)+1)
    except: return render_template('berita.html', articles=[], page=1, total_pages=1)

@app.route("/cctv")
def cctv_page(): return render_template("cctv.html")

@app.route("/jadwal-sholat")
def jadwal_sholat_page():
    if 'user' in session and not session.get('sholat_sent'):
        try:
            u = ref.child(f"users/{session['user']}").get()
            if u and u.get('email'):
                msg = Message("Panggilan Ketenangan Hati", recipients=[u['email']])
                msg.body = f"Assalamualaikum Kak {u.get('nama')},\n\nDi tengah kesibukan, suara adzan adalah panggilan sayang dari-Nya untuk kita istirahat sejenak. Mari sholat tepat waktu.\n\nSalam,\nKTVDI"
                mail.send(msg)
                session['sholat_sent'] = True
        except: pass
    kota = ["Ambon", "Balikpapan", "Banda Aceh", "Bandar Lampung", "Bandung", "Banjarmasin", "Batam", "Bekasi", "Bengkulu", "Bogor", "Bukittinggi", "Cilegon", "Cimahi", "Cirebon", "Denpasar", "Depok", "Dumai", "Gorontalo", "Jakarta", "Jambi", "Jayapura", "Kediri", "Kendari", "Kupang", "Lubuklinggau", "Madiun", "Magelang", "Makassar", "Malang", "Mamuju", "Manado", "Mataram", "Medan", "Padang", "Palangkaraya", "Palembang", "Palu", "Pangkal Pinang", "Parepare", "Pasuruan", "Pekalongan", "Pekanbaru", "Pontianak", "Probolinggo", "Purwokerto", "Purwodadi", "Salatiga", "Samarinda", "Semarang", "Serang", "Sidoarjo", "Singkawang", "Solo", "Sorong", "Sukabumi", "Surabaya", "Tangerang", "Tanjung Pinang", "Tarakan", "Tasikmalaya", "Tegal", "Ternate", "Yogyakarta"]
    return render_template("jadwal-sholat.html", daftar_kota=sorted(kota))

# AUTH ROUTES (SAMA SEPERTI SEBELUMNYA, DENGAN EMAIL YANG DIPERBAIKI)
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
        return render_template('login.html', error="Gagal Login")
    return render_template('login.html')

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        u = request.form.get("username")
        e = request.form.get("email")
        p = request.form.get("password")
        n = request.form.get("nama")
        if ref.child("users").get() and u in ref.child("users").get(): flash("Username dipakai", "error"); return render_template("register.html")
        otp = str(random.randint(100000, 999999))
        ref.child(f'pending_users/{u}').set({"nama": n, "email": e, "password": hash_password(p), "otp": otp})
        try:
            msg = Message("Selamat Datang di Keluarga KTVDI", recipients=[e])
            msg.body = f"Halo Kak {n},\n\nTerima kasih sudah bergabung! Untuk memastikan ini benar Kakak, masukkan kode rahasia ini: {otp}\n\nKode ini hanya berlaku sebentar ya. Jangan berikan ke orang lain.\n\nSalam,\nAdmin KTVDI"
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
            flash("Berhasil!", "success")
            return redirect(url_for('login'))
        flash("OTP Salah", "error")
    return render_template("verify-register.html", username=u)

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password(): return render_template("forgot-password.html")
@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp(): return render_template("verify-otp.html")
@app.route("/reset-password", methods=["GET", "POST"])
def reset_password(): return render_template("reset_password.html")

@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    data = ref.child("provinsi").get() or {}
    return render_template("dashboard.html", name=session.get('nama'), provinsi_list=list(data.values()))

@app.route("/daftar-siaran")
def daftar_siaran(): return render_template("daftar-siaran.html", provinsi_list=list((ref.child("provinsi").get() or {}).values()))

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

if __name__ == "__main__":
    app.run(debug=True)
