```python
import os
import time
import socket
import random
import hashlib
import ipaddress
import platform
import urllib3
import xml.etree.ElementTree as ET

from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytz
import requests
import feedparser
import firebase_admin
import google.generativeai as genai

from dotenv import load_dotenv
from firebase_admin import credentials, db
from flask import Flask, request, render_template, redirect, url_for, session, flash, jsonify
from flask_cors import CORS
from flask_mail import Mail, Message


# =========================================================
# 1. ENVIRONMENT & APPLICATION
# =========================================================

load_dotenv()

urllib3.disable_warnings(
    urllib3.exceptions.InsecureRequestWarning
)

app = Flask(__name__)

CORS(
    app,
    resources={
        r"/api/*": {
            "origins": "*"
        }
    }
)

app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY",
    "KTVDI_OFFICIAL_SECRET_KEY_FINAL_PRO_2026"
)

app.config.update(
    SESSION_PERMANENT=True,
    PERMANENT_SESSION_LIFETIME=86400,
    JSON_SORT_KEYS=False
)


# =========================================================
# 2. TIMEZONE
# =========================================================

WIB = pytz.timezone("Asia/Jakarta")


def now_wib():
    """Mengembalikan waktu Jakarta."""
    return datetime.now(WIB)


def now_timestamp():
    """Unix timestamp."""
    return time.time()


# =========================================================
# 3. MAINTENANCE
# =========================================================

# Isi None jika tidak ingin maintenance mode.
MAINTENANCE_END_DATE = None


@app.before_request
def maintenance_interceptor():
    """
    Mencegah maintenance mengganggu static/API
    jika maintenance memang diaktifkan.
    """

    if MAINTENANCE_END_DATE is None:
        return None

    if request.endpoint == "static":
        return None

    if request.path.startswith("/api/health"):
        return None

    if now_wib().replace(tzinfo=None) < MAINTENANCE_END_DATE:
        return render_template(
            "maintenance.html"
        ), 503

    return None


# =========================================================
# 4. VISITOR TRACKER
# =========================================================

TRACKER_DATA = {
    "date": now_wib().date(),
    "daily_ips": set(),
    "online_ips": {},
    "ip_locations": {}
}


def get_client_ip():
    """
    Mengambil IP client dengan aman.

    Prioritas:
    1. X-Forwarded-For
    2. X-Real-IP
    3. remote_addr
    """

    forwarded = request.headers.get(
        "X-Forwarded-For"
    )

    if forwarded:
        return forwarded.split(",")[0].strip()

    real_ip = request.headers.get(
        "X-Real-IP"
    )

    if real_ip:
        return real_ip.strip()

    return (
        request.remote_addr
        or ""
    ).strip()


def is_valid_ip(value):
    try:
        ipaddress.ip_address(value)
        return True
    except Exception:
        return False


def fetch_and_store_location_sync(ip):
    """
    GeoIP ringan.

    Timeout dibuat pendek agar tidak menyebabkan
    Vercel function menggantung.
    """

    try:
        if not is_valid_ip(ip):
            return

        ip_obj = ipaddress.ip_address(ip)

        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_reserved
        ):
            TRACKER_DATA["ip_locations"][ip] = (
                "Jaringan Lokal"
            )
            return

        response = requests.get(
            f"https://ip-api.com/json/{ip}",
            params={
                "fields": "status,city,regionName,country"
            },
            timeout=1.5
        )

        if response.status_code != 200:
            return

        data = response.json()

        if data.get("status") != "success":
            TRACKER_DATA["ip_locations"][ip] = (
                "Tidak Terdeteksi"
            )
            return

        city = data.get(
            "city",
            "Unknown"
        )

        region = data.get(
            "regionName",
            ""
        )

        country = data.get(
            "country",
            ""
        )

        location = ", ".join(
            part
            for part in [
                city,
                region,
                country
            ]
            if part
        )

        TRACKER_DATA["ip_locations"][ip] = (
            location or "Tidak Terdeteksi"
        )

    except Exception:
        TRACKER_DATA["ip_locations"][ip] = (
            "Tidak Terdeteksi"
        )


@app.before_request
def visitor_tracker():
    """
    Tracker sederhana.

    Jangan melakukan pekerjaan berat di sini.
    """

    if not request.endpoint:
        return None

    if request.endpoint == "static":
        return None

    try:
        today = now_wib().date()

        if TRACKER_DATA["date"] != today:
            TRACKER_DATA["date"] = today
            TRACKER_DATA["daily_ips"].clear()
            TRACKER_DATA["online_ips"].clear()
            TRACKER_DATA["ip_locations"].clear()

        user_ip = get_client_ip()

        if not user_ip:
            return None

        TRACKER_DATA["daily_ips"].add(
            user_ip
        )

        TRACKER_DATA["online_ips"][user_ip] = (
            now_timestamp()
        )

        if (
            user_ip not in TRACKER_DATA["ip_locations"]
            and is_valid_ip(user_ip)
        ):
            try:
                private = ipaddress.ip_address(
                    user_ip
                ).is_private
            except Exception:
                private = True

            if not private:
                # Jangan blok request utama terlalu lama.
                # Tandai dulu.
                TRACKER_DATA["ip_locations"][user_ip] = (
                    "Belum tersedia"
                )

    except Exception as exc:
        print(
            "TRACKER WARNING:",
            exc
        )

    return None


# =========================================================
# 5. FIREBASE
# =========================================================

ref = None


def initialize_firebase():
    global ref

    try:
        if firebase_admin._apps:
            ref = db.reference("/")
            return

        private_key = os.environ.get(
            "FIREBASE_PRIVATE_KEY"
        )

        if private_key:
            credential_data = {
                "type": "service_account",
                "project_id": os.environ.get(
                    "FIREBASE_PROJECT_ID"
                ),
                "private_key_id": os.environ.get(
                    "FIREBASE_PRIVATE_KEY_ID"
                ),
                "private_key": private_key.replace(
                    "\\n",
                    "\n"
                ),
                "client_email": os.environ.get(
                    "FIREBASE_CLIENT_EMAIL"
                ),
                "client_id": os.environ.get(
                    "FIREBASE_CLIENT_ID"
                ),
                "auth_uri": (
                    "https://accounts.google.com/"
                    "o/oauth2/auth"
                ),
                "token_uri": (
                    "https://oauth2.googleapis.com/token"
                ),
                "auth_provider_x509_cert_url": (
                    "https://www.googleapis.com/oauth2/v1/certs"
                ),
                "client_x509_cert_url": os.environ.get(
                    "FIREBASE_CLIENT_X509_CERT_URL"
                ),
                "universe_domain": "googleapis.com"
            }

            credential = credentials.Certificate(
                credential_data
            )

        elif os.path.exists("credentials.json"):
            credential = credentials.Certificate(
                "credentials.json"
            )

        else:
            print(
                "WARNING: Firebase credentials tidak ditemukan."
            )
            return

        firebase_admin.initialize_app(
            credential,
            {
                "databaseURL": os.environ.get(
                    "DATABASE_URL"
                )
            }
        )

        ref = db.reference("/")

        print(
            "INFO: Firebase berhasil terhubung."
        )

    except Exception as exc:
        ref = None

        print(
            "FIREBASE ERROR:",
            exc
        )


initialize_firebase()


# =========================================================
# 6. MAIL
# =========================================================

app.config.update(
    MAIL_SERVER="smtp.gmail.com",
    MAIL_PORT=587,
    MAIL_USE_TLS=True,
    MAIL_USERNAME=os.environ.get(
        "MAIL_USERNAME"
    ),
    MAIL_PASSWORD=os.environ.get(
        "MAIL_PASSWORD"
    ),
    MAIL_DEFAULT_SENDER=os.environ.get(
        "MAIL_USERNAME"
    )
)

mail = Mail(app)


# =========================================================
# 7. GEMINI
# =========================================================

GEMINI_KEY = os.environ.get(
    "GEMINI_API_KEY"
)

GEMINI_MODEL = None


def get_gemini_model():
    global GEMINI_MODEL

    if GEMINI_MODEL is not None:
        return GEMINI_MODEL

    if not GEMINI_KEY:
        return None

    try:
        genai.configure(
            api_key=GEMINI_KEY
        )

        GEMINI_MODEL = genai.GenerativeModel(
            "gemini-1.5-flash"
        )

        return GEMINI_MODEL

    except Exception as exc:
        print(
            "GEMINI ERROR:",
            exc
        )

        return None


MODI_PROMPT = """
Anda adalah MODI, Asisten Virtual Resmi
Komunitas TV Digital Indonesia (KTVDI).

Gunakan Bahasa Indonesia yang profesional,
informatif, objektif, dan mudah dipahami.

Fokus:
1. TV Digital.
2. STB.
3. Antena.
4. Topologi jaringan siaran.
5. Informasi siaran.
6. Cuaca dan EWS secara faktual.
"""


# =========================================================
# 8. GENERAL HELPERS
# =========================================================

def hash_password(password):
    return hashlib.sha256(
        (password or "").encode()
    ).hexdigest()


def normalize_input(value):
    return (
        value.strip().lower()
        if value
        else ""
    )


def safe_json(data, default=None):
    try:
        return data.json()
    except Exception:
        return (
            default
            if default is not None
            else {}
        )


def format_indo_date(time_struct):
    if not time_struct:
        return now_wib().strftime(
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
        return (
            "Informasi Waktu Tidak Tersedia"
        )


def get_email_template(
    action_type,
    nama_user,
    otp_code
):
    waktu = now_wib().strftime(
        "%d %B %Y, Pukul %H:%M WIB"
    )

    if action_type == "REGISTER":
        subject = (
            "Verifikasi Keamanan: "
            f"Pendaftaran Akun KTVDI [{otp_code}]"
        )

        title = (
            "Verifikasi Pendaftaran Akun Baru"
        )

        desc = (
            "Sistem mendeteksi permintaan "
            "pendaftaran akun baru di portal KTVDI."
        )

        warning = (
            "Apabila Anda tidak melakukan "
            "pendaftaran ini, abaikan pesan."
        )

    else:
        subject = (
            "Pemberitahuan Sistem KTVDI"
        )

        title = (
            "Notifikasi Sistem"
        )

        desc = (
            "Terdapat pembaruan informasi "
            "terkait akun Anda."
        )

        warning = ""

    body = f"""
SISTEM KEAMANAN RESMI KTVDI

Yth. {nama_user},

{desc}

Kode Verifikasi:
[ {otp_code} ]

Kode berlaku selama 60 detik.

{warning}

Waktu Permintaan:
{waktu}

Hormat kami,
Divisi Teknologi & Keamanan Informasi KTVDI
"""

    return subject, body


# =========================================================
# 9. NEWS CACHE
# =========================================================

NEWS_CACHE = []
NEWS_LAST_FETCH = 0
NEWS_CACHE_TTL = 300


def fetch_feed(url):
    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": "KTVDI/1.0"
            },
            timeout=2
        )

        if response.status_code != 200:
            return None

        return feedparser.parse(
            response.content
        )

    except Exception:
        return None


def get_news_entries():
    global NEWS_CACHE
    global NEWS_LAST_FETCH

    if (
        NEWS_CACHE
        and now_timestamp() - NEWS_LAST_FETCH
        < NEWS_CACHE_TTL
    ):
        return NEWS_CACHE

    sources = [
        "https://www.kompas.tv/rss",
        "https://www.setneg.go.id/rss",
        "https://www.liputan6.com/rss",
        "https://www.tribunnews.com/rss"
    ]

    all_news = []

    try:
        with ThreadPoolExecutor(
            max_workers=4
        ) as executor:

            futures = {
                executor.submit(
                    fetch_feed,
                    url
                ): url
                for url in sources
            }

            for future in as_completed(
                futures
            ):
                url = futures[future]

                try:
                    feed = future.result()
                except Exception:
                    continue

                if not feed or not feed.entries:
                    continue

                domain = (
                    url.split("//")[-1]
                    .split(".")[1]
                    .capitalize()
                )

                for entry in feed.entries[:8]:
                    entry["source_name"] = domain

                    image = None

                    media = entry.get(
                        "media_content"
                    )

                    if media:
                        image = media[0].get(
                            "url"
                        )

                    entry["image"] = image

                    all_news.append(
                        entry
                    )

    except Exception as exc:
        print(
            "NEWS WARNING:",
            exc
        )

    all_news.sort(
        key=lambda item: (
            item.get(
                "published_parsed"
            )
            or time.gmtime(0)
        ),
        reverse=True
    )

    NEWS_CACHE = all_news[:50]

    if not NEWS_CACHE:
        NEWS_CACHE = [
            {
                "title": (
                    "Sistem Informasi KTVDI Normal"
                ),
                "link": "#",
                "published_parsed": (
                    now_wib().timetuple()
                ),
                "source_name": "Internal",
                "image": None
            }
        ]

    NEWS_LAST_FETCH = now_timestamp()

    return NEWS_CACHE


def time_since_published(
    published_time
):
    try:
        published = datetime(
            *published_time[:6]
        )

        diff = datetime.now() - published

        if diff.days > 0:
            return f"{diff.days} hari lalu"

        if diff.seconds > 3600:
            return (
                f"{diff.seconds // 3600} jam lalu"
            )

        if diff.seconds > 60:
            return (
                f"{diff.seconds // 60} menit lalu"
            )

        return "Terkini"

    except Exception:
        return ""


# =========================================================
# 10. WEATHER
# =========================================================

WEATHER_CACHE = []
WEATHER_LAST_FETCH = 0
WEATHER_CACHE_TTL = 300


def get_cuaca_10_kota():
    global WEATHER_CACHE
    global WEATHER_LAST_FETCH

    if (
        WEATHER_CACHE
        and now_timestamp() - WEATHER_LAST_FETCH
        < WEATHER_CACHE_TTL
    ):
        return WEATHER_CACHE

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
        }
    ]

    try:
        latitude = ",".join(
            str(city["lat"])
            for city in cities
        )

        longitude = ",".join(
            str(city["lon"])
            for city in cities
        )

        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={latitude}"
            f"&longitude={longitude}"
            "&current=temperature_2m,weather_code"
            "&timezone=Asia%2FBangkok"
        )

        response = requests.get(
            url,
            timeout=2
        )

        if response.status_code != 200:
            raise RuntimeError(
                "Weather API error"
            )

        raw = response.json()

        data_list = (
            raw
            if isinstance(raw, list)
            else [raw]
        )

        results = []

        for index, item in enumerate(
            data_list
        ):
            if index >= len(cities):
                break

            current = item.get(
                "current",
                {}
            )

            code = current.get(
                "weather_code"
            )

            temp = current.get(
                "temperature_2m"
            )

            status = "Berawan"
            icon = "fa-cloud"
            anim = "float"

            if code in [0, 1]:
                status = "Cerah"
                icon = "fa-sun"
                anim = "spin-slow"

            elif code in [51, 61, 80]:
                status = "Hujan"
                icon = "fa-cloud-rain"
                anim = "bounce"

            results.append({
                "kota": cities[index]["name"],
                "suhu": (
                    round(temp)
                    if isinstance(
                        temp,
                        (int, float)
                    )
                    else "-"
                ),
                "cuaca": status,
                "icon": icon,
                "anim": anim
            })

        WEATHER_CACHE = results
        WEATHER_LAST_FETCH = now_timestamp()

        return results

    except Exception as exc:
        print(
            "WEATHER WARNING:",
            exc
        )

        return [
            {
                "kota": city["name"],
                "suhu": "-",
                "cuaca": "Tidak tersedia",
                "icon": "fa-cloud",
                "anim": ""
            }
            for city in cities
        ]


# =========================================================
# 11. EWS
# =========================================================

def smart_convert_cm(value):
    try:
        number = float(value)

        if (
            number != 0
            and number < 50
        ):
            return f"{number * 100:.0f}"

        return f"{number:.0f}"

    except Exception:
        return "0"


def normalize_dam_data(raw_data):
    result = []

    for item in raw_data:
        try:
            latest = (
                item.get(
                    "latest_debit_report",
                    {}
                )
                or {}
            )

            name = (
                item.get("dam_name")
                or item.get("nama")
                or "Infrastruktur Bendungan"
            )

            siaga = smart_convert_cm(
                item.get("siaga", 0)
            )

            awas = smart_convert_cm(
                item.get("awas", 0)
            )

            if float(siaga) == 0:
                siaga = "200"

            if float(awas) == 0:
                awas = "300"

            raw_tma = (
                latest.get("limpas")
                if latest
                else (
                    item.get("tma")
                    or item.get("siap")
                    or 0
                )
            )

            tma = smart_convert_cm(
                raw_tma
            )

            result.append({
                "name": name,
                "tma": tma,
                "siaga": siaga,
                "awas": awas,
                "inflow": latest.get(
                    "debit",
                    0
                ),
                "outflow": latest.get(
                    "debit_ke_saluran_induk",
                    0
                ),
                "status": (
                    latest.get("status")
                    or item.get(
                        "status_alert"
                    )
                    or "Operasional Normal"
                ),
                "cuaca": latest.get(
                    "cuaca",
                    "Berawan"
                ),
                "petugas": (
                    f"ID: {latest.get('pob_id', 'Unit')}"
                ),
                "updated_at": (
                    "Pembaruan Terakhir WIB"
                ),
                "lokasi": item.get(
                    "river_name",
                    "Jawa Tengah"
                )
            })

        except Exception:
            continue

    return result


def fetch_ews_data():
    try:
        response = requests.get(
            "https://siagakranji.my.id/data/latest_dams.json",
            params={
                "t": int(
                    now_timestamp()
                )
            },
            headers={
                "User-Agent": "KTVDI/1.0",
                "Accept": "application/json"
            },
            timeout=3,
            verify=False
        )

        if response.status_code != 200:
            return []

        raw = response.json()

        if isinstance(raw, dict):
            raw_list = (
                raw.get("data")
                or raw.get("result")
                or []
            )
        elif isinstance(raw, list):
            raw_list = raw
        else:
            raw_list = []

        return normalize_dam_data(
            raw_list
        )

    except Exception as exc:
        print(
            "EWS WARNING:",
            exc
        )

        return []


# =========================================================
# 12. HOME
# =========================================================

@app.route("/")
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
                if not isinstance(
                    prov,
                    dict
                ):
                    continue

                stats["wilayah"] += len(
                    prov
                )

                for wilayah in prov.values():
                    if not isinstance(
                        wilayah,
                        dict
                    ):
                        continue

                    stats["mux"] += len(
                        wilayah
                    )

                    for item in wilayah.values():
                        if (
                            isinstance(
                                item,
                                dict
                            )
                            and "siaran" in item
                        ):
                            stats["channel"] += len(
                                item["siaran"]
                            )

            last_str = now_wib().strftime(
                "%d-%m-%Y"
            )

        except Exception as exc:
            print(
                "HOME FIREBASE WARNING:",
                exc
            )

    return render_template(
        "index.html",
        stats=stats,
        last_updated_time=last_str
    )


# =========================================================
# 13. AUTHENTICATION
# =========================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():
    if request.method == "POST":

        username = normalize_input(
            request.form.get("username")
        )

        password = hash_password(
            request.form.get("password")
        )

        if not ref:
            return render_template(
                "login.html",
                error="Database tidak terhubung."
            )

        try:
            users = (
                ref.child("users").get()
                or {}
            )

            target_user = None
            target_uid = None

            for uid, data in users.items():

                if not isinstance(
                    data,
                    dict
                ):
                    continue

                if (
                    normalize_input(uid)
                    == username
                    or
                    normalize_input(
                        data.get("email")
                    )
                    == username
                ):
                    target_user = data
                    target_uid = uid
                    break

            if (
                target_user
                and target_user.get("password")
                == password
            ):
                session.permanent = True

                session["user"] = target_uid

                session["nama"] = (
                    target_user.get(
                        "nama",
                        "Pengguna Terdaftar"
                    )
                )

                return redirect(
                    url_for("dashboard")
                )

        except Exception as exc:
            print(
                "LOGIN ERROR:",
                exc
            )

            return render_template(
                "login.html",
                error="Terjadi kesalahan server."
            )

        return render_template(
            "login.html",
            error="Kredensial tidak valid."
        )

    return render_template(
        "login.html"
    )


@app.route("/logout")
def logout():
    session.clear()

    return redirect(
        url_for("login")
    )


@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if request.method == "POST":

        username = normalize_input(
            request.form.get("username")
        )

        email = normalize_input(
            request.form.get("email")
        )

        nama = (
            request.form.get("nama")
            or ""
        ).strip()

        password = request.form.get(
            "password"
        )

        if not ref:
            return (
                "Database tidak terhubung.",
                500
            )

        try:
            users = (
                ref.child("users").get()
                or {}
            )

            if username in users:
                flash(
                    "Nama pengguna telah terdaftar.",
                    "error"
                )

                return render_template(
                    "register.html"
                )

            otp = str(
                random.randint(
                    100000,
                    999999
                )
            )

            ref.child(
                f"pending_users/{username}"
            ).set({
                "nama": nama,
                "email": email,
                "password": hash_password(
                    password
                ),
                "otp": otp,
                "expiry": (
                    now_timestamp() + 60
                )
            })

            subject, body = get_email_template(
                "REGISTER",
                nama,
                otp
            )

            mail.send(
                Message(
                    subject,
                    recipients=[email],
                    body=body
                )
            )

            session[
                "pending_username"
            ] = username

            return redirect(
                url_for(
                    "verify_register"
                )
            )

        except Exception as exc:
            print(
                "REGISTER ERROR:",
                exc
            )

            flash(
                "Kegagalan proses registrasi.",
                "error"
            )

    return render_template(
        "register.html"
    )


@app.route(
    "/verify-register",
    methods=["GET", "POST"]
)
def verify_register():

    username = session.get(
        "pending_username"
    )

    if not username:
        return redirect(
            url_for("register")
        )

    if request.method == "POST":

        try:
            pending = (
                ref.child(
                    f"pending_users/{username}"
                ).get()
            )

            if not pending:
                return redirect(
                    url_for("register")
                )

            if (
                now_timestamp()
                >
                float(
                    pending.get(
                        "expiry",
                        0
                    )
                )
            ):
                flash(
                    "Kode verifikasi telah kedaluwarsa.",
                    "error"
                )

                ref.child(
                    f"pending_users/{username}"
                ).delete()

                return redirect(
                    url_for("register")
                )

            otp = (
                request.form.get("otp")
                or ""
            ).strip()

            if (
                str(
                    pending.get("otp")
                ).strip()
                == otp
            ):
                ref.child(
                    f"users/{username}"
                ).set({
                    "nama": pending.get(
                        "nama",
                        ""
                    ),
                    "email": pending.get(
                        "email",
                        ""
                    ),
                    "password": pending.get(
                        "password",
                        ""
                    )
                })

                ref.child(
                    f"pending_users/{username}"
                ).delete()

                session.pop(
                    "pending_username",
                    None
                )

                flash(
                    "Registrasi berhasil.",
                    "success"
                )

                return redirect(
                    url_for("login")
                )

            flash(
                "Kode verifikasi tidak tepat.",
                "error"
            )

        except Exception as exc:
            print(
                "VERIFY ERROR:",
                exc
            )

            flash(
                "Terjadi kesalahan server.",
                "error"
            )

    return render_template(
        "verify-register.html",
        username=username
    )


@app.route("/dashboard")
def dashboard():

    if "user" not in session:
        return redirect(
            url_for("login")
        )

    data = {}

    if ref:
        try:
            data = (
                ref.child("provinsi").get()
                or {}
            )
        except Exception:
            data = {}

    return render_template(
        "dashboard.html",
        name=session.get(
            "nama"
        ),
        provinsi_list=list(
            data.values()
        )
    )


# =========================================================
# 14. NEWS
# =========================================================

@app.route("/berita")
def berita_page():

    entries = get_news_entries()

    page = request.args.get(
        "page",
        1,
        type=int
    )

    page = max(
        1,
        page
    )

    per_page = 9

    start = (
        page - 1
    ) * per_page

    end = (
        start + per_page
    )

    current = entries[
        start:end
    ]

    for article in current:

        published = article.get(
            "published_parsed"
        )

        if published:

            article["formatted_date"] = (
                format_indo_date(
                    published
                )
            )

            article[
                "time_since_published"
            ] = time_since_published(
                published
            )

        else:

            article[
                "formatted_date"
            ] = "Waktu Tidak Tersedia"

            article[
                "time_since_published"
            ] = "Terkini"

    total_pages = max(
        1,
        (
            len(entries)
            + per_page
            - 1
        ) // per_page
    )

    return render_template(
        "berita.html",
        articles=current,
        page=page,
        total_pages=total_pages
    )


@app.route("/api/news-ticker")
def news_ticker():

    return jsonify([
        item.get(
            "title",
            ""
        )
        for item in get_news_entries()
    ])


# =========================================================
# 15. EWS
# =========================================================

@app.route("/ews-jateng")
def ews_jateng_page():

    return render_template(
        "ews-jateng.html",
        dams=fetch_ews_data(),
        cuaca_list=get_cuaca_10_kota()
    )


# =========================================================
# 16. CHATBOT
# =========================================================

@app.route(
    "/api/chat",
    methods=["POST"]
)
def chatbot_api():

    try:
        payload = (
            request.get_json(
                silent=True
            )
            or {}
        )

        user_message = (
            payload.get("prompt")
            or ""
        ).strip()

        if not user_message:
            return jsonify({
                "response": (
                    "Silakan masukkan pertanyaan."
                )
            })

        model = get_gemini_model()

        if not model:
            return jsonify({
                "response": (
                    "Layanan AI sedang tidak tersedia."
                )
            })

        prompt = (
            MODI_PROMPT
            + "\nPengguna: "
            + user_message
            + "\nMODI:"
        )

        result = model.generate_content(
            prompt
        )

        response_text = getattr(
            result,
            "text",
            None
        )

        if not response_text:
            raise RuntimeError(
                "Gemini tidak mengembalikan teks."
            )

        return jsonify({
            "response": response_text
        })

    except Exception as exc:

        print(
            "CHAT ERROR:",
            exc
        )

        return jsonify({
            "response": (
                "Mohon maaf, layanan AI "
                "sedang mengalami gangguan."
            )
        })


# =========================================================
# 17. NETWORK MONITORING
# =========================================================

@app.route("/network")
def network_page():

    if "user" not in session:
        return redirect(
            url_for("login")
        )

    return render_template(
        "network.html"
    )


# ---------------------------------------------------------
# CLIENT NETWORK MERGE
# ---------------------------------------------------------

@app.route(
    "/api/network-client-merge",
    methods=["POST"]
)
def network_client_merge():

    try:
        data = (
            request.get_json(
                silent=True
            )
            or {}
        )

        public_ip = (
            data.get("public_ip")
            or get_client_ip()
        )

        client = {
            "public_ip": public_ip,
            "browser": data.get(
                "browser"
            ),
            "os": data.get(
                "os"
            ),
            "connection_type": data.get(
                "connection_type"
            ),
            "downlink": data.get(
                "downlink"
            ),
            "rtt": data.get(
                "rtt"
            ),
            "save_data": data.get(
                "save_data"
            )
        }

        return jsonify({
            "status": "success",
            "message": "Data client diterima.",
            "client": client
        })

    except Exception as exc:

        print(
            "CLIENT NETWORK ERROR:",
            exc
        )

        return jsonify({
            "status": "error",
            "message": (
                "Data jaringan client gagal diproses."
            ),
            "client": {}
        }), 200


# ---------------------------------------------------------
# NETWORK DATA
# ---------------------------------------------------------

def build_network_response():
    """
    Response kompatibel dengan network.html.

    Penting:
    Data yang tidak dapat diperoleh dari Vercel
    dikembalikan sebagai null / unavailable.

    Jangan mengarang SSID, MAC, gateway,
    perangkat LAN, atau Speedtest.
    """

    client_ip = get_client_ip()

    return {
        "status": "success",

        "message": (
            "Network API berjalan dalam "
            "mode serverless."
        ),

        "local": {
            "ip": None,
            "network": None,
            "prefix": None,
            "hostname": None
        },

        "router": {
            "ip": None,
            "mac": None,
            "vendor": None,
            "hostname": None,
            "online": None,
            "latency_ms": None
        },

        "wifi": {
            "available": False,
            "connected": None,
            "ssid": None,
            "band": None,
            "channel": None,
            "signal_percent": None,
            "signal_dbm": None,
            "interface": None,
            "radio_type": None,
            "receive_mbps": None,
            "transmit_mbps": None
        },

        "speedtest": {
            "success": False,
            "available": False,
            "download_mbps": None,
            "upload_mbps": None,
            "ping_ms": None,
            "packet_loss_percent": None,
            "server": None,
            "isp": None,
            "source": "Tidak dijalankan di Vercel",
            "message": (
                "Speedtest aktual tidak dijalankan "
                "oleh serverless backend."
            )
        },

        "devices": [],

        "clients_count": 0,

        "known_devices_count": 0,

        "online_count": 0,

        "client": {
            "public_ip": client_ip or None
        },

        "platform": (
            "Vercel Serverless"
        ),

        "scan_time": (
            now_wib().strftime(
                "%d-%m-%Y %H:%M:%S"
            )
        ),

        "capabilities": {
            "wifi_local": False,
            "arp_scan": False,
            "lan_scan": False,
            "gateway_detection": False,
            "speedtest": False,
            "public_ip": True
        }
    }


@app.route("/api/network-data")
def network_data_api():

    try:
        return jsonify(
            build_network_response()
        )

    except Exception as exc:

        print(
            "NETWORK API ERROR:",
            exc
        )

        # Sangat penting:
        # Jangan sampai frontend mendapat
        # HTML 500 dari endpoint JSON.

        return jsonify({
            "status": "error",
            "message": (
                "Network monitoring sementara "
                "tidak tersedia."
            ),
            "devices": [],
            "router": {},
            "wifi": {},
            "speedtest": {}
        }), 200


# ---------------------------------------------------------
# NETWORK RESCAN
# ---------------------------------------------------------

@app.route("/api/network-rescan")
def network_rescan():

    return network_data_api()


# =========================================================
# 18. HEALTH CHECK
# =========================================================

@app.route("/api/health")
def health_check():

    return jsonify({
        "status": "ok",
        "application": "KTVDI",
        "platform": "Vercel Serverless",
        "python": platform.python_version(),
        "time": now_wib().isoformat(),
        "firebase": (
            firebase_admin._apps
            != {}
        )
    })


# =========================================================
# 19. ERROR HANDLERS
# =========================================================

@app.errorhandler(404)
def not_found(error):

    if request.path.startswith("/api/"):
        return jsonify({
            "status": "error",
            "message": "Endpoint tidak ditemukan."
        }), 404

    return (
        render_template(
            "404.html"
        ),
        404
    )


@app.errorhandler(500)
def internal_error(error):

    print(
        "INTERNAL SERVER ERROR:",
        error
    )

    if request.path.startswith("/api/"):
        return jsonify({
            "status": "error",
            "message": (
                "Terjadi kesalahan internal server."
            )
        }), 200

    return (
        "Terjadi kesalahan internal server.",
        500
    )


# =========================================================
# 20. LOCAL DEVELOPMENT
# =========================================================

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
```
