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
import socket
import subprocess
import platform
import ipaddress
import shutil

from concurrent.futures import ThreadPoolExecutor, as_completed
from firebase_admin import credentials, db
from flask import (
    Flask,
    request,
    render_template,
    redirect,
    url_for,
    session,
    flash,
    jsonify,
    send_from_directory
)
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

app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY",
    "KTVDI_OFFICIAL_SECRET_KEY_FINAL_PRO_2026_SUPER_SECURE"
)

app.config["SESSION_PERMANENT"] = True
app.config["PERMANENT_SESSION_LIFETIME"] = 86400


# ==========================================
# 2. SISTEM AUTO-MAINTENANCE
# ==========================================

MAINTENANCE_END_DATE = datetime(2026, 2, 3, 7, 0, 0)


@app.before_request
def maintenance_interceptor():
    if request.endpoint == "static":
        return None

    now_wib = datetime.utcnow() + timedelta(hours=7)

    if now_wib < MAINTENANCE_END_DATE:
        return render_template("maintenance.html"), 503

    return None


# ==========================================
# 2.5. SISTEM TRACKER PENGUNJUNG & LOKASI
# ==========================================

TRACKER_DATA = {
    "date": datetime.now(
        pytz.timezone("Asia/Jakarta")
    ).date(),
    "daily_ips": set(),
    "online_ips": {},
    "ip_locations": {}
}


def fetch_and_store_location_sync(ip):
    """
    Mengambil perkiraan lokasi IP publik.
    IP private tidak dikirim ke layanan geolokasi.
    """

    try:
        ip_obj = ipaddress.ip_address(ip)

        if ip_obj.is_private or ip_obj.is_loopback:
            TRACKER_DATA["ip_locations"][ip] = "Jaringan Lokal"
            return

        r = requests.get(
            f"http://ip-api.com/json/{ip}?fields=city,country,status",
            timeout=1.5
        )

        if r.status_code == 200:
            res = r.json()

            if res.get("status") == "success":
                TRACKER_DATA["ip_locations"][ip] = (
                    f"{res.get('city', 'Unknown City')}, "
                    f"{res.get('country', 'Unknown Country')}"
                )
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

        user_ip = request.headers.get(
            "X-Forwarded-For",
            request.remote_addr
        )

        if user_ip:
            user_ip = user_ip.split(",")[0].strip()

            TRACKER_DATA["daily_ips"].add(user_ip)
            TRACKER_DATA["online_ips"][user_ip] = time.time()

            try:
                private_ip = ipaddress.ip_address(user_ip).is_private
            except Exception:
                private_ip = False

            if (
                user_ip not in TRACKER_DATA["ip_locations"]
                and not private_ip
            ):
                TRACKER_DATA["ip_locations"][user_ip] = (
                    "Mendeteksi Lokasi..."
                )
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
            "private_key": os.environ.get(
                "FIREBASE_PRIVATE_KEY"
            ).replace("\\n", "\n"),
            "client_email": os.environ.get("FIREBASE_CLIENT_EMAIL"),
            "client_id": os.environ.get("FIREBASE_CLIENT_ID"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url":
                "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url":
                os.environ.get("FIREBASE_CLIENT_X509_CERT_URL"),
            "universe_domain": "googleapis.com"
        })

    else:

        if os.path.exists("credentials.json"):
            cred = credentials.Certificate("credentials.json")
        else:
            cred = None

    if cred and not firebase_admin._apps:
        firebase_admin.initialize_app(
            cred,
            {
                "databaseURL": os.environ.get("DATABASE_URL")
            }
        )

    if firebase_admin._apps:

        ref = db.reference("/")

        print(
            "INFO: Koneksi Basis Data KTVDI berhasil ditetapkan."
        )

    else:

        ref = None

        print(
            "WARNING: Kredensial Firebase tidak ditemukan. "
            "Sistem berjalan tanpa basis data."
        )

except Exception as e:

    ref = None

    print(
        f"ERROR: Kegagalan koneksi basis data. "
        f"Mode luring diaktifkan. Rincian: {e}"
    )


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
            {
                "category": "HARM_CATEGORY_HARASSMENT",
                "threshold": "BLOCK_NONE"
            },
            {
                "category": "HARM_CATEGORY_HATE_SPEECH",
                "threshold": "BLOCK_NONE"
            },
            {
                "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "threshold": "BLOCK_NONE"
            },
            {
                "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                "threshold": "BLOCK_NONE"
            }
        ]

        return genai.GenerativeModel(
            "gemini-1.5-flash",
            safety_settings=safety_settings
        )

    except Exception as e:

        print(
            f"ERROR: Konfigurasi model Gemini mengalami kegagalan. "
            f"Rincian: {e}"
        )

        return None


MODI_PROMPT = """
Anda adalah MODI, Asisten Virtual Resmi dari Komunitas TV Digital Indonesia (KTVDI).

Karakteristik Komunikasi:
Sangat profesional, informatif, objektif, dan menggunakan Bahasa Indonesia
baku yang tepat sesuai Ejaan Yang Disempurnakan (EYD).

Tugas Utama:
1. Memberikan respons yang akurat terkait teknologi Televisi Digital,
   Set Top Box (STB), topologi antena, dan pemecahan masalah siaran.
2. Menyampaikan data cuaca dan peringatan dini bencana secara faktual.
3. Menghindari penggunaan bahasa gaul, sapaan informal, atau opini pribadi.

INSTRUKSI KRITIKAL:
Apabila data Early Warning System (EWS) mengindikasikan bendungan
berstatus 'Siaga' atau 'Awas', Anda wajib mengeluarkan peringatan resmi
yang instruktif dan berorientasi pada mitigasi risiko.
"""


# ==========================================
# 6. FUNGSI BANTUAN
# ==========================================

def hash_password(pw):
    return hashlib.sha256(
        (pw or "").encode()
    ).hexdigest()


def normalize_input(text):
    return text.strip().lower() if text else ""


def format_indo_date(time_struct):

    if not time_struct:
        return datetime.now().strftime(
            "%A, %d %B %Y - %H:%M WIB"
        )

    try:

        dt = datetime.fromtimestamp(
            time.mktime(time_struct)
        )

        return dt.strftime(
            "%A, %d %B %Y - %H:%M WIB"
        )

    except Exception:
        return "Informasi Waktu Tidak Tersedia"


def get_email_template(action_type, nama_user, otp_code):

    waktu = datetime.now().strftime(
        "%d %B %Y, Pukul %H:%M WIB"
    )

    if action_type == "REGISTER":

        subject = (
            f"🔐 Verifikasi Keamanan: Pendaftaran Akun KTVDI "
            f"[{otp_code}]"
        )

        title = "Verifikasi Pendaftaran Akun Baru"

        desc = (
            "Sistem kami mendeteksi permintaan pendaftaran akun baru "
            "di portal Komunitas TV Digital Indonesia (KTVDI) "
            "yang terafiliasi dengan alamat surel ini."
        )

        warning = (
            "Apabila Anda tidak merasa menginisiasi pendaftaran ini, "
            "harap abaikan pesan ini. Kode OTP ini bersifat sangat RAHASIA."
        )

    elif action_type == "RESET":

        subject = (
            f"⚠️ Peringatan Keamanan: Permintaan Atur Ulang "
            f"Kata Sandi [{otp_code}]"
        )

        title = "Permintaan Atur Ulang Kata Sandi"

        desc = (
            "Sistem kami menerima instruksi untuk mengatur ulang "
            "kata sandi (Reset Password) pada akun KTVDI Anda."
        )

        warning = (
            "JANGAN MEMBERIKAN kode ini kepada pihak mana pun, "
            "termasuk staf atau administrator KTVDI. Jika permintaan "
            "ini bukan dari Anda, segera lakukan pengamanan akun."
        )

    else:

        subject = "Pemberitahuan Sistem KTVDI"
        title = "Notifikasi Sistem"
        desc = (
            "Terdapat pembaruan informasi terkait akun Anda."
        )
        warning = ""

    body = f"""
========================================================
SISTEM KEAMANAN RESMI KTVDI
========================================================

Yth. {nama_user},

{desc}

Sebagai langkah otorisasi untuk memproses {title}, mohon gunakan
Kode Verifikasi (OTP) berikut:

[ {otp_code} ]

*Catatan: Kode verifikasi ini hanya berlaku selama 60 detik
terhitung sejak surel ini diterbitkan.

INSTRUKSI KEAMANAN:
{warning}

Rincian Transaksi Sistem:
- Waktu Permintaan : {waktu}
- Status Transaksi : Menunggu Otorisasi Pengguna

Hormat kami,
Divisi Teknologi & Keamanan Informasi,
Komunitas TV Digital Indonesia (KTVDI)
========================================================
"""

    return subject, body


