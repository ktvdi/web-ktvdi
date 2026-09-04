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
import concurrent.futures
import base64  
import json
from firebase_admin import credentials, db
from flask import Flask, request, render_template, redirect, url_for, session, flash, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
from flask_mail import Mail, Message
from datetime import datetime, timedelta, date
import urllib3

# ==========================================
# 1. KONFIGURASI SYSTEM & SECURITY
# ==========================================
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

app = Flask(__name__)
CORS(app)

app.secret_key = "KTVDI_OFFICIAL_SECRET_KEY_FINAL_PRO_2026_SUPER_SECURE"
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 86400 # 24 Jam

# ==========================================
# 2. SISTEM AUTO-MAINTENANCE
# ==========================================
MAINTENANCE_END_DATE = datetime(2026, 2, 3, 7, 0, 0) 

@app.before_request
def maintenance_interceptor():
    if request.endpoint == 'static':
        return None
    now_wib = datetime.utcnow() + timedelta(hours=7) 
    if now_wib < MAINTENANCE_END_DATE:
        return render_template('maintenance.html'), 503
    return None

# ==========================================
# 3. KONEKSI DATABASE (FIREBASE)
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
        if os.path.exists("credentials.json"):
            cred = credentials.Certificate("credentials.json")
        else:
            cred = None
    
    if cred and not firebase_admin._apps:
        firebase_admin.initialize_app(cred, {'databaseURL': os.environ.get('DATABASE_URL')})
    
    if firebase_admin._apps:
        ref = db.reference('/')
        print("INFO: Koneksi Basis Data KTVDI berhasil ditetapkan.")
    else:
        ref = None
        print("WARNING: Kredensial Firebase tidak ditemukan. Sistem berjalan tanpa basis data.")

except Exception as e:
    ref = None
    print(f"ERROR: Kegagalan koneksi basis data. Mode luring diaktifkan. Rincian: {e}")

# ==========================================
# 4. KONFIGURASI EMAIL (SMTP GMAIL)
# ==========================================
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME") 
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD") 
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")
mail = Mail(app)

# ==========================================
# 5. KONFIGURASI AI (GEMINI)
# ==========================================
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyCqEFdnO3N0JBUBuaceTQLejepyDlK_eGU") 

def get_gemini_model():
    try:
        genai.configure(api_key=GEMINI_KEY)
        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
        ]
        return genai.GenerativeModel("gemini-1.5-flash", safety_settings=safety_settings) 
    except Exception as e:
        print(f"ERROR: Konfigurasi model Gemini mengalami kegagalan. Rincian: {e}")
        return None

MODI_PROMPT = """
Anda adalah MODI, Asisten Virtual Resmi dari Komunitas TV Digital Indonesia (KTVDI).
Karakteristik Komunikasi: Sangat profesional, informatif, objektif, dan menggunakan Bahasa Indonesia baku yang tepat sesuai Ejaan Yang Disempurnakan (EYD).
Tugas Utama: 
1. Memberikan respons yang akurat terkait teknologi Televisi Digital, Set Top Box (STB), topologi antena, dan pemecahan masalah (troubleshooting) siaran.
2. Menyampaikan data cuaca dan peringatan dini bencana secara faktual dan presisi.
3. Menghindari penggunaan bahasa gaul, sapaan informal, atau opini pribadi.

INSTRUKSI KRITIKAL: Apabila data Early Warning System (EWS) mengindikasikan bendungan berstatus 'Siaga' atau 'Awas', Anda wajib mengeluarkan peringatan resmi yang instruktif dan berorientasi pada mitigasi risiko.
"""

# ==========================================
# 6. FUNGSI BANTUAN (HELPERS)
# ==========================================

def hash_password(pw): return hashlib.sha256(pw.encode()).hexdigest()
def normalize_input(text): return text.strip().lower() if text else ""

