import os
import hashlib
import firebase_admin
import random
import re
import pytz
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

# --- KONFIGURASI AWAL ---
load_dotenv()

app = Flask(__name__)
CORS(app)

# Pastikan SECRET_KEY ada di .env atau gunakan default yang kuat
app.secret_key = os.environ.get("SECRET_KEY", "kunci_rahasia_produksi_ktvdi_2025")

# --- 1. KONEKSI FIREBASE (REAL) ---
try:
    if not firebase_admin._apps:
        # Mengambil kredensial dari Environment Variables
        cred = credentials.Certificate({
            "type": "service_account",
            "project_id": os.environ.get("FIREBASE_PROJECT_ID"),
            "private_key_id": os.environ.get("FIREBASE_PRIVATE_KEY_ID"),
            "private_key": os.environ.get("FIREBASE_PRIVATE_KEY", "").replace('\\n', '\n'),
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
    print("✅ [SYSTEM] Firebase Connected Successfully.")

except Exception as e:
    # Karena ini mode real, jika gagal connect, print error fatal
    print(f"❌ [CRITICAL] Firebase Connection Failed: {str(e)}")
    # Jangan raise error dulu agar app tetap bisa start server, tapi fitur DB akan mati.

# --- 2. KONEKSI EMAIL (SMTP) ---
app.config['MAIL_SERVER'] = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
app.config['MAIL_PORT'] = int(os.environ.get("MAIL_PORT", 587))
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD")
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")

mail = Mail(app)

# --- 3. KONEKSI AI (GEMINI) ---
if os.environ.get("GEMINI_APP_KEY"):
    genai.configure(api_key=os.environ.get("GEMINI_APP_KEY"))
    model = genai.GenerativeModel("gemini-2.5-flash", 
        system_instruction="Anda adalah Asisten Virtual KTVDI. Jawab singkat, padat, dan membantu terkait TV Digital Indonesia.")
else:
    model = None
    print("⚠️ [WARNING] Gemini API Key missing.")

# --- FUNGSI BANTUAN: FETCH GEMPA BMKG (REAL-TIME) ---
def get_real_gempa():
    """Mengambil data gempa terkini langsung dari API BMKG"""
    try:
        url = "https://data.bmkg.go.id/DataMKG/TEWS/autogempa.json"
        response = requests.get(url, timeout=3) # Timeout 3 detik agar web tidak loading lama
        if response.status_code == 200:
            data = response.json()['Infogempa']['gempa']
            # Format ulang tanggal agar sesuai tampilan HTML
            # BMKG: Tanggal="22 Des 2024", Jam="19:00:00 WIB" -> Gabung
            data['Tanggal'] = f"{data['Tanggal']}, {data['Jam']}"
            return data
    except Exception as e:
        print(f"⚠️ Gagal ambil data BMKG: {e}")
        return None
    return None

# --- ROUTE UTAMA ---
@app.route("/", methods=['GET', 'POST'])
def home():
    # --- LOGIKA CHATBOT (POST) ---
    if request.method == 'POST':
        try:
            data = request.get_json()
            prompt = data.get("prompt")
            
            if model:
                response = model.generate_content(prompt)
                reply_text = response.text
            else:
                reply_text = "Maaf, sistem AI sedang pemeliharaan (API Key belum diset)."
            
            return jsonify({"response": reply_text})
        except Exception as e:
            return jsonify({"error": "Terjadi kesalahan pada server."}), 500

    # --- LOGIKA DASHBOARD PUBLIK (GET) ---
    # 1. Ambil Data Siaran dari Firebase
    siaran_data = db.reference('siaran').get() or {}

    # 2. Hitung Statistik
    jumlah_wilayah_layanan = 0
    jumlah_siaran = 0
    jumlah_penyelenggara_mux = 0
    siaran_counts = Counter()
    last_updated_time = None

    if siaran_data:
        for provinsi, p_data in siaran_data.items():
            if isinstance(p_data, dict):
                jumlah_wilayah_layanan += len(p_data)
                for wilayah, w_data in p_data.items():
                    if isinstance(w_data, dict):
                        jumlah_penyelenggara_mux += len(w_data)
                        for mux, m_data in w_data.items():
                            if 'siaran' in m_data:
                                jumlah_siaran += len(m_data['siaran'])
                                for s in m_data['siaran']:
                                    siaran_counts[s.lower()] += 1
                            
                            # Cek Last Updated
                            if 'last_updated_date' in m_data:
                                try:
                                    t_str = m_data['last_updated_date']
                                    t_obj = datetime.strptime(t_str, '%d-%m-%Y')
                                    if last_updated_time is None or t_obj > last_updated_time:
                                        last_updated_time = t_obj
                                except: pass

    # 3. Cari Siaran Terbanyak
    if siaran_counts:
        top = siaran_counts.most_common(1)[0]
        most_common_siaran_name = top[0].upper()
        most_common_siaran_count = top[1]
    else:
        most_common_siaran_name = "-"
        most_common_siaran_count = 0

    last_updated_str = last_updated_time.strftime('%d-%m-%Y') if last_updated_time else "-"

    # 4. Ambil Data Gempa Real-Time BMKG
    # Data ini dikirim ke HTML variable 'gempa_data'
    gempa_data_real = get_real_gempa()

    return render_template('index.html', 
                           most_common_siaran_name=most_common_siaran_name,
                           most_common_siaran_count=most_common_siaran_count,
                           jumlah_wilayah_layanan=jumlah_wilayah_layanan,
                           jumlah_siaran=jumlah_siaran, 
                           jumlah_penyelenggara_mux=jumlah_penyelenggara_mux, 
                           last_updated_time=last_updated_str,
                           gempa_data=gempa_data_real) # Mengirim data asli BMKG atau None

# --- ROUTE LAINNYA ---

@app.route('/sitemap.xml')
def sitemap():
    return send_from_directory('static', 'sitemap.xml')

@app.route("/daftar-siaran")
def daftar_siaran():
    provinsi_data = db.reference("provinsi").get() or {}
    provinsi_list = list(provinsi_data.values())
    return render_template("daftar-siaran.html", provinsi_list=provinsi_list)

@app.route('/berita')
def berita():
    # Mengambil RSS Google News Real
    rss_url = 'https://news.google.com/rss/search?q=tv+digital+indonesia&hl=id&gl=ID&ceid=ID:id'
    feed = feedparser.parse(rss_url)
    articles = feed.entries
    
    # Pagination
    page = request.args.get('page', 1, type=int)
    per_page = 6
    total = len(articles)
    start = (page - 1) * per_page
    end = start + per_page
    
    display_articles = articles[start:end]
    total_pages = (total + per_page - 1) // per_page
    
    # Helper Time Since
    now = datetime.now()
    for a in display_articles:
        if 'published_parsed' in a:
            pub = datetime(*a.published_parsed[:6])
            diff = now - pub
            if diff.days > 0: a.time_since = f"{diff.days} hari lalu"
            elif diff.seconds > 3600: a.time_since = f"{diff.seconds // 3600} jam lalu"
            else: a.time_since = "Baru saja"
        else:
            a.time_since = ""

    return render_template('berita.html', articles=display_articles, page=page, total_pages=total_pages)

# --- AUTH SYSTEM (LOGIN/REGISTER/OTP) ---

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("identifier")
        users = db.reference("users").get() or {}
        
        target_uid = None
        target_user = None
        
        for uid, u in users.items():
            if u.get('email', '').lower() == email.lower():
                target_uid = uid
                target_user = u
                break
        
        if target_uid:
            otp = str(random.randint(100000, 999999))
            db.reference(f"otp/{target_uid}").set({"email": email, "otp": otp})
            
            try:
                msg = Message("Reset Password KTVDI", recipients=[email])
                msg.body = f"Halo {target_user.get('nama')},\nKode OTP Anda: {otp}"
                mail.send(msg)
                session["reset_uid"] = target_uid
                flash("OTP terkirim ke email.", "success")
                return redirect(url_for("verify_otp"))
            except Exception as e:
                flash(f"Gagal kirim email: {e}", "error")
        else:
            flash("Email tidak terdaftar.", "error")
            
    return render_template("forgot-password.html")

@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    uid = session.get("reset_uid")
    if not uid: return redirect(url_for("forgot_password"))
    
    if request.method == "POST":
        input_otp = request.form.get("otp")
        real_otp = db.reference(f"otp/{uid}").get()
        
        if real_otp and real_otp.get('otp') == input_otp:
            return redirect(url_for("reset_password"))
        else:
            flash("OTP Salah.", "error")
            
    return render_template("verify-otp.html")

@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    uid = session.get("reset_uid")
    if not uid: return redirect(url_for("forgot_password"))
    
    if request.method == "POST":
        pw = request.form.get("password")
        if len(pw) < 8:
            flash("Password minimal 8 karakter.", "error")
        else:
            hashed = hashlib.sha256(pw.encode()).hexdigest()
            db.reference(f"users/{uid}").update({"password": hashed})
            db.reference(f"otp/{uid}").delete()
            session.pop("reset_uid", None)
            flash("Password berhasil diubah. Silakan login.", "success")
            return redirect(url_for("login"))
            
    return render_template("reset-password.html")

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = request.form['username'].strip()
        pw = request.form['password'].strip()
        hashed = hashlib.sha256(pw.encode()).hexdigest()
        
        user_data = db.reference(f'users/{user}').get()
        
        if user_data and user_data.get('password') == hashed:
            session['user'] = user
            session['nama'] = user_data.get('nama')
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error="Username atau Password salah.")
            
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
            flash("Password min 8 karakter", "error")
            return render_template("register.html")
            
        # Cek duplikat (bisa dioptimalkan dengan query firebase)
        users = db.reference("users").get() or {}
        if username in users:
            flash("Username sudah dipakai", "error")
            return render_template("register.html")
            
        hashed = hashlib.sha256(password.encode()).hexdigest()
        otp = str(random.randint(100000, 999999))
        
        # Simpan sementara
        db.reference(f"pending_users/{username}").set({
            "nama": nama, "email": email, "password": hashed, "otp": otp
        })
        
        try:
            msg = Message("Verifikasi KTVDI", recipients=[email])
            msg.body = f"Kode OTP Pendaftaran: {otp}"
            mail.send(msg)
            session["pending_username"] = username
            return redirect(url_for("verify_register"))
        except:
            flash("Gagal kirim email verifikasi", "error")
            
    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    user = session.get("pending_username")
    if not user: return redirect(url_for("register"))
    
    if request.method == "POST":
        otp = request.form.get("otp")
        pending = db.reference(f"pending_users/{user}").get()
        
        if pending and pending.get('otp') == otp:
            # Pindahkan ke Users Real
            db.reference(f"users/{user}").set({
                "nama": pending['nama'],
                "email": pending['email'],
                "password": pending['password'],
                "points": 0
            })
            db.reference(f"pending_users/{user}").delete()
            session.pop("pending_username", None)
            flash("Akun aktif! Silakan login.", "success")
            return redirect(url_for("login"))
        else:
            flash("OTP Salah", "error")
            
    return render_template("verify-register.html", username=user)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- DASHBOARD & CRUD DATA ---

@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    
    # Ambil data untuk dropdown provinsi
    p_data = db.reference("provinsi").get() or {}
    return render_template("dashboard.html", name=session.get('nama'), provinsi_list=list(p_data.values()))

@app.route("/add_data", methods=["GET", "POST"])
def add_data():
    if 'user' not in session: return redirect(url_for('login'))
    
    p_list = list(db.reference("provinsi").get().values())
    
    if request.method == 'POST':
        prov = request.form['provinsi']
        wil = request.form['wilayah'].strip() # Format: Jabar-1
        mux = request.form['mux'].strip()     # Format: UHF 25 - SCTV
        ch_raw = request.form['siaran']
        
        # Validasi Format Wilayah & Mux (Regex)
        if not re.match(r"^[a-zA-Z\s]+-\d+$", wil):
            return render_template('add_data_form.html', error_message="Format Wilayah Salah (Cth: Jawa Barat-1)", provinsi_list=p_list)
            
        channels = sorted([c.strip() for c in ch_raw.split(',') if c.strip()])
        
        now = datetime.now(pytz.timezone('Asia/Jakarta'))
        payload = {
            "siaran": channels,
            "last_updated_by_username": session['user'],
            "last_updated_by_name": session['nama'],
            "last_updated_date": now.strftime("%d-%m-%Y"),
            "last_updated_time": now.strftime("%H:%M:%S WIB")
        }
        
        # Simpan ke DB
        db.reference(f"siaran/{prov}/{wil}/{mux}").set(payload)
        return redirect(url_for('dashboard'))
        
    return render_template('add_data_form.html', provinsi_list=p_list)

@app.route("/edit_data/<provinsi>/<wilayah>/<mux>", methods=["GET", "POST"])
def edit_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    
    # URL Decode manual
    provinsi = provinsi.replace('%20', ' ')
    wilayah = wilayah.replace('%20', ' ')
    mux = mux.replace('%20', ' ')
    
    if request.method == 'POST':
        ch_raw = request.form['siaran']
        channels = sorted([c.strip() for c in ch_raw.split(',') if c.strip()])
        
        now = datetime.now(pytz.timezone('Asia/Jakarta'))
        payload = {
            "siaran": channels,
            "last_updated_by_username": session['user'],
            "last_updated_by_name": session['nama'],
            "last_updated_date": now.strftime("%d-%m-%Y"),
            "last_updated_time": now.strftime("%H:%M:%S WIB")
        }
        
        db.reference(f"siaran/{provinsi}/{wilayah}/{mux}").update(payload)
        return redirect(url_for('dashboard'))
        
    return render_template('edit_data_form.html', provinsi=provinsi, wilayah=wilayah, mux=mux)

@app.route("/delete_data/<provinsi>/<wilayah>/<mux>", methods=["POST"])
def delete_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    db.reference(f"siaran/{provinsi}/{wilayah}/{mux}").delete()
    return redirect(url_for('dashboard'))

# --- API HELPERS (AJAX) ---

@app.route("/get_wilayah")
def get_wilayah():
    prov = request.args.get("provinsi")
    data = db.reference(f"siaran/{prov}").get() or {}
    return jsonify({"wilayah": list(data.keys())})

@app.route("/get_mux")
def get_mux():
    prov = request.args.get("provinsi")
    wil = request.args.get("wilayah")
    data = db.reference(f"siaran/{prov}/{wil}").get() or {}
    return jsonify({"mux": list(data.keys())})

@app.route("/get_siaran")
def get_siaran():
    prov = request.args.get("provinsi")
    wil = request.args.get("wilayah")
    mux = request.args.get("mux")
    data = db.reference(f"siaran/{prov}/{wil}/{mux}").get() or {}
    return jsonify(data)

# --- ERROR HANDLERS ---
@app.errorhandler(500)
def internal_error(error):
    return "<h1>500 Internal Server Error</h1><p>Ada masalah pada server. Cek koneksi Firebase/Env Variables.</p>", 500

@app.errorhandler(404)
def not_found(error):
    return "<h1>404 Page Not Found</h1>", 404

if __name__ == "__main__":
    app.run(debug=True, port=5000)
