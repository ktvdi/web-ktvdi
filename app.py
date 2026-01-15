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
from datetime import datetime, timedelta
from collections import Counter

# Load environment lokal
load_dotenv()

app = Flask(__name__)
CORS(app)

# --- 1. KEAMANAN SESI (CRUCIAL FOR LOGIN) ---
# Gunakan key statis sebagai fallback jika ENV tidak terbaca, agar login tidak mental
app.secret_key = os.environ.get("SECRET_KEY", "ktvdi-super-secret-key-2026-fixed")
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 86400 # 24 Jam

# --- 2. KONEKSI FIREBASE (VERCEL SAFE MODE) ---
ref = None
try:
    # Prioritas 1: Cek Environment Variable (Vercel Production)
    priv_key = os.environ.get("FIREBASE_PRIVATE_KEY")
    
    if priv_key:
        # PENTING: Fix formatting private key di Vercel
        final_priv_key = priv_key.replace('\\n', '\n')
        
        cred_dict = {
            "type": "service_account",
            "project_id": os.environ.get("FIREBASE_PROJECT_ID"),
            "private_key_id": os.environ.get("FIREBASE_PRIVATE_KEY_ID"),
            "private_key": final_priv_key,
            "client_email": os.environ.get("FIREBASE_CLIENT_EMAIL"),
            "client_id": os.environ.get("FIREBASE_CLIENT_ID"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": os.environ.get("FIREBASE_CLIENT_X509_CERT_URL"),
            "universe_domain": "googleapis.com"
        }
        
        cred = credentials.Certificate(cred_dict)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred, {'databaseURL': os.environ.get('DATABASE_URL')})
        ref = db.reference('/')
        print("✅ Firebase Connected via ENV")
        
    # Prioritas 2: Cek File credentials.json (Lokal Development)
    elif os.path.exists("credentials.json"):
        cred = credentials.Certificate("credentials.json")
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred, {'databaseURL': os.environ.get('DATABASE_URL')})
        ref = db.reference('/')
        print("✅ Firebase Connected via JSON")
        
    else:
        print("⚠️ Warning: No Firebase Credentials found.")

except Exception as e:
    # Tangkap error agar Vercel TIDAK 500 ERROR, tapi lanjut jalan dengan fitur terbatas
    print(f"❌ Firebase Init Error: {e}")
    ref = None

# --- 3. KONFIGURASI EMAIL ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME") 
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD") 
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")
mail = Mail(app)

