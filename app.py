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

app.secret_key = os.environ.get('SECRET_KEY', 'b/g5n!o0?hs&dm!fn8md7')

# --- PERBAIKAN FATAL ERROR VERCEL (JANGAN DIHAPUS) ---
# Kode ini otomatis memilih cara koneksi terbaik (Env Var atau File)
ref = None
try:
    if not firebase_admin._apps:
        # Cek 1: Apakah ada Environment Variable di Vercel?
        firebase_creds_env = os.environ.get('FIREBASE_CREDENTIALS')
        
        if firebase_creds_env:
            # Jika ada, pakai ini (Cara Vercel)
            cred_dict = json.loads(firebase_creds_env)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred, {
                'databaseURL': 'https://website-ktvdi-default-rtdb.firebaseio.com/'
            })
            print("✅ Firebase Connected via ENV")
        else:
            # Cek 2: Cari file credentials.json (Cara Local)
            # Pakai path absolut biar tidak error 500
            BASE_DIR = os.path.dirname(os.path.abspath(__file__))
            CREDENTIALS_PATH = os.path.join(BASE_DIR, 'credentials.json')
            
            if os.path.exists(CREDENTIALS_PATH):
                cred = credentials.Certificate(CREDENTIALS_PATH)
                firebase_admin.initialize_app(cred, {
                    'databaseURL': 'https://website-ktvdi-default-rtdb.firebaseio.com/'
                })
                print("✅ Firebase Connected via File")
            else:
                print("⚠️ Warning: Tidak ada ENV maupun File Credentials. Masuk mode Offline.")

    # Cek koneksi db
    try:
        ref = db.reference('/')
    except:
        ref = None

except Exception as e:
    print(f"❌ Firebase Init Error: {e}")
    ref = None

# Inisialisasi Email
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_USERNAME'] = 'kom.tvdigitalid@gmail.com'
app.config['MAIL_PASSWORD'] = 'lvjo uwrj sbiy ggkg'
app.config['MAIL_DEFAULT_SENDER'] = 'kom.tvdigitalid@gmail.com'

try:
    mail = Mail(app)
except:
    mail = None

# API Keys (Pakai Error Handling biar gak Crash)
NEWS_API_KEY = os.getenv('NEWS_API_KEY')
try:
    newsapi = NewsApiClient(api_key=NEWS_API_KEY) if NEWS_API_KEY else None
except:
    newsapi = None

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
try:
    model = genai.GenerativeModel("gemini-2.5-flash", 
        system_instruction="Anda adalah Chatbot AI KTVDI. Jawab singkat dan ramah.")
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
    # Render halaman meskipun DB mati (data kosong)
    wilayah_count = 0
    mux_count = 0
    siaran_count = 0
    last_updated_time = None
    most_common_siaran_name = None
    most_common_siaran_count = 0
    
    if ref:
        try:
            siaran_data = ref.child('siaran').get() or {}
            siaran_counts = Counter()
            
            for prov_data in siaran_data.values():
                if isinstance(prov_data, dict):
                    wilayah_count += len(prov_data)
                    for wil_data in prov_data.values():
                        if isinstance(wil_data, dict):
                            mux_count += len(wil_data)
                            for mux_data in wil_data.values():
                                if 'siaran' in mux_data:
                                    siaran_count += len(mux_data['siaran'])
                                    for s in mux_data['siaran']:
                                        siaran_counts[s.lower()] += 1
                                
                                if 'last_updated_date' in mux_data:
                                    try:
                                        curr = datetime.strptime(mux_data['last_updated_date'], '%d-%m-%Y')
                                        if not last_updated_time or curr > last_updated_time:
                                            last_updated_time = curr
                                    except: pass
            
            if siaran_counts:
                top = siaran_counts.most_common(1)[0]
                most_common_siaran_name = top[0].upper()
                most_common_siaran_count = top[1]

            if last_updated_time:
                last_updated_time = last_updated_time.strftime('%d-%m-%Y')
        except:
            pass
    
    return render_template('index.html', 
                           most_common_siaran_name=most_common_siaran_name,
                           most_common_siaran_count=most_common_siaran_count,
                           jumlah_wilayah_layanan=wilayah_count,
                           jumlah_siaran=siaran_count, 
                           jumlah_penyelenggara_mux=mux_count, 
                           last_updated_time=last_updated_time)

@app.route('/', methods=['POST'])
def chatbot():
    data = request.get_json()
    prompt = data.get("prompt")
    try:
        if not model: return jsonify({"response": "Maaf, AI sedang istirahat."})
        response = model.generate_content(prompt)
        return jsonify({"response": response.text})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/cctv")
def cctv_page():
    return render_template("cctv.html")

