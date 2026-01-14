import os
import hashlib
import firebase_admin
import random
import feedparser
import requests
import xml.etree.ElementTree as ET
import google.generativeai as genai
from firebase_admin import credentials, db
from flask import Flask, request, render_template, redirect, url_for, session, flash, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
from flask_mail import Mail, Message
from datetime import datetime

load_dotenv()

app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

# --- KONEKSI FIREBASE ---
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

# --- KONFIGURASI EMAIL ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME") 
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD") 
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")
mail = Mail(app)

# --- KONFIGURASI AI (MODI) ---
api_key = os.environ.get("GEMINI_APP_KEY")
if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")
else:
    model = None

# --- SYSTEM PROMPT (AGAR RAMAH & MANUSIAWI) ---
MODI_PROMPT = """
Kamu adalah MODI, Customer Service & Asisten Virtual dari Komunitas TV Digital Indonesia (KTVDI).
Karaktermu:
1. SANGAT RAMAH, CERIA, dan SUPORTIF. Anggap pengguna adalah teman dekat.
2. Selalu gunakan sapaan "Kak", "Sobat", atau "Bestie".
3. WAJIB menggunakan emoji di setiap kalimat agar tidak kaku (contoh: 😊, 👋, 📺, ✨).
4. Jika user bertanya, jawab dengan ringkas tapi solutif.
5. Jika user menyapa (Halo/Hi), sapa balik dengan antusias.
6. Di akhir jawaban, SELALU tawarkan bantuan lagi (Contoh: "Ada lagi yang bisa Modi bantu, Kak?").
7. Topikmu seputar: TV Digital, STB, Antena, Sinyal Hilang, dan Info Komunitas.
8. Jangan terlalu kaku/baku seperti robot.
"""

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

# --- FUNGSI BANTUAN CUACA & BERITA ---
def get_bmkg_weather():
    try:
        url = "https://data.bmkg.go.id/DataMKG/MEWS/DigitalForecast/DigitalForecast-DKIJakarta.xml"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            for area in root.findall(".//area[@description='Jakarta Pusat']"):
                for parameter in area.findall("parameter[@id='weather']"):
                    timerange = parameter.find("timerange")
                    if timerange is not None:
                        val_elem = timerange.find("value")
                        if val_elem is not None:
                            value = val_elem.text
                            weather_codes = {
                                "0": "Cerah ☀️", "1": "Cerah Berawan 🌤️", "2": "Cerah Berawan 🌤️", 
                                "3": "Berawan ☁️", "4": "Berawan Tebal ☁️", "5": "Udara Kabur 🌫️", 
                                "60": "Hujan Ringan 🌧️", "61": "Hujan Sedang 🌧️", "63": "Hujan Lebat ⛈️", 
                                "80": "Hujan Petir ⛈️", "95": "Hujan Petir ⛈️"
                            }
                            cuaca = weather_codes.get(value, "Berawan ☁️")
                            return f"Jakarta Pusat: {cuaca}"
            return "Cerah Berawan 🌤️"
        return "Data Cuaca Tidak Tersedia"
    except Exception as e:
        return "Cerah Berawan 🌤️"

def get_daily_news_summary_ai():
    try:
        feed = feedparser.parse('https://news.google.com/rss?hl=id&gl=ID&ceid=ID:id')
        titles = [entry.title for entry in feed.entries[:5]]
        text_data = "\n".join(titles)
        if model:
            prompt = f"Buatlah rangkuman berita harian singkat (3 poin) yang santai untuk newsletter komunitas TV Digital dari judul-judul berikut:\n{text_data}"
            response = model.generate_content(prompt)
            return response.text if response.text else "Gagal merangkum berita."
        return "Silakan cek halaman berita untuk update terbaru."
    except: return "Gagal memuat berita harian."

