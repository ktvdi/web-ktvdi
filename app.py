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

# Secret Key (Gunakan env var di Vercel agar session aman)
app.secret_key = os.environ.get("SECRET_KEY", 'b/g5n!o0?hs&dm!fn8md7')

# --- 1. KONEKSI FIREBASE (FIXED FOR VERCEL) ---
# Menggunakan Environment Variable agar tidak crash mencari file json
ref = None
try:
    cred = None
    # Cek apakah ada private key di Environment Vercel
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
    # Jika di Localhost dan ada file json
    elif os.path.exists('credentials.json'):
        cred = credentials.Certificate('credentials.json')

    if cred:
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred, {
                'databaseURL': os.environ.get('DATABASE_URL', 'https://website-ktvdi-default-rtdb.firebaseio.com/')
            })
        ref = db.reference('/')
        print("✅ Firebase Connected!")
    else:
        print("⚠️ Warning: Firebase Credential Missing")

except Exception as e:
    print(f"❌ Firebase Error: {e}")

# --- 2. CONFIG EMAIL ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_USERNAME'] = 'kom.tvdigitalid@gmail.com'
app.config['MAIL_PASSWORD'] = 'lvjo uwrj sbiy ggkg' 
app.config['MAIL_DEFAULT_SENDER'] = 'kom.tvdigitalid@gmail.com'
mail = Mail(app)

# --- 3. CONFIG API ---
NEWS_API_KEY = os.getenv('NEWS_API_KEY')
newsapi = None
if NEWS_API_KEY:
    try: newsapi = NewsApiClient(api_key=NEWS_API_KEY)
    except: pass

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
try:
    model = genai.GenerativeModel("gemini-1.5-flash", 
        system_instruction="Anda adalah Asisten KTVDI. Jawab singkat dan ramah seputar TV Digital.")
except:
    model = None

# --- PENTING: INJECT VARIABLE KE BASE.HTML ---
# Ini mencegah error di base.html saat membuka halaman selain Home
@app.context_processor
def inject_global_vars():
    news_list = []
    try:
        rss_url = 'https://news.google.com/rss/search?q=tv+digital+indonesia+kominfo&hl=id&gl=ID&ceid=ID:id'
        feed = feedparser.parse(rss_url)
        for entry in feed.entries[:7]:
            news_list.append(entry.title)
    except: pass
    
    if not news_list:
        news_list = ["Selamat Datang di KTVDI", "Update Frekuensi TV Digital Terbaru", "Pastikan STB Bersertifikat"]
        
    return dict(breaking_news=news_list)

# --- ROUTES ---

@app.route("/")
def home():
    siaran_data = {}
    if ref: siaran_data = ref.child('siaran').get() or {}
    
    # Statistik
    jumlah_wilayah_layanan = 0
    jumlah_siaran = 0
    jumlah_penyelenggara_mux = 0 
    siaran_counts = Counter()
    last_updated_time = None 
    chart_provinsi_labels = []
    chart_provinsi_data = []

    for provinsi, provinsi_data in siaran_data.items():
        if isinstance(provinsi_data, dict):
            jumlah_wilayah_provinsi = len(provinsi_data)
            chart_provinsi_labels.append(provinsi)
            chart_provinsi_data.append(jumlah_wilayah_provinsi)
            jumlah_wilayah_layanan += jumlah_wilayah_provinsi

            for wilayah, wilayah_data in provinsi_data.items():
                if isinstance(wilayah_data, dict):
                    jumlah_penyelenggara_mux += len(wilayah_data)
                    for penyelenggara, details in wilayah_data.items():
                        if 'siaran' in details:
                            jumlah_siaran += len(details['siaran'])
                            for s in details['siaran']: siaran_counts[s.lower()] += 1
                        if 'last_updated_date' in details:
                            try:
                                cur_time = datetime.strptime(details['last_updated_date'], '%d-%m-%Y')
                                if not last_updated_time or cur_time > last_updated_time:
                                    last_updated_time = cur_time
                            except: pass

    most_common = siaran_counts.most_common(1)[0] if siaran_counts else ("-", 0)
    last_update_str = last_updated_time.strftime('%d-%m-%Y') if last_updated_time else "-"

    return render_template('index.html', 
                           most_common_siaran_name=most_common[0].upper(),
                           most_common_siaran_count=most_common[1],
                           jumlah_wilayah_layanan=jumlah_wilayah_layanan,
                           jumlah_siaran=jumlah_siaran, 
                           jumlah_penyelenggara_mux=jumlah_penyelenggara_mux, 
                           last_updated_time=last_update_str,
                           chart_labels=json.dumps(chart_provinsi_labels),
                           chart_data=json.dumps(chart_provinsi_data))

