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

# Muat variabel lingkungan
load_dotenv()

app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")

# ==========================================
# 1. KONEKSI FIREBASE (KODE ASLI ANDA)
# ==========================================
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
    print("✅ Firebase berhasil terhubung!")
except Exception as e:
    print("❌ Error initializing Firebase:", str(e))
    ref = None

# ==========================================
# 2. EMAIL (SETUP)
# ==========================================
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD")
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")
mail = Mail(app)

# ==========================================
# 3. AI CHATBOT (KEY ANDA DITANAM)
# ==========================================
# 👇 KEY ANDA SUDAH SAYA MASUKKAN 👇
MY_API_KEY = "AIzaSyCqEFdnO3N0JBUBuaceTQLejepyDlK_eGU"

try:
    genai.configure(api_key=MY_API_KEY)
    model = genai.GenerativeModel("gemini-1.5-flash")
    print("✅ Gemini AI Connected")
except Exception as e:
    model = None
    print(f"❌ AI Error: {e}")

MODI_PROMPT = """
Kamu adalah MODI, Customer Service Profesional dari KTVDI.
Tugas: Membantu user seputar TV Digital, STB, Sinyal, dan Website KTVDI.
Gaya: Ramah, Sopan, Menggunakan Emoji (😊, 👋, 📺), namun tetap Profesional.
Aturan:
1. Sapa dengan "Kak" atau "Sobat KTVDI".
2. Jawaban ringkas, padat, dan solutif.
3. Jika ditanya Piala Dunia 2026, jawab hak siar dipegang TVRI (Gratis & HD).
4. Selalu tawarkan bantuan lain di akhir percakapan.
"""

SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
]

# ==========================================
# 4. HELPERS
# ==========================================
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

def get_bmkg_weather():
    try:
        url = "https://data.bmkg.go.id/DataMKG/MEWS/DigitalForecast/DigitalForecast-DKIJakarta.xml"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            root = ET.fromstring(r.content)
            for area in root.findall(".//area[@description='Jakarta Pusat']"):
                for p in area.findall("parameter[@id='weather']"):
                    t = p.find("timerange")
                    if t:
                        val = t.find("value").text
                        codes = {"0":"Cerah ☀️","1":"Cerah Berawan 🌤️","3":"Berawan ☁️","60":"Hujan 🌧️","95":"Badai ⛈️"}
                        return f"Jakarta Pusat: {codes.get(val, 'Berawan ☁️')}"
        return "Cerah Berawan 🌤️"
    except: return "Cerah Berawan 🌤️"

def get_news_entries():
    """Mengambil berita dengan fallback agar tidak kosong"""
    sources = [
        'https://www.cnnindonesia.com/teknologi/rss',
        'https://news.google.com/rss/search?q=tv+digital+indonesia&hl=id&gl=ID&ceid=ID:id'
    ]
    for url in sources:
        try:
            feed = feedparser.parse(url)
            if feed.entries: return feed.entries
        except: continue
    return []

def get_daily_news_summary_ai():
    entries = get_news_entries()
    if not entries: return "Update berita sedang tidak tersedia."
    titles = [e.title for e in entries[:5]]
    text = "\n".join(titles)
    if model:
        try:
            response = model.generate_content(f"Buat ringkasan berita teknologi harian (3 poin) yang profesional:\n{text}", safety_settings=SAFETY_SETTINGS)
            return response.text
        except: pass
    return "Cek halaman Berita untuk informasi terbaru."

# ==========================================
# 5. ROUTES
# ==========================================

