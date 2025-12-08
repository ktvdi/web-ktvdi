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
    "Anda adalah Chatbot AI KTVDI untuk website Komunitas TV Digital Indonesia (KTVDI). "
    "Tugas Anda adalah menjawab pertanyaan pengguna seputar website KTVDI, "
    "fungsi-fungsinya (login, daftar, tambah data, edit data, hapus data), "
    "serta pertanyaan umum tentang TV Digital di Indonesia (DVB-T2, MUX, mencari siaran, antena, STB, merk TV). "
    "Jawab dengan ramah, informatif, dan ringkas. "
    "Gunakan bahasa Indonesia formal. "
    "Jika pertanyaan di luar cakupan Anda atau memerlukan informasi real-time yang tidak Anda miliki, "
    "arahkan pengguna untuk mencari informasi lebih lanjut di sumber resmi atau bertanya di forum/komunitas terkait TV Digital."
    "\n\nBerikut adalah beberapa contoh FAQ yang bisa Anda jawab dan informasi yang harus Anda pertimbangkan:"
    "\n- **Apa itu KTVDI?** KTVDI adalah platform komunitas online tempat pengguna dapat berbagi, menambahkan, memperbarui, dan melihat data siaran TV Digital (DVB-T2) di berbagai provinsi dan wilayah di Indonesia."
    "\n- **Bagaimana cara menambahkan data siaran?** Anda perlu login ke akun KTVDI Anda. Setelah login, Anda akan melihat bagian 'Tambahkan Data Siaran Baru' di halaman utama. Isi detail provinsi, wilayah, penyelenggara MUX, dan daftar siaran yang tersedia."
    "\n- **Bagaimana cara mendapatkan poin?** Anda mendapatkan 10 poin setiap kali Anda berhasil menambahkan data siaran baru. Anda mendapatkan 5 poin saat memperbarui data siaran yang sudah ada. Anda juga mendapatkan 1 poin setiap kali Anda mengirimkan komentar pada data MUX tertentu."
    "\n- **Apa itu MUX?** MUX adalah singkatan dari Multiplex. Dalam konteks TV Digital, MUX adalah teknologi yang memungkinkan beberapa saluran televisi digital disiarkan secara bersamaan melalui satu frekuensi atau kanal UHF. Setiap MUX biasanya dikelola oleh satu penyelenggara (misalnya, Metro TV, SCTV, Trans TV, TVRI)."
    "\n- **Bagaimana cara mencari siaran TV digital?** Anda dapat mencari siaran TV digital dengan melakukan pemindaian otomatis (auto scan) pada televisi digital Anda atau Set Top Box (STB) DVB-T2. Pastikan antena Anda terpasang dengan benar dan mengarah ke pemancar terdekat."
    "\n- **Apa itu DVB-T2?** DVB-T2 adalah standar penyiaran televisi digital terestrial generasi kedua yang digunakan di Indonesia. Standar ini memungkinkan kualitas gambar dan suara yang lebih baik serta efisiensi frekuensi yang lebih tinggi dibandingkan siaran analog."
    "\n- **Apakah saya bisa mengedit data yang diinput orang lain?** Tidak, Anda hanya bisa mengedit data siaran yang Anda tambahkan sendiri. Jika ada data yang salah atau perlu diperbarui yang diinput oleh pengguna lain, Anda dapat melaporkan atau menunggu kontributor yang bersangkutan untuk memperbaruinya."
    "\n- **Bagaimana cara melihat profil pengguna lain?** Di sidebar aplikasi, terdapat tombol 'Lihat Profil Pengguna Lain'. Anda bisa memilih username dari daftar untuk melihat informasi profil publik mereka seperti nama, poin, provinsi, wilayah, dan merk perangkat TV digital mereka."
    "\n- **Bagaimana cara reset password?** Jika Anda lupa password, di halaman login, klik tombol 'Lupa Password?'. Masukkan email yang terdaftar, dan Anda akan menerima kode OTP untuk mereset password Anda."
    "\n- **Bisakah saya menghapus komentar saya?** Saat ini, tidak ada fitur langsung untuk menghapus komentar setelah dikirim. Harap berhati-hati dalam menulis komentar Anda."
    "\n- **Poin untuk apa?** Poin adalah bentuk apresiasi atas kontribusi Anda dalam berbagi dan memperbarui data siaran. Pengguna dengan poin tertinggi akan ditampilkan di halaman Leaderboard."
    "\n- **Apakah harus login untuk melihat data siaran?** Tidak, Anda dapat melihat data siaran tanpa login. Login hanya diperlukan untuk menambahkan, mengedit, menghapus data, memberi komentar, melihat profil Anda, dan mengakses leaderboard."
    "\n- **Format apa untuk Wilayah Layanan?** Formatnya adalah 'Nama Provinsi-Angka'. Contoh: 'Jawa Timur-1', 'DKI Jakarta-2'."
    "\n- **Format apa untuk Penyelenggara MUX?** Formatnya adalah 'UHF XX - Nama MUX'. Contoh: 'UHF 27 - Metro TV'."
    "\n- **Bagaimana cara kerja poin?** Poin diberikan secara otomatis setiap kali Anda berkontribusi. Tambah data (10 poin), edit data (5 poin), komentar (1 poin)."
    "\n- **Apa yang harus saya lakukan jika siaran tidak muncul?** Pastikan TV/STB Anda mendukung DVB-T2, antena terpasang benar dan mengarah ke pemancar, serta lakukan scan ulang saluran."
)

