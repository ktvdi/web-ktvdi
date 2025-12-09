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
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-ktvdi")

# --- 1. SETUP FIREBASE (DENGAN SAFE GUARD) ---
ref = None # Default None
try:
    # Cek apakah variabel env ada
    if os.environ.get("FIREBASE_PROJECT_ID"):
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
        
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred, {'databaseURL': os.environ.get('DATABASE_URL')})
        
        ref = db.reference('/')
        print("✅ Firebase Terhubung!")
    else:
        print("⚠️ Warning: Environment Variable Firebase tidak lengkap. Mode Offline.")
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
model = genai.GenerativeModel("gemini-2.5-flash", system_instruction="Anda adalah Chatbot AI KTVDI...")

# --- HELPERS ---
def get_gempa_terkini():
    try:
        url = "https://data.bmkg.go.id/DataMKG/TEWS/gempadirasakan.json"
        r = requests.get(url, timeout=2) # Timeout cepat biar web gak lemot
        if r.status_code == 200: return r.json()['Infogempa']['gempa'][0]
    except: return None

def get_cuaca_default():
    try:
        url = "https://api.open-meteo.com/v1/forecast?latitude=-6.99&longitude=110.42&current_weather=true"
        r = requests.get(url, timeout=2)
        if r.status_code == 200:
            d = r.json()['current_weather']
            codes = {0:'Cerah', 1:'Cerah Berawan', 2:'Berawan', 3:'Mendung', 51:'Gerimis', 61:'Hujan', 95:'Badai'}
            desc = codes.get(d['weathercode'], 'Berawan')
            return {'t': round(d['temperature']), 'ws': d['windspeed'], 'weather_desc': desc, 'lokasi': 'Semarang (Default)'}
    except: return None

def hash_pw(p): return hashlib.sha256(p.encode()).hexdigest()

# --- ROUTES ---
@app.route("/")
def home():
    # SAFE GUARD: Jika Firebase error, pakai data kosong agar web tetap jalan
    siaran_data = {}
    if ref:
        try:
            siaran_data = ref.child('siaran').get() or {}
        except: pass

    stats = {'wilayah': 0, 'siaran': 0, 'mux': 0, 'top_name': '-', 'top_count': 0, 'last_update': datetime.now().strftime('%d-%m-%Y')}
    provinsi_tersedia = []
    siaran_counts = Counter()

    if siaran_data:
        provinsi_tersedia = list(siaran_data.keys())
        for p_val in siaran_data.values():
            if isinstance(p_val, dict):
                stats['wilayah'] += len(p_val)
                for w_val in p_val.values():
                    if isinstance(w_val, dict):
                        stats['mux'] += len(w_val)
                        for m_val in w_val.values():
                            if 'siaran' in m_val:
                                stats['siaran'] += len(m_val['siaran'])
                                for s in m_val['siaran']: siaran_counts[s.lower()] += 1
                            if 'last_updated_date' in m_val: stats['last_update'] = m_val['last_updated_date']

    if siaran_counts:
        top = siaran_counts.most_common(1)[0]
        stats['top_name'] = top[0].upper(); stats['top_count'] = top[1]

    return render_template('index.html', 
                           jumlah_wilayah_layanan=stats['wilayah'],
                           jumlah_penyelenggara_mux=stats['mux'],
                           jumlah_siaran=stats['siaran'],
                           most_common_siaran_name=stats['top_name'],
                           most_common_siaran_count=stats['top_count'],
                           last_updated_time=stats['last_update'],
                           gempa_data=get_gempa_terkini(),
                           cuaca_data=get_cuaca_default(),
                           provinsi_tersedia=provinsi_tersedia)

@app.route('/', methods=['POST'])
def chatbot():
    data = request.get_json()
    try:
        response = model.generate_content(data.get("prompt"))
        return jsonify({"response": response.text})
    except: return jsonify({"error": "AI Busy"})

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if not ref: return render_template('login.html', error="Database Error")
        u = request.form['username'].strip()
        p = hash_pw(request.form['password'].strip())
        udata = ref.child(f'users/{u}').get()
        if udata and udata.get('password') == p:
            session['user'] = u; session['nama'] = udata.get('nama')
            return redirect(url_for('dashboard'))
        return render_template('login.html', error="Login Gagal")
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    provs = []
    if ref: provs = list((ref.child("provinsi").get() or {}).values())
    return render_template("dashboard.html", name=session.get('nama'), provinsi_list=provs)

# ... (Rute lain seperti register, forgot-password, CRUD data, faq, about, berita)
# Pastikan untuk rute CRUD juga ditambahkan cek "if ref:" agar tidak crash

@app.route('/faq')
def faq(): return render_template('faq.html')
@app.route('/about')
def about(): return render_template('about.html')
@app.route('/berita')
def berita():
    try:
        feed = feedparser.parse('https://news.google.com/rss/search?q=tv+digital&hl=id&gl=ID&ceid=ID:id')
        return render_template('berita.html', articles=feed.entries[:5], page=1, total_pages=1)
    except: return render_template('berita.html', articles=[], page=1, total_pages=1)
@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

# API Helpers
@app.route("/daftar-siaran")
def daftar_siaran():
    provs = []
    if ref: provs = list((ref.child("provinsi").get() or {}).values())
    return render_template("daftar-siaran.html", provinsi_list=provs)

if __name__ == "__main__":
    app.run(debug=True)