# ==========================================
# 6.1. TANGGAL HIJRIAH
# ==========================================

def get_hijri_date_string():

    HIJRI_OFFSET = -1

    try:

        tz_jakarta = pytz.timezone("Asia/Jakarta")

        now_wib = (
            datetime.now(tz_jakarta)
            + timedelta(days=HIJRI_OFFSET)
        )

        url = (
            "https://api.aladhan.com/v1/gToH"
            f"?date={now_wib.strftime('%d-%m-%Y')}"
        )

        r = requests.get(url, timeout=3)

        if r.status_code == 200:

            data = r.json()["data"]["hijri"]

            indo_months = {
                "Muharram": "Muharam",
                "Safar": "Safar",
                "Rabi' al-awwal": "Rabiul Awal",
                "Rabi' al-thani": "Rabiul Akhir",
                "Jumada al-awwal": "Jumadil Awal",
                "Jumada al-thani": "Jumadil Akhir",
                "Rajab": "Rajab",
                "Sha'ban": "Syakban",
                "Ramadan": "Ramadan",
                "Shawwal": "Syawal",
                "Dhu al-Qi'dah": "Zulkaidah",
                "Dhu al-Hijjah": "Zulhijah"
            }

            d = data["day"].lstrip("0")
            m = indo_months.get(
                data["month"]["en"],
                data["month"]["en"]
            )
            y = data["year"]

            return f"{d} {m} {y} H"

    except Exception:
        pass

    return "Tanggal Hijriah Tidak Tersedia"


# ==========================================
# 6.2. CACHE BERITA
# ==========================================

NEWS_CACHE = []
NEWS_LAST_FETCH = 0


def get_news_entries():

    global NEWS_CACHE, NEWS_LAST_FETCH

    if (
        len(NEWS_CACHE) > 0
        and time.time() - NEWS_LAST_FETCH < 30
    ):
        return NEWS_CACHE

    all_news = []

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    # --------------------------------------
    # BMKG GEMPA TERKINI
    # --------------------------------------

    try:

        r_bmkg = requests.get(
            "https://data.bmkg.go.id/DataMKG/TEWS/autogempa.xml",
            timeout=5
        )

        if r_bmkg.status_code == 200:

            root = ET.fromstring(
                r_bmkg.content
            )

            gempa = root.find("gempa")

            if gempa is not None:

                wilayah = gempa.find("Wilayah").text
                magnitude = gempa.find("Magnitude").text
                potensi = gempa.find("Potensi").text
                shakemap = gempa.find("Shakemap").text

                all_news.append({
                    "title": (
                        f"INFORMASI GEMPA BMKG: "
                        f"Magnitudo {magnitude} di {wilayah} "
                        f"({potensi})"
                    ),
                    "link": "https://warning.bmkg.go.id/",
                    "published_parsed": datetime.now().timetuple(),
                    "source_name": "BMKG Resmi",
                    "image": (
                        "https://data.bmkg.go.id/"
                        f"DataMKG/TEWS/{shakemap}"
                    )
                })

    except Exception:
        pass

    # --------------------------------------
    # RSS NEWS
    # --------------------------------------

    try:

        sources = [
            "https://www.kompas.tv/rss",
            "https://www.setneg.go.id/rss",
            "https://www.liputan6.com/rss",
            "https://www.tribunnews.com/rss",
            "https://www.cnnindonesia.com/nasional/rss",
            "https://www.cnbcindonesia.com/news/rss",
            "https://www.antaranews.com/rss/top-news.xml",
            "https://rss.sindonews.com/news"
        ]

        def fetch_feed(url):

            try:

                res = requests.get(
                    url,
                    headers=headers,
                    timeout=4
                )

                if res.status_code == 200:
                    return url, feedparser.parse(res.content)

            except Exception:
                return url, None

            return url, None

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(sources)
        ) as pool:

            futures = [
                pool.submit(fetch_feed, url)
                for url in sources
            ]

            for future in concurrent.futures.as_completed(
                futures
            ):

                url, feed = future.result()

                if not feed or not feed.entries:
                    continue

                for entry in feed.entries[:20]:

                    if "kompas.tv" in url:
                        source_name = "Kompas TV"

                    elif "setneg" in url:
                        source_name = "Sekretariat Negara"

                    elif "liputan6" in url:
                        source_name = "Liputan 6"

                    elif "tribunnews" in url:
                        source_name = "Tribunnews"

                    elif "cnnindonesia" in url:
                        source_name = "CNN Indonesia"

                    elif "cnbcindonesia" in url:
                        source_name = "CNBC Indonesia"

                    elif "antara" in url:
                        source_name = "Antara News"

                    elif "sindonews" in url:
                        source_name = "Sindonews"

                    else:
                        source_name = (
                            url.split(".")[1].capitalize()
                        )

                    entry["source_name"] = source_name

                    img_url = None

                    if (
                        "media_content" in entry
                        and entry.media_content
                    ):

                        img_url = (
                            entry.media_content[0]["url"]
                        )

                    if not img_url and "links" in entry:

                        for link in entry.links:

                            if link.get(
                                "type", ""
                            ).startswith("image"):

                                img_url = link.get("href")
                                break

                    if (
                        not img_url
                        and "description" in entry
                    ):

                        match = re.search(
                            r'src="([^"]+)"',
                            entry.description
                        )

                        if match:
                            img_url = match.group(1)

                    if not img_url and "enclosures" in entry:

                        for enc in entry.enclosures:

                            if enc.get(
                                "type", ""
                            ).startswith("image"):

                                img_url = enc.get("href")
                                break

                    entry["image"] = img_url

                    all_news.append(entry)

        all_news.sort(
            key=lambda x:
                x.published_parsed
                if x.get("published_parsed")
                else time.gmtime(0),
            reverse=True
        )

    except Exception:
        pass

    if not all_news:

        if NEWS_CACHE:
            return NEWS_CACHE

        t = datetime.now().timetuple()

        return [{
            "title":
                "Pusat Informasi KTVDI Beroperasi Normal",
            "link": "#",
            "published_parsed": t,
            "source_name": "Sistem Internal",
            "image": None
        }]

    NEWS_CACHE = all_news[:150]
    NEWS_LAST_FETCH = time.time()

    return NEWS_CACHE


def time_since_published(published_time):

    try:

        now = datetime.now()

        pt = datetime(
            *published_time[:6]
        )

        diff = now - pt

        if diff.days > 0:
            return f"{diff.days} hari yang lalu"

        if diff.seconds > 3600:
            return f"{diff.seconds // 3600} jam yang lalu"

        if diff.seconds > 60:
            return f"{diff.seconds // 60} menit yang lalu"

        return "Terbaru"

    except Exception:
        return "Waktu tidak dapat dipastikan"


def get_quote_religi():

    return {
        "muslim": [
            "Maka dirikanlah shalat... (QS. An-Nisa: 103)",
            "Hindari perbuatan curang dalam bentuk apa pun.",
            "Manusia terbaik adalah yang memberikan manfaat bagi sesamanya."
        ],
        "universal": [
            "Integritas adalah landasan dari setiap tindakan yang benar.",
            "Kedamaian global bermula dari kedamaian personal.",
            "Kejujuran adalah nilai tukar universal yang diakui secara global."
        ]
    }


def get_smart_fallback_response(text):

    return (
        "Mohon maaf, server kecerdasan buatan kami saat ini "
        "sedang memproses volume antrean yang tinggi. "
        "Kami memohon kesediaan Anda untuk mencoba kembali "
        "dalam beberapa saat."
    )


# ==========================================
# 6.3. DATA KOTA SHOLAT
# ==========================================

KEMENAG_KOTA_CACHE = []
KEMENAG_LAST_FETCH = 0


