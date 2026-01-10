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
import json
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

app.secret_key = 'b/g5n!o0?hs&dm!fn8md7'

# --- PERBAIKAN KHUSUS VERCEL (JANGAN DIUBAH LAGI) ---
# Kita harus mencari letak file ini secara absolut agar terbaca oleh Vercel
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_PATH = os.path.join(BASE_DIR, 'credentials.json')

# Inisialisasi Firebase
if not firebase_admin._apps:
    try:
        # Gunakan path absolut yang sudah kita buat di atas
        cred = credentials.Certificate(CREDENTIALS_PATH)
        firebase_admin.initialize_app(cred, {
            'databaseURL': 'https://website-ktvdi-default-rtdb.firebaseio.com/'
        })
    except FileNotFoundError:
        print(f"CRITICAL ERROR: File tidak ditemukan di {CREDENTIALS_PATH}")
        # Jangan crash, biar log errornya kelihatan di Vercel
    except Exception as e:
        print(f"Firebase Error: {e}")

# Referensi ke Realtime Database
try:
    ref = db.reference('/')
except:
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

# Menginisialisasi NewsApiClient dengan API key
try:
    newsapi = NewsApiClient(api_key=NEWS_API_KEY)
except:
    newsapi = None

# Konfigurasi Gemini API Key
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Inisialisasi model Gemini
try:
    model = genai.GenerativeModel(
        "gemini-2.5-flash", 
        system_instruction="Anda adalah Chatbot AI KTVDI. Jawab singkat dan ramah seputar TV Digital."
    )
except:
    model = None

# --- FUNGSI HELPER ---
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
    except:
        return "Baru saja"

def get_actual_url_from_google_news(link):
    try:
        response = requests.get(link, timeout=3)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            article_link = soup.find('a', {'class': 'DY5T1d'})
            return article_link['href'] if article_link else link
    except:
        pass
    return link

# --- ROUTES ---

@app.route("/")
def home():
    if not ref:
        return "<h1>Error: Database Tidak Terhubung</h1><p>Pastikan file <b>credentials.json</b> sudah di-upload ke GitHub dengan perintah <code>git add -f credentials.json</code>.</p>", 500

    try:
        siaran_data = ref.child('siaran').get() or {}
    except:
        siaran_data = {}

    jumlah_wilayah_layanan = 0
    jumlah_siaran = 0
    jumlah_penyelenggara_mux = 0
    siaran_counts = Counter()
    last_updated_time = None
    
    for prov_data in siaran_data.values():
        if isinstance(prov_data, dict):
            jumlah_wilayah_layanan += len(prov_data)
            for wil_data in prov_data.values():
                if isinstance(wil_data, dict):
                    jumlah_penyelenggara_mux += len(wil_data)
                    for mux_data in wil_data.values():
                        if 'siaran' in mux_data:
                            jumlah_siaran += len(mux_data['siaran'])
                            for s in mux_data['siaran']:
                                siaran_counts[s.lower()] += 1
                        
                        if 'last_updated_date' in mux_data:
                            try:
                                curr = datetime.strptime(mux_data['last_updated_date'], '%d-%m-%Y')
                                if not last_updated_time or curr > last_updated_time:
                                    last_updated_time = curr
                            except: pass

    most_common_siaran_name = None
    most_common_siaran_count = 0
    if siaran_counts:
        top = siaran_counts.most_common(1)[0]
        most_common_siaran_name = top[0].upper()
        most_common_siaran_count = top[1]

    if last_updated_time:
        last_updated_time = last_updated_time.strftime('%d-%m-%Y')
    
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

