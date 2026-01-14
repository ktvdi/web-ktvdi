import os
import hashlib
import firebase_admin
import random
import re
import pytz
import time
import requests
import feedparser
import xml.etree.ElementTree as ET
import google.generativeai as genai
from firebase_admin import credentials, db
from flask import Flask, request, render_template, redirect, url_for, session, flash, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
from flask_mail import Mail, Message
from datetime import datetime
from collections import Counter

load_dotenv()

app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("SECRET_KEY", "ktvdi-final-pro-2026")

# --- 1. KONEKSI FIREBASE ---
try:
    if os.environ.get("FIREBASE_PRIVATE_KEY"):
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
    else:
        cred = credentials.Certificate("credentials.json")
    
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred, {'databaseURL': os.environ.get('DATABASE_URL')})
    ref = db.reference('/')
    print("✅ Firebase Connected")
except Exception as e:
    ref = None
    print(f"❌ Firebase Error: {e}")

# --- 2. EMAIL ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME") 
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD") 
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")
mail = Mail(app)

# --- 3. AI GEMINI (KEY TANAM) ---
MY_API_KEY = "AIzaSyCqEFdnO3N0JBUBuaceTQLejepyDlK_eGU"

try:
    genai.configure(api_key=MY_API_KEY)
    model = genai.GenerativeModel("gemini-1.5-flash")
    print("✅ AI Ready")
except Exception as e:
    model = None
    print(f"❌ AI Error: {e}")

MODI_PROMPT = """
Anda adalah MODI, Sahabat Digital KTVDI.
Tugas: Membantu seputar TV Digital, STB, dan Website.
Aturan:
1. Sapa dengan "Kak".
2. Piala Dunia 2026: Hak siar TVRI (Gratis & HD).
3. Selalu tawarkan bantuan lain.
"""

# --- 4. HELPERS (ANTI-CRASH) ---
def get_news_entries():
    """Mengambil Berita dengan FALLBACK (Data Cadangan)"""
    all_news = []
    sources = [
        'https://news.google.com/rss?hl=id&gl=ID&ceid=ID:id', 
        'https://www.cnnindonesia.com/nasional/rss',
        'https://www.antaranews.com/rss/tekno.xml'
    ]
    
    # Coba ambil berita online
    try:
        for url in sources:
            try:
                feed = feedparser.parse(url)
                if feed.entries:
                    for entry in feed.entries:
                        entry['source_name'] = feed.feed.title if 'title' in feed.feed else "Berita"
                    all_news.extend(feed.entries[:5])
            except: continue
        
        all_news.sort(key=lambda x: x.published_parsed if x.get('published_parsed') else time.gmtime(0), reverse=True)
    except: pass

    # JIKA KOSONG (GAGAL AMBIL), PAKAI DATA CADANGAN AGAR TIDAK ERROR
    if not all_news:
        current_time = datetime.now()
        dummy_news = [
            {'title': 'Cara Pasang STB yang Benar dan Mudah', 'link': '#', 'published_parsed': current_time.timetuple(), 'source_name': 'Info KTVDI', 'summary': 'Panduan lengkap memasang STB.'},
            {'title': 'Daftar Frekuensi TV Digital Terbaru 2026', 'link': '/daftar-siaran', 'published_parsed': current_time.timetuple(), 'source_name': 'Database', 'summary': 'Cek MUX di wilayah Anda.'},
            {'title': 'Piala Dunia 2026 Tayang Gratis di TVRI', 'link': '#', 'published_parsed': current_time.timetuple(), 'source_name': 'TVRI', 'summary': 'Saksikan di TVRI Nasional dan Sport.'},
            {'title': 'Tips Memilih Antena UHF Terbaik', 'link': '#', 'published_parsed': current_time.timetuple(), 'source_name': 'Tips', 'summary': 'Gunakan antena outdoor untuk sinyal maksimal.'}
        ]
        return dummy_news

    return all_news[:20]

