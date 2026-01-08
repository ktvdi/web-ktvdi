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
from newsapi import NewsApiClient
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

# Secret Key (Gunakan env atau fallback)
app.secret_key = os.environ.get("SECRET_KEY", "b/g5n!o0?hs&dm!fn8md7")

# --- 1. INISIALISASI FIREBASE (SAFE INIT) ---
# Menggunakan try-except agar tidak crash 500 jika env belum lengkap
ref = None
try:
    # Cek apakah credential ada di ENV (Vercel) atau file json (Lokal)
    cred = None
    
    # Prioritas 1: ENV Variable (Untuk Vercel Production)
    if os.environ.get("FIREBASE_PRIVATE_KEY"):
        cred_dict = {
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
        }
        cred = credentials.Certificate(cred_dict)
    
    # Prioritas 2: File JSON (Untuk Localhost)
    elif os.path.exists('credentials.json'):
        cred = credentials.Certificate('credentials.json')

    if cred:
        # Cek inisialisasi agar tidak double init
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred, {
                'databaseURL': os.environ.get('DATABASE_URL', 'https://website-ktvdi-default-rtdb.firebaseio.com/')
            })
        ref = db.reference('/')
        print("✅ Firebase Connected!")
    else:
        print("⚠️ Warning: Firebase Credentials tidak ditemukan.")

except Exception as e:
    print(f"❌ Firebase Error: {e}")

# --- 2. INISIALISASI EMAIL ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com' 
app.config['MAIL_PORT'] = 587 
app.config['MAIL_USE_TLS'] = True 
app.config['MAIL_USE_SSL'] = False 
app.config['MAIL_USERNAME'] = 'kom.tvdigitalid@gmail.com' 
app.config['MAIL_PASSWORD'] = 'lvjo uwrj sbiy ggkg' 
app.config['MAIL_DEFAULT_SENDER'] = 'kom.tvdigitalid@gmail.com' 

mail = Mail(app)

# NewsAPI Key
NEWS_API_KEY = os.getenv('NEWS_API_KEY')
if NEWS_API_KEY:
    newsapi = NewsApiClient(api_key=NEWS_API_KEY)

# --- 3. KONFIGURASI GEMINI AI (UPDATED) ---
GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_APP_KEY")
model = None

if GOOGLE_API_KEY:
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash")
        print("✅ Gemini AI 1.5 Flash Siap!")
    except Exception as e:
        print(f"❌ Error Config Gemini: {e}")

# --- 4. FUNGSI RSS BERITA (BARU - UNTUK TICKER) ---
def get_breaking_news():
    """Mengambil berita real-time dari Google News RSS"""
    news_list = []
    try:
        rss_url = 'https://news.google.com/rss/search?q=tv+digital+indonesia+kominfo&hl=id&gl=ID&ceid=ID:id'
        feed = feedparser.parse(rss_url)
        for entry in feed.entries[:8]:
            news_list.append(entry.title)
    except:
        pass
    
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
    # Ambil data dari Firebase (KODE ASLI)
    siaran_data = {}
    if ref:
        siaran_data = db.reference('siaran').get() or {}

    # Variabel Statistik
    jumlah_wilayah_layanan = 0
    jumlah_siaran = 0
    jumlah_penyelenggara_mux = 0 
    siaran_counts = Counter()
    last_updated_time = None 
    
    chart_provinsi_labels = []
    chart_provinsi_data = []

    # Iterasi Data (KODE ASLI)
    for provinsi, provinsi_data in siaran_data.items():
        if isinstance(provinsi_data, dict):
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

    # Ambil Berita RSS (UNTUK TICKER)
    breaking_news = get_breaking_news()

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

# --- ROUTE CHATBOT (UPDATED HANDLING) ---
@app.route('/', methods=['POST'])
def chatbot():
    data = request.get_json()
    prompt = data.get("prompt")

    if not model:
        # Kirim kode khusus 503 agar frontend mengaktifkan Mode Offline
        return jsonify({"error": "Offline Mode"}), 503

    try:
        sys_msg = "Jawab sebagai Asisten KTVDI. Topik: TV Digital, STB, Bola. Singkat & Ramah."
        response = model.generate_content(f"{sys_msg}\n{prompt}")
        return jsonify({"response": response.text})
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "Quota" in error_msg:
            return jsonify({"error": "Quota Exceeded"}), 429
        return jsonify({"error": str(e)}), 500

