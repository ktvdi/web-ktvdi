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

# --- 1. KONFIGURASI SISTEM ---
load_dotenv() 

app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("SECRET_KEY", "rahasia_donk")

# --- 2. KONEKSI FIREBASE ---
try:
    if not firebase_admin._apps:
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
        firebase_admin.initialize_app(cred, {'databaseURL': os.environ.get('DATABASE_URL')})
    ref = db.reference('/')
    print("✅ Firebase Terhubung!")
except Exception as e:
    print(f"⚠️ Peringatan Firebase: {e}")

# --- 3. KONEKSI EMAIL ---
app.config['MAIL_SERVER'] = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
app.config['MAIL_PORT'] = int(os.environ.get("MAIL_PORT", 587))
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD")
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")
mail = Mail(app)

# --- 4. KONEKSI AI (GEMINI) ---
if os.environ.get("GEMINI_APP_KEY"):
    genai.configure(api_key=os.environ.get("GEMINI_APP_KEY"))
    model = genai.GenerativeModel("gemini-2.5-flash", system_instruction="Anda adalah Asisten KTVDI. Jawab singkat dan sopan.")
else:
    model = None

# --- 5. FUNGSI BANTUAN ---
def get_bmkg_gempa():
    try:
        url = "https://data.bmkg.go.id/DataMKG/TEWS/autogempa.json"
        resp = requests.get(url, timeout=3)
        if resp.status_code == 200:
            data = resp.json()['Infogempa']['gempa']
            data['Tanggal'] = f"{data['Tanggal']}, {data['Jam']}"
            return data
    except: return None
    return None

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def time_since_published(published_time):
    now = datetime.now()
    publish_time = datetime(*published_time[:6])
    delta = now - publish_time
    if delta.days >= 1: return f"{delta.days} hari lalu"
    if delta.seconds >= 3600: return f"{delta.seconds // 3600} jam lalu"
    return "Baru saja"

# --- 6. ROUTE UTAMA (HOME) ---
@app.route("/", methods=['GET', 'POST'])
def home():
    # =================================================================
    # 🔥 MODE MAINTENANCE AKTIF (DENGAN BERITA GOOGLE NEWS) 🔥
    # =================================================================
    
    # 1. Ambil Berita Nasional Terkini (RSS Feed)
    berita_nasional = []
    try:
        # Link RSS Google News Topik Indonesia
        rss_url = 'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFZxYUdjU0FtdHZHZ0pMVWlnQVAB?hl=id&gl=ID&ceid=ID%3Aid'
        feed = feedparser.parse(rss_url)
        
        # Ambil 10 Judul Berita Teratas
        for entry in feed.entries[:10]:
            berita_nasional.append(entry.title)
    except Exception as e:
        print(f"Gagal ambil berita: {e}")
        berita_nasional = ["Situs sedang dalam perbaikan.", "Update sistem sedang berlangsung.", "Mohon kembali lagi nanti."]

    # 2. Tampilkan Halaman Maintenance
    # Hapus baris 'return' di bawah ini jika ingin website kembali normal
    return render_template('maintenance.html', news_list=berita_nasional)
    
    # =================================================================
    # KODE ASLI (NORMAL) - TIDAK AKAN JALAN SELAMA DIATAS ADA RETURN
    # =================================================================
    
    if request.method == 'POST':
        try:
            prompt = request.get_json().get("prompt")
            reply = model.generate_content(prompt).text if model else "AI belum aktif."
            return jsonify({"response": reply})
        except: return jsonify({"error": "Error"}), 500

    try: siaran_data = db.reference('siaran').get() or {}
    except: siaran_data = {}

    stats = {'wilayah': 0, 'siaran': 0, 'mux': 0, 'last_update': None, 'top_channel': "-", 'top_count': 0}
    counter = Counter()

    if siaran_data:
        for p_val in siaran_data.values():
            if isinstance(p_val, dict):
                stats['wilayah'] += len(p_val)
                for w_val in p_val.values():
                    if isinstance(w_val, dict):
                        stats['mux'] += len(w_val)
                        for m_val in w_val.values():
                            if 'siaran' in m_val:
                                stats['siaran'] += len(m_val['siaran'])
                                for s in m_val['siaran']: counter[s.lower()] += 1
                            if 'last_updated_date' in m_val:
                                try:
                                    d = datetime.strptime(m_val['last_updated_date'], '%d-%m-%Y')
                                    if not stats['last_update'] or d > stats['last_update']: stats['last_update'] = d
                                except: pass

    if counter:
        top = counter.most_common(1)[0]
        stats['top_channel'] = top[0].upper()
        stats['top_count'] = top[1]
    
    last_update_str = stats['last_update'].strftime('%d-%m-%Y') if stats['last_update'] else "-"
    gempa = get_bmkg_gempa()

    return render_template('index.html', 
                           most_common_siaran_name=stats['top_channel'],
                           most_common_siaran_count=stats['top_count'],
                           jumlah_wilayah_layanan=stats['wilayah'],
                           jumlah_siaran=stats['siaran'],
                           jumlah_penyelenggara_mux=stats['mux'],
                           last_updated_time=last_update_str,
                           gempa_data=gempa)