@app.route("/")
def home():
    # LOGIKA ASLI ANDA (Counter Statistik)
    siaran_data = ref.child('siaran').get() if ref else {}
    jumlah_wilayah_layanan = 0
    jumlah_siaran = 0
    jumlah_penyelenggara_mux = 0
    siaran_counts = Counter()
    last_updated_time = None
    
    if siaran_data:
        for prov_data in siaran_data.values():
            if isinstance(prov_data, dict):
                jumlah_wilayah_layanan += len(prov_data)
                for wil_data in prov_data.values():
                    if isinstance(wil_data, dict):
                        jumlah_penyelenggara_mux += len(wil_data)
                        for detail in wil_data.values():
                            if 'siaran' in detail:
                                jumlah_siaran += len(detail['siaran'])
                                for s in detail['siaran']: siaran_counts[s.lower()] += 1
                            if 'last_updated_date' in detail:
                                try:
                                    curr = datetime.strptime(detail['last_updated_date'], '%d-%m-%Y')
                                    if last_updated_time is None or curr > last_updated_time: 
                                        last_updated_time = curr
                                except: pass

    most_common = siaran_counts.most_common(1)
    most_common_name = most_common[0][0].upper() if most_common else None
    most_common_count = most_common[0][1] if most_common else 0
    last_update_str = last_updated_time.strftime('%d-%m-%Y') if last_updated_time else "-"

    return render_template('index.html', 
        most_common_siaran_name=most_common_name,
        most_common_siaran_count=most_common_count,
        jumlah_wilayah_layanan=jumlah_wilayah_layanan,
        jumlah_siaran=jumlah_siaran, 
        jumlah_penyelenggara_mux=jumlah_penyelenggara_mux, 
        last_updated_time=last_update_str
    )

# 🔹 CHATBOT API (KEY FIX)
@app.route('/', methods=['POST'])
def chatbot_api():
    if not model: return jsonify({"response": "Maaf Kak, sistem AI sedang inisialisasi. Coba refresh halaman. 🙏"})
    data = request.get_json()
    user_msg = data.get("prompt")
    if not user_msg: return jsonify({"response": "..."})

    try:
        response = model.generate_content(f"{MODI_PROMPT}\nUser: {user_msg}\nModi:", safety_settings=SAFETY_SETTINGS)
        return jsonify({"response": response.text})
    except Exception as e:
        return jsonify({"response": "Maaf Kak, Modi sedang melayani banyak antrian. Coba tanya lagi ya? 😊"})

# 🔹 NEWS TICKER
@app.route("/api/news-ticker")
def news_ticker():
    entries = get_news_entries()
    titles = [e.title for e in entries[:25]] # Ambil 25 berita
    if not titles: titles = ["Selamat Datang di KTVDI", "Pantau Informasi TV Digital Terkini", "Cek Sinyal di Daerahmu Sekarang"]
    return jsonify(titles)

# 🔹 EMAIL BLAST (PROFESIONAL)
@app.route("/api/cron/daily-blast", methods=['GET'])
def trigger_daily_blast():
    try:
        if not ref: return jsonify({"error": "No DB"}), 500
        users = ref.child('users').get()
        if not users: return jsonify({"status": "No users"}), 200
        
        cuaca = get_bmkg_weather()
        berita = get_daily_news_summary_ai()
        date = datetime.now().strftime("%d %B %Y")
        
        count = 0
        for uid, user in users.items():
            if user.get('email'):
                try:
                    msg = Message(f"📰 Buletin Harian KTVDI - {date}", recipients=[user['email']])
                    msg.body = f"""Yth. {user.get('nama','Anggota KTVDI')},

Selamat malam dan salam sejahtera.
KTVDI hadir kembali untuk menyampaikan rangkuman informasi harian.

--------------------------------------------------
🌤️ PRAKIRAAN CUACA BESOK (DKI Jakarta)
{cuaca}
--------------------------------------------------

📰 RANGKUMAN BERITA HARI INI
{berita}

--------------------------------------------------
💡 ETIKA & POLA HIDUP DIGITAL
"Teknologi ada untuk memudahkan, bukan menjauhkan yang dekat."
Mari jaga kesehatan mata dengan membatasi durasi menonton, dan jaga etika berkomentar di media sosial.

Hormat kami,
TIM IT KTVDI
"""
                    mail.send(msg)
                    count += 1
                except: pass
        return jsonify({"status": "Sent", "count": count}), 200
    except Exception as e: return jsonify({"error": str(e)}), 500

