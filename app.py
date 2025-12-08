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
    """Mengambil data gempa dirasakan dari API BMKG"""
    try:
        url = "https://data.bmkg.go.id/DataMKG/TEWS/gempadirasakan.json"
        response = requests.get(url, timeout=3)
        if response.status_code == 200:
            data = response.json()
            return data['Infogempa']['gempa'][0]
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
    
    provinsi_tersedia = []

    if siaran_data:
        provinsi_tersedia = list(siaran_data.keys())
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

    return render_template('index.html', 
                           most_common_siaran_name=most_common_siaran_name,
                           most_common_siaran_count=most_common_siaran_count,
                           jumlah_wilayah_layanan=jumlah_wilayah_layanan,
                           jumlah_siaran=jumlah_siaran, 
                           jumlah_penyelenggara_mux=jumlah_penyelenggara_mux, 
                           last_updated_time=last_updated_time,
                           gempa_data=gempa_data,
                           provinsi_tersedia=provinsi_tersedia)

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
@app.route('/faq')
def faq(): return render_template('faq.html')
@app.route('/about')
def about(): return render_template('about.html')

# --- AUTH & CRUD ---
def hash_password(password): return hashlib.sha256(password.encode()).hexdigest()

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("identifier")
        users_ref = db.reference("users")
        users = users_ref.get() or {}
        found_uid = None
        for uid, user in users.items():
            if user.get("email", "").lower() == email.lower():
                found_uid = uid; break
        if found_uid:
            otp = str(random.randint(100000, 999999))
            db.reference(f"otp/{found_uid}").set({"email": email, "otp": otp})
            try:
                msg = Message("Reset Password", recipients=[email])
                msg.body = f"OTP: {otp}"
                mail.send(msg)
                session["reset_uid"] = found_uid
                return redirect(url_for("verify_otp"))
            except: pass
    return render_template("forgot-password.html")

@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    uid = session.get("reset_uid")
    if request.method == "POST":
        if db.reference(f"otp/{uid}").get().get("otp") == request.form.get("otp"):
            return redirect(url_for("reset_password"))
    return render_template("verify-otp.html")

@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    uid = session.get("reset_uid")
    if request.method == "POST":
        hashed_pw = hashlib.sha256(request.form.get("password").encode()).hexdigest()
        db.reference(f"users/{uid}").update({"password": hashed_pw})
        session.pop("reset_uid", None)
        return redirect(url_for("login"))
    return render_template("reset-password.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")
        otp = str(random.randint(100000, 999999))
        db.reference(f"pending_users/{username}").set({
            "nama": request.form.get("nama"), "email": email,
            "password": hashlib.sha256(password.encode()).hexdigest(), "otp": otp
        })
        try:
            msg = Message("Verifikasi", recipients=[email])
            msg.body = f"OTP: {otp}"
            mail.send(msg)
            session["pending_username"] = username
            return redirect(url_for("verify_register"))
        except: pass
    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    username = session.get("pending_username")
    if request.method == "POST":
        data = db.reference(f"pending_users/{username}").get()
        if data and data.get("otp") == request.form.get("otp"):
            db.reference(f"users/{username}").set({
                "nama": data["nama"], "email": data["email"],
                "password": data["password"], "points": 0
            })
            db.reference(f"pending_users/{username}").delete()
            session.pop("pending_username", None)
            return redirect(url_for("login"))
    return render_template("verify-register.html", username=username)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        hashed_pw = hashlib.sha256(request.form['password'].strip().encode()).hexdigest()
        user_data = db.reference(f'users/{username}').get()
        if user_data and user_data.get('password') == hashed_pw:
            session['user'] = username
            session['nama'] = user_data.get("nama", "Pengguna")
            return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    return render_template("dashboard.html", name=session.get('nama'), provinsi_list=list((db.reference("provinsi").get() or {}).values()))

@app.route("/daftar-siaran")
def daftar_siaran():
    return render_template("daftar-siaran.html", provinsi_list=list((db.reference("provinsi").get() or {}).values()))

@app.route("/add_data", methods=["GET", "POST"])
def add_data():
    if 'user' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        provinsi = request.form['provinsi']
        wilayah = request.form['wilayah']
        mux = request.form['mux']
        siaran = sorted([s.strip() for s in request.form['siaran'].split(',')])
        now = datetime.now(pytz.timezone('Asia/Jakarta'))
        db.reference(f"siaran/{provinsi}/{wilayah}/{mux}").set({
            "siaran": siaran, "last_updated_by_username": session.get('user'),
            "last_updated_by_name": session.get('nama'),
            "last_updated_date": now.strftime("%d-%m-%Y"),
            "last_updated_time": now.strftime("%H:%M:%S WIB")
        })
        return redirect(url_for('dashboard'))
    return render_template('add_data_form.html', provinsi_list=list((db.reference("provinsi").get() or {}).values()))

@app.route("/edit_data/<provinsi>/<wilayah>/<mux>", methods=["GET", "POST"])
def edit_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    provinsi = provinsi.replace('%20',' ')
    wilayah = wilayah.replace('%20', ' ')
    mux = mux.replace('%20', ' ')
    if request.method == 'POST':
        siaran = sorted([s.strip() for s in request.form['siaran'].split(',')])
        now = datetime.now(pytz.timezone('Asia/Jakarta'))
        db.reference(f"siaran/{provinsi}/{wilayah}/{mux}").update({
            "siaran": siaran, "last_updated_by_username": session.get('user'),
            "last_updated_by_name": session.get('nama'),
            "last_updated_date": now.strftime("%d-%m-%Y"),
            "last_updated_time": now.strftime("%H:%M:%S WIB")
        })
        return redirect(url_for('dashboard'))
    return render_template('edit_data_form.html', provinsi=provinsi, wilayah=wilayah, mux=mux)

@app.route("/delete_data/<provinsi>/<wilayah>/<mux>", methods=["POST"])
def delete_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    db.reference(f"siaran/{provinsi}/{wilayah}/{mux}").delete()
    return redirect(url_for('dashboard'))

@app.route("/get_wilayah")
def get_wilayah(): return jsonify({"wilayah": list((db.reference(f"siaran/{request.args.get('provinsi')}").get() or {}).keys())})
@app.route("/get_mux")
def get_mux(): return jsonify({"mux": list((db.reference(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}").get() or {}).keys())})
@app.route("/get_siaran")
def get_siaran(): return jsonify(db.reference(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}/{request.args.get('mux')}").get() or {})
@app.route('/logout')
def logout(): session.pop('user', None); return redirect(url_for('login'))
@app.route('/berita')
def berita():
    feed = feedparser.parse('https://news.google.com/rss/search?q=tv+digital&hl=id&gl=ID&ceid=ID:id')
    return render_template('berita.html', articles=feed.entries[:5], page=1, total_pages=1)

if __name__ == "__main__":
    app.run(debug=True)
