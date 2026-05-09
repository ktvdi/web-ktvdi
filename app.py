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
import json
from firebase_admin import credentials, db
from flask import Flask, request, render_template, redirect, url_for, session, flash, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
from flask_mail import Mail, Message
from datetime import datetime, timedelta
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
# 3. SISTEM TRACKER PENGUNJUNG & LOKASI (VERCEL OPTIMIZED)
# ==========================================
TRACKER_DATA = {
    "date": datetime.now(pytz.timezone('Asia/Jakarta')).date(),
    "daily_ips": set(),
    "online_ips": {},
    "ip_locations": {}
}

def fetch_and_store_location_sync(ip):
    """Pengambilan IP dengan timeout sangat ketat agar Vercel tidak timeout"""
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}?fields=city,country,status", timeout=1.0)
        if r.status_code == 200:
            res = r.json()
            if res.get("status") == "success":
                TRACKER_DATA["ip_locations"][ip] = f"{res.get('city', 'Unknown')}, {res.get('country', 'Unknown')}"
            else:
                TRACKER_DATA["ip_locations"][ip] = "Tidak Terdeteksi"
    except Exception:
        TRACKER_DATA["ip_locations"][ip] = "Tidak Terdeteksi"

@app.before_request
def visitor_tracker():
    # Hanya jalankan pelacakan untuk rute HTML utama, hindari rute statis/API agar server tidak berat
    if request.endpoint and not request.endpoint.startswith(('static', 'api_')):
        tz = pytz.timezone('Asia/Jakarta')
        today = datetime.now(tz).date()
        
        # Reset memori jika hari berganti (simulasi cron lokal)
        if TRACKER_DATA["date"] != today:
            TRACKER_DATA["date"] = today
            TRACKER_DATA["daily_ips"].clear()
            TRACKER_DATA["ip_locations"].clear()
            
        user_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        if user_ip:
            user_ip = user_ip.split(',')[0].strip()
            TRACKER_DATA["daily_ips"].add(user_ip)
            TRACKER_DATA["online_ips"][user_ip] = time.time()
            
            # Cek lokasi jika IP belum ada
            if user_ip not in TRACKER_DATA["ip_locations"] and not user_ip.startswith(('127.', '192.168.', '10.')):
                TRACKER_DATA["ip_locations"][user_ip] = "Mendeteksi..."
                fetch_and_store_location_sync(user_ip)

# ==========================================
# 4. KONEKSI DATABASE (FIREBASE)
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
# 5. KONFIGURASI EMAIL (SMTP GMAIL)
# ==========================================
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME") 
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD") 
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")
mail = Mail(app)

# ==========================================
# 6. KONFIGURASI AI (GEMINI)
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
# 7. FUNGSI BANTUAN (HELPERS)
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
        desc = "Sistem kami mendeteksi permintaan pendaftaran akun baru di portal Komunitas TV Digital Indonesia (KTVDI)."
        warning = "Apabila Anda tidak merasa menginisiasi pendaftaran ini, harap abaikan pesan ini. Kode OTP ini bersifat RAHASIA."
    elif action_type == "RESET":
        subject = f"⚠️ Peringatan Keamanan: Permintaan Atur Ulang Kata Sandi [{otp_code}]"
        title = "Permintaan Atur Ulang Kata Sandi"
        desc = "Sistem kami menerima instruksi untuk mengatur ulang kata sandi (Reset Password) pada akun KTVDI Anda."
        warning = "JANGAN MEMBERIKAN kode ini kepada pihak mana pun, termasuk staf atau administrator KTVDI."
    else:
        subject = "Pemberitahuan Sistem KTVDI"; title = "Notifikasi Sistem"; desc = "Terdapat pembaruan informasi terkait akun Anda."; warning = ""

    body = f"""========================================================
SISTEM KEAMANAN RESMI KTVDI
========================================================

Yth. {nama_user},

{desc}

Sebagai langkah otorisasi untuk memproses {title}, mohon gunakan Kode Verifikasi (OTP) berikut:

[ {otp_code} ]

*Catatan: Kode verifikasi ini hanya berlaku selama 60 detik.

INSTRUKSI KEAMANAN: {warning}

Rincian Transaksi Sistem:
- Waktu Permintaan : {waktu}
- Status Transaksi : Menunggu Otorisasi Pengguna

Hormat kami,
Divisi Teknologi & Keamanan Informasi, KTVDI
========================================================"""
    return subject, body

