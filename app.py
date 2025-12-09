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

# --- KONFIGURASI AWAL ---
load_dotenv()

app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-ktvdi")

# --- 1. SETUP FIREBASE ---
try:
    # Pastikan environment variables sudah di-set di .env atau server
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
    
    # Cek apakah app sudah diinisialisasi untuk menghindari error double init
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred, {'databaseURL': os.environ.get('DATABASE_URL')})
    
    ref = db.reference('/')
    print("✅ Firebase Terhubung")
except Exception as e:
    print(f"❌ Firebase Error: {e}")
    ref = None

# --- 2. SETUP EMAIL ---
app.config['MAIL_SERVER'] = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
app.config['MAIL_PORT'] = int(os.environ.get("MAIL_PORT", 587))
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD")
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")
mail = Mail(app)

# --- 3. SETUP GEMINI AI ---
genai.configure(api_key=os.environ.get("GEMINI_APP_KEY"))
model = genai.GenerativeModel(
    "gemini-2.5-flash", 
    system_instruction="Anda adalah Chatbot AI KTVDI (Komunitas TV Digital Indonesia). Tugas Anda menjawab pertanyaan seputar TV Digital, STB, Antena, MUX, dan fitur website ini dengan bahasa yang santai, ramah, dan membantu. Jika ditanya soal cuaca atau gempa, arahkan user melihat widget di halaman beranda."
)

# --- FUNGSI BANTUAN (BMKG & UTILS) ---
def get_gempa_terkini():
    """Mengambil data gempa dirasakan dari BMKG"""
    try:
        # Gunakan gempadirasakan.json agar gempa kecil yang terasa tetap muncul
        url = "https://data.bmkg.go.id/DataMKG/TEWS/gempadirasakan.json"
        r = requests.get(url, timeout=3)
        if r.status_code == 200:
            # Ambil gempa pertama (terbaru)
            return r.json()['Infogempa']['gempa'][0]
    except Exception as e:
        print(f"Error Gempa: {e}")
        return None
    return None

def get_cuaca_default():
    """Data cuaca default (Semarang) untuk render awal sebelum GPS aktif"""
    try:
        # API Open-Meteo untuk Semarang (Lokasi Default)
        url = "https://api.open-meteo.com/v1/forecast?latitude=-6.99&longitude=110.42&current_weather=true"
        r = requests.get(url, timeout=3)
        if r.status_code == 200:
            d = r.json()['current_weather']
            code = d['weathercode']
            desc = "Cerah"
            if code > 3: desc = "Berawan"
            if code > 50: desc = "Hujan"
            if code > 80: desc = "Hujan Lebat"
            
            return {
                't': round(d['temperature']),
                'ws': d['windspeed'],
                'weather_desc': desc,
                'lokasi': 'Semarang (Default)'
            }
    except Exception as e:
        print(f"Error Cuaca: {e}")
        return None
    return None

def hash_pw(password):
    return hashlib.sha256(password.encode()).hexdigest()

# --- ROUTE UTAMA (BERANDA) ---
@app.route("/")
def home():
    # Ambil data siaran dari Firebase
    ref = db.reference('siaran')
    siaran_data = ref.get()

    # Inisialisasi Variabel Statistik
    stats = {
        'wilayah': 0,
        'siaran': 0,
        'mux': 0,
        'top_name': '-',
        'top_count': 0,
        'last_update': datetime.now().strftime('%d-%m-%Y')
    }
    
    provinsi_tersedia = [] # List ini PENTING untuk fitur "Cek Jangkauan" di JS
    siaran_counts = Counter()
    last_updated_dt = None

    if siaran_data:
        provinsi_tersedia = list(siaran_data.keys())
        for provinsi, prov_data in siaran_data.items():
            if isinstance(prov_data, dict):
                stats['wilayah'] += len(prov_data)
                for wilayah, wil_data in prov_data.items():
                    if isinstance(wil_data, dict):
                        stats['mux'] += len(wil_data)
                        for mux, mux_data in wil_data.items():
                            # Hitung Channel
                            if 'siaran' in mux_data:
                                stats['siaran'] += len(mux_data['siaran'])
                                for s in mux_data['siaran']:
                                    siaran_counts[s.lower()] += 1
                            
                            # Cek Tanggal Update Terakhir
                            if 'last_updated_date' in mux_data:
                                try:
                                    curr_dt = datetime.strptime(mux_data['last_updated_date'], '%d-%m-%Y')
                                    if last_updated_dt is None or curr_dt > last_updated_dt:
                                        last_updated_dt = curr_dt
                                except: pass

    # Set Statistik Terbanyak & Tanggal
    if siaran_counts:
        top = siaran_counts.most_common(1)[0]
        stats['top_name'] = top[0].upper()
        stats['top_count'] = top[1]
    
    if last_updated_dt:
        stats['last_update'] = last_updated_dt.strftime('%d-%m-%Y')

    # Ambil Data API Eksternal
    gempa_data = get_gempa_terkini()
    cuaca_data = get_cuaca_default()

    # Kirim SEMUA variable ini ke index.html
    return render_template('index.html', 
                           # Mapping variable lama agar kompatibel dengan template
                           jumlah_wilayah_layanan=stats['wilayah'],
                           jumlah_penyelenggara_mux=stats['mux'],
                           jumlah_siaran=stats['siaran'],
                           most_common_siaran_name=stats['top_name'],
                           most_common_siaran_count=stats['top_count'],
                           last_updated_time=stats['last_update'],
                           # Variable baru
                           gempa_data=gempa_data,
                           cuaca_data=cuaca_data,
                           provinsi_tersedia=provinsi_tersedia)

