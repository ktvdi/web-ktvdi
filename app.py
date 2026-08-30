import os
import hashlib
import random
import re
import time
import socket
import platform
import ipaddress
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
    session, flash, jsonify
)
from flask_cors import CORS
from dotenv import load_dotenv
from flask_mail import Mail, Message

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

# ==========================================
# 7. CACHE BERITA & CUACA
# ==========================================
NEWS_CACHE, NEWS_LAST_FETCH = [], 0

def get_news_entries():
    global NEWS_CACHE, NEWS_LAST_FETCH
    if len(NEWS_CACHE) > 0 and time.time() - NEWS_LAST_FETCH < 120:
        return NEWS_CACHE
    
    all_news = []
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        r_bmkg = requests.get("https://data.bmkg.go.id/DataMKG/TEWS/autogempa.xml", timeout=3)
        if r_bmkg.status_code == 200:
            gempa = ET.fromstring(r_bmkg.content).find("gempa")
            if gempa is not None:
                all_news.append({
                    "title": f"INFORMASI GEMPA BMKG: Magnitudo {gempa.find('Magnitude').text} di {gempa.find('Wilayah').text}",
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
            "https://www.tribunnews.com/rss", "https://www.cnnindonesia.com/nasional/rss"
        ]

        def fetch_feed(url):
            try:
                # Batasi timeout jadi sangat singkat agar Vercel tidak timeout
                res = requests.get(url, headers=headers, timeout=2.5) 
                if res.status_code == 200:
                    return url, feedparser.parse(res.content)
            except Exception:
                pass
            return url, None

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(fetch_feed, url) for url in sources]
            for future in as_completed(futures):
                url, feed = future.result()
                if not feed or not feed.entries: continue
                for entry in feed.entries[:10]:
                    source_name = url.split(".")[1].capitalize()
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

    NEWS_CACHE = all_news[:100] or [{"title": "Pusat Informasi KTVDI Beroperasi Normal", "link": "#", "published_parsed": datetime.now().timetuple(), "source_name": "Sistem Internal", "image": None}]
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

def get_cuaca_10_kota():
    cities = [{"name": "Semarang", "lat": -6.9667, "lon": 110.4167}, {"name": "Surakarta", "lat": -7.5761, "lon": 110.8294}]
    lats, lons = ",".join(str(c["lat"]) for c in cities), ",".join(str(c["lon"]) for c in cities)
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lats}&longitude={lons}&current=temperature_2m,weather_code&timezone=Asia%2FBangkok"
    results = []
    try:
        r = requests.get(url, timeout=3)
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
    data = ref.child("provinsi").get() if ref else {}
    return render_template("dashboard.html", name=session.get("nama"), provinsi_list=list((data or {}).values()))

# ==========================================================
# 9. INTEGRASI API SISTEM & EWS LAINNYA
# ==========================================================
@app.route("/api/news-ticker")
def news_ticker():
    return jsonify([n["title"] for n in get_news_entries()])

@app.route("/ews-jateng")
def ews_jateng_page():
    return render_template("ews-jateng.html", dams=[], cuaca_list=get_cuaca_10_kota())

# ==========================================================
# 10. NETWORK MONITORING (VERSI RINGAN - CLIENT CENTRIC)
# ==========================================================
# Menghindari pemrosesan OS / Speedtest berat di sisi Serverless (Vercel)
# Semua beban ditangani secara efisien oleh browser (klien) melalui network.html

@app.route("/network")
def network_page():
    if "user" not in session: return redirect(url_for("login"))
    return render_template("network.html")

@app.route("/api/network-client-merge", methods=["POST"])
def network_client_merge():
    """
    Endpoint ini menerima data yang dikirim oleh Javascript browser.
    Server hanya akan meneruskan (echo) data tersebut tanpa melakukan
    pemrosesan berat (Anti-Vercel Crash / Error 500).
    """
    try:
        client_data = request.get_json() or {}
        # Membalas ke Frontend (Mengabungkan hasil Client-side)
        return jsonify({
            "status": "success",
            "message": "Data Klien Diterima",
            "client": client_data
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/api/network-data")
def network_data_api():
    """
    Vercel/Serverless TIDAK BISA menjalankan arp, netsh, iwconfig, atau speedtest.
    API ini dipangkas ekstrem. Mengembalikan identitas klien sederhana.
    Sisa logika grafik, speedtest, dll, sudah ditangani Frontend (JS).
    """
    try:
        # Dapatkan IP Klien dari Headers Proxy Vercel
        client_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
        if client_ip:
            client_ip = client_ip.split(",")[0].strip()

        # Dummy data balasan instan (< 0.1 detik eksekusi)
        result = {
            "status": "success",
            "local_ip": "Lingkungan Cloud Serverless",
            "gateway": "-",
            "platform": platform.system(),
            "clients_count": 1,
            "online_count": 1,
            "devices": [
                {
                    "ip": client_ip or "IP Disembunyikan", 
                    "mac": "Di-masking (Privasi)", 
                    "status": "Online", 
                    "device": "Perangkat Klien Web", 
                    "role": "client",
                    "latency_ms": random.randint(15, 60)
                }
            ],
            "scan_time": datetime.now().strftime("%d-%m-%Y %H:%M:%S"),
            "isp": "Deteksi via Browser Aktif",
            "download_mbps": None,
            "upload_mbps": None,
            "ssid": "Mode Serverless Aktif",
            "signal": "-",
            "tx_rate": "-",
            "rx_rate": "-"
        }
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": "Gagal sinkronisasi data cloud", "devices": []})

@app.route("/api/network-rescan")
def network_rescan():
    # Karena backend tidak menyimpan state scan berat lagi,
    # rescan cukup memanggil ulang API network-data.
    return network_data_api()

# ==========================================
# 11. RUN SERVER
# ==========================================
if __name__ == "__main__":
    app.run(
        host="0.0.0.0", 
        port=int(os.environ.get("PORT", 5000)), 
        debug=True
    )