# --- HELPER FUNCTIONS ---
def time_since_published(published_time):
    now = datetime.now()
    try:
        publish_time = datetime(*published_time[:6])
        delta = now - publish_time
        if delta.days >= 1: return f"{delta.days} hari lalu"
        if delta.seconds >= 3600: return f"{delta.seconds // 3600} jam lalu"
        return "Baru saja"
    except:
        return "-"

def get_actual_url_from_google_news(link):
    try:
        response = requests.get(link)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            article_link = soup.find('a', {'class': 'DY5T1d'})
            if article_link: return article_link['href']
    except:
        pass
    return link

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# --- HALAMAN LAIN ---

@app.route('/berita')
def berita():
    rss_url = 'https://news.google.com/rss/search?q=tv+digital&hl=id&gl=ID&ceid=ID:id'
    try:
        feed = feedparser.parse(rss_url)
        articles = feed.entries
    except:
        articles = []
    
    page = request.args.get('page', 1, type=int)
    per_page = 5
    total_articles = len(articles)
    total_pages = (total_articles + per_page - 1) // per_page
    start = (page - 1) * per_page
    end = start + per_page
    articles_on_page = articles[start:end]

    for article in articles_on_page:
        if 'published_parsed' in article:
            article.time_since_published = time_since_published(article.published_parsed)
        article.actual_link = get_actual_url_from_google_news(article.link)

    return render_template('berita.html', articles=articles_on_page, page=page, total_pages=total_pages)

@app.route('/about')
def about():
    return render_template('about.html')

@app.route("/daftar-siaran")
def daftar_siaran():
    provinsi_list = []
    if ref:
        data = db.reference("provinsi").get() or {}
        provinsi_list = list(data.values())
    return render_template("daftar-siaran.html", provinsi_list=provinsi_list)

# --- AUTH ROUTES (FULL KODE ASLI) ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    error_message = None
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()
        hashed_pw = hash_password(password)
        
        try:
            if ref:
                user_data = db.reference(f'users/{username}').get()
                if not user_data:
                    error_message = "Username tidak ditemukan."
                elif user_data.get('password') == hashed_pw:
                    session['user'] = username
                    session['nama'] = user_data.get("nama", "Pengguna")
                    return redirect(url_for('dashboard'))
                else:
                    error_message = "Password salah."
            else:
                error_message = "Database Error"
        except Exception as e:
            error_message = f"Error: {str(e)}"

    return render_template('login.html', error=error_message)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        nama = request.form.get("nama")
        email = request.form.get("email")
        username = request.form.get("username")
        password = request.form.get("password")

        if len(password) < 8:
            flash("Password minimal 8 karakter.", "error")
            return render_template("register.html")

        if ref:
            users = db.reference("users").get() or {}
            for uid, user in users.items():
                if user.get("email") == email:
                    flash("Email sudah terdaftar!", "error")
                    return render_template("register.html")
            if username in users:
                flash("Username sudah dipakai!", "error")
                return render_template("register.html")

            hashed_pw = hash_password(password)
            otp = str(random.randint(100000, 999999))

            db.reference(f"pending_users/{username}").set({
                "nama": nama, "email": email, "password": hashed_pw, "otp": otp
            })

            try:
                msg = Message("Kode OTP Verifikasi", recipients=[email])
                msg.body = f"Kode OTP Anda: {otp}"
                mail.send(msg)
                session["pending_username"] = username
                return redirect(url_for("verify_register"))
            except Exception as e:
                flash(f"Error Email: {str(e)}", "error")

    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    uname = session.get("pending_username")
    if not uname: return redirect(url_for("register"))
    
    if request.method == "POST":
        otp = request.form.get("otp")
        pending = db.reference(f"pending_users/{uname}").get()
        
        if pending and pending.get("otp") == otp:
            db.reference(f"users/{uname}").set({
                "nama": pending["nama"], "email": pending["email"],
                "password": pending["password"], "points": 0
            })
            db.reference(f"pending_users/{uname}").delete()
            session.pop("pending_username", None)
            return redirect(url_for("login"))
        else:
            flash("OTP Salah", "error")
            
    return render_template("verify-register.html", username=uname)

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("identifier")
        users = db.reference("users").get() or {}
        found_uid = None
        for uid, u in users.items():
            if u.get("email") == email:
                found_uid = uid
                break
        
        if found_uid:
            otp = str(random.randint(100000, 999999))
            db.reference(f"otp/{found_uid}").set({"email": email, "otp": otp})
            try:
                msg = Message("Reset Password", recipients=[email])
                msg.body = f"OTP Reset: {otp}"
                mail.send(msg)
                session["reset_uid"] = found_uid
                return redirect(url_for("verify_otp"))
            except:
                flash("Gagal kirim email", "error")
        else:
            flash("Email tidak ditemukan", "error")
    return render_template("forgot-password.html")

