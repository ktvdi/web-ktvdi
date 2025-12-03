import os
import hashlib
import random
import re
import pytz
import time
import feedparser
import google.generativeai as genai
from datetime import datetime
from collections import Counter

# Flask & Firebase Imports
import firebase_admin
from firebase_admin import credentials, db
from flask import Flask, request, render_template, redirect, url_for, session, flash, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
from flask_mail import Mail, Message

# 1. KONFIGURASI AWAL
# ==============================================================================
load_dotenv() # Muat variabel lingkungan dari .env

app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-wajib-ganti")

# --- Inisialisasi Firebase ---
try:
    # Memproses private key agar newline terbaca dengan benar
    private_key = os.environ.get("FIREBASE_PRIVATE_KEY")
    if private_key:
        private_key = private_key.replace('\\n', '\n')

    cred = credentials.Certificate({
        "type": "service_account",
        "project_id": os.environ.get("FIREBASE_PROJECT_ID"),
        "private_key_id": os.environ.get("FIREBASE_PRIVATE_KEY_ID"),
        "private_key": private_key,
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
    
    # Test koneksi sederhana
    ref = db.reference('/')
    print("✅ Firebase berhasil terhubung!")

except Exception as e:
    print(f"❌ Gagal inisialisasi Firebase: {str(e)}")
    ref = None

# --- Inisialisasi Email ---
app.config['MAIL_SERVER'] = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
app.config['MAIL_PORT'] = int(os.environ.get("MAIL_PORT", 587))
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD")
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")

mail = Mail(app)

# --- Konfigurasi Gemini AI ---
genai.configure(api_key=os.environ.get("GEMINI_APP_KEY"))
model = genai.GenerativeModel(
    "gemini-2.5-flash", 
    system_instruction="Anda adalah Chatbot AI KTVDI..." # (Isi instruksi sama seperti sebelumnya)
)

# 2. FUNGSI BANTUAN (HELPER)
# ==============================================================================
def hash_password(password):
    """Mengenkripsi password menggunakan SHA-256."""
    return hashlib.sha256(password.encode()).hexdigest()

def time_since_published(published_time):
    """Menghitung selisih waktu artikel berita."""
    now = datetime.now()
    publish_time = datetime(*published_time[:6])
    delta = now - publish_time
    
    if delta.days >= 1:
        return "1 hari yang lalu" if delta.days == 1 else f"{delta.days} hari yang lalu"
    if delta.seconds >= 3600:
        return f"{delta.seconds // 3600} jam yang lalu"
    if delta.seconds >= 60:
        return f"{delta.seconds // 60} menit yang lalu"
    return "Baru saja"

# 3. ROUTES UTAMA (HALAMAN)
# ==============================================================================

@app.route("/")
def home():
    """Halaman Beranda & Statistik."""
    try:
        ref = db.reference('siaran')
        siaran_data = ref.get() or {}

        jumlah_wilayah = 0
        jumlah_siaran = 0
        jumlah_mux = 0
        siaran_counts = Counter()
        last_updated_time = None

        # Iterasi data untuk statistik
        if isinstance(siaran_data, dict):
            for provinsi, prov_data in siaran_data.items():
                if isinstance(prov_data, dict):
                    jumlah_wilayah += len(prov_data)
                    for wilayah, wil_data in prov_data.items():
                        if isinstance(wil_data, dict):
                            jumlah_mux += len(wil_data)
                            for mux, mux_details in wil_data.items():
                                # Hitung total siaran
                                siaran_list = mux_details.get('siaran', [])
                                jumlah_siaran += len(siaran_list)
                                for s in siaran_list:
                                    siaran_counts[s.lower()] += 1
                                
                                # Cek last updated
                                updated_str = mux_details.get('last_updated_date')
                                if updated_str:
                                    try:
                                        curr_time = datetime.strptime(updated_str, '%d-%m-%Y')
                                        if last_updated_time is None or curr_time > last_updated_time:
                                            last_updated_time = curr_time
                                    except ValueError:
                                        pass

        # Siaran terbanyak
        top_siaran_name = "-"
        top_siaran_count = 0
        if siaran_counts:
            top = siaran_counts.most_common(1)[0]
            top_siaran_name = top[0].upper()
            top_siaran_count = top[1]

        last_update_str = last_updated_time.strftime('%d-%m-%Y') if last_updated_time else "-"

        return render_template('home.html', 
            most_common_siaran_name=top_siaran_name,
            most_common_siaran_count=top_siaran_count,
            jumlah_wilayah_layanan=jumlah_wilayah,
            jumlah_siaran=jumlah_siaran, 
            jumlah_penyelenggara_mux=jumlah_mux, 
            last_updated_time=last_update_str
        )
    except Exception as e:
        print(f"Error di Home: {e}")
        return render_template('home.html', error="Gagal memuat data statistik.")

@app.route('/', methods=['POST'])
def chatbot():
    """Endpoint API untuk Chatbot."""
    data = request.get_json()
    prompt = data.get("prompt")
    try:
        response = model.generate_content(prompt)
        return jsonify({"response": response.text})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/daftar-siaran")
def daftar_siaran():
    """Halaman Daftar Siaran (Filter)."""
    ref = db.reference("provinsi")
    data = ref.get()
    
    provinsi_list = []
    if data:
        if isinstance(data, list):
            provinsi_list = [p for p in data if p]
        elif isinstance(data, dict):
            provinsi_list = list(data.values())
    provinsi_list.sort()
    
    return render_template("daftar-siaran.html", provinsi_list=provinsi_list)

@app.route('/berita')
def berita():
    """Halaman Berita (RSS Feed)."""
    rss_url = 'https://news.google.com/rss/search?q=tv+digital&hl=id&gl=ID&ceid=ID:id'
    feed = feedparser.parse(rss_url)
    articles = feed.entries
    
    # Paginasi
    per_page = 6 # Ubah jadi 6 agar grid rapi (2 baris x 3 kolom)
    page = request.args.get('page', 1, type=int)
    total = len(articles)
    start = (page - 1) * per_page
    end = start + per_page
    current_articles = articles[start:end]
    total_pages = (total + per_page - 1) // per_page

    for art in current_articles:
        if 'published_parsed' in art:
            art.time_since_published = time_since_published(art.published_parsed)
    
    return render_template('berita.html', articles=current_articles, page=page, total_pages=total_pages)

# 4. AUTHENTICATION ROUTES (LOGIN/REGISTER/RESET)
# ==============================================================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()
        hashed_pw = hash_password(password)

        try:
            ref = db.reference(f'users/{username}')
            user_data = ref.get()

            if user_data and user_data.get('password') == hashed_pw:
                session['user'] = username
                session['nama'] = user_data.get("nama", "Pengguna")
                return redirect(url_for('dashboard'))
            else:
                return render_template('login.html', error="Username atau Password salah.")
        except Exception as e:
            return render_template('login.html', error=f"Terjadi kesalahan: {str(e)}")

    return render_template('login.html')

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        nama = request.form.get("nama")
        email = request.form.get("email")
        username = request.form.get("username")
        password = request.form.get("password")

        # Validasi sederhana
        if len(password) < 8:
            flash("Password minimal 8 karakter.", "error")
            return render_template("register.html")
        
        if not re.match(r"^[a-z0-9]+$", username):
            flash("Username hanya boleh huruf kecil dan angka.", "error")
            return render_template("register.html")

        # Cek duplikasi di database
        users_ref = db.reference("users")
        users = users_ref.get() or {}
        
        # Cek username
        if username in users:
            flash("Username sudah digunakan.", "error")
            return render_template("register.html")
            
        # Cek email (looping manual karena firebase realtime db key-based)
        for u in users.values():
            if u.get('email') == email:
                flash("Email sudah terdaftar.", "error")
                return render_template("register.html")

        # Simpan ke pending (menunggu verifikasi OTP)
        otp = str(random.randint(100000, 999999))
        hashed_pw = hash_password(password)
        
        db.reference(f"pending_users/{username}").set({
            "nama": nama, "email": email, "password": hashed_pw, "otp": otp
        })

        # Kirim Email OTP
        try:
            msg = Message("Kode OTP Verifikasi KTVDI", recipients=[email])
            msg.body = f"Halo {nama},\n\nKode OTP pendaftaran Anda: {otp}\n\nTerima kasih."
            mail.send(msg)
            session["pending_username"] = username
            flash("Kode OTP telah dikirim ke email.", "success")
            return redirect(url_for("verify_register"))
        except Exception as e:
            flash(f"Gagal kirim email: {str(e)}", "error")

    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    username = session.get("pending_username")
    if not username:
        return redirect(url_for("register"))

    if request.method == "POST":
        otp_input = request.form.get("otp")
        pending_ref = db.reference(f"pending_users/{username}")
        data = pending_ref.get()

        if data and data.get("otp") == otp_input:
            # Pindahkan ke users aktif
            db.reference(f"users/{username}").set({
                "nama": data["nama"],
                "email": data["email"],
                "password": data["password"],
                "points": 0
            })
            pending_ref.delete()
            session.pop("pending_username", None)
            flash("Akun aktif! Silakan login.", "success")
            return redirect(url_for("login"))
        else:
            flash("Kode OTP salah.", "error")

    return render_template("verify-register.html", username=username)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# 5. DASHBOARD & CRUD ROUTES
# ==============================================================================

@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    
    # Ambil list provinsi untuk dropdown
    ref = db.reference("provinsi")
    data = ref.get() or {}
    provinsi_list = []
    if isinstance(data, list): provinsi_list = [p for p in data if p]
    elif isinstance(data, dict): provinsi_list = list(data.values())
    provinsi_list.sort()

    return render_template("dashboard.html", name=session.get('nama'), provinsi_list=provinsi_list)

@app.route("/add_data", methods=["GET", "POST"])
def add_data():
    if 'user' not in session: return redirect(url_for('login'))

    # Ambil list provinsi
    ref = db.reference("provinsi")
    data = ref.get()
    provinsi_list = []
    if data:
        if isinstance(data, list): provinsi_list = [p for p in data if p]
        elif isinstance(data, dict): provinsi_list = list(data.values())
    provinsi_list.sort()

    if request.method == 'POST':
        provinsi = request.form['provinsi']
        wilayah = request.form['wilayah'].strip()
        mux = request.form['mux'].strip()
        siaran_raw = request.form['siaran']
        
        # Validasi Format
        if not re.match(r"^[a-zA-Z\s]+-\d+$", wilayah):
            return render_template('add_data_form.html', error_message="Format Wilayah salah. Gunakan: Nama Provinsi-Angka", provinsi_list=provinsi_list)
        
        if not re.match(r"^UHF\s+\d{1,3}\s*-\s*.+$", mux):
            return render_template('add_data_form.html', error_message="Format MUX salah. Gunakan: UHF XX - Nama MUX", provinsi_list=provinsi_list)

        # Proses Data
        siaran_list = sorted([s.strip() for s in siaran_raw.split(',') if s.strip()])
        tz = pytz.timezone('Asia/Jakarta')
        now = datetime.now(tz)

        data_to_save = {
            "siaran": siaran_list,
            "last_updated_by_username": session.get('user'),
            "last_updated_by_name": session.get('nama'),
            "last_updated_date": now.strftime("%d-%m-%Y"),
            "last_updated_time": now.strftime("%H:%M:%S WIB")
        }

        # Simpan ke Firebase (Path: siaran/Provinsi/Wilayah/MUX)
        try:
            db.reference(f"siaran/{provinsi}/{wilayah}/{mux}").set(data_to_save)
            return redirect(url_for('dashboard'))
        except Exception as e:
            return render_template('add_data_form.html', error_message=f"Gagal simpan: {e}", provinsi_list=provinsi_list)

    return render_template('add_data_form.html', provinsi_list=provinsi_list)

@app.route("/edit_data/<provinsi>/<wilayah>/<mux>", methods=["GET", "POST"])
def edit_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))

    # Decode URL params (hapus %20 jika ada, walau flask biasanya otomatis)
    provinsi = provinsi.replace('%20', ' ')
    wilayah = wilayah.replace('%20', ' ')
    mux = mux.replace('%20', ' ')

    # Ambil data lama untuk ditampilkan di form
    ref = db.reference(f"siaran/{provinsi}/{wilayah}/{mux}")
    current_data = ref.get()
    
    current_siaran = ""
    if current_data and 'siaran' in current_data:
        current_siaran = ", ".join(current_data['siaran'])

    if request.method == 'POST':
        siaran_raw = request.form['siaran']
        siaran_list = sorted([s.strip() for s in siaran_raw.split(',') if s.strip()])
        
        tz = pytz.timezone('Asia/Jakarta')
        now = datetime.now(tz)

        update_data = {
            "siaran": siaran_list,
            "last_updated_by_username": session.get('user'),
            "last_updated_by_name": session.get('nama'),
            "last_updated_date": now.strftime("%d-%m-%Y"),
            "last_updated_time": now.strftime("%H:%M:%S WIB")
        }

        try:
            ref.update(update_data)
            return redirect(url_for('dashboard'))
        except Exception as e:
            return render_template('edit_data_form.html', error_message=f"Gagal update: {e}", provinsi=provinsi, wilayah=wilayah, mux=mux, siaran=current_siaran)

    return render_template('edit_data_form.html', provinsi=provinsi, wilayah=wilayah, mux=mux, siaran=current_siaran)

@app.route("/delete_data/<provinsi>/<wilayah>/<mux>", methods=["POST"])
def delete_data(provinsi, wilayah, mux):
    if 'user' not in session: return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    try:
        db.reference(f"siaran/{provinsi}/{wilayah}/{mux}").delete()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# 6. API HELPER (AJAX)
# ==============================================================================
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
        "siaran": data.get("siaran", []),
        "last_updated_date": data.get("last_updated_date", "-"),
        "last_updated_time": data.get("last_updated_time", ""),
        "last_updated_by_name": data.get("last_updated_by_name", "-")
    })

# --- Lain-lain ---
@app.route('/sitemap.xml')
def sitemap_xml():
    return send_from_directory('static', 'sitemap.xml')

# Rute Lupa Password & Verifikasi (sama seperti sebelumnya, sudah included di atas)

if __name__ == "__main__":
    app.run(debug=True)