def fetch_kemenag_kota():

    global KEMENAG_KOTA_CACHE
    global KEMENAG_LAST_FETCH

    if (
        len(KEMENAG_KOTA_CACHE) > 50
        and time.time() - KEMENAG_LAST_FETCH < 86400
    ):
        return KEMENAG_KOTA_CACHE

    try:

        r = requests.get(
            "https://api.myquran.com/v2/sholat/kota/semua",
            timeout=8
        )

        if r.status_code == 200:

            data = r.json()

            if data.get("status") and "data" in data:

                all_cities = [
                    {
                        "id": item["id"],
                        "nama": item["lokasi"].title()
                    }
                    for item in data["data"]
                ]

                KEMENAG_KOTA_CACHE = sorted(
                    all_cities,
                    key=lambda x: x["nama"]
                )

                KEMENAG_LAST_FETCH = time.time()

                return KEMENAG_KOTA_CACHE

    except Exception:
        pass

    return [
        {
            "id": "1301",
            "nama": "Kota Jakarta"
        },
        {
            "id": "1604",
            "nama": "Kota Semarang"
        },
        {
            "id": "1638",
            "nama": "Kota Surabaya"
        },
        {
            "id": "0418",
            "nama": "Kota Medan"
        },
        {
            "id": "1205",
            "nama": "Kota Bandung"
        }
    ]


# ==========================================
# 7. LOGIKA EWS & CUACA
# ==========================================

def smart_convert_cm(value):

    try:

        val_float = float(value)

        if val_float != 0 and val_float < 50:
            return f"{val_float * 100:.0f}"

        return f"{val_float:.0f}"

    except Exception:
        return "0"


def get_cuaca_10_kota():

    cities = [
        {
            "name": "Semarang",
            "lat": -6.9667,
            "lon": 110.4167
        },
        {
            "name": "Surakarta",
            "lat": -7.5761,
            "lon": 110.8294
        },
        {
            "name": "Tegal",
            "lat": -6.8694,
            "lon": 109.1403
        },
        {
            "name": "Pekalongan",
            "lat": -6.8886,
            "lon": 109.6753
        },
        {
            "name": "Salatiga",
            "lat": -7.3305,
            "lon": 110.5084
        },
        {
            "name": "Magelang",
            "lat": -7.4706,
            "lon": 110.2178
        },
        {
            "name": "Purwokerto",
            "lat": -7.4245,
            "lon": 109.2302
        },
        {
            "name": "Cilacap",
            "lat": -7.7279,
            "lon": 109.0077
        },
        {
            "name": "Kudus",
            "lat": -6.8048,
            "lon": 110.8405
        },
        {
            "name": "Pati",
            "lat": -6.7550,
            "lon": 111.0380
        }
    ]

    lats = ",".join(
        str(c["lat"]) for c in cities
    )

    lons = ",".join(
        str(c["lon"]) for c in cities
    )

    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lats}"
        f"&longitude={lons}"
        "&current=temperature_2m,weather_code"
        "&timezone=Asia%2FBangkok"
    )

    results = []

    try:

        r = requests.get(
            url,
            timeout=5
        )

        if r.status_code == 200:

            data = r.json()

            data_list = (
                data
                if isinstance(data, list)
                else [data]
                if "current" in data
                else []
            )

            for i, item in enumerate(data_list):

                if i >= len(cities):
                    break

                code = item["current"]["weather_code"]
                temp = item["current"]["temperature_2m"]

                status = "Berawan"
                icon = "fa-cloud"
                anim = "float"

                if code in [0, 1]:

                    status = "Cerah"
                    icon = "fa-sun"
                    anim = "spin-slow"

                elif code in [2, 3]:

                    status = "Berawan"
                    icon = "fa-cloud-sun"
                    anim = "float"

                elif code in [45, 48]:

                    status = "Kabut"
                    icon = "fa-smog"
                    anim = "pulse"

                elif code in [
                    51, 53, 55,
                    61, 63, 65,
                    80, 81, 82
                ]:

                    status = "Hujan"
                    icon = "fa-cloud-rain"
                    anim = "bounce"

                elif code >= 95:

                    status = "Badai"
                    icon = "fa-bolt"
                    anim = "flash"

                results.append({
                    "kota": cities[i]["name"],
                    "suhu": round(temp),
                    "cuaca": status,
                    "icon": icon,
                    "anim": anim
                })

    except Exception:
        pass

    if not results:

        for c in cities:

            results.append({
                "kota": c["name"],
                "suhu": "-",
                "cuaca": "Tidak Tersedia",
                "icon": "fa-cloud",
                "anim": ""
            })

    return results


def normalize_dam_data(raw_data):

    clean_data = []

    for item in raw_data:

        try:

            latest = item.get(
                "latest_debit_report",
                {}
            )

            if not isinstance(latest, dict):
                latest = {}

            name = (
                item.get("dam_name")
                or item.get("nama")
                or item.get("name")
                or "Infrastruktur Bendungan"
            )

            siaga_val = item.get("siaga", 0)
            awas_val = item.get("awas", 0)

            siaga_cm = smart_convert_cm(siaga_val)
            awas_cm = smart_convert_cm(awas_val)

            if float(siaga_cm) == 0:
                siaga_cm = "200"

            if float(awas_cm) == 0:
                awas_cm = "300"

            raw_tma = (
                latest.get("limpas")
                if latest
                else (
                    item.get("tma")
                    or item.get("siap")
                    or 0
                )
            )

            tma_cm = smart_convert_cm(raw_tma)

            raw_time = (
                latest.get("created_at")
                or item.get("updated_at")
            )

            waktu_display = "Pembaruan Terakhir"

            if raw_time:

                try:

                    clean_str = (
                        str(raw_time)
                        .split(".")[0]
                        .replace("Z", "")
                    )

                    dt_utc = datetime.strptime(
                        clean_str,
                        "%Y-%m-%dT%H:%M:%S"
                    )

                    dt_wib = (
                        dt_utc
                        + timedelta(hours=7)
                    )

                    waktu_display = dt_wib.strftime(
                        "%d-%m-%Y %H:%M"
                    )

                except Exception:

                    waktu_display = (
                        str(raw_time)[:16]
                        .replace("T", " ")
                    )

            status = (
                latest.get("status")
                or item.get("status_alert")
                or "Operasional Normal"
            )

            pob = latest.get("pob_id")

            petugas = (
                f"ID Petugas: {pob}"
                if pob
                else "Unit Pemantauan"
            )

            cuaca_lokal = latest.get(
                "cuaca",
                "Berawan"
            )

            dam = {
                "name": name,
                "tma": tma_cm,
                "siaga": siaga_cm,
                "awas": awas_cm,
                "inflow": latest.get("debit", 0),
                "outflow": latest.get(
                    "debit_ke_saluran_induk",
                    0
                ),
                "status": status,
                "cuaca": cuaca_lokal,
                "petugas": petugas,
                "updated_at": (
                    waktu_display
                    + " WIB"
                ),
                "lokasi": (
                    item.get("river_name")
                    or item.get("regency_name")
                    or "Jawa Tengah"
                )
            }

            clean_data.append(dam)

        except Exception:
            continue

    return clean_data


def fetch_ews_data():

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json"
    }

    try:

        ts = int(time.time() * 1000)

        url = (
            "https://siagakranji.my.id/"
            f"data/latest_dams.json?t={ts}"
        )

        r = requests.get(
            url,
            headers=headers,
            timeout=6,
            verify=False
        )

        if r.status_code == 200:

            data = r.json()

            raw_list = (
                data.get("data")
                or data.get("result")
                or (
                    data
                    if isinstance(data, list)
                    else []
                )
            )

            if raw_list:
                return normalize_dam_data(
                    raw_list
                )

    except Exception:
        pass

    try:

        url = (
            "https://api.ewsjateng.com/"
            "api/dams?page=1&pageSize=200"
        )

        r = requests.get(
            url,
            headers=headers,
            timeout=9,
            verify=False
        )

        if r.status_code == 200:

            data = r.json()

            raw_list = data.get(
                "data",
                []
            )

            return normalize_dam_data(
                raw_list
            )

    except Exception:
        pass

    return []


# ==========================================
# 8. ROUTES UTAMA
# ==========================================