def format_indo_date(time_struct):
    if not time_struct: return datetime.now().strftime("%A, %d %B %Y - %H:%M WIB")
    try:
        dt = datetime.fromtimestamp(time.mktime(time_struct))
        return dt.strftime("%A, %d %B %Y - %H:%M WIB")
    except: return "Informasi Waktu Tidak Tersedia"

def get_email_template(action_type, nama_user, otp_code):
    waktu = datetime.now().strftime("%d %B %Y, Pukul %H:%M WIB")
    if action_type == "REGISTER":
        subject = f"🔐 Verifikasi Keamanan: Pendaftaran Akun KTVDI [{otp_code}]"
        title = "Verifikasi Pendaftaran Akun Baru"
        desc = "Sistem kami mendeteksi permintaan pendaftaran akun baru di portal Komunitas TV Digital Indonesia (KTVDI) yang terafiliasi dengan alamat surel ini."
        warning = "Apabila Anda tidak merasa menginisiasi pendaftaran ini, harap abaikan pesan ini. Kode OTP ini bersifat sangat RAHASIA."
    elif action_type == "RESET":
        subject = f"⚠️ Peringatan Keamanan: Permintaan Atur Ulang Kata Sandi [{otp_code}]"
        title = "Permintaan Atur Ulang Kata Sandi"
        desc = "Sistem kami menerima instruksi untuk mengatur ulang kata sandi (Reset Password) pada akun KTVDI Anda."
        warning = "JANGAN MEMBERIKAN kode ini kepada pihak mana pun, termasuk staf atau administrator KTVDI. Jika permintaan ini bukan dari Anda, segera lakukan pengamanan akun."
    else:
        subject = "Pemberitahuan Sistem KTVDI"; title = "Notifikasi Sistem"; desc = "Terdapat pembaruan informasi terkait akun Anda."; warning = ""

    body = f"""========================================================
SISTEM KEAMANAN RESMI KTVDI
========================================================

Yth. {nama_user},

{desc}

Sebagai langkah otorisasi untuk memproses {title}, mohon gunakan Kode Verifikasi (OTP) berikut:

[ {otp_code} ]

*Catatan: Kode verifikasi ini hanya berlaku selama 60 detik terhitung sejak surel ini diterbitkan.

INSTRUKSI KEAMANAN: {warning}

Rincian Transaksi Sistem:
- Waktu Permintaan : {waktu}
- Status Transaksi : Menunggu Otorisasi Pengguna

Hormat kami,
Divisi Teknologi & Keamanan Informasi,
Komunitas TV Digital Indonesia (KTVDI)
========================================================"""
    return subject, body

# --- CACHE UNTUK BERITA ---
NEWS_CACHE = []
NEWS_LAST_FETCH = 0