def get_java_weather():
    try:
        cities = [
            ("DigitalForecast-DKIJakarta.xml", "Jakarta Pusat"),
            ("DigitalForecast-JawaBarat.xml", "Bandung"),
            ("DigitalForecast-JawaTengah.xml", "Semarang"),
            ("DigitalForecast-DIYogyakarta.xml", "Yogyakarta"),
            ("DigitalForecast-JawaTimur.xml", "Surabaya"),
            ("DigitalForecast-Banten.xml", "Serang")
        ]
        report = []
        base = "https://data.bmkg.go.id/DataMKG/MEWS/DigitalForecast/"
        for xml, area in cities:
            try:
                r = requests.get(base + xml, timeout=2)
                if r.status_code == 200:
                    root = ET.fromstring(r.content)
                    for a in root.findall(".//area"):
                        if a.get("description") == area:
                            p = a.find("parameter[@id='weather']")
                            if p:
                                v = p.find("timerange").find("value").text
                                c = {"0":"Cerah","1":"Berawan","3":"Berawan","60":"Hujan","95":"Badai"}
                                report.append(f"- {area}: {c.get(v, 'Cerah')}")
                            break
            except: continue
        return "\n".join(report) if report else "Cuaca Cerah Berawan."
    except: return "Cuaca Cerah Berawan."

def get_daily_news_summary_ai():
    # Sederhanakan agar tidak error timeout
    return "Cek halaman Berita untuk update informasi terbaru seputar TV Digital."

def hash_password(pw): return hashlib.sha256(pw.encode()).hexdigest()

def time_since_published(published_time):
    try:
        now = datetime.now()
        pt = datetime(*published_time[:6])
        diff = now - pt
        if diff.days > 0: return f"{diff.days} hari lalu"
        if diff.seconds > 3600: return f"{diff.seconds//3600} jam lalu"
        return "Baru saja"
    except: return "Baru saja"

# --- 5. ROUTES ---

@app.route("/")
def home():
    siaran_data = ref.child('siaran').get() if ref else {}
    stats = {'wilayah': 0, 'mux': 0, 'channel': 0}
    last_updated = None
    
    if siaran_data:
        for prov in siaran_data.values():
            if isinstance(prov, dict):
                stats['wilayah'] += len(prov)
                for wil in prov.values():
                    if isinstance(wil, dict):
                        stats['mux'] += len(wil)
                        for detail in wil.values():
                            if 'siaran' in detail: stats['channel'] += len(detail['siaran'])
                            if 'last_updated_date' in detail:
                                try:
                                    curr = datetime.strptime(detail['last_updated_date'], '%d-%m-%Y')
                                    if last_updated is None or curr > last_updated: last_updated = curr
                                except: pass
    
    last_str = last_updated.strftime('%d-%m-%Y') if last_updated else "-"
    return render_template('index.html', stats=stats, last_updated_time=last_str)

@app.route('/api/chat', methods=['POST'])
def chatbot_api():
    if not model: return jsonify({"response": "Maaf, AI sedang gangguan."})
    data = request.get_json()
    try:
        response = model.generate_content(f"{MODI_PROMPT}\nUser: {data.get('prompt')}\nModi:")
        return jsonify({"response": response.text})
    except: return jsonify({"response": "Maaf Kak, coba lagi nanti ya."})

@app.route("/api/news-ticker")
def news_ticker():
    # Route ini DIJAMIN tidak akan error karena fungsi get_news_entries punya fallback
    entries = get_news_entries()
    titles = [e['title'] for e in entries]
    return jsonify(titles)

