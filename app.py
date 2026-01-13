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

# --- Inisialisasi Firebase ---
try:
    # Cek kredensial dari Environment Variable (untuk Vercel/Production)
    if os.environ.get("FIREBASE_PRIVATE_KEY"):
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
    else:
        # Fallback ke file lokal jika ada
        cred = credentials.Certificate("credentials.json")

    firebase_admin.initialize_app(cred, {
        'databaseURL': os.environ.get('DATABASE_URL')
    })

    ref = db.reference('/')
    print("✅ Firebase berhasil terhubung!")

except Exception as e:
    print("❌ Error initializing Firebase:", str(e))
    ref = None

# --- Inisialisasi Email ---
app.config['MAIL_SERVER'] = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
app.config['MAIL_PORT'] = int(os.environ.get("MAIL_PORT", 587))
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD")
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")

mail = Mail(app)

# --- Konfigurasi Gemini API Key ---
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
)

# --- Helper Functions ---
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def time_since_published(published_time):
    now = datetime.now()
    try:
        publish_time = datetime(*published_time[:6])
        delta = now - publish_time
        if delta.days >= 1: return f"{delta.days} hari lalu"
        if delta.seconds >= 3600: return f"{delta.seconds // 3600} jam lalu"
        return "Baru saja"
    except: return ""

# --- ROUTES UTAMA ---

@app.route("/")
def home():
    # Ambil data dari seluruh node "siaran" untuk semua provinsi
    siaran_data = ref.child('siaran').get() if ref else {}

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
                        
                        # Menghitung jumlah siaran dari penyelenggara mux
                        for penyelenggara, penyelenggara_details in wilayah_data.items():
                            if 'siaran' in penyelenggara_details:
                                jumlah_siaran += len(penyelenggara_details['siaran']) 
                                for siaran in penyelenggara_details['siaran']:
                                    siaran_counts[siaran.lower()] += 1
                    
                    # Mengambil waktu terakhir pembaruan jika ada
                    if 'last_updated_date' in penyelenggara_details:
                        current_updated_time_str = penyelenggara_details['last_updated_date']
                        try:
                            current_updated_time = datetime.strptime(current_updated_time_str, '%d-%m-%Y')
                        except ValueError:
                            current_updated_time = None
                        if current_updated_time and (last_updated_time is None or current_updated_time > last_updated_time):
                            last_updated_time = current_updated_time

    # Menentukan siaran TV terbanyak berdasarkan hitungan
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
    
    # Kirim variabel LENGKAP ke template agar index.html default Anda bekerja
    return render_template('index.html', 
                           most_common_siaran_name=most_common_siaran_name,
                           most_common_siaran_count=most_common_siaran_count,
                           jumlah_wilayah_layanan=jumlah_wilayah_layanan,
                           jumlah_siaran=jumlah_siaran, 
                           jumlah_penyelenggara_mux=jumlah_penyelenggara_mux, 
                           last_updated_time=last_updated_time)

@app.route('/', methods=['POST'])
def chatbot():
    data = request.get_json()
    prompt = data.get("prompt")

    try:
        response = model.generate_content(prompt)
        return jsonify({"response": response.text})
    except Exception as e:
        return jsonify({"error": str(e)})

# ==========================================
# 🆕 TAMBAHAN ROUTE: CCTV & JADWAL SHOLAT
# ==========================================

@app.route("/cctv")
def cctv_page():
    return render_template("cctv.html")

