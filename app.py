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
app.secret_key = os.environ.get("SECRET_KEY", "ktvdi-super-secret-key-2026")

# ==========================================
# 1. KONEKSI FIREBASE (DATABASE)
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
        # Pastikan file credentials.json ada di folder yang sama jika jalan di local
        cred = credentials.Certificate("credentials.json")
    
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred, {'databaseURL': os.environ.get('DATABASE_URL')})
    
    ref = db.reference('/')
    print("✅ Firebase Berhasil Terhubung")
except Exception as e:
    ref = None
    print(f"❌ Firebase Error: {e}")

# ==========================================
# 2. EMAIL CONFIGURATION (PENTING)
# ==========================================
# Pastikan MAIL_PASSWORD di .env adalah "App Password" Gmail (16 digit), bukan password login biasa.
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME") 
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD") 
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")
mail = Mail(app)

# ==========================================
# 3. AI CHATBOT (KEY DITANAM)
# ==========================================
# Kunci API yang Anda berikan:
MY_API_KEY = "AIzaSyCqEFdnO3N0JBUBuaceTQLejepyDlK_eGU"

try:
    genai.configure(api_key=MY_API_KEY)
    # Menggunakan model flash karena lebih cepat dan hemat kuota
    model = genai.GenerativeModel("gemini-1.5-flash")
    print("✅ Gemini AI Siap")
except Exception as e:
    model = None
    print(f"❌ AI Error: {e}")

MODI_PROMPT = """
Anda adalah MODI, Sahabat Digital dari KTVDI (Komunitas TV Digital Indonesia).
Tugas: Membantu masyarakat awam memahami TV Digital dengan bahasa yang hangat, sabar, dan jelas.
Gaya: Menggunakan Emoji (😊, 👋, 📺), bahasa sopan, dan solutif.
Aturan:
1. Sapa dengan "Kak" atau "Sobat KTVDI".
2. Jika tanya Piala Dunia 2026: Jawab hak siar dipegang TVRI (Nasional & Sport), Gratis, HD, pakai STB.
3. Selalu tawarkan bantuan lain di akhir percakapan.
4. Jika user bilang "Terima kasih", jawab dengan "Sama-sama, senang bisa membantu!".
"""

SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
]

# ==========================================
# 4. HELPERS (BERITA & CUACA)
# ==========================================
def get_news_entries():
    """Mengambil Berita Google News & CNN (Campuran Topik)"""
    all_news = []
    sources = [
        'https://news.google.com/rss?hl=id&gl=ID&ceid=ID:id', # Top Stories ID
        'https://www.cnnindonesia.com/nasional/rss',
        'https://www.antaranews.com/rss/tekno.xml'
    ]
    for url in sources:
        try:
            feed = feedparser.parse(url)
            if feed.entries:
                for entry in feed.entries:
                    entry['source_name'] = feed.feed.title if 'title' in feed.feed else "Berita"
                all_news.extend(feed.entries[:10]) # Ambil 10 dari tiap sumber
        except: continue
    
    # Sortir dari yang paling baru
    all_news.sort(key=lambda x: x.published_parsed if x.get('published_parsed') else time.gmtime(0), reverse=True)
    
    # Hapus duplikat
    unique_news = []
    seen = set()
    for news in all_news:
        if news.title not in seen:
            unique_news.append(news)
            seen.add(news.title)
    
    return unique_news[:25] # Kembalikan 25 berita

def get_java_weather():
    """Cuaca Ibukota Provinsi di Jawa"""
    cities = [
        ("DKI Jakarta", "DigitalForecast-DKIJakarta.xml", "Jakarta Pusat"),
        ("Jawa Barat", "DigitalForecast-JawaBarat.xml", "Bandung"),
        ("Jawa Tengah", "DigitalForecast-JawaTengah.xml", "Semarang"),
        ("Yogyakarta", "DigitalForecast-DIYogyakarta.xml", "Yogyakarta"),
        ("Jawa Timur", "DigitalForecast-JawaTimur.xml", "Surabaya"),
        ("Banten", "DigitalForecast-Banten.xml", "Serang")
    ]
    
    weather_report = []
    base_url = "https://data.bmkg.go.id/DataMKG/MEWS/DigitalForecast/"
    
    for province, xml_file, city_name in cities:
        try:
            r = requests.get(base_url + xml_file, timeout=2)
            if r.status_code == 200:
                root = ET.fromstring(r.content)
                # Cari area berdasarkan description kota
                for area in root.findall(".//area"):
                    if area.get("description") == city_name:
                        param = area.find("parameter[@id='weather']")
                        if param:
                            # Ambil timerange pertama (biasanya saat ini/besok pagi)
                            val = param.find("timerange").find("value").text
                            codes = {"0":"Cerah ☀️","1":"Cerah Berawan 🌤️","3":"Berawan ☁️","60":"Hujan 🌧️","95":"Badai ⛈️"}
                            weather = codes.get(val, "Berawan ☁️")
                            weather_report.append(f"- {city_name}: {weather}")
                        break
        except: continue
        
    return "\n".join(weather_report) if weather_report else "Data cuaca sedang dimuat."

