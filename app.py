import os
import hashlib
import firebase_admin
import random
import re
import pytz
import time
import requests
import feedparser
import google.generativeai as genai
from firebase_admin import credentials, db
from flask import Flask, request, render_template, redirect, url_for, session, flash, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
from flask_mail import Mail, Message
from datetime import datetime
from collections import Counter

# Muat variabel lingkungan
load_dotenv()

app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")

# Inisialisasi Firebase
try:
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

    firebase_admin.initialize_app(cred, {
        'databaseURL': os.environ.get('DATABASE_URL')
    })

    ref = db.reference('/')
    print("✅ Firebase berhasil terhubung!")

except Exception as e:
    print("❌ Error initializing Firebase:", str(e))
    ref = None

# Inisialisasi Email
app.config['MAIL_SERVER'] = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
app.config['MAIL_PORT'] = int(os.environ.get("MAIL_PORT", 587))
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD")
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")

mail = Mail(app)

# Konfigurasi Gemini API Key
genai.configure(api_key=os.environ.get("GEMINI_APP_KEY"))

# Inisialisasi model Gemini
model = genai.GenerativeModel(
    "gemini-2.5-flash", 
    system_instruction="Anda adalah Chatbot AI KTVDI..."
)

# --- FUNGSI TAMBAHAN: BMKG ---
def get_gempa_terkini():
    try:
        url = "https://data.bmkg.go.id/DataMKG/TEWS/gempadirasakan.json"
        response = requests.get(url, timeout=3)
        if response.status_code == 200:
            data = response.json()
            return data['Infogempa']['gempa'][0]
    except Exception as e:
        return None
    return None

def get_cuaca_semarang():
    try:
        url = "https://api.bmkg.go.id/publik/prakiraan-cuaca?adm4=33.74.13.1004"
        response = requests.get(url, timeout=3)
        if response.status_code == 200:
            data = response.json()
            return data['data'][0]['cuaca'][0][0]
    except Exception as e:
        return None
    return None

# --- ROUTE UTAMA ---
@app.route("/")
def home():
    ref = db.reference('siaran')
    siaran_data = ref.get()

    jumlah_wilayah_layanan = 0
    jumlah_siaran = 0
    jumlah_penyelenggara_mux = 0
    siaran_counts = Counter()
    last_updated_time = None
    
    # List provinsi yang ada di database untuk pengecekan lokasi user
    provinsi_tersedia = []

    if siaran_data:
        provinsi_tersedia = list(siaran_data.keys()) # Ambil daftar provinsi
        for provinsi, provinsi_data in siaran_data.items():
            if isinstance(provinsi_data, dict):
                jumlah_wilayah_layanan += len(provinsi_data)
                for wilayah, wilayah_data in provinsi_data.items():
                    if isinstance(wilayah_data, dict):
                        jumlah_penyelenggara_mux += len(wilayah_data)
                        for penyelenggara, penyelenggara_details in wilayah_data.items():
                            if 'siaran' in penyelenggara_details:
                                jumlah_siaran += len(penyelenggara_details['siaran'])
                                for siaran in penyelenggara_details['siaran']:
                                    siaran_counts[siaran.lower()] += 1
                            if 'last_updated_date' in penyelenggara_details:
                                current_updated_time_str = penyelenggara_details['last_updated_date']
                                try:
                                    current_updated_time = datetime.strptime(current_updated_time_str, '%d-%m-%Y')
                                except ValueError:
                                    current_updated_time = None
                                if current_updated_time and (last_updated_time is None or current_updated_time > last_updated_time):
                                    last_updated_time = current_updated_time

    if siaran_counts:
        most_common_siaran = siaran_counts.most_common(1)[0]
        most_common_siaran_name = most_common_siaran[0].upper()
        most_common_siaran_count = most_common_siaran[1]
    else:
        most_common_siaran_name = None
        most_common_siaran_count = 0

    if last_updated_time:
        last_updated_time = last_updated_time.strftime('%d-%m-%Y')
    
    gempa_data = get_gempa_terkini()
    cuaca_data = get_cuaca_semarang()

    return render_template('index.html', 
                           most_common_siaran_name=most_common_siaran_name,
                           most_common_siaran_count=most_common_siaran_count,
                           jumlah_wilayah_layanan=jumlah_wilayah_layanan,
                           jumlah_siaran=jumlah_siaran, 
                           jumlah_penyelenggara_mux=jumlah_penyelenggara_mux, 
                           last_updated_time=last_updated_time,
                           gempa_data=gempa_data,
                           cuaca_data=cuaca_data,
                           provinsi_tersedia=provinsi_tersedia) # Kirim list provinsi ke frontend

# --- ROUTE LAINNYA ---
@app.route('/faq')
def faq(): return render_template('faq.html')

@app.route('/', methods=['POST'])
def chatbot():
    data = request.get_json()
    prompt = data.get("prompt")
    try:
        response = model.generate_content(prompt)
        return jsonify({"response": response.text})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/sitemap.xml')
def sitemap(): return send_from_directory('static', 'sitemap.xml')

# --- AUTH ROUTES (Sama seperti sebelumnya) ---
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    # ... (Kode forgot password sama seperti sebelumnya)
    return render_template("forgot-password.html")

@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    # ... (Kode verify otp sama seperti sebelumnya)
    return render_template("verify-otp.html")

@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    # ... (Kode reset password sama seperti sebelumnya)
    return render_template("reset-password.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    # ... (Kode register sama seperti sebelumnya)
    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    # ... (Kode verify register sama seperti sebelumnya)
    return render_template("verify-register.html")

@app.route('/login', methods=['GET', 'POST'])
def login():
    error_message = None
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()
        hashed_password = hash_password(password)
        ref = db.reference('users')
        try:
            user_data = ref.child(username).get()
            if not user_data:
                error_message = "Username tidak ditemukan."
                return render_template('login.html', error=error_message)
            if user_data.get('password') == hashed_password:
                session['user'] = username
                session['nama'] = user_data.get("nama", "Pengguna")
                return redirect(url_for('dashboard'))
            error_message = "Password salah."
        except Exception as e:
            error_message = f"Error: {str(e)}"
    return render_template('login.html', error=error_message)

# --- DASHBOARD & CRUD (Sama seperti sebelumnya) ---
@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    provinsi_list = list((db.reference("provinsi").get() or {}).values())
    return render_template("dashboard.html", name=session.get('nama'), provinsi_list=provinsi_list)

@app.route("/daftar-siaran")
def daftar_siaran():
    provinsi_list = list((db.reference("provinsi").get() or {}).values())
    return render_template("daftar-siaran.html", provinsi_list=provinsi_list)

# ... (Route API get_wilayah, get_mux, get_siaran, add_data, edit_data, delete_data tetap sama) ...
# Agar tidak kepanjangan, bagian CRUD API yang tidak berubah saya singkat komentarnya, 
# tapi pastikan di file asli tetap ada.

@app.route('/berita')
def berita():
    feed = feedparser.parse('https://news.google.com/rss/search?q=tv+digital&hl=id&gl=ID&ceid=ID:id')
    page = request.args.get('page', 1, type=int)
    articles_per_page = 5
    articles = feed.entries[(page-1)*articles_per_page : page*articles_per_page]
    return render_template('berita.html', articles=articles, page=page, total_pages=(len(feed.entries)+4)//5)

@app.route('/about')
def about(): return render_template('about.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

if __name__ == "__main__":
    app.run(debug=True)
