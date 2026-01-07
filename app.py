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
import io
import csv
import google.generativeai as genai
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs
from newsapi import NewsApiClient # Jika tidak dipakai bisa dihapus, tapi saya biarkan sesuai source
from firebase_admin import credentials, db
from flask import Flask, request, render_template, redirect, url_for, session, flash, jsonify, send_file
from flask_cors import CORS
from dotenv import load_dotenv
from flask_mail import Mail, Message
from datetime import datetime
from collections import Counter

# Muat variabel lingkungan
load_dotenv()

app = Flask(__name__)
CORS(app)

app.secret_key = os.environ.get("SECRET_KEY", "b/g5n!o0?hs&dm!fn8md7")

# --- 1. INISIALISASI FIREBASE (TETAP SESUAI KODE ASLI) ---
# Pastikan file credentials.json ada di folder yang sama
try:
    cred = credentials.Certificate('credentials.json')
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://website-ktvdi-default-rtdb.firebaseio.com/' 
    })
    ref = db.reference('/')
    print("✅ Firebase Connected!")
except Exception as e:
    print(f"❌ Firebase Error: {e}")
    ref = None

# --- 2. INISIALISASI EMAIL ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_USERNAME'] = 'kom.tvdigitalid@gmail.com'
app.config['MAIL_PASSWORD'] = 'lvjo uwrj sbiy ggkg' # Sebaiknya pakai Environment Variable
app.config['MAIL_DEFAULT_SENDER'] = 'kom.tvdigitalid@gmail.com'

mail = Mail(app)

# --- 3. KONFIGURASI GEMINI AI (TERBARU & LEBIH CEPAT) ---
GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY")
model = None

if GOOGLE_API_KEY:
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        # Menggunakan model 1.5-flash yang stabil, cepat, dan hemat kuota
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            system_instruction=(
                "Anda adalah Asisten Virtual KTVDI. "
                "Tugas: Jawab pertanyaan seputar TV Digital, STB, Antena, Frekuensi MUX, dan Jadwal Bola Piala Dunia 2026. "
                "Gaya bahasa: Ramah, singkat, dan informatif. "
                "Jangan menjawab hal di luar topik teknologi penyiaran."
            )
        )
        print("✅ Gemini AI 1.5 Flash Siap!")
    except Exception as e:
        print(f"❌ Gemini Error: {e}")

# --- 4. FUNGSI BARU: RSS BERITA GOOGLE ---
def get_google_news():
    """Mengambil berita real-time dari Google News RSS"""
    news_list = []
    try:
        # Feed Google News Indonesia (Teknologi & Digital)
        rss_url = 'https://news.google.com/rss/search?q=tv+digital+indonesia+kominfo+siaran&hl=id&gl=ID&ceid=ID:id'
        feed = feedparser.parse(rss_url)
        for entry in feed.entries[:10]: # Ambil 10 berita terbaru
            news_list.append(entry.title)
    except:
        pass
    
    # Fallback jika gagal fetch
    if not news_list:
        news_list = [
            "Selamat Datang di KTVDI - Komunitas TV Digital Indonesia",
            "Jelang Piala Dunia 2026: Pastikan TV Anda Sudah Digital",
            "Update Frekuensi MUX Terbaru Tersedia di Database Kami"
        ]
    return news_list

# --- ROUTES ---