def get_daily_news_summary_ai():
    entries = get_news_entries()
    if not entries: return "Tim redaksi sedang merangkum berita terbaru."
    titles = [e.title for e in entries[:5]]
    text = "\n".join(titles)
    if model:
        try:
            response = model.generate_content(f"Buat ringkasan cerita pendek yang menarik dan informatif dari berita berikut:\n{text}", safety_settings=SAFETY_SETTINGS)
            return response.text
        except: pass
    return "Silakan cek halaman Berita untuk update selengkapnya."

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

# ==========================================
# 5. ROUTES (SEMUA FITUR LENGKAP)
# ==========================================

@app.route("/")
def home():
    siaran_data = ref.child('siaran').get() if ref else {}
    stats = {'wilayah': 0, 'mux': 0, 'channel': 0}
    last_updated_time = None
    siaran_counts = Counter()
    most_common_siaran_name = None
    most_common_siaran_count = 0

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
        stats=stats,
        last_updated_time=last_str,
        most_common_siaran_name=most_common_siaran_name,
        most_common_siaran_count=most_common_siaran_count,
        jumlah_wilayah_layanan=stats['wilayah'],
        jumlah_siaran=stats['channel'], 
        jumlah_penyelenggara_mux=stats['mux']
    )

@app.route('/', methods=['POST'])
def chatbot_api():
    if not model: return jsonify({"response": "Maaf Kak, sistem AI sedang loading. Coba refresh halaman ya. 🙏"})
    data = request.get_json()
    try:
        response = model.generate_content(f"{MODI_PROMPT}\nUser: {data.get('prompt')}\nModi:", safety_settings=SAFETY_SETTINGS)
        return jsonify({"response": response.text})
    except: return jsonify({"response": "Maaf Kak, Modi lagi sibuk banget. Coba tanya lagi nanti ya? 😅"})

@app.route("/api/news-ticker")
def news_ticker():
    entries = get_news_entries()
    titles = [e.title for e in entries[:25]]
    if not titles: titles = ["Selamat Datang di KTVDI", "Pantau Info TV Digital Terkini", "Siaran Jernih, Canggih, Gratis"]
    return jsonify(titles)

# --- EMAIL BLAST ---
@app.route("/api/cron/daily-blast", methods=['GET'])
def trigger_daily_blast():
    try:
        users = ref.child('users').get() if ref else {}
        if not users: return jsonify({"status": "No users"}), 200
        
        cuaca_jawa = get_java_weather()
        berita = get_daily_news_summary_ai()
        date = datetime.now().strftime("%d %B %Y")
        
        for uid, user in users.items():
            if user.get('email'):
                try:
                    msg = Message(f"Surat Kabar Senja KTVDI - {date}", recipients=[user['email']])
                    msg.body = f"""Halo Sahabat {user.get('nama','KTVDI')},

Selamat malam. Semoga surat ini menjumpai Kakak dalam keadaan sehat dan hati yang tenang.

Di tengah kesibukan, izinkan kami berbagi sedikit kabar hari ini untuk menemani waktu istirahat Kakak.

--------------------------------------------------
🌤️ Prakiraan Cuaca Esok (Kota Besar Jawa)
{cuaca_jawa}

Jangan lupa siapkan payung atau jas hujan jika diperlukan ya, Kak.
--------------------------------------------------

📰 Cerita Hari Ini
Dunia terus berputar dengan segala beritanya. Berikut rangkuman cerita pilihan AI kami untuk Kakak:

{berita}

--------------------------------------------------
💡 Pesan Malam
"Rumah adalah tempat terbaik untuk kembali. Matikan sejenak notifikasi, dan nikmati obrolan hangat dengan keluarga."

Terima kasih telah menjadi bagian dari keluarga KTVDI.

Salam sayang dan hormat,

**Modi & Tim Pengurus KTVDI**
Komunitas TV Digital Indonesia
"""
                    mail.send(msg)
                except: pass
        return jsonify({"status": "Sent"}), 200
    except Exception as e: return jsonify({"error": str(e)}), 500