def get_news_entries():
    global NEWS_CACHE, NEWS_LAST_FETCH
    if len(NEWS_CACHE) > 0 and (time.time() - NEWS_LAST_FETCH < 30):
        return NEWS_CACHE

    all_news = []
    headers = {'User-Agent': 'Mozilla/5.0'}

    # Ambil BMKG Update (Gempa Terkini)
    try:
        r_bmkg = requests.get("https://data.bmkg.go.id/DataMKG/TEWS/autogempa.xml", timeout=5)
        if r_bmkg.status_code == 200:
            root = ET.fromstring(r_bmkg.content)
            gempa = root.find('gempa')
            if gempa is not None:
                wilayah = gempa.find('Wilayah').text
                magnitude = gempa.find('Magnitude').text
                potensi = gempa.find('Potensi').text
                shakemap = gempa.find('Shakemap').text
                
                all_news.append({
                    'title': f"INFORMASI GEMPA BMKG: Magnitudo {magnitude} di {wilayah} ({potensi})",
                    'link': "https://warning.bmkg.go.id/",
                    'published_parsed': datetime.now().timetuple(),
                    'source_name': 'BMKG Resmi',
                    'image': f"https://data.bmkg.go.id/DataMKG/TEWS/{shakemap}"
                })
    except Exception as e:
        pass

    # Ambil RSS sesuai list terbaru
    try:
        sources = [
            'https://www.kompas.tv/rss',
            'https://www.setneg.go.id/rss',
            'https://www.liputan6.com/rss',
            'https://www.tribunnews.com/rss',
            'https://www.cnnindonesia.com/nasional/rss',
            'https://www.cnbcindonesia.com/news/rss',
            'https://www.antaranews.com/rss/top-news.xml',
            'https://rss.sindonews.com/news'
        ]
        
        def fetch_feed(url):
            try:
                res = requests.get(url, headers=headers, timeout=4)
                if res.status_code == 200:
                    return url, feedparser.parse(res.content)
            except:
                return url, None
            return url, None

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(sources)) as pool:
            futures = [pool.submit(fetch_feed, url) for url in sources]
            for future in concurrent.futures.as_completed(futures):
                url, feed = future.result()
                if feed and feed.entries:
                    for entry in feed.entries[:20]: 
                        if 'kompas.tv' in url: source_name = 'Kompas TV'
                        elif 'setneg' in url: source_name = 'Sekretariat Negara'
                        elif 'liputan6' in url: source_name = 'Liputan 6'
                        elif 'tribunnews' in url: source_name = 'Tribunnews'
                        elif 'cnnindonesia' in url: source_name = 'CNN Indonesia'
                        elif 'cnbcindonesia' in url: source_name = 'CNBC Indonesia'
                        elif 'antara' in url: source_name = 'Antara News'
                        elif 'sindonews' in url: source_name = 'Sindonews'
                        else: source_name = url.split('.')[1].capitalize()
                        
                        entry['source_name'] = source_name
                        
                        img_url = None
                        if 'media_content' in entry and entry.media_content:
                            img_url = entry.media_content[0]['url']
                        if not img_url and 'links' in entry:
                            for link in entry.links:
                                if link.get('type', '').startswith('image'):
                                    img_url = link.get('href'); break
                        if not img_url and 'description' in entry:
                            match = re.search(r'src="([^"]+)"', entry.description)
                            if match: img_url = match.group(1)
                        
                        if not img_url and 'enclosures' in entry:
                            for enc in entry.enclosures:
                                if enc.get('type', '').startswith('image'):
                                    img_url = enc.get('href'); break
                                    
                        entry['image'] = img_url
                        all_news.append(entry)
                        
        all_news.sort(key=lambda x: x.published_parsed if x.get('published_parsed') else time.gmtime(0), reverse=True)
    except: pass
    
    if not all_news:
        if NEWS_CACHE: return NEWS_CACHE
        t = datetime.now().timetuple()
        return [{'title': 'Pusat Informasi KTVDI Beroperasi Normal', 'link': '#', 'published_parsed': t, 'source_name': 'Sistem Internal', 'image': None}]
    
    NEWS_CACHE = all_news[:150] 
    NEWS_LAST_FETCH = time.time()
    
    return NEWS_CACHE

def time_since_published(published_time):
    try:
        now = datetime.now()
        pt = datetime(*published_time[:6])
        diff = now - pt
        if diff.days > 0: return f"{diff.days} hari yang lalu"
        if diff.seconds > 3600: return f"{diff.seconds//3600} jam yang lalu"
        if diff.seconds > 60: return f"{diff.seconds//60} menit yang lalu"
        return "Terbaru"
    except: return "Waktu tidak dapat dipastikan"

def get_smart_fallback_response(text):
    return "Mohon maaf, server kecerdasan buatan kami saat ini sedang memproses volume antrean yang tinggi. Kami memohon kesediaan Anda untuk mencoba kembali dalam beberapa saat."

# ==========================================
# 7. LOGIKA EWS & CUACA
# ==========================================

def smart_convert_cm(value):
    try:
        val_float = float(value)
        if val_float != 0 and val_float < 50: return f"{val_float * 100:.0f}" 
        return f"{val_float:.0f}"
    except: return "0"