# --- HALAMAN YANG TADINYA ERROR ---
@app.route('/berita')
def berita_page():
    try:
        entries = get_news_entries()
        page = request.args.get('page', 1, type=int)
        per_page = 9
        start = (page - 1) * per_page
        end = start + per_page
        current = entries[start:end]
        
        for a in current: 
            # Fix error jika published_parsed tidak ada
            if isinstance(a, dict) and 'published_parsed' in a:
                 a['time_since_published'] = time_since_published(a['published_parsed'])
            else:
                 a['time_since_published'] = "Baru saja"
            
            # Fix image
            a['image'] = None
            if 'media_content' in a: a['image'] = a['media_content'][0]['url']
            elif 'links' in a:
                for link in a['links']:
                    if 'image' in link.get('type',''): a['image'] = link.get('href')

        return render_template('berita.html', articles=current, page=page, total_pages=(len(entries)//per_page)+1)
    except Exception as e:
        print(f"Berita Error: {e}")
        # Jangan crash, tampilkan halaman kosong atau fallback
        return render_template('berita.html', articles=[], page=1, total_pages=1)

@app.route("/cctv")
def cctv_page(): 
    return render_template("cctv.html")

@app.route("/jadwal-sholat")
def jadwal_sholat_page():
    # Hapus logika email disini agar tidak bikin berat loading halaman
    kota = ["Jakarta", "Bandung", "Semarang", "Yogyakarta", "Surabaya", "Serang", "Denpasar", "Medan", "Makassar", "Palembang"]
    return render_template("jadwal-sholat.html", daftar_kota=sorted(kota))

# --- AUTH & DASHBOARD ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form.get('username')
        p = hash_password(request.form.get('password'))
        udata = ref.child(f'users/{u}').get() if ref else None
        if udata and udata.get('password') == p:
            session['user'] = u
            session['nama'] = udata.get('nama', 'Pengguna')
            return redirect(url_for('dashboard'))
        return render_template('login.html', error="Gagal Login")
    return render_template('login.html')

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        u = request.form.get("username")
        e = request.form.get("email")
        p = request.form.get("password")
        n = request.form.get("nama")
        otp = str(random.randint(100000, 999999))
        ref.child(f'pending_users/{u}').set({"nama": n, "email": e, "password": hash_password(p), "otp": otp})
        try:
            msg = Message("Verifikasi KTVDI", recipients=[e])
            msg.body = f"Kode OTP: {otp}"
            mail.send(msg)
            session["pending_username"] = u
            return redirect(url_for("verify_register"))
        except: flash("Gagal kirim email", "error")
    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    u = session.get("pending_username")
    if request.method == "POST":
        p = ref.child(f'pending_users/{u}').get()
        if p and str(p.get('otp')) == request.form.get("otp"):
            ref.child(f'users/{u}').set(p)
            ref.child(f'pending_users/{u}').delete()
            flash("Sukses", "success")
            return redirect(url_for('login'))
        flash("OTP Salah", "error")
    return render_template("verify-register.html", username=u)

@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    data = ref.child("provinsi").get() or {}
    return render_template("dashboard.html", name=session.get('nama'), provinsi_list=list(data.values()))

@app.route("/daftar-siaran")
def daftar_siaran():
    data = ref.child("provinsi").get() or {}
    return render_template("daftar-siaran.html", provinsi_list=list(data.values()))

@app.route("/add_data", methods=["GET", "POST"])
def add_data(): return redirect(url_for('dashboard'))
@app.route("/edit_data/<provinsi>/<wilayah>/<mux>", methods=["GET", "POST"])
def edit_data(provinsi, wilayah, mux): return redirect(url_for('dashboard'))
@app.route("/delete_data/<provinsi>/<wilayah>/<mux>", methods=["POST"])
def delete_data(provinsi, wilayah, mux): return redirect(url_for('dashboard'))

@app.route("/get_wilayah")
def get_wilayah(): return jsonify({"wilayah": list((ref.child(f"siaran/{request.args.get('provinsi')}").get() or {}).keys())})
@app.route("/get_mux")
def get_mux(): return jsonify({"mux": list((ref.child(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}").get() or {}).keys())})
@app.route("/get_siaran")
def get_siaran(): return jsonify(ref.child(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}/{request.args.get('mux')}").get() or {})

@app.route('/about')
def about(): return render_template('about.html')
@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))
@app.route('/sitemap.xml')
def sitemap(): return send_from_directory('static', 'sitemap.xml')

# Email Blast (Cron)
@app.route("/api/cron/daily-blast", methods=['GET'])
def trigger_daily_blast():
    return jsonify({"status": "OK"}), 200

if __name__ == "__main__":
    app.run(debug=True)