@app.route("/", methods=["GET"])
def home():

    stats = {
        "wilayah": 0,
        "mux": 0,
        "channel": 0
    }

    last_str = "-"

    if ref:

        try:

            siaran = (
                ref.child("siaran").get()
                or {}
            )

            for prov in siaran.values():

                if isinstance(prov, dict):

                    stats["wilayah"] += len(prov)

                    for wil in prov.values():

                        if isinstance(wil, dict):

                            stats["mux"] += len(wil)

                            for d in wil.values():

                                if (
                                    isinstance(d, dict)
                                    and "siaran" in d
                                ):

                                    stats["channel"] += len(
                                        d["siaran"]
                                    )

            last_str = datetime.now().strftime(
                "%d-%m-%Y"
            )

        except Exception:
            pass

    return render_template(
        "index.html",
        stats=stats,
        last_updated_time=last_str
    )


# ==========================================
# 8.1 LOGIN
# ==========================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        raw_input = request.form.get(
            "username"
        )

        password = request.form.get(
            "password"
        )

        hashed_pw = hash_password(
            password
        )

        clean_input = normalize_input(
            raw_input
        )

        if not ref:

            return render_template(
                "login.html",
                error=(
                    "Sistem gagal terhubung "
                    "ke pangkalan data utama."
                )
            )

        users = (
            ref.child("users").get()
            or {}
        )

        target_user = None
        target_uid = None

        for uid, data in users.items():

            if not isinstance(data, dict):
                continue

            if (
                normalize_input(uid)
                == clean_input
            ):

                target_user = data
                target_uid = uid
                break

            if (
                normalize_input(
                    data.get("email")
                )
                == clean_input
            ):

                target_user = data
                target_uid = uid
                break

        if (
            target_user
            and target_user.get("password")
            == hashed_pw
        ):

            session.permanent = True

            session["user"] = target_uid

            session["nama"] = target_user.get(
                "nama",
                "Pengguna Terdaftar"
            )

            return redirect(
                url_for("dashboard")
            )

        return render_template(
            "login.html",
            error=(
                "Kredensial identitas atau "
                "kata sandi yang Anda masukkan "
                "tidak valid."
            )
        )

    return render_template("login.html")


# ==========================================
# 8.2 REGISTER
# ==========================================

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        u = normalize_input(
            request.form.get("username")
        )

        e = normalize_input(
            request.form.get("email")
        )

        n = request.form.get("nama")
        p = request.form.get("password")

        if not ref:

            return (
                "Terjadi galat pada koneksi basis data. "
                "Harap hubungi administrator.",
                500
            )

        users = (
            ref.child("users").get()
            or {}
        )

        if u in users:

            flash(
                "Nama pengguna tersebut telah terdaftar "
                "di dalam sistem.",
                "error"
            )

            return render_template(
                "register.html"
            )

        for uid, data in users.items():

            if (
                isinstance(data, dict)
                and normalize_input(
                    data.get("email")
                ) == e
            ):

                flash(
                    "Alamat surel tersebut telah "
                    "diasosiasikan dengan akun lain.",
                    "error"
                )

                return render_template(
                    "register.html"
                )

        otp = str(
            random.randint(100000, 999999)
        )

        expiry = time.time() + 60

        ref.child(
            f"pending_users/{u}"
        ).set({
            "nama": n,
            "email": e,
            "password": hash_password(p),
            "otp": otp,
            "expiry": expiry
        })

        try:

            subject, body = get_email_template(
                "REGISTER",
                n,
                otp
            )

            msg = Message(
                subject,
                recipients=[e]
            )

            msg.body = body

            mail.send(msg)

            session["pending_username"] = u

            return redirect(
                url_for("verify_register")
            )

        except Exception:

            flash(
                "Kegagalan transmisi surel. "
                "Pastikan alamat yang diberikan valid "
                "dan aktif.",
                "error"
            )

    return render_template(
        "register.html"
    )


# ==========================================
# 8.3 VERIFIKASI REGISTER
# ==========================================

@app.route(
    "/verify-register",
    methods=["GET", "POST"]
)
def verify_register():

    u = session.get(
        "pending_username"
    )

    if not u:
        return redirect(
            url_for("register")
        )

    if request.method == "POST":

        p = (
            ref.child(
                f"pending_users/{u}"
            ).get()
        )

        if not p:
            return redirect(
                url_for("register")
            )

        if time.time() > p.get(
            "expiry",
            0
        ):

            flash(
                "Sesi kode verifikasi telah berakhir. "
                "Silakan lakukan permohonan ulang.",
                "error"
            )

            ref.child(
                f"pending_users/{u}"
            ).delete()

            return redirect(
                url_for("register")
            )

        submitted_otp = (
            request.form.get("otp") or ""
        ).strip()

        if (
            str(p.get("otp")).strip()
            == submitted_otp
        ):

            ref.child(
                f"users/{u}"
            ).set({
                "nama": p["nama"],
                "email": p["email"],
                "password": p["password"]
            })

            ref.child(
                f"pending_users/{u}"
            ).delete()

            session.pop(
                "pending_username",
                None
            )

            flash(
                "Registrasi telah berhasil diproses. "
                "Silakan masuk.",
                "success"
            )

            return redirect(
                url_for("login")
            )

        flash(
            "Kode otorisasi yang Anda masukkan "
            "tidak tepat.",
            "error"
        )

    return render_template(
        "verify-register.html",
        username=u
    )


# ==========================================
# 8.4 FORGOT PASSWORD
# ==========================================

@app.route(
    "/forgot-password",
    methods=["GET", "POST"]
)
def forgot_password():

    if request.method == "POST":

        email_input = normalize_input(
            request.form.get("identifier")
        )

        if not ref:
            return render_template(
                "forgot-password.html"
            )

        users = (
            ref.child("users").get()
            or {}
        )

        found_uid = None
        user_name = "Pengguna"

        for uid, user_data in users.items():

            if (
                isinstance(user_data, dict)
                and normalize_input(
                    user_data.get("email")
                ) == email_input
            ):

                found_uid = uid

                user_name = user_data.get(
                    "nama",
                    "Pengguna"
                )

                break

        if found_uid:

            otp = str(
                random.randint(
                    100000,
                    999999
                )
            )

            expiry = time.time() + 60

            ref.child(
                f"otp/{found_uid}"
            ).set({
                "email": email_input,
                "otp": otp,
                "expiry": expiry
            })

            try:

                subject, body = get_email_template(
                    "RESET",
                    user_name,
                    otp
                )

                msg = Message(
                    subject,
                    recipients=[email_input]
                )

                msg.body = body

                mail.send(msg)

                session["reset_uid"] = found_uid

                return redirect(
                    url_for("verify_otp")
                )

            except Exception:
                pass

    return render_template(
        "forgot-password.html"
    )


# ==========================================
# 8.5 VERIFY OTP
# ==========================================

@app.route(
    "/verify-otp",
    methods=["GET", "POST"]
)
def verify_otp():

    uid = session.get(
        "reset_uid"
    )

    if not uid:
        return redirect(
            url_for("forgot_password")
        )

    if request.method == "POST":

        data = (
            ref.child(
                f"otp/{uid}"
            ).get()
        )

        if not data:
            return redirect(
                url_for("forgot_password")
            )

        if time.time() > data.get(
            "expiry",
            0
        ):

            flash(
                "Masa berlaku kode verifikasi "
                "telah habis.",
                "error"
            )

            return redirect(
                url_for("forgot_password")
            )

        submitted_otp = (
            request.form.get("otp") or ""
        ).strip()

        if (
            str(data.get("otp")).strip()
            == submitted_otp
        ):

            session["reset_verified"] = True

            return redirect(
                url_for("reset_password")
            )

        flash(
            "Kode verifikasi tidak sesuai.",
            "error"
        )

    return render_template(
        "verify-otp.html"
    )


# ==========================================
# 8.6 RESET PASSWORD
# ==========================================

@app.route(
    "/reset-password",
    methods=["GET", "POST"]
)
def reset_password():

    if not session.get(
        "reset_verified"
    ):

        return redirect(
            url_for("login")
        )

    if request.method == "POST":

        uid = session.get(
            "reset_uid"
        )

        pw = request.form.get(
            "password"
        )

        ref.child(
            f"users/{uid}"
        ).update({
            "password": hash_password(pw)
        })

        ref.child(
            f"otp/{uid}"
        ).delete()

        session.clear()

        return redirect(
            url_for("login")
        )

    return render_template(
        "reset-password.html"
    )