# --- FUNGSI TAMBAHAN: BMKG (Gempa & Cuaca Semarang) ---
def get_gempa_terkini():
    """Mengambil data gempa terkini dari API BMKG"""
    try:
        url = "https://data.bmkg.go.id/DataMKG/TEWS/gempadirasakan.json"
        response = requests.get(url, timeout=3)
        if response.status_code == 200:
            data = response.json()
            # Ambil gempa pertama dari list
            return data['Infogempa']['gempa'][0]
    except Exception as e:
        print(f"Gagal ambil data BMKG: {e}")
        return None
    return None

def get_cuaca_semarang():
    """Mengambil data prakiraan cuaca khusus Semarang"""
    try:
        # Kode Wilayah 33.74.13.1004 = Mugassari, Semarang Selatan (Area Simpang Lima/Pusat)
        url = "https://api.bmkg.go.id/publik/prakiraan-cuaca?adm4=33.74.13.1004"
        response = requests.get(url, timeout=3)
        if response.status_code == 200:
            data = response.json()
            # Ambil data cuaca saat ini (indeks 0 dari array data per jam)
            return data['data'][0]['cuaca'][0][0]
    except Exception as e:
        print(f"Gagal ambil cuaca Semarang: {e}")
        return None
    return None

# --- ROUTE UTAMA ---
@app.route("/")
def home():
    # Ambil data dari seluruh node "siaran" untuk semua provinsi
    ref = db.reference('siaran')
    siaran_data = ref.get()

    # Variabel Statistik
    jumlah_wilayah_layanan = 0
    jumlah_siaran = 0
    jumlah_penyelenggara_mux = 0
    siaran_counts = Counter()
    last_updated_time = None
    
    # Iterasi melalui provinsi, wilayah layanan, dan penyelenggara mux
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

    # Menentukan siaran TV terbanyak
    if siaran_counts:
        most_common_siaran = siaran_counts.most_common(1)[0]
        most_common_siaran_name = most_common_siaran[0].upper()
        most_common_siaran_count = most_common_siaran[1]
    else:
        most_common_siaran_name = None
        most_common_siaran_count = 0

    if last_updated_time:
        last_updated_time = last_updated_time.strftime('%d-%m-%Y')
    
    # AMBIL DATA API (GEMPA & CUACA SEMARANG)
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
                           cuaca_data=cuaca_data) # Data cuaca dikirim ke template

# --- ROUTE FAQ ---
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

# --- AUTH & PASSWORD ---
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
                msg.body = f"""Halo {nama} ({username}),\n\nAnda meminta reset password.\nKode OTP Anda adalah: {otp}\n\nJika Anda tidak meminta reset, abaikan email ini."""
                mail.send(msg)

                flash(f"Kode OTP telah dikirim ke email Anda. Username: {username}", "success")
                session["reset_uid"] = found_uid
                return redirect(url_for("verify_otp"))

            except Exception as e:
                flash(f"Gagal mengirim email: {str(e)}", "error")

        else:
            flash("Email tidak ditemukan di database!", "error")

    return render_template("forgot-password.html")

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

        if len(password) < 8:
            flash("Password harus minimal 8 karakter.", "error")
            return render_template("register.html")

        if not re.match(r"^[a-z0-9]+$", username):
            flash("Username hanya boleh huruf kecil dan angka.", "error")
            return render_template("register.html")

        users_ref = db.reference("users")
        users = users_ref.get() or {}

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
            "nama": nama,
            "email": email,
            "password": hashed_pw,
            "otp": otp
        })

        try:
            msg = Message("Kode OTP Verifikasi Akun", recipients=[email])
            msg.body = f"""Halo {nama},\n\nTerima kasih sudah mendaftar.\nKode OTP Anda: {otp}\n\nGunakan kode ini untuk mengaktifkan akun Anda."""
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

