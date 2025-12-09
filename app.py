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

# --- FIREBASE INIT ---
try:
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
    firebase_admin.initialize_app(cred, {'databaseURL': os.environ.get('DATABASE_URL')})
    ref = db.reference('/')
    print("✅ Firebase Connected")
except Exception as e:
    print(f"❌ Firebase Error: {e}")
    ref = None

# --- EMAIL CONFIG ---
app.config['MAIL_SERVER'] = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
app.config['MAIL_PORT'] = int(os.environ.get("MAIL_PORT", 587))
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD")
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")
mail = Mail(app)

# --- GEMINI AI ---
genai.configure(api_key=os.environ.get("GEMINI_APP_KEY"))
model = genai.GenerativeModel("gemini-2.5-flash", system_instruction="Anda adalah Chatbot AI KTVDI. Jawab pertanyaan seputar TV Digital, STB, dan troubleshooting sinyal dengan ramah.")

# --- FUNGSI PENDUKUNG ---
def get_gempa_terkini():
    """Ambil Gempa Dirasakan dari BMKG"""
    try:
        url = "https://data.bmkg.go.id/DataMKG/TEWS/gempadirasakan.json"
        r = requests.get(url, timeout=3)
        if r.status_code == 200:
            return r.json()['Infogempa']['gempa'][0]
    except: return None

# --- ROUTE UTAMA ---
@app.route("/")
def home():
    ref = db.reference('siaran')
    siaran_data = ref.get()

    # Default Stats
    stats = {'wilayah': 0, 'siaran': 0, 'mux': 0, 'top_name': '-', 'top_count': 0}
    last_update = datetime.now().strftime('%d-%m-%Y')
    
    provinsi_tersedia = []
    siaran_counts = Counter()

    if siaran_data:
        provinsi_tersedia = list(siaran_data.keys())
        for prov_val in siaran_data.values():
            if isinstance(prov_val, dict):
                stats['wilayah'] += len(prov_val)
                for wil_val in prov_val.values():
                    if isinstance(wil_val, dict):
                        stats['mux'] += len(wil_val)
                        for mux_val in wil_val.values():
                            if 'siaran' in mux_val:
                                stats['siaran'] += len(mux_val['siaran'])
                                for s in mux_val['siaran']: siaran_counts[s.lower()] += 1
                            if 'last_updated_date' in mux_val:
                                last_update = mux_val['last_updated_date']

    if siaran_counts:
        top = siaran_counts.most_common(1)[0]
        stats['top_name'] = top[0].upper()
        stats['top_count'] = top[1]

    return render_template('index.html', 
                           stats=stats,
                           last_update=last_update,
                           gempa_data=get_gempa_terkini(),
                           provinsi_tersedia=provinsi_tersedia)

# --- CHATBOT API ---
@app.route('/', methods=['POST'])
def chatbot():
    data = request.get_json()
    try:
        response = model.generate_content(data.get("prompt"))
        return jsonify({"response": response.text})
    except: return jsonify({"error": "AI Busy"})

# --- STATIC PAGES ---
@app.route('/faq')
def faq(): return render_template('faq.html')
@app.route('/about')
def about(): return render_template('about.html')
@app.route('/sitemap.xml')
def sitemap(): return send_from_directory('static', 'sitemap.xml')

# --- AUTH SYSTEM (Hash & Routes) ---
def hash_pw(p): return hashlib.sha256(p.encode()).hexdigest()

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form['username'].strip()
        p = hash_pw(request.form['password'].strip())
        udata = db.reference(f'users/{u}').get()
        if udata and udata.get('password') == p:
            session['user'] = u
            session['nama'] = udata.get('nama')
            return redirect(url_for('dashboard'))
        return render_template('login.html', error="Username/Password Salah")
    return render_template('login.html')

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        u, e, p = request.form['username'], request.form['email'], request.form['password']
        otp = str(random.randint(100000, 999999))
        db.reference(f"pending_users/{u}").set({"nama": request.form['nama'], "email": e, "password": hash_pw(p), "otp": otp})
        # Mock Email Send (In prod use mail.send)
        session["pending_username"] = u
        return redirect(url_for("verify_register"))
    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    u = session.get("pending_username")
    if request.method == "POST":
        data = db.reference(f"pending_users/{u}").get()
        if data and data.get("otp") == request.form['otp']:
            db.reference(f"users/{u}").set({"nama": data["nama"], "email": data["email"], "password": data["password"], "points": 0})
            db.reference(f"pending_users/{u}").delete()
            return redirect(url_for("login"))
    return render_template("verify-register.html", username=u)

# --- DASHBOARD & CRUD ---
@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    return render_template("dashboard.html", name=session.get('nama'), provinsi_list=list((db.reference("provinsi").get() or {}).values()))

@app.route("/daftar-siaran")
def daftar_siaran(): return render_template("daftar-siaran.html", provinsi_list=list((db.reference("provinsi").get() or {}).values()))

# ... (Add/Edit/Delete/Get Routes sesuai kode sebelumnya) ...
@app.route("/add_data", methods=["GET", "POST"])
def add_data():
    if 'user' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        # Simpan logika
        p, w, m, s = request.form['provinsi'], request.form['wilayah'], request.form['mux'], request.form['siaran']
        now = datetime.now(pytz.timezone('Asia/Jakarta'))
        db.reference(f"siaran/{p}/{w}/{m}").set({
            "siaran": sorted([x.strip() for x in s.split(',')]),
            "last_updated_date": now.strftime("%d-%m-%Y")
        })
        return redirect(url_for('dashboard'))
    return render_template('add_data_form.html', provinsi_list=list((db.reference("provinsi").get() or {}).values()))

@app.route("/get_wilayah")
def get_wilayah(): return jsonify({"wilayah": list((db.reference(f"siaran/{request.args.get('provinsi')}").get() or {}).keys())})
@app.route("/get_mux")
def get_mux(): return jsonify({"mux": list((db.reference(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}").get() or {}).keys())})
@app.route("/get_siaran")
def get_siaran(): return jsonify(db.reference(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}/{request.args.get('mux')}").get() or {})

@app.route('/berita')
def berita():
    feed = feedparser.parse('https://news.google.com/rss/search?q=tv+digital&hl=id&gl=ID&ceid=ID:id')
    return render_template('berita.html', articles=feed.entries[:5], page=1, total_pages=1)

if __name__ == "__main__":
    app.run(debug=True)