# --- 7. ROUTE LAINNYA ---

@app.route("/daftar-siaran")
def daftar_siaran():
    try: data = db.reference("provinsi").get() or {}
    except: data = {}
    return render_template("daftar-siaran.html", provinsi_list=list(data.values()))

@app.route('/berita')
def berita():
    try:
        feed = feedparser.parse('https://news.google.com/rss/search?q=tv+digital+indonesia&hl=id&gl=ID&ceid=ID:id')
        articles = feed.entries[:5]
        for a in articles:
            if 'published_parsed' in a: a.time_since_published = time_since_published(a.published_parsed)
        return render_template('berita.html', articles=articles, page=1, total_pages=1)
    except: return render_template('berita.html', articles=[], page=1, total_pages=1)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = request.form['username'].strip()
        pw = hash_password(request.form['password'].strip())
        try:
            u_data = db.reference(f'users/{user}').get()
            if u_data and u_data.get('password') == pw:
                session['user'] = user
                session['nama'] = u_data.get('nama')
                return redirect(url_for('dashboard'))
            return render_template('login.html', error="Login Gagal")
        except: return render_template('login.html', error="Error DB")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        nama = request.form.get("nama")
        email = request.form.get("email")
        user = request.form.get("username")
        pw = request.form.get("password")
        
        if len(pw) < 8:
            flash("Password minimal 8 karakter.", "error")
            return render_template("register.html")
            
        hashed = hash_password(pw)
        otp = str(random.randint(100000, 999999))
        
        db.reference(f"pending_users/{user}").set({
            "nama": nama, "email": email, "password": hashed, "otp": otp
        })
        
        try:
            msg = Message("Kode OTP KTVDI", recipients=[email])
            msg.body = f"Kode OTP Anda: {otp}"
            mail.send(msg)
            session["pending_username"] = user
            return redirect(url_for("verify_register"))
        except:
            flash("Gagal kirim email OTP.", "error")
            
    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    user = session.get("pending_username")
    if not user: return redirect(url_for("register"))
    
    if request.method == "POST":
        otp = request.form.get("otp")
        pending = db.reference(f"pending_users/{user}").get()
        
        if pending and pending.get('otp') == otp:
            db.reference(f"users/{user}").set({
                "nama": pending['nama'], "email": pending['email'], 
                "password": pending['password'], "points": 0
            })
            db.reference(f"pending_users/{user}").delete()
            session.pop("pending_username", None)
            flash("Sukses! Silakan Login.", "success")
            return redirect(url_for("login"))
        else:
            flash("Kode OTP Salah.", "error")
            
    return render_template("verify-register.html", username=user)

# --- 8. DASHBOARD & CRUD DATA ---