@app.route('/', methods=['POST'])
def chatbot():
    data = request.get_json()
    if not model: return jsonify({"error": "Offline Mode"}), 503
    try:
        res = model.generate_content(data.get("prompt"))
        return jsonify({"response": res.text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- ROUTES LAIN ---

@app.route('/about')
def about(): return render_template('about.html')

@app.route("/daftar-siaran")
def daftar_siaran():
    data = ref.child("provinsi").get() if ref else {}
    return render_template("daftar-siaran.html", provinsi_list=list((data or {}).values()))

@app.route("/get_wilayah")
def get_wilayah():
    p = request.args.get("provinsi")
    d = ref.child(f"siaran/{p}").get() if ref else {}
    return jsonify({"wilayah": list((d or {}).keys())})

@app.route("/get_mux")
def get_mux():
    p = request.args.get("provinsi")
    w = request.args.get("wilayah")
    d = ref.child(f"siaran/{p}/{w}").get() if ref else {}
    return jsonify({"mux": list((d or {}).keys())})

@app.route("/get_siaran")
def get_siaran():
    p = request.args.get("provinsi")
    w = request.args.get("wilayah")
    m = request.args.get("mux")
    d = ref.child(f"siaran/{p}/{w}/{m}").get() if ref else {}
    return jsonify(d or {"siaran": []})

@app.route('/berita')
def berita():
    try:
        feed = feedparser.parse('https://news.google.com/rss/search?q=tv+digital+indonesia&hl=id&gl=ID&ceid=ID:id')
        articles = feed.entries
    except: articles = []
    page = request.args.get('page', 1, type=int)
    start = (page-1)*5
    return render_template('berita.html', articles=articles[start:start+5], page=page, total_pages=(len(articles)+4)//5)

def hash_password(pw): return hashlib.sha256(pw.encode()).hexdigest()

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form['username'].strip()
        p = request.form['password'].strip()
        if ref:
            user = ref.child(f'users/{u}').get()
            if user and user.get('password') == hash_password(p):
                session['user'] = u; session['nama'] = user.get('nama')
                return redirect(url_for('dashboard'))
        return render_template('login.html', error="Gagal Login")
    return render_template('login.html')

@app.route('/logout')
def logout(): session.pop('user', None); return redirect(url_for('login'))

@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    data = ref.child("provinsi").get() if ref else {}
    return render_template("dashboard.html", name=session.get('nama'), provinsi_list=list((data or {}).values()))

@app.route("/add_data", methods=["GET", "POST"])
def add_data():
    if 'user' not in session: return redirect(url_for('login'))
    data = ref.child("provinsi").get() if ref else {}
    if request.method == 'POST':
        p=request.form['provinsi']; w=request.form['wilayah']; m=request.form['mux']; s=request.form['siaran'].split(',')
        w_cl = re.sub(r'\s*-\s*', '-', w.strip())
        if ref:
            ref.child(f"siaran/{p}/{w_cl}/{m.strip()}").set({
                "siaran": [x.strip() for x in s],
                "last_updated_by_username": session['user'],
                "last_updated_by_name": session['nama'],
                "last_updated_date": datetime.now(pytz.timezone('Asia/Jakarta')).strftime("%d-%m-%Y"),
                "last_updated_time": datetime.now(pytz.timezone('Asia/Jakarta')).strftime("%H:%M:%S WIB")
            })
        return redirect(url_for('dashboard'))
    return render_template('add_data_form.html', provinsi_list=list((data or {}).values()))

@app.route("/edit_data/<provinsi>/<wilayah>/<mux>", methods=["GET", "POST"])
def edit_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        s = request.form['siaran'].split(',')
        w_cl = re.sub(r'\s*-\s*', '-', wilayah.strip())
        if ref:
            ref.child(f"siaran/{provinsi}/{w_cl}/{mux}").update({
                "siaran": sorted([x.strip() for x in s]),
                "last_updated_by_name": session['nama'],
                "last_updated_date": datetime.now(pytz.timezone('Asia/Jakarta')).strftime("%d-%m-%Y"),
                "last_updated_time": datetime.now(pytz.timezone('Asia/Jakarta')).strftime("%H:%M:%S WIB")
            })
        return redirect(url_for('dashboard'))
    return render_template('edit_data_form.html', provinsi=provinsi, wilayah=wilayah, mux=mux)

@app.route("/delete_data/<provinsi>/<wilayah>/<mux>", methods=["POST"])
def delete_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    if ref: ref.child(f"siaran/{provinsi}/{wilayah}/{mux}").delete()
    return redirect(url_for('dashboard'))

# Route Register & Forgot Pass
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        u=request.form['username']; e=request.form['email']; p=request.form['password']; n=request.form['nama']
        if ref:
            otp = str(random.randint(100000, 999999))
            ref.child(f"pending_users/{u}").set({"nama":n, "email":e, "password":hash_password(p), "otp":otp})
            # mail.send(...) # Uncomment di prod
            session["pending_username"] = u
            return redirect(url_for("verify_register"))
    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    u = session.get("pending_username")
    if request.method == "POST":
        if ref and ref.child(f"pending_users/{u}/otp").get() == request.form['otp']:
            d = ref.child(f"pending_users/{u}").get()
            ref.child(f"users/{u}").set({"nama":d['nama'], "email":d['email'], "password":d['password'], "points":0})
            ref.child(f"pending_users/{u}").delete()
            return redirect(url_for("login"))
    return render_template("verify-register.html")

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password(): return render_template("forgot-password.html")
@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp(): return render_template("verify-otp.html")
@app.route("/reset-password", methods=["GET", "POST"])
def reset_password(): return render_template("reset-password.html")

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
def sitemap(): return send_file('static/sitemap.xml')

if __name__ == "__main__":
    app.run(debug=True)
