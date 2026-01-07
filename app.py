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
# Menggunakan model 1.5-flash yang lebih stabil dan hemat kuota
GOOGLE_API_KEY = os.environ.get("GEMINI_APP_KEY")
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)
    try:
        # Konfigurasi agar respon lebih natural
        generation_config = {
            "temperature": 0.7,
            "top_p": 0.95,
            "top_k": 40,
            "max_output_tokens": 8192,
            "response_mime_type": "text/plain",
        }
        
        system_instruction = (
            "Anda adalah Chatbot AI KTVDI. Jawablah dengan ramah, singkat, dan membantu. "
            "Topik: TV Digital, STB, Antena, Sinyal, dan Jadwal Bola. "
            "Jika ditanya di luar topik itu, arahkan kembali ke TV Digital."
        )
        
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            generation_config=generation_config,
            system_instruction=system_instruction
        )
        print("✅ Gemini AI 1.5 Flash Siap!")
    except Exception as e:
        print(f"❌ Error Config Gemini: {e}")
        model = None
else:
    print("❌ API Key Gemini tidak ditemukan.")
    model = None

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

# --- HELPER: RSS NEWS ---
def get_breaking_news():
    """Mengambil berita terbaru untuk Flip Text"""
    news = []
    try:
        # Feed Google News Indonesia (Teknologi)
        feed = feedparser.parse('https://news.google.com/rss/search?q=tv+digital+indonesia+kominfo&hl=id&gl=ID&ceid=ID:id')
        for entry in feed.entries[:7]: # Ambil 7 berita
            news.append(entry.title)
    except:
        pass
    
    if not news:
        news = ["Selamat Datang di KTVDI", "Update Frekuensi TV Digital Terbaru", "Pastikan STB Bersertifikat Kominfo"]
    return news

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
            # Hitung data untuk chart (Jumlah Wilayah per Provinsi)
            jumlah_wilayah_provinsi = len(provinsi_data)
            chart_provinsi_labels.append(provinsi)
            chart_provinsi_data.append(jumlah_wilayah_provinsi)
            
            # Statistik Global
            jumlah_wilayah_layanan += jumlah_wilayah_provinsi

            for wilayah, wilayah_data in provinsi_data.items():
                if isinstance(wilayah_data, dict):
                    jumlah_penyelenggara_mux += len(wilayah_data)
                    
                    # Menghitung jumlah siaran
                    for penyelenggara, penyelenggara_details in wilayah_data.items():
                        if 'siaran' in penyelenggara_details:
                            jumlah_siaran += len(penyelenggara_details['siaran'])
                            for siaran in penyelenggara_details['siaran']:
                                siaran_counts[siaran.lower()] += 1
                        
                        # Mengambil waktu update terakhir
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

    # Ambil Berita RSS Terbaru (UPDATED)
    breaking_news = get_breaking_news()

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
                           breaking_news=breaking_news)

@app.route('/', methods=['POST'])
def chatbot():
    data = request.get_json()
    prompt = data.get("prompt")

    if not model:
        return jsonify({"error": "Offline Mode (Server AI Busy)"}), 503

    try:
        response = model.generate_content(prompt)
        return jsonify({"response": response.text})
    except Exception as e:
        error_msg = str(e)
        # Deteksi spesifik error kuota agar frontend bisa switch ke mode manual
        if "429" in error_msg or "Quota" in error_msg:
            return jsonify({"error": "Quota Exceeded"}), 429
        return jsonify({"error": str(e)}), 500

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
            db.reference(f"otp/{found_uid}").set({
                "email": email,
                "otp": otp
            })

            try:
                username = found_uid
                nama = found_user.get("nama", "")

                msg = Message("Kode OTP Reset Password", recipients=[email])
                msg.body = f"""
Halo {nama} ({username}),

Anda meminta reset password.
Kode OTP Anda adalah: {otp}

Jika Anda tidak meminta reset, abaikan email ini.
"""
                mail.send(msg)

                flash(
                    f"Kode OTP telah dikirim ke email Anda. Username: {username}, Nama: {nama}",
                    "success"
                )
                session["reset_uid"] = found_uid
                return redirect(url_for("verify_otp"))

            except Exception as e:
                flash(f"Gagal mengirim email: {str(e)}", "error")

        else:
            flash("Email tidak ditemukan di database!", "error")

    return render_template("forgot-password.html")