def get_cuaca_10_kota():
    cities = [
        {"name": "Semarang", "lat": -6.9667, "lon": 110.4167}, {"name": "Surakarta", "lat": -7.5761, "lon": 110.8294},
        {"name": "Tegal", "lat": -6.8694, "lon": 109.1403}, {"name": "Pekalongan", "lat": -6.8886, "lon": 109.6753},
        {"name": "Salatiga", "lat": -7.3305, "lon": 110.5084}, {"name": "Magelang", "lat": -7.4706, "lon": 110.2178},
        {"name": "Purwokerto", "lat": -7.4245, "lon": 109.2302}, {"name": "Cilacap", "lat": -7.7279, "lon": 109.0077},
        {"name": "Kudus", "lat": -6.8048, "lon": 110.8405}, {"name": "Pati", "lat": -6.7550, "lon": 111.0380}
    ]
    lats = ",".join([str(c['lat']) for c in cities])
    lons = ",".join([str(c['lon']) for c in cities])
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lats}&longitude={lons}&current=temperature_2m,weather_code&timezone=Asia%2FBangkok"
    results = []
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            data_list = data if isinstance(data, list) else [data] if 'current' in data else []
            for i, item in enumerate(data_list):
                if i >= len(cities): break
                code = item['current']['weather_code']
                temp = item['current']['temperature_2m']
                status, icon, anim = "Berawan", "fa-cloud", "float"
                if code in [0, 1]: status, icon, anim = "Cerah", "fa-sun", "spin-slow"
                elif code in [2, 3]: status, icon, anim = "Berawan", "fa-cloud-sun", "float"
                elif code in [45, 48]: status, icon, anim = "Kabut", "fa-smog", "pulse"
                elif code in [51, 53, 55, 61, 63, 65, 80, 81, 82]: status, icon, anim = "Hujan", "fa-cloud-rain", "bounce"
                elif code >= 95: status, icon, anim = "Badai", "fa-bolt", "flash"
                results.append({"kota": cities[i]['name'], "suhu": round(temp), "cuaca": status, "icon": icon, "anim": anim})
    except: pass
    if not results:
        for c in cities: results.append({"kota": c['name'], "suhu": "-", "cuaca": "Tidak Tersedia", "icon": "fa-cloud", "anim": ""})
    return results

def normalize_dam_data(raw_data):
    clean_data = []
    for item in raw_data:
        try:
            latest = item.get('latest_debit_report', {})
            if not isinstance(latest, dict): latest = {}
            name = item.get('dam_name') or item.get('nama') or item.get('name') or "Infrastruktur Bendungan"
            siaga_val = item.get('siaga', 0)
            awas_val = item.get('awas', 0)
            siaga_cm = smart_convert_cm(siaga_val)
            awas_cm = smart_convert_cm(awas_val)
            if float(siaga_cm) == 0: siaga_cm = "200"
            if float(awas_cm) == 0: awas_cm = "300"
            raw_tma = latest.get('limpas') if latest else (item.get('tma') or item.get('siap') or 0)
            tma_cm = smart_convert_cm(raw_tma)
            raw_time = latest.get('created_at') or item.get('updated_at')
            waktu_display = "Pembaruan Terakhir"
            if raw_time:
                try:
                    clean_str = str(raw_time).split('.')[0].replace('Z', '')
                    dt_utc = datetime.strptime(clean_str, "%Y-%m-%dT%H:%M:%S")
                    dt_wib = dt_utc + timedelta(hours=7) 
                    waktu_display = dt_wib.strftime("%d-%m-%Y %H:%M")
                except:
                    waktu_display = str(raw_time)[:16].replace('T', ' ')
            status = latest.get('status') or item.get('status_alert') or 'Operasional Normal'
            pob = latest.get('pob_id')
            petugas = f"ID Petugas: {pob}" if pob else "Unit Pemantauan"
            cuaca_lokal = latest.get('cuaca', 'Berawan') 
            dam = {
                'name': name, 'tma': tma_cm, 'siaga': siaga_cm, 'awas': awas_cm,    
                'inflow': latest.get('debit', 0), 'outflow': latest.get('debit_ke_saluran_induk', 0),
                'status': status, 'cuaca': cuaca_lokal, 'petugas': petugas,
                'updated_at': waktu_display + " WIB", 'lokasi': item.get('river_name') or item.get('regency_name') or 'Jawa Tengah'
            }
            clean_data.append(dam)
        except: continue
    return clean_data