def get_hijri_date_string():
    HIJRI_OFFSET = -1 
    try:
        tz_jakarta = pytz.timezone('Asia/Jakarta')
        now_wib = datetime.now(tz_jakarta) + timedelta(days=HIJRI_OFFSET)
        url = f"https://api.aladhan.com/v1/gToH?date={now_wib.strftime('%d-%m-%Y')}"
        r = requests.get(url, timeout=2.0)
        if r.status_code == 200:
            data = r.json()['data']['hijri']
            indo_months = {
                "Muharram": "Muharam", "Safar": "Safar", "Rabi' al-awwal": "Rabiul Awal", 
                "Rabi' al-thani": "Rabiul Akhir", "Jumada al-awwal": "Jumadil Awal", 
                "Jumada al-thani": "Jumadil Akhir", "Rajab": "Rajab", "Sha'ban": "Syakban", 
                "Ramadan": "Ramadan", "Shawwal": "Syawal", "Dhu al-Qi'dah": "Zulkaidah", 
                "Dhu al-Hijjah": "Zulhijah"
            }
            d = data['day'].lstrip('0')
            m = indo_months.get(data['month']['en'], data['month']['en'])
            y = data['year']
            return f"{d} {m} {y} H"
    except Exception: pass
    return f"Tanggal Hijriah Tidak Tersedia"

# --- CACHE UNTUK BERITA (VERCEL OPTIMIZED) ---
NEWS_CACHE = []
NEWS_LAST_FETCH = 0

def get_news_entries():
    global NEWS_CACHE, NEWS_LAST_FETCH
    if len(NEWS_CACHE) > 0 and (time.time() - NEWS_LAST_FETCH < 300): # Cache dinaikkan 5 menit agar ringan
        return NEWS_CACHE

    all_news = []
    headers = {'User-Agent': 'Mozilla/5.0'}

    try:
        r_bmkg = requests.get("https://data.bmkg.go.id/DataMKG/TEWS/autogempa.xml", timeout=3.0)
        if r_bmkg.status_code == 200:
            root = ET.fromstring(r_bmkg.content)
            gempa = root.find('gempa')
            if gempa is not None:
                all_news.append({
                    'title': f"INFORMASI GEMPA BMKG: Magnitudo {gempa.find('Magnitude').text} di {gempa.find('Wilayah').text} ({gempa.find('Potensi').text})",
                    'link': "https://warning.bmkg.go.id/",
                    'published_parsed': datetime.now().timetuple(),
                    'source_name': 'BMKG Resmi',
                    'image': f"https://data.bmkg.go.id/DataMKG/TEWS/{gempa.find('Shakemap').text}"
                })
    except Exception: pass

    try:
        # Sumber berita dikurangi jadi 2 saja agar terhindar dari Vercel Timeout (10 Detik)
        sources = [
            'https://news.google.com/rss?hl=id&gl=ID&ceid=ID:id',
            'https://rss.detik.com/index.php/detikcom'
        ]
        
        for url in sources:
            try:
                res = requests.get(url, headers=headers, timeout=2.5)
                if res.status_code == 200:
                    feed = feedparser.parse(res.content)
                    if feed and feed.entries:
                        for entry in feed.entries[:8]: # Ambil masing-masing 8 teratas saja
                            source_name = 'DetikNews' if 'detik' in url else 'Google News'
                            entry['source_name'] = source_name
                            
                            img_url = None
                            if 'media_content' in entry and entry.media_content:
                                img_url = entry.media_content[0]['url']
                            if not img_url and 'links' in entry:
                                for link in entry.links:
                                    if link.get('type', '').startswith('image'): img_url = link.get('href'); break
                            if not img_url and 'description' in entry:
                                match = re.search(r'src="([^"]+)"', entry.description)
                                if match: img_url = match.group(1)
                            
                            entry['image'] = img_url
                            all_news.append(entry)
            except: pass
                        
        all_news.sort(key=lambda x: x.published_parsed if x.get('published_parsed') else time.gmtime(0), reverse=True)
    except: pass
    
    if not all_news:
        if NEWS_CACHE: return NEWS_CACHE
        t = datetime.now().timetuple()
        return [{'title': 'Pusat Informasi KTVDI Beroperasi Normal', 'link': '#', 'published_parsed': t, 'source_name': 'Sistem Internal', 'image': None}]
    
    NEWS_CACHE = all_news[:50] 
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

def get_quote_religi():
    return {
        "muslim": ["Maka dirikanlah shalat... (QS. An-Nisa: 103)", "Hindari perbuatan curang dalam bentuk apa pun.", "Manusia terbaik adalah yang memberikan manfaat bagi sesamanya."],
        "universal": ["Integritas adalah landasan dari setiap tindakan yang benar.", "Kedamaian global bermula dari kedamaian personal.", "Kejujuran adalah nilai tukar universal yang diakui secara global."]
    }

def get_smart_fallback_response(text):
    return "Mohon maaf, server kecerdasan buatan kami saat ini sedang memproses antrean. Silakan coba kembali."

KEMENAG_KOTA_CACHE = []
KEMENAG_LAST_FETCH = 0

