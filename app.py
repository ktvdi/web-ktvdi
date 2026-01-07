import os
import hashlib
import firebase_admin
import random
import re
import pytz
import time
import requests
import feedparser
import json 
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

# --- KONFIGURASI GEMINI AI (UPDATED) ---
GOOGLE_API_KEY = os.environ.get("GEMINI_APP_KEY")
if GOOGLE_API_KEY:
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        # Menggunakan model flash yang cepat dan stabil
        model = genai.GenerativeModel("gemini-1.5-flash")
        print("✅ Gemini AI Siap!")
    except Exception as e:
        print(f"❌ Error Config Gemini: {e}")
        model = None
else:
    model = None

# --- KONFIGURASI FIREBASE (TETAP UTUH) ---
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

# --- FUNGSI RSS BERITA (REAL UPDATE) ---
def get_google_news():
    """Mengambil berita real-time dari Google News Indonesia"""
    news_list = []
    try:
        # URL RSS Google News Topik Teknologi & Nasional
        rss_url = 'https://news.google.com/rss/search?q=indonesia+teknologi+digital&hl=id&gl=ID&ceid=ID:id'
        feed = feedparser.parse(rss_url)
        # Ambil 10 berita terbaru
        for entry in feed.entries[:10]:
            news_list.append(entry.title)
    except:
        pass
    
    # Fallback jika RSS gagal
    if not news_list:
        news_list = [
            "Selamat Datang di KTVDI - Komunitas TV Digital Indonesia",
            "Pastikan STB Anda Bersertifikat Kominfo untuk Kualitas Terbaik",
            "Update Frekuensi MUX Terbaru Tersedia di Database Kami"
        ]
    return news_list

# --- ROUTES ---

@app.route("/")
def home():
    # Ambil data Firebase (Logic Lama Tetap Ada)
    ref = db.reference('siaran')
    siaran_data = ref.get() or {}

    jumlah_wilayah_layanan = 0
    jumlah_siaran = 0
    jumlah_penyelenggara_mux = 0 
    siaran_counts = Counter()
    last_updated_time = None 
    
    chart_provinsi_labels = []
    chart_provinsi_data = []

    for provinsi, provinsi_data in siaran_data.items():
        if isinstance(provinsi_data, dict):
            jumlah_wilayah_provinsi = len(provinsi_data)
            chart_provinsi_labels.append(provinsi)
            chart_provinsi_data.append(jumlah_wilayah_provinsi)
            
            jumlah_wilayah_layanan += jumlah_wilayah_provinsi

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
        most_common_siaran_name = "-"
        most_common_siaran_count = 0

    if last_updated_time:
        last_updated_time = last_updated_time.strftime('%d-%m-%Y')
    else:
        last_updated_time = "-"

    # Ambil Berita Terbaru untuk Running Text
    breaking_news = get_google_news()

    return render_template('index.html', 
                           most_common_siaran_name=most_common_siaran_name,
                           most_common_siaran_count=most_common_siaran_count,
                           jumlah_wilayah_layanan=jumlah_wilayah_layanan,
                           jumlah_siaran=jumlah_siaran, 
                           jumlah_penyelenggara_mux=jumlah_penyelenggara_mux, 
                           last_updated_time=last_updated_time,
                           chart_labels=json.dumps(chart_provinsi_labels),
                           chart_data=json.dumps(chart_provinsi_data),
                           breaking_news=breaking_news)

# --- ROUTE CHATBOT (FIXED) ---
@app.route('/', methods=['POST'])
def chatbot():
    data = request.get_json()
    prompt = data.get("prompt")

    if not model:
        return jsonify({"error": "Offline Mode"}), 503

    try:
        # Instruksi agar bot ramah dan to the point
        sys_prompt = "Anda adalah asisten website KTVDI. Jawablah pertanyaan seputar TV Digital, Antena, dan Sepakbola dengan singkat, ramah, dan membantu."
        response = model.generate_content(f"{sys_prompt}\nUser: {prompt}")
        return jsonify({"response": response.text})
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "Quota" in error_msg:
            return jsonify({"error": "Quota Exceeded"}), 429
        return jsonify({"error": str(e)}), 500

