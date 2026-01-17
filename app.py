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

# Matikan warning SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

app = Flask(__name__)
CORS(app)

# 1. KONFIGURASI SESI
app.secret_key = "KTVDI_OFFICIAL_SECRET_KEY_FINAL_PRO_2026_SUPER_SECURE"
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 86400 

# 2. KONEKSI FIREBASE
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
        print("✅ STATUS: Database KTVDI Terhubung.")
    else:
        ref = None
        print("⚠️ STATUS: Firebase credentials tidak ditemukan.")

except Exception as e:
    ref = None
    print(f"⚠️ STATUS: Mode Offline (DB Error: {e})")

# 3. EMAIL
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME") 
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD") 
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")
mail = Mail(app)

# 4. AI GEMINI
GEMINI_KEY = "AIzaSyCqEFdnO3N0JBUBuaceTQLejepyDlK_eGU" 
try:
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash") 
except: model = None

MODI_PROMPT = """
Anda adalah MODI, Asisten Virtual Resmi dari KTVDI.
Tugas: Menjawab pertanyaan seputar TV Digital, STB, dan EWS Bendungan Jawa Tengah.
Gunakan data real-time yang diberikan untuk menjawab status bendungan.
"""

# ==========================================
# 5. FUNGSI BANTUAN
# ==========================================

def hash_password(pw): return hashlib.sha256(pw.encode()).hexdigest()
def normalize_input(text): return text.strip().lower() if text else ""

def format_indo_date(time_struct):
    if not time_struct: return datetime.now().strftime("%A, %d %B %Y - %H:%M WIB")
    try:
        dt = datetime.fromtimestamp(time.mktime(time_struct))
        hari_list = ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu']
        bulan_list = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember']
        hari = hari_list[dt.weekday()]
        bulan = bulan_list[dt.month - 1]
        return f"{hari}, {dt.day} {bulan} {dt.year} - {dt.strftime('%H:%M')} WIB"
    except: return "Baru Saja"

def get_news_entries():
    all_news = []
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    try:
        sources = [
            'https://news.google.com/rss?hl=id&gl=ID&ceid=ID:id', 
            'https://www.cnnindonesia.com/nasional/rss',
            'https://www.antaranews.com/rss/top-news.xml'
        ]
        for url in sources:
            try:
                response = requests.get(url, headers=headers, timeout=3)
                if response.status_code == 200:
                    feed = feedparser.parse(response.content)
                    if feed.entries:
                        for entry in feed.entries[:6]: 
                            if 'cnn' in url: entry['source_name'] = 'CNN Indonesia'
                            elif 'antara' in url: entry['source_name'] = 'Antara News'
                            else: entry['source_name'] = entry.get('source', {}).get('title', 'Google News')
                            all_news.append(entry)
            except: continue
        all_news.sort(key=lambda x: x.published_parsed if x.get('published_parsed') else time.gmtime(0), reverse=True)
    except: pass
    if not all_news:
        t = datetime.now().timetuple()
        return [{'title': 'Selamat Datang di Portal Informasi KTVDI', 'link': '#', 'published_parsed': t, 'source_name': 'Info Resmi'}]
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
    return {"muslim": ["Maka dirikanlah shalat..."], "universal": ["Integritas adalah kunci..."]}

def get_smart_fallback_response(text):
    return "Siap Ndan! Monitor 86. Data sedang diproses."

# ==========================================
# 6. LOGIKA CUACA BARU (OPEN-METEO)
# ==========================================

