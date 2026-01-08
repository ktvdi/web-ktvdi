import os
import hashlib
import random
import re
import time
import json
import io
import csv
from datetime import datetime
from collections import Counter

# Import Library dengan Safety Check
try:
    import firebase_admin
    from firebase_admin import credentials, db
    from flask import Flask, request, render_template, redirect, url_for, session, flash, jsonify, send_file
    from flask_cors import CORS
    from flask_mail import Mail, Message
    from dotenv import load_dotenv
    import requests
    import feedparser
    import google.generativeai as genai
    from newsapi import NewsApiClient
    import pytz
except ImportError as e:
    print(f"CRITICAL: Library Missing - {e}")

# --- KONFIGURASI ---
load_dotenv()
app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("SECRET_KEY", "b/g5n!o0?hs&dm!fn8md7")

# --- 1. FIREBASE CONNECTION ---
ref = None
try:
    cred = None
    # Cek Env Vercel
    if os.environ.get("FIREBASE_PRIVATE_KEY"):
        pk = os.environ.get("FIREBASE_PRIVATE_KEY").replace('\\n', '\n').replace('"', '')
        cred = credentials.Certificate({
            "type": "service_account",
            "project_id": os.environ.get("FIREBASE_PROJECT_ID"),
            "private_key_id": os.environ.get("FIREBASE_PRIVATE_KEY_ID"),
            "private_key": pk,
            "client_email": os.environ.get("FIREBASE_CLIENT_EMAIL"),
            "client_id": os.environ.get("FIREBASE_CLIENT_ID"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": os.environ.get("FIREBASE_CLIENT_X509_CERT_URL"),
            "universe_domain": "googleapis.com"
        })
    # Cek Localhost
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
        print("⚠️ Warning: Firebase Credentials Missing")
except Exception as e:
    print(f"❌ Firebase Error: {e}")

# --- 2. EMAIL ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_USERNAME'] = 'kom.tvdigitalid@gmail.com'
app.config['MAIL_PASSWORD'] = 'lvjo uwrj sbiy ggkg'
app.config['MAIL_DEFAULT_SENDER'] = 'kom.tvdigitalid@gmail.com'
mail = Mail(app)

# --- 3. API SETUP ---
NEWS_API_KEY = os.getenv('NEWS_API_KEY')
newsapi = NewsApiClient(api_key=NEWS_API_KEY) if NEWS_API_KEY else None

genai.configure(api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_APP_KEY"))
model = None
try:
    model = genai.GenerativeModel("gemini-1.5-flash", 
        system_instruction="Anda adalah Asisten KTVDI. Jawab singkat seputar TV Digital, STB, dan Bola.")
except: pass

# --- GLOBAL CONTEXT (BERITA UNTUK SEMUA HALAMAN) ---
@app.context_processor
def inject_global_vars():
    news_list = []
    try:
        # RSS CNN Nasional
        rss_url = 'https://www.cnnindonesia.com/nasional/rss'
        feed = feedparser.parse(rss_url)
        for entry in feed.entries[:8]:
            news_list.append(entry.title)
    except: pass
    
    if not news_list:
        news_list = ["Selamat Datang di KTVDI", "Update Frekuensi TV Digital Terbaru", "KTVDI Siap Menyambut Piala Dunia 2026"]
    
    return dict(breaking_news=news_list)

# --- ROUTES ---

@app.route("/")
def home():
    siaran_data = {}
    if ref: 
        try: siaran_data = ref.child('siaran').get() or {}
        except: pass
    
    stats = {"wilayah": 0, "mux": 0, "channel": 0}
    chart_labels = []
    chart_data = []

    for provinsi, p_data in siaran_data.items():
        if isinstance(p_data, dict):
            w_count = len(p_data)
            stats["wilayah"] += w_count
            chart_labels.append(provinsi)
            chart_data.append(w_count)
            for wilayah, w_data in p_data.items():
                if isinstance(w_data, dict):
                    stats["mux"] += len(w_data)
                    for mux, m_data in w_data.items():
                        if 'siaran' in m_data:
                            stats["channel"] += len(m_data['siaran'])

    return render_template('index.html', 
                           stats=stats,
                           chart_labels=json.dumps(chart_labels),
                           chart_data=json.dumps(chart_data))

@app.route('/cctv')
def cctv():
    return render_template('cctv.html')

@app.route('/chatbot', methods=['POST'])
def chatbot_api():
    data = request.get_json()
    if not model: return jsonify({"error": "Offline Mode"}), 503
    try:
        res = model.generate_content(data.get("prompt"))
        return jsonify({"response": res.text})
    except: return jsonify({"error": "Busy"}), 500

@app.route('/', methods=['POST'])
def chatbot_legacy(): return chatbot_api()

# --- AUTH & CRUD ---

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
        feed = feedparser.parse('https://www.cnnindonesia.com/teknologi/rss')
        articles = feed.entries
    except: articles = []
    page = request.args.get('page', 1, type=int)
    start = (page-1)*6
    return render_template('berita.html', articles=articles[start:start+6], page=page, total_pages=(len(articles)+5)//6)

def hash_password(pw): return hashlib.sha256(pw.encode()).hexdigest()

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form['username'].strip(); p = request.form['password'].strip()
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
                "last_updated_date": datetime.now(pytz.timezone('Asia/Jakarta')).strftime("%d-%m-%Y")
            })
        return redirect(url_for('dashboard'))
    return render_template('edit_data_form.html', provinsi=provinsi, wilayah=wilayah, mux=mux)

@app.route("/delete_data/<provinsi>/<wilayah>/<mux>", methods=["POST"])
def delete_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    if ref: ref.child(f"siaran/{provinsi}/{wilayah}/{mux}").delete()
    return redirect(url_for('dashboard'))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        u=request.form['username']; e=request.form['email']; p=request.form['password']; n=request.form['nama']
        if ref:
            otp = str(random.randint(100000, 999999))
            ref.child(f"pending_users/{u}").set({"nama":n, "email":e, "password":hash_password(p), "otp":otp})
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
    output = []
    for u, d in users_data.items():
        output.append(f"INSERT INTO users VALUES ('{u}', '{d.get('nama')}', '{d.get('email')}');")
    return send_file(io.BytesIO("\n".join(output).encode()), as_attachment=True, download_name="users.sql", mimetype="text/plain")

@app.route('/download-csv')
def download_csv():
    users_data = ref.child('users').get() if ref else {}
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(['username', 'nama', 'email'])
    for u, d in users_data.items():
        writer.writerow([u, d.get('nama'), d.get('email')])
    out.seek(0)
    return send_file(io.BytesIO(out.getvalue().encode()), as_attachment=True, download_name="users.csv", mimetype="text/csv")

@app.route("/test-firebase")
def test_firebase(): return "Firebase Connected" if ref else "Error"
@app.route('/sitemap.xml')
def sitemap(): return send_file('static/sitemap.xml')

if __name__ == "__main__":
    app.run(debug=True)