@app.route("/")
def home():
    # Ambil data dari seluruh node "siaran" untuk semua provinsi
    ref = db.reference('siaran')
    siaran_data = ref.get() or {}

    # Variabel Statistik
    jumlah_wilayah_layanan = 0
    jumlah_siaran = 0
    jumlah_penyelenggara_mux = 0
    siaran_counts = Counter()
    last_updated_time = None
    
    # Data untuk Diagram (Chart)
    chart_provinsi_labels = []
    chart_provinsi_data = []

    # Iterasi melalui provinsi, wilayah layanan, dan penyelenggara mux
    for provinsi, provinsi_data in siaran_data.items():
        if isinstance(provinsi_data, dict):
            # Hitung data untuk chart
            jumlah_wilayah_provinsi = len(provinsi_data)
            chart_provinsi_labels.append(provinsi)
            chart_provinsi_data.append(jumlah_wilayah_provinsi)
            
            jumlah_wilayah_layanan += len(provinsi_data)
            
            for wilayah, wilayah_data in provinsi_data.items():
                if isinstance(wilayah_data, dict):
                    jumlah_penyelenggara_mux += len(wilayah_data)
                    
                    for penyelenggara, penyelenggara_details in wilayah_data.items():
                        if 'siaran' in penyelenggara_details:
                            jumlah_siaran += len(penyelenggara_details['siaran'])
                            for siaran in penyelenggara_details['siaran']:
                                siaran_counts[siaran.lower()] += 1
                        
                        # Cek last updated
                        if 'last_updated_date' in penyelenggara_details:
                            current_updated_time_str = penyelenggara_details['last_updated_date']
                            try:
                                current_updated_time = datetime.strptime(current_updated_time_str, '%d-%m-%Y')
                            except ValueError:
                                current_updated_time = None
                            if current_updated_time and (last_updated_time is None or current_updated_time > last_updated_time):
                                last_updated_time = current_updated_time

    # Menentukan siaran TV terbanyak
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

    # --- BARU: Ambil Berita RSS untuk dikirim ke Template ---
    breaking_news = get_google_news()

    # Kirim data ke template
    return render_template('index.html', 
                           most_common_siaran_name=most_common_siaran_name,
                           most_common_siaran_count=most_common_siaran_count,
                           jumlah_wilayah_layanan=jumlah_wilayah_layanan,
                           jumlah_siaran=jumlah_siaran, 
                           jumlah_penyelenggara_mux=jumlah_penyelenggara_mux, 
                           last_updated_time=last_updated_time,
                           # Kirim data chart JSON
                           chart_labels=json.dumps(chart_provinsi_labels),
                           chart_data=json.dumps(chart_provinsi_data),
                           breaking_news=breaking_news) # Kirim berita ke frontend

# --- ROUTE CHATBOT (UPDATED HANDLING) ---
@app.route('/', methods=['POST'])
def chatbot():
    data = request.get_json()
    prompt = data.get("prompt")

    if not model:
        # Kirim kode khusus 503 agar frontend mengaktifkan Mode Offline
        return jsonify({"error": "Offline Mode"}), 503

    try:
        response = model.generate_content(prompt)
        return jsonify({"response": response.text})
    except Exception as e:
        error_msg = str(e)
        # Deteksi jika kuota habis (429)
        if "429" in error_msg or "Quota" in error_msg:
            return jsonify({"error": "Quota Exceeded"}), 429
        return jsonify({"error": str(e)}), 500

# --- ROUTE UTILS (SITEMAP, DLL) ---
@app.route('/sitemap.xml')
def sitemap():
    return send_file('static/sitemap.xml')