# --- Halaman verifikasi OTP ---
@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    uid = session.get("reset_uid")
    if not uid:
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        otp_input = request.form.get("otp")

        otp_data = db.reference(f"otp/{uid}").get()
        if otp_data and otp_data["otp"] == otp_input:
            flash("OTP benar, silakan ganti password Anda.", "success")
            return redirect(url_for("reset_password"))
        else:
            flash("OTP salah atau kadaluarsa.", "error")

    return render_template("verify-otp.html")

# --- Halaman reset password ---
@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    uid = session.get("reset_uid")
    if not uid:
        flash("Sesi reset password tidak ditemukan!", "error")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        new_password = request.form.get("password")

        if len(new_password) < 8:
            flash("Password harus minimal 8 karakter.", "error")
            return render_template("reset-password.html")

        hashed_pw = hashlib.sha256(new_password.encode()).hexdigest()

        user_ref = db.reference(f"users/{uid}")
        user_ref.update({"password": hashed_pw})

        db.reference(f"otp/{uid}").delete()
        session.pop("reset_uid", None)

        flash("Password berhasil direset, silakan login kembali.", "success")

    return render_template("reset-password.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        nama = request.form.get("nama")
        email = request.form.get("email")
        username = request.form.get("username")
        password = request.form.get("password")

        # --- Validasi ---
        if len(password) < 8:
            flash("Password harus minimal 8 karakter.", "error")
            return render_template("register.html")

        if not re.match(r"^[a-z0-9]+$", username):
            flash("Username hanya boleh huruf kecil dan angka.", "error")
            return render_template("register.html")

        users_ref = db.reference("users")
        users = users_ref.get() or {}

        # cek email sudah terdaftar
        for uid, user in users.items():
            if user.get("email", "").lower() == email.lower():
                flash("Email sudah terdaftar!", "error")
                return render_template("register.html")

        # cek username sudah dipakai
        if username in users:
            flash("Username sudah dipakai!", "error")
            return render_template("register.html")

        hashed_pw = hashlib.sha256(password.encode()).hexdigest()
        otp = str(random.randint(100000, 999999))

        db.reference(f"pending_users/{username}").set({
            "nama": nama,
            "email": email,
            "password": hashed_pw,
            "otp": otp
        })

        try:
            msg = Message("Kode OTP Verifikasi Akun", recipients=[email])
            msg.body = f"""
Halo {nama},

Terima kasih sudah mendaftar.
Kode OTP Anda: {otp}

Gunakan kode ini untuk mengaktifkan akun Anda.
"""
            mail.send(msg)

            session["pending_username"] = username
            flash("Kode OTP telah dikirim ke email Anda. Silakan verifikasi.", "success")
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

@app.route("/daftar-siaran")
def daftar_siaran():
    ref = db.reference("provinsi")
    data = ref.get() or {}
    provinsi_list = list(data.values())
    return render_template("daftar-siaran.html", provinsi_list=provinsi_list)

@app.route("/get_wilayah")
def get_wilayah():
    provinsi = request.args.get("provinsi")
    ref = db.reference(f"siaran/{provinsi}")
    data = ref.get() or {}
    wilayah_list = list(data.keys())
    return jsonify({"wilayah": wilayah_list})

@app.route("/get_mux")
def get_mux():
    provinsi = request.args.get("provinsi")
    wilayah = request.args.get("wilayah")
    ref = db.reference(f"siaran/{provinsi}/{wilayah}")
    data = ref.get() or {}
    mux_list = list(data.keys())
    return jsonify({"mux": mux_list})

@app.route("/get_siaran")
def get_siaran():
    provinsi = request.args.get("provinsi")
    wilayah = request.args.get("wilayah")
    mux = request.args.get("mux")
    ref = db.reference(f"siaran/{provinsi}/{wilayah}/{mux}")
    data = ref.get() or {}

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
    
    if delta.days >= 1:
        if delta.days == 1:
            return "1 hari yang lalu"
        return f"{delta.days} hari yang lalu"
    
    if delta.seconds >= 3600:
        hours = delta.seconds // 3600
        return f"{hours} jam yang lalu"
    
    if delta.seconds >= 60:
        minutes = delta.seconds // 60
        return f"{minutes} menit yang lalu"
    
    return "Beberapa detik yang lalu"

@app.route('/berita')
def berita():
    rss_url = 'https://news.google.com/rss/search?q=tv+digital&hl=id&gl=ID&ceid=ID:id'
    feed = feedparser.parse(rss_url)
    articles = feed.entries
    articles_per_page = 5
    page = request.args.get('page', 1, type=int)
    total_articles = len(articles)
    
    start = (page - 1) * articles_per_page
    end = start + articles_per_page
    articles_on_page = articles[start:end]
    total_pages = (total_articles + articles_per_page - 1) // articles_per_page

    for article in articles_on_page:
        if 'published_parsed' in article:
            article.time_since_published = time_since_published(article.published_parsed)
    
    return render_template(
        'berita.html', 
        articles=articles_on_page, 
        page=page,
        total_pages=total_pages
    )

@app.route('/about')
def about():
    return render_template('about.html')

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

@app.route("/dashboard")
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))

    nama_lengkap = session.get('nama', 'Pengguna')
    nama_lengkap = nama_lengkap.replace('%20', ' ')

    ref = db.reference("provinsi")
    data = ref.get() or {}
    provinsi_list = list(data.values())

    return render_template("dashboard.html", name=nama_lengkap, provinsi_list=provinsi_list)