@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("login")
    )


# ==========================================
# 8.7 BERITA
# ==========================================

@app.route("/berita")
def berita_page():

    entries = get_news_entries()

    page = request.args.get(
        "page",
        1,
        type=int
    )

    per_page = 9

    start = (
        page - 1
    ) * per_page

    end = start + per_page

    current = entries[
        start:end
    ]

    for article in current:

        if (
            "published_parsed" in article
            and article["published_parsed"]
        ):

            article["formatted_date"] = (
                format_indo_date(
                    article["published_parsed"]
                )
            )

            article["time_since_published"] = (
                time_since_published(
                    article["published_parsed"]
                )
            )

        else:

            article["formatted_date"] = (
                "Data Waktu Tidak Tersedia"
            )

            article["time_since_published"] = (
                "Terkini"
            )

    total_pages = max(
        1,
        (len(entries) + per_page - 1)
        // per_page
    )

    return render_template(
        "berita.html",
        articles=current,
        page=page,
        total_pages=total_pages
    )


# ==========================================
# 8.8 DASHBOARD
# ==========================================

@app.route("/dashboard")
def dashboard():

    if "user" not in session:
        return redirect(
            url_for("login")
        )

    data = (
        ref.child("provinsi").get()
        or {}
    )

    return render_template(
        "dashboard.html",
        name=session.get("nama"),
        provinsi_list=list(
            data.values()
        )
    )


@app.route("/daftar-siaran")
def daftar_siaran():

    data = (
        ref.child("provinsi").get()
        or {}
    )

    return render_template(
        "daftar-siaran.html",
        provinsi_list=list(
            data.values()
        )
    )


# ==========================================
# 8.9 DATA SIARAN
# ==========================================

@app.route(
    "/add_data",
    methods=["GET", "POST"]
)
def add_data():

    if "user" not in session:
        return redirect(
            url_for("login")
        )

    prov_data = (
        ref.child("provinsi").get()
        or {}
    )

    provinsi_list = (
        list(prov_data.values())
        if prov_data
        else [
            "DKI Jakarta",
            "Jawa Barat",
            "Jawa Tengah",
            "Jawa Timur"
        ]
    )

    if request.method == "POST":

        p = request.form.get(
            "provinsi"
        )

        w = request.form.get(
            "wilayah"
        )

        m = request.form.get(
            "mux"
        )

        s = request.form.get(
            "siaran"
        )

        if p and w and m and s:

            data_new = {
                "siaran": [
                    ch.strip()
                    for ch in s.split(",")
                ],
                "last_updated_by_name":
                    session.get("nama"),
                "last_updated_by_username":
                    session.get("user"),
                "last_updated_date":
                    datetime.now().strftime(
                        "%d-%m-%Y"
                    ),
                "last_updated_time":
                    datetime.now().strftime(
                        "%H:%M:%S WIB"
                    )
            }

            ref.child(
                f"siaran/{p}/{w}/{m}"
            ).set(data_new)

            ref.child(
                f"provinsi/{p}"
            ).set(p)

            flash(
                "Data berhasil ditambahkan "
                "ke dalam sistem.",
                "success"
            )

            return redirect(
                url_for("dashboard")
            )

    return render_template(
        "add_data_form.html",
        provinsi_list=sorted(
            provinsi_list
        )
    )


@app.route(
    "/edit_data/<provinsi>/<wilayah>/<mux>",
    methods=["GET", "POST"]
)
def edit_data(
    provinsi,
    wilayah,
    mux
):

    if "user" not in session:
        return redirect(
            url_for("login")
        )

    curr_data = (
        ref.child(
            f"siaran/{provinsi}/{wilayah}/{mux}"
        ).get()
    )

    if request.method == "POST":

        s = request.form.get(
            "siaran"
        )

        ref.child(
            f"siaran/{provinsi}/{wilayah}/{mux}"
        ).update({
            "siaran": [
                ch.strip()
                for ch in s.split(",")
            ],
            "last_updated_by_name":
                session.get("nama"),
            "last_updated_date":
                datetime.now().strftime(
                    "%d-%m-%Y"
                )
        })

        flash(
            "Pembaruan data berhasil disimpan.",
            "success"
        )

        return redirect(
            url_for("dashboard")
        )

    siaran_str = (
        ", ".join(
            curr_data.get("siaran", [])
        )
        if curr_data
        else ""
    )

    return render_template(
        "add_data_form.html",
        edit_mode=True,
        curr_siaran=siaran_str,
        provinsi_list=[provinsi],
        curr_provinsi=provinsi,
        curr_wilayah=wilayah,
        curr_mux=mux
    )


@app.route(
    "/delete_data/<provinsi>/<wilayah>/<mux>",
    methods=["POST"]
)
def delete_data(
    provinsi,
    wilayah,
    mux
):

    if "user" in session:

        try:

            ref.child(
                f"siaran/{provinsi}/{wilayah}/{mux}"
            ).delete()

            return jsonify({
                "status": "success"
            })

        except Exception:

            return jsonify({
                "status": "error"
            })

    return jsonify({
        "status": "unauthorized"
    })


@app.route("/get_wilayah")
def get_wilayah():

    provinsi = request.args.get(
        "provinsi"
    )

    data = (
        ref.child(
            f"siaran/{provinsi}"
        ).get()
        or {}
    )

    return jsonify({
        "wilayah": list(data.keys())
    })


@app.route("/get_mux")
def get_mux():

    provinsi = request.args.get(
        "provinsi"
    )

    wilayah = request.args.get(
        "wilayah"
    )

    data = (
        ref.child(
            f"siaran/{provinsi}/{wilayah}"
        ).get()
        or {}
    )

    return jsonify({
        "mux": list(data.keys())
    })


@app.route("/get_siaran")
def get_siaran():

    provinsi = request.args.get(
        "provinsi"
    )

    wilayah = request.args.get(
        "wilayah"
    )

    mux = request.args.get(
        "mux"
    )

    data = (
        ref.child(
            f"siaran/{provinsi}/{wilayah}/{mux}"
        ).get()
        or {}
    )

    return jsonify(data)


# ==========================================
# 8.10 EWS JATENG
# ==========================================

@app.route("/ews-jateng")
def ews_jateng_page():

    dams = fetch_ews_data()

    cuaca_list = get_cuaca_10_kota()

    return render_template(
        "ews-jateng.html",
        dams=dams,
        cuaca_list=cuaca_list
    )


@app.route("/lokasi")
def lokasi_page():

    return render_template(
        "lokasi.html"
    )


# ==========================================
# 8.11 CHATBOT MODI
# ==========================================

@app.route(
    "/api/chat",
    methods=["POST"]
)
def chatbot_api():

    data = request.get_json() or {}

    user_msg = data.get(
        "prompt",
        ""
    )

    if (
        "bendungan" in user_msg.lower()
        or "banjir" in user_msg.lower()
    ):

        dams = fetch_ews_data()

        bahaya = [
            f"{d['name']} ({d['status']})"
            for d in dams
            if (
                "awas"
                in d["status"].lower()
                or "siaga"
                in d["status"].lower()
            )
        ]

        if bahaya:

            context = (
                "INSTRUKSI PRIORITAS: "
                "Terdeteksi infrastruktur bendungan "
                "dalam status kewaspadaan tingkat tinggi: "
                f"{', '.join(bahaya)}. "
            )

        else:

            context = (
                "INFORMASI: Hasil pemantauan menunjukkan "
                f"{len(dams)} fasilitas bendungan berada "
                "dalam parameter operasional normal. "
            )

        full_prompt = (
            f"{MODI_PROMPT}\n"
            f"{context}\n"
            f"Pengguna: {user_msg}\n"
            "Modi:"
        )

    else:

        full_prompt = (
            f"{MODI_PROMPT}\n"
            f"Pengguna: {user_msg}\n"
            "Modi:"
        )

    model = get_gemini_model()

    if not model:

        return jsonify({
            "response":
                get_smart_fallback_response(
                    user_msg
                )
        })

    try:

        response = model.generate_content(
            full_prompt
        )

        try:

            teks_balasan = response.text

        except ValueError:

            teks_balasan = (
                "Sistem keamanan otomatis AI "
                "memblokir transmisi ini karena "
                "terindikasi mengandung konten yang "
                "tidak sesuai dengan protokol "
                "keamanan standar. Proses dihentikan."
            )

        return jsonify({
            "response": teks_balasan
        })

    except Exception as e:

        print(
            f"INFO GALAT: Anomali pada API Gemini: {e}"
        )

        return jsonify({
            "response":
                get_smart_fallback_response(
                    user_msg
                )
        })


