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
app.secret_key = os.environ.get("SECRET_KEY", "ktvdi-final-fix-2026")

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
Gaya: Ramah, Sopan, Solutif, Emoji (😊, 👋).
Aturan:
1. Sapa dengan "Kak" atau "Sobat".
2. Piala Dunia 2026: Hak siar TVRI (Gratis & HD).
3. Selalu tawarkan bantuan lain.
"""

# --- 4. HELPERS ---
def get_news_entries():
    """Berita Google News & CNN"""
    all_news = []
    sources = [
        'https://news.google.com/rss?hl=id&gl=ID&ceid=ID:id', 
        'https://www.cnnindonesia.com/nasional/rss',
        'https://www.antaranews.com/rss/tekno.xml'
    ]
    for url in sources:
        try:
            feed = feedparser.parse(url)
            if feed.entries:
                for entry in feed.entries:
                    entry['source_name'] = feed.feed.title if 'title' in feed.feed else "Berita"
                all_news.extend(feed.entries[:10])
        except: continue
    
    all_news.sort(key=lambda x: x.published_parsed if x.get('published_parsed') else time.gmtime(0), reverse=True)
    
    # Hapus Duplikat
    unique_news = []
    seen = set()
    for news in all_news:
        if news.title not in seen:
            unique_news.append(news)
            seen.add(news.title)
    return unique_news[:20]

def get_java_weather():
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
                            c = {"0":"Cerah ☀️","1":"Cerah Berawan 🌤️","3":"Berawan ☁️","60":"Hujan 🌧️","95":"Badai ⛈️"}
                            report.append(f"- {area}: {c.get(v, 'Berawan ☁️')}")
                        break
        except: continue
    return "\n".join(report) if report else "Data cuaca tidak tersedia."

def get_daily_news_summary_ai():
    entries = get_news_entries()
    if not entries: return "Update berita..."
    titles = [e.title for e in entries[:5]]
    text = "\n".join(titles)
    if model:
        try:
            res = model.generate_content(f"Ceritakan ulang berita ini:\n{text}")
            return res.text
        except: pass
    return "Cek halaman Berita."

def hash_password(pw): return hashlib.sha256(pw.encode()).hexdigest()

def time_since_published(published_time):
    try:
        now = datetime.now()
        pt = datetime(*published_time[:6])
        diff = now - pt
        if diff.days > 0: return f"{diff.days} hari lalu"
        if diff.seconds > 3600: return f"{diff.seconds//3600} jam lalu"
        return "Baru saja"
    except: return ""

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

# 🔹 FIX: CHATBOT API DI JALUR SENDIRI (MENGHINDARI ERROR 405)
@app.route('/api/chat', methods=['POST'])
def chatbot_api():
    if not model: return jsonify({"response": "Maaf Kak, AI sedang loading..."})
    data = request.get_json()
    try:
        response = model.generate_content(f"{MODI_PROMPT}\nUser: {data.get('prompt')}\nModi:")
        return jsonify({"response": response.text})
    except: return jsonify({"response": "Maaf Kak, Modi lagi sibuk."})

@app.route("/api/news-ticker")
def news_ticker():
    entries = get_news_entries()
    titles = [e.title for e in entries[:20]]
    if not titles: titles = ["Selamat Datang di KTVDI", "Pantau Info TV Digital Terkini"]
    return jsonify(titles)

# --- EMAIL ---
@app.route("/api/cron/daily-blast", methods=['GET'])
def trigger_daily_blast():
    try:
        users = ref.child('users').get() if ref else {}
        cuaca = get_java_weather()
        berita = get_daily_news_summary_ai()
        date = datetime.now().strftime("%d %B %Y")
        
        for uid, user in users.items():
            if isinstance(user, dict) and user.get('email'):
                try:
                    msg = Message(f"Kabar Senja KTVDI - {date}", recipients=[user['email']])
                    msg.body = f"Halo Kak {user.get('nama','KTVDI')},\n\nCuaca Esok (Jawa):\n{cuaca}\n\nBerita:\n{berita}\n\nSalam,\nKTVDI"
                    mail.send(msg)
                except: pass
        return jsonify({"status": "Sent"}), 200
    except Exception as e: return jsonify({"error": str(e)}), 500

# --- AUTH ---
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
        if ref.child("users").get() and u in ref.child("users").get(): flash("Username dipakai", "error"); return render_template("register.html")
        otp = str(random.randint(100000, 999999))
        ref.child(f'pending_users/{u}').set({"nama": n, "email": e, "password": hash_password(p), "otp": otp})
        try:
            msg = Message("Verifikasi KTVDI", recipients=[e])
            msg.body = f"Halo Kak {n}, Kode OTP: {otp}\n\nSalam,\nAdmin KTVDI"
            mail.send(msg)
            session["pending_username"] = u
            return redirect(url_for("verify_register"))
        except: flash("Gagal kirim email", "error")
    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    u = session.get("pending_username")
    if not u: return redirect(url_for("register"))
    if request.method == "POST":
        p = ref.child(f'pending_users/{u}').get()
        if p and str(p.get('otp')) == request.form.get("otp"):
            ref.child(f'users/{u}').set({"nama":p['nama'], "email":p['email'], "password":p['password'], "points":0})
            ref.child(f'pending_users/{u}').delete()
            session.pop('pending_username', None)
            try:
                msg = Message("Akun Aktif!", recipients=[p['email']])
                msg.body = f"Halo {p['nama']}, Selamat datang di KTVDI!"
                mail.send(msg)
            except: pass
            flash("Berhasil!", "success")
            return redirect(url_for('login'))
        flash("OTP Salah", "error")
    return render_template("verify-register.html", username=u)

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("identifier")
        users = ref.child("users").get() or {}
        found_uid = next((uid for uid, v in users.items() if v.get('email')==email), None)
        if found_uid:
            otp = str(random.randint(100000, 999999))
            ref.child(f"otp/{found_uid}").set({"email": email, "otp": otp})
            try:
                msg = Message("Reset Password", recipients=[email])
                msg.body = f"Kode OTP: {otp}"
                mail.send(msg)
                session["reset_uid"] = found_uid
                return redirect(url_for("verify_otp"))
            except: flash("Gagal kirim email", "error")
        else: flash("Email tidak ditemukan", "error")
    return render_template("forgot-password.html")

@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    uid = session.get("reset_uid")
    if request.method == "POST":
        data = ref.child(f"otp/{uid}").get()
        if data and str(data.get("otp")) == request.form.get("otp"):
            session['reset_verified'] = True
            return redirect(url_for("reset_password"))
        flash("OTP Salah", "error")
    return render_template("verify-otp.html")

@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    if not session.get('reset_verified'): return redirect(url_for('login'))
    uid = session.get("reset_uid")
    if request.method == "POST":
        pw = request.form.get("password")
        ref.child(f"users/{uid}").update({"password": hash_password(pw)})
        ref.child(f"otp/{uid}").delete()
        session.clear()
        flash("Sukses", "success")
        return redirect(url_for('login'))
    return render_template("reset-password.html")

# --- OTHER ROUTES ---
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
def delete_data(provinsi, wilayah, mux):
    if 'user' in session: ref.child(f"siaran/{provinsi}/{wilayah}/{mux}").delete()
    return redirect(url_for('dashboard'))

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

if __name__ == "__main__":
    app.run(debug=True)