@app.route("/cctv")
def cctv_page():
    return render_template("cctv.html")

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        if not ref: return "Database Error", 500
        email = request.form.get("identifier")
        users = ref.child('users').get() or {}
        found_uid = None
        for uid, u in users.items():
            if u.get('email') == email: found_uid = uid; break
        
        if found_uid:
            otp = str(random.randint(100000, 999999))
            ref.child(f'otp/{found_uid}').set({"email": email, "otp": otp})
            try:
                msg = Message("Kode OTP Reset Password", recipients=[email])
                msg.body = f"Kode OTP: {otp}"
                mail.send(msg)
                flash(f"Kode OTP terkirim ke {email}", "success")
                session["reset_uid"] = found_uid
                return redirect(url_for("verify_otp"))
            except Exception as e:
                flash(f"Gagal kirim email: {e}", "error")
        else:
            flash("Email tidak ditemukan!", "error")
    return render_template("forgot-password.html")

@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    uid = session.get("reset_uid")
    if not uid: return redirect(url_for("forgot_password"))
    if request.method == "POST":
        otp_input = request.form.get("otp")
        otp_data = ref.child(f"otp/{uid}").get()
        if otp_data and str(otp_data["otp"]) == str(otp_input):
            return redirect(url_for("reset_password"))
        else:
            flash("OTP salah.", "error")
    return render_template("verify-otp.html")