def fetch_ews_data():
    headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
    try:
        ts = int(time.time() * 1000)
        url = f"https://siagakranji.my.id/data/latest_dams.json?t={ts}"
        r = requests.get(url, headers=headers, timeout=6, verify=False)
        if r.status_code == 200:
            data = r.json()
            raw_list = data.get('data') or data.get('result') or (data if isinstance(data, list) else [])
            if raw_list: return normalize_dam_data(raw_list)
    except: pass
    try:
        url = "https://api.ewsjateng.com/api/dams?page=1&pageSize=200"
        r = requests.get(url, headers=headers, timeout=9, verify=False)
        if r.status_code == 200:
            data = r.json()
            raw_list = data.get('data', [])
            return normalize_dam_data(raw_list)
    except: pass
    return []

# ==========================================
# 8. ROUTES & CONTROLLERS
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

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        raw_input = request.form.get('username')
        password = request.form.get('password')
        hashed_pw = hash_password(password)
        clean_input = normalize_input(raw_input)
        if not ref: return render_template('login.html', error="Sistem gagal terhubung ke pangkalan data utama.")
        users = ref.child('users').get() or {}
        target_user = None; target_uid = None
        for uid, data in users.items():
            if not isinstance(data, dict): continue
            if normalize_input(uid) == clean_input: target_user = data; target_uid = uid; break
            if normalize_input(data.get('email')) == clean_input: target_user = data; target_uid = uid; break
        if target_user and target_user.get('password') == hashed_pw:
            session.permanent = True
            session['user'] = target_uid
            session['nama'] = target_user.get('nama', 'Pengguna Terdaftar')
            return redirect(url_for('dashboard'))
        return render_template('login.html', error="Kredensial identitas atau kata sandi yang Anda masukkan tidak valid.")
    return render_template('login.html')

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        u = normalize_input(request.form.get("username"))
        e = normalize_input(request.form.get("email"))
        n = request.form.get("nama")
        p = request.form.get("password")
        if not ref: return "Terjadi galat pada koneksi basis data. Harap hubungi administrator.", 500
        users = ref.child("users").get() or {}
        if u in users:
            flash("Nama pengguna tersebut telah terdaftar di dalam sistem.", "error")
            return render_template("register.html")
        for uid, data in users.items():
            if normalize_input(data.get('email')) == e:
                flash("Alamat surel tersebut telah diasosiasikan dengan akun lain.", "error")
                return render_template("register.html")
        
        otp = str(random.randint(100000, 999999))
        expiry = time.time() + 60 
        ref.child(f'pending_users/{u}').set({"nama": n, "email": e, "password": hash_password(p), "otp": otp, "expiry": expiry})
        try:
            subject, body = get_email_template("REGISTER", n, otp)
            msg = Message(subject, recipients=[e])
            msg.body = body
            mail.send(msg)
            session["pending_username"] = u
            return redirect(url_for("verify_register"))
        except: flash("Kegagalan transmisi surel. Pastikan alamat yang diberikan valid dan aktif.", "error")
    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    u = session.get("pending_username")
    if not u: return redirect(url_for("register"))
    if request.method == "POST":
        p = ref.child(f'pending_users/{u}').get()
        if not p: return redirect(url_for("register"))
        if time.time() > p.get('expiry', 0):
            flash("Sesi kode verifikasi telah berakhir. Silakan lakukan permohonan ulang.", "error")
            ref.child(f'pending_users/{u}').delete()
            return redirect(url_for("register"))
        if str(p.get('otp')).strip() == request.form.get("otp").strip():
            ref.child(f'users/{u}').set({"nama": p['nama'], "email": p['email'], "password": p['password']})
            ref.child(f'pending_users/{u}').delete()
            session.pop('pending_username', None)
            flash("Registrasi telah berhasil diproses. Silakan masuk.", "success")
            return redirect(url_for('login'))
        flash("Kode otorisasi yang Anda masukkan tidak tepat.", "error")
    return render_template("verify-register.html", username=u)

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email_input = normalize_input(request.form.get("identifier"))
        users = ref.child("users").get() or {}
        found_uid = None
        user_name = "Pengguna"
        
        for uid, user_data in users.items():
            if isinstance(user_data, dict) and normalize_input(user_data.get('email')) == email_input:
                found_uid = uid
                user_name = user_data.get('nama', 'Pengguna')
                break
                
        if found_uid:
            otp = str(random.randint(100000, 999999))
            expiry = time.time() + 60
            ref.child(f"otp/{found_uid}").set({"email": email_input, "otp": otp, "expiry": expiry})
            try:
                subject, body = get_email_template("RESET", user_name, otp)
                msg = Message(subject, recipients=[email_input])
                msg.body = body
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
        if time.time() > data.get('expiry', 0):
            flash("Masa berlaku kode verifikasi telah habis.", "error")
            return redirect(url_for("forgot_password"))
        if str(data.get("otp")).strip() == request.form.get("otp").strip():
            session['reset_verified'] = True
            return redirect(url_for("reset_password"))
        flash("Kode verifikasi tidak sesuai.", "error")
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
def logout(): 
    session.clear() 
    return redirect(url_for('login'))

