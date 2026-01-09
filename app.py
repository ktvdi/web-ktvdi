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
import csv
import io
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

# Secret Key (Gunakan Env di Vercel, fallback lokal)
app.secret_key = os.environ.get('SECRET_KEY', 'b/g5n!o0?hs&dm!fn8md7')

# --- 1. KONEKSI FIREBASE (VERCEL COMPATIBLE) ---
# Bagian ini saya perbaiki agar membaca Environment Variable, BUKAN file fisik.
try:
    cred = None
    # Cek apakah ada Environment Variable (Settingan Vercel)
    if os.environ.get("FIREBASE_PRIVATE_KEY"):
        # Fix format key yang sering error saat copy-paste di Vercel
        private_key = os.environ.get("FIREBASE_PRIVATE_KEY").replace('\\n', '\n').replace('"', '')
        
        cred_dict = {
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
        }
        cred = credentials.Certificate(cred_dict)
    
    # Jika di Localhost dan ada file json
    elif os.path.exists('credentials.json'):
        cred = credentials.Certificate('credentials.json')

    if cred:
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred, {
                'databaseURL': os.environ.get('DATABASE_URL', 'https://website-ktvdi-default-rtdb.firebaseio.com/')
            })
        ref = db.reference('/')
        print("✅ Firebase Berhasil Terhubung!")
    else:
        print("⚠️ Warning: Firebase Credential tidak ditemukan. Cek Environment Variables Vercel.")
        ref = None

except Exception as e:
    print(f"❌ Firebase Error: {e}")
    ref = None

# Inisialisasi Email
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_USERNAME'] = 'kom.tvdigitalid@gmail.com'
app.config['MAIL_PASSWORD'] = 'lvjo uwrj sbiy ggkg'
app.config['MAIL_DEFAULT_SENDER'] = 'kom.tvdigitalid@gmail.com'

mail = Mail(app)

# Memuat API key dari variabel lingkungan
NEWS_API_KEY = os.getenv('NEWS_API_KEY')

# Menginisialisasi NewsApiClient (Perbaikan: Cek key dulu biar gak crash)
newsapi = None
if NEWS_API_KEY:
    try:
        newsapi = NewsApiClient(api_key=NEWS_API_KEY)
    except:
        pass

# Konfigurasi Gemini API Key
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Inisialisasi model Gemini (Perbaikan: Pakai 1.5-flash yang valid)
try:
    model = genai.GenerativeModel(
        "gemini-1.5-flash", 
        system_instruction=(
            "Anda adalah Chatbot AI KTVDI untuk website Komunitas TV Digital Indonesia (KTVDI). "
            "Tugas Anda adalah menjawab pertanyaan pengguna seputar aplikasi KTVDI, "
            "fungsi-fungsinya, serta pertanyaan umum tentang TV Digital di Indonesia (DVB-T2, MUX, mencari siaran, antena, STB). "
            "Jawab dengan ramah, informatif, dan ringkas."
        )
    )
except:
    model = None

# --- ROUTE ---

@app.route("/")
def home():
    # Ambil data dari Firebase (dengan safety check)
    siaran_data = {}
    if ref:
        siaran_data = ref.child('siaran').get() or {}

    # Variabel Statistik
    jumlah_wilayah_layanan = 0
    jumlah_siaran = 0
    jumlah_penyelenggara_mux = 0
    siaran_counts = Counter()
    last_updated_time = None
    
    # Data untuk Diagram (Chart)
    chart_provinsi_labels = []
    chart_provinsi_data = []

    # Iterasi data
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

    # Ambil Berita RSS (Logic Tambahan untuk Ticker)
    breaking_news = []
    try:
        feed = feedparser.parse('https://news.google.com/rss/search?q=tv+digital+indonesia&hl=id&gl=ID&ceid=ID:id')
        for entry in feed.entries[:8]:
            breaking_news.append(entry.title)
    except:
        pass
    if not breaking_news:
        breaking_news = ["Selamat Datang di KTVDI", "Update Frekuensi Terbaru"]

    return render_template('index.html', 
                           most_common_siaran_name=most_common_siaran_name,
                           most_common_siaran_count=most_common_siaran_count,
                           jumlah_wilayah_layanan=jumlah_wilayah_layanan,
                           jumlah_siaran=jumlah_siaran, 
                           jumlah_penyelenggara_mux=jumlah_penyelenggara_mux, 
                           last_updated_time=last_updated_time,
                           # Tambahan Data Chart & Berita untuk Ticker
                           chart_labels=json.dumps(chart_provinsi_labels),
                           chart_data=json.dumps(chart_provinsi_data),
                           breaking_news=breaking_news)