# --- AUTH ROUTES ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    error_message = None
    if request.method == 'POST':
        if not ref: return render_template('login.html', error="Database Offline (Cek Config)")
        
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        hashed_pw = hash_password(password)
        
        try:
            user_data = ref.child(f'users/{username}').get()
            if not user_data:
                error_message = "Username tidak ditemukan."
            elif user_data.get('password') == hashed_pw:
                session['user'] = username
                session['nama'] = user_data.get('nama', 'Pengguna')
                return redirect(url_for('dashboard'))
            else:
                error_message = "Password salah."
        except Exception as e:
            error_message = f"Error: {e}"
            
    return render_template('login.html', error=error_message)

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        if not ref: 
            flash("Database Offline.", "error")
            return render_template("register.html")

        nama = request.form.get("nama")
        email = request.form.get("email")
        username = request.form.get("username")
        password = request.form.get("password")

        # Basic validation
        if len(password) < 8:
            flash("Password minimal 8 karakter.", "error")
            return render_template("register.html")

        try:
            users = ref.child('users').get() or {}
            if username in users:
                flash("Username sudah digunakan.", "error")
                return render_template("register.html")
            
            for u in users.values():
                if u.get('email') == email:
                    flash("Email sudah terdaftar.", "error")
                    return render_template("register.html")

            hashed_pw = hash_password(password)
            otp = str(random.randint(100000, 999999))
            
            ref.child(f'pending_users/{username}').set({
                "nama": nama, "email": email, "password": hashed_pw, "otp": otp
            })

            if mail:
                msg = Message("Kode Verifikasi KTVDI", recipients=[email])
                msg.body = f"Halo {nama},\nKode OTP Anda: {otp}"
                mail.send(msg)
                flash("Kode OTP telah dikirim ke email.", "success")
                session['pending_username'] = username
                return redirect(url_for('verify_register'))
            else:
                flash("Gagal inisialisasi Email Server.", "error")

        except Exception as e:
            flash(f"Error: {e}", "error")

    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    username = session.get('pending_username')
    if not username: return redirect(url_for('register'))

    if request.method == "POST":
        if not ref: 
            flash("Database Error", "error")
            return render_template("verify-register.html", username=username)

        otp_input = request.form.get("otp")
        pending_data = ref.child(f'pending_users/{username}').get()
        
        if pending_data and str(pending_data['otp']) == str(otp_input):
            ref.child(f'users/{username}').set({
                "nama": pending_data['nama'],
                "email": pending_data['email'],
                "password": pending_data['password'],
                "points": 0
            })
            ref.child(f'pending_users/{username}').delete()
            session.pop('pending_username', None)
            flash("Pendaftaran berhasil! Silakan login.", "success")
            return redirect(url_for('login'))
        else:
            flash("Kode OTP salah.", "error")

    return render_template("verify-register.html", username=username)

# --- FORGOT PASSWORD ---

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        if not ref: 
            flash("Database Error", "error")
            return render_template("forgot-password.html")

        email = request.form.get("identifier")
        users = ref.child('users').get() or {}
        found_uid = None
        
        for uid, u in users.items():
            if u.get('email') == email:
                found_uid = uid
                break
        
        if found_uid:
            otp = str(random.randint(100000, 999999))
            ref.child(f'otp/{found_uid}').set({"email": email, "otp": otp})
            
            if mail:
                try:
                    msg = Message("Reset Password KTVDI", recipients=[email])
                    msg.body = f"Kode OTP Reset: {otp}"
                    mail.send(msg)
                    session['reset_uid'] = found_uid
                    flash(f"OTP dikirim ke {email}", "success")
                    return redirect(url_for('verify_otp'))
                except Exception as e:
                    flash(f"Gagal kirim email: {e}", "error")
            else:
                flash("Email service error", "error")
        else:
            flash("Email tidak ditemukan.", "error")
            
    return render_template("forgot-password.html")

@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    uid = session.get('reset_uid')
    if not uid: return redirect(url_for('forgot_password'))
    
    if request.method == "POST":
        if not ref: return "DB Error", 500
        otp_input = request.form.get("otp")
        stored_otp = ref.child(f'otp/{uid}').get()
        
        if stored_otp and str(stored_otp['otp']) == str(otp_input):
            return redirect(url_for('reset_password'))
        else:
            flash("OTP Salah.", "error")
            
    return render_template("verify-otp.html")

@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    uid = session.get('reset_uid')
    if not uid: return redirect(url_for('forgot_password'))
    
    if request.method == "POST":
        if not ref: return "DB Error", 500
        pw = request.form.get("password")
        if len(pw) < 8:
            flash("Password minimal 8 karakter.", "error")
            return render_template("reset-password.html")

        ref.child(f'users/{uid}').update({"password": hash_password(pw)})
        ref.child(f'otp/{uid}').delete()
        session.pop('reset_uid', None)
        flash("Password berhasil diubah.", "success")
        return redirect(url_for('login'))
        
    return render_template("reset-password.html")

# --- DASHBOARD & CRUD ---

@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    prov_data = {}
    if ref: prov_data = ref.child('provinsi').get() or {}
    return render_template("dashboard.html", name=session.get('nama'), provinsi_list=list(prov_data.values()))