@app.route("/jadwal-sholat")
def jadwal_sholat_page():
    # Daftar Kota Lengkap
    daftar_kota = [
        {"id": "1106", "nama": "Purwodadi (Grobogan)"},
        {"id": "1108", "nama": "Kota Semarang"},
        {"id": "1301", "nama": "DKI Jakarta"},
        {"id": "1630", "nama": "Kota Surabaya"},
        {"id": "1219", "nama": "Kota Bandung"},
        {"id": "0224", "nama": "Kota Medan"},
        {"id": "1221", "nama": "Kota Bekasi"},
        {"id": "2701", "nama": "Kota Makassar"},
        {"id": "0612", "nama": "Kota Palembang"},
        {"id": "1222", "nama": "Kota Depok"},
        {"id": "3006", "nama": "Kabupaten Pekalongan"},
        {"id": "3210", "nama": "Kota Batam"},
        {"id": "0412", "nama": "Kota Pekanbaru"},
        {"id": "1633", "nama": "Kota Malang"},
        {"id": "1130", "nama": "Kota Surakarta (Solo)"},
        {"id": "1009", "nama": "Kota Yogyakarta"},
        {"id": "1701", "nama": "Kota Denpasar"}
    ]
    # Sortir
    daftar_kota = sorted(daftar_kota, key=lambda x: x['nama'])
    return render_template("jadwal-sholat.html", daftar_kota=daftar_kota)

@app.route("/api/jadwal-sholat/<id_kota>")
def get_jadwal_api(id_kota):
    try:
        today = datetime.now().strftime("%Y/%m/%d")
        url = f"https://api.myquran.com/v2/sholat/jadwal/{id_kota}/{today}"
        r = requests.get(url, timeout=5)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# ==========================================
# AKHIR TAMBAHAN ROUTE
# ==========================================

@app.route('/sitemap.xml')
def sitemap():
    return send_from_directory('static', 'sitemap.xml')

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("identifier")
        users_ref = db.reference("users")
        users = users_ref.get() or {}
        
        found_uid = None
        for uid, user in users.items():
            if "email" in user and user["email"].lower() == email.lower():
                found_uid = uid
                break

        if found_uid:
            otp = str(random.randint(100000, 999999))
            db.reference(f"otp/{found_uid}").set({"email": email, "otp": otp})
            try:
                msg = Message("Reset Password KTVDI", recipients=[email])
                msg.body = f"Kode OTP Anda: {otp}"
                mail.send(msg)
                session["reset_uid"] = found_uid
                return redirect(url_for("verify_otp"))
            except Exception as e:
                flash(f"Error kirim email: {str(e)}", "error")
        else:
            flash("Email tidak ditemukan!", "error")
    return render_template("forgot-password.html")

@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    uid = session.get("reset_uid")
    if not uid: return redirect(url_for("forgot_password"))
    
    if request.method == "POST":
        if str(db.reference(f"otp/{uid}/otp").get()) == request.form.get("otp"):
            return redirect(url_for("reset_password"))
        flash("OTP Salah", "error")
    return render_template("verify-otp.html")

