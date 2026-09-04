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

urllib3.disable_warnings(
    urllib3.exceptions.InsecureRequestWarning
)

load_dotenv()

app = Flask(__name__)

CORS(app)

app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY",
    "change-this-secret-in-env"
)

app.config['SESSION_PERMANENT'] = True

app.config['PERMANENT_SESSION_LIFETIME'] = 86400


# ==========================================
# 2. SISTEM AUTO-MAINTENANCE
# ==========================================

MAINTENANCE_END_DATE = datetime(
    2026,
    2,
    3,
    7,
    0,
    0
)


@app.before_request
def maintenance_interceptor():

    if request.endpoint == 'static':

        return None

    now_wib = (
        datetime.utcnow()
        +
        timedelta(hours=7)
    )

    if now_wib < MAINTENANCE_END_DATE:

        return render_template(
            'maintenance.html'
        ), 503

    return None


# ==========================================
# 2.5. SISTEM TRACKER PENGUNJUNG & LOKASI
# ==========================================

TRACKER_DATA = {

    "date":
        datetime.now(
            pytz.timezone(
                'Asia/Jakarta'
            )
        ).date(),

    "daily_ips":
        set(),

    "online_ips":
        {},

    "ip_locations":
        {}
}


def fetch_and_store_location_sync(ip):

    """
    Pengambilan lokasi disinkronkan dengan batas
    waktu ketat agar Vercel tidak Crash.
    """

    try:

        r = requests.get(

            f"http://ip-api.com/json/{ip}"
            "?fields=city,country,status",

            timeout=1.5

        )

        if r.status_code == 200:

            res = r.json()

            if res.get(
                "status"
            ) == "success":

                TRACKER_DATA[
                    "ip_locations"
                ][ip] = (

                    f"{res.get('city', 'Unknown City')}, "
                    f"{res.get('country', 'Unknown Country')}"

                )

            else:

                TRACKER_DATA[
                    "ip_locations"
                ][ip] = (
                    "Tidak Terdeteksi"
                )

    except Exception:

        TRACKER_DATA[
            "ip_locations"
        ][ip] = (
            "Tidak Terdeteksi"
        )


@app.before_request
def visitor_tracker():

    if (
        request.endpoint
        and
        'static' not in request.endpoint
    ):

        tz = pytz.timezone(
            'Asia/Jakarta'
        )

        today = datetime.now(
            tz
        ).date()

        if (
            TRACKER_DATA["date"]
            !=
            today
        ):

            TRACKER_DATA["date"] = today

            TRACKER_DATA[
                "daily_ips"
            ].clear()

            TRACKER_DATA[
                "ip_locations"
            ].clear()

        user_ip = request.headers.get(
            'X-Forwarded-For',
            request.remote_addr
        )

        if user_ip:

            user_ip = (
                user_ip
                .split(',')[0]
                .strip()
            )

            TRACKER_DATA[
                "daily_ips"
            ].add(
                user_ip
            )

            TRACKER_DATA[
                "online_ips"
            ][user_ip] = (
                time.time()
            )

            if (

                user_ip
                not in
                TRACKER_DATA[
                    "ip_locations"
                ]

                and

                not user_ip.startswith(
                    (
                        '127.',
                        '192.168.',
                        '10.'
                    )
                )

            ):

                TRACKER_DATA[
                    "ip_locations"
                ][user_ip] = (
                    "Mendeteksi Lokasi..."
                )

                fetch_and_store_location_sync(
                    user_ip
                )


# ==========================================
# 3. KONEKSI DATABASE (FIREBASE)
# ==========================================

try:

    if os.environ.get(
        "FIREBASE_PRIVATE_KEY"
    ):

        cred = credentials.Certificate({

            "type":
                "service_account",

            "project_id":
                os.environ.get(
                    "FIREBASE_PROJECT_ID"
                ),

            "private_key_id":
                os.environ.get(
                    "FIREBASE_PRIVATE_KEY_ID"
                ),

            "private_key":
                os.environ.get(
                    "FIREBASE_PRIVATE_KEY"
                ).replace(
                    '\\n',
                    '\n'
                ),

            "client_email":
                os.environ.get(
                    "FIREBASE_CLIENT_EMAIL"
                ),

            "client_id":
                os.environ.get(
                    "FIREBASE_CLIENT_ID"
                ),

            "auth_uri":
                "https://accounts.google.com/o/oauth2/auth",

            "token_uri":
                "https://oauth2.googleapis.com/token",

            "auth_provider_x509_cert_url":
                "https://www.googleapis.com/oauth2/v1/certs",

            "client_x509_cert_url":
                os.environ.get(
                    "FIREBASE_CLIENT_X509_CERT_URL"
                ),

            "universe_domain":
                "googleapis.com"
        })

    else:

        if os.path.exists(
            "credentials.json"
        ):

            cred = credentials.Certificate(
                "credentials.json"
            )

        else:

            cred = None

    if (
        cred
        and
        not firebase_admin._apps
    ):

        firebase_admin.initialize_app(

            cred,

            {
                'databaseURL':
                    os.environ.get(
                        'DATABASE_URL'
                    )
            }
        )

    if firebase_admin._apps:

        ref = db.reference('/')

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
# 4. KONFIGURASI EMAIL (SMTP GMAIL)
# ==========================================

app.config['MAIL_SERVER'] = (
    'smtp.gmail.com'
)

app.config['MAIL_PORT'] = 587

app.config['MAIL_USE_TLS'] = True

app.config['MAIL_USERNAME'] = (
    os.environ.get(
        "MAIL_USERNAME"
    )
)

app.config['MAIL_PASSWORD'] = (
    os.environ.get(
        "MAIL_PASSWORD"
    )
)

app.config['MAIL_DEFAULT_SENDER'] = (
    os.environ.get(
        "MAIL_USERNAME"
    )
)

mail = Mail(
    app
)


# ==========================================
# 5. KONFIGURASI AI (GEMINI)
# ==========================================

GEMINI_KEY = os.environ.get(
    "GEMINI_API_KEY",
    ""
)


def get_gemini_model():

    try:

        genai.configure(
            api_key=GEMINI_KEY
        )

        safety_settings = [

            {
                "category":
                    "HARM_CATEGORY_HARASSMENT",

                "threshold":
                    "BLOCK_NONE"
            },

            {
                "category":
                    "HARM_CATEGORY_HATE_SPEECH",

                "threshold":
                    "BLOCK_NONE"
            },

            {
                "category":
                    "HARM_CATEGORY_SEXUALLY_EXPLICIT",

                "threshold":
                    "BLOCK_NONE"
            },

            {
                "category":
                    "HARM_CATEGORY_DANGEROUS_CONTENT",

                "threshold":
                    "BLOCK_NONE"
            }
        ]

        return genai.GenerativeModel(
            "gemini-1.5-flash",
            safety_settings=safety_settings
        )

    except Exception as e:

        print(
            "ERROR: Konfigurasi model Gemini mengalami "
            f"kegagalan. Rincian: {e}"
        )

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

def hash_password(pw):

    return hashlib.sha256(
        pw.encode()
    ).hexdigest()


def normalize_input(text):

    return (
        text.strip().lower()
        if text
        else
        ""
    )


def format_indo_date(time_struct):

    if not time_struct:

        return datetime.now().strftime(
            "%A, %d %B %Y - %H:%M WIB"
        )

    try:

        dt = datetime.fromtimestamp(
            time.mktime(
                time_struct
            )
        )

        return dt.strftime(
            "%A, %d %B %Y - %H:%M WIB"
        )

    except:

        return (
            "Informasi Waktu Tidak Tersedia"
        )


def get_email_template(
    action_type,
    nama_user,
    otp_code
):

    waktu = datetime.now().strftime(
        "%d %B %Y, Pukul %H:%M WIB"
    )

    if action_type == "REGISTER":

        subject = (
            f"🔐 Verifikasi Keamanan: Pendaftaran Akun KTVDI "
            f"[{otp_code}]"
        )

        title = (
            "Verifikasi Pendaftaran Akun Baru"
        )

        desc = (
            "Sistem kami mendeteksi permintaan pendaftaran "
            "akun baru di portal Komunitas TV Digital Indonesia "
            "(KTVDI) yang terafiliasi dengan alamat surel ini."
        )

        warning = (
            "Apabila Anda tidak merasa menginisiasi pendaftaran "
            "ini, harap abaikan pesan ini. Kode OTP ini bersifat "
            "sangat RAHASIA."
        )

    elif action_type == "RESET":

        subject = (
            f"⚠️ Peringatan Keamanan: Permintaan Atur Ulang "
            f"Kata Sandi [{otp_code}]"
        )

        title = (
            "Permintaan Atur Ulang Kata Sandi"
        )

        desc = (
            "Sistem kami menerima instruksi untuk mengatur ulang "
            "kata sandi (Reset Password) pada akun KTVDI Anda."
        )

        warning = (
            "JANGAN MEMBERIKAN kode ini kepada pihak mana pun, "
            "termasuk staf atau administrator KTVDI. Jika "
            "permintaan ini bukan dari Anda, segera lakukan "
            "pengamanan akun."
        )

    else:

        subject = (
            "Pemberitahuan Sistem KTVDI"
        )

        title = (
            "Notifikasi Sistem"
        )

        desc = (
            "Terdapat pembaruan informasi terkait akun Anda."
        )

        warning = ""

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


def get_hijri_date_string():

    HIJRI_OFFSET = -1

    try:

        tz_jakarta = pytz.timezone(
            'Asia/Jakarta'
        )

        now_wib = (
            datetime.now(
                tz_jakarta
            )
            +
            timedelta(
                days=HIJRI_OFFSET
            )
        )

        url = (
            "https://api.aladhan.com/v1/gToH"
            f"?date={now_wib.strftime('%d-%m-%Y')}"
        )

        r = requests.get(
            url,
            timeout=3
        )

        if r.status_code == 200:

            data = (
                r.json()['data']['hijri']
            )

            indo_months = {

                "Muharram":
                    "Muharam",

                "Safar":
                    "Safar",

                "Rabi' al-awwal":
                    "Rabiul Awal",

                "Rabi' al-thani":
                    "Rabiul Akhir",

                "Jumada al-awwal":
                    "Jumadil Awal",

                "Jumada al-thani":
                    "Jumadil Akhir",

                "Rajab":
                    "Rajab",

                "Sha'ban":
                    "Syakban",

                "Ramadan":
                    "Ramadan",

                "Shawwal":
                    "Syawal",

                "Dhu al-Qi'dah":
                    "Zulkaidah",

                "Dhu al-Hijjah":
                    "Zulhijah"
            }

            d = data[
                'day'
            ].lstrip('0')

            m = indo_months.get(
                data[
                    'month'
                ]['en'],
                data[
                    'month'
                ]['en']
            )

            y = data[
                'year'
            ]

            return (
                f"{d} {m} {y} H"
            )

    except Exception:

        pass

    return (
        "Tanggal Hijriah Tidak Tersedia"
    )


# ==========================================
# CACHE UNTUK BERITA
# ==========================================

NEWS_CACHE = []

NEWS_LAST_FETCH = 0


def get_news_entries():

    global NEWS_CACHE
    global NEWS_LAST_FETCH

    if (

        len(
            NEWS_CACHE
        ) > 0

        and

        (
            time.time()
            -
            NEWS_LAST_FETCH
            <
            30
        )

    ):

        return NEWS_CACHE

    all_news = []

    headers = {
        'User-Agent':
            'Mozilla/5.0'
    }

    # --------------------------------------
    # BMKG UPDATE
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

            gempa = root.find(
                'gempa'
            )

            if gempa is not None:

                wilayah = gempa.find(
                    'Wilayah'
                ).text

                magnitude = gempa.find(
                    'Magnitude'
                ).text

                potensi = gempa.find(
                    'Potensi'
                ).text

                shakemap = gempa.find(
                    'Shakemap'
                ).text

                all_news.append({

                    'title':
                        f"INFORMASI GEMPA BMKG: "
                        f"Magnitudo {magnitude} di "
                        f"{wilayah} ({potensi})",

                    'link':
                        "https://warning.bmkg.go.id/",

                    'published_parsed':
                        datetime.now().timetuple(),

                    'source_name':
                        'BMKG Resmi',

                    'image':
                        f"https://data.bmkg.go.id/"
                        f"DataMKG/TEWS/{shakemap}"
                })

    except Exception:

        pass

    # --------------------------------------
    # RSS
    # --------------------------------------

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

                res = requests.get(
                    url,
                    headers=headers,
                    timeout=4
                )

                if res.status_code == 200:

                    return (
                        url,
                        feedparser.parse(
                            res.content
                        )
                    )

            except:

                return (
                    url,
                    None
                )

            return (
                url,
                None
            )

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(
                sources
            )
        ) as pool:

            futures = [

                pool.submit(
                    fetch_feed,
                    url
                )

                for url in sources
            ]

            for future in concurrent.futures.as_completed(
                futures
            ):

                url, feed = future.result()

                if feed and feed.entries:

                    for entry in feed.entries[:20]:

                        if 'kompas.tv' in url:

                            source_name = 'Kompas TV'

                        elif 'setneg' in url:

                            source_name = 'Sekretariat Negara'

                        elif 'liputan6' in url:

                            source_name = 'Liputan 6'

                        elif 'tribunnews' in url:

                            source_name = 'Tribunnews'

                        elif 'cnnindonesia' in url:

                            source_name = 'CNN Indonesia'

                        elif 'cnbcindonesia' in url:

                            source_name = 'CNBC Indonesia'

                        elif 'antara' in url:

                            source_name = 'Antara News'

                        elif 'sindonews' in url:

                            source_name = 'Sindonews'

                        else:

                            source_name = (
                                url
                                .split('.')[1]
                                .capitalize()
                            )

                        entry[
                            'source_name'
                        ] = source_name

                        img_url = None

                        if (

                            'media_content'
                            in entry

                            and
                            entry.media_content

                        ):

                            img_url = (
                                entry
                                .media_content[0]['url']
                            )

                        if (

                            not img_url
                            and
                            'links'
                            in entry

                        ):

                            for link in entry.links:

                                if link.get(
                                    'type',
                                    ''
                                ).startswith(
                                    'image'
                                ):

                                    img_url = (
                                        link.get(
                                            'href'
                                        )
                                    )

                                    break

                        if (

                            not img_url
                            and
                            'description'
                            in entry

                        ):

                            match = re.search(
                                r'src="([^"]+)"',
                                entry.description
                            )

                            if match:

                                img_url = (
                                    match.group(1)
                                )

                        if (

                            not img_url
                            and
                            'enclosures'
                            in entry

                        ):

                            for enc in entry.enclosures:

                                if enc.get(
                                    'type',
                                    ''
                                ).startswith(
                                    'image'
                                ):

                                    img_url = (
                                        enc.get(
                                            'href'
                                        )
                                    )

                                    break

                        entry[
                            'image'
                        ] = img_url

                        all_news.append(
                            entry
                        )

        all_news.sort(

            key=lambda x:
                x.published_parsed
                if x.get(
                    'published_parsed'
                )
                else
                time.gmtime(0),

            reverse=True

        )

    except:

        pass

    if not all_news:

        if NEWS_CACHE:

            return NEWS_CACHE

        t = datetime.now().timetuple()

        return [{

            'title':
                'Pusat Informasi KTVDI Beroperasi Normal',

            'link':
                '#',

            'published_parsed':
                t,

            'source_name':
                'Sistem Internal',

            'image':
                None
        }]

    NEWS_CACHE = (
        all_news[:150]
    )

    NEWS_LAST_FETCH = (
        time.time()
    )

    return NEWS_CACHE


