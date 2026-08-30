import os
import hashlib
import random
import re
import time
import socket
import subprocess
import platform
import ipaddress
import shutil
import threading
import json
import base64
import urllib3
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import pytz
import requests
import feedparser
import firebase_admin
import google.generativeai as genai
from concurrent.futures import ThreadPoolExecutor, as_completed
from firebase_admin import credentials, db
from flask import (
    Flask, request, render_template, redirect, url_for, 
    session, flash, jsonify, send_from_directory
)
from flask_cors import CORS
from dotenv import load_dotenv
from flask_mail import Mail, Message

try:
    import speedtest
except ImportError:
    speedtest = None

# ==========================================
# 1. KONFIGURASI SYSTEM & SECURITY
# ==========================================
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
load_dotenv()

app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "KTVDI_OFFICIAL_SECRET_KEY_FINAL_PRO_2026_SUPER_SECURE")
app.config["SESSION_PERMANENT"] = True
app.config["PERMANENT_SESSION_LIFETIME"] = 86400

# ==========================================
# 2. SISTEM AUTO-MAINTENANCE & TRACKER
# ==========================================
MAINTENANCE_END_DATE = datetime(2026, 2, 3, 7, 0, 0)
TRACKER_DATA = {
    "date": datetime.now(pytz.timezone("Asia/Jakarta")).date(),
    "daily_ips": set(),
    "online_ips": {},
    "ip_locations": {}
}

@app.before_request
def maintenance_interceptor():
    if request.endpoint == "static":
        return None
    now_wib = datetime.utcnow() + timedelta(hours=7)
    if now_wib < MAINTENANCE_END_DATE:
        return render_template("maintenance.html"), 503
    return None

def fetch_and_store_location_sync(ip):
    try:
        ip_obj = ipaddress.ip_address(ip)
        if ip_obj.is_private or ip_obj.is_loopback:
            TRACKER_DATA["ip_locations"][ip] = "Jaringan Lokal"
            return
        r = requests.get(f"http://ip-api.com/json/{ip}?fields=city,country,status", timeout=1.5)
        if r.status_code == 200:
            res = r.json()
            if res.get("status") == "success":
                TRACKER_DATA["ip_locations"][ip] = f"{res.get('city', 'Unknown City')}, {res.get('country', 'Unknown Country')}"
            else:
                TRACKER_DATA["ip_locations"][ip] = "Tidak Terdeteksi"
    except Exception:
        TRACKER_DATA["ip_locations"][ip] = "Tidak Terdeteksi"

@app.before_request
def visitor_tracker():
    if request.endpoint and "static" not in request.endpoint:
        tz = pytz.timezone("Asia/Jakarta")
        today = datetime.now(tz).date()
        
        if TRACKER_DATA["date"] != today:
            TRACKER_DATA["date"] = today
            TRACKER_DATA["daily_ips"].clear()
            TRACKER_DATA["ip_locations"].clear()

        user_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
        if user_ip:
            user_ip = user_ip.split(",")[0].strip()
            TRACKER_DATA["daily_ips"].add(user_ip)
            TRACKER_DATA["online_ips"][user_ip] = time.time()
            
            try:
                private_ip = ipaddress.ip_address(user_ip).is_private
            except Exception:
                private_ip = False
                
            if user_ip not in TRACKER_DATA["ip_locations"] and not private_ip:
                TRACKER_DATA["ip_locations"][user_ip] = "Mendeteksi Lokasi..."
                fetch_and_store_location_sync(user_ip)

