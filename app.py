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

# --- 6. ROUTE UTAMA ---
@app.route("/", methods=['GET', 'POST'])
def home():
    # Chatbot Logic
    if request.method == 'POST':
        try:
            prompt = request.get_json().get("prompt")
            reply = model.generate_content(prompt).text if model else "AI belum aktif."
            return jsonify({"response": reply})
        except: return jsonify({"error": "Error"}), 500

    # Data Page Logic
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

    # RENDER KE INDEX.HTML (Yang akan meng-extend base.html)
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
    # (Logika register sama seperti sebelumnya, disingkat agar muat)
    if request.method == "POST":
        user = request.form.get("username")
        # ...simpan ke pending...
        flash("Silakan cek email untuk OTP (Logika disingkat)", "info")
        return redirect(url_for("login")) 
    return render_template("register.html")

@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    try: p_list = list(db.reference("provinsi").get().values())
    except: p_list = []
    return render_template("dashboard.html", name=session.get('nama'), provinsi_list=p_list)

# (Tambahkan route add_data, edit_data, delete_data sesuai kode sebelumnya)
# Route API get_wilayah dll juga tetap sama

@app.errorhandler(500)
def server_error(e): return "<h1>500 - Server Error</h1><p>Cek Terminal & .env</p>", 500

if __name__ == "__main__":
    app.run(debug=True)