def time_since_published(
    published_time
):

    try:

        now = datetime.now()

        pt = datetime(
            *published_time[:6]
        )

        diff = now - pt

        if diff.days > 0:

            return (
                f"{diff.days} hari yang lalu"
            )

        if diff.seconds > 3600:

            return (
                f"{diff.seconds // 3600} jam yang lalu"
            )

        if diff.seconds > 60:

            return (
                f"{diff.seconds // 60} menit yang lalu"
            )

        return "Terbaru"

    except:

        return (
            "Waktu tidak dapat dipastikan"
        )


def get_quote_religi():

    return {

        "muslim": [

            "Maka dirikanlah shalat... "
            "(QS. An-Nisa: 103)",

            "Hindari perbuatan curang "
            "dalam bentuk apa pun.",

            "Manusia terbaik adalah yang "
            "memberikan manfaat bagi sesamanya."
        ],

        "universal": [

            "Integritas adalah landasan "
            "dari setiap tindakan yang benar.",

            "Kedamaian global bermula "
            "dari kedamaian personal.",

            "Kejujuran adalah nilai tukar "
            "universal yang diakui secara global."
        ]
    }


def get_smart_fallback_response(
    text
):

    return (
        "Mohon maaf, server kecerdasan buatan kami "
        "saat ini sedang memproses volume antrean "
        "yang tinggi. Kami memohon kesediaan Anda "
        "untuk mencoba kembali dalam beberapa saat."
    )


KEMENAG_KOTA_CACHE = []

KEMENAG_LAST_FETCH = 0


def fetch_kemenag_kota():

    global KEMENAG_KOTA_CACHE
    global KEMENAG_LAST_FETCH

    if (

        len(
            KEMENAG_KOTA_CACHE
        ) > 50

        and

        (
            time.time()
            -
            KEMENAG_LAST_FETCH
            <
            86400
        )

    ):

        return KEMENAG_KOTA_CACHE

    try:

        r = requests.get(
            "https://api.myquran.com/v2/sholat/kota/semua",
            timeout=8
        )

        if r.status_code == 200:

            data = r.json()

            if (
                data.get('status')
                and
                'data' in data
            ):

                all_cities = [

                    {
                        "id":
                            item['id'],

                        "nama":
                            item['lokasi'].title()
                    }

                    for item
                    in data['data']
                ]

                KEMENAG_KOTA_CACHE = sorted(

                    all_cities,

                    key=lambda x:
                        x['nama']

                )

                KEMENAG_LAST_FETCH = (
                    time.time()
                )

                return KEMENAG_KOTA_CACHE

    except Exception:

        pass

    return [

        {
            "id":
                "1301",

            "nama":
                "Kota Jakarta"
        },

        {
            "id":
                "1604",

            "nama":
                "Kota Semarang"
        },

        {
            "id":
                "1638",

            "nama":
                "Kota Surabaya"
        },

        {
            "id":
                "0418",

            "nama":
                "Kota Medan"
        },

        {
            "id":
                "1205",

            "nama":
                "Kota Bandung"
        }

    ]


# ==========================================
# 7. LOGIKA EWS & CUACA
# ==========================================

def smart_convert_cm(
    value
):

    try:

        val_float = float(
            value
        )

        if (

            val_float != 0

            and

            val_float < 50

        ):

            return f"{val_float * 100:.0f}"

        return f"{val_float:.0f}"

    except:

        return "0"


def get_cuaca_10_kota():

    cities = [

        {
            "name":
                "Semarang",

            "lat":
                -6.9667,

            "lon":
                110.4167
        },

        {
            "name":
                "Surakarta",

            "lat":
                -7.5761,

            "lon":
                110.8294
        },

        {
            "name":
                "Tegal",

            "lat":
                -6.8694,

            "lon":
                109.1403
        },

        {
            "name":
                "Pekalongan",

            "lat":
                -6.8886,

            "lon":
                109.6753
        },

        {
            "name":
                "Salatiga",

            "lat":
                -7.3305,

            "lon":
                110.5084
        },

        {
            "name":
                "Magelang",

            "lat":
                -7.4706,

            "lon":
                110.2178
        },

        {
            "name":
                "Purwokerto",

            "lat":
                -7.4245,

            "lon":
                109.2302
        },

        {
            "name":
                "Cilacap",

            "lat":
                -7.7279,

            "lon":
                109.0077
        },

        {
            "name":
                "Kudus",

            "lat":
                -6.8048,

            "lon":
                110.8405
        },

        {
            "name":
                "Pati",

            "lat":
                -6.7550,

            "lon":
                111.0380
        }

    ]

    lats = ",".join(

        [
            str(c['lat'])
            for c in cities
        ]
    )

    lons = ",".join(

        [
            str(c['lon'])
            for c in cities
        ]
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

                if isinstance(
                    data,
                    list
                )

                else

                [data]

                if 'current' in data

                else

                []

            )

            for i, item in enumerate(
                data_list
            ):

                if i >= len(
                    cities
                ):

                    break

                code = item[
                    'current'
                ]['weather_code']

                temp = item[
                    'current'
                ]['temperature_2m']

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

                    "kota":
                        cities[i]['name'],

                    "suhu":
                        round(temp),

                    "cuaca":
                        status,

                    "icon":
                        icon,

                    "anim":
                        anim
                })

    except:

        pass

    if not results:

        for c in cities:

            results.append({

                "kota":
                    c['name'],

                "suhu":
                    "-",

                "cuaca":
                    "Tidak Tersedia",

                "icon":
                    "fa-cloud",

                "anim":
                    ""
            })

    return results


def normalize_dam_data(
    raw_data
):

    clean_data = []

    for item in raw_data:

        try:

            latest = item.get(
                'latest_debit_report',
                {}
            )

            if not isinstance(
                latest,
                dict
            ):

                latest = {}

            name = (

                item.get(
                    'dam_name'
                )

                or

                item.get(
                    'nama'
                )

                or

                item.get(
                    'name'
                )

                or

                "Infrastruktur Bendungan"
            )

            siaga_val = item.get(
                'siaga',
                0
            )

            awas_val = item.get(
                'awas',
                0
            )

            siaga_cm = smart_convert_cm(
                siaga_val
            )

            awas_cm = smart_convert_cm(
                awas_val
            )

            if float(
                siaga_cm
            ) == 0:

                siaga_cm = "200"

            if float(
                awas_cm
            ) == 0:

                awas_cm = "300"

            raw_tma = (

                latest.get(
                    'limpas'
                )

                if latest

                else (

                    item.get('tma')
                    or
                    item.get('siap')
                    or
                    0

                )
            )

            tma_cm = smart_convert_cm(
                raw_tma
            )

            raw_time = (

                latest.get(
                    'created_at'
                )

                or

                item.get(
                    'updated_at'
                )
            )

            waktu_display = (
                "Pembaruan Terakhir"
            )

            if raw_time:

                try:

                    clean_str = (

                        str(
                            raw_time
                        )
                        .split('.')[0]
                        .replace(
                            'Z',
                            ''
                        )

                    )

                    dt_utc = datetime.strptime(
                        clean_str,
                        "%Y-%m-%dT%H:%M:%S"
                    )

                    dt_wib = (
                        dt_utc
                        +
                        timedelta(
                            hours=7
                        )
                    )

                    waktu_display = (
                        dt_wib.strftime(
                            "%d-%m-%Y %H:%M"
                        )
                    )

                except:

                    waktu_display = (
                        str(
                            raw_time
                        )[:16]
                        .replace(
                            'T',
                            ' '
                        )
                    )

            status = (

                latest.get(
                    'status'
                )

                or

                item.get(
                    'status_alert'
                )

                or

                'Operasional Normal'
            )

            pob = latest.get(
                'pob_id'
            )

            petugas = (

                f"ID Petugas: {pob}"

                if pob

                else

                "Unit Pemantauan"
            )

            cuaca_lokal = latest.get(
                'cuaca',
                'Berawan'
            )

            dam = {

                'name':
                    name,

                'tma':
                    tma_cm,

                'siaga':
                    siaga_cm,

                'awas':
                    awas_cm,

                'inflow':
                    latest.get(
                        'debit',
                        0
                    ),

                'outflow':
                    latest.get(
                        'debit_ke_saluran_induk',
                        0
                    ),

                'status':
                    status,

                'cuaca':
                    cuaca_lokal,

                'petugas':
                    petugas,

                'updated_at':
                    waktu_display +
                    " WIB",

                'lokasi':
                    (
                        item.get(
                            'river_name'
                        )

                        or

                        item.get(
                            'regency_name'
                        )

                        or

                        'Jawa Tengah'
                    )
            }

            clean_data.append(
                dam
            )

        except:

            continue

    return clean_data


def fetch_ews_data():

    headers = {

        'User-Agent':
            'Mozilla/5.0',

        'Accept':
            'application/json'
    }

    try:

        ts = int(
            time.time()
            *
            1000
        )

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

                data.get(
                    'data'
                )

                or

                data.get(
                    'result'
                )

                or

                (
                    data

                    if isinstance(
                        data,
                        list
                    )

                    else

                    []
                )
            )

            if raw_list:

                return normalize_dam_data(
                    raw_list
                )

    except:

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
                'data',
                []
            )

            return normalize_dam_data(
                raw_list
            )

    except:

        pass

    return []


# ==========================================
# 8. ROUTES & CONTROLLERS
# ==========================================

@app.route(
    "/",
    methods=['GET']
)
def home():

    stats = {

        'wilayah':
            0,

        'mux':
            0,

        'channel':
            0
    }

    last_str = "-"

    if ref:

        try:

            siaran = (
                ref.child(
                    'siaran'
                ).get()
                or
                {}
            )

            for prov in siaran.values():

                if isinstance(
                    prov,
                    dict
                ):

                    stats[
                        'wilayah'
                    ] += len(
                        prov
                    )

                    for wil in prov.values():

                        if isinstance(
                            wil,
                            dict
                        ):

                            stats[
                                'mux'
                            ] += len(
                                wil
                            )

                            for d in wil.values():

                                if (
                                    'siaran'
                                    in
                                    d
                                ):

                                    stats[
                                        'channel'
                                    ] += len(
                                        d[
                                            'siaran'
                                        ]
                                    )

            last_str = datetime.now().strftime(
                '%d-%m-%Y'
            )

        except:

            pass

    return render_template(
        'index.html',
        stats=stats,
        last_updated_time=last_str
    )


@app.route(
    '/login',
    methods=['GET', 'POST']
)
def login():

    if request.method == 'POST':

        raw_input = request.form.get(
            'username'
        )

        password = request.form.get(
            'password'
        )

        hashed_pw = hash_password(
            password
        )

        clean_input = normalize_input(
            raw_input
        )

        if not ref:

            return render_template(
                'login.html',
                error=(
                    "Sistem gagal terhubung "
                    "ke pangkalan data utama."
                )
            )

        users = (
            ref.child(
                'users'
            ).get()
            or
            {}
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

                normalize_input(
                    uid
                )
                ==
                clean_input

            ):

                target_user = data

                target_uid = uid

                break

            if (

                normalize_input(
                    data.get(
                        'email'
                    )
                )
                ==
                clean_input

            ):

                target_user = data

                target_uid = uid

                break

        if (

            target_user

            and

            target_user.get(
                'password'
            )
            ==
            hashed_pw

        ):

            session.permanent = True

            session[
                'user'
            ] = target_uid

            session[
                'nama'
            ] = (
                target_user.get(
                    'nama',
                    'Pengguna Terdaftar'
                )
            )

            return redirect(
                url_for(
                    'dashboard'
                )
            )

        return render_template(
            'login.html',
            error=(
                "Kredensial identitas atau "
                "kata sandi yang Anda masukkan "
                "tidak valid."
            )
        )

    return render_template(
        'login.html'
    )