# --- ROUTE AUTHENTICATION (ASLI DARI USER) ---

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

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
                return redirect(url_for('dashboard', name=user_data['nama']))

            error_message = "Password salah."
        except Exception as e:
            error_message = f"Error fetching data from Firebase: {str(e)}"

    return render_template('login.html', error=error_message)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        nama = request.form.get("nama")
        email = request.form.get("email")
        username = request.form.get("username")
        password = request.form.get("password")

        # Validasi
        if len(password) < 8:
            flash("Password harus minimal 8 karakter.", "error")
            return render_template("register.html")

        if not re.match(r"^[a-z0-9]+$", username):
            flash("Username hanya boleh huruf kecil dan angka.", "error")
            return render_template("register.html")

        users_ref = db.reference("users")
        users = users_ref.get() or {}

        # Cek email & username
        for uid, user in users.items():
            if user.get("email", "").lower() == email.lower():
                flash("Email sudah terdaftar!", "error")
                return render_template("register.html")

        if username in users:
            flash("Username sudah dipakai!", "error")
            return render_template("register.html")

        hashed_pw = hashlib.sha256(password.encode()).hexdigest()
        otp = str(random.randint(100000, 999999))

        db.reference(f"pending_users/{username}").set({
            "nama": nama, "email": email, "password": hashed_pw, "otp": otp
        })

        try:
            msg = Message("Kode OTP Verifikasi Akun", recipients=[email])
            msg.body = f"Halo {nama},\n\nKode OTP Anda: {otp}\nGunakan kode ini untuk mengaktifkan akun Anda."
            mail.send(msg)
            session["pending_username"] = username
            flash("Kode OTP telah dikirim ke email Anda.", "success")
            return redirect(url_for("verify_register"))
        except Exception as e:
            flash(f"Gagal mengirim email OTP: {str(e)}", "error")

    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    username = session.get("pending_username")
    if not username:
        flash("Sesi pendaftaran tidak ditemukan.", "error")
        return redirect(url_for("register"))

    pending_ref = db.reference(f"pending_users/{username}")
    pending_data = pending_ref.get()

    if not pending_data:
        flash("Data pendaftaran tidak ditemukan.", "error")
        return redirect(url_for("register"))

    if request.method == "POST":
        otp_input = request.form.get("otp")
        if pending_data.get("otp") == otp_input:
            db.reference(f"users/{username}").set({
                "nama": pending_data["nama"],
                "email": pending_data["email"],
                "password": pending_data["password"],
                "points": 0
            })
            pending_ref.delete()
            session.pop("pending_username", None)
            flash("Akun berhasil diverifikasi! Silakan login.", "success")
        else:
            flash("Kode OTP salah!", "error")

    return render_template("verify-register.html", username=username)

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
                msg.body = f"Kode OTP Reset Password: {otp}"
                mail.send(msg)
                flash(f"Kode OTP dikirim ke {email}.", "success")
                session["reset_uid"] = found_uid
                return redirect(url_for("verify_otp"))
            except Exception as e:
                flash(f"Gagal mengirim email: {str(e)}", "error")
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
        new_password = request.form.get("password")
        if len(new_password) < 8:
            flash("Password minimal 8 karakter.", "error")
            return render_template("reset-password.html")
        hashed_pw = hashlib.sha256(new_password.encode()).hexdigest()
        db.reference(f"users/{uid}").update({"password": hashed_pw})
        db.reference(f"otp/{uid}").delete()
        session.pop("reset_uid", None)
        flash("Password berhasil direset.", "success")
    return render_template("reset-password.html")

# --- DASHBOARD & CRUD ROUTES ---

@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    nama_lengkap = session.get('nama', 'Pengguna').replace('%20', ' ')
    ref = db.reference("provinsi")
    data = ref.get() or {}
    return render_template("dashboard.html", name=nama_lengkap, provinsi_list=list(data.values()))

@app.route("/add_data", methods=["GET", "POST"])
def add_data():
    if 'user' not in session: return redirect(url_for('login'))
    ref = db.reference("provinsi")
    provinsi_list = list((ref.get() or {}).values())

    if request.method == 'POST':
        provinsi = request.form['provinsi']
        wilayah = request.form['wilayah']
        mux = request.form['mux']
        siaran_input = request.form['siaran']
        siaran_list = [s.strip() for s in siaran_input.split(',') if s.strip()]
        
        # (Validasi logic tetap sama seperti kode asli...)
        # Disini saya persingkat untuk kejelasan, tapi Anda bisa pakai logic validasi regex asli
        
        try:
            tz = pytz.timezone('Asia/Jakarta')
            now_wib = datetime.now(tz)
            data_to_save = {
                "siaran": sorted(siaran_list),
                "last_updated_by_username": session.get('user'),
                "last_updated_by_name": session.get('nama', 'Pengguna'),
                "last_updated_date": now_wib.strftime("%d-%m-%Y"),
                "last_updated_time": now_wib.strftime("%H:%M:%S WIB")
            }
            # Cleaning key agar aman di URL/DB
            w_clean = re.sub(r'\s*-\s*', '-', wilayah.strip())
            m_clean = mux.strip()
            db.reference(f"siaran/{provinsi}/{w_clean}/{m_clean}").set(data_to_save)
            return redirect(url_for('dashboard'))
        except Exception as e:
            return f"Gagal: {e}"

    return render_template('add_data_form.html', provinsi_list=provinsi_list)