# --- CHATBOT API ---
@app.route('/', methods=['POST'])
def chatbot():
    data = request.get_json()
    prompt = data.get("prompt")
    try:
        response = model.generate_content(prompt)
        return jsonify({"response": response.text})
    except Exception as e:
        return jsonify({"error": "Maaf, server AI sedang sibuk."})

# --- HALAMAN STATIS ---
@app.route('/faq')
def faq(): return render_template('faq.html')

@app.route('/about')
def about(): return render_template('about.html')

@app.route('/berita')
def berita():
    # Mengambil berita teknologi dari Google News RSS
    try:
        feed = feedparser.parse('https://news.google.com/rss/search?q=tv+digital+indonesia&hl=id&gl=ID&ceid=ID:id')
        # Pagination sederhana
        page = request.args.get('page', 1, type=int)
        per_page = 5
        start = (page - 1) * per_page
        end = start + per_page
        total_pages = (len(feed.entries) + per_page - 1) // per_page
        
        return render_template('berita.html', articles=feed.entries[start:end], page=page, total_pages=total_pages)
    except:
        return render_template('berita.html', articles=[], page=1, total_pages=1)

@app.route('/sitemap.xml')
def sitemap(): return send_from_directory('static', 'sitemap.xml')

# --- OTENTIKASI (LOGIN/REGISTER) ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = hash_pw(request.form['password'].strip())
        
        user_ref = db.reference(f'users/{username}')
        user_data = user_ref.get()

        if user_data and user_data.get('password') == password:
            session['user'] = username
            session['nama'] = user_data.get('nama', 'Pengguna')
            return redirect(url_for('dashboard'))
        
        return render_template('login.html', error="Username atau Password Salah")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        user = request.form['username']
        email = request.form['email']
        pw = hash_pw(request.form['password'])
        otp = str(random.randint(100000, 999999))
        
        # Cek user exist
        if db.reference(f"users/{user}").get():
            flash("Username sudah dipakai", "error")
            return render_template("register.html")

        db.reference(f"pending_users/{user}").set({
            "nama": request.form['nama'], "email": email, "password": pw, "otp": otp
        })
        
        try:
            msg = Message("Kode OTP KTVDI", recipients=[email])
            msg.body = f"Kode OTP Anda adalah: {otp}"
            mail.send(msg)
            session["pending_username"] = user
            return redirect(url_for("verify_register"))
        except:
            flash("Gagal mengirim email", "error")
            
    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    user = session.get("pending_username")
    if not user: return redirect(url_for("register"))
    
    if request.method == "POST":
        data = db.reference(f"pending_users/{user}").get()
        if data and data.get("otp") == request.form['otp']:
            db.reference(f"users/{user}").set({
                "nama": data["nama"], "email": data["email"], 
                "password": data["password"], "points": 0
            })
            db.reference(f"pending_users/{user}").delete()
            session.pop("pending_username", None)
            return redirect(url_for("login"))
        else:
            flash("OTP Salah", "error")
    return render_template("verify-register.html", username=user)

# --- PASSWORD RESET ---
@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("identifier")
        users = db.reference("users").get() or {}
        found_uid = next((uid for uid, u in users.items() if u.get("email") == email), None)
        
        if found_uid:
            otp = str(random.randint(100000, 999999))
            db.reference(f"otp/{found_uid}").set({"email": email, "otp": otp})
            try:
                msg = Message("Reset Password KTVDI", recipients=[email])
                msg.body = f"OTP Reset: {otp}"
                mail.send(msg)
                session["reset_uid"] = found_uid
                return redirect(url_for("verify_otp"))
            except: flash("Gagal kirim email", "error")
        else:
            flash("Email tidak terdaftar", "error")
    return render_template("forgot-password.html")