@app.route('/', methods=['POST'])
def chatbot():
    data = request.get_json()
    prompt = data.get("prompt")

    if not model:
        return jsonify({"error": "Offline Mode"}), 503

    try:
        response = model.generate_content(prompt)
        return jsonify({"response": response.text})
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "Quota" in error_msg:
            return jsonify({"error": "Quota Exceeded"}), 429
        return jsonify({"error": str(e)}), 500

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("identifier")
        
        if ref:
            users_ref = ref.child("users")
            users = users_ref.get() or {}
            found_uid, found_user = None, None
            for uid, user in users.items():
                if "email" in user and user["email"].lower() == email.lower():
                    found_uid, found_user = uid, user
                    break

            if found_uid:
                otp = str(random.randint(100000, 999999))
                ref.child(f"otp/{found_uid}").set({"email": email, "otp": otp})
                try:
                    username = found_uid
                    nama = found_user.get("nama", "")
                    msg = Message("Kode OTP Reset Password", recipients=[email])
                    msg.body = f"Halo {nama},\nKode OTP Anda: {otp}"
                    mail.send(msg)
                    flash("Kode OTP telah dikirim.", "success")
                    session["reset_uid"] = found_uid
                    return redirect(url_for("verify_otp"))
                except Exception as e:
                    flash(f"Gagal mengirim email: {str(e)}", "error")
            else:
                flash("Email tidak ditemukan!", "error")
        else:
            flash("Database Error", "error")

    return render_template("forgot-password.html")

@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    uid = session.get("reset_uid")
    if not uid: return redirect(url_for("forgot_password"))

    if request.method == "POST":
        otp_input = request.form.get("otp")
        otp_data = ref.child(f"otp/{uid}").get() if ref else None
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
        if ref:
            ref.child(f"users/{uid}").update({"password": hashed_pw})
            ref.child(f"otp/{uid}").delete()
        
        session.pop("reset_uid", None)
        flash("Password berhasil direset.", "success")
    return render_template("reset-password.html")

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
            users = ref.child("users").get() or {}
            for uid, user in users.items():
                if user.get("email", "").lower() == email.lower():
                    flash("Email sudah terdaftar!", "error")
                    return render_template("register.html")
            if username in users:
                flash("Username sudah dipakai!", "error")
                return render_template("register.html")

            hashed_pw = hashlib.sha256(password.encode()).hexdigest()
            otp = str(random.randint(100000, 999999))

            ref.child(f"pending_users/{username}").set({
                "nama": nama, "email": email, "password": hashed_pw, "otp": otp
            })

            try:
                msg = Message("Kode OTP Verifikasi", recipients=[email])
                msg.body = f"Kode OTP Anda: {otp}"
                mail.send(msg)
                session["pending_username"] = username
                flash("Kode OTP dikirim.", "success")
                return redirect(url_for("verify_register"))
            except Exception as e:
                flash(f"Gagal kirim email: {str(e)}", "error")

    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    username = session.get("pending_username")
    if not username: return redirect(url_for("register"))

    pending_data = ref.child(f"pending_users/{username}").get() if ref else None
    if not pending_data: return redirect(url_for("register"))

    if request.method == "POST":
        otp_input = request.form.get("otp")
        if pending_data.get("otp") == otp_input:
            ref.child(f"users/{username}").set({
                "nama": pending_data["nama"], "email": pending_data["email"],
                "password": pending_data["password"], "points": 0
            })
            ref.child(f"pending_users/{username}").delete()
            session.pop("pending_username", None)
            flash("Akun berhasil diverifikasi!", "success")
        else:
            flash("Kode OTP salah!", "error")
    return render_template("verify-register.html", username=username)

@app.route("/daftar-siaran")
def daftar_siaran():
    provinsi_list = []
    if ref:
        data = ref.child("provinsi").get() or {}
        provinsi_list = list(data.values())
    return render_template("daftar-siaran.html", provinsi_list=provinsi_list)

@app.route("/get_wilayah")
def get_wilayah():
    p = request.args.get("provinsi")
    d = ref.child(f"siaran/{p}").get() or {} if ref else {}
    return jsonify({"wilayah": list(d.keys())})

@app.route("/get_mux")
def get_mux():
    p = request.args.get("provinsi")
    w = request.args.get("wilayah")
    d = ref.child(f"siaran/{p}/{w}").get() or {} if ref else {}
    return jsonify({"mux": list(d.keys())})