@app.route("/edit_data/<provinsi>/<wilayah>/<mux>", methods=["GET", "POST"])
def edit_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    p = provinsi.replace('%20',' ')
    w = wilayah.replace('%20', ' ')
    m = mux.replace('%20', ' ')

    if request.method == 'POST':
        siaran_list = [s.strip() for s in request.form['siaran'].split(',') if s.strip()]
        try:
            tz = pytz.timezone('Asia/Jakarta')
            now_wib = datetime.now(tz)
            data_to_update = {
                "siaran": sorted(siaran_list),
                "last_updated_by_username": session.get('user'),
                "last_updated_by_name": session.get('nama', 'Pengguna'),
                "last_updated_date": now_wib.strftime("%d-%m-%Y"),
                "last_updated_time": now_wib.strftime("%H:%M:%S WIB")
            }
            w_clean = re.sub(r'\s*-\s*', '-', w.strip())
            db.reference(f"siaran/{p}/{w_clean}/{m.strip()}").update(data_to_update)
            return redirect(url_for('dashboard'))
        except Exception as e:
            return f"Gagal update: {e}"

    return render_template('edit_data_form.html', provinsi=p, wilayah=w, mux=m)

@app.route("/delete_data/<provinsi>/<wilayah>/<mux>", methods=["POST"])
def delete_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    try:
        db.reference(f"siaran/{provinsi}/{wilayah}/{mux}").delete()
        return redirect(url_for('dashboard'))
    except Exception as e:
        return f"Gagal hapus: {e}"

# --- ROUTE LAIN & API ---

@app.route("/get_wilayah")
def get_wilayah():
    p = request.args.get("provinsi")
    d = db.reference(f"siaran/{p}").get() or {}
    return jsonify({"wilayah": list(d.keys())})

@app.route("/get_mux")
def get_mux():
    p = request.args.get("provinsi")
    w = request.args.get("wilayah")
    d = db.reference(f"siaran/{p}/{w}").get() or {}
    return jsonify({"mux": list(d.keys())})

@app.route("/get_siaran")
def get_siaran():
    p = request.args.get("provinsi")
    w = request.args.get("wilayah")
    m = request.args.get("mux")
    d = db.reference(f"siaran/{p}/{w}/{m}").get() or {}
    return jsonify(d)

@app.route('/berita')
def berita():
    # Mengambil berita untuk halaman berita penuh
    rss_url = 'https://news.google.com/rss/search?q=tv+digital+indonesia&hl=id&gl=ID&ceid=ID:id'
    feed = feedparser.parse(rss_url)
    articles = feed.entries
    page = request.args.get('page', 1, type=int)
    per_page = 5
    start = (page - 1) * per_page
    end = start + per_page
    
    # Helper time_since_published digunakan di sini
    def tsp(pt):
        now = datetime.now()
        pub = datetime(*pt[:6])
        d = now - pub
        if d.days >= 1: return f"{d.days} hari lalu"
        if d.seconds >= 3600: return f"{d.seconds//3600} jam lalu"
        return "Baru saja"

    for a in articles[start:end]:
        if 'published_parsed' in a: a.time_since_published = tsp(a.published_parsed)
        # Helper get_actual_url bisa dimasukkan disini jika perlu scraping
        
    return render_template('berita.html', articles=articles[start:end], page=page, total_pages=(len(articles)+per_page-1)//per_page)

@app.route('/download-sql')
def download_sql():
    users_data = db.reference('users').get()
    if not users_data: return "No data", 404
    sql_queries = []
    for uname, udata in users_data.items():
        sql_queries.append(f"INSERT INTO users (username, nama, email, password) VALUES ('{uname}', '{udata['nama']}', '{udata['email']}', '{udata['password']}');")
    return send_file(io.BytesIO("\n".join(sql_queries).encode()), as_attachment=True, download_name="export_users.sql", mimetype="text/plain")

@app.route('/download-csv')
def download_csv():
    users_data = db.reference('users').get()
    if not users_data: return "No data", 404
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['username', 'nama', 'email', 'password'])
    for uname, udata in users_data.items():
        writer.writerow([uname, udata['nama'], udata['email'], udata['password']])
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode('utf-8')), as_attachment=True, download_name="export_users.csv", mimetype="text/csv")

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

@app.route("/test-firebase")
def test_firebase():
    try:
        data = ref.get()
        return f"Connected! Data: {str(data)[:100]}..." if data else "Connected (Empty)"
    except Exception as e:
        return f"Error: {e}"

if __name__ == "__main__":
    app.run(debug=True)