# --- AUTH ROUTES (LENGKAP: LOGIN, REGISTER, LUPA PASSWORD) ---

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
        return render_template('login.html', error="Gagal Login: Username atau Password Salah")
    return render_template('login.html')

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        u = request.form.get("username")
        e = request.form.get("email")
        p = request.form.get("password")
        n = request.form.get("nama")
        
        # Validasi Username Unik
        if ref.child("users").get() and u in ref.child("users").get(): 
            flash("Username sudah digunakan, coba yang lain ya.", "error")
            return render_template("register.html")
            
        otp = str(random.randint(100000, 999999))
        
        # Simpan sementara di pending_users
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
        except Exception as err:
            print(f"Mail Error: {err}")
            flash("Gagal mengirim email OTP. Pastikan email Kakak benar.", "error")
            
    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    u = session.get("pending_username")
    if not u: return redirect(url_for("register"))
    
    if request.method == "POST":
        p = ref.child(f'pending_users/{u}').get()
        if p and str(p['otp']) == request.form.get("otp"):
            # Pindahkan ke users resmi
            ref.child(f'users/{u}').set({"nama":p['nama'], "email":p['email'], "password":p['password'], "points":0})
            ref.child(f'pending_users/{u}').delete()
            session.pop('pending_username', None)
            
            try:
                msg = Message("Pelukan Hangat dari KTVDI", recipients=[p['email']])
                msg.body = f"Halo Kak {p['nama']},\n\nSelamat! Akun Kakak sudah aktif sepenuhnya.\nRasanya senang sekali keluarga kami bertambah satu orang hebat lagi hari ini.\n\nSelamat berkontribusi!\n\nSalam sayang,\nKeluarga Besar KTVDI"
                mail.send(msg)
            except: pass
            
            flash("Berhasil! Akun aktif. Silakan Login.", "success")
            return redirect(url_for('login'))
        flash("Kode OTP Salah, coba periksa email lagi ya.", "error")
    return render_template("verify-register.html", username=u)

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("identifier")
        users = ref.child("users").get() or {}
        
        # Cari user berdasarkan email
        found_uid = next((uid for uid, v in users.items() if v.get('email')==email), None)
        
        if found_uid:
            otp = str(random.randint(100000, 999999))
            ref.child(f"otp/{found_uid}").set({"email": email, "otp": otp})
            try:
                msg = Message("Bantuan Pemulihan Akun KTVDI", recipients=[email])
                msg.body = f"""Halo Kak,

Kami mendengar bahwa Kakak mengalami kesulitan untuk masuk ke dalam akun. Jangan khawatir, hal ini wajar terjadi dan kami di sini siap membantu Kakak.

Untuk mengatur ulang kata sandi dan mengamankan akun Kakak kembali, silakan gunakan kode verifikasi berikut:

{otp}

Jika Kakak merasa tidak pernah meminta kode ini, mohon abaikan saja email ini. Keamanan data Kakak adalah prioritas kami.

Semoga hari Kakak menyenangkan!

Salam,
Tim Support KTVDI
"""
                mail.send(msg)
                session["reset_uid"] = found_uid
                return redirect(url_for("verify_otp"))
            except: flash("Gagal kirim email. Coba lagi nanti.", "error")
        else: flash("Email tidak ditemukan di database kami.", "error")
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
        flash("Kode OTP Salah.", "error")
    return render_template("verify-otp.html")

@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    if not session.get('reset_verified'): return redirect(url_for('login'))
    uid = session.get("reset_uid")
    if request.method == "POST":
        pw = request.form.get("password")
        ref.child(f"users/{uid}").update({"password": hash_password(pw)})
        ref.child(f"otp/{uid}").delete()
        
        try:
            udata = ref.child(f"users/{uid}").get()
            msg = Message("Kata Sandi Berhasil Diperbarui", recipients=[udata['email']])
            msg.body = "Halo Kak,\n\nKata sandi Kakak berhasil diperbarui. Silakan login kembali dengan sandi baru.\n\nTetap aman ya!\n\nSalam,\nAdmin KTVDI"
            mail.send(msg)
        except: pass
        
        session.clear()
        flash("Sukses ganti password, silakan login.", "success")
        return redirect(url_for('login'))
    return render_template("reset-password.html")

# --- OTHER ROUTES ---
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

@app.route('/about')
def about(): return render_template('about.html')
@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))
@app.route('/sitemap.xml')
def sitemap(): return send_from_directory('static', 'sitemap.xml')

if __name__ == "__main__":
    app.run(debug=True)