def get_daily_tips():
    tips = [
        "Pastikan antena TV mengarah tepat ke pemancar (MUX) terdekat untuk sinyal maksimal 📡.",
        "Gunakan kabel koaksial RG6 berkualitas tinggi agar sinyal tidak bocor 🔌.",
        "Lakukan pencarian ulang (scan) STB secara berkala untuk mendapatkan channel baru 📺.",
        "Jaga kebersihan remote TV dan STB agar tombol tetap responsif ✨.",
        "Matikan STB saat tidak ditonton untuk menghemat listrik dan menjaga keawetan alat ⚡."
    ]
    return random.choice(tips)

# --- ROUTE CRON JOB (BLAST HARIAN) ---
@app.route("/api/cron/daily-blast", methods=['GET'])
def trigger_daily_blast():
    try:
        print(f"⏰ Memulai Blast Email Harian... {datetime.now()}")
        if not ref: return jsonify({"error": "Database not connected"}), 500
        
        users_data = ref.child('users').get()
        if not users_data: return jsonify({"status": "No users found"}), 200

        cuaca = get_bmkg_weather()
        berita_ai = get_daily_news_summary_ai()
        tips = get_daily_tips()
        tanggal = datetime.now().strftime("%d %B %Y")
        
        count = 0
        for uid, user in users_data.items():
            email_dest = user.get('email')
            nama_user = user.get('nama', 'Sobat KTVDI')
            
            if email_dest:
                try:
                    msg = Message(f"📰 Kabar Harian KTVDI - {tanggal}", recipients=[email_dest])
                    msg.body = f"""Halo Kak {nama_user}! 👋

Apa kabar hari ini? Semoga sehat selalu ya.
Berikut update informasi harian spesial untuk Kakak dari KTVDI:

🌤️ PRAKIRAAN CUACA HARI INI
{cuaca}
*Tetap jaga kesehatan ya Kak!*

📰 RANGKUMAN BERITA TERKINI
{berita_ai}

💡 TIPS DIGITAL HARI INI
{tips}

Jangan lupa cek dashboard KTVDI untuk update status sinyal terbaru.
Selamat beristirahat dan menikmati tayangan TV Digital yang jernih!

Salam hangat,
Modi & Tim KTVDI
Komunitas TV Digital Indonesia
"""
                    mail.send(msg)
                    count += 1
                except Exception as e:
                    print(f"Gagal kirim ke {email_dest}: {e}")
        
        return jsonify({"status": "Success", "sent_count": count}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- CHATBOT HANDLER (API) ---
@app.route('/', methods=['POST'])
def chatbot():
    if not model:
        return jsonify({"response": "Maaf Kak, Modi lagi perbaikan sistem nih. Hubungi admin ya! 🙏"})

    data = request.get_json()
    user_msg = data.get("prompt")
    
    if not user_msg:
        return jsonify({"response": "Maaf Kak, Modi tidak mendengar pesan Kakak. Bisa diulangi? 👂"})

    try:
        full_prompt = f"{MODI_PROMPT}\n\nUser: {user_msg}\nModi:"
        res = model.generate_content(full_prompt)
        reply = res.text
        if not reply: reply = "Waduh, Modi lagi loading nih Kak. Tanya lagi ya? 😅"
        return jsonify({"response": reply})
    except Exception as e:
        print(f"AI Error: {e}")
        return jsonify({"response": "Maaf Kak, server Modi lagi sibuk banget nih. Coba beberapa saat lagi ya 🙏"})

# --- ROUTES UTAMA ---
@app.route("/")
def home():
    siaran_data = ref.child('siaran').get() if ref else {}
    stats = {'wilayah': 0, 'mux': 0, 'channel': 0}
    if siaran_data:
        for prov in siaran_data.values():
            if isinstance(prov, dict):
                stats['wilayah'] += len(prov)
                for wil in prov.values():
                    if isinstance(wil, dict):
                        stats['mux'] += len(wil)
                        for mux in wil.values():
                            if 'siaran' in mux: stats['channel'] += len(mux['siaran'])
    return render_template('index.html', stats=stats)

@app.route("/api/news-ticker")
def news_ticker():
    try:
        feed = feedparser.parse('https://news.google.com/rss?hl=id&gl=ID&ceid=ID:id')
        news_list = []
        for entry in feed.entries[:15]:
            title = entry.title
            if ' - ' in title:
                parts = title.rsplit(' - ', 1)
                judul = parts[0]
                sumber = parts[1]
                clean_title = f"<span class='text-brand-blue font-black'>[{sumber}]</span> {judul}"
                news_list.append(clean_title)
            else:
                news_list.append(title)
        return jsonify(news_list)
    except: return jsonify([])

@app.route("/cctv")
def cctv_page(): return render_template("cctv.html")

@app.route("/jadwal-sholat")
def jadwal_sholat_page():
    # LIST KOTA LENGKAP DIKEMBALIKAN
    daftar_kota = [
        "Jakarta", "Surabaya", "Bandung", "Semarang", "Medan", "Makassar", 
        "Palembang", "Bekasi", "Tangerang", "Depok", "Pekalongan", "Grobogan", 
        "Malang", "Surakarta", "Yogyakarta", "Denpasar", "Balikpapan", 
        "Samarinda", "Banda Aceh", "Banjarmasin", "Bandar Lampung", "Pontianak", 
        "Manado", "Jayapura", "Kupang", "Mataram", "Padang", "Tegal", "Bogor", 
        "Sidoarjo", "Cirebon", "Demak", "Ambon", "Gorontalo", "Palu", "Kendari", 
        "Jambi", "Bengkulu", "Serang", "Mamuju", "Palangkaraya", "Ternate", 
        "Sorong", "Tasikmalaya", "Cimahi", "Magelang", "Salatiga", "Batu", 
        "Kediri", "Madiun"
    ]
    return render_template("jadwal-sholat.html", daftar_kota=sorted(daftar_kota))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user, pw = request.form.get('username'), hash_password(request.form.get('password'))
        u = ref.child(f'users/{user}').get() if ref else None
        if u and u.get('password') == pw:
            session['user'], session['nama'] = user, u.get('nama')
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
        if ref.child(f'users/{u}').get():
            flash("Username sudah digunakan", "error")
            return render_template("register.html")
        otp = str(random.randint(100000, 999999))
        ref.child(f'pending_users/{u}').set({"nama": n, "email": e, "password": hash_password(p), "otp": otp})
        try:
            msg = Message("Kode OTP Pendaftaran KTVDI", recipients=[e])
            msg.body = f"Halo {n}, Kode OTP Anda: {otp}"
            mail.send(msg)
            session['pending_username'] = u
            return redirect(url_for("verify_register"))
        except: flash("Gagal kirim email", "error")
    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    u = session.get('pending_username')
    if not u: return redirect(url_for('register'))
    if request.method == "POST":
        p = ref.child(f'pending_users/{u}').get()
        if p and str(p['otp']) == request.form.get("otp"):
            ref.child(f'users/{u}').set({"nama":p['nama'], "email":p['email'], "password":p['password'], "points":0})
            ref.child(f'pending_users/{u}').delete()
            session.pop('pending_username', None)
            flash("Registrasi Berhasil!", "success")
            return redirect(url_for('login'))
        flash("OTP Salah!", "error")
    return render_template("verify-register.html", username=u)

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email_input = request.form.get("email")
        target_user = None
        all_users = ref.child('users').get()
        if all_users:
            for uid, data in all_users.items():
                if data.get('email') == email_input:
                    target_user = uid
                    break
        if not target_user:
            flash("Email tidak ditemukan.", "error")
            return render_template("forgot-password.html")
        otp = str(random.randint(100000, 999999))
        session['reset_user'] = target_user
        session['reset_email'] = email_input
        session['reset_otp'] = otp
        try:
            msg = Message("Reset Password", recipients=[email_input])
            msg.body = f"Kode OTP: {otp}"
            mail.send(msg)
            return redirect(url_for('verify_reset'))
        except: flash("Gagal kirim email", "error")
    return render_template("forgot-password.html")

@app.route("/verify-reset", methods=["GET", "POST"])
def verify_reset():
    if 'reset_user' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        if request.form.get('otp') == session.get('reset_otp'):
            session['reset_verified'] = True
            return redirect(url_for('reset_password'))
        flash("OTP Salah", "error")
    return render_template("verify_reset.html")

@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    if not session.get('reset_verified'): return redirect(url_for('login'))
    if request.method == "POST":
        new_pass = request.form.get("password")
        if new_pass == request.form.get("confirm_password"):
            uid = session['reset_user']
            ref.child(f'users/{uid}').update({"password": hash_password(new_pass)})
            session.clear()
            flash("Password berhasil diubah.", "success")
            return redirect(url_for('login'))
        flash("Password tidak sama.", "error")
    return render_template("reset_password.html")

# --- CRUD DASHBOARD (LENGKAP) ---
@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    return render_template("dashboard.html", name=session.get('nama'), provinsi_list=list((ref.child('provinsi').get() or {}).values()))

@app.route("/daftar-siaran")
def daftar_siaran(): return render_template("daftar-siaran.html", provinsi_list=list((ref.child('provinsi').get() or {}).values()))

@app.route("/add_data", methods=["GET", "POST"])
def add_data():
    if 'user' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        p, w, m, s = request.form['provinsi'], request.form['wilayah'].replace(' ', ''), request.form['mux'], request.form['siaran']
        sl = sorted([x.strip() for x in s.split(',') if x.strip()])
        ref.child(f'siaran/{p}/{w}/{m}').set({"siaran": sl, "last_updated_by": session['user'], "last_updated_date": datetime.now().strftime("%d-%m-%Y")})
        return redirect(url_for('dashboard'))
    return render_template('add_data_form.html', provinsi_list=list((ref.child('provinsi').get() or {}).values()))

@app.route("/edit_data/<provinsi>/<wilayah>/<mux>", methods=["GET", "POST"])
def edit_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        sl = sorted([x.strip() for x in request.form['siaran'].split(',') if x.strip()])
        ref.child(f'siaran/{provinsi}/{wilayah}/{mux}').update({"siaran": sl, "last_updated_date": datetime.now().strftime("%d-%m-%Y")})
        return redirect(url_for('dashboard'))
    return render_template('edit_data_form.html', provinsi=provinsi, wilayah=wilayah, mux=mux)

@app.route("/delete_data/<provinsi>/<wilayah>/<mux>", methods=["POST"])
def delete_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    ref.child(f'siaran/{provinsi}/{wilayah}/{mux}').delete()
    return redirect(url_for('dashboard'))

@app.route("/get_wilayah")
def get_wilayah(): return jsonify({"wilayah": list((ref.child(f"siaran/{request.args.get('provinsi')}").get() or {}).keys())})
@app.route("/get_mux")
def get_mux(): return jsonify({"mux": list((ref.child(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}").get() or {}).keys())})
@app.route("/get_siaran")
def get_siaran(): return jsonify(ref.child(f"siaran/{request.args.get('provinsi')}/{request.args.get('wilayah')}/{request.args.get('mux')}").get() or {})

@app.route('/berita')
def berita():
    feed = feedparser.parse('https://news.google.com/rss?hl=id&gl=ID&ceid=ID:id')
    articles = feed.entries
    page = request.args.get('page', 1, type=int)
    per_page = 6
    start = (page - 1) * per_page
    end = start + per_page
    current = articles[start:end]
    for a in current: 
        if hasattr(a,'published_parsed'): a.time_since_published = time_since_published(a.published_parsed)
    return render_template('berita.html', articles=current, page=page, total_pages=(len(articles)//per_page)+1)

@app.route('/about')
def about(): return render_template('about.html')
@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))
@app.route('/sitemap.xml')
def sitemap(): return send_from_directory('static', 'sitemap.xml')

if __name__ == "__main__":
    app.run(debug=True)