# ==========================================
# 8.12 JADWAL SHOLAT
# ==========================================

@app.route("/jadwal-sholat")
def jadwal_sholat_page():

    daftar_kota = fetch_kemenag_kota()

    hijri_today = (
        get_hijri_date_string()
    )

    return render_template(
        "jadwal-sholat.html",
        daftar_kota=daftar_kota,
        quotes=get_quote_religi(),
        hijri_date=hijri_today
    )


@app.route("/api/jadwal-imsakiyah")
def get_jadwal_kemenag():

    id_kota = request.args.get(
        "id_kota"
    )

    bulan = request.args.get(
        "bulan",
        datetime.now().month
    )

    tahun = request.args.get(
        "tahun",
        datetime.now().year
    )

    if not id_kota:

        return jsonify({
            "status": False,
            "message": (
                "Atribut id_kota bersifat esensial "
                "dan wajib dilampirkan."
            )
        })

    try:

        url = (
            "https://api.myquran.com/v2/sholat/"
            f"jadwal/{id_kota}/{tahun}/{bulan}"
        )

        r = requests.get(
            url,
            timeout=10
        )

        if r.status_code == 200:
            return jsonify(
                r.json()
            )

    except Exception as e:

        return jsonify({
            "status": False,
            "message": str(e)
        })

    return jsonify({
        "status": False,
        "message": (
            "Terjadi kegagalan komunikasi dengan "
            "server penjadwalan pusat."
        )
    })


# ==========================================
# 8.13 NEWS TICKER
# ==========================================

@app.route("/api/news-ticker")
def news_ticker():

    return jsonify([
        n["title"]
        for n in get_news_entries()
    ])


# ==========================================
# 8.14 VISITOR STATS
# ==========================================

@app.route("/api/visitor-stats")
def visitor_stats():

    current_time = time.time()

    active_ips = {
        ip: ts
        for ip, ts
        in TRACKER_DATA["online_ips"].items()
        if current_time - ts <= 300
    }

    TRACKER_DATA["online_ips"] = active_ips

    active_locations = [
        TRACKER_DATA["ip_locations"].get(
            ip,
            "Tidak Terdeteksi"
        )
        for ip in active_ips.keys()
    ]

    return jsonify({
        "daily": len(
            TRACKER_DATA["daily_ips"]
        ),
        "online": max(
            1,
            len(active_ips)
        ),
        "active_locations": list(
            set(active_locations)
        )
    })


# ==========================================
# 9. API DETEKSI PELANGGARAN
# ==========================================

@app.route(
    "/api/detect_violation",
    methods=["POST"]
)
def api_detect_violation():

    try:

        data = request.get_json() or {}

        frame_base64 = data.get(
            "frame",
            ""
        )

        chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

        plat = (
            f"H {random.randint(1000, 9999)} "
            f"{random.choice(chars)}"
            f"{random.choice(chars)}"
        )

        pelanggaran = random.choice([
            "Pelanggaran Marka Jalan",
            "Ketidakpatuhan Penggunaan Sabuk Pengaman",
            "Pengendara Tidak Menggunakan Helm Standar"
        ])

        return jsonify({
            "status": "success",
            "plate": plat,
            "violation": pelanggaran
        })

    except Exception as e:

        return jsonify({
            "status": "error",
            "message": (
                "Terjadi kesalahan pada modul "
                f"pemrosesan citra: {str(e)}"
            )
        }), 500


# ==========================================
# 10. HALAMAN LAIN
# ==========================================

@app.route("/about")
def about():

    return render_template(
        "about.html"
    )


@app.route("/cctv")
def cctv_page():

    return render_template(
        "cctv.html"
    )


@app.route("/sitemap.xml")
def sitemap():

    return send_from_directory(
        "static",
        "sitemap.xml"
    )


# ==========================================
# 11. EMAIL BLAST EWS KTVDI
# ==========================================

@app.route(
    "/email",
    methods=["GET", "POST"]
)
def email_blast_page():

    if "user" not in session:

        return redirect(
            url_for("login")
        )

    if request.method == "POST":

        subject = request.form.get(
            "subject"
        )

        body_text = request.form.get(
            "message"
        )

        kategori = request.form.get(
            "kategori",
            "Informasi Umum"
        )

        prioritas = request.form.get(
            "prioritas",
            "Normal"
        )

        if not subject or not body_text:

            flash(
                "Halo Admin, mohon pastikan "
                "subjek dan isi pesan sudah terisi ya.",
                "error"
            )

            return redirect(
                url_for("email_blast_page")
            )

        if not ref:

            flash(
                "Gagal memuat database anggota. "
                "Pastikan koneksi ke Firebase aman.",
                "error"
            )

            return redirect(
                url_for("email_blast_page")
            )

        users = (
            ref.child("users").get()
            or {}
        )

        sent_details = []

        tz_jakarta = pytz.timezone(
            "Asia/Jakarta"
        )

        with app.app_context():

            for uid, user_data in users.items():

                if not isinstance(
                    user_data,
                    dict
                ):
                    continue

                email_tujuan = user_data.get(
                    "email"
                )

                nama_user = user_data.get(
                    "nama",
                    "Anggota KTVDI"
                )

                if not email_tujuan:
                    continue

                formatted_body = f"""
PESAN BLAST KTVDI (KOMUNITAS TV DIGITAL INDONESIA)
Kategori  : {kategori}
Prioritas : {prioritas}
========================================================

Halo Bapak/Ibu {nama_user},

{body_text}

Terima kasih atas perhatiannya. Mari tetap dukung
pertelevisian di Indonesia bersama KTVDI.

Salam hangat,
Admin KTVDI
========================================================
"""

                waktu_kirim = datetime.now(
                    tz_jakarta
                ).strftime(
                    "%d %b %Y - %H:%M:%S WIB"
                )

                try:

                    msg = Message(
                        subject,
                        recipients=[
                            email_tujuan
                        ]
                    )

                    msg.body = formatted_body

                    mail.send(msg)

                    sent_details.append({
                        "nama": nama_user,
                        "email": email_tujuan,
                        "waktu": waktu_kirim,
                        "status": "Sukses"
                    })

                except Exception as e:

                    print(
                        f"Gagal mengirim ke "
                        f"{email_tujuan}: {e}"
                    )

                    sent_details.append({
                        "nama": nama_user,
                        "email": email_tujuan,
                        "waktu": waktu_kirim,
                        "status": "Gagal"
                    })

        if sent_details:

            session[
                "last_sent_details"
            ] = sent_details

            berhasil = sum(
                1
                for x in sent_details
                if x["status"] == "Sukses"
            )

            flash(
                f"Mantap! Pesan blast berhasil "
                f"terkirim ke {berhasil} dari "
                f"{len(sent_details)} anggota.",
                "success"
            )

        else:

            flash(
                "Ups, proses dibatalkan atau tidak "
                "ada anggota di database.",
                "error"
            )

        return redirect(
            url_for("email_blast_page")
        )

    sent_list = session.pop(
        "last_sent_details",
        None
    )

    total_users = 0

    if ref:

        try:

            total_users = len(
                ref.child(
                    "users"
                ).get()
                or {}
            )

        except Exception:
            pass

    return render_template(
        "email.html",
        sent_list=sent_list,
        total_users=total_users
    )


# ==========================================================
# 12. NETWORK MONITORING
# ==========================================================

NETWORK_CACHE = {
    "time": 0,
    "data": None
}


def run_command(command, timeout=3):

    try:

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False
        )

        return result.stdout.strip()

    except Exception:
        return ""