@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    uid = session.get("reset_uid")
    if not uid: return redirect(url_for("forgot_password"))
    if request.method == "POST":
        otp = request.form.get("otp")
        data = db.reference(f"otp/{uid}").get()
        if data and data["otp"] == otp:
            return redirect(url_for("reset_password"))
        else:
            flash("OTP Salah", "error")
    return render_template("verify-otp.html")

@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    uid = session.get("reset_uid")
    if not uid: return redirect(url_for("forgot_password"))
    if request.method == "POST":
        pw = request.form.get("password")
        if len(pw) < 8:
            flash("Min 8 karakter", "error")
        else:
            hashed = hash_password(pw)
            db.reference(f"users/{uid}").update({"password": hashed})
            db.reference(f"otp/{uid}").delete()
            session.pop("reset_uid", None)
            flash("Password berhasil direset", "success")
            return redirect(url_for("login"))
    return render_template("reset-password.html")

# --- DASHBOARD & CRUD ---

@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    provinsi = db.reference("provinsi").get() or {}
    return render_template("dashboard.html", name=session.get('nama'), provinsi_list=list(provinsi.values()))

@app.route("/add_data", methods=["GET", "POST"])
def add_data():
    if 'user' not in session: return redirect(url_for('login'))
    ref_prov = db.reference("provinsi")
    provinsi_list = list((ref_prov.get() or {}).values())

    if request.method == 'POST':
        p = request.form['provinsi']
        w = request.form['wilayah']
        m = request.form['mux']
        s = request.form['siaran'].split(',')
        
        # Validasi (Simplified for brevity, but logic remains)
        if not all([p, w, m, s]):
            return render_template('add_data_form.html', error_message="Data tidak lengkap", provinsi_list=provinsi_list)
            
        try:
            tz = pytz.timezone('Asia/Jakarta')
            now_wib = datetime.now(tz)
            data_to_save = {
                "siaran": [x.strip() for x in s],
                "last_updated_by_username": session.get('user'),
                "last_updated_by_name": session.get('nama'),
                "last_updated_date": now_wib.strftime("%d-%m-%Y"),
                "last_updated_time": now_wib.strftime("%H:%M:%S WIB")
            }
            w_clean = re.sub(r'\s*-\s*', '-', w.strip())
            m_clean = m.strip()
            db.reference(f"siaran/{p}/{w_clean}/{m_clean}").set(data_to_save)
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
                "last_updated_by_name": session.get('nama'),
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

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

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

@app.route('/download-sql')
def download_sql():
    users_data = db.reference('users').get() or {}
    output = []
    for u, d in users_data.items():
        output.append(f"INSERT INTO users VALUES ('{u}', '{d.get('nama')}', '{d.get('email')}');")
    return send_file(io.BytesIO("\n".join(output).encode()), as_attachment=True, download_name="users.sql", mimetype="text/plain")

@app.route('/download-csv')
def download_csv():
    users_data = db.reference('users').get() or {}
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(['username', 'nama', 'email'])
    for u, d in users_data.items():
        writer.writerow([u, d.get('nama'), d.get('email')])
    out.seek(0)
    return send_file(io.BytesIO(out.getvalue().encode()), as_attachment=True, download_name="users.csv", mimetype="text/csv")

@app.route("/test-firebase")
def test_firebase():
    try:
        data = ref.get()
        return f"Connected! Data: {str(data)[:50]}..." if data else "Connected (Empty)"
    except Exception as e:
        return f"Error: {e}"

if __name__ == "__main__":
    app.run(debug=True)