def fetch_kemenag_kota():
    global KEMENAG_KOTA_CACHE, KEMENAG_LAST_FETCH
    if len(KEMENAG_KOTA_CACHE) > 50 and (time.time() - KEMENAG_LAST_FETCH < 86400): return KEMENAG_KOTA_CACHE
    try:
        r = requests.get("https://api.myquran.com/v2/sholat/kota/semua", timeout=4.0)
        if r.status_code == 200:
            data = r.json()
            if data.get('status') and 'data' in data:
                all_cities = [{"id": item['id'], "nama": item['lokasi'].title()} for item in data['data']]
                KEMENAG_KOTA_CACHE = sorted(all_cities, key=lambda x: x['nama'])
                KEMENAG_LAST_FETCH = time.time()
                return KEMENAG_KOTA_CACHE
    except Exception: pass
    return [{"id": "1301", "nama": "Kota Jakarta"}, {"id": "1604", "nama": "Kota Semarang"}]

# ==========================================
# 8. LOGIKA EWS & CUACA
# ==========================================
def smart_convert_cm(value):
    try:
        val_float = float(value)
        if val_float != 0 and val_float < 50: return f"{val_float * 100:.0f}" 
        return f"{val_float:.0f}"
    except: return "0"

def get_cuaca_10_kota():
    cities = [{"name": "Semarang", "lat": -6.9667, "lon": 110.4167}, {"name": "Pekalongan", "lat": -6.8886, "lon": 109.6753}]
    lats = ",".join([str(c['lat']) for c in cities])
    lons = ",".join([str(c['lon']) for c in cities])
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lats}&longitude={lons}&current=temperature_2m,weather_code&timezone=Asia%2FBangkok"
    results = []
    try:
        r = requests.get(url, timeout=3.0)
        if r.status_code == 200:
            data = r.json()
            data_list = data if isinstance(data, list) else [data] if 'current' in data else []
            for i, item in enumerate(data_list):
                if i >= len(cities): break
                code = item['current']['weather_code']
                temp = item['current']['temperature_2m']
                status, icon, anim = "Berawan", "fa-cloud", "float"
                if code in [0, 1]: status, icon, anim = "Cerah", "fa-sun", "spin-slow"
                elif code in [51, 53, 55, 61, 63, 65, 80, 81, 82]: status, icon, anim = "Hujan", "fa-cloud-rain", "bounce"
                results.append({"kota": cities[i]['name'], "suhu": round(temp), "cuaca": status, "icon": icon, "anim": anim})
    except: pass
    if not results:
        for c in cities: results.append({"kota": c['name'], "suhu": "-", "cuaca": "Tidak Tersedia", "icon": "fa-cloud", "anim": ""})
    return results

def fetch_ews_data():
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        url = "https://api.ewsjateng.com/api/dams?page=1&pageSize=50"
        r = requests.get(url, headers=headers, timeout=4.0, verify=False)
        if r.status_code == 200:
            clean_data = []
            for item in r.json().get('data', []):
                try:
                    dam = {
                        'name': item.get('dam_name') or "Infrastruktur Bendungan",
                        'status': item.get('status_alert') or 'Operasional Normal',
                        'lokasi': item.get('regency_name') or 'Jawa Tengah'
                    }
                    clean_data.append(dam)
                except: continue
            return clean_data
    except: pass
    return []

# ==========================================
# 9. ROUTES & CONTROLLERS
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
        return render_template('login.html', error="Kredensial identitas atau kata sandi tidak valid.")
    return render_template('login.html')

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    data = ref.child("provinsi").get() or {}
    return render_template("dashboard.html", name=session.get('nama'), provinsi_list=list(data.values()))

@app.route("/daftar-siaran")
def daftar_siaran():
    data = ref.child("provinsi").get() or {}
    return render_template("daftar-siaran.html", provinsi_list=list(data.values()))