@app.route("/daftar-siaran")
def daftar_siaran():
    prov_data = {}
    if ref: prov_data = ref.child('provinsi').get() or {}
    return render_template("daftar-siaran.html", provinsi_list=list(prov_data.values()))

@app.route("/add_data", methods=["GET", "POST"])
def add_data():
    if 'user' not in session: return redirect(url_for('login'))
    prov_list = []
    if ref: prov_list = list((ref.child('provinsi').get() or {}).values())
    
    if request.method == 'POST':
        if not ref: return "Database Error", 500
        prov = request.form['provinsi']
        wil = request.form['wilayah']
        mux = request.form['mux']
        siaran = [s.strip() for s in request.form['siaran'].split(',') if s.strip()]
        
        wil_clean = re.sub(r'\s*-\s*', '-', wil.strip())
        mux_clean = mux.strip()
        
        if not all([prov, wil_clean, mux_clean, siaran]):
            return render_template('add_data_form.html', error_message="Isi semua data", provinsi_list=prov_list)
            
        data = {
            "siaran": sorted(siaran),
            "last_updated_by": session.get('user'),
            "last_updated_by_name": session.get('nama'),
            "last_updated_date": datetime.now().strftime("%d-%m-%Y"),
            "last_updated_time": datetime.now().strftime("%H:%M:%S WIB")
        }
        ref.child(f'siaran/{prov}/{wil_clean}/{mux_clean}').set(data)
        return redirect(url_for('dashboard'))
        
    return render_template('add_data_form.html', provinsi_list=prov_list)

@app.route("/edit_data/<provinsi>/<wilayah>/<mux>", methods=["GET", "POST"])
def edit_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    if not ref: return "Database Error", 500

    provinsi = provinsi.replace('%20',' ')
    wilayah = wilayah.replace('%20', ' ')
    mux = mux.replace('%20', ' ')

    if request.method == 'POST':
        siaran_list = [s.strip() for s in request.form['siaran'].split(',') if s.strip()]
        try:
            db.reference(f"siaran/{provinsi}/{wilayah}/{mux}").update({
                "siaran": sorted(siaran_list),
                "last_updated_by_username": session.get('user'),
                "last_updated_by_name": session.get('nama'),
                "last_updated_date": datetime.now().strftime("%d-%m-%Y"),
                "last_updated_time": datetime.now().strftime("%H:%M:%S WIB")
            })
            return redirect(url_for('dashboard'))
        except Exception as e:
            return f"Gagal: {e}"
    return render_template('edit_data_form.html', provinsi=provinsi, wilayah=wilayah, mux=mux)

@app.route("/delete_data/<provinsi>/<wilayah>/<mux>", methods=["POST"])
def delete_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    if not ref: return "Database Error", 500
    try:
        db.reference(f"siaran/{provinsi}/{wilayah}/{mux}").delete()
        return redirect(url_for('dashboard'))
    except Exception as e:
        return f"Gagal hapus: {e}"

@app.route('/download-sql')
def download_sql():
    if not ref: return "DB Error", 500
    users_data = db.reference('users').get() or {}
    sql = "\n".join([f"INSERT INTO users VALUES ('{u}', '{d['nama']}', '{d['email']}', '{d['password']}');" for u, d in users.items()])
    return send_file(io.BytesIO(sql.encode()), as_attachment=True, download_name="users.sql", mimetype="text/plain")

@app.route('/download-csv')
def download_csv():
    if not ref: return "DB Error", 500
    users_data = db.reference('users').get() or {}
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['username', 'nama', 'email', 'password'])
    for u, d in users_data.items(): writer.writerow([u, d['nama'], d['email'], d['password']])
    return send_file(io.BytesIO(output.getvalue().encode('utf-8')), as_attachment=True, download_name="users.csv", mimetype="text/csv")

@app.route("/test-firebase")
def test_firebase():
    if ref: return "✅ Firebase Connected (Vercel Mode)"
    return "❌ Firebase Error"

# API Helpers
@app.route("/get_wilayah")
def get_wilayah():
    if not ref: return jsonify({"wilayah": []})
    p = request.args.get("provinsi")
    d = ref.child(f'siaran/{p}').get() or {}
    return jsonify({"wilayah": list(d.keys())})

@app.route("/get_mux")
def get_mux():
    if not ref: return jsonify({"mux": []})
    p = request.args.get("provinsi")
    w = request.args.get("wilayah")
    d = ref.child(f'siaran/{p}/{w}').get() or {}
    return jsonify({"mux": list(d.keys())})

@app.route("/get_siaran")
def get_siaran():
    if not ref: return jsonify({})
    p = request.args.get("provinsi")
    w = request.args.get("wilayah")
    m = request.args.get("mux")
    d = ref.child(f'siaran/{p}/{w}/{m}').get() or {}
    return jsonify(d)

if __name__ == "__main__":
    app.run(debug=True)