# --- 4. AI GEMINI ---
GEMINI_KEY = os.environ.get("GEMINI_APP_KEY")
model = None
try:
    if GEMINI_KEY:
        genai.configure(api_key=GEMINI_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash") # Gunakan 1.5 Flash yang stabil
except Exception as e:
    print(f"⚠️ Gemini Init Error: {e}")

MODI_PROMPT = """
Anda adalah MODI, Asisten Virtual Resmi KTVDI.
Karakter: Profesional, Ramah, Solutif, dan Menggunakan Bahasa Indonesia Baku namun hangat.
"""

# --- 5. HELPERS ---
def hash_password(pw): return hashlib.sha256(pw.encode()).hexdigest()
def normalize_input(text): return text.strip().lower() if text else ""

def format_indo_date(time_struct):
    if not time_struct: return ""
    try:
        dt = datetime.fromtimestamp(time.mktime(time_struct))
        hari = ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu'][dt.weekday()]
        bulan = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'][dt.month - 1]
        return f"{hari}, {dt.day} {bulan} {dt.year} | {dt.strftime('%H:%M')} WIB"
    except: return "Baru saja"

def get_news_entries():
    all_news = []
    try:
        sources = [
            'https://news.google.com/rss/search?q=tv+digital+indonesia+kominfo&hl=id&gl=ID&ceid=ID:id',
            'https://www.cnnindonesia.com/nasional/rss',
            'https://www.antaranews.com/rss/tekno.xml',
            'https://www.suara.com/rss/tekno'
        ]
        for url in sources:
            try:
                # Timeout penting agar Vercel tidak timeout saat fetch berita
                response = requests.get(url, timeout=4) 
                feed = feedparser.parse(response.content)
                if feed.entries:
                    for entry in feed.entries[:5]: 
                        if 'cnn' in url: entry['source_name'] = 'CNN Nasional'
                        elif 'antara' in url: entry['source_name'] = 'Antara Tekno'
                        elif 'suara' in url: entry['source_name'] = 'Suara.com'
                        else: entry['source_name'] = 'Google News'
                        all_news.append(entry)
            except: continue
        all_news.sort(key=lambda x: x.published_parsed if x.get('published_parsed') else time.gmtime(0), reverse=True)
    except: pass
    
    if not all_news:
        t = datetime.now().timetuple()
        return [{'title': 'Selamat Datang di Portal KTVDI', 'link': '#', 'published_parsed': t, 'source_name': 'Info'}]
    return all_news[:20]

def time_since_published(published_time):
    try:
        now = datetime.now()
        pt = datetime(*published_time[:6])
        diff = now - pt
        if diff.days > 0: return f"{diff.days} hari lalu"
        if diff.seconds > 3600: return f"{diff.seconds//3600} jam lalu"
        return "Baru saja"
    except: return "Baru saja"

def get_quote_religi():
    return {
        "muslim": [
            "Wahai orang-orang yang beriman, bertakwalah kepada Allah dan hendaklah kamu bersama orang-orang yang jujur. (QS. At-Taubah: 119)",
            "Sesungguhnya shalat itu mencegah dari (perbuatan-perbuatan) keji dan mungkar. (QS. Al-Ankabut: 45)",
            "Kejujuran adalah ketenangan, sedangkan kebohongan adalah kegelisahan. (HR. Tirmidzi)",
            "Barangsiapa yang tidak menyayangi, maka tidak akan disayangi. (HR. Bukhari)"
        ],
        "universal": [
            "Integritas adalah melakukan hal yang benar, bahkan ketika tidak ada orang yang melihat.",
            "Kejujuran adalah mata uang yang berlaku di mana saja. Jadilah pribadi yang dapat dipercaya.",
            "Kebaikan yang Anda tanam hari ini akan menjadi pohon peneduh bagi Anda di masa depan.",
            "Damai di dunia dimulai dari damai di hati dan kejujuran dalam perbuatan."
        ]
    }

# ==========================================
# 6. ROUTE HANDLERS
# ==========================================

@app.route("/", methods=['GET'])
def home():
    stats = {'wilayah': 0, 'mux': 0, 'channel': 0}
    last_str = "-"
    # Cek ref sebelum akses untuk mencegah crash
    if ref:
        try:
            siaran = ref.child('siaran').get() or {}
            for prov in siaran.values():
                if isinstance(prov, dict):
                    stats['wilayah'] += len(prov)
                    for wil in prov.values():
                        if isinstance(wil, dict):
                            stats['mux'] += len(wil)
                            for d in wil.values():
                                if 'siaran' in d: stats['channel'] += len(d['siaran'])
            last_str = datetime.now().strftime('%d-%m-%Y')
        except: pass
    return render_template('index.html', stats=stats, last_updated_time=last_str)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        raw_input = request.form.get('username')
        password = request.form.get('password')
        
        if not ref: return render_template('login.html', error="Koneksi Database Terputus. Cek Server.")
        
        hashed_pw = hash_password(password)
        clean_input = normalize_input(raw_input)
        
        try:
            users = ref.child('users').get() or {}
            target_user = None
            target_uid = None
            
            for uid, data in users.items():
                if not isinstance(data, dict): continue
                if normalize_input(uid) == clean_input:
                    target_user = data; target_uid = uid; break
                if normalize_input(data.get('email')) == clean_input:
                    target_user = data; target_uid = uid; break
            
            if target_user and target_user.get('password') == hashed_pw:
                session.permanent = True
                session['user'] = target_uid
                session['nama'] = target_user.get('nama', 'Pengguna')
                return redirect(url_for('dashboard'))
            
            return render_template('login.html', error="Username/Email atau Password Salah.")
        except Exception as e:
            return render_template('login.html', error=f"Terjadi kesalahan sistem: {str(e)}")
            
    return render_template('login.html')

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        u = normalize_input(request.form.get("username"))
        e = normalize_input(request.form.get("email"))
        n = request.form.get("nama")
        p = request.form.get("password")
        
        if not ref: 
            flash("Database Error: Tidak dapat terhubung ke Firebase.", "error")
            return render_template("register.html")
            
        try:
            users = ref.child("users").get() or {}
            
            if u in users:
                flash("Username sudah dipakai.", "error"); return render_template("register.html")
            for uid, data in users.items():
                if isinstance(data, dict) and normalize_input(data.get('email')) == e:
                    flash("Email sudah terdaftar.", "error"); return render_template("register.html")

            otp = str(random.randint(100000, 999999))
            expiry = time.time() + 60 # 1 Menit
            
            ref.child(f'pending_users/{u}').set({
                "nama": n, "email": e, "password": hash_password(p), "otp": otp, "expiry": expiry
            })
            
            msg = Message("Kode Verifikasi KTVDI", recipients=[e])
            msg.body = f"Halo {n},\n\nKode OTP Anda (1 Menit): {otp}\n\nSalam,\nAdmin KTVDI"
            mail.send(msg)
            
            session["pending_username"] = u
            return redirect(url_for("verify_register"))
        except Exception as err:
            print(f"Register Error: {err}")
            flash("Gagal memproses pendaftaran. Cek koneksi internet/email.", "error")
            
    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    u = session.get("pending_username")
    if not u: return redirect(url_for("register"))
    
    if request.method == "POST":
        try:
            p = ref.child(f'pending_users/{u}').get()
            if not p:
                flash("Sesi habis.", "error"); return redirect(url_for("register"))
            
            if time.time() > p.get('expiry', 0):
                flash("Kode OTP Kedaluwarsa.", "error")
                ref.child(f'pending_users/{u}').delete()
                return redirect(url_for("register"))

            if str(p.get('otp')).strip() == request.form.get("otp").strip():
                ref.child(f'users/{u}').set({
                    "nama": p['nama'], "email": p['email'], "password": p['password'], "points": 0, "join_date": datetime.now().strftime("%d-%m-%Y")
                })
                ref.child(f'pending_users/{u}').delete()
                session.pop('pending_username', None)
                flash("Sukses! Silakan Login.", "success")
                return redirect(url_for('login'))
            flash("OTP Salah.", "error")
        except:
            flash("Terjadi kesalahan verifikasi.", "error")
            
    return render_template("verify-register.html", username=u)

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email_input = normalize_input(request.form.get("identifier"))
        if not ref: 
            flash("Database Error.", "error"); return render_template("forgot-password.html")
            
        users = ref.child("users").get() or {}
        found_uid = None
        target_name = "Sahabat"
        
        for uid, user_data in users.items():
            if isinstance(user_data, dict) and normalize_input(user_data.get('email')) == email_input:
                found_uid = uid
                target_name = user_data.get('nama', 'Sahabat')
                break
        
        if found_uid:
            otp = str(random.randint(100000, 999999))
            expiry = time.time() + 60
            ref.child(f"otp/{found_uid}").set({"email": email_input, "otp": otp, "expiry": expiry})
            try:
                msg = Message("Reset Password KTVDI", recipients=[email_input])
                msg.body = f"Halo {target_name},\n\nKode Reset (1 Menit): {otp}"
                mail.send(msg)
                session["reset_uid"] = found_uid
                return redirect(url_for("verify_otp"))
            except: flash("Gagal kirim email.", "error")
        else: flash("Email tidak ditemukan.", "error")
    return render_template("forgot-password.html")

@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    uid = session.get("reset_uid")
    if not uid: return redirect(url_for("forgot_password"))
    if request.method == "POST":
        data = ref.child(f"otp/{uid}").get()
        if not data or time.time() > data.get('expiry', 0):
            flash("Kode kedaluwarsa.", "error"); return redirect(url_for("forgot_password"))
        if str(data.get("otp")).strip() == request.form.get("otp").strip():
            session['reset_verified'] = True
            return redirect(url_for("reset_password"))
        flash("Kode Salah.", "error")
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
        flash("Password diubah. Login sekarang.", "success")
        return redirect(url_for('login'))
    return render_template("reset-password.html")

# --- FITUR RELIGI & JADWAL SHOLAT ---
@app.route("/jadwal-sholat")
def jadwal_sholat_page():
    kota = ["Ambon", "Balikpapan", "Banda Aceh", "Bandar Lampung", "Bandung", "Banjar", "Banjarbaru", "Banjarmasin", "Batam", "Batu",
        "Bau-Bau", "Bekasi", "Bengkulu", "Bima", "Binjai", "Bitung", "Blitar", "Bogor", "Bontang", "Bukittinggi",
        "Cilegon", "Cimahi", "Cirebon", "Denpasar", "Depok", "Dumai", "Garut", "Gorontalo", "Gunungsitoli", "Jakarta", "Jambi",
        "Jayapura", "Kediri", "Kendari", "Kotamobagu", "Kupang", "Langsa", "Lhokseumawe", "Lubuklinggau", "Madiun", "Magelang",
        "Makassar", "Malang", "Manado", "Mataram", "Medan", "Metro", "Mojokerto", "Padang", "Padangpanjang", "Padangsidempuan",
        "Pagar Alam", "Palangkaraya", "Palembang", "Palopo", "Palu", "Pangkal Pinang", "Parepare", "Pariaman", "Pasuruan", "Payakumbuh",
        "Pekalongan", "Pekanbaru", "Pematangsiantar", "Pontianak", "Prabumulih", "Probolinggo", "Purwokerto", "Purwodadi", "Sabang", "Salatiga",
        "Samarinda", "Sawahlunto", "Semarang", "Serang", "Sibolga", "Singkawang", "Solok", "Sorong", "Subulussalam", "Sukabumi",
        "Surabaya", "Surakarta (Solo)", "Tangerang", "Tangerang Selatan", "Tanjungbalai", "Tanjungpinang", "Tarakan", "Tasikmalaya", "Tebing Tinggi", "Tegal",
        "Ternate", "Tidore Kepulauan", "Tomohon", "Tual", "Yogyakarta"
    ]
    quotes = get_quote_religi()
    
    # Notif Email (Sekali per sesi)
    if 'user' in session and not session.get('religi_notif_sent'):
        try:
            users = ref.child('users').get() or {}
            user_data = users.get(session['user'])
            if user_data and user_data.get('email'):
                nama = user_data.get('nama', 'Sahabat')
                msg = Message("🕌 Pengingat Kebaikan KTVDI", recipients=[user_data['email']])
                msg.body = f"Halo Kak {nama},\n\nTerima kasih sudah membuka fitur Jadwal Sholat.\nSemoga harimu berkah dan selalu dalam lindungan-Nya.\n\nSalam,\nKTVDI"
                mail.send(msg)
                session['religi_notif_sent'] = True
        except: pass

    return render_template("jadwal-sholat.html", daftar_kota=sorted(kota), quotes=quotes)

# --- CRON EMAIL BLAST ---
@app.route("/api/cron/daily-blast", methods=['GET'])
def trigger_daily_blast():
    try:
        users = ref.child('users').get() or {}
        news = get_news_entries()
        news_summary = "\n".join([f"- {i['title']} ({i['source_name']})" for i in news[:3]])
        date_str = datetime.now().strftime("%d %B %Y")
        
        prompt = f"""
        Buatkan email harian pendek dan sopan untuk member KTVDI.
        Berita: {news_summary}
        Tanggal: {date_str}
        Isi: Sapaan (Gunakan [NAMA]), Rangkuman Berita, Info Cuaca Umum, Pesan Moral (Jujur & Ibadah).
        """
        
        content = "Konten sedang disiapkan."
        if model:
            try:
                content = model.generate_content(prompt).text
            except: pass
        
        count = 0
        for uid, user in users.items():
            if isinstance(user, dict) and user.get('email'):
                try:
                    nama = user.get('nama', 'Anggota')
                    final_body = content.replace("[NAMA]", nama).replace("[Nama]", nama)
                    if "[NAMA]" not in content: final_body = f"Halo {nama},\n\n" + final_body
                    
                    msg = Message(f"Warta KTVDI - {date_str}", recipients=[user['email']])
                    msg.body = final_body
                    mail.send(msg)
                    count += 1
                except: pass
        return jsonify({"status": "Success", "sent": count}), 200
    except Exception as e: return jsonify({"error": str(e)}), 500

# --- API CHATBOT ---
@app.route('/api/chat', methods=['POST'])
def chatbot_api():
    data = request.get_json()
    if not model: return jsonify({"response": "Maaf Kak, AI sedang maintenance."})
    try:
        response = model.generate_content(f"{MODI_PROMPT}\nUser: {data.get('prompt')}\nModi:")
        return jsonify({"response": response.text})
    except: return jsonify({"response": "Maaf Kak, sedang sibuk."})

# --- ROUTES LAIN ---
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
            if isinstance(a, dict) and 'published_parsed' in a:
                 a['formatted_date'] = format_indo_date(a['published_parsed'])
                 a['time_since_published'] = time_since_published(a['published_parsed'])
            else:
                 a['formatted_date'] = datetime.now().strftime("%d %B %Y")
                 a['time_since_published'] = "Baru saja"
            
            a['image'] = None
            if 'media_content' in a: a['image'] = a['media_content'][0]['url']
            elif 'links' in a:
                for link in a['links']:
                    if 'image' in link.get('type',''): a['image'] = link.get('href')
                    
        return render_template('berita.html', articles=current, page=page, total_pages=(len(entries)//per_page)+1)
    except: return render_template('berita.html', articles=[], page=1, total_pages=1)

@app.route("/cctv")
def cctv_page(): return render_template("cctv.html")
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
@app.route("/api/news-ticker")
def news_ticker():
    entries = get_news_entries()
    titles = [e.get('title') for e in entries]
    return jsonify(titles)

if __name__ == "__main__":
    app.run(debug=True)