@app.route("/add_data", methods=["GET", "POST"])
def add_data():
    if 'user' not in session:
        return redirect(url_for('login'))

    ref = db.reference("provinsi")
    provinsi_data = ref.get() or {}
    provinsi_list = list(provinsi_data.values())

    if request.method == 'POST':
        provinsi = request.form['provinsi']
        wilayah = request.form['wilayah']
        mux = request.form['mux']
        siaran_input = request.form['siaran']

        siaran_list = [s.strip() for s in siaran_input.split(',') if s.strip()]
        wilayah_clean = re.sub(r'\s*-\s*', '-', wilayah.strip())
        mux_clean = mux.strip()

        is_valid = True
        error_message = ""
        
        if not all([provinsi, wilayah_clean, mux_clean, siaran_list]):
            is_valid = False
            error_message = "Harap isi semua kolom."
        else:
            # Validasi format wilayah
            wilayah_pattern = r"^[a-zA-Z\s]+-\d+$"
            if not re.fullmatch(wilayah_pattern, wilayah_clean):
                is_valid = False
                error_message = "Format **Wilayah Layanan** tidak valid. Gunakan 'Nama Provinsi-Angka'."

            # Validasi kecocokan provinsi
            wilayah_parts = wilayah_clean.split('-')
            if len(wilayah_parts) > 1:
                provinsi_from_wilayah = '-'.join(wilayah_parts[:-1]).strip()
                if provinsi_from_wilayah.lower() != provinsi.lower():
                    is_valid = False
                    error_message = f"Provinsi wilayah '{provinsi_from_wilayah}' tidak cocok dengan pilihan '{provinsi}'."
            else:
                is_valid = False
                error_message = "Format **Wilayah Layanan** tidak lengkap."
            
            # Validasi MUX
            mux_pattern = r"^UHF\s+\d{1,3}\s*-\s*.+$"
            if not re.fullmatch(mux_pattern, mux_clean):
                is_valid = False
                error_message = "Format **MUX** tidak valid. Gunakan 'UHF XX - Nama MUX'."

        if is_valid:
            try:
                tz = pytz.timezone('Asia/Jakarta')
                now_wib = datetime.now(tz)
                updated_date = now_wib.strftime("%d-%m-%Y")
                updated_time = now_wib.strftime("%H:%M:%S WIB")

                data_to_save = {
                    "siaran": sorted(siaran_list),
                    "last_updated_by_username": session.get('user'),
                    "last_updated_by_name": session.get('nama', 'Pengguna'),
                    "last_updated_date": updated_date,
                    "last_updated_time": updated_time
                }

                db.reference(f"siaran/{provinsi}/{wilayah_clean}/{mux_clean}").set(data_to_save)
                return redirect(url_for('dashboard'))
            except Exception as e:
                return f"Gagal menyimpan data: {e}"

        return render_template('add_data_form.html', error_message=error_message, provinsi_list=provinsi_list)

    return render_template('add_data_form.html', provinsi_list=provinsi_list)