# --- DAFTAR SIARAN & API ---
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

# --- BERITA ---
def time_since_published(published_time):
    now = datetime.now()
    publish_time = datetime(*published_time[:6])
    delta = now - publish_time
    if delta.days >= 1: return f"{delta.days} hari yang lalu"
    if delta.seconds >= 3600: return f"{delta.seconds // 3600} jam yang lalu"
    if delta.seconds >= 60: return f"{delta.seconds // 60} menit yang lalu"
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
    
    return render_template('berita.html', articles=articles_on_page, page=page, total_pages=total_pages)

@app.route('/about')
def about():
    return render_template('about.html')

# --- LOGIN & DASHBOARD ---
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
    if 'user' not in session: return redirect(url_for('login'))
    nama_lengkap = session.get('nama', 'Pengguna').replace('%20', ' ')
    ref = db.reference("provinsi")
    data = ref.get() or {}
    provinsi_list = list(data.values())
    return render_template("dashboard.html", name=nama_lengkap, provinsi_list=provinsi_list)

# --- CRUD DATA ---
@app.route("/add_data", methods=["GET", "POST"])
def add_data():
    if 'user' not in session: return redirect(url_for('login'))
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
        if not all([provinsi, wilayah_clean, mux_clean, siaran_list]):
            is_valid = False
            error_message = "Harap isi semua kolom."
        else:
            if not re.fullmatch(r"^[a-zA-Z\s]+-\d+$", wilayah_clean):
                is_valid = False
                error_message = "Format Wilayah salah (Provinsi-Angka)."
            elif not wilayah_clean.lower().startswith(provinsi.lower()):
                is_valid = False
                error_message = "Provinsi di Wilayah Layanan tidak cocok."
            
            if not re.fullmatch(r"^UHF\s+\d{1,3}\s*-\s*.+$", mux_clean):
                is_valid = False
                error_message = "Format MUX salah (UHF XX - Nama)."

        if is_valid:
            try:
                tz = pytz.timezone('Asia/Jakarta')
                now_wib = datetime.now(tz)
                db.reference(f"siaran/{provinsi}/{wilayah_clean}/{mux_clean}").set({
                    "siaran": sorted(siaran_list),
                    "last_updated_by_username": session.get('user'),
                    "last_updated_by_name": session.get('nama', 'Pengguna'),
                    "last_updated_date": now_wib.strftime("%d-%m-%Y"),
                    "last_updated_time": now_wib.strftime("%H:%M:%S WIB")
                })
                return redirect(url_for('dashboard'))
            except Exception as e:
                return f"Gagal menyimpan data: {e}"

        return render_template('add_data_form.html', error_message=error_message, provinsi_list=provinsi_list)
    return render_template('add_data_form.html', provinsi_list=provinsi_list)

@app.route("/edit_data/<provinsi>/<wilayah>/<mux>", methods=["GET", "POST"])
def edit_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    provinsi = provinsi.replace('%20',' ')
    wilayah = wilayah.replace('%20', ' ')
    mux = mux.replace('%20', ' ')

    if request.method == 'POST':
        siaran_input = request.form['siaran']
        siaran_list = [s.strip() for s in siaran_input.split(',') if s.strip()]
        
        try:
            tz = pytz.timezone('Asia/Jakarta')
            now_wib = datetime.now(tz)
            db.reference(f"siaran/{provinsi}/{wilayah}/{mux}").update({
                "siaran": sorted(siaran_list),
                "last_updated_by_username": session.get('user'),
                "last_updated_by_name": session.get('nama', 'Pengguna'),
                "last_updated_date": now_wib.strftime("%d-%m-%Y"),
                "last_updated_time": now_wib.strftime("%H:%M:%S WIB")
            })
            return redirect(url_for('dashboard'))
        except Exception as e:
            return f"Gagal update: {e}"

    return render_template('edit_data_form.html', provinsi=provinsi, wilayah=wilayah, mux=mux)

@app.route("/delete_data/<provinsi>/<wilayah>/<mux>", methods=["POST"])
def delete_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    try:
        db.reference(f"siaran/{provinsi}/{wilayah}/{mux}").delete()
        return redirect(url_for('dashboard'))
    except Exception as e:
        return f"Gagal hapus: {e}"

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

@app.route("/test-firebase")
def test_firebase():
    try:
        if ref is None: return "❌ Firebase belum terhubung"
        data = ref.get()
        if not data: return "✅ Firebase terhubung, data kosong."
        return f"✅ Firebase terhubung! Data root:<br><pre>{data}</pre>"
    except Exception as e:
        return f"❌ Error: {e}"

if __name__ == "__main__":
    app.run(debug=True)