@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    uid = session.get("reset_uid")
    if not uid: return redirect(url_for("forgot_password"))
    
    if request.method == "POST":
        pw = hash_password(request.form.get("password"))
        db.reference(f"users/{uid}").update({"password": pw})
        db.reference(f"otp/{uid}").delete()
        session.pop("reset_uid", None)
        flash("Password berhasil direset", "success")
        return redirect(url_for("login"))
    return render_template("reset-password.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        user = request.form.get("username")
        email = request.form.get("email")
        
        if db.reference(f"users/{user}").get():
            flash("Username sudah dipakai", "error")
            return render_template("register.html")
            
        otp = str(random.randint(100000, 999999))
        db.reference(f"pending_users/{user}").set({
            "nama": request.form.get("nama"), "email": email, 
            "password": hash_password(request.form.get("password")), "otp": otp
        })
        try:
            msg = Message("Verifikasi KTVDI", recipients=[email])
            msg.body = f"Kode OTP: {otp}"
            mail.send(msg)
            session["pending_username"] = user
            return redirect(url_for("verify_register"))
        except: flash("Gagal kirim email", "error")
    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    user = session.get("pending_username")
    if not user: return redirect(url_for("register"))
    
    if request.method == "POST":
        pending = db.reference(f"pending_users/{user}").get()
        if pending and str(pending['otp']) == request.form.get("otp"):
            db.reference(f"users/{user}").set({
                "nama": pending['nama'], "email": pending['email'], 
                "password": pending['password'], "points": 0
            })
            db.reference(f"pending_users/{user}").delete()
            flash("Berhasil", "success")
            return redirect(url_for("login"))
        flash("OTP Salah", "error")
    return render_template("verify-register.html", username=user)

@app.route("/daftar-siaran")
def daftar_siaran():
    prov = db.reference("provinsi").get() or {}
    return render_template("daftar-siaran.html", provinsi_list=list(prov.values()))

@app.route("/get_wilayah")
def get_wilayah():
    d = db.reference(f"siaran/{request.args.get('provinsi')}").get() or {}
    return jsonify({"wilayah": list(d.keys())})

@app.route("/get_mux")
def get_mux():
    d = db.reference(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}").get() or {}
    return jsonify({"mux": list(d.keys())})

@app.route("/get_siaran")
def get_siaran():
    return jsonify(db.reference(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}/{request.args.get('mux')}").get() or {})

@app.route('/berita')
def berita():
    feed = feedparser.parse('https://news.google.com/rss/search?q=tv+digital&hl=id&gl=ID&ceid=ID:id')
    articles = feed.entries
    page = request.args.get('page', 1, type=int)
    per_page = 5
    start = (page - 1) * per_page
    end = start + per_page
    current = articles[start:end]
    for a in current:
        if hasattr(a, 'published_parsed'):
            a.time_since_published = time_since_published(a.published_parsed)
    return render_template('berita.html', articles=current, page=page, total_pages=(len(articles) + per_page - 1) // per_page)

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = request.form['username'].strip()
        pw = hash_password(request.form['password'].strip())
        udata = db.reference(f'users/{user}').get()
        if udata and udata.get('password') == pw:
            session['user'] = user
            session['nama'] = udata.get('nama')
            return redirect(url_for('dashboard'))
        return render_template('login.html', error="Login Gagal")
    return render_template('login.html')

@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    prov = db.reference("provinsi").get() or {}
    return render_template("dashboard.html", name=session.get('nama'), provinsi_list=list(prov.values()))

@app.route("/add_data", methods=["GET", "POST"])
def add_data():
    if 'user' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        p, w, m = request.form['provinsi'], request.form['wilayah'].replace(' ', ''), request.form['mux']
        s = sorted([x.strip() for x in request.form['siaran'].split(',') if x.strip()])
        db.reference(f'siaran/{p}/{w}/{m}').set({"siaran": s, "last_updated_by_username": session['user'], "last_updated_date": datetime.now().strftime("%d-%m-%Y")})
        return redirect(url_for('dashboard'))
    prov = db.reference("provinsi").get() or {}
    return render_template('add_data_form.html', provinsi_list=list(prov.values()))

@app.route("/edit_data/<provinsi>/<wilayah>/<mux>", methods=["GET", "POST"])
def edit_data(provinsi, wilayah, mux):
    # Route ini sama seperti default Anda, hanya dirapikan
    if 'user' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        s = sorted([x.strip() for x in request.form['siaran'].split(',') if x.strip()])
        db.reference(f'siaran/{provinsi}/{wilayah}/{mux}').update({"siaran": s, "last_updated_date": datetime.now().strftime("%d-%m-%Y")})
        return redirect(url_for('dashboard'))
    return render_template('edit_data_form.html', provinsi=provinsi, wilayah=wilayah, mux=mux)

@app.route("/delete_data/<provinsi>/<wilayah>/<mux>", methods=["POST"])
def delete_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    db.reference(f'siaran/{provinsi}/{wilayah}/{mux}').delete()
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

@app.route("/test-firebase")
def test_firebase():
    try:
        if ref is None: return "❌ Firebase Error"
        data = ref.get()
        return f"✅ Connected. Data: {data}" if data else "✅ Connected (Empty)"
    except Exception as e: return f"❌ Error: {e}"

if __name__ == "__main__":
    app.run(debug=True)