def get_cuaca_10_kota():
    """Menggunakan Open-Meteo untuk 10 Kota Jateng (Pasti Update & Lengkap)"""
    
    cities = [
        {"name": "Semarang", "lat": -6.9667, "lon": 110.4167},
        {"name": "Surakarta", "lat": -7.5761, "lon": 110.8294},
        {"name": "Magelang", "lat": -7.4706, "lon": 110.2178},
        {"name": "Pekalongan", "lat": -6.8886, "lon": 109.6753},
        {"name": "Tegal", "lat": -6.8694, "lon": 109.1403},
        {"name": "Salatiga", "lat": -7.3305, "lon": 110.5084},
        {"name": "Purwokerto", "lat": -7.4245, "lon": 109.2302},
        {"name": "Cilacap", "lat": -7.7279, "lon": 109.0077},
        {"name": "Kudus", "lat": -6.8048, "lon": 110.8405},
        {"name": "Pati", "lat": -6.7550, "lon": 111.0380}
    ]
    
    # Buat URL Request Sekaligus (Batch)
    lats = ",".join([str(c['lat']) for c in cities])
    lons = ",".join([str(c['lon']) for c in cities])
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lats}&longitude={lons}&current=temperature_2m,weather_code&timezone=Asia%2FBangkok"
    
    results = []
    
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            
            # Open-Meteo mengembalikan list jika multiple coords
            if isinstance(data, list):
                for i, item in enumerate(data):
                    code = item['current']['weather_code']
                    temp = item['current']['temperature_2m']
                    
                    # WMO Weather Code Mapping
                    status = "Berawan"
                    icon = "fa-cloud"
                    if code in [0, 1]: status="Cerah"; icon="fa-sun"
                    elif code in [2, 3]: status="Berawan"; icon="fa-cloud-sun"
                    elif code in [45, 48]: status="Kabut"; icon="fa-smog"
                    elif code in [51, 53, 55, 61, 63, 65, 80, 81, 82]: status="Hujan"; icon="fa-cloud-rain"
                    elif code in [95, 96, 99]: status="Badai Petir"; icon="fa-bolt"
                    
                    results.append({
                        "kota": cities[i]['name'],
                        "suhu": round(temp),
                        "cuaca": status,
                        "icon": icon
                    })
            else:
                # Fallback single location (jarang terjadi dgn kode di atas)
                pass
    except Exception as e:
        print(f"Weather API Error: {e}")
        
    # Fallback Data Dummy Jika API Mati Total
    if not results:
        for c in cities:
            results.append({"kota": c['name'], "suhu": "--", "cuaca": "Tidak Tersedia", "icon": "fa-circle-question"})
            
    return results

# ==========================================
# 7. LOGIKA EWS (NORMALISASI CM)
# ==========================================

def normalize_dam_data(raw_data, source_type):
    """Normalisasi Data Bendungan (Convert Meter to CM otomatis)"""
    clean_data = []
    
    for item in raw_data:
        try:
            # 1. Ambil Nama
            name = item.get('dam_name') or item.get('nama') or item.get('name') or "Bendungan"
            
            # 2. Ambil TMA / Limpas / Water Level
            # Prioritas: latest_debit_report -> tma -> limpas -> water_level
            tma_val = 0
            
            # Cek di latest_debit_report (biasa di EWS Jateng)
            latest = item.get('latest_debit_report')
            if latest and isinstance(latest, dict):
                # EWS Jateng biasanya pakai 'limpas' (meter)
                tma_val = latest.get('limpas', 0)
                # Ambil status update dari latest report
                update_time = latest.get('created_at', '-')
                inflow = latest.get('debit', 0)
                outflow = latest.get('debit_ke_saluran_induk', 0)
                status_alert = latest.get('status', 'Normal')
            else:
                # Fallback ke root object (biasa di Siaga Kranji)
                tma_val = item.get('tma') or item.get('tinggi_muka_air') or item.get('water_level') or 0
                update_time = item.get('updated_at', '-')
                inflow = item.get('inflow') or item.get('debit_masuk') or 0
                outflow = item.get('outflow') or item.get('debit_keluar') or 0
                status_alert = item.get('status') or item.get('status_siaga') or 'Normal'

            # 3. KONVERSI METER KE CM (LOGIKA PINTAR)
            # Jika nilai TMA kecil (misal < 50), asumsikan itu Meter -> kali 100
            # Jika nilai TMA besar (misal > 50), asumsikan itu CM -> biarkan
            try:
                val_float = float(tma_val)
                if val_float < 50: # Asumsi Meter
                    display_tma = f"{int(val_float * 100)}" # Jadi CM
                else: # Asumsi sudah CM
                    display_tma = f"{int(val_float)}"
            except:
                display_tma = "0"

            # 4. Format Waktu Update
            try:
                # Coba parse ISO format: 2026-01-17T16:08:11.000000Z
                dt = datetime.strptime(str(update_time).split('.')[0], "%Y-%m-%dT%H:%M:%S")
                formatted_time = dt.strftime("%d-%m-%Y %H:%M")
            except:
                formatted_time = str(update_time)[:16].replace('T', ' ') # Fallback string slice

            dam = {
                'name': name,
                'tma': display_tma, # Sudah dalam CM string
                'inflow': inflow,
                'outflow': outflow,
                'status_alert': status_alert,
                'updated_at_wib': formatted_time,
                'regency_name': item.get('kabupaten') or item.get('river_name') or 'Jateng'
            }
            clean_data.append(dam)
        except Exception as e:
            continue # Skip item error
            
    return clean_data