def get_default_gateway():

    system = platform.system().lower()

    # --------------------------------------
    # WINDOWS
    # --------------------------------------

    if system == "windows":

        output = run_command(
            [
                "ipconfig"
            ],
            timeout=3
        )

        gateway = None

        for line in output.splitlines():

            if (
                "Default Gateway"
                in line
            ):

                value = line.split(
                    ":",
                    1
                )[-1].strip()

                if value:

                    try:
                        ipaddress.ip_address(
                            value
                        )

                        gateway = value
                        break

                    except Exception:
                        continue

        return gateway

    # --------------------------------------
    # LINUX / MAC
    # --------------------------------------

    if shutil.which("ip"):

        output = run_command(
            [
                "ip",
                "route",
                "show",
                "default"
            ]
        )

        match = re.search(
            r"default via ([0-9.]+)",
            output
        )

        if match:
            return match.group(1)

    if shutil.which("route"):

        output = run_command(
            [
                "route",
                "-n"
            ]
        )

        for line in output.splitlines():

            parts = line.split()

            if (
                len(parts) >= 2
                and parts[0] == "0.0.0.0"
            ):

                try:

                    ipaddress.ip_address(
                        parts[1]
                    )

                    return parts[1]

                except Exception:
                    pass

    return None


def get_local_ip():

    try:

        s = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM
        )

        s.settimeout(1)

        s.connect(
            ("8.8.8.8", 80)
        )

        ip = s.getsockname()[0]

        s.close()

        return ip

    except Exception:

        try:
            return socket.gethostbyname(
                socket.gethostname()
            )
        except Exception:
            return None


def get_local_interface():

    system = platform.system().lower()

    if system == "windows":

        local_ip = get_local_ip()

        if not local_ip:
            return ""

        output = run_command(
            [
                "ipconfig"
            ]
        )

        current_adapter = ""

        for line in output.splitlines():

            line_strip = line.strip()

            if (
                line
                and not line.startswith(" ")
                and not line.startswith("\t")
                and ":" in line
            ):
                current_adapter = (
                    line_strip.rstrip(":")
                )

            if local_ip in line:

                return current_adapter

        return ""

    if shutil.which("ip"):

        local_ip = get_local_ip()

        output = run_command(
            [
                "ip",
                "-o",
                "addr",
                "show"
            ]
        )

        for line in output.splitlines():

            if local_ip and local_ip in line:

                parts = line.split()

                if len(parts) >= 2:
                    return parts[1]

    return ""


def get_local_network():

    local_ip = get_local_ip()
    gateway = get_default_gateway()

    if not local_ip:
        return None

    # Umumnya LAN rumah/kantor menggunakan /24.
    # Jika gateway diketahui dan satu subnet,
    # gunakan /24 sebagai fallback aman.

    try:

        if gateway:

            network = ipaddress.ip_network(
                f"{local_ip}/24",
                strict=False
            )

            if (
                ipaddress.ip_address(
                    gateway
                ) in network
            ):
                return network

        return ipaddress.ip_network(
            f"{local_ip}/24",
            strict=False
        )

    except Exception:
        return None


def normalize_mac(mac):

    if not mac:
        return ""

    mac = mac.strip().lower()

    mac = mac.replace("-", ":")
    mac = mac.replace(".", ":")

    parts = mac.split(":")

    if len(parts) == 6:

        return ":".join(
            p.zfill(2)
            for p in parts
        )

    return mac


def get_mac_vendor(mac):

    """
    Lookup vendor melalui MAC prefix.
    Tidak bergantung pada layanan eksternal.
    """

    if not mac:
        return "Tidak Diketahui"

    oui = normalize_mac(
        mac
    ).replace(":", "")[:6].upper()

    known = {

        "001A2B": "Cisco",
        "001C42": "Parallels",
        "000C29": "VMware",
        "005056": "VMware",
        "080027": "VirtualBox",

        "3C5A37": "Google",
        "F4F5D8": "Google",

        "B827EB": "Raspberry Pi",
        "DC4F22": "Raspberry Pi",

        "ACDE48": "Apple",
        "3C22FB": "Apple",
        "F0D2F1": "Apple",

        "001A11": "Intel",
        "3CE9F7": "Intel",

        "F8E4FB": "Xiaomi",
        "C8FF28": "Xiaomi",
        "7811DC": "Xiaomi",

        "A4C138": "Samsung",
        "CC07AB": "Samsung",
        "B8BC1B": "Samsung",

        "D850E6": "Huawei",
        "E8CD2D": "Huawei",

        "FCFBFB": "TP-Link",
        "50C7BF": "TP-Link",
        "AC84C6": "TP-Link",

        "E4FAED": "ZTE",

        "001E58": "Hikvision",
        "C0EAE4": "Hikvision",

        "B0BE76": "D-Link",
        "1C7EE5": "D-Link"
    }

    return known.get(
        oui,
        "Vendor Tidak Diketahui"
    )


def resolve_hostname(ip):

    try:

        host = socket.gethostbyaddr(
            ip
        )[0]

        if host:
            return host

    except Exception:
        pass

    return "-"


def guess_device_type(
    hostname="",
    vendor="",
    mac=""
):

    text = (
        f"{hostname} "
        f"{vendor} "
        f"{mac}"
    ).lower()

    if any(
        x in text
        for x in [
            "iphone",
            "ipad",
            "apple"
        ]
    ):
        return "Apple"

    if any(
        x in text
        for x in [
            "android",
            "samsung",
            "xiaomi",
            "redmi",
            "oppo",
            "vivo",
            "realme",
            "huawei"
        ]
    ):
        return "Smartphone"

    if any(
        x in text
        for x in [
            "printer",
            "epson",
            "canon",
            "hp-"
        ]
    ):
        return "Printer"

    if any(
        x in text
        for x in [
            "camera",
            "cctv",
            "hikvision",
            "dahua"
        ]
    ):
        return "CCTV"

    if any(
        x in text
        for x in [
            "router",
            "gateway",
            "mikrotik",
            "tp-link",
            "zte",
            "huawei"
        ]
    ):
        return "Router / Network"

    if any(
        x in text
        for x in [
            "desktop",
            "pc",
            "windows"
        ]
    ):
        return "PC"

    if any(
        x in text
        for x in [
            "laptop",
            "notebook"
        ]
    ):
        return "Laptop"

    return "Perangkat"


def parse_linux_neighbors():

    devices = []

    if not shutil.which("ip"):
        return devices

    output = run_command(
        [
            "ip",
            "neigh",
            "show"
        ],
        timeout=3
    )

    for line in output.splitlines():

        line = line.strip()

        if not line:
            continue

        match = re.search(
            r"^(\d+\.\d+\.\d+\.\d+)"
            r".*?"
            r"(?:lladdr\s+)"
            r"([0-9a-fA-F:]{17})"
            r"(?:\s+(\S+))?",
            line
        )

        if not match:
            continue

        ip = match.group(1)
        mac = normalize_mac(
            match.group(2)
        )

        state = (
            match.group(3)
            or "UNKNOWN"
        ).upper()

        devices.append({
            "ip": ip,
            "mac": mac,
            "state": state,
            "source": "ARP / Neighbor"
        })

    return devices


def parse_windows_arp():

    devices = []

    if platform.system().lower() != "windows":
        return devices

    output = run_command(
        [
            "arp",
            "-a"
        ],
        timeout=4
    )

    for line in output.splitlines():

        match = re.search(
            r"(\d+\.\d+\.\d+\.\d+)"
            r"\s+"
            r"([0-9a-fA-F-]{17})"
            r"\s+(\w+)",
            line
        )

        if not match:
            continue

        devices.append({
            "ip": match.group(1),
            "mac": normalize_mac(
                match.group(2)
            ),
            "state": "REACHABLE",
            "source": "ARP"
        })

    return devices


def parse_arp_command():

    devices = []

    if not shutil.which("arp"):
        return devices

    output = run_command(
        [
            "arp",
            "-a"
        ],
        timeout=4
    )

    for line in output.splitlines():

        match = re.search(
            r"\(?(\d+\.\d+\.\d+\.\d+)\)?"
            r".*?"
            r"([0-9a-fA-F:]{17}|[0-9a-fA-F-]{17})",
            line
        )

        if not match:
            continue

        devices.append({
            "ip": match.group(1),
            "mac": normalize_mac(
                match.group(2)
            ),
            "state": "REACHABLE",
            "source": "ARP"
        })

    return devices