@app.route('/berita')
def berita_page():
    entries = get_news_entries()
    page = request.args.get('page', 1, type=int)
    per_page = 9
    start = (page - 1) * per_page
    end = start + per_page
    current = entries[start:end]
    
    for a in current:
        if 'published_parsed' in a and a['published_parsed']:
            a['formatted_date'] = format_indo_date(a['published_parsed'])
            a['time_since_published'] = time_since_published(a['published_parsed'])
        else:
            a['formatted_date'] = "Data Waktu Tidak Tersedia"
            a['time_since_published'] = "Terkini"

    total_pages = (len(entries)//per_page) + 1
    return render_template('berita.html', articles=current, page=page, total_pages=total_pages)

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
        provinsi = request.form.get("provinsi")
        wilayah = request.form.get("wilayah")
        mux = request.form.get("mux")
        nama_siaran = request.form.get("nama_siaran")
        
        if not all([provinsi, wilayah, mux, nama_siaran]):
            flash("Informasi tidak lengkap. Seluruh kolom wajib diisi.", "error")
            return redirect(url_for("add_data"))
            
        try:
            channel_data = {
                "nama": nama_siaran,
                "ditambahkan_oleh": session.get('nama'),
                "waktu_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            ref.child(f"siaran/{provinsi}/{wilayah}/{mux}/siaran").push(channel_data)
            flash("Data siaran berhasil ditambahkan ke dalam sistem KTVDI.", "success")
            return redirect(url_for("dashboard"))
        except Exception as e:
            flash(f"Terjadi kesalahan saat menyimpan data: {str(e)}", "error")
            return redirect(url_for("add_data"))
            
    return render_template("add-data.html", provinsi_list=provinsi_list)

@app.route('/ews')
def ews_page():
    dams_data = fetch_ews_data()
    cuaca_data = get_cuaca_10_kota()
    return render_template('ews.html', dams=dams_data, cuaca=cuaca_data)

@app.route('/api/chat', methods=['POST'])
def api_chat():
    user_message = request.json.get('message', '')
    if not user_message:
        return jsonify({'response': "Pesan tidak dapat diproses karena kosong."})
        
    model = get_gemini_model()
    if not model:
        return jsonify({'response': get_smart_fallback_response(user_message)})
        
    try:
        full_prompt = f"{MODI_PROMPT}\n\nPertanyaan Pengguna: {user_message}\nJawaban MODI:"
        response = model.generate_content(full_prompt)
        return jsonify({'response': response.text})
    except Exception as e:
        return jsonify({'response': get_smart_fallback_response(user_message)})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