@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if request.method == "POST":

        u = normalize_input(
            request.form.get(
                "username"
            )
        )

        e = normalize_input(
            request.form.get(
                "email"
            )
        )

        n = request.form.get(
            "nama"
        )

        p = request.form.get(
            "password"
        )

        if not ref:

            return (
                "Terjadi galat pada koneksi "
                "basis data. Harap hubungi administrator.",
                500
            )

        users = (
            ref.child(
                "users"
            ).get()
            or
            {}
        )

        if u in users:

            flash(
                "Nama pengguna tersebut telah "
                "terdaftar di dalam sistem.",
                "error"
            )

            return render_template(
                "register.html"
            )

        for uid, data in users.items():

            if (

                normalize_input(
                    data.get(
                        'email'
                    )
                )
                ==
                e

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
            random.randint(
                100000,
                999999
            )
        )

        expiry = (
            time.time()
            +
            60
        )

        ref.child(
            f'pending_users/{u}'
        ).set({

            "nama":
                n,

            "email":
                e,

            "password":
                hash_password(
                    p
                ),

            "otp":
                otp,

            "expiry":
                expiry
        })

        try:

            subject, body = (
                get_email_template(
                    "REGISTER",
                    n,
                    otp
                )
            )

            msg = Message(
                subject,
                recipients=[e]
            )

            msg.body = body

            mail.send(
                msg
            )

            session[
                "pending_username"
            ] = u

            return redirect(
                url_for(
                    "verify_register"
                )
            )

        except:

            flash(
                "Kegagalan transmisi surel. "
                "Pastikan alamat yang diberikan "
                "valid dan aktif.",
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

    u = session.get(
        "pending_username"
    )

    if not u:

        return redirect(
            url_for(
                "register"
            )
        )

    if request.method == "POST":

        p = (
            ref.child(
                f'pending_users/{u}'
            ).get()
        )

        if not p:

            return redirect(
                url_for(
                    "register"
                )
            )

        if time.time() > p.get(
            'expiry',
            0
        ):

            flash(
                "Sesi kode verifikasi telah "
                "berakhir. Silakan lakukan "
                "permohonan ulang.",
                "error"
            )

            ref.child(
                f'pending_users/{u}'
            ).delete()

            return redirect(
                url_for(
                    "register"
                )
            )

        if (

            str(
                p.get(
                    'otp'
                )
            ).strip()

            ==

            request.form.get(
                "otp"
            ).strip()

        ):

            ref.child(
                f'users/{u}'
            ).set({

                "nama":
                    p['nama'],

                "email":
                    p['email'],

                "password":
                    p['password']
            })

            ref.child(
                f'pending_users/{u}'
            ).delete()

            session.pop(
                'pending_username',
                None
            )

            flash(
                "Registrasi telah berhasil "
                "diproses. Silakan masuk.",
                "success"
            )

            return redirect(
                url_for(
                    'login'
                )
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


@app.route(
    "/forgot-password",
    methods=["GET", "POST"]
)
def forgot_password():

    if request.method == "POST":

        email_input = normalize_input(
            request.form.get(
                "identifier"
            )
        )

        users = (
            ref.child(
                "users"
            ).get()
            or
            {}
        )

        found_uid = None

        user_name = "Pengguna"

        for uid, user_data in users.items():

            if (

                isinstance(
                    user_data,
                    dict
                )

                and

                normalize_input(
                    user_data.get(
                        'email'
                    )
                )
                ==
                email_input

            ):

                found_uid = uid

                user_name = user_data.get(
                    'nama',
                    'Pengguna'
                )

                break

        if found_uid:

            otp = str(
                random.randint(
                    100000,
                    999999
                )
            )

            expiry = (
                time.time()
                +
                60
            )

            ref.child(
                f"otp/{found_uid}"
            ).set({

                "email":
                    email_input,

                "otp":
                    otp,

                "expiry":
                    expiry
            })

            try:

                subject, body = (
                    get_email_template(
                        "RESET",
                        user_name,
                        otp
                    )
                )

                msg = Message(
                    subject,
                    recipients=[
                        email_input
                    ]
                )

                msg.body = body

                mail.send(
                    msg
                )

                session[
                    "reset_uid"
                ] = found_uid

                return redirect(
                    url_for(
                        "verify_otp"
                    )
                )

            except:

                pass

    return render_template(
        "forgot-password.html"
    )


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
            url_for(
                "forgot_password"
            )
        )

    if request.method == "POST":

        data = (
            ref.child(
                f"otp/{uid}"
            ).get()
        )

        if not data:

            return redirect(
                url_for(
                    "forgot_password"
                )
            )

        if time.time() > data.get(
            'expiry',
            0
        ):

            flash(
                "Masa berlaku kode verifikasi "
                "telah habis.",
                "error"
            )

            return redirect(
                url_for(
                    "forgot_password"
                )
            )

        if (

            str(
                data.get(
                    "otp"
                )
            ).strip()

            ==

            request.form.get(
                "otp"
            ).strip()

        ):

            session[
                'reset_verified'
            ] = True

            return redirect(
                url_for(
                    "reset_password"
                )
            )

        flash(
            "Kode verifikasi tidak sesuai.",
            "error"
        )

    return render_template(
        "verify-otp.html"
    )


@app.route(
    "/reset-password",
    methods=["GET", "POST"]
)
def reset_password():

    if not session.get(
        'reset_verified'
    ):

        return redirect(
            url_for(
                'login'
            )
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

            "password":
                hash_password(
                    pw
                )
        })

        ref.child(
            f"otp/{uid}"
        ).delete()

        session.clear()

        return redirect(
            url_for(
                'login'
            )
        )

    return render_template(
        "reset-password.html"
    )


@app.route(
    '/logout'
)
def logout():

    session.clear()

    return redirect(
        url_for(
            'login'
        )
    )


@app.route(
    '/berita'
)
def berita_page():

    entries = get_news_entries()

    page = request.args.get(
        'page',
        1,
        type=int
    )

    per_page = 9

    start = (
        page - 1
    ) * per_page

    end = (
        start
        +
        per_page
    )

    current = entries[
        start:end
    ]

    for a in current:

        if (

            'published_parsed' in a

            and

            a['published_parsed']

        ):

            a[
                'formatted_date'
            ] = format_indo_date(
                a[
                    'published_parsed'
                ]
            )

            a[
                'time_since_published'
            ] = time_since_published(
                a[
                    'published_parsed'
                ]
            )

        else:

            a[
                'formatted_date'
            ] = (
                "Data Waktu Tidak Tersedia"
            )

            a[
                'time_since_published'
            ] = "Terkini"

    total_pages = (
        len(entries)
        //
        per_page
    ) + 1

    return render_template(
        'berita.html',
        articles=current,
        page=page,
        total_pages=total_pages
    )


@app.route(
    "/dashboard"
)
def dashboard():

    if 'user' not in session:

        return redirect(
            url_for(
                'login'
            )
        )

    data = (
        ref.child(
            "provinsi"
        ).get()
        or
        {}
    )

    return render_template(
        "dashboard.html",
        name=session.get(
            'nama'
        ),
        provinsi_list=list(
            data.values()
        )
    )


@app.route(
    "/daftar-siaran"
)
def daftar_siaran():

    data = (
        ref.child(
            "provinsi"
        ).get()
        or
        {}
    )

    return render_template(
        "daftar-siaran.html",
        provinsi_list=list(
            data.values()
        )
    )


