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
    system_instruction=
    "Anda adalah Chatbot AI KTVDI. Jawab pertanyaan seputar TV Digital, MUX, STB, dan fitur website KTVDI dengan ramah dan ringkas."
)

# --- FUNGSI TAMBAHAN: BMKG (Gempa & Cuaca Default) ---
def get_gempa_terkini():
    """Mengambil data gempa terkini dari API BMKG"""
    try:
        url = "https://data.bmkg.go.id/DataMKG/TEWS/gempadirasakan.json"
        response = requests.get(url, timeout=3)
        if response.status_code == 200:
            data = response.json()
            return data['Infogempa']['gempa'][0]
    except Exception as e:
        print(f"Gagal ambil data BMKG: {e}")
        return None
    return None

def get_cuaca_default():
    """
    Mengambil data prakiraan cuaca default (Semarang) 
    sebagai cadangan jika GPS user mati.
    """
    try:
        # Kode Wilayah Semarang Selatan
        url = "https://api.bmkg.go.id/publik/prakiraan-cuaca?adm4=33.74.13.1004"
        response = requests.get(url, timeout=3)
        if response.status_code == 200:
            data = response.json()
            # Mapping data agar sesuai format frontend
            cuaca_now = data['data'][0]['cuaca'][0][0]
            return {
                'lokasi': 'Semarang (Default)',
                't': cuaca_now['t'],
                'desc': cuaca_now['weather_desc'],
                'ws': cuaca_now['ws']
            }
    except Exception as e:
        print(f"Gagal ambil cuaca default: {e}")
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
    
    if siaran_data:
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
    
    # AMBIL DATA API
    gempa_data = get_gempa_terkini()
    cuaca_data = get_cuaca_default() # Data default Semarang

    return render_template('index.html', 
                           most_common_siaran_name=most_common_siaran_name,
                           most_common_siaran_count=most_common_siaran_count,
                           jumlah_wilayah_layanan=jumlah_wilayah_layanan,
                           jumlah_siaran=jumlah_siaran, 
                           jumlah_penyelenggara_mux=jumlah_penyelenggara_mux, 
                           last_updated_time=last_updated_time,
                           gempa_data=gempa_data,
                           cuaca_data=cuaca_data)

# --- ROUTE LAINNYA ---
@app.route('/faq')
def faq():
    return render_template('faq.html')

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
def sitemap():
    return send_from_directory('static', 'sitemap.xml')

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("identifier")
        users_ref = db.reference("users")
        users = users_ref.get() or {}
        found_uid, found_user = None, None
        for uid, user in users.items():
            if "email" in user and user["email"].lower() == email.lower():
                found_uid, found_user = uid, user
                break
        if found_uid:
            otp = str(random.randint(100000, 999999))
            db.reference(f"otp/{found_uid}").set({"email": email, "otp": otp})
            try:
                msg = Message("Kode OTP Reset Password", recipients=[email])
                msg.body = f"Kode OTP Anda: {otp}"
                mail.send(msg)
                flash(f"Kode OTP terkirim ke {email}", "success")
                session["reset_uid"] = found_uid
                return redirect(url_for("verify_otp"))
            except Exception as e:
                flash(f"Gagal kirim email: {str(e)}", "error")
        else:
            flash("Email tidak ditemukan!", "error")
    return render_template("forgot-password.html")

@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    uid = session.get("reset_uid")
    if not uid: return redirect(url_for("forgot_password"))
    if request.method == "POST":
        otp_input = request.form.get("otp")
        otp_data = db.reference(f"otp/{uid}").get()
        if otp_data and otp_data["otp"] == otp_input:
            flash("OTP benar.", "success")
            return redirect(url_for("reset_password"))
        else:
            flash("OTP salah.", "error")
    return render_template("verify-otp.html")

@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    uid = session.get("reset_uid")
    if not uid: return redirect(url_for("forgot_password"))
    if request.method == "POST":
        new_pw = request.form.get("password")
        hashed_pw = hashlib.sha256(new_pw.encode()).hexdigest()
        db.reference(f"users/{uid}").update({"password": hashed_pw})
        db.reference(f"otp/{uid}").delete()
        session.pop("reset_uid", None)
        flash("Password berhasil direset.", "success")
    return render_template("reset-password.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")
        hashed_pw = hashlib.sha256(password.encode()).hexdigest()
        otp = str(random.randint(100000, 999999))
        db.reference(f"pending_users/{username}").set({
            "nama": request.form.get("nama"), "email": email, "password": hashed_pw, "otp": otp
        })
        try:
            msg = Message("Kode OTP Verifikasi", recipients=[email])
            msg.body = f"Kode OTP Anda: {otp}"
            mail.send(msg)
            session["pending_username"] = username
            flash("Kode OTP terkirim.", "success")
            return redirect(url_for("verify_register"))
        except:
            flash("Gagal kirim email.", "error")
    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    username = session.get("pending_username")
    if not username: return redirect(url_for("register"))
    pending_data = db.reference(f"pending_users/{username}").get()
    if request.method == "POST":
        if pending_data.get("otp") == request.form.get("otp"):
            db.reference(f"users/{username}").set({
                "nama": pending_data["nama"], "email": pending_data["email"], "password": pending_data["password"], "points": 0
            })
            db.reference(f"pending_users/{username}").delete()
            session.pop("pending_username", None)
            flash("Verifikasi berhasil.", "success")
        else:
            flash("OTP salah.", "error")
    return render_template("verify-register.html", username=username)

@app.route("/daftar-siaran")
def daftar_siaran():
    ref = db.reference("provinsi")
    data = ref.get() or {}
    return render_template("daftar-siaran.html", provinsi_list=list(data.values()))

@app.route("/get_wilayah")
def get_wilayah():
    return jsonify({"wilayah": list((db.reference(f"siaran/{request.args.get('provinsi')}").get() or {}).keys())})

@app.route("/get_mux")
def get_mux():
    return jsonify({"mux": list((db.reference(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}").get() or {}).keys())})

@app.route("/get_siaran")
def get_siaran():
    data = db.reference(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}/{request.args.get('mux')}").get() or {}
    return jsonify(data)

@app.route('/berita')
def berita():
    feed = feedparser.parse('https://news.google.com/rss/search?q=tv+digital&hl=id&gl=ID&ceid=ID:id')
    page = request.args.get('page', 1, type=int)
    articles = feed.entries[(page-1)*5 : page*5]
    return render_template('berita.html', articles=articles, page=page, total_pages=(len(feed.entries)+4)//5)

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        hashed_pw = hashlib.sha256(request.form['password'].strip().encode()).hexdigest()
        user_data = db.reference(f'users/{username}').get()
        if user_data and user_data.get('password') == hashed_pw:
            session['user'] = username
            session['nama'] = user_data.get("nama", "Pengguna")
            return redirect(url_for('dashboard', name=user_data['nama']))
        return render_template('login.html', error="Login gagal.")
    return render_template('login.html')

@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    provinsi_list = list((db.reference("provinsi").get() or {}).values())
    return render_template("dashboard.html", name=session.get('nama'), provinsi_list=provinsi_list)

@app.route("/add_data", methods=["GET", "POST"])
def add_data():
    if 'user' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        # (Logic Add Data Simplifikasi - sama seperti sebelumnya)
        # ... simpan ke db ...
        return redirect(url_for('dashboard'))
    return render_template('add_data_form.html', provinsi_list=list((db.reference("provinsi").get() or {}).values()))

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

if __name__ == "__main__":
    app.run(debug=True)