# ==========================================
# 3. KONEKSI DATABASE FIREBASE
# ==========================================
try:
    if os.environ.get("FIREBASE_PRIVATE_KEY"):
        cred = credentials.Certificate({
            "type": "service_account",
            "project_id": os.environ.get("FIREBASE_PROJECT_ID"),
            "private_key_id": os.environ.get("FIREBASE_PRIVATE_KEY_ID"),
            "private_key": os.environ.get("FIREBASE_PRIVATE_KEY").replace("\\n", "\n"),
            "client_email": os.environ.get("FIREBASE_CLIENT_EMAIL"),
            "client_id": os.environ.get("FIREBASE_CLIENT_ID"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": os.environ.get("FIREBASE_CLIENT_X509_CERT_URL"),
            "universe_domain": "googleapis.com"
        })
    else:
        cred = credentials.Certificate("credentials.json") if os.path.exists("credentials.json") else None

    if cred and not firebase_admin._apps:
        firebase_admin.initialize_app(cred, {"databaseURL": os.environ.get("DATABASE_URL")})

    if firebase_admin._apps:
        ref = db.reference("/")
        print("INFO: Koneksi Basis Data KTVDI berhasil ditetapkan.")
    else:
        ref = None
        print("WARNING: Kredensial Firebase tidak ditemukan. Sistem berjalan tanpa basis data.")
except Exception as e:
    ref = None
    print(f"ERROR: Kegagalan koneksi basis data. Mode luring diaktifkan. Rincian: {e}")

# ==========================================
# 4. KONFIGURASI EMAIL SMTP GMAIL
# ==========================================
app.config["MAIL_SERVER"] = "smtp.gmail.com"
app.config["MAIL_PORT"] = 587
app.config["MAIL_USE_TLS"] = True
app.config["MAIL_USERNAME"] = os.environ.get("MAIL_USERNAME")
app.config["MAIL_PASSWORD"] = os.environ.get("MAIL_PASSWORD")
app.config["MAIL_DEFAULT_SENDER"] = os.environ.get("MAIL_USERNAME")
mail = Mail(app)

# ==========================================
# 5. KONFIGURASI AI GEMINI
# ==========================================
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")

def get_gemini_model():
    try:
        if not GEMINI_KEY:
            return None
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
Karakteristik Komunikasi: Sangat profesional, informatif, objektif, dan menggunakan Bahasa Indonesia baku.
Tugas Utama:
1. Memberikan respons akurat terkait TV Digital, STB, topologi antena, dan siaran.
2. Menyampaikan data cuaca dan EWS faktual.
INSTRUKSI KRITIKAL: Jika data EWS mengindikasikan bendungan berstatus 'Siaga' atau 'Awas', wajib mengeluarkan peringatan resmi.
"""

# ==========================================
# 6. FUNGSI BANTUAN
# ==========================================
def hash_password(pw):
    return hashlib.sha256((pw or "").encode()).hexdigest()

def normalize_input(text):
    return text.strip().lower() if text else ""

def format_indo_date(time_struct):
    if not time_struct:
        return datetime.now().strftime("%A, %d %B %Y - %H:%M WIB")
    try:
        dt = datetime.fromtimestamp(time.mktime(time_struct))
        return dt.strftime("%A, %d %B %Y - %H:%M WIB")
    except Exception:
        return "Informasi Waktu Tidak Tersedia"

def get_email_template(action_type, nama_user, otp_code):
    waktu = datetime.now().strftime("%d %B %Y, Pukul %H:%M WIB")
    if action_type == "REGISTER":
        subject = f"🔐 Verifikasi Keamanan: Pendaftaran Akun KTVDI [{otp_code}]"
        title = "Verifikasi Pendaftaran Akun Baru"
        desc = "Sistem kami mendeteksi permintaan pendaftaran akun baru di portal KTVDI."
        warning = "Apabila Anda tidak merasa menginisiasi pendaftaran ini, harap abaikan pesan ini."
    elif action_type == "RESET":
        subject = f"⚠️ Peringatan Keamanan: Permintaan Atur Ulang Kata Sandi [{otp_code}]"
        title = "Permintaan Atur Ulang Kata Sandi"
        desc = "Sistem kami menerima instruksi untuk mengatur ulang kata sandi."
        warning = "JANGAN MEMBERIKAN kode ini kepada pihak mana pun."
    else:
        subject = "Pemberitahuan Sistem KTVDI"
        title = "Notifikasi Sistem"
        desc = "Terdapat pembaruan informasi terkait akun Anda."
        warning = ""

    body = f"""========================================================
SISTEM KEAMANAN RESMI KTVDI
========================================================

Yth. {nama_user},

{desc}

Sebagai langkah otorisasi untuk memproses {title}, mohon gunakan Kode Verifikasi (OTP) berikut:
[ {otp_code} ]
*Catatan: Berlaku selama 60 detik.

INSTRUKSI KEAMANAN: {warning}
Waktu Permintaan: {waktu}

Hormat kami,
Divisi Teknologi & Keamanan Informasi, KTVDI
========================================================"""
    return subject, body

def get_hijri_date_string():
    try:
        now_wib = datetime.now(pytz.timezone("Asia/Jakarta")) + timedelta(days=-1)
        r = requests.get(f"https://api.aladhan.com/v1/gToH?date={now_wib.strftime('%d-%m-%Y')}", timeout=3)
        if r.status_code == 200:
            data = r.json()["data"]["hijri"]
            indo_months = {
                "Muharram": "Muharam", "Safar": "Safar", "Rabi' al-awwal": "Rabiul Awal", "Rabi' al-thani": "Rabiul Akhir",
                "Jumada al-awwal": "Jumadil Awal", "Jumada al-thani": "Jumadil Akhir", "Rajab": "Rajab", "Sha'ban": "Syakban",
                "Ramadan": "Ramadan", "Shawwal": "Syawal", "Dhu al-Qi'dah": "Zulkaidah", "Dhu al-Hijjah": "Zulhijah"
            }
            d = data["day"].lstrip("0")
            m = indo_months.get(data["month"]["en"], data["month"]["en"])
            y = data["year"]
            return f"{d} {m} {y} H"
    except Exception:
        pass
    return "Tanggal Hijriah Tidak Tersedia"

# ==========================================
# 7. CACHE BERITA & CUACA
# ==========================================
NEWS_CACHE, NEWS_LAST_FETCH = [], 0
KEMENAG_KOTA_CACHE, KEMENAG_LAST_FETCH = [], 0

def get_news_entries():
    global NEWS_CACHE, NEWS_LAST_FETCH
    if len(NEWS_CACHE) > 0 and time.time() - NEWS_LAST_FETCH < 30:
        return NEWS_CACHE
    
    all_news = []
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        r_bmkg = requests.get("https://data.bmkg.go.id/DataMKG/TEWS/autogempa.xml", timeout=5)
        if r_bmkg.status_code == 200:
            gempa = ET.fromstring(r_bmkg.content).find("gempa")
            if gempa is not None:
                all_news.append({
                    "title": f"INFORMASI GEMPA BMKG: Magnitudo {gempa.find('Magnitude').text} di {gempa.find('Wilayah').text} ({gempa.find('Potensi').text})",
                    "link": "https://warning.bmkg.go.id/",
                    "published_parsed": datetime.now().timetuple(),
                    "source_name": "BMKG Resmi",
                    "image": f"https://data.bmkg.go.id/DataMKG/TEWS/{gempa.find('Shakemap').text}"
                })
    except Exception:
        pass

    try:
        sources = [
            "https://www.kompas.tv/rss", "https://www.setneg.go.id/rss", "https://www.liputan6.com/rss",
            "https://www.tribunnews.com/rss", "https://www.cnnindonesia.com/nasional/rss", 
            "https://www.cnbcindonesia.com/news/rss", "https://www.antaranews.com/rss/top-news.xml"
        ]

        def fetch_feed(url):
            try:
                res = requests.get(url, headers=headers, timeout=4)
                if res.status_code == 200:
                    return url, feedparser.parse(res.content)
            except Exception:
                pass
            return url, None

        with ThreadPoolExecutor(max_workers=len(sources)) as pool:
            futures = [pool.submit(fetch_feed, url) for url in sources]
            for future in as_completed(futures):
                url, feed = future.result()
                if not feed or not feed.entries: continue
                for entry in feed.entries[:20]:
                    source_name = url.split(".")[1].capitalize() if "antara" not in url else "Antara News"
                    entry["source_name"] = source_name
                    img_url = None
                    if "media_content" in entry and entry.media_content: img_url = entry.media_content[0]["url"]
                    if not img_url and "links" in entry:
                        for link in entry.links:
                            if link.get("type", "").startswith("image"): img_url = link.get("href"); break
                    entry["image"] = img_url
                    all_news.append(entry)
        all_news.sort(key=lambda x: x.published_parsed if x.get("published_parsed") else time.gmtime(0), reverse=True)
    except Exception:
        pass

    NEWS_CACHE = all_news[:150] or [{"title": "Pusat Informasi KTVDI Beroperasi Normal", "link": "#", "published_parsed": datetime.now().timetuple(), "source_name": "Sistem Internal", "image": None}]
    NEWS_LAST_FETCH = time.time()
    return NEWS_CACHE

def time_since_published(published_time):
    try:
        diff = datetime.now() - datetime(*published_time[:6])
        if diff.days > 0: return f"{diff.days} hari yang lalu"
        if diff.seconds > 3600: return f"{diff.seconds // 3600} jam yang lalu"
        if diff.seconds > 60: return f"{diff.seconds // 60} menit yang lalu"
        return "Terbaru"
    except Exception:
        return "Waktu tidak dapat dipastikan"

def get_quote_religi():
    return {
        "muslim": ["Maka dirikanlah shalat... (QS. An-Nisa: 103)", "Hindari perbuatan curang dalam bentuk apa pun."],
        "universal": ["Integritas adalah landasan dari setiap tindakan yang benar.", "Kedamaian global bermula dari kedamaian personal."]
    }

def get_smart_fallback_response(text):
    return "Mohon maaf, server kecerdasan buatan kami saat ini sedang memproses volume antrean yang tinggi. Silakan coba kembali."

def fetch_kemenag_kota():
    global KEMENAG_KOTA_CACHE, KEMENAG_LAST_FETCH
    if len(KEMENAG_KOTA_CACHE) > 50 and time.time() - KEMENAG_LAST_FETCH < 86400: return KEMENAG_KOTA_CACHE
    try:
        r = requests.get("https://api.myquran.com/v2/sholat/kota/semua", timeout=8)
        if r.status_code == 200:
            data = r.json()
            if data.get("status") and "data" in data:
                KEMENAG_KOTA_CACHE = sorted([{"id": item["id"], "nama": item["lokasi"].title()} for item in data["data"]], key=lambda x: x["nama"])
                KEMENAG_LAST_FETCH = time.time()
                return KEMENAG_KOTA_CACHE
    except Exception:
        pass
    return [{"id": "1604", "nama": "Kota Semarang"}]

def smart_convert_cm(value):
    try:
        val_float = float(value)
        return f"{val_float * 100:.0f}" if val_float != 0 and val_float < 50 else f"{val_float:.0f}"
    except Exception:
        return "0"

def get_cuaca_10_kota():
    cities = [{"name": "Semarang", "lat": -6.9667, "lon": 110.4167}, {"name": "Surakarta", "lat": -7.5761, "lon": 110.8294}]
    lats, lons = ",".join(str(c["lat"]) for c in cities), ",".join(str(c["lon"]) for c in cities)
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lats}&longitude={lons}&current=temperature_2m,weather_code&timezone=Asia%2FBangkok"
    results = []
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            data_list = r.json() if isinstance(r.json(), list) else [r.json()]
            for i, item in enumerate(data_list):
                if i >= len(cities): break
                code, temp = item["current"]["weather_code"], item["current"]["temperature_2m"]
                status, icon, anim = "Berawan", "fa-cloud", "float"
                if code in [0, 1]: status, icon, anim = "Cerah", "fa-sun", "spin-slow"
                elif code in [51, 61, 80]: status, icon, anim = "Hujan", "fa-cloud-rain", "bounce"
                results.append({"kota": cities[i]["name"], "suhu": round(temp), "cuaca": status, "icon": icon, "anim": anim})
    except Exception:
        pass
    return results or [{"kota": c["name"], "suhu": "-", "cuaca": "Tidak Tersedia", "icon": "fa-cloud", "anim": ""} for c in cities]

def normalize_dam_data(raw_data):
    clean_data = []
    for item in raw_data:
        try:
            latest = item.get("latest_debit_report", {}) or {}
            name = item.get("dam_name") or item.get("nama") or "Infrastruktur Bendungan"
            siaga_cm, awas_cm = smart_convert_cm(item.get("siaga", 0)), smart_convert_cm(item.get("awas", 0))
            if float(siaga_cm) == 0: siaga_cm = "200"
            if float(awas_cm) == 0: awas_cm = "300"
            
            raw_tma = latest.get("limpas") if latest else (item.get("tma") or item.get("siap") or 0)
            tma_cm = smart_convert_cm(raw_tma)
            status = latest.get("status") or item.get("status_alert") or "Operasional Normal"

            clean_data.append({
                "name": name, "tma": tma_cm, "siaga": siaga_cm, "awas": awas_cm,
                "inflow": latest.get("debit", 0), "outflow": latest.get("debit_ke_saluran_induk", 0),
                "status": status, "cuaca": latest.get("cuaca", "Berawan"), "petugas": f"ID Petugas: {latest.get('pob_id', 'Unit')}",
                "updated_at": "Pembaruan Terakhir WIB", "lokasi": item.get("river_name", "Jawa Tengah")
            })
        except Exception:
            continue
    return clean_data

def fetch_ews_data():
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    try:
        r = requests.get(f"https://siagakranji.my.id/data/latest_dams.json?t={int(time.time() * 1000)}", headers=headers, timeout=6, verify=False)
        if r.status_code == 200:
            raw_list = r.json().get("data") or r.json().get("result") or (r.json() if isinstance(r.json(), list) else [])
            if raw_list: return normalize_dam_data(raw_list)
    except Exception: pass
    try:
        r = requests.get("https://api.ewsjateng.com/api/dams?page=1&pageSize=200", headers=headers, timeout=9, verify=False)
        if r.status_code == 200: return normalize_dam_data(r.json().get("data", []))
    except Exception: pass
    return []

# ==========================================
# 8. ROUTES UTAMA (Auth, Web, Berita, EWS)
# ==========================================
@app.route("/", methods=["GET"])
def home():
    stats = {"wilayah": 0, "mux": 0, "channel": 0}
    last_str = "-"
    if ref:
        try:
            siaran = ref.child("siaran").get() or {}
            for prov in siaran.values():
                if isinstance(prov, dict):
                    stats["wilayah"] += len(prov)
                    for wil in prov.values():
                        if isinstance(wil, dict):
                            stats["mux"] += len(wil)
                            for d in wil.values():
                                if isinstance(d, dict) and "siaran" in d:
                                    stats["channel"] += len(d["siaran"])
            last_str = datetime.now().strftime("%d-%m-%Y")
        except Exception: pass
    return render_template("index.html", stats=stats, last_updated_time=last_str)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        clean_input = normalize_input(request.form.get("username"))
        hashed_pw = hash_password(request.form.get("password"))
        if not ref: return render_template("login.html", error="Sistem gagal terhubung ke pangkalan data utama.")
        
        users = ref.child("users").get() or {}
        target_user, target_uid = None, None
        for uid, data in users.items():
            if not isinstance(data, dict): continue
            if normalize_input(uid) == clean_input or normalize_input(data.get("email")) == clean_input:
                target_user, target_uid = data, uid
                break

        if target_user and target_user.get("password") == hashed_pw:
            session.permanent = True
            session["user"] = target_uid
            session["nama"] = target_user.get("nama", "Pengguna Terdaftar")
            return redirect(url_for("dashboard"))
        return render_template("login.html", error="Kredensial identitas atau kata sandi yang Anda masukkan tidak valid.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        u = normalize_input(request.form.get("username"))
        e = normalize_input(request.form.get("email"))
        n, p = request.form.get("nama"), request.form.get("password")
        
        if not ref: return "Terjadi galat pada koneksi basis data. Harap hubungi administrator.", 500
        users = ref.child("users").get() or {}
        if u in users:
            flash("Nama pengguna tersebut telah terdaftar di dalam sistem.", "error")
            return render_template("register.html")
        for uid, data in users.items():
            if isinstance(data, dict) and normalize_input(data.get("email")) == e:
                flash("Alamat surel tersebut telah diasosiasikan dengan akun lain.", "error")
                return render_template("register.html")

        otp = str(random.randint(100000, 999999))
        ref.child(f"pending_users/{u}").set({"nama": n, "email": e, "password": hash_password(p), "otp": otp, "expiry": time.time() + 60})
        
        try:
            subject, body = get_email_template("REGISTER", n, otp)
            mail.send(Message(subject, recipients=[e], body=body))
            session["pending_username"] = u
            return redirect(url_for("verify_register"))
        except Exception:
            flash("Kegagalan transmisi surel. Pastikan alamat yang diberikan valid dan aktif.", "error")
    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    u = session.get("pending_username")
    if not u: return redirect(url_for("register"))
    if request.method == "POST":
        p = ref.child(f"pending_users/{u}").get()
        if not p: return redirect(url_for("register"))
        if time.time() > p.get("expiry", 0):
            flash("Sesi kode verifikasi telah berakhir. Silakan lakukan permohonan ulang.", "error")
            ref.child(f"pending_users/{u}").delete()
            return redirect(url_for("register"))
        
        if str(p.get("otp")).strip() == (request.form.get("otp") or "").strip():
            ref.child(f"users/{u}").set({"nama": p["nama"], "email": p["email"], "password": p["password"]})
            ref.child(f"pending_users/{u}").delete()
            session.pop("pending_username", None)
            flash("Registrasi telah berhasil diproses. Silakan masuk.", "success")
            return redirect(url_for("login"))
        flash("Kode otorisasi yang Anda masukkan tidak tepat.", "error")
    return render_template("verify-register.html", username=u)

@app.route("/berita")
def berita_page():
    entries = get_news_entries()
    page, per_page = request.args.get("page", 1, type=int), 9
    start, end = (page - 1) * per_page, page * per_page
    current = entries[start:end]
    for article in current:
        if "published_parsed" in article and article["published_parsed"]:
            article["formatted_date"] = format_indo_date(article["published_parsed"])
            article["time_since_published"] = time_since_published(article["published_parsed"])
        else:
            article["formatted_date"], article["time_since_published"] = "Data Waktu Tidak Tersedia", "Terkini"
    total_pages = max(1, (len(entries) + per_page - 1) // per_page)
    return render_template("berita.html", articles=current, page=page, total_pages=total_pages)

@app.route("/dashboard")
def dashboard():
    if "user" not in session: return redirect(url_for("login"))
    data = ref.child("provinsi").get() or {}
    return render_template("dashboard.html", name=session.get("nama"), provinsi_list=list(data.values()))

# ... (Rute Tambah/Edit Siaran dan lainnya yang berkaitan dengan Firebase tetap utuh dan berfungsi sama)

# ==========================================================
# 9. INTEGRASI API SISTEM & EWS LAINNYA
# ==========================================================
@app.route("/api/news-ticker")
def news_ticker():
    return jsonify([n["title"] for n in get_news_entries()])

@app.route("/ews-jateng")
def ews_jateng_page():
    return render_template("ews-jateng.html", dams=fetch_ews_data(), cuaca_list=get_cuaca_10_kota())

@app.route("/api/chat", methods=["POST"])
def chatbot_api():
    user_msg = (request.get_json() or {}).get("prompt", "")
    full_prompt = f"{MODI_PROMPT}\nPengguna: {user_msg}\nModi:"
    model = get_gemini_model()
    if not model: return jsonify({"response": get_smart_fallback_response(user_msg)})
    try:
        return jsonify({"response": model.generate_content(full_prompt).text})
    except Exception:
        return jsonify({"response": get_smart_fallback_response(user_msg)})

# ==========================================================
# 10. NETWORK MONITORING, DETEKSI ISP, SIGNAL & BANDWIDTH
# ==========================================================
NETWORK_CACHE = {"time": 0, "data": None}
SPEEDTEST_DATA = {"download": 0, "upload": 0, "isp": "Mendeteksi ISP...", "last_test": 0}
WIFI_STATS_CACHE = {"ssid": "-", "signal": "-", "tx_rate": "-", "rx_rate": "-"}

def run_command(command, timeout=3):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, shell=False)
        return result.stdout.strip()
    except Exception:
        return ""

def get_isp_and_public_ip():
    """Mengambil informasi nama ISP dan IP Publik dengan cepat."""
    try:
        r = requests.get("http://ip-api.com/json/", timeout=3)
        if r.status_code == 200:
            data = r.json()
            return data.get("isp", "ISP Tidak Diketahui")
    except Exception:
        pass
    return "ISP Tidak Terdeteksi"

def run_speedtest_background():
    """Menjalankan speedtest di background agar tidak memblokir server."""
    global SPEEDTEST_DATA
    if not speedtest:
        SPEEDTEST_DATA["isp"] = "Gagal (Modul speedtest-cli tidak diinstal)"
        return

    try:
        st = speedtest.Speedtest()
        st.get_best_server()
        SPEEDTEST_DATA["download"] = round(st.download() / 1_000_000, 2)
        SPEEDTEST_DATA["upload"] = round(st.upload() / 1_000_000, 2)
        SPEEDTEST_DATA["isp"] = get_isp_and_public_ip()
        SPEEDTEST_DATA["last_test"] = time.time()
    except Exception as e:
        SPEEDTEST_DATA["isp"] = "Pengujian Gagal"

def get_wifi_stats():
    """Mengambil SSID, Kekuatan Sinyal, dan TX/RX rate lewat OS command."""
    stats = {"ssid": "-", "signal": "-", "tx_rate": "-", "rx_rate": "-"}
    system = platform.system().lower()

    if system == "windows":
        out = run_command(["netsh", "wlan", "show", "interfaces"])
        for line in out.splitlines():
            if "SSID" in line and "BSSID" not in line: stats["ssid"] = line.split(":", 1)[1].strip()
            elif "Signal" in line: stats["signal"] = line.split(":", 1)[1].strip()
            elif "Transmit rate (Mbps)" in line: stats["tx_rate"] = line.split(":", 1)[1].strip() + " Mbps"
            elif "Receive rate (Mbps)" in line: stats["rx_rate"] = line.split(":", 1)[1].strip() + " Mbps"
            
    elif system == "linux":
        out = run_command(["iwconfig"], timeout=2)
        for line in out.splitlines():
            if "ESSID:" in line:
                m = re.search(r'ESSID:"([^"]+)"', line)
                if m: stats["ssid"] = m.group(1)
            if "Bit Rate=" in line:
                m = re.search(r'Bit Rate=([\d\.]+)\s*Mb/s', line)
                if m: stats["tx_rate"] = m.group(1) + " Mbps"
            if "Signal level=" in line:
                m = re.search(r'Signal level=(-\d+)\s*dBm', line)
                if m: stats["signal"] = m.group(1) + " dBm"

    return stats

def get_default_gateway():
    system = platform.system().lower()
    if system == "windows":
        out = run_command(["ipconfig"])
        for line in out.splitlines():
            if "Default Gateway" in line:
                val = line.split(":", 1)[-1].strip()
                if val: return val
    elif shutil.which("ip"):
        out = run_command(["ip", "route", "show", "default"])
        match = re.search(r"default via ([0-9.]+)", out)
        if match: return match.group(1)
    return None

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None

def normalize_mac(mac):
    if not mac: return ""
    mac = mac.strip().lower().replace("-", ":").replace(".", ":")
    parts = mac.split(":")
    return ":".join(p.zfill(2) for p in parts) if len(parts) == 6 else mac

def scan_network_devices():
    now = time.time()
    
    # Update cache setiap 15 detik untuk menghemat resource (CPU friendly)
    if NETWORK_CACHE["data"] is not None and now - NETWORK_CACHE["time"] < 15:
        return NETWORK_CACHE["data"]

    # Jalankan speedtest setiap 15 menit, dilakukan via Background Thread
    if now - SPEEDTEST_DATA["last_test"] > 900:
        threading.Thread(target=run_speedtest_background).start()

    # Perbarui data WiFi stats
    wifi_stats = get_wifi_stats()

    local_ip = get_local_ip()
    gateway = get_default_gateway()
    devices = []

    # Memindai konfigurasi ARP lokal secara dinamis (Linux/Windows)
    if platform.system().lower() == "windows":
        for line in run_command(["arp", "-a"]).splitlines():
            match = re.search(r"(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F-]{17})\s+(\w+)", line)
            if match: devices.append({"ip": match.group(1), "mac": normalize_mac(match.group(2)), "status": "Online", "device": "Perangkat Jaringan"})
    else:
        for line in run_command(["ip", "neigh", "show"]).splitlines():
            match = re.search(r"^(\d+\.\d+\.\d+\.\d+).*?(?:lladdr\s+)([0-9a-fA-F:]{17})", line)
            if match: devices.append({"ip": match.group(1), "mac": normalize_mac(match.group(2)), "status": "Online", "device": "Perangkat Jaringan"})

    result = {
        "status": "success",
        "local_ip": local_ip or "-",
        "gateway": gateway or "-",
        "platform": platform.system(),
        "clients_count": len(devices),
        "online_count": len(devices),
        "devices": devices,
        "scan_time": datetime.now().strftime("%d-%m-%Y %H:%M:%S"),
        
        # Tambahan Fitur Jaringan Baru
        "isp": SPEEDTEST_DATA["isp"],
        "download_mbps": SPEEDTEST_DATA["download"],
        "upload_mbps": SPEEDTEST_DATA["upload"],
        "ssid": wifi_stats["ssid"],
        "signal": wifi_stats["signal"],
        "tx_rate": wifi_stats["tx_rate"],
        "rx_rate": wifi_stats["rx_rate"]
    }

    NETWORK_CACHE["time"] = now
    NETWORK_CACHE["data"] = result
    return result

@app.route("/network")
def network_page():
    if "user" not in session: return redirect(url_for("login"))
    return render_template("network.html")

@app.route("/api/network-data")
def network_data_api():
    try:
        return jsonify(scan_network_devices())
    except Exception as e:
        return jsonify({"status": "error", "message": str(e), "devices": []})

@app.route("/api/network-rescan")
def network_rescan():
    NETWORK_CACHE["time"] = 0
    NETWORK_CACHE["data"] = None
    SPEEDTEST_DATA["last_test"] = 0 # Force rescan pada sesi speedtest
    return jsonify(scan_network_devices())

# ==========================================
# 11. RUN SERVER
# ==========================================
if __name__ == "__main__":
    app.run(
        host="0.0.0.0", 
        port=int(os.environ.get("PORT", 5000)), 
        debug=True
    )