def get_gateway_device():

    gateway = get_default_gateway()

    if not gateway:
        return None

    mac = ""

    for source in [
        parse_linux_neighbors(),
        parse_windows_arp(),
        parse_arp_command()
    ]:

        for item in source:

            if item["ip"] == gateway:

                mac = item.get(
                    "mac",
                    ""
                )

                break

        if mac:
            break

    hostname = resolve_hostname(
        gateway
    )

    vendor = get_mac_vendor(
        mac
    )

    return {
        "ip": gateway,
        "mac": mac,
        "hostname": hostname,
        "vendor": vendor,
        "device": "Gateway / Router",
        "status": "Online",
        "signal": "-",
        "connection": "Gateway",
        "source": "Gateway"
    }


def scan_with_nmap(network):

    devices = []

    if not shutil.which("nmap"):
        return devices

    try:

        output = run_command(
            [
                "nmap",
                "-sn",
                str(network)
            ],
            timeout=20
        )

        current_ip = None

        for line in output.splitlines():

            ip_match = re.search(
                r"Nmap scan report for "
                r"(?:[^(]+\s+\()?(\d+\.\d+\.\d+\.\d+)",
                line
            )

            if ip_match:

                current_ip = (
                    ip_match.group(1)
                )

            mac_match = re.search(
                r"MAC Address:\s+"
                r"([0-9A-Fa-f:]{17})"
                r"(?:\s+\((.*?)\))?",
                line
            )

            if (
                current_ip
                and mac_match
            ):

                mac = normalize_mac(
                    mac_match.group(1)
                )

                vendor = (
                    mac_match.group(2)
                    or get_mac_vendor(mac)
                )

                devices.append({
                    "ip": current_ip,
                    "mac": mac,
                    "state": "REACHABLE",
                    "vendor": vendor,
                    "source": "Nmap"
                })

                current_ip = None

    except Exception:
        pass

    return devices


def scan_network_devices():

    now = time.time()

    # Cache 15 detik supaya network.html
    # polling tidak melakukan scan terus-menerus.

    if (
        NETWORK_CACHE["data"] is not None
        and now - NETWORK_CACHE["time"] < 15
    ):
        return NETWORK_CACHE["data"]

    local_ip = get_local_ip()
    gateway = get_default_gateway()
    interface = get_local_interface()
    network = get_local_network()

    raw_devices = []

    # --------------------------------------
    # 1. Linux Neighbor Table
    # --------------------------------------

    raw_devices.extend(
        parse_linux_neighbors()
    )

    # --------------------------------------
    # 2. Windows ARP
    # --------------------------------------

    raw_devices.extend(
        parse_windows_arp()
    )

    # --------------------------------------
    # 3. ARP Generic
    # --------------------------------------

    raw_devices.extend(
        parse_arp_command()
    )

    # --------------------------------------
    # 4. NMAP sebagai tambahan
    # --------------------------------------

    if network:

        raw_devices.extend(
            scan_with_nmap(
                network
            )
        )

    # --------------------------------------
    # DEDUPLICATION
    # --------------------------------------

    unique = {}

    for item in raw_devices:

        ip = item.get("ip")

        if not ip:
            continue

        try:
            ipaddress.ip_address(ip)
        except Exception:
            continue

        mac = normalize_mac(
            item.get("mac", "")
        )

        key = mac or ip

        if key not in unique:

            unique[key] = {
                "ip": ip,
                "mac": mac,
                "state": item.get(
                    "state",
                    "UNKNOWN"
                ),
                "source": item.get(
                    "source",
                    "Unknown"
                ),
                "vendor": item.get(
                    "vendor",
                    ""
                )
            }

        else:

            # Jika sumber baru mempunyai MAC
            # lebih lengkap, gunakan data tersebut.

            if (
                mac
                and not unique[key].get("mac")
            ):
                unique[key]["mac"] = mac

            if (
                item.get("vendor")
                and (
                    not unique[key].get("vendor")
                    or unique[key]["vendor"]
                    == "Vendor Tidak Diketahui"
                )
            ):
                unique[key]["vendor"] = (
                    item["vendor"]
                )

    # --------------------------------------
    # FORMAT FINAL
    # --------------------------------------

    devices = []

    for item in unique.values():

        ip = item["ip"]
        mac = item.get("mac", "")

        hostname = resolve_hostname(
            ip
        )

        vendor = (
            item.get("vendor")
            or get_mac_vendor(mac)
        )

        state = (
            item.get("state")
            or "UNKNOWN"
        ).upper()

        online_states = [
            "REACHABLE",
            "STALE",
            "DELAY",
            "PROBE"
        ]

        status = (
            "Online"
            if state in online_states
            else "Terdeteksi"
        )

        # Gateway selalu diprioritaskan.

        if gateway and ip == gateway:

            device_type = (
                "Gateway / Router"
            )

            connection = "Gateway"

        else:

            device_type = guess_device_type(
                hostname,
                vendor,
                mac
            )

            connection = (
                "LAN"
                if ip
                else "-"
            )

        devices.append({
            "ip": ip,
            "mac": mac or "-",
            "hostname": hostname,
            "vendor": vendor,
            "device": device_type,
            "status": status,
            "signal": "-",
            "connection": connection,
            "source": item.get(
                "source",
                "ARP"
            )
        })

    # --------------------------------------
    # MASUKKAN LOCAL HOST
    # --------------------------------------

    if local_ip:

        local_exists = any(
            d["ip"] == local_ip
            for d in devices
        )

        if not local_exists:

            hostname = resolve_hostname(
                local_ip
            )

            devices.append({
                "ip": local_ip,
                "mac": "-",
                "hostname": hostname,
                "vendor": "Local Host",
                "device": "Server / Host",
                "status": "Online",
                "signal": "-",
                "connection": "LAN",
                "source": "Local"
            })

    # --------------------------------------
    # GATEWAY
    # --------------------------------------

    gateway_device = (
        get_gateway_device()
    )

    if gateway_device:

        existing_gateway = next(
            (
                d
                for d in devices
                if d["ip"] == gateway_device["ip"]
            ),
            None
        )

        if existing_gateway:

            existing_gateway.update(
                gateway_device
            )

        else:

            devices.insert(
                0,
                gateway_device
            )

    # --------------------------------------
    # SORT IP
    # --------------------------------------

    def ip_sort(item):

        try:

            return tuple(
                int(x)
                for x in item["ip"].split(".")
            )

        except Exception:

            return (
                999,
                999,
                999,
                999
            )

    devices.sort(
        key=ip_sort
    )

    result = {
        "status": "success",
        "local_ip": local_ip or "-",
        "gateway": gateway or "-",
        "network": (
            str(network)
            if network
            else "-"
        ),
        "interface": interface or "-",
        "platform": platform.system(),
        "clients_count": len(devices),
        "online_count": sum(
            1
            for d in devices
            if d["status"] == "Online"
        ),
        "devices": devices,
        "scan_time": datetime.now().strftime(
            "%d-%m-%Y %H:%M:%S"
        )
    }

    NETWORK_CACHE["time"] = now
    NETWORK_CACHE["data"] = result

    return result


# ==========================================
# 12.1 NETWORK PAGE
# ==========================================

@app.route("/network")
def network_page():

    if "user" not in session:

        return redirect(
            url_for("login")
        )

    return render_template(
        "network.html"
    )


# ==========================================
# 12.2 NETWORK DATA API
# ==========================================

@app.route("/api/network-data")
def network_data_api():

    try:

        data = scan_network_devices()

        return jsonify(data)

    except Exception as e:

        return jsonify({
            "status": "error",
            "message": str(e),
            "ssid": "Tidak Terdeteksi",
            "channel": "-",
            "clients_count": 0,
            "online_count": 0,
            "avg_signal": 0,
            "download_mbps": 0,
            "upload_mbps": 0,
            "devices": []
        })


# ==========================================
# 12.3 NETWORK RESCAN
# ==========================================

@app.route("/api/network-rescan")
def network_rescan():

    try:

        NETWORK_CACHE["time"] = 0
        NETWORK_CACHE["data"] = None

        data = scan_network_devices()

        return jsonify(data)

    except Exception as e:

        return jsonify({
            "status": "error",
            "message": str(e),
            "devices": []
        }), 500


# ==========================================
# 13. RUN SERVER
# ==========================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                5000
            )
        ),
        debug=True
    )