# 🔹 HALAMAN BERITA
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
            if hasattr(a,'published_parsed'): 
                try:
                    dt = datetime(*a.published_parsed[:6])
                    diff = datetime.now() - dt
                    if diff.days > 0: a.time_since_published = f"{diff.days} hari lalu"
                    else: a.time_since_published = f"{diff.seconds//3600} jam lalu"
                except: a.time_since_published = "Baru saja"
            
            # Cari gambar
            a.image = None
            if 'media_content' in a: a.image = a.media_content[0]['url']
            elif 'links' in a:
                for link in a.links:
                    if 'image' in link.type: a.image = link.href

        return render_template('berita.html', articles=current, page=page, total_pages=(len(entries)//per_page)+1)
    except:
        return render_template('berita.html', articles=[], page=1, total_pages=1)

# 🔹 ROUTES LAIN
@app.route("/cctv")
def cctv_page(): return render_template("cctv.html")

@app.route("/jadwal-sholat")
def jadwal_sholat_page():
    if 'user' in session and not session.get('sholat_sent'):
        try:
            u = ref.child(f"users/{session['user']}").get()
            if u and u.get('email'):
                msg = Message("🕋 Pengingat Ibadah - KTVDI", recipients=[u['email']])
                msg.body = f"Assalamualaikum {u.get('nama')},\n\nPesan KTVDI:\nMari laksanakan sholat tepat waktu. Kejujuran adalah kunci keberkahan hidup.\n\nBagi rekan non-muslim, mari tebar kebaikan.\n\nSalam,\nKTVDI"
                mail.send(msg)
                session['sholat_sent'] = True
        except: pass
    
    kota = [
        "Ambon", "Balikpapan", "Banda Aceh", "Bandar Lampung", "Bandung", "Banjarmasin", "Batam", "Bekasi", "Bengkulu", "Bogor",
        "Cirebon", "Denpasar", "Depok", "Gorontalo", "Jakarta", "Jambi", "Jayapura", "Kendari", "Kupang", "Madiun",
        "Magelang", "Makassar", "Malang", "Mamuju", "Manado", "Mataram", "Medan", "Padang", "Palangkaraya", "Palembang",
        "Palu", "Pangkal Pinang", "Pekalongan", "Pekanbaru", "Pontianak", "Purwokerto", "Purwodadi", "Salatiga", "Samarinda", "Semarang",
        "Serang", "Sidoarjo", "Solo", "Sorong", "Surabaya", "Tangerang", "Tanjung Pinang", "Tasikmalaya", "Tegal", "Ternate", "Yogyakarta",
        "Bukittinggi", "Cilegon", "Cimahi", "Dumai", "Kediri", "Lubuklinggau", "Parepare", "Pasuruan", "Probolinggo", "Singkawang", "Sukabumi", "Tarakan"
    ]
    return render_template("jadwal-sholat.html", daftar_kota=sorted(kota))

# 🔹 AUTH (LOGIKA ASLI ANDA)
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form.get('username').strip()
        p = request.form.get('password').strip()
        hashed_pw = hash_password(p)
        
        user_data = ref.child(f'users/{u}').get() if ref else None
        
        if user_data and user_data.get('password') == hashed_pw:
            session['user'] = u
            session['nama'] = user_data.get('nama', 'Pengguna')
            return redirect(url_for('dashboard'))
        return render_template('login.html', error="Username atau Password Salah")
    return render_template('login.html')

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        u = request.form.get("username")
        e = request.form.get("email")
        p = request.form.get("password")
        n = request.form.get("nama")
        
        users = ref.child("users").get() or {}
        if u in users: flash("Username dipakai", "error"); return render_template("register.html")
        
        otp = str(random.randint(100000, 999999))
        ref.child(f'pending_users/{u}').set({"nama": n, "email": e, "password": hash_password(p), "otp": otp})
        
        try:
            msg = Message("Verifikasi Pendaftaran KTVDI", recipients=[e])
            msg.body = f"Yth. {n},\n\nSelamat datang di KTVDI.\nKode OTP: {otp}\n\nJaga kerahasiaan akun Anda.\n\nSalam,\nAdmin KTVDI"
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
        if p and str(p['otp']) == request.form.get("otp"):
            ref.child(f'users/{u}').set({"nama":p['nama'], "email":p['email'], "password":p['password'], "points":0})
            ref.child(f'pending_users/{u}').delete()
            session.pop('pending_username', None)
            try:
                msg = Message("Selamat Datang Resmi di KTVDI", recipients=[p['email']])
                msg.body = f"Yth. {p['nama']},\n\nAkun Anda aktif. Selamat berkontribusi.\n\nSalam,\nKTVDI"
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
                msg = Message("Reset Password KTVDI", recipients=[email])
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
        if data and data["otp"] == request.form.get("otp"):
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
        try:
            udata = ref.child(f"users/{uid}").get()
            msg = Message("Password Berhasil Diubah", recipients=[udata['email']])
            msg.body = "Password akun KTVDI Anda telah diubah."
            mail.send(msg)
        except: pass
        session.clear()
        flash("Sukses", "success")
        return redirect(url_for('login'))
    return render_template("reset-password.html")

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
def add_data():
    if 'user' not in session: return redirect(url_for('login'))
    provs = list((ref.child("provinsi").get() or {}).values())
    if request.method == 'POST':
        p, w, m, s = request.form['provinsi'], request.form['wilayah'], request.form['mux'], request.form['siaran']
        w_clean = re.sub(r'\s*-\s*', '-', w.strip())
        
        # Validasi Regex Asli
        if not re.fullmatch(r"^[a-zA-Z\s]+-\d+$", w_clean):
            return render_template('add_data_form.html', error_message="Format Wilayah Salah", provinsi_list=provs)
        
        now = datetime.now(pytz.timezone('Asia/Jakarta'))
        ref.child(f"siaran/{p}/{w_clean}/{m.strip()}").set({
            "siaran": sorted([x.strip() for x in s.split(',') if x.strip()]),
            "last_updated_by_username": session.get('user'),
            "last_updated_by_name": session.get('nama'),
            "last_updated_date": now.strftime("%d-%m-%Y"),
            "last_updated_time": now.strftime("%H:%M:%S WIB")
        })
        return redirect(url_for('dashboard'))
    return render_template('add_data_form.html', provinsi_list=provs)

@app.route("/edit_data/<provinsi>/<wilayah>/<mux>", methods=["GET", "POST"])
def edit_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    p, w, m = provinsi.replace('%20',' '), wilayah.replace('%20',' '), mux.replace('%20',' ')
    if request.method == 'POST':
        s = request.form['siaran']
        now = datetime.now(pytz.timezone('Asia/Jakarta'))
        ref.child(f"siaran/{p}/{w}/{m}").update({
            "siaran": sorted([x.strip() for x in s.split(',') if x.strip()]),
            "last_updated_date": now.strftime("%d-%m-%Y"),
            "last_updated_time": now.strftime("%H:%M:%S WIB")
        })
        return redirect(url_for('dashboard'))
    return render_template('edit_data_form.html', provinsi=p, wilayah=w, mux=m)

@app.route("/delete_data/<provinsi>/<wilayah>/<mux>", methods=["POST"])
def delete_data(provinsi, wilayah, mux):
    if 'user' in session: ref.child(f"siaran/{provinsi}/{wilayah}/{mux}").delete()
    return redirect(url_for('dashboard'))

@app.route("/get_wilayah")
def get_wilayah(): return jsonify({"wilayah": list((ref.child(f"siaran/{request.args.get('provinsi')}").get() or {}).keys())})
@app.route("/get_mux")
def get_mux(): return jsonify({"mux": list((ref.child(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}").get() or {}).keys())})
@app.route("/get_siaran")
def get_siaran():
    p, w, m = request.args.get("provinsi"), request.args.get("wilayah"), request.args.get("mux")
    return jsonify(ref.child(f"siaran/{p}/{w}/{m}").get() or {})

@app.route('/about')
def about(): return render_template('about.html')
@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))
@app.route('/sitemap.xml')
def sitemap(): return send_from_directory('static', 'sitemap.xml')

if __name__ == "__main__":
    app.run(debug=True)
