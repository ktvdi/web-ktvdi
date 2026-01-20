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
import urllib3

# 1. KONFIGURASI SYSTEM
# ----------------------------------------
# Matikan warning SSL agar request ke server pemerintah lancar
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
load_dotenv()

app = Flask(__name__)
CORS(app)

# Konfigurasi Session & Security
app.secret_key = "KTVDI_OFFICIAL_SECRET_KEY_FINAL_PRO_2026_SUPER_SECURE"
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 86400 # 24 Jam

# 2. KONEKSI DATABASE (FIREBASE)
# ----------------------------------------
try:
    if os.environ.get("FIREBASE_PRIVATE_KEY"):
        # Mode Cloud (Vercel / Production)
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
        # Mode Lokal (Development)
        if os.path.exists("credentials.json"):
            cred = credentials.Certificate("credentials.json")
        else:
            cred = None
    
    if cred and not firebase_admin._apps:
        firebase_admin.initialize_app(cred, {'databaseURL': os.environ.get('DATABASE_URL')})
    
    if firebase_admin._apps:
        ref = db.reference('/')
        print("✅ STATUS: Database KTVDI Terhubung.")
    else:
        ref = None
        print("⚠️ STATUS: Firebase credentials tidak ditemukan.")

except Exception as e:
    ref = None
    print(f"⚠️ STATUS: Mode Offline (DB Error: {e})")

# 3. KONFIGURASI EMAIL (SMTP GMAIL)
# ----------------------------------------
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME") 
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD") 
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")
mail = Mail(app)

# 4. KONFIGURASI AI (GEMINI)
# ----------------------------------------
GEMINI_KEY = "AIzaSyCqEFdnO3N0JBUBuaceTQLejepyDlK_eGU" 
try:
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel("gemini-1.5-flash") # Model cepat & stabil
except: model = None

MODI_PROMPT = """
Anda adalah MODI, Asisten Virtual Resmi dari KTVDI (Komunitas TV Digital Indonesia).
Karakter: Profesional, Ramah, Solutif, dan Menggunakan Bahasa Indonesia Baku namun hangat.
Tugas: Menjawab pertanyaan seputar TV Digital, STB, Antena, dan Solusi Masalah Siaran.
Jika ditanya soal bendungan, gunakan data EWS yang diberikan.
"""

# ==========================================
# 5. FUNGSI BANTUAN (HELPERS UTILS)
# ==========================================

def hash_password(pw): return hashlib.sha256(pw.encode()).hexdigest()
def normalize_input(text): return text.strip().lower() if text else ""

def format_indo_date(time_struct):
    if not time_struct: return datetime.now().strftime("%A, %d %B %Y - %H:%M WIB")
    try:
        dt = datetime.fromtimestamp(time.mktime(time_struct))
        return dt.strftime("%A, %d %B %Y - %H:%M WIB")
    except: return "Baru Saja"

def get_news_entries():
    """Mengambil berita dari RSS Feed dengan Fallback"""
    all_news = []
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    try:
        sources = [
            'https://news.google.com/rss?hl=id&gl=ID&ceid=ID:id', 
            'https://www.cnnindonesia.com/nasional/rss',
            'https://www.antaranews.com/rss/top-news.xml',
            'https://www.republika.co.id/rss',
            'https://www.cnbcindonesia.com/news/rss'
        ]
        for url in sources:
            try:
                response = requests.get(url, headers=headers, timeout=4)
                if response.status_code == 200:
                    feed = feedparser.parse(response.content)
                    if feed.entries:
                        for entry in feed.entries[:5]: 
                            if 'cnn' in url: entry['source_name'] = 'CNN Indonesia'
                            elif 'antara' in url: entry['source_name'] = 'Antara News'
                            elif 'republika' in url: entry['source_name'] = 'Republika'
                            elif 'cnbc' in url: entry['source_name'] = 'CNBC Indonesia'
                            else: entry['source_name'] = 'Google News'
                            
                            # Ekstraksi Gambar (Regex)
                            img_url = None
                            if 'media_content' in entry and entry.media_content:
                                img_url = entry.media_content[0]['url']
                            if not img_url and 'links' in entry:
                                for link in entry.links:
                                    if link.get('type', '').startswith('image'):
                                        img_url = link.get('href')
                                        break
                            if not img_url and 'description' in entry:
                                match = re.search(r'src="([^"]+)"', entry.description)
                                if match: img_url = match.group(1)
                            
                            entry['image'] = img_url
                            all_news.append(entry)
            except: continue
        all_news.sort(key=lambda x: x.published_parsed if x.get('published_parsed') else time.gmtime(0), reverse=True)
    except: pass
    
    if not all_news:
        t = datetime.now().timetuple()
        return [{'title': 'Selamat Datang di Portal Informasi KTVDI', 'link': '#', 'published_parsed': t, 'source_name': 'Info Resmi', 'image': None}]
    return all_news[:24]

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
    return {
        "muslim": ["Maka dirikanlah shalat... (QS. An-Nisa: 103)", "Jauhi korupsi sekecil apapun..."],
        "universal": ["Integritas adalah melakukan hal yang benar...", "Damai di dunia dimulai dari damai di hati..."]
    }