@app.route("/edit_data/<provinsi>/<wilayah>/<mux>", methods=["GET", "POST"])
def edit_data(provinsi, wilayah, mux):
    if 'user' not in session:
        return redirect(url_for('login'))

    provinsi = provinsi.replace('%20',' ')
    wilayah = wilayah.replace('%20', ' ')
    mux = mux.replace('%20', ' ')

    if request.method == 'POST':
        siaran_input = request.form['siaran']
        
        siaran_list = [s.strip() for s in siaran_input.split(',') if s.strip()]
        wilayah_clean = re.sub(r'\s*-\s*', '-', wilayah.strip())
        mux_clean = mux.strip()

        is_valid = True
        error_message = ""
        
        if not all([provinsi, wilayah_clean, mux_clean, siaran_list]):
            is_valid = False
            error_message = "Harap isi semua kolom."
        else:
            # Validasi ulang seperti add_data
            wilayah_pattern = r"^[a-zA-Z\s]+-\d+$"
            if not re.fullmatch(wilayah_pattern, wilayah_clean):
                is_valid = False
                error_message = "Format Wilayah tidak valid."

            wilayah_parts = wilayah_clean.split('-')
            if len(wilayah_parts) > 1:
                provinsi_from_wilayah = '-'.join(wilayah_parts[:-1]).strip()
                if provinsi_from_wilayah.lower() != provinsi.lower():
                    is_valid = False
                    error_message = "Provinsi tidak cocok."
            
            mux_pattern = r"^UHF\s+\d{1,3}\s*-\s*.+$"
            if not re.fullmatch(mux_pattern, mux_clean):
                is_valid = False
                error_message = "Format MUX tidak valid."

        if is_valid:
            try:
                tz = pytz.timezone('Asia/Jakarta')
                now_wib = datetime.now(tz)
                updated_date = now_wib.strftime("%d-%m-%Y")
                updated_time = now_wib.strftime("%H:%M:%S WIB")
                
                data_to_update = {
                    "siaran": sorted(siaran_list),
                    "last_updated_by_username": session.get('user'),
                    "last_updated_by_name": session.get('nama', 'Pengguna'),
                    "last_updated_date": updated_date,
                    "last_updated_time": updated_time
                }

                db.reference(f"siaran/{provinsi}/{wilayah_clean}/{mux_clean}").update(data_to_update)
                return redirect(url_for('dashboard'))

            except Exception as e:
                return f"Gagal memperbarui data: {e}"

        return render_template('edit_data_form.html', error_message=error_message)

    return render_template('edit_data_form.html', provinsi=provinsi, wilayah=wilayah, mux=mux)

@app.route("/delete_data/<provinsi>/<wilayah>/<mux>", methods=["POST"])
def delete_data(provinsi, wilayah, mux):
    if 'user' not in session:
        return redirect(url_for('login'))

    try:
        db.reference(f"siaran/{provinsi}/{wilayah}/{mux}").delete()
        return redirect(url_for('dashboard'))
    except Exception as e:
        return f"Gagal menghapus data: {e}"

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

@app.route("/test-firebase")
def test_firebase():
    try:
        if ref is None:
            return "❌ Firebase belum terhubung"
        data = ref.get()
        if not data:
            return "✅ Firebase terhubung, tapi data kosong."
        return f"✅ Firebase terhubung! Data root:<br><pre>{data}</pre>"
    except Exception as e:
        return f"❌ Error akses Firebase: {e}"

if __name__ == "__main__":
    app.run(debug=True)