@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    uid = session.get("reset_uid")
    if not uid: return redirect(url_for("forgot_password"))
    if request.method == "POST":
        real_otp_data = db.reference(f"otp/{uid}").get()
        if real_otp_data and real_otp_data.get("otp") == request.form.get("otp"):
            return redirect(url_for("reset_password"))
    return render_template("verify-otp.html")

@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    uid = session.get("reset_uid")
    if not uid: return redirect(url_for("forgot_password"))
    if request.method == "POST":
        new_pw = hash_pw(request.form.get("password"))
        db.reference(f"users/{uid}").update({"password": new_pw})
        db.reference(f"otp/{uid}").delete()
        session.pop("reset_uid", None)
        return redirect(url_for("login"))
    return render_template("reset-password.html")

# --- DASHBOARD & CRUD DATA ---
@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    prov_list = list((db.reference("provinsi").get() or {}).values())
    return render_template("dashboard.html", name=session.get('nama'), provinsi_list=prov_list)

@app.route("/add_data", methods=["GET", "POST"])
def add_data():
    if 'user' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        prov, wil, mux = request.form['provinsi'], request.form['wilayah'], request.form['mux']
        siaran = sorted([s.strip() for s in request.form['siaran'].split(',')])
        
        now = datetime.now(pytz.timezone('Asia/Jakarta'))
        db.reference(f"siaran/{prov}/{wil}/{mux}").set({
            "siaran": siaran,
            "last_updated_by": session.get('user'),
            "last_updated_name": session.get('nama'),
            "last_updated_date": now.strftime("%d-%m-%Y"),
            "last_updated_time": now.strftime("%H:%M:%S WIB")
        })
        return redirect(url_for('dashboard'))
    
    prov_list = list((db.reference("provinsi").get() or {}).values())
    return render_template('add_data_form.html', provinsi_list=prov_list)

@app.route("/edit_data/<provinsi>/<wilayah>/<mux>", methods=["GET", "POST"])
def edit_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    # Decode URL params (hapus %20 jika ada)
    p = provinsi.replace('%20',' ')
    w = wilayah.replace('%20',' ')
    m = mux.replace('%20',' ')
    
    if request.method == 'POST':
        siaran = sorted([s.strip() for s in request.form['siaran'].split(',')])
        now = datetime.now(pytz.timezone('Asia/Jakarta'))
        db.reference(f"siaran/{p}/{w}/{m}").update({
            "siaran": siaran,
            "last_updated_by": session.get('user'),
            "last_updated_name": session.get('nama'),
            "last_updated_date": now.strftime("%d-%m-%Y"),
            "last_updated_time": now.strftime("%H:%M:%S WIB")
        })
        return redirect(url_for('dashboard'))
        
    return render_template('edit_data_form.html', provinsi=p, wilayah=w, mux=m)

@app.route("/delete_data/<provinsi>/<wilayah>/<mux>", methods=["POST"])
def delete_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    db.reference(f"siaran/{provinsi}/{wilayah}/{mux}").delete()
    return redirect(url_for('dashboard'))

# --- API HELPERS (Untuk AJAX di Frontend) ---
@app.route("/daftar-siaran")
def daftar_siaran():
    prov_list = list((db.reference("provinsi").get() or {}).values())
    return render_template("daftar-siaran.html", provinsi_list=prov_list)

@app.route("/get_wilayah")
def get_wilayah():
    p = request.args.get('provinsi')
    return jsonify({"wilayah": list((db.reference(f"siaran/{p}").get() or {}).keys())})

@app.route("/get_mux")
def get_mux():
    p, w = request.args.get('provinsi'), request.args.get('wilayah')
    return jsonify({"mux": list((db.reference(f"siaran/{p}/{w}").get() or {}).keys())})

@app.route("/get_siaran")
def get_siaran():
    p, w, m = request.args.get('provinsi'), request.args.get('wilayah'), request.args.get('mux')
    return jsonify(db.reference(f"siaran/{p}/{w}/{m}").get() or {})

@app.route("/test-firebase")
def test_firebase():
    return "✅ Firebase OK" if ref else "❌ Error"

if __name__ == "__main__":
    app.run(debug=True)