@app.route("/get_siaran")
def get_siaran():
    p = request.args.get("provinsi")
    w = request.args.get("wilayah")
    m = request.args.get("mux")
    d = ref.child(f"siaran/{p}/{w}/{m}").get() or {} if ref else {}
    return jsonify(d)

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

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

@app.route('/login', methods=['GET', 'POST'])
def login():
    error_message = None
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()
        hashed_pw = hash_password(password)
        try:
            if ref:
                user_data = ref.child(f'users/{username}').get()
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

@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    nama = session.get('nama', 'Pengguna').replace('%20', ' ')
    data = ref.child("provinsi").get() or {} if ref else {}
    return render_template("dashboard.html", name=nama, provinsi_list=list(data.values()))

@app.route("/add_data", methods=["GET", "POST"])
def add_data():
    if 'user' not in session: return redirect(url_for('login'))
    data = ref.child("provinsi").get() or {} if ref else {}
    provinsi_list = list(data.values())

    if request.method == 'POST':
        p = request.form['provinsi']
        w = request.form['wilayah']
        m = request.form['mux']
        s = request.form['siaran'].split(',')
        w_clean = re.sub(r'\s*-\s*', '-', w.strip())
        m_clean = m.strip()
        
        try:
            tz = pytz.timezone('Asia/Jakarta')
            now_wib = datetime.now(tz)
            save_data = {
                "siaran": sorted([x.strip() for x in s]),
                "last_updated_by_username": session.get('user'),
                "last_updated_by_name": session.get('nama'),
                "last_updated_date": now_wib.strftime("%d-%m-%Y"),
                "last_updated_time": now_wib.strftime("%H:%M:%S WIB")
            }
            if ref:
                ref.child(f"siaran/{p}/{w_clean}/{m_clean}").set(save_data)
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
        s = request.form['siaran'].split(',')
        try:
            tz = pytz.timezone('Asia/Jakarta')
            now_wib = datetime.now(tz)
            update_data = {
                "siaran": sorted([x.strip() for x in s]),
                "last_updated_by_username": session.get('user'),
                "last_updated_by_name": session.get('nama'),
                "last_updated_date": now_wib.strftime("%d-%m-%Y"),
                "last_updated_time": now_wib.strftime("%H:%M:%S WIB")
            }
            w_clean = re.sub(r'\s*-\s*', '-', w.strip())
            if ref:
                ref.child(f"siaran/{p}/{w_clean}/{m.strip()}").update(update_data)
            return redirect(url_for('dashboard'))
        except Exception as e:
            return f"Gagal update: {e}"

    return render_template('edit_data_form.html', provinsi=p, wilayah=w, mux=m)

@app.route("/delete_data/<provinsi>/<wilayah>/<mux>", methods=["POST"])
def delete_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    try:
        if ref:
            ref.child(f"siaran/{provinsi}/{wilayah}/{mux}").delete()
        return redirect(url_for('dashboard'))
    except Exception as e:
        return f"Gagal hapus: {e}"

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

@app.route('/download-sql')
def download_sql():
    users_data = ref.child('users').get() if ref else {}
    if not users_data: return "No data", 404
    sql_queries = []
    for uname, udata in users_data.items():
        sql_queries.append(f"INSERT INTO users VALUES ('{uname}', '{udata['nama']}', '{udata['email']}', '{udata['password']}');")
    return send_file(io.BytesIO("\n".join(sql_queries).encode()), as_attachment=True, download_name="export_users.sql", mimetype="text/plain")

@app.route('/download-csv')
def download_csv():
    users_data = ref.child('users').get() if ref else {}
    if not users_data: return "No data", 404
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['username', 'nama', 'email', 'password'])
    for uname, udata in users_data.items():
        writer.writerow([uname, udata['nama'], udata['email'], udata['password']])
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode('utf-8')), as_attachment=True, download_name="export_users.csv", mimetype="text/csv")

@app.route("/test-firebase")
def test_firebase():
    try:
        data = ref.get() if ref else None
        return f"Connected! Data: {str(data)[:100]}..." if data else "Empty"
    except Exception as e:
        return f"Error: {e}"

@app.route('/sitemap.xml')
def sitemap():
    return send_file('static/sitemap.xml')

# --- TAMBAHAN ROUTE CCTV ---
@app.route('/cctv')
def cctv():
    return render_template('cctv.html')

if __name__ == "__main__":
    app.run(debug=True)