@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    uid = session.get("reset_uid")
    if not uid: return redirect(url_for("forgot_password"))
    if request.method == "POST":
        pw = request.form.get("password")
        ref.child(f"users/{uid}").update({"password": hash_password(pw)})
        ref.child(f"otp/{uid}").delete()
        session.pop("reset_uid", None)
        flash("Password berhasil diubah.", "success")
        return redirect(url_for("login"))
    return render_template("reset-password.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        if not ref: return "Database Error", 500
        nama = request.form.get("nama")
        email = request.form.get("email")
        username = request.form.get("username")
        password = request.form.get("password")

        users = ref.child('users').get() or {}
        if username in users:
            flash("Username sudah dipakai", "error")
            return render_template("register.html")

        hashed_pw = hash_password(password)
        otp = str(random.randint(100000, 999999))
        
        ref.child(f"pending_users/{username}").set({
            "nama": nama, "email": email, "password": hashed_pw, "otp": otp
        })

        try:
            msg = Message("Kode Verifikasi KTVDI", recipients=[email])
            msg.body = f"Kode OTP: {otp}"
            mail.send(msg)
            session["pending_username"] = username
            return redirect(url_for("verify_register"))
        except:
            flash("Gagal kirim email", "error")

    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    username = session.get("pending_username")
    if not username: return redirect(url_for("register"))
    if request.method == "POST":
        otp = request.form.get("otp")
        pending = ref.child(f"pending_users/{username}").get()
        if pending and str(pending['otp']) == str(otp):
            ref.child(f"users/{username}").set({
                "nama": pending['nama'], "email": pending['email'],
                "password": pending['password'], "points": 0
            })
            ref.child(f"pending_users/{username}").delete()
            session.pop("pending_username", None)
            flash("Berhasil! Silakan Login", "success")
            return redirect(url_for("login"))
        flash("OTP Salah", "error")
    return render_template("verify-register.html", username=username)

@app.route("/daftar-siaran")
def daftar_siaran():
    ref_prov = db.reference("provinsi")
    data = ref_prov.get() or {}
    return render_template("daftar-siaran.html", provinsi_list=list(data.values()))

@app.route("/get_wilayah")
def get_wilayah():
    p = request.args.get("provinsi")
    d = ref.child(f"siaran/{p}").get() or {}
    return jsonify({"wilayah": list(d.keys())})

@app.route("/get_mux")
def get_mux():
    p = request.args.get("provinsi")
    w = request.args.get("wilayah")
    d = ref.child(f"siaran/{p}/{w}").get() or {}
    return jsonify({"mux": list(d.keys())})

@app.route("/get_siaran")
def get_siaran():
    p = request.args.get("provinsi")
    w = request.args.get("wilayah")
    m = request.args.get("mux")
    d = ref.child(f"siaran/{p}/{w}/{m}").get() or {}
    return jsonify(d)

@app.route('/berita')
def berita():
    try:
        rss = 'https://news.google.com/rss/search?q=tv+digital&hl=id&gl=ID&ceid=ID:id'
        feed = feedparser.parse(rss)
        return render_template('berita.html', articles=feed.entries[:10], page=1, total_pages=1)
    except:
        return render_template('berita.html', articles=[], page=1, total_pages=1)

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if not ref: return "Database Error", 500
        username = request.form.get('username')
        password = request.form.get('password')
        hashed = hash_password(password)
        user = ref.child(f'users/{username}').get()
        if user and user.get('password') == hashed:
            session['user'] = username
            session['nama'] = user.get('nama')
            return redirect(url_for('dashboard'))
        return render_template('login.html', error="Login Gagal")
    return render_template('login.html')

@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    prov = ref.child('provinsi').get() or {}
    return render_template("dashboard.html", name=session.get('nama'), provinsi_list=list(prov.values()))

@app.route("/add_data", methods=["GET", "POST"])
def add_data():
    if 'user' not in session: return redirect(url_for('login'))
    provs = list((ref.child('provinsi').get() or {}).values())
    if request.method == 'POST':
        prov = request.form['provinsi']
        wil = request.form['wilayah']
        mux = request.form['mux']
        siaran = [s.strip() for s in request.form['siaran'].split(',') if s.strip()]
        
        wil_clean = re.sub(r'\s*-\s*', '-', wil.strip())
        mux_clean = mux.strip()
        
        if all([prov, wil_clean, mux_clean, siaran]):
            data = {
                "siaran": sorted(siaran),
                "last_updated_by": session.get('user'),
                "last_updated_date": datetime.now().strftime("%d-%m-%Y")
            }
            ref.child(f'siaran/{prov}/{wil_clean}/{mux_clean}').set(data)
            return redirect(url_for('dashboard'))
    return render_template('add_data_form.html', provinsi_list=provs)

@app.route("/edit_data/<provinsi>/<wilayah>/<mux>", methods=["GET", "POST"])
def edit_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    prov = provinsi.replace('%20',' ')
    wil = wilayah.replace('%20',' ')
    mx = mux.replace('%20',' ')
    
    if request.method == 'POST':
        siaran = [s.strip() for s in request.form['siaran'].split(',') if s.strip()]
        ref.child(f'siaran/{prov}/{wil}/{mx}').update({
            "siaran": sorted(siaran),
            "last_updated_by": session.get('user'),
            "last_updated_date": datetime.now().strftime("%d-%m-%Y")
        })
        return redirect(url_for('dashboard'))
    return render_template('edit_data_form.html', provinsi=prov, wilayah=wil, mux=mx)

@app.route("/delete_data/<provinsi>/<wilayah>/<mux>", methods=["POST"])
def delete_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    ref.child(f'siaran/{provinsi}/{wilayah}/{mux}').delete()
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

@app.route('/download-sql')
def download_sql():
    users = ref.child('users').get() or {}
    sql = "\n".join([f"INSERT INTO users VALUES ('{u}', '{d['nama']}', '{d['email']}', '{d['password']}');" for u, d in users.items()])
    return send_file(io.BytesIO(sql.encode()), as_attachment=True, download_name="users.sql", mimetype="text/plain")

@app.route('/download-csv')
def download_csv():
    users = ref.child('users').get() or {}
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['username', 'nama', 'email', 'password'])
    for u, d in users.items(): writer.writerow([u, d['nama'], d['email'], d['password']])
    return send_file(io.BytesIO(output.getvalue().encode('utf-8')), as_attachment=True, download_name="users.csv", mimetype="text/csv")

@app.route("/test-firebase")
def test_firebase():
    if ref: return "✅ Firebase Connected (Vercel Mode)"
    return "❌ Firebase Error"

if __name__ == "__main__":
    app.run(debug=True)
