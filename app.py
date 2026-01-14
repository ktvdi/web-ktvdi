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

# Inisialisasi Firebase
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

# Inisialisasi Email
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD")
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")
mail = Mail(app)

# --- KONFIGURASI AI (KEY TANAM) ---
MY_API_KEY = "AIzaSyCqEFdnO3N0JBUBuaceTQLejepyDlK_eGU"

try:
    genai.configure(api_key=MY_API_KEY)
    model = genai.GenerativeModel("gemini-1.5-flash")
    print("✅ AI Connected")
except Exception as e:
    model = None
    print(f"❌ AI Error: {e}")

MODI_PROMPT = """
Anda adalah MODI, Sahabat Digital dari KTVDI.
Tugas: Membantu masyarakat awam memahami TV Digital dengan bahasa yang sangat ramah, sabar, dan jelas.
Gaya: Menggunakan Emoji (😊, 👋, 📺), tidak kaku, seperti teman curhat teknologi.
Aturan:
1. Sapa dengan "Kak" atau "Sobat".
2. Jika tanya Piala Dunia 2026: Jawab hak siar dipegang TVRI (TVRI Nasional & TVRI Sport), Gratis, HD, pakai STB.
3. Selalu tawarkan bantuan lain di akhir.
4. Kalau bilang "Cukup" atau "Sudah" maka ucapkan Terima Kasih".
"""

SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
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

def get_news_entries():
    """Mengambil Berita Google News Indonesia Terupdate (Umum & Tekno)"""
    all_news = []
    # URL Google News Top Stories Indonesia (Bukan cuma tekno)
    sources = [
        'https://news.google.com/rss?hl=id&gl=ID&ceid=ID:id', 
        'https://www.cnnindonesia.com/nasional/rss'
    ]
    for url in sources:
        try:
            feed = feedparser.parse(url)
            if feed.entries:
                for entry in feed.entries:
                    # Tambahkan nama sumber
                    entry['source_name'] = feed.feed.title if 'title' in feed.feed else "Berita"
                all_news.extend(feed.entries[:15]) # Ambil 15 dari tiap sumber
        except: continue
    
    # Sortir dari yang paling baru
    all_news.sort(key=lambda x: x.published_parsed if x.get('published_parsed') else time.gmtime(0), reverse=True)
    
    # Hapus duplikat judul
    unique_news = []
    seen = set()
    for news in all_news:
        if news.title not in seen:
            unique_news.append(news)
            seen.add(news.title)
    
    return unique_news[:20] # Ambil 20 berita teratas

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
    if not entries: return "Sedang merangkum berita..."
    titles = [e.title for e in entries[:5]]
    text = "\n".join(titles)
    if model:
        try:
            response = model.generate_content(f"Ceritakan ulang 3 berita ini dengan gaya bahasa sahabat yang hangat:\n{text}", safety_settings=SAFETY_SETTINGS)
            return response.text
        except: pass
    return "Cek halaman Berita untuk update terbaru hari ini."

# --- ROUTES ---

@app.route("/")
def home():
    siaran_data = ref.child('siaran').get() if ref else {}
    stats = {'wilayah': 0, 'mux': 0, 'channel': 0}
    last_updated_time = None
    most_common_siaran_name = None
    most_common_siaran_count = 0
    siaran_counts = Counter()

    if siaran_data:
        for prov_data in siaran_data.values():
            if isinstance(prov_data, dict):
                stats['wilayah'] += len(prov_data)
                for wil_data in prov_data.values():
                    if isinstance(wil_data, dict):
                        stats['mux'] += len(wil_data)
                        for detail in wil_data.values():
                            if 'siaran' in detail:
                                stats['channel'] += len(detail['siaran'])
                                for s in detail['siaran']: siaran_counts[s.lower()] += 1
                            if 'last_updated_date' in detail:
                                try:
                                    curr = datetime.strptime(detail['last_updated_date'], '%d-%m-%Y')
                                    if last_updated_time is None or curr > last_updated_time: 
                                        last_updated_time = curr
                                except: pass
    
    if siaran_counts:
        most = siaran_counts.most_common(1)[0]
        most_common_siaran_name = most[0].upper()
        most_common_siaran_count = most[1]

    last_str = last_updated_time.strftime('%d-%m-%Y') if last_updated_time else "-"

    return render_template('index.html', 
        stats={'wilayah': stats['wilayah'], 'mux': stats['mux'], 'channel': stats['channel']},
        last_updated_time=last_str,
        most_common_siaran_name=most_common_siaran_name,
        most_common_siaran_count=most_common_siaran_count,
        jumlah_wilayah_layanan=stats['wilayah'],
        jumlah_siaran=stats['channel'], 
        jumlah_penyelenggara_mux=stats['mux']
    )

@app.route('/', methods=['POST'])
def chatbot():
    if not model: return jsonify({"response": "Maaf Kak, sistem AI sedang inisialisasi. Coba refresh halaman ya. 🙏"})
    data = request.get_json()
    try:
        response = model.generate_content(f"{MODI_PROMPT}\nUser: {data.get('prompt')}\nModi:", safety_settings=SAFETY_SETTINGS)
        return jsonify({"response": response.text})
    except: return jsonify({"response": "Maaf Kak, Modi lagi banyak yang tanya. Coba lagi ya? 😅"})