def get_smart_fallback_response(text):
    return "<b>Siap Ndan!</b> Sistem AI sedang sibuk. Mohon ulangi pertanyaan atau cek menu yang tersedia. 👮‍♂️"

# ==========================================
# 6. LOGIKA EWS & CUACA (CORE INTELLIGENCE)
# ==========================================

def smart_convert_cm(value):
    """
    Mengubah nilai Meter ke CM secara cerdas.
    - Jika nilai < 50, diasumsikan Meter -> dikali 100.
    - Jika nilai >= 50, diasumsikan sudah CM -> biarkan.
    """
    try:
        val_float = float(value)
        if val_float != 0 and val_float < 50:
            return f"{val_float * 100:.0f}" 
        return f"{val_float:.0f}"
    except:
        return "0"

def get_cuaca_10_kota():
    """Mengambil Data Cuaca 10 Kota Jateng dari Open-Meteo"""
    cities = [
        {"name": "Semarang", "lat": -6.9667, "lon": 110.4167},
        {"name": "Surakarta", "lat": -7.5761, "lon": 110.8294},
        {"name": "Tegal", "lat": -6.8694, "lon": 109.1403},
        {"name": "Pekalongan", "lat": -6.8886, "lon": 109.6753},
        {"name": "Salatiga", "lat": -7.3305, "lon": 110.5084},
        {"name": "Magelang", "lat": -7.4706, "lon": 110.2178},
        {"name": "Purwokerto", "lat": -7.4245, "lon": 109.2302},
        {"name": "Cilacap", "lat": -7.7279, "lon": 109.0077},
        {"name": "Kudus", "lat": -6.8048, "lon": 110.8405},
        {"name": "Pati", "lat": -6.7550, "lon": 111.0380}
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
    
    # Fallback jika API Cuaca Gagal
    if not results:
        for c in cities: results.append({"kota": c['name'], "suhu": "-", "cuaca": "N/A", "icon": "fa-cloud", "anim": ""})
    return results

def normalize_dam_data(raw_data):
    """
    Normalisasi Data Bendungan:
    1. Ambil Batas (Threshold) dari DB, Konversi ke CM.
    2. Ambil TMA Realtime, Konversi ke CM.
    3. Fix Timezone (UTC to WIB +7).
    """
    clean_data = []
    
    for item in raw_data:
        try:
            latest = item.get('latest_debit_report', {})
            if not isinstance(latest, dict): latest = {}

            name = item.get('dam_name') or item.get('nama') or item.get('name') or "Bendungan"
            
            # 1. THRESHOLD (BATAS WAJAR)
            siaga_val = item.get('siaga', 0)
            awas_val = item.get('awas', 0)
            siaga_cm = smart_convert_cm(siaga_val)
            awas_cm = smart_convert_cm(awas_val)
            
            # Fallback jika API mengembalikan 0
            if float(siaga_cm) == 0: siaga_cm = "200"
            if float(awas_cm) == 0: awas_cm = "300"

            # 2. TMA (TINGGI MUKA AIR)
            raw_tma = latest.get('limpas') if latest else (item.get('tma') or item.get('siap') or 0)
            tma_cm = smart_convert_cm(raw_tma)

            # 3. FIX TIMEZONE (UTC -> WIB)
            raw_time = latest.get('created_at') or item.get('updated_at')
            waktu_display = "Hari ini"
            if raw_time:
                try:
                    clean_str = str(raw_time).split('.')[0].replace('Z', '')
                    dt_utc = datetime.strptime(clean_str, "%Y-%m-%dT%H:%M:%S")
                    dt_wib = dt_utc + timedelta(hours=7) # Tambah 7 Jam
                    waktu_display = dt_wib.strftime("%d-%m-%Y %H:%M")
                except:
                    waktu_display = str(raw_time)[:16].replace('T', ' ')

            # 4. DETAIL DATA LAIN
            status = latest.get('status') or item.get('status_alert') or 'Aman'
            pob = latest.get('pob_id')
            petugas = f"Kode: {pob}" if pob else "Tim Piket"
            cuaca_lokal = latest.get('cuaca', 'Berawan') 

            dam = {
                'name': name,
                'tma': tma_cm,     # CM
                'siaga': siaga_cm, # CM
                'awas': awas_cm,   # CM
                'inflow': latest.get('debit', 0),
                'outflow': latest.get('debit_ke_saluran_induk', 0),
                'status': status,
                'cuaca': cuaca_lokal,
                'petugas': petugas,
                'updated_at': waktu_display + " WIB", 
                'lokasi': item.get('river_name') or item.get('regency_name') or 'Jateng'
            }
            clean_data.append(dam)
        except: continue
        
    return clean_data

def fetch_ews_data():
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36', 'Accept': 'application/json'}
    
    # 1. UTAMA: SIAGA KRANJI (Anti-Cache)
    try:
        ts = int(time.time() * 1000)
        url = f"https://siagakranji.my.id/data/latest_dams.json?t={ts}"
        r = requests.get(url, headers=headers, timeout=6, verify=False)
        if r.status_code == 200:
            data = r.json()
            raw_list = data.get('data') or data.get('result') or (data if isinstance(data, list) else [])
            if raw_list: return normalize_dam_data(raw_list)
    except: pass

    # 2. BACKUP: EWS JATENG (Official)
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
# 7. ROUTE LENGKAP & OTENTIKASI
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
        if not ref: return render_template('login.html', error="Koneksi Database Terputus.")
        users = ref.child('users').get() or {}
        target_user = None; target_uid = None
        for uid, data in users.items():
            if not isinstance(data, dict): continue
            if normalize_input(uid) == clean_input: target_user = data; target_uid = uid; break
            if normalize_input(data.get('email')) == clean_input: target_user = data; target_uid = uid; break
        if target_user and target_user.get('password') == hashed_pw:
            session.permanent = True
            session['user'] = target_uid
            session['nama'] = target_user.get('nama', 'Pengguna')
            return redirect(url_for('dashboard'))
        return render_template('login.html', error="Identitas akun atau kata sandi tidak sesuai.")
    return render_template('login.html')

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
            flash("Maaf Kak, Username ini sudah digunakan.", "error")
            return render_template("register.html")
        for uid, data in users.items():
            if normalize_input(data.get('email')) == e:
                flash("Email ini sudah terdaftar.", "error")
                return render_template("register.html")
        
        # OTP 1 MENIT
        otp = str(random.randint(100000, 999999))
        expiry = time.time() + 60 
        ref.child(f'pending_users/{u}').set({"nama": n, "email": e, "password": hash_password(p), "otp": otp, "expiry": expiry})
        try:
            msg = Message("Verifikasi Akun KTVDI", recipients=[e])
            msg.body = f"Kode OTP Anda (1 Menit): {otp}"
            mail.send(msg)
            session["pending_username"] = u
            return redirect(url_for("verify_register"))
        except: flash("Gagal kirim email. Pastikan email aktif.", "error")
    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    u = session.get("pending_username")
    if not u: return redirect(url_for("register"))
    if request.method == "POST":
        p = ref.child(f'pending_users/{u}').get()
        if not p: return redirect(url_for("register"))
        if time.time() > p.get('expiry', 0):
            flash("Kode OTP telah kedaluwarsa.", "error")
            ref.child(f'pending_users/{u}').delete()
            return redirect(url_for("register"))
        if str(p.get('otp')).strip() == request.form.get("otp").strip():
            ref.child(f'users/{u}').set({"nama": p['nama'], "email": p['email'], "password": p['password']})
            ref.child(f'pending_users/{u}').delete()
            session.pop('pending_username', None)
            flash("Registrasi Berhasil.", "success")
            return redirect(url_for('login'))
        flash("Kode OTP Salah.", "error")
    return render_template("verify-register.html", username=u)

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email_input = normalize_input(request.form.get("identifier"))
        users = ref.child("users").get() or {}
        found_uid = None
        for uid, user_data in users.items():
            if isinstance(user_data, dict) and normalize_input(user_data.get('email')) == email_input:
                found_uid = uid; break
        if found_uid:
            otp = str(random.randint(100000, 999999))
            expiry = time.time() + 60
            ref.child(f"otp/{found_uid}").set({"email": email_input, "otp": otp, "expiry": expiry})
            try:
                msg = Message("Reset Password", recipients=[email_input])
                msg.body = f"Kode OTP Reset Password: {otp}"
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
            flash("Kode OTP Kedaluwarsa.", "error")
            return redirect(url_for("forgot_password"))
        if str(data.get("otp")).strip() == request.form.get("otp").strip():
            session['reset_verified'] = True
            return redirect(url_for("reset_password"))
        flash("Kode Salah.", "error")
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
def logout(): session.clear(); return redirect(url_for('login'))

@app.route('/berita')
def berita_page():
    # Menggunakan fungsi baru get_news_entries()
    entries = get_news_entries()
    page = request.args.get('page', 1, type=int)
    per_page = 9
    start = (page - 1) * per_page
    end = start + per_page
    current = entries[start:end]
    
    # Format tanggal untuk UI
    for a in current:
        if 'published_parsed' in a and a['published_parsed']:
            a['formatted_date'] = format_indo_date(a['published_parsed'])
            a['time_since_published'] = time_since_published(a['published_parsed'])
        else:
            a['formatted_date'] = "Baru Saja"
            a['time_since_published'] = "Baru Saja"

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
        p, w, m, s = request.form.get("provinsi"), request.form.get("wilayah"), request.form.get("mux"), request.form.get("siaran")
        if p and w and m and s:
            data_new = {
                "siaran": [ch.strip() for ch in s.split(',')],
                "last_updated_by_name": session.get('nama'),
                "last_updated_by_username": session.get('user'),
                "last_updated_date": datetime.now().strftime("%d-%m-%Y"),
                "last_updated_time": datetime.now().strftime("%H:%M:%S WIB")
            }
            ref.child(f"siaran/{p}/{w}/{m}").set(data_new)
            ref.child(f"provinsi/{p}").set(p)
            flash("Sukses", "success"); return redirect(url_for('dashboard'))
    return render_template("add_data_form.html", provinsi_list=sorted(provinsi_list))

@app.route("/edit_data/<provinsi>/<wilayah>/<mux>", methods=["GET", "POST"])
def edit_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    curr_data = ref.child(f"siaran/{provinsi}/{wilayah}/{mux}").get()
    if request.method == "POST":
        s = request.form.get("siaran")
        ref.child(f"siaran/{provinsi}/{wilayah}/{mux}").update({
            "siaran": [ch.strip() for ch in s.split(',')],
            "last_updated_by_name": session.get('nama'),
            "last_updated_date": datetime.now().strftime("%d-%m-%Y")
        })
        flash("Sukses Update", "success"); return redirect(url_for('dashboard'))
    siaran_str = ", ".join(curr_data.get('siaran', [])) if curr_data else ""
    return render_template("add_data_form.html", edit_mode=True, curr_siaran=siaran_str, provinsi_list=[provinsi], curr_provinsi=provinsi, curr_wilayah=wilayah, curr_mux=mux)

@app.route("/delete_data/<provinsi>/<wilayah>/<mux>", methods=["POST"])
def delete_data(provinsi, wilayah, mux):
    if 'user' in session: 
        try: ref.child(f"siaran/{provinsi}/{wilayah}/{mux}").delete(); return jsonify({"status": "success"})
        except: return jsonify({"status": "error"})
    return jsonify({"status": "unauthorized"})

# API Helper
@app.route("/get_wilayah")
def get_wilayah(): return jsonify({"wilayah": list((ref.child(f"siaran/{request.args.get('provinsi')}").get() or {}).keys())})
@app.route("/get_mux")
def get_mux(): return jsonify({"mux": list((ref.child(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}").get() or {}).keys())})
@app.route("/get_siaran")
def get_siaran(): return jsonify(ref.child(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}/{request.args.get('mux')}").get() or {})

# --- EWS BENDUNGAN & AI CHAT ---
@app.route('/ews-jateng')
def ews_jateng_page():
    dams = fetch_ews_data()
    cuaca_list = get_cuaca_10_kota()
    return render_template('ews-jateng.html', dams=dams, cuaca_list=cuaca_list)

@app.route('/api/chat', methods=['POST'])
def chatbot_api():
    data = request.get_json()
    user_msg = data.get('prompt', '')
    
    # Injeksi Data Real-time ke AI
    if "bendungan" in user_msg.lower() or "banjir" in user_msg.lower():
        dams = fetch_ews_data()
        bahaya = [f"{d['name']} ({d['status']})" for d in dams if 'awas' in d['status'].lower() or 'siaga' in d['status'].lower()]
        
        if bahaya:
            context = f"PERINGATAN: Ada bendungan status bahaya saat ini: {', '.join(bahaya)}. "
        else:
            context = f"INFO: Saat ini terpantau {len(dams)} bendungan dalam kondisi AMAN. "
            
        full_prompt = f"{MODI_PROMPT}\n{context}\nUser: {user_msg}\nModi:"
    else:
        full_prompt = f"{MODI_PROMPT}\nUser: {user_msg}\nModi:"

    if not model: return jsonify({"response": get_smart_fallback_response(user_msg)})
    
    try:
        response = model.generate_content(full_prompt)
        return jsonify({"response": response.text})
    except: return jsonify({"response": get_smart_fallback_response(user_msg)})

@app.route("/jadwal-sholat")
def jadwal_sholat_page():
    kota = ["Ambon", "Balikpapan", "Banda Aceh", "Bandar Lampung", "Bandung", "Banjar", "Banjarbaru", "Banjarmasin", "Batam", "Batu", "Bau-Bau", "Bekasi", "Bengkulu", "Bima", "Binjai", "Bitung", "Blitar", "Bogor", "Bontang", "Bukittinggi", "Cilegon", "Cimahi", "Cirebon", "Denpasar", "Depok", "Dumai", "Gorontalo", "Gunungsitoli", "Jakarta", "Jambi", "Jayapura", "Kediri", "Kendari", "Kotamobagu", "Kupang", "Langsa", "Lhokseumawe", "Lubuklinggau", "Madiun", "Magelang", "Makassar", "Malang", "Manado", "Mataram", "Medan", "Metro", "Mojokerto", "Padang", "Padangpanjang", "Padangsidempuan", "Pagar Alam", "Palangkaraya", "Palembang", "Palopo", "Palu", "Pangkal Pinang", "Parepare", "Pariaman", "Pasuruan", "Payakumbuh", "Pekalongan", "Pekanbaru", "Pematangsiantar", "Pontianak", "Prabumulih", "Probolinggo", "Purwokerto", "Sabang", "Salatiga", "Samarinda", "Sawahlunto", "Semarang", "Serang", "Sibolga", "Singkawang", "Solok", "Sorong", "Subulussalam", "Sukabumi", "Surabaya", "Surakarta", "Tangerang", "Tangerang Selatan", "Tanjungbalai", "Tanjungpinang", "Tarakan", "Tasikmalaya", "Tebing Tinggi", "Tegal", "Ternate", "Tidore Kepulauan", "Tomohon", "Tual", "Yogyakarta"]
    return render_template("jadwal-sholat.html", daftar_kota=sorted(kota), quotes=get_quote_religi())

@app.route("/api/news-ticker")
def news_ticker():
    news = get_news_entries()
    titles = [n['title'] for n in news]
    return jsonify(titles)

@app.route('/about')
def about(): return render_template('about.html')
@app.route('/cctv')
def cctv_page(): return render_template("cctv.html")
@app.route('/sitemap.xml')
def sitemap(): return send_from_directory('static', 'sitemap.xml')

if __name__ == "__main__":
    app.run(debug=True)