def fetch_ews_data():
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    # 1. UTAMA: SIAGA KRANJI (Data JSON Bersih)
    try:
        ts = int(time.time() * 1000)
        url = f"https://siagakranji.my.id/data/latest_dams.json?t={ts}"
        r = requests.get(url, headers=headers, timeout=5, verify=False)
        if r.status_code == 200:
            data = r.json()
            # Handle berbagai kemungkinan struktur JSON
            raw_list = []
            if isinstance(data, list): raw_list = data
            elif isinstance(data, dict):
                if 'result' in data: raw_list = data['result']
                elif 'data' in data: raw_list = data['data']
            
            if raw_list:
                return normalize_dam_data(raw_list, 'kranji')
    except: pass

    # 2. BACKUP: EWS JATENG (Official)
    try:
        url = "https://api.ewsjateng.com/api/dams?page=1&pageSize=200"
        r = requests.get(url, headers=headers, timeout=8, verify=False)
        if r.status_code == 200:
            raw = r.json().get('data', [])
            return normalize_dam_data(raw, 'ews')
    except: pass

    return []

# ==========================================
# 8. ROUTES
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
        otp = str(random.randint(100000, 999999))
        expiry = time.time() + 60
        ref.child(f'pending_users/{u}').set({"nama": n, "email": e, "password": hash_password(p), "otp": otp, "expiry": expiry})
        try:
            msg = Message("Verifikasi Akun KTVDI", recipients=[e])
            msg.body = f"Kode OTP Anda (1 Menit): {otp}"
            mail.send(msg)
            session["pending_username"] = u
            return redirect(url_for("verify_register"))
        except: flash("Gagal kirim email.", "error")
    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    u = session.get("pending_username")
    if not u: return redirect(url_for("register"))
    if request.method == "POST":
        p = ref.child(f'pending_users/{u}').get()
        if not p: return redirect(url_for("register"))
        if time.time() > p.get('expiry', 0):
            flash("Kode OTP expired.", "error")
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
                msg.body = f"Kode OTP: {otp}"
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
            flash("Kode Expired.", "error")
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
    try:
        entries = get_news_entries()
        page = request.args.get('page', 1, type=int)
        per_page = 9
        start = (page - 1) * per_page
        end = start + per_page
        current = entries[start:end]
        for a in current:
            if isinstance(a, dict) and 'published_parsed' in a:
                 a['formatted_date'] = format_indo_date(a['published_parsed'])
                 a['time_since_published'] = time_since_published(a['published_parsed'])
            else:
                 a['formatted_date'] = datetime.now().strftime("%A, %d %B %Y - %H:%M WIB")
                 a['time_since_published'] = "Baru saja"
            a['image'] = None
            if 'media_content' in a: a['image'] = a['media_content'][0]['url']
            elif 'links' in a:
                for link in a['links']:
                    if 'image' in link.get('type',''): a['image'] = link.get('href')
            if not a.get('source_name'): a['source_name'] = 'Berita Terkini'
        total_pages = (len(entries)//per_page) + 1
        return render_template('berita.html', articles=current, page=page, total_pages=total_pages)
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

# --- EWS BENDUNGAN ---
@app.route('/ews-jateng')
def ews_jateng_page():
    # 1. Ambil Data Bendungan (Prioritas Kranji, Fallback EWS)
    dams = fetch_ews_data()
    # 2. Ambil Cuaca (Open-Meteo 10 Kota)
    cuaca_list = get_cuaca_10_kota()
    return render_template('ews-jateng.html', dams=dams, cuaca_list=cuaca_list)

@app.route('/api/chat', methods=['POST'])
def chatbot_api():
    data = request.get_json()
    user_msg = data.get('prompt', '')
    
    if not model: return jsonify({"response": get_smart_fallback_response(user_msg)})
    try:
        response = model.generate_content(f"{MODI_PROMPT}\nUser: {user_msg}\nModi:")
        return jsonify({"response": response.text})
    except: return jsonify({"response": get_smart_fallback_response(user_msg)})

@app.route("/jadwal-sholat")
def jadwal_sholat_page():
    kota = ["Jakarta", "Semarang", "Surabaya", "Bandung", "Yogyakarta"] # (Isi lengkap 70 kota disini agar ringkas)
    quotes = get_quote_religi()
    return render_template("jadwal-sholat.html", daftar_kota=sorted(kota), quotes=quotes)

@app.route("/api/news-ticker")
def news_ticker():
    entries = get_news_entries()
    titles = [e.get('title') for e in entries]
    return jsonify(titles)

@app.route('/about')
def about(): return render_template('about.html')
@app.route('/cctv')
def cctv_page(): return render_template("cctv.html")
@app.route('/sitemap.xml')
def sitemap(): return send_from_directory('static', 'sitemap.xml')

if __name__ == "__main__":
    app.run(debug=True)