@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    try: p_list = list(db.reference("provinsi").get().values())
    except: p_list = []
    return render_template("dashboard.html", name=session.get('nama'), provinsi_list=p_list)

@app.route("/add_data", methods=["GET", "POST"])
def add_data():
    if 'user' not in session: return redirect(url_for('login'))
    p_list = list(db.reference("provinsi").get().values())
    
    if request.method == 'POST':
        prov = request.form['provinsi']
        wil = request.form['wilayah'].strip()
        mux = request.form['mux'].strip()
        siaran = sorted([s.strip() for s in request.form['siaran'].split(',') if s.strip()])
        
        if not re.match(r"^[a-zA-Z\s]+-\d+$", wil):
            return render_template('add_data_form.html', error_message="Format Wilayah Salah (Cth: Jabar-1)", provinsi_list=p_list)
        
        now = datetime.now(pytz.timezone('Asia/Jakarta'))
        data = {
            "siaran": siaran,
            "last_updated_by_username": session['user'],
            "last_updated_by_name": session['nama'],
            "last_updated_date": now.strftime("%d-%m-%Y"),
            "last_updated_time": now.strftime("%H:%M:%S WIB")
        }
        db.reference(f"siaran/{prov}/{wil}/{mux}").set(data)
        return redirect(url_for('dashboard'))
        
    return render_template('add_data_form.html', provinsi_list=p_list)

@app.route("/edit_data/<provinsi>/<wilayah>/<mux>", methods=["GET", "POST"])
def edit_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    provinsi = provinsi.replace('%20',' ')
    wilayah = wilayah.replace('%20', ' ')
    mux = mux.replace('%20', ' ')

    if request.method == 'POST':
        siaran = sorted([s.strip() for s in request.form['siaran'].split(',') if s.strip()])
        now = datetime.now(pytz.timezone('Asia/Jakarta'))
        data = {
            "siaran": siaran,
            "last_updated_by_username": session['user'],
            "last_updated_by_name": session['nama'],
            "last_updated_date": now.strftime("%d-%m-%Y"),
            "last_updated_time": now.strftime("%H:%M:%S WIB")
        }
        db.reference(f"siaran/{provinsi}/{wilayah}/{mux}").update(data)
        return redirect(url_for('dashboard'))
        
    return render_template('edit_data_form.html', provinsi=provinsi, wilayah=wilayah, mux=mux)

@app.route("/delete_data/<provinsi>/<wilayah>/<mux>", methods=["POST"])
def delete_data(provinsi, wilayah, mux):
    if 'user' in session:
        db.reference(f"siaran/{provinsi}/{wilayah}/{mux}").delete()
    return redirect(url_for('dashboard'))

# --- 9. API AJAX (GET DATA) ---
@app.route("/get_wilayah")
def get_wilayah():
    return jsonify({"wilayah": list((db.reference(f"siaran/{request.args.get('provinsi')}").get() or {}).keys())})

@app.route("/get_mux")
def get_mux():
    return jsonify({"mux": list((db.reference(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}").get() or {}).keys())})

@app.route("/get_siaran")
def get_siaran():
    return jsonify(db.reference(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}/{request.args.get('mux')}").get() or {})

# --- 10. ERROR HANDLING ---
@app.errorhandler(404)
def not_found(e): return "<h1>404 - Halaman Tidak Ditemukan</h1>", 404

@app.errorhandler(500)
def server_error(e): return "<h1>500 - Server Bermasalah</h1><p>Cek file .env Anda.</p>", 500

@app.route('/sitemap.xml')
def sitemap():
    return send_from_directory('static', 'sitemap.xml')

# Routes Auth Lupa Password (Placeholder)
@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        flash("Fitur sedang maintenance.", "info")
        return redirect(url_for('login'))
    return render_template("forgot-password.html")

@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    return render_template("verify-otp.html")

@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    return render_template("reset-password.html")

if __name__ == "__main__":
    app.run(debug=True)