@app.route(
    "/add_data",
    methods=["GET", "POST"]
)
def add_data():

    if 'user' not in session:

        return redirect(
            url_for(
                'login'
            )
        )

    prov_data = (
        ref.child(
            "provinsi"
        ).get()
        or
        {}
    )

    provinsi_list = (

        list(
            prov_data.values()
        )

        if prov_data

        else

        [
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

                    for ch in s.split(',')

                ],

                "last_updated_by_name":
                    session.get(
                        'nama'
                    ),

                "last_updated_by_username":
                    session.get(
                        'user'
                    ),

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
            ).set(
                data_new
            )

            ref.child(
                f"provinsi/{p}"
            ).set(
                p
            )

            flash(
                "Data berhasil ditambahkan "
                "ke dalam sistem.",
                "success"
            )

            return redirect(
                url_for(
                    'dashboard'
                )
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

    if 'user' not in session:

        return redirect(
            url_for(
                'login'
            )
        )

    curr_data = (
        ref.child(
            f"siaran/{provinsi}/{wilayah}/{mux}"
        ).get()
    )

    if request.method == "POST":

        s = request.form.get(
            'siaran'
        )

        ref.child(
            f"siaran/{provinsi}/{wilayah}/{mux}"
        ).update({

            "siaran": [

                ch.strip()

                for ch in s.split(',')

            ],

            "last_updated_by_name":
                session.get(
                    'nama'
                ),

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
            url_for(
                'dashboard'
            )
        )

    siaran_str = (

        ", ".join(
            curr_data.get(
                'siaran',
                []
            )
        )

        if curr_data

        else

        ""
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

    if 'user' in session:

        try:

            ref.child(
                f"siaran/{provinsi}/{wilayah}/{mux}"
            ).delete()

            return jsonify({

                "status":
                    "success"

            })

        except:

            return jsonify({

                "status":
                    "error"

            })

    return jsonify({

        "status":
            "unauthorized"

    })


@app.route(
    "/get_wilayah"
)
def get_wilayah():

    return jsonify({

        "wilayah":
            list(

                (
                    ref.child(
                        f"siaran/{request.args.get('provinsi')}"
                    ).get()

                    or
                    {}

                ).keys()

            )

    })


@app.route(
    "/get_mux"
)
def get_mux():

    return jsonify({

        "mux":
            list(

                (
                    ref.child(
                        f"siaran/{request.args.get('provinsi')}/"
                        f"{request.args.get('wilayah')}"
                    ).get()

                    or
                    {}

                ).keys()

            )

    })


@app.route(
    "/get_siaran"
)
def get_siaran():

    return jsonify(

        ref.child(
            f"siaran/"
            f"{request.args.get('provinsi')}/"
            f"{request.args.get('wilayah')}/"
            f"{request.args.get('mux')}"
        ).get()

        or
        {}

    )


@app.route(
    '/ews-jateng'
)
def ews_jateng_page():

    dams = fetch_ews_data()

    cuaca_list = get_cuaca_10_kota()

    return render_template(
        'ews-jateng.html',
        dams=dams,
        cuaca_list=cuaca_list
    )


@app.route(
    '/lokasi'
)
def lokasi_page():

    return render_template(
        'lokasi.html'
    )


@app.route(
    '/api/chat',
    methods=['POST']
)
def chatbot_api():

    data = request.get_json()

    user_msg = data.get(
        'prompt',
        ''
    )

    if (

        "bendungan"
        in
        user_msg.lower()

        or

        "banjir"
        in
        user_msg.lower()

    ):

        dams = fetch_ews_data()

        bahaya = [

            f"{d['name']} ({d['status']})"

            for d in dams

            if (

                'awas'
                in
                d['status'].lower()

                or

                'siaga'
                in
                d['status'].lower()

            )

        ]

        if bahaya:

            context = (
                "INSTRUKSI PRIORITAS: Terdeteksi "
                "infrastruktur bendungan dalam status "
                "kewaspadaan tingkat tinggi: "
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
                "tidak sesuai dengan protokol keamanan "
                "standar. Proses dihentikan."
            )

        return jsonify({

            "response":
                teks_balasan

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


@app.route(
    "/jadwal-sholat"
)
def jadwal_sholat_page():

    daftar_kota = fetch_kemenag_kota()

    hijri_today = get_hijri_date_string()

    return render_template(
        "jadwal-sholat.html",
        daftar_kota=daftar_kota,
        quotes=get_quote_religi(),
        hijri_date=hijri_today
    )


@app.route(
    "/api/jadwal-imsakiyah"
)
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

            "status":
                False,

            "message":
                "Atribut id_kota bersifat esensial "
                "dan wajib dilampirkan."

        })

    try:

        url = (
            f"https://api.myquran.com/v2/sholat/"
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

            "status":
                False,

            "message":
                str(e)

        })

    return jsonify({

        "status":
            False,

        "message":
            "Terjadi kegagalan komunikasi dengan "
            "server penjadwalan pusat."

    })


@app.route(
    "/api/news-ticker"
)
def news_ticker():

    return jsonify([

        n['title']

        for n in get_news_entries()

    ])


@app.route(
    '/api/visitor-stats'
)
def visitor_stats():

    current_time = time.time()

    active_ips = {

        ip: ts

        for ip, ts
        in TRACKER_DATA["online_ips"].items()

        if current_time - ts <= 300

    }

    TRACKER_DATA[
        "online_ips"
    ] = active_ips

    active_locations = [

        TRACKER_DATA[
            "ip_locations"
        ].get(
            ip,
            "Tidak Terdeteksi"
        )

        for ip in active_ips.keys()

    ]

    return jsonify({

        "daily":
            len(
                TRACKER_DATA[
                    "daily_ips"
                ]
            ),

        "online":
            max(
                1,
                len(active_ips)
            ),

        "active_locations":
            list(
                set(
                    active_locations
                )
            )

    })


# ==========================================
# 9. API DETEKSI PELANGGARAN (SIMULASI DUMMY)
# ==========================================

@app.route(
    '/api/detect_violation',
    methods=['POST']
)
def api_detect_violation():

    try:

        data = request.get_json()

        frame_base64 = data.get(
            'frame',
            ''
        )

        chars = (
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        )

        plat = (

            f"H {random.randint(1000, 9999)} "
            f"{random.choice(chars)}"
            f"{random.choice(chars)}"

        )

        pelanggaran = random.choice([

            "Pelanggaran Marka Jalan",

            "Ketidakpatuhan Penggunaan "
            "Sabuk Pengaman",

            "Pengendara Tidak Menggunakan "
            "Helm Standar"

        ])

        return jsonify({

            "status":
                "success",

            "plate":
                plat,

            "violation":
                pelanggaran

        })

    except Exception as e:

        return jsonify({

            "status":
                "error",

            "message":
                "Terjadi kesalahan pada modul "
                "pemrosesan citra: "
                f"{str(e)}"

        }), 500


@app.route(
    '/about'
)
def about():

    return render_template(
        "about.html"
    )


@app.route(
    '/cctv'
)
def cctv_page():

    return render_template(
        "cctv.html"
    )


@app.route(
    '/sitemap.xml'
)
def sitemap():

    return send_from_directory(
        'static',
        'sitemap.xml'
    )


# ==========================================
# 10. FITUR PUSAT PESAN BLAST EWS KTVDI
# ==========================================

@app.route(
    '/email',
    methods=['GET', 'POST']
)
def email_blast_page():

    if 'user' not in session:

        return redirect(
            url_for(
                'login'
            )
        )

    if request.method == 'POST':

        subject = request.form.get(
            'subject'
        )

        body_text = request.form.get(
            'message'
        )

        kategori = request.form.get(
            'kategori',
            'Informasi Umum'
        )

        prioritas = request.form.get(
            'prioritas',
            'Normal'
        )

        if not subject or not body_text:

            flash(
                "Halo Admin, mohon pastikan subjek "
                "dan isi pesan sudah terisi ya.",
                "error"
            )

            return redirect(
                url_for(
                    'email_blast_page'
                )
            )

        if not ref:

            flash(
                "Gagal memuat database anggota. "
                "Pastikan koneksi ke Firebase aman.",
                "error"
            )

            return redirect(
                url_for(
                    'email_blast_page'
                )
            )

        users = (
            ref.child(
                'users'
            ).get()
            or
            {}
        )

        sent_details = []

        tz_jakarta = pytz.timezone(
            'Asia/Jakarta'
        )

        with app.app_context():

            for uid, user_data in users.items():

                if not isinstance(
                    user_data,
                    dict
                ):

                    continue

                email_tujuan = user_data.get(
                    'email'
                )

                nama_user = user_data.get(
                    'nama',
                    'Anggota KTVDI'
                )

                if not email_tujuan:

                    continue

                formatted_body = f"""
PESAN BLAST KTVDI (KOMUNITAS TV DIGITAL INDONESIA)
Kategori  : {kategori}
Prioritas : {prioritas}
========================================================

Halo Bapak/Ibu {nama_user},

{body_text}

Terima kasih atas perhatiannya. Mari tetap dukung pertelevisian di Indonesia bersama KTVDI.

Salam hangat,
Admin KTVDI
========================================================"""

                waktu_kirim = (
                    datetime.now(
                        tz_jakarta
                    ).strftime(
                        "%d %b %Y - %H:%M:%S WIB"
                    )
                )

                try:

                    msg = Message(
                        subject,
                        recipients=[
                            email_tujuan
                        ]
                    )

                    msg.body = formatted_body

                    mail.send(
                        msg
                    )

                    sent_details.append({

                        "nama":
                            nama_user,

                        "email":
                            email_tujuan,

                        "waktu":
                            waktu_kirim,

                        "status":
                            "Sukses"

                    })

                except Exception as e:

                    print(
                        f"Gagal mengirim ke "
                        f"{email_tujuan}: {e}"
                    )

                    sent_details.append({

                        "nama":
                            nama_user,

                        "email":
                            email_tujuan,

                        "waktu":
                            waktu_kirim,

                        "status":
                            "Gagal"

                    })

        if sent_details:

            session[
                'last_sent_details'
            ] = sent_details

            berhasil = sum(

                1

                for x in sent_details

                if x['status'] ==
                   "Sukses"

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
            url_for(
                'email_blast_page'
            )
        )

    sent_list = session.pop(
        'last_sent_details',
        None
    )

    total_users = 0

    if ref:

        try:

            total_users = len(
                ref.child(
                    'users'
                ).get()
                or
                {}
            )

        except:

            pass

    return render_template(
        'email.html',
        sent_list=sent_list,
        total_users=total_users
    )

# ==========================================
# 11. FITUR DASHBOARD JARINGAN KTVDI
#     CLIENT NETWORK + WIFI + ISP + SPEEDTEST
# ==========================================

#
# SUMBER DATA:
#
# CLIENT:
#   - public IP browser
#   - ISP / ASN berdasarkan public IP client
#   - browser
#   - OS
#   - effective connection type
#   - browser downlink
#   - browser RTT
#
# LOCAL BACKEND:
#   - local IPv4
#   - default gateway
#   - subnet
#   - ARP / neighbour table
#   - hostname
#   - SSID
#   - Wi-Fi signal
#   - Wi-Fi channel
#   - Wi-Fi radio / band
#   - interface
#
# SPEEDTEST:
#   - Ookla Speedtest CLI jika tersedia
#
# PENTING:
#
# Kalau Flask berjalan di laptop Windows:
#     data LAN/WiFi = laptop tersebut.
#
# Kalau Flask berjalan di Vercel/cloud:
#     data LAN/WiFi = server cloud,
#     BUKAN perangkat pengunjung.
#
# ==========================================


NETWORK_CACHE = {

    "data":
        None,

    "timestamp":
        0,

    "lock":
        __import__(
            "threading"
        ).RLock(),

    "building":
        False

}


NETWORK_CACHE_TTL = max(

    3,

    int(
        os.environ.get(
            "NETWORK_CACHE_TTL",
            "5"
        )
    )

)


NETWORK_ACTIVE_DISCOVERY = (

    os.environ.get(
        "NETWORK_ACTIVE_DISCOVERY",
        "false"
    )
    .strip()
    .lower()

    in (

        "1",
        "true",
        "yes",
        "on"

    )

)


NETWORK_DISCOVERY_WORKERS = max(

    4,

    min(

        64,

        int(
            os.environ.get(
                "NETWORK_DISCOVERY_WORKERS",
                "32"
            )
        )

    )

)


NETWORK_DISCOVERY_TIMEOUT = max(

    0.2,

    min(

        1.5,

        float(
            os.environ.get(
                "NETWORK_DISCOVERY_TIMEOUT",
                "0.5"
            )
        )

    )

)


# Jalankan speedtest hanya jika diaktifkan.
#
# .env:
#
# NETWORK_SPEEDTEST=true
#
NETWORK_SPEEDTEST_ENABLED = (

    os.environ.get(
        "NETWORK_SPEEDTEST",
        "false"
    )
    .strip()
    .lower()

    in (

        "1",
        "true",
        "yes",
        "on"

    )

)


NETWORK_SPEEDTEST_TIMEOUT = max(

    10,

    min(

        120,

        int(

            os.environ.get(
                "NETWORK_SPEEDTEST_TIMEOUT",
                "60"
            )

        )

    )

)


# ==========================================
# COMMAND OS
# ==========================================

def _run_command(
    command,
    timeout=3
):

    try:

        creationflags = 0

        if (
            platform.system().lower()
            ==
            "windows"
        ):

            creationflags = (
                subprocess.CREATE_NO_WINDOW
            )

        result = subprocess.run(

            command,

            stdout=subprocess.PIPE,

            stderr=subprocess.DEVNULL,

            stdin=subprocess.DEVNULL,

            text=True,

            timeout=timeout,

            check=False,

            creationflags=creationflags

        )

        return (
            result.stdout.strip()
        )

    except (
        FileNotFoundError,
        subprocess.TimeoutExpired,
        PermissionError,
        OSError
    ):

        return ""


# ==========================================
# VALIDASI IPV4
# ==========================================

def _is_valid_ipv4(
    ip
):

    try:

        parsed = ipaddress.ip_address(
            str(ip).strip()
        )

        return (
            parsed.version == 4
        )

    except ValueError:

        return False


def _is_valid_lan_ipv4(
    ip
):

    try:

        parsed = ipaddress.ip_address(
            str(ip).strip()
        )

        return (

            parsed.version == 4

            and
            parsed.is_private

            and
            not parsed.is_loopback

            and
            not parsed.is_link_local

            and
            not parsed.is_unspecified

            and
            not parsed.is_multicast

        )

    except ValueError:

        return False


# ==========================================
# PUBLIC IP BACKEND
# ==========================================

def get_public_ip():

    services = [

        (
            "https://api.ipify.org"
            "?format=json"
        ),

        (
            "https://api64.ipify.org"
            "?format=json"
        )

    ]

    for service in services:

        try:

            response = requests.get(

                service,

                timeout=3,

                headers={
                    "User-Agent":
                        "KTVDI-NetSight/1.0"
                }

            )

            if not response.ok:

                continue

            data = response.json()

            public_ip = str(
                data.get(
                    "ip",
                    ""
                )
            ).strip()

            if _is_valid_ipv4(
                public_ip
            ):

                return public_ip

            # IPv6 juga valid.
            try:

                ipaddress.ip_address(
                    public_ip
                )

                return public_ip

            except ValueError:

                continue

        except Exception:

            continue

    return None


# ==========================================
# ISP / ASN CLIENT
# ==========================================

def get_ip_organization(
    public_ip
):

    """
    Lookup berdasarkan IP publik CLIENT.

    IPinfo menyediakan field org/ASN organization.
    """

    if not public_ip:

        return {

            "isp":
                None,

            "asn":
                None,

            "org":
                None,

            "domain":
                None,

            "city":
                None,

            "region":
                None,

            "country":
                None,

            "source":
                None

        }


    # --------------------------------------
    # IPINFO TOKEN
    # --------------------------------------

    token = os.environ.get(
        "IPINFO_TOKEN",
        ""
    ).strip()


    urls = []


    if token:

        urls.append(

            (
                "https://ipinfo.io/"
                f"{public_ip}/json"
                f"?token={token}"
            )

        )

    else:

        urls.append(

            (
                "https://ipinfo.io/"
                f"{public_ip}/json"
            )

        )


    for url in urls:

        try:

            response = requests.get(

                url,

                timeout=4,

                headers={

                    "User-Agent":
                        "KTVDI-NetSight/1.0",

                    "Accept":
                        "application/json"

                }

            )

            if not response.ok:

                continue


            data = response.json()


            org_raw = str(
                data.get(
                    "org",
                    ""
                )
            ).strip()


            isp = None

            asn = None


            if org_raw:

                parts = org_raw.split(
                    " ",
                    1
                )


                if (
                    parts
                    and
                    parts[0].upper().startswith(
                        "AS"
                    )
                ):

                    asn = parts[0]

                    isp = (
                        parts[1].strip()
                        if len(parts) > 1
                        else
                        org_raw
                    )

                else:

                    isp = org_raw


            # Legacy / nested ASN
            if not asn:

                asn_data = data.get(
                    "asn"
                )

                if isinstance(
                    asn_data,
                    dict
                ):

                    asn = asn_data.get(
                        "asn"
                    )

                    if not isp:

                        isp = (
                            asn_data.get(
                                "name"
                            )
                            or
                            asn_data.get(
                                "domain"
                            )
                        )


            return {

                "isp":
                    isp,

                "asn":
                    asn,

                "org":
                    org_raw or None,

                "domain":
                    (
                        data.get(
                            "hostname"
                        )
                        or
                        (
                            data.get(
                                "asn",
                                {}
                            ).get(
                                "domain"
                            )
                            if isinstance(
                                data.get(
                                    "asn"
                                ),
                                dict
                            )
                            else
                            None
                        )
                    ),

                "city":
                    data.get(
                        "city"
                    ),

                "region":
                    data.get(
                        "region"
                    ),

                "country":
                    data.get(
                        "country"
                    ),

                "source":
                    "IPinfo"

            }


        except Exception as e:

            print(
                "INFO: IP organization lookup gagal: "
                f"{e}"
            )

            continue


    return {

        "isp":
            None,

        "asn":
            None,

        "org":
            None,

        "domain":
            None,

        "city":
            None,

        "region":
            None,

        "country":
            None,

        "source":
            None

    }


# ==========================================
# IP CLIENT VIA HTTP HEADER
# ==========================================

def get_request_public_ip():

    """
    Mendapatkan IP pengunjung dari request.

    Prioritas:
    X-Forwarded-For
    X-Real-IP
    remote_addr

    Dipakai sebagai fallback apabila browser
    tidak mengirim public IP melalui API.
    """

    candidates = [

        request.headers.get(
            "X-Forwarded-For"
        ),

        request.headers.get(
            "X-Real-IP"
        ),

        request.remote_addr

    ]


    for candidate in candidates:

        if not candidate:

            continue


        for raw_ip in str(
            candidate
        ).split(","):

            raw_ip = raw_ip.strip()


            if _is_valid_ipv4(
                raw_ip
            ):

                try:

                    parsed = ipaddress.ip_address(
                        raw_ip
                    )

                    if not parsed.is_private:

                        return raw_ip

                except ValueError:

                    continue


    return None


# ==========================================
# IP LOKAL
# ==========================================

def get_local_ip():

    """
    IPv4 interface LAN yang digunakan route utama.
    """

    sock = None

    try:

        sock = socket.socket(

            socket.AF_INET,

            socket.SOCK_DGRAM

        )

        sock.settimeout(
            0.8
        )

        sock.connect(
            (
                "8.8.8.8",
                80
            )
        )

        local_ip = (
            sock.getsockname()[0]
        )


        if _is_valid_lan_ipv4(
            local_ip
        ):

            return local_ip


    except (
        OSError,
        socket.error
    ):

        pass


    finally:

        if sock:

            try:

                sock.close()

            except:

                pass


    system = platform.system().lower()


    # ======================================
    # WINDOWS
    # ======================================

    if system == "windows":

        output = _run_command(

            [
                "powershell",
                "-NoProfile",
                "-Command",

                (
                    "Get-NetIPAddress "
                    "-AddressFamily IPv4 "
                    "| Where-Object {"
                    "$_.IPAddress -and "
                    "$_.IPAddress -notlike '127.*' -and "
                    "$_.IPAddress -notlike '169.254.*'"
                    "} "
                    "| Select-Object "
                    "-ExpandProperty IPAddress"
                )

            ],

            timeout=3

        )


        candidates = []

        for line in output.splitlines():

            candidate = line.strip()

            if _is_valid_lan_ipv4(
                candidate
            ):

                candidates.append(
                    candidate
                )


        if candidates:

            return candidates[0]


    # ======================================
    # LINUX
    # ======================================

    if system == "linux":

        output = _run_command(

            [
                "ip",
                "-4",
                "-o",
                "addr",
                "show"
            ],

            timeout=3

        )


        for line in output.splitlines():

            match = re.search(

                r"\binet\s+"
                r"(\d+\.\d+\.\d+\.\d+)/\d+",

                line

            )


            if match:

                candidate = (
                    match.group(1)
                )


                if _is_valid_lan_ipv4(
                    candidate
                ):

                    return candidate


    # ======================================
    # GENERIC
    # ======================================

    try:

        hostname = socket.gethostname()

        addresses = socket.gethostbyname_ex(
            hostname
        )[2]


        for ip in addresses:

            if _is_valid_lan_ipv4(
                ip
            ):

                return ip


    except Exception:

        pass


    return None


# ==========================================
# DEFAULT GATEWAY
# ==========================================

def detect_default_gateway():

    system = platform.system().lower()


    # ======================================
    # WINDOWS
    # ======================================

    if system == "windows":

        output = _run_command(

            [
                "route",
                "print",
                "-4",
                "0.0.0.0"
            ],

            timeout=3

        )


        for line in output.splitlines():

            line = line.strip()

            if not line:

                continue


            parts = line.split()


            if len(parts) >= 3:

                if parts[0] == "0.0.0.0":

                    gateway = parts[2]


                    if _is_valid_lan_ipv4(
                        gateway
                    ):

                        return gateway


        ps_output = _run_command(

            [
                "powershell",
                "-NoProfile",
                "-Command",

                (
                    "(Get-NetRoute "
                    "-AddressFamily IPv4 "
                    "-DestinationPrefix '0.0.0.0/0' "
                    "| Where-Object {"
                    "$_.NextHop -and "
                    "$_.NextHop -ne '0.0.0.0'"
                    "} "
                    "| Sort-Object RouteMetric,ifMetric "
                    "| Select-Object -First 1 "
                    "-ExpandProperty NextHop)"
                )

            ],

            timeout=4

        )


        for line in ps_output.splitlines():

            gateway = line.strip()

            if _is_valid_lan_ipv4(
                gateway
            ):

                return gateway


    # ======================================
    # LINUX
    # ======================================

    elif system == "linux":

        output = _run_command(

            [
                "ip",
                "-4",
                "route",
                "show",
                "default"
            ],

            timeout=3

        )


        match = re.search(

            r"default\s+via\s+"
            r"(\d+\.\d+\.\d+\.\d+)",

            output

        )


        if match:

            gateway = match.group(1)


            if _is_valid_lan_ipv4(
                gateway
            ):

                return gateway


    # ======================================
    # MACOS
    # ======================================

    elif system == "darwin":

        output = _run_command(

            [
                "route",
                "-n",
                "get",
                "default"
            ],

            timeout=3

        )


        match = re.search(

            r"gateway:\s+"
            r"(\d+\.\d+\.\d+\.\d+)",

            output

        )


        if match:

            gateway = match.group(1)


            if _is_valid_lan_ipv4(
                gateway
            ):

                return gateway


    return None


# ==========================================
# SUBNET
# ==========================================

def get_interface_network(
    local_ip,
    gateway=None
):

    if not local_ip:

        return None


    system = platform.system().lower()


    # ======================================
    # WINDOWS POWERSHELL
    # ======================================

    if system == "windows":

        command = (

            "Get-NetIPAddress "

            "-AddressFamily IPv4 "

            f"-IPAddress '{local_ip}' "

            "| Select-Object "
            "IPAddress,PrefixLength "

            "| ConvertTo-Json -Compress"

        )


        output = _run_command(

            [
                "powershell",
                "-NoProfile",
                "-Command",
                command
            ],

            timeout=4

        )


        if output:

            try:

                data = json.loads(
                    output
                )


                if isinstance(
                    data,
                    list
                ):

                    data = (
                        data[0]
                        if data
                        else
                        None
                    )


                if isinstance(
                    data,
                    dict
                ):

                    prefix = data.get(
                        "PrefixLength"
                    )


                    if prefix is not None:

                        prefix = int(
                            prefix
                        )


                        return ipaddress.ip_network(

                            f"{local_ip}/{prefix}",

                            strict=False

                        )


            except Exception:

                pass


    # ======================================
    # LINUX
    # ======================================

    elif system == "linux":

        output = _run_command(

            [
                "ip",
                "-4",
                "-o",
                "addr",
                "show"
            ],

            timeout=3

        )


        for line in output.splitlines():

            match = re.search(

                r"\binet\s+"
                r"(\d+\.\d+\.\d+\.\d+)/(\d+)",

                line

            )


            if match:

                candidate_ip = (
                    match.group(1)
                )

                prefix = int(
                    match.group(2)
                )


                if candidate_ip == local_ip:

                    return ipaddress.ip_network(

                        f"{local_ip}/{prefix}",

                        strict=False

                    )


    # ======================================
    # FALLBACK
    # ======================================

    try:

        return ipaddress.ip_network(

            f"{local_ip}/24",

            strict=False

        )

    except ValueError:

        return None


# ==========================================
# WINDOWS WIFI INFO
# ==========================================

def get_windows_wifi_info():

    """
    Membaca Wi-Fi interface aktif dengan:

        netsh wlan show interfaces

    Informasi yang dicoba:
        SSID
        BSSID
        Signal
        Channel
        Radio type
        Authentication
        Receive rate
        Transmit rate
        State
    """

    if (
        platform.system().lower()
        !=
        "windows"
    ):

        return {

            "available":
                False,

            "connected":
                False,

            "ssid":
                None,

            "bssid":
                None,

            "signal_percent":
                None,

            "channel":
                None,

            "radio_type":
                None,

            "band":
                None,

            "interface":
                None,

            "receive_mbps":
                None,

            "transmit_mbps":
                None,

            "authentication":
                None,

            "state":
                None,

            "source":
                None

        }


    output = _run_command(

        [
            "netsh",
            "wlan",
            "show",
            "interfaces"
        ],

        timeout=5

    )


    result = {

        "available":
            bool(output),

        "connected":
            False,

        "ssid":
            None,

        "bssid":
            None,

        "signal_percent":
            None,

        "channel":
            None,

        "radio_type":
            None,

        "band":
            None,

        "interface":
            None,

        "receive_mbps":
            None,

        "transmit_mbps":
            None,

        "authentication":
            None,

        "state":
            None,

        "source":
            "netsh wlan"

    }


    if not output:

        return result


    # ======================================
    # PARSER FIELD
    # ======================================

    field_patterns = {

        "interface":
            [
                r"^\s*Name\s*:\s*(.+)$",
                r"^\s*Nama\s*:\s*(.+)$"
            ],

        "state":
            [
                r"^\s*State\s*:\s*(.+)$",
                r"^\s*Status\s*:\s*(.+)$"
            ],

        "ssid":
            [
                r"^\s*SSID\s*:\s*(.*)$"
            ],

        "bssid":
            [
                r"^\s*BSSID\s*:\s*(.*)$"
            ],

        "signal":
            [
                r"^\s*Signal\s*:\s*(\d+)%"
            ],

        "channel":
            [
                r"^\s*Channel\s*:\s*(\d+)"
            ],

        "radio_type":
            [
                r"^\s*Radio type\s*:\s*(.+)$",
                r"^\s*Tipe radio\s*:\s*(.+)$"
            ],

        "authentication":
            [
                r"^\s*Authentication\s*:\s*(.+)$",
                r"^\s*Authentication\s*:\s*(.+)$"
            ],

        "receive":
            [
                r"^\s*Receive rate \(Mbps\)\s*:\s*([\d.]+)",
                r"^\s*Kecepatan penerimaan \(Mbps\)\s*:\s*([\d.]+)"
            ],

        "transmit":
            [
                r"^\s*Transmit rate \(Mbps\)\s*:\s*([\d.]+)",
                r"^\s*Kecepatan transmisi \(Mbps\)\s*:\s*([\d.]+)"
            ]

    }


    for line in output.splitlines():

        for key, patterns in field_patterns.items():

            for pattern in patterns:

                match = re.search(
                    pattern,
                    line,
                    re.I
                )


                if not match:

                    continue


                value = (
                    match.group(1).strip()
                )


                if key == "signal":

                    try:

                        result[
                            "signal_percent"
                        ] = int(
                            value
                        )

                    except:

                        pass

                elif key == "channel":

                    try:

                        result[
                            "channel"
                        ] = int(
                            value
                        )

                    except:

                        pass

                elif key == "receive":

                    try:

                        result[
                            "receive_mbps"
                        ] = float(
                            value
                        )

                    except:

                        pass

                elif key == "transmit":

                    try:

                        result[
                            "transmit_mbps"
                        ] = float(
                            value
                        )

                    except:

                        pass

                else:

                    result[key] = value


                break


    # ======================================
    # NORMALISASI STATE
    # ======================================

    state_value = (
        str(
            result.get(
                "state"
            )
            or
            ""
        )
        .strip()
        .lower()
    )


    if (
        state_value
        in
        (
            "connected",
            "terhubung"
        )
    ):

        result[
            "connected"
        ] = True


    # ======================================
    # BAND
    # ======================================

    channel = result.get(
        "channel"
    )


    radio_type = (
        str(
            result.get(
                "radio_type"
            )
            or
            ""
        )
        .lower()
    )


    if channel is not None:

        if (
            1
            <=
            int(channel)
            <=
            14
        ):

            result[
                "band"
            ] = "2.4 GHz"

        elif (
            32
            <=
            int(channel)
            <=
            177
        ):

            result[
                "band"
            ] = "5 GHz"


    if not result.get(
        "band"
    ):

        if (
            "802.11ax"
            in
            radio_type
        ):

            result[
                "band"
            ] = "5/2.4 GHz"

        elif (
            "802.11ac"
            in
            radio_type
        ):

            result[
                "band"
            ] = "5 GHz"


    return result


# ==========================================
# GENERIC WIFI INFO
# ==========================================

def get_wifi_info():

    system = platform.system().lower()


    if system == "windows":

        return get_windows_wifi_info()


    # ======================================
    # LINUX
    # ======================================

    if system == "linux":

        result = {

            "available":
                False,

            "connected":
                False,

            "ssid":
                None,

            "bssid":
                None,

            "signal_percent":
                None,

            "channel":
                None,

            "radio_type":
                None,

            "band":
                None,

            "interface":
                None,

            "receive_mbps":
                None,

            "transmit_mbps":
                None,

            "authentication":
                None,

            "state":
                None,

            "source":
                "Linux"

        }


        iw_output = _run_command(

            [
                "iw",
                "dev"
            ],

            timeout=4

        )


        if iw_output:

            result[
                "available"
            ] = True


        # interface
        match = re.search(

            r"Interface\s+(\S+)",

            iw_output

        )


        if match:

            result[
                "interface"
            ] = match.group(1)


        if result.get(
            "interface"
        ):

            link = _run_command(

                [
                    "iw",
                    "dev",
                    result["interface"],
                    "link"
                ],

                timeout=4

            )


            if link:

                result[
                    "connected"
                ] = "Connected" in link


                match = re.search(

                    r"SSID\s+(.+)",

                    link

                )


                if match:

                    result[
                        "ssid"
                    ] = match.group(1).strip()


                match = re.search(

                    r"signal:\s+(-?\d+)",

                    link

                )


                if match:

                    result[
                        "signal_dbm"
                    ] = int(
                        match.group(1)
                    )


        return result


    # ======================================
    # MACOS
    # ======================================

    if system == "darwin":

        result = {

            "available":
                True,

            "connected":
                False,

            "ssid":
                None,

            "bssid":
                None,

            "signal_percent":
                None,

            "signal_dbm":
                None,

            "channel":
                None,

            "radio_type":
                None,

            "band":
                None,

            "interface":
                None,

            "receive_mbps":
                None,

            "transmit_mbps":
                None,

            "authentication":
                None,

            "state":
                None,

            "source":
                "macOS"

        }


        airport_output = _run_command(

            [
                "/System/Library/PrivateFrameworks/"
                "Apple80211.framework/Versions/Current/"
                "Resources/airport",
                "-I"
            ],

            timeout=5

        )


        if airport_output:

            result[
                "connected"
            ] = True


            patterns = {

                "ssid":
                    r"^\s*SSID:\s*(.+)$",

                "bssid":
                    r"^\s*BSSID:\s*(.+)$",

                "signal_dbm":
                    r"^\s*agrCtlRSSI:\s*(-?\d+)",

                "channel":
                    r"^\s*channel:\s*(\d+)"

            }


            for key, pattern in patterns.items():

                match = re.search(

                    pattern,

                    airport_output,

                    re.I |
                    re.M

                )


                if match:

                    value = match.group(1).strip()


                    try:

                        result[key] = (
                            int(value)
                            if key in
                            (
                                "channel",
                                "signal_dbm"
                            )
                            else
                            value
                        )

                    except:

                        result[key] = value


            channel = result.get(
                "channel"
            )


            if channel:

                result[
                    "band"
                ] = (
                    "2.4 GHz"
                    if channel <= 14
                    else
                    "5 GHz"
                )


        return result


    return {

        "available":
            False,

        "connected":
            False,

        "ssid":
            None,

        "bssid":
            None,

        "signal_percent":
            None,

        "signal_dbm":
            None,

        "channel":
            None,

        "radio_type":
            None,

        "band":
            None,

        "interface":
            None,

        "receive_mbps":
            None,

        "transmit_mbps":
            None,

        "authentication":
            None,

        "state":
            None,

        "source":
            None

    }


# ==========================================
# ARP / NEIGHBOUR
# ==========================================

def normalize_mac(
    mac
):

    if not mac:

        return None


    compact = re.sub(

        r"[^0-9A-Fa-f]",

        "",

        str(mac)

    )


    if len(compact) == 12:

        return ":".join(

            [

                compact[0:2],
                compact[2:4],
                compact[4:6],
                compact[6:8],
                compact[8:10],
                compact[10:12]

            ]

        ).upper()


    return str(
        mac
    ).replace(
        "-",
        ":"
    ).upper()


def get_arp_neighbors():

    neighbors = {}

    system = platform.system().lower()


    # ======================================
    # WINDOWS
    # ======================================

    if system == "windows":

        output = _run_command(

            [
                "arp",
                "-a"
            ],

            timeout=4

        )


        current_interface = None


        for line in output.splitlines():

            line = line.strip()


            if not line:

                continue


            interface_match = re.search(

                r"Interface:\s+"
                r"(\d+\.\d+\.\d+\.\d+)",

                line,

                re.I

            )


            if interface_match:

                current_interface = (
                    interface_match.group(1)
                )

                continue


            match = re.search(

                r"(\d+\.\d+\.\d+\.\d+)"
                r"\s+"
                r"([0-9a-fA-F:-]{17})"
                r"\s+"
                r"(\w+)",

                line

            )


            if match:

                ip_addr = (
                    match.group(1)
                )


                if not _is_valid_ipv4(
                    ip_addr
                ):

                    continue


                mac_addr = (
                    match.group(2)
                )


                state = (
                    match.group(3)
                    .upper()
                )


                neighbors[
                    ip_addr
                ] = {

                    "ip":
                        ip_addr,

                    "mac":
                        normalize_mac(
                            mac_addr
                        ),

                    "state":
                        state,

                    "interface":
                        current_interface

                }


        # ==================================
        # POWERSHELL
        # ==================================

        ps_output = _run_command(

            [
                "powershell",
                "-NoProfile",
                "-Command",

                (
                    "Get-NetNeighbor "
                    "-AddressFamily IPv4 "
                    "| Where-Object {"
                    "$_.IPAddress -and "
                    "$_.LinkLayerAddress"
                    "} "
                    "| Select-Object "
                    "IPAddress,LinkLayerAddress,State "
                    "| ConvertTo-Json -Compress"
                )

            ],

            timeout=5

        )


        if ps_output:

            try:

                data = json.loads(
                    ps_output
                )


                if isinstance(
                    data,
                    dict
                ):

                    data = [data]


                for item in data:

                    if not isinstance(
                        item,
                        dict
                    ):

                        continue


                    ip_addr = str(
                        item.get(
                            "IPAddress",
                            ""
                        )
                    ).strip()


                    mac_addr = str(
                        item.get(
                            "LinkLayerAddress",
                            ""
                        )
                    ).strip()


                    state = str(
                        item.get(
                            "State",
                            "UNKNOWN"
                        )
                    ).upper()


                    if not _is_valid_ipv4(
                        ip_addr
                    ):

                        continue


                    if (
                        not re.match(
                            r"^[0-9A-Fa-f:-]{17}$",
                            mac_addr
                        )
                    ):

                        continue


                    neighbors[
                        ip_addr
                    ] = {

                        "ip":
                            ip_addr,

                        "mac":
                            normalize_mac(
                                mac_addr
                            ),

                        "state":
                            state,

                        "interface":
                            None

                    }


            except Exception:

                pass


    # ======================================
    # LINUX
    # ======================================

    elif system == "linux":

        output = _run_command(

            [
                "ip",
                "-4",
                "neigh",
                "show"
            ],

            timeout=4

        )


        for line in output.splitlines():

            match = re.search(

                r"(\d+\.\d+\.\d+\.\d+)"
                r".*?"
                r"(?:lladdr\s+"
                r"([0-9a-fA-F:]{17}))?"
                r".*?"
                r"(REACHABLE|STALE|DELAY|PROBE|FAILED|PERMANENT|NOARP|INCOMPLETE)",

                line,

                re.I

            )


            if match:

                ip_addr = (
                    match.group(1)
                )


                neighbors[
                    ip_addr
                ] = {

                    "ip":
                        ip_addr,

                    "mac":
                        normalize_mac(
                            match.group(2)
                        ),

                    "state":
                        (
                            match.group(3)
                            or
                            "UNKNOWN"
                        ).upper(),

                    "interface":
                        None

                }


    # ======================================
    # MACOS
    # ======================================

    elif system == "darwin":

        output = _run_command(

            [
                "arp",
                "-an"
            ],

            timeout=4

        )


        for line in output.splitlines():

            match = re.search(

                r"\((\d+\.\d+\.\d+\.\d+)\)"
                r"\s+at\s+"
                r"([0-9a-fA-F:]{17})",

                line,

                re.I

            )


            if match:

                ip_addr = (
                    match.group(1)
                )


                neighbors[
                    ip_addr
                ] = {

                    "ip":
                        ip_addr,

                    "mac":
                        normalize_mac(
                            match.group(2)
                        ),

                    "state":
                        "KNOWN",

                    "interface":
                        None

                }


    return neighbors


# ==========================================
# MAC VENDOR
# ==========================================

def get_mac_vendor(
    mac
):

    mac = normalize_mac(
        mac
    )


    if not mac:

        return None


    compact = re.sub(
        r"[^0-9A-F]",
        "",
        mac.upper()
    )


    if len(compact) < 6:

        return None


    oui = ":".join(

        [

            compact[0:2],
            compact[2:4],
            compact[4:6]

        ]

    )


    common_oui = {

        "00:46:4B":
            "Huawei",

        "00:18:82":
            "Huawei",

        "00:25:68":
            "Huawei",

        "48:46:FB":
            "Huawei",

        "50:C7:BF":
            "TP-Link",

        "54:A7:03":
            "TP-Link",

        "C0:4A:00":
            "TP-Link",

        "28:6C:07":
            "Xiaomi",

        "34:CE:00":
            "Xiaomi",

        "64:09:80":
            "Xiaomi",

        "00:1C:B3":
            "Apple",

        "3C:06:30":
            "Apple",

        "A4:83:E7":
            "Apple",

        "00:07:AB":
            "Samsung",

        "5C:49:7D":
            "Samsung",

        "CC:07:AB":
            "Samsung",

        "00:1B:21":
            "Intel",

        "00:1E:67":
            "Intel",

        "3C:F0:11":
            "Intel",

        "00:E0:4C":
            "Realtek",

        "00:00:0C":
            "Cisco",

        "00:14:22":
            "Dell",

        "00:1E:0B":
            "HP",

        "00:1F:C6":
            "ASUS",

        "3C:5A:B4":
            "Google"

    }


    return common_oui.get(
        oui
    )


# ==========================================
# HOSTNAME
# ==========================================

def resolve_hostname(
    ip,
    timeout=0.5
):

    old_timeout = (
        socket.getdefaulttimeout()
    )


    try:

        socket.setdefaulttimeout(
            timeout
        )


        result = socket.gethostbyaddr(
            ip
        )


        if result:

            return result[0]


    except (
        socket.herror,
        socket.gaierror,
        socket.timeout,
        OSError
    ):

        pass


    finally:

        try:

            socket.setdefaulttimeout(
                old_timeout
            )

        except:

            pass


    return None


def resolve_hostnames_parallel(
    devices,
    max_workers=16
):

    targets = [

        device

        for device in devices

        if (

            device.get(
                "ip"
            )

            and

            not device.get(
                "hostname"
            )

            and

            device.get(
                "role"
            )
            !=
            "local_device"

        )

    ]


    if not targets:

        return devices


    workers = max(

        1,

        min(
            max_workers,
            len(targets)
        )

    )


    with ThreadPoolExecutor(
        max_workers=workers
    ) as executor:

        futures = {

            executor.submit(

                resolve_hostname,

                device["ip"]

            ):
                device

            for device in targets

        }


        for future in as_completed(
            futures
        ):

            device = futures[
                future
            ]


            try:

                hostname = (
                    future.result()
                )


                if hostname:

                    device[
                        "hostname"
                    ] = hostname


            except Exception:

                pass


    return devices


# ==========================================
# PING
# ==========================================

def ping_host(
    ip,
    timeout=1
):

    if not ip:

        return False, None


    if not _is_valid_ipv4(
        ip
    ):

        return False, None


    system = platform.system().lower()


    if system == "windows":

        command = [

            "ping",

            "-n",
            "1",

            "-w",
            str(
                max(
                    1,
                    int(
                        timeout
                        *
                        1000
                    )
                )
            ),

            ip

        ]


    else:

        command = [

            "ping",

            "-c",
            "1",

            "-W",
            str(
                max(
                    1,
                    int(timeout)
                )
            ),

            ip

        ]


    started = time.perf_counter()


    output = _run_command(

        command,

        timeout=(
            timeout
            +
            1.5
        )

    )


    elapsed = round(

        (
            time.perf_counter()
            -
            started
        )
        *
        1000,

        1

    )


    if output:

        text = output.lower()


        if (

            "ttl=" in text

            or

            "time=" in text

            or

            "time<" in text

        ):

            # Coba ambil angka ping asli.
            match = re.search(

                r"(?:time[=<])\s*(\d+(?:[.,]\d+)?)\s*ms",

                text

            )


            if match:

                try:

                    return True, float(
                        match.group(1)
                        .replace(
                            ",",
                            "."
                        )
                    )

                except:

                    pass


            return True, elapsed


    return False, None


# ==========================================
# ACTIVE DISCOVERY
# ==========================================

def probe_host(
    ip,
    timeout=0.5
):

    online, latency = ping_host(

        ip,

        timeout=timeout

    )


    return {

        "ip":
            ip,

        "online":
            online,

        "latency_ms":
            latency

    }


def active_network_discovery(
    network,
    known_neighbors=None,
    local_ip=None,
    gateway=None
):

    if not NETWORK_ACTIVE_DISCOVERY:

        return {}


    if not network:

        return {}


    if not isinstance(
        network,
        ipaddress.IPv4Network
    ):

        return {}


    # Hindari scan terlalu besar.
    if (

        network.prefixlen < 16

        or

        network.prefixlen > 24

    ):

        return {}


    known_neighbors = (

        known_neighbors

        if isinstance(
            known_neighbors,
            dict
        )

        else

        {}

    )


    known_ips = set(
        known_neighbors.keys()
    )


    targets = []


    for host in network.hosts():

        ip_addr = str(
            host
        )


        if ip_addr == local_ip:

            continue


        if ip_addr == gateway:

            continue


        if ip_addr in known_ips:

            continue


        targets.append(
            ip_addr
        )


    if not targets:

        return {}


    discovered = {}


    workers = min(

        NETWORK_DISCOVERY_WORKERS,

        len(targets)

    )


    with ThreadPoolExecutor(
        max_workers=max(
            1,
            workers
        )
    ) as executor:

        futures = {

            executor.submit(

                probe_host,

                ip_addr,

                NETWORK_DISCOVERY_TIMEOUT

            ):
                ip_addr

            for ip_addr in targets

        }


        for future in as_completed(
            futures
        ):

            try:

                item = future.result()


                if item.get(
                    "online"
                ):

                    discovered[
                        item["ip"]
                    ] = item


            except Exception:

                continue


    return discovered


# ==========================================
# BUILD DEVICES
# ==========================================

def build_device_list(
    local_ip,
    gateway,
    network,
    neighbors,
    active_discovered=None
):

    devices = {}


    active_discovered = (

        active_discovered

        if isinstance(
            active_discovered,
            dict
        )

        else

        {}

    )


    # --------------------------------------
    # LOCAL
    # --------------------------------------

    if local_ip:

        devices[
            local_ip
        ] = {

            "ip":
                local_ip,

            "mac":
                None,

            "hostname":
                socket.gethostname(),

            "online":
                True,

            "latency_ms":
                0,

            "role":
                "local_device",

            "vendor":
                None,

            "state":
                "LOCAL",

            "source":
                "local_interface"

        }


    # --------------------------------------
    # NEIGHBOR
    # --------------------------------------

    online_states = {

        "REACHABLE",
        "STALE",
        "DELAY",
        "PROBE",
        "PERMANENT",
        "PUBLISHED",
        "KNOWN",
        "DYNAMIC",
        "STATIC",
        "NOARP"

    }


    for ip_addr, item in neighbors.items():

        if not _is_valid_ipv4(
            ip_addr
        ):

            continue


        mac = normalize_mac(
            item.get(
                "mac"
            )
        )


        state = str(
            item.get(
                "state",
                "UNKNOWN"
            )
        ).upper()


        is_online = (

            state
            in
            online_states

        )


        role = "device"


        if (

            gateway

            and

            ip_addr == gateway

        ):

            role = "router"

            # Gateway routing table saja tidak
            # berarti ping wajib berhasil.
            # Status ditentukan ping di tahap berikut.


        if (

            local_ip

            and

            ip_addr == local_ip

        ):

            role = "local_device"

            is_online = True


        devices[
            ip_addr
        ] = {

            "ip":
                ip_addr,

            "mac":
                mac,

            "hostname":
                None,

            "online":
                is_online,

            "latency_ms":
                None,

            "role":
                role,

            "vendor":
                get_mac_vendor(
                    mac
                ),

            "state":
                state,

            "source":
                "arp"

        }


    # --------------------------------------
    # ACTIVE DISCOVERY
    # --------------------------------------

    for ip_addr, item in active_discovered.items():

        if not _is_valid_ipv4(
            ip_addr
        ):

            continue


        if ip_addr in devices:

            devices[
                ip_addr
            ]["online"] = True


            devices[
                ip_addr
            ]["latency_ms"] = (
                item.get(
                    "latency_ms"
                )
            )


            devices[
                ip_addr
            ]["source"] = (

                devices[
                    ip_addr
                ].get(
                    "source",
                    "arp"
                )

                +
                "+probe"

            )


            continue


        devices[
            ip_addr
        ] = {

            "ip":
                ip_addr,

            "mac":
                None,

            "hostname":
                None,

            "online":
                True,

            "latency_ms":
                item.get(
                    "latency_ms"
                ),

            "role":
                "device",

            "vendor":
                None,

            "state":
                "PROBE_REACHABLE",

            "source":
                "active_probe"

        }


    # --------------------------------------
    # GATEWAY
    # --------------------------------------

    if gateway:

        if gateway not in devices:

            devices[
                gateway
            ] = {

                "ip":
                    gateway,

                "mac":
                    None,

                "hostname":
                    None,

                "online":
                    False,

                "latency_ms":
                    None,

                "role":
                    "router",

                "vendor":
                    None,

                "state":
                    "ROUTING_TABLE",

                "source":
                    "routing_table"

            }

        else:

            devices[
                gateway
            ]["role"] = (
                "router"
            )


    return list(
        devices.values()
    )


# ==========================================
# SPEEDTEST OOKLA CLI
# ==========================================

def find_speedtest_command():

    candidates = [

        "speedtest",

        "speedtest.exe"

    ]


    for command in candidates:

        output = _run_command(

            [
                command,
                "--version"
            ],

            timeout=5

        )


        if output:

            return command


    # Windows common path
    windows_paths = [

        os.path.join(
            os.environ.get(
                "ProgramFiles",
                "C:\\Program Files"
            ),
            "Ookla",
            "Speedtest",
            "speedtest.exe"
        ),

        os.path.join(
            os.environ.get(
                "ProgramFiles(x86)",
                "C:\\Program Files (x86)"
            ),
            "Ookla",
            "Speedtest",
            "speedtest.exe"
        ),

        os.path.join(
            os.environ.get(
                "LOCALAPPDATA",
                ""
            ),
            "Programs",
            "speedtest",
            "speedtest.exe"
        )

    ]


    for path in windows_paths:

        if os.path.isfile(
            path
        ):

            return path


    return None


def run_ookla_speedtest():

    """
    Menjalankan Ookla Speedtest CLI jika tersedia.

    Hasil:
        ping_ms
        download_mbps
        upload_mbps
        server
        isp
        packet_loss
    """

    if not NETWORK_SPEEDTEST_ENABLED:

        return {

            "available":
                False,

            "running":
                False,

            "success":
                False,

            "download_mbps":
                None,

            "upload_mbps":
                None,

            "ping_ms":
                None,

            "packet_loss_percent":
                None,

            "server":
                None,

            "isp":
                None,

            "source":
                "Ookla Speedtest CLI",

            "message":
                "Speedtest dinonaktifkan."

        }


    command = find_speedtest_command()


    if not command:

        return {

            "available":
                False,

            "running":
                False,

            "success":
                False,

            "download_mbps":
                None,

            "upload_mbps":
                None,

            "ping_ms":
                None,

            "packet_loss_percent":
                None,

            "server":
                None,

            "isp":
                None,

            "source":
                "Ookla Speedtest CLI",

            "message":
                (
                    "Ookla Speedtest CLI tidak ditemukan "
                    "di komputer tempat Flask berjalan."
                )

        }


    try:

        # JSON output dipakai agar tidak perlu parsing
        # teks progress yang panjang.
        result = subprocess.run(

            [
                command,
                "--format=json",
                "--accept-license",
                "--accept-gdpr"
            ],

            stdout=subprocess.PIPE,

            stderr=subprocess.DEVNULL,

            stdin=subprocess.DEVNULL,

            text=True,

            timeout=NETWORK_SPEEDTEST_TIMEOUT,

            check=False,

            creationflags=(

                subprocess.CREATE_NO_WINDOW

                if platform.system().lower()
                ==
                "windows"

                else

                0

            )

        )


        raw = (
            result.stdout
            or
            ""
        ).strip()


        if not raw:

            return {

                "available":
                    True,

                "running":
                    False,

                "success":
                    False,

                "download_mbps":
                    None,

                "upload_mbps":
                    None,

                "ping_ms":
                    None,

                "packet_loss_percent":
                    None,

                "server":
                    None,

                "isp":
                    None,

                "source":
                    "Ookla Speedtest CLI",

                "message":
                    "Speedtest tidak mengembalikan data."

            }


        # Terkadang output memiliki line tambahan.
        # Ambil JSON object pertama.
        json_start = raw.find(
            "{"
        )

        json_end = raw.rfind(
            "}"
        )


        if (
            json_start == -1
            or
            json_end == -1
        ):

            raise ValueError(
                "Output Speedtest bukan JSON."
            )


        payload = json.loads(

            raw[
                json_start:
                json_end + 1
            ]

        )


        download_bps = None

        upload_bps = None

        ping_ms = None

        packet_loss = None


        if isinstance(
            payload.get("download"),
            dict
        ):

            download_bps = payload[
                "download"
            ].get(
                "bandwidth"
            )


        if isinstance(
            payload.get("upload"),
            dict
        ):

            upload_bps = payload[
                "upload"
            ].get(
                "bandwidth"
            )


        if isinstance(
            payload.get("ping"),
            dict
        ):

            ping_ms = payload[
                "ping"
            ].get(
                "latency"
            )


            packet_loss = payload[
                "ping"
            ].get(
                "packetLoss"
            )


        # Ookla JSON menggunakan bandwidth bytes/sec.
        #
        # Konversi:
        # bytes/s -> bits/s -> Mbps
        #
        download_mbps = (

            (
                float(download_bps)
                *
                8
            )
            /
            1_000_000

            if download_bps is not None

            else

            None

        )


        upload_mbps = (

            (
                float(upload_bps)
                *
                8
            )
            /
            1_000_000

            if upload_bps is not None

            else

            None

        )


        server = (
            payload.get(
                "server"
            )
            if isinstance(
                payload.get(
                    "server"
                ),
                dict
            )
            else
            {}
        )


        server_name = (

            server.get(
                "name"
            )
            or
            server.get(
                "host"
            )

        )


        isp = (
            payload.get(
                "isp"
            )
        )


        return {

            "available":
                True,

            "running":
                False,

            "success":
                True,

            "download_mbps":
                round(
                    download_mbps,
                    2
                )
                if download_mbps is not None
                else
                None,

            "upload_mbps":
                round(
                    upload_mbps,
                    2
                )
                if upload_mbps is not None
                else
                None,

            "ping_ms":
                round(
                    float(ping_ms),
                    2
                )
                if ping_ms is not None
                else
                None,

            "packet_loss_percent":
                (
                    round(
                        float(packet_loss),
                        2
                    )
                    if packet_loss is not None
                    else
                    None
                ),

            "server":
                server_name,

            "isp":
                isp,

            "source":
                "Ookla Speedtest CLI",

            "message":
                "Speedtest berhasil."

        }


    except subprocess.TimeoutExpired:

        return {

            "available":
                True,

            "running":
                False,

            "success":
                False,

            "download_mbps":
                None,

            "upload_mbps":
                None,

            "ping_ms":
                None,

            "packet_loss_percent":
                None,

            "server":
                None,

            "isp":
                None,

            "source":
                "Ookla Speedtest CLI",

            "message":
                "Speedtest melebihi batas waktu."

        }


    except Exception as e:

        print(
            "INFO: Ookla Speedtest gagal: "
            f"{e}"
        )


        return {

            "available":
                True,

            "running":
                False,

            "success":
                False,

            "download_mbps":
                None,

            "upload_mbps":
                None,

            "ping_ms":
                None,

            "packet_loss_percent":
                None,

            "server":
                None,

            "isp":
                None,

            "source":
                "Ookla Speedtest CLI",

            "message":
                str(e)

        }


# ==========================================
# NETWORK SNAPSHOT
# ==========================================

def build_network_snapshot():

    started = time.perf_counter()


    # ======================================
    # LOCAL NETWORK
    # ======================================

    local_ip = get_local_ip()


    gateway = detect_default_gateway()


    network = get_interface_network(

        local_ip,

        gateway

    )


    neighbors = get_arp_neighbors()


    wifi = get_wifi_info()


    # ======================================
    # ACTIVE DISCOVERY
    # ======================================

    active_discovered = (

        active_network_discovery(

            network,

            known_neighbors=neighbors,

            local_ip=local_ip,

            gateway=gateway

        )

        if NETWORK_ACTIVE_DISCOVERY

        else

        {}

    )


    # ======================================
    # DEVICES
    # ======================================

    devices = build_device_list(

        local_ip,

        gateway,

        network,

        neighbors,

        active_discovered

    )


    devices = resolve_hostnames_parallel(
        devices
    )


    # ======================================
    # GATEWAY PING
    # ======================================

    gateway_online = False

    gateway_latency = None


    router = next(

        (

            device

            for device in devices

            if device.get(
                "role"
            )
            ==
            "router"

        ),

        None

    )


    if gateway:

        gateway_online, gateway_latency = (

            ping_host(

                gateway,

                timeout=1

            )

        )


        if router:

            router[
                "online"
            ] = gateway_online

            router[
                "latency_ms"
            ] = gateway_latency


    # ======================================
    # CLIENT DEVICE STATUS
    # ======================================

    active_devices = [

        device

        for device in devices

        if (

            device.get(
                "online"
            )

            and

            device.get(
                "role"
            )
            not in
            (
                "router",
                "local_device"
            )

        )

    ]


    known_devices = [

        device

        for device in devices

        if device.get(
            "role"
        )
        ==
        "device"

    ]


    # ======================================
    # BACKEND PUBLIC IP
    # ======================================

    server_public_ip = (
        get_public_ip()
    )


    # ======================================
    # ROUTER INFO
    # ======================================

    router_data = {

        "online":
            gateway_online,

        "ip":
            gateway,

        "mac":
            (
                router.get(
                    "mac"
                )
                if router
                else
                None
            ),

        "hostname":
            (
                router.get(
                    "hostname"
                )
                if router
                else
                None
            ),

        "latency_ms":
            gateway_latency,

        "vendor":
            (
                router.get(
                    "vendor"
                )
                if router
                else
                None
            ),

        "state":
            (
                router.get(
                    "state"
                )
                if router
                else
                None
            )

    }


    # ======================================
    # SPEEDTEST
    # ======================================

    speedtest = (
        run_ookla_speedtest()
        if NETWORK_SPEEDTEST_ENABLED
        else
        {

            "available":
                False,

            "running":
                False,

            "success":
                False,

            "download_mbps":
                None,

            "upload_mbps":
                None,

            "ping_ms":
                None,

            "packet_loss_percent":
                None,

            "server":
                None,

            "isp":
                None,

            "source":
                "Ookla Speedtest CLI",

            "message":
                "Speedtest tidak dijalankan."

        }
    )


    # ======================================
    # RESPONSE
    # ======================================

    return {

        "status":
            "success",

        "auto_detected":
            True,

        "source":
            "local_device",

        "timestamp":
            datetime.now(
                pytz.timezone(
                    "Asia/Jakarta"
                )
            ).isoformat(),

        "scan_time_ms":
            round(

                (
                    time.perf_counter()
                    -
                    started
                )
                *
                1000,

                1

            ),


        # ==================================
        # ROUTER
        # ==================================

        "router":
            router_data,


        "gateway":
            gateway,


        "gateway_ip":
            gateway,


        # ==================================
        # LOCAL
        # ==================================

        "local":
            {

                "ip":
                    local_ip,

                "network":
                    (
                        str(network)
                        if network
                        else
                        None
                    ),

                "prefix":
                    (
                        network.prefixlen
                        if network
                        else
                        None
                    ),

                "hostname":
                    socket.gethostname()

            },


        # ==================================
        # SERVER
        # ==================================

        "server":
            {

                "public_ip":
                    server_public_ip,

                "hostname":
                    socket.gethostname(),

                "platform":
                    platform.system(),

                "source":
                    "Flask backend"

            },


        # ==================================
        # WIFI
        # ==================================

        "wifi":
            wifi,


        "ssid":
            wifi.get(
                "ssid"
            ),


        "bssid":
            wifi.get(
                "bssid"
            ),


        "channel":
            wifi.get(
                "channel"
            ),


        "band":
            wifi.get(
                "band"
            ),


        "wifi_signal_percent":
            wifi.get(
                "signal_percent"
            ),


        "wifi_signal_dbm":
            wifi.get(
                "signal_dbm"
            ),


        "wifi_radio_type":
            wifi.get(
                "radio_type"
            ),


        "wifi_interface":
            wifi.get(
                "interface"
            ),


        "wifi_receive_mbps":
            wifi.get(
                "receive_mbps"
            ),


        "wifi_transmit_mbps":
            wifi.get(
                "transmit_mbps"
            ),


        # ==================================
        # SPEEDTEST
        # ==================================

        "speedtest":
            speedtest,


        "download_mbps":
            speedtest.get(
                "download_mbps"
            ),


        "upload_mbps":
            speedtest.get(
                "upload_mbps"
            ),


        "speedtest_ping_ms":
            speedtest.get(
                "ping_ms"
            ),


        "speedtest_server":
            speedtest.get(
                "server"
            ),


        "speedtest_isp":
            speedtest.get(
                "isp"
            ),


        # ==================================
        # CLIENT
        # ==================================

        #
        # Data client dikirim oleh browser
        # melalui /api/client-network.
        #
        "client":
            {

                "public_ip":
                    None,

                "isp":
                    None,

                "asn":
                    None,

                "org":
                    None,

                "city":
                    None,

                "region":
                    None,

                "country":
                    None,

                "browser":
                    None,

                "os":
                    None,

                "connection_type":
                    None,

                "downlink_mbps":
                    None,

                "rtt_ms":
                    None,

                "save_data":
                    None

            },


        # ==================================
        # DEVICES
        # ==================================

        "clients_count":
            len(
                active_devices
            ),


        "known_devices_count":
            len(
                known_devices
            ),


        "active_discovery":
            NETWORK_ACTIVE_DISCOVERY,


        "devices":
            sorted(

                devices,

                key=lambda x: (

                    0

                    if x.get(
                        "role"
                    )
                    ==
                    "local_device"

                    else

                    1

                    if x.get(
                        "role"
                    )
                    ==
                    "router"

                    else

                    2,

                    (
                        int(
                            ipaddress.ip_address(
                                x["ip"]
                            )
                        )

                        if x.get(
                            "ip"
                        )

                        else

                        0

                    )

                )

            ),


        # ==================================
        # CAPABILITIES
        # ==================================

        "capabilities":
            {

                "local_ip_detection":
                    True,

                "gateway_detection":
                    True,

                "subnet_detection":
                    True,

                "arp_discovery":
                    True,

                "neighbor_table_discovery":
                    True,

                "hostname_resolution":
                    True,

                "ping_gateway":
                    True,

                "wifi_ssid":
                    bool(
                        wifi.get(
                            "ssid"
                        )
                    ),

                "wifi_band":
                    bool(
                        wifi.get(
                            "band"
                        )
                    ),

                "wifi_channel":
                    bool(
                        wifi.get(
                            "channel"
                        )
                    ),

                "wifi_signal":
                    (
                        wifi.get(
                            "signal_percent"
                        )
                        is not None
                        or
                        wifi.get(
                            "signal_dbm"
                        )
                        is not None
                    ),

                "wifi_interface":
                    bool(
                        wifi.get(
                            "interface"
                        )
                    ),

                "ookla_speedtest":
                    bool(
                        speedtest.get(
                            "available"
                        )
                    ),

                "router_bandwidth":
                    bool(
                        speedtest.get(
                            "success"
                        )
                    ),

                "client_isp":
                    False,

                "client_public_ip":
                    "browser",

                "tr069":
                    False,

                "snmp":
                    False,

                "active_discovery":
                    NETWORK_ACTIVE_DISCOVERY,

                "full_subnet_scan":
                    NETWORK_ACTIVE_DISCOVERY

            },


        "message":
            (

                "Deteksi jaringan lokal berhasil. "

                "Gateway, LAN, ARP, hostname, dan Wi-Fi "
                "dibaca dari mesin tempat Flask berjalan. "

                "Informasi ISP client tidak diambil dari "
                "IP server backend; ISP akan ditentukan "
                "berdasarkan IP publik client yang dikirim "
                "oleh browser. "

                "Bandwidth aktual hanya diisi dari "
                "Ookla Speedtest CLI apabila tersedia "
                "dan NETWORK_SPEEDTEST=true."

            )

    }


# ==========================================
# NETWORK CACHE
# ==========================================

def get_network_snapshot(
    force=False
):

    now = time.time()


    with NETWORK_CACHE[
        "lock"
    ]:

        cached_data = (
            NETWORK_CACHE.get(
                "data"
            )
        )


        cached_timestamp = (
            NETWORK_CACHE.get(
                "timestamp",
                0
            )
        )


        cache_valid = (

            cached_data is not None

            and

            (
                now
                -
                cached_timestamp
            )
            <
            NETWORK_CACHE_TTL

        )


        if (

            not force

            and

            cache_valid

        ):

            return cached_data


        if NETWORK_CACHE.get(
            "building"
        ):

            if cached_data is not None:

                return cached_data


        NETWORK_CACHE[
            "building"
        ] = True


    try:

        data = (
            build_network_snapshot()
        )


        with NETWORK_CACHE[
            "lock"
        ]:

            NETWORK_CACHE[
                "data"
            ] = data

            NETWORK_CACHE[
                "timestamp"
            ] = time.time()

            NETWORK_CACHE[
                "building"
            ] = False


        return data


    except Exception:

        with NETWORK_CACHE[
            "lock"
        ]:

            NETWORK_CACHE[
                "building"
            ] = False


        raise


# ==========================================
# NETWORK PAGE
# ==========================================

@app.route(
    "/network"
)
def network_page():

    if 'user' not in session:

        return redirect(
            url_for(
                'login'
            )
        )


    return render_template(
        'network.html'
    )


# ==========================================
# CLIENT NETWORK API
# ==========================================

@app.route(
    '/api/client-network',
    methods=['POST']
)
def client_network_api():

    if 'user' not in session:

        return jsonify({

            "status":
                "error",

            "message":
                "Unauthorized"

        }), 401


    try:

        data = request.get_json(
            silent=True
        ) or {}


        public_ip = str(
            data.get(
                "public_ip",
                ""
            )
        ).strip()


        browser = str(
            data.get(
                "browser",
                ""
            )
        ).strip()


        operating_system = str(
            data.get(
                "os",
                ""
            )
        ).strip()


        connection_type = str(
            data.get(
                "connection_type",
                ""
            )
        ).strip()


        downlink = data.get(
            "downlink"
        )


        rtt = data.get(
            "rtt"
        )


        save_data = data.get(
            "save_data"
        )


        # ----------------------------------
        # VALIDATE PUBLIC IP
        # ----------------------------------

        valid_public_ip = None


        if public_ip:

            try:

                parsed = ipaddress.ip_address(
                    public_ip
                )


                if (
                    parsed.version
                    in
                    (
                        4,
                        6
                    )
                ):

                    valid_public_ip = (
                        public_ip
                    )

            except ValueError:

                pass


        # ----------------------------------
        # FALLBACK HEADER
        # ----------------------------------

        if not valid_public_ip:

            valid_public_ip = (
                get_request_public_ip()
            )


        # ----------------------------------
        # NUMBERS
        # ----------------------------------

        try:

            downlink_value = (

                float(
                    downlink
                )
                if downlink is not None
                else
                None

            )

        except (
            TypeError,
            ValueError
        ):

            downlink_value = None


        try:

            rtt_value = (

                float(
                    rtt
                )
                if rtt is not None
                else
                None

            )

        except (
            TypeError,
            ValueError
        ):

            rtt_value = None


        # ----------------------------------
        # ISP LOOKUP
        # ----------------------------------

        organization = (
            get_ip_organization(
                valid_public_ip
            )
        )


        client_data = {

            "public_ip":
                valid_public_ip,

            "isp":
                organization.get(
                    "isp"
                ),

            "asn":
                organization.get(
                    "asn"
                ),

            "org":
                organization.get(
                    "org"
                ),

            "domain":
                organization.get(
                    "domain"
                ),

            "city":
                organization.get(
                    "city"
                ),

            "region":
                organization.get(
                    "region"
                ),

            "country":
                organization.get(
                    "country"
                ),

            "browser":
                browser or None,

            "os":
                operating_system or None,

            "connection_type":
                connection_type or None,

            "downlink_mbps":
                downlink_value,

            "rtt_ms":
                rtt_value,

            "save_data":
                save_data,

            "received_at":
                datetime.now(
                    pytz.timezone(
                        "Asia/Jakarta"
                    )
                ).isoformat(),

            "source":
                "browser_client"

        }


        return jsonify({

            "status":
                "success",

            "client":
                client_data,

            "message":
                (
                    "Data client diterima dan ISP "
                    "ditentukan berdasarkan IP publik "
                    "client."
                )

        })


    except Exception as e:

        app.logger.exception(
            "Client network API error"
        )


        return jsonify({

            "status":
                "error",

            "message":
                str(e)

        }), 500


# ==========================================
# NETWORK DATA API
# ==========================================

@app.route(
    '/api/network-data'
)
def network_data_api():

    if 'user' not in session:

        return jsonify({

            "status":
                "error",

            "message":
                "Unauthorized"

        }), 401


    force = (

        request.args.get(
            'refresh',
            '0'
        )
        .lower()

        in

        (
            '1',
            'true',
            'yes'
        )

    )


    try:

        data = (
            get_network_snapshot(
                force=force
            )
        )


        return jsonify(
            data
        )


    except Exception as e:

        app.logger.exception(
            "Network discovery error"
        )


        return jsonify({

            "status":
                "error",

            "auto_detected":
                False,

            "message":
                "Gagal mendeteksi jaringan lokal: "
                +
                str(e)

        }), 500


# ==========================================
# MERGE CLIENT DATA KE NETWORK DATA
# ==========================================

@app.route(
    '/api/network-client-merge',
    methods=['POST']
)
def network_client_merge():

    """
    Endpoint alternatif apabila network.html ingin
    mengirim data client dan langsung menerima
    snapshot lengkap.

    Browser mengirim public IP + metadata.
    Backend kemudian:
        1. lookup ISP client
        2. ambil snapshot LAN/Wi-Fi
        3. gabungkan semuanya
    """

    if 'user' not in session:

        return jsonify({

            "status":
                "error",

            "message":
                "Unauthorized"

        }), 401


    try:

        client_payload = (
            request.get_json(
                silent=True
            )
            or
            {}
        )


        public_ip = str(
            client_payload.get(
                "public_ip",
                ""
            )
        ).strip()


        browser = str(
            client_payload.get(
                "browser",
                ""
            )
        ).strip()


        operating_system = str(
            client_payload.get(
                "os",
                ""
            )
        ).strip()


        connection_type = str(
            client_payload.get(
                "connection_type",
                ""
            )
        ).strip()


        downlink = client_payload.get(
            "downlink"
        )


        rtt = client_payload.get(
            "rtt"
        )


        save_data = client_payload.get(
            "save_data"
        )


        if public_ip:

            try:

                ipaddress.ip_address(
                    public_ip
                )

            except ValueError:

                public_ip = (
                    get_request_public_ip()
                )

        else:

            public_ip = (
                get_request_public_ip()
            )


        organization = (
            get_ip_organization(
                public_ip
            )
        )


        try:

            downlink = (
                float(
                    downlink
                )
                if downlink is not None
                else
                None
            )

        except:

            downlink = None


        try:

            rtt = (
                float(
                    rtt
                )
                if rtt is not None
                else
                None
            )

        except:

            rtt = None


        snapshot = (
            get_network_snapshot(
                force=True
            )
        )


        snapshot[
            "client"
        ] = {

            "public_ip":
                public_ip,

            "isp":
                organization.get(
                    "isp"
                ),

            "asn":
                organization.get(
                    "asn"
                ),

            "org":
                organization.get(
                    "org"
                ),

            "domain":
                organization.get(
                    "domain"
                ),

            "city":
                organization.get(
                    "city"
                ),

            "region":
                organization.get(
                    "region"
                ),

            "country":
                organization.get(
                    "country"
                ),

            "browser":
                browser or None,

            "os":
                operating_system or None,

            "connection_type":
                connection_type or None,

            "downlink_mbps":
                downlink,

            "rtt_ms":
                rtt,

            "save_data":
                save_data,

            "source":
                "browser_client"

        }


        snapshot[
            "capabilities"
        ][
            "client_isp"
        ] = bool(
            organization.get(
                "isp"
            )
        )


        return jsonify(
            snapshot
        )


    except Exception as e:

        app.logger.exception(
            "Network client merge error"
        )


        return jsonify({

            "status":
                "error",

            "message":
                str(e)

        }), 500


# ==========================================
# FORCE NETWORK REFRESH
# ==========================================

@app.route(
    '/api/network-refresh',
    methods=['POST']
)
def network_refresh_api():

    if 'user' not in session:

        return jsonify({

            "status":
                "error",

            "message":
                "Unauthorized"

        }), 401


    try:

        data = (
            get_network_snapshot(
                force=True
            )
        )


        return jsonify(
            data
        )


    except Exception as e:

        app.logger.exception(
            "Forced network discovery error"
        )


        return jsonify({

            "status":
                "error",

            "message":
                "Gagal melakukan refresh "
                "jaringan lokal: "
                +
                str(e)

        }), 500