@app.route("/api/news-ticker")
def news_ticker():
    entries = get_news_entries()
    # Ambil judul berita terbaru
    titles = [e.title for e in entries[:20]] 
    if not titles: titles = ["Selamat Datang di KTVDI", "Pantau Info TV Digital Terkini"]
    return jsonify(titles)

# --- EMAIL BLAST (STORYTELLING) ---
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
                    msg = Message(f"💌 Surat Kecil dari KTVDI - {date}", recipients=[user['email']])
                    msg.body = f"""Halo Sahabat {user.get('nama','KTVDI')},

Selamat malam. Semoga surat ini menjumpai Kakak dalam keadaan sehat dan hati yang tenang setelah seharian beraktivitas.

Di tengah hiruk-pikuk kesibukan dunia, KTVDI ingin menyempatkan waktu sejenak untuk menyapa dan berbagi sedikit cerita hari ini. Kami berharap Kakak selalu dalam lindungan-Nya.

🌤️ **Bagaimana Langit Besok?**
Untuk esok hari di wilayah Jakarta dan sekitarnya, diprediksi: {cuaca}. 
Jika Kakak berencana keluar rumah, mohon persiapkan diri ya. Kesehatan Kakak adalah prioritas utama bagi orang-orang tersayang.

📰 **Cerita Hari Ini**
Dunia terus berputar dengan segala beritanya. Berikut sedikit rangkuman cerita yang kami pilihkan khusus untuk Kakak:

{berita}

💡 **Pesan Hangat Sebelum Tidur**
"Teknologi diciptakan untuk memudahkan, namun kehangatan hati manusialah yang menyempurnakan."
Malam ini, mari letakkan sejenak gadget kita. Sapa keluarga tercinta, atau nikmati waktu hening untuk bersyukur atas nafas hari ini.

Terima kasih telah menjadi bagian dari keluarga KTVDI.

Salam sayang dan hormat,

**Tim Pengurus & IT KTVDI**
Komunitas TV Digital Indonesia
"""
                    mail.send(msg)
                except: pass
        return jsonify({"status": "Sent"}), 200
    except Exception as e: return jsonify({"error": str(e)}), 500

# --- REGISTER (EMAIL LENGKAP) ---
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
            msg = Message("Selamat Datang di Rumah Baru Kakak - KTVDI", recipients=[e])
            msg.body = f"""Halo Kak {n},

Selamat datang! Kami sangat bahagia menyambut Kakak sebagai calon anggota keluarga baru Komunitas TV Digital Indonesia.

Langkah Kakak untuk bergabung bersama kami adalah awal dari semangat berbagi informasi yang bermanfaat.

Untuk memastikan keamanan akun Kakak, kami membutuhkan sedikit verifikasi. Berikut adalah kode rahasia untuk Kakak:

>> {otp} <<

Mohon jaga kode ini baik-baik ya Kak, dan masukkan segera di halaman verifikasi.

Kami sudah tidak sabar menunggu partisipasi Kakak di dalam.

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
        if p and str(p['otp']) == request.form.get("otp"):
            ref.child(f'users/{u}').set({"nama":p['nama'], "email":p['email'], "password":p['password'], "points":0})
            ref.child(f'pending_users/{u}').delete()
            session.pop('pending_username', None)
            try:
                msg = Message("Pelukan Hangat dari KTVDI", recipients=[p['email']])
                msg.body = f"Halo Kak {p['nama']},\n\nSelamat! Akun Kakak sudah aktif sepenuhnya.\nRasanya senang sekali keluarga kami bertambah satu orang hebat lagi hari ini.\n\nSelamat berkontribusi!\n\nSalam sayang,\nKeluarga Besar KTVDI"
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
                msg = Message("Bantuan Pemulihan Akun", recipients=[email])
                msg.body = f"Halo Kak,\n\nKami mendengar Kakak kesulitan masuk. Gunakan kode ini: {otp}\n\nSalam,\nTim Support"
                mail.send(msg)
                session["reset_uid"] = found_uid
                return redirect(url_for("verify_otp"))
            except: flash("Gagal kirim email", "error")
        else: flash("Email tidak ditemukan", "error")
    return render_template("forgot-password.html")

@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    uid = session.get("reset_uid")
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
        ref.child(f"users/{uid}").update({"password": hash_password(pw)})
        ref.child(f"otp/{uid}").delete()
        flash("Sukses", "success")
        return redirect(url_for('login'))
    return render_template("reset-password.html")

# 🔹 DASHBOARD & CRUD
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
    provs = list((ref.child("provinsi").get() or {}).values())
    if request.method == 'POST':
        p, w, m, s = request.form['provinsi'], request.form['wilayah'], request.form['mux'], request.form['siaran']
        w_clean = re.sub(r'\s*-\s*', '-', w.strip())
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

@app.route('/about')
def about(): return render_template('about.html')
@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))
@app.route('/sitemap.xml')
def sitemap(): return send_from_directory('static', 'sitemap.xml')

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

if __name__ == "__main__":
    app.run(debug=True)