@app.route("/get_wilayah")
def get_wilayah(): return jsonify({"wilayah": list((ref.child(f"siaran/{request.args.get('provinsi')}").get() or {}).keys())})
@app.route("/get_mux")
def get_mux(): return jsonify({"mux": list((ref.child(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}").get() or {}).keys())})
@app.route("/get_siaran")
def get_siaran(): return jsonify(ref.child(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}/{request.args.get('mux')}").get() or {})

@app.route('/berita')
def berita_page():
    entries = get_news_entries()
    page = request.args.get('page', 1, type=int)
    per_page = 9
    start = (page - 1) * per_page
    end = start + per_page
    current = entries[start:end]
    for a in current:
        a['formatted_date'] = format_indo_date(a.get('published_parsed'))
        a['time_since_published'] = time_since_published(a.get('published_parsed'))
    total_pages = (len(entries)//per_page) + 1
    return render_template('berita.html', articles=current, page=page, total_pages=total_pages)

@app.route('/ews-jateng')
def ews_jateng_page():
    return render_template('ews-jateng.html', dams=fetch_ews_data(), cuaca_list=get_cuaca_10_kota())

@app.route('/lokasi')
def lokasi_page():
    return render_template('lokasi.html')

@app.route("/jadwal-sholat")
def jadwal_sholat_page():
    return render_template("jadwal-sholat.html", daftar_kota=fetch_kemenag_kota(), quotes=get_quote_religi(), hijri_date=get_hijri_date_string())

@app.route("/api/jadwal-imsakiyah")
def get_jadwal_kemenag():
    try:
        url = f"https://api.myquran.com/v2/sholat/jadwal/{request.args.get('id_kota')}/{request.args.get('tahun', datetime.now().year)}/{request.args.get('bulan', datetime.now().month)}"
        r = requests.get(url, timeout=4.0)
        if r.status_code == 200: return jsonify(r.json())
    except Exception as e: return jsonify({"status": False, "message": str(e)})
    return jsonify({"status": False, "message": "Gagal ke server."})

@app.route('/api/chat', methods=['POST'])
def chatbot_api():
    data = request.get_json()
    user_msg = data.get('prompt', '')
    
    if "bendungan" in user_msg.lower() or "banjir" in user_msg.lower():
        dams = fetch_ews_data()
        bahaya = [f"{d['name']} ({d['status']})" for d in dams if 'awas' in d['status'].lower() or 'siaga' in d['status'].lower()]
        context = f"INSTRUKSI: Bendungan bahaya: {', '.join(bahaya)}." if bahaya else "INFORMASI: Bendungan AMAN."
        full_prompt = f"{MODI_PROMPT}\n{context}\nPengguna: {user_msg}\nModi:"
    else: full_prompt = f"{MODI_PROMPT}\nPengguna: {user_msg}\nModi:"

    model = get_gemini_model()
    if not model: return jsonify({"response": get_smart_fallback_response(user_msg)})
    
    try: 
        response = model.generate_content(full_prompt)
        return jsonify({"response": response.text})
    except Exception: 
        return jsonify({"response": get_smart_fallback_response(user_msg)})

@app.route('/api/detect_violation', methods=['POST'])
def api_detect_violation():
    try:
        chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        plat = f"H {random.randint(1000, 9999)} {random.choice(chars)}{random.choice(chars)}"
        pelanggaran = random.choice(["Pelanggaran Marka Jalan", "Tidak Pakai Sabuk Pengaman", "Tidak Pakai Helm"])
        return jsonify({"status": "success", "plate": plat, "violation": pelanggaran})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/about')
def about(): return render_template('about.html')

@app.route('/cctv')
def cctv_page(): return render_template("cctv.html")

# ==========================================
# 10. VERCEL CRON JOBS ENDPOINT
# ==========================================
@app.route('/api/cron/send-scheduled-email', methods=['GET'])
def cron_send_email():
    """Endpoint ini akan di-trigger oleh Vercel Cron"""
    auth_header = request.headers.get('Authorization')
    if auth_header != f"Bearer {os.environ.get('CRON_SECRET')}":
        return jsonify({"error": "Otorisasi ditolak"}), 401
    
    tipe_notif = request.args.get('tipe')
    if tipe_notif not in ["weekend", "daily_rabu"]:
        return jsonify({"error": "Tipe notifikasi tidak valid"}), 400

    if not ref:
        return jsonify({"error": "Koneksi database terputus"}), 500

    users = ref.child('users').get() or {}
    
    with app.app_context():
        for uid, user_data in users.items():
            if not isinstance(user_data, dict): continue
            
            email_tujuan = user_data.get('email')
            nama_user = user_data.get('nama', 'Anggota KTVDI')
            
            if not email_tujuan: continue

            if tipe_notif == "weekend":
                subject = "Laporan Tinjauan Akhir Pekan & Pembaruan Kondisi Terkini - KTVDI"
                body = f"Yth. Bapak/Ibu {nama_user},\n\nJangan lupa scan ulang STB Anda untuk memastikan kualitas saluran digital di rumah."
            else:
                subject = "Pengingat Pemeliharaan Rutin Infrastruktur Penyiaran - KTVDI"
                body = f"Yth. Bapak/Ibu {nama_user},\n\nMohon pastikan kabel antena dan jack RF STB Anda dalam keadaan aman dan tertancap kokoh."

            try:
                msg = Message(subject, recipients=[email_tujuan])
                msg.body = body
                mail.send(msg)
            except Exception:
                pass

    return jsonify({"status": "sukses", "pesan": f"Email {tipe_notif} telah dikirim."}), 200

# Vercel butuh akses ke instans app Flask
if __name__ == '__main__':
    app.run(debug=True)