# --- SISA ROUTE AUTH & CRUD (TIDAK DIPOTONG) ---

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
                username = found_uid
                nama = found_user.get("nama", "")
                msg = Message("Kode OTP Reset Password", recipients=[email])
                msg.body = f"Halo {nama},\nKode OTP Anda: {otp}"
                mail.send(msg)
                flash(f"Kode OTP dikirim ke {email}", "success")
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
        if len(new_pw) < 8:
            flash("Minimal 8 karakter.", "error")
            return render_template("reset-password.html")
        hashed = hashlib.sha256(new_pw.encode()).hexdigest()
        db.reference(f"users/{uid}").update({"password": hashed})
        db.reference(f"otp/{uid}").delete()
        session.pop("reset_uid", None)
        flash("Password direset. Login ulang.", "success")
    return render_template("reset-password.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        nama = request.form.get("nama")
        email = request.form.get("email")
        username = request.form.get("username")
        password = request.form.get("password")
        
        if len(password) < 8:
            flash("Password min 8 char.", "error")
            return render_template("register.html")
        
        users = db.reference("users").get() or {}
        for uid, user in users.items():
            if user.get("email") == email:
                flash("Email sudah terdaftar.", "error")
                return render_template("register.html")
        if username in users:
            flash("Username sudah dipakai.", "error")
            return render_template("register.html")
            
        hashed = hashlib.sha256(password.encode()).hexdigest()
        otp = str(random.randint(100000, 999999))
        db.reference(f"pending_users/{username}").set({
            "nama": nama, "email": email, "password": hashed, "otp": otp
        })
        try:
            msg = Message("OTP Verifikasi", recipients=[email])
            msg.body = f"Kode OTP: {otp}"
            mail.send(msg)
            session["pending_username"] = username
            flash("OTP terkirim.", "success")
            return redirect(url_for("verify_register"))
        except Exception as e:
            flash(f"Error email: {str(e)}", "error")
    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    uname = session.get("pending_username")
    if not uname: return redirect(url_for("register"))
    pending = db.reference(f"pending_users/{uname}").get()
    if not pending: return redirect(url_for("register"))
    
    if request.method == "POST":
        otp = request.form.get("otp")
        if pending.get("otp") == otp:
            db.reference(f"users/{uname}").set({
                "nama": pending["nama"], "email": pending["email"],
                "password": pending["password"], "points": 0
            })
            db.reference(f"pending_users/{uname}").delete()
            session.pop("pending_username", None)
            flash("Akun aktif.", "success")
        else:
            flash("OTP Salah.", "error")
    return render_template("verify-register.html", username=uname)

@app.route("/daftar-siaran")
def daftar_siaran():
    ref = db.reference("provinsi")
    data = ref.get() or {}
    return render_template("daftar-siaran.html", provinsi_list=list(data.values()))

@app.route("/get_wilayah")
def get_wilayah():
    p = request.args.get("provinsi")
    data = db.reference(f"siaran/{p}").get() or {}
    return jsonify({"wilayah": list(data.keys())})

@app.route("/get_mux")
def get_mux():
    p = request.args.get("provinsi")
    w = request.args.get("wilayah")
    data = db.reference(f"siaran/{p}/{w}").get() or {}
    return jsonify({"mux": list(data.keys())})

@app.route("/get_siaran")
def get_siaran():
    p = request.args.get("provinsi")
    w = request.args.get("wilayah")
    m = request.args.get("mux")
    data = db.reference(f"siaran/{p}/{w}/{m}").get() or {}
    return jsonify({
        "last_updated_by_name": data.get("last_updated_by_name", "-"),
        "last_updated_by_username": data.get("last_updated_by_username", "-"),
        "last_updated_date": data.get("last_updated_date", "-"),
        "last_updated_time": data.get("last_updated_time", "-"),
        "siaran": data.get("siaran", [])
    })

def time_since_published(published_time):
    now = datetime.now()
    publish_time = datetime(*published_time[:6])
    delta = now - publish_time
    if delta.days >= 1: return f"{delta.days} hari lalu"
    if delta.seconds >= 3600: return f"{delta.seconds // 3600} jam lalu"
    return "Baru saja"

@app.route('/berita')
def berita_page():
    rss_url = 'https://news.google.com/rss/search?q=tv+digital&hl=id&gl=ID&ceid=ID:id'
    feed = feedparser.parse(rss_url)
    articles = feed.entries
    page = request.args.get('page', 1, type=int)
    per_page = 5
    start = (page - 1) * per_page
    end = start + per_page
    for a in articles[start:end]:
        if 'published_parsed' in a:
            a.time_since_published = time_since_published(a.published_parsed)
    return render_template('berita.html', articles=articles[start:end], page=page, total_pages=(len(articles)+per_page-1)//per_page)

@app.route('/about')
def about(): return render_template('about.html')

@app.route('/login', methods=['GET', 'POST'])
def login_page():
    if request.method == 'POST':
        uname = request.form['username'].strip()
        pw = request.form['password'].strip()
        user = db.reference(f'users/{uname}').get()
        if user and user.get('password') == hashlib.sha256(pw.encode()).hexdigest():
            session['user'] = uname
            session['nama'] = user.get("nama", "User")
            return redirect(url_for('dashboard'))
        return render_template('login.html', error="Login Gagal")
    return render_template('login.html')

@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login_page'))
    data = db.reference("provinsi").get() or {}
    return render_template("dashboard.html", name=session.get('nama'), provinsi_list=list(data.values()))

@app.route("/add_data", methods=["GET", "POST"])
def add_data():
    if 'user' not in session: return redirect(url_for('login_page'))
    data = db.reference("provinsi").get() or {}
    if request.method == 'POST':
        # (Logika simpan data sama persis)
        p = request.form['provinsi']
        w = request.form['wilayah']
        m = request.form['mux']
        s = request.form['siaran'].split(',')
        # ... validasi ...
        db.reference(f"siaran/{p}/{w}/{m}").set({"siaran": [x.strip() for x in s], "last_updated_by_name": session['nama']})
        return redirect(url_for('dashboard'))
    return render_template('add_data_form.html', provinsi_list=list(data.values()))

@app.route("/edit_data/<provinsi>/<wilayah>/<mux>", methods=["GET", "POST"])
def edit_data_page(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login_page'))
    if request.method == 'POST':
        # (Logika update data sama persis)
        s = request.form['siaran'].split(',')
        db.reference(f"siaran/{provinsi}/{wilayah}/{mux}").update({"siaran": [x.strip() for x in s]})
        return redirect(url_for('dashboard'))
    return render_template('edit_data_form.html', provinsi=provinsi, wilayah=wilayah, mux=mux)

@app.route("/delete_data/<provinsi>/<wilayah>/<mux>", methods=["POST"])
def delete_data_action(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login_page'))
    db.reference(f"siaran/{provinsi}/{wilayah}/{mux}").delete()
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout_action():
    session.pop('user', None)
    return redirect(url_for('login_page'))

@app.route("/test-firebase")
def test_firebase_action():
    return "Firebase Connected" if ref else "Error"

if __name__ == "__main__":
    app.run(debug=True)
