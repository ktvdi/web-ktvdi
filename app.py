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
    print("⚠️ API Key Gemini belum disetting di Vercel!")

# --- SYSTEM PROMPT CHATBOT ---
MODI_PROMPT = """
Kamu adalah MODI, Customer Service & Asisten Virtual dari Komunitas TV Digital Indonesia (KTVDI).
Karaktermu:
1. SANGAT RAMAH, CERIA, dan SUPORTIF. Anggap pengguna adalah teman dekat.
2. Selalu gunakan sapaan "Kak", "Sobat", atau "Bestie".
3. WAJIB menggunakan emoji di setiap kalimat.
4. Jawab pertanyaan seputar TV Digital, STB, Antena, dan Sinyal dengan solusi teknis yang mudah dipahami.
5. Jika ditanya selain topik TV Digital, jawab dengan sopan bahwa kamu hanya ahli di bidang TV Digital.
6. Selalu akhiri chat dengan menawarkan bantuan lagi.
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
                            weather_codes = {"0": "Cerah ☀️", "1": "Cerah Berawan 🌤️", "3": "Berawan ☁️", "60": "Hujan 🌧️", "61": "Hujan 🌧️"}
                            return f"Jakarta Pusat: {weather_codes.get(value, 'Berawan ☁️')}"
            return "Cerah Berawan 🌤️"
        return "Data Cuaca Tidak Tersedia"
    except: return "Cerah Berawan 🌤️"

def get_daily_news_summary_ai():
    try:
        feed = feedparser.parse('https://news.google.com/rss?hl=id&gl=ID&ceid=ID:id')
        titles = [entry.title for entry in feed.entries[:5]]
        text_data = "\n".join(titles)
        if model:
            prompt = f"Buatlah rangkuman berita harian singkat (3 poin) yang santai tentang teknologi/indonesia dari judul ini:\n{text_data}"
            response = model.generate_content(prompt)
            return response.text if response.text else "Gagal merangkum berita."
        return "Silakan cek halaman berita untuk update terbaru."
    except: return "Gagal memuat berita harian."

def get_daily_tips():
    tips = [
        "Jaga etika berkomentar di sosial media, jarimu harimaumu.",
        "Istirahatkan mata setelah 2 jam menonton TV.",
        "Pastikan kabel STB tidak tertekuk agar awet.",
        "Bersikap jujur adalah mata uang yang berlaku di mana saja.",
        "Saling membantu sesama anggota komunitas mempererat persaudaraan."
    ]
    return random.choice(tips)

# --- ROUTE CRON JOB (BLAST HARIAN - JAM 19.00) ---
@app.route("/api/cron/daily-blast", methods=['GET'])
def trigger_daily_blast():
    try:
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
                    msg = Message(f"🌙 Buletin Malam KTVDI - {tanggal}", recipients=[email_dest])
                    msg.body = f"""Selamat Malam Kak {nama_user},

Semoga hari ini menyenangkan dan penuh berkah. KTVDI hadir menemani istirahat malammu.

🌤️ **Info Cuaca Besok:**
{cuaca}

📰 **Sekilas Berita Hari Ini:**
{berita_ai}

💡 **Renungan & Tips Harian:**
"{tips}"
Mari kita jaga pola hidup sehat, istirahat cukup, dan selalu menjunjung tinggi etika dalam bermasyarakat.

📺 **Info Komunitas:**
Jangan lupa cek sinyal MUX di daerahmu. Jika ada kendala, segera lapor di grup ya!

Selamat beristirahat.

Hormat kami,
**Pengurus Pusat KTVDI**
Komunitas TV Digital Indonesia
"""
                    mail.send(msg)
                    count += 1
                except Exception as e:
                    print(f"Gagal kirim ke {email_dest}: {e}")
        
        return jsonify({"status": "Success", "sent_count": count}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- CHATBOT HANDLER (PERBAIKAN KONEKSI AI) ---
@app.route('/', methods=['POST'])
def chatbot():
    # 1. Cek Model
    if not model:
        return jsonify({"response": "Maaf Kak, sistem Modi sedang dalam pemeliharaan server. Mohon hubungi admin untuk cek API Key. 🙏"})

    data = request.get_json()
    user_msg = data.get("prompt")
    
    if not user_msg:
        return jsonify({"response": "Maaf Kak, Modi tidak mendengar. Bisa ketik ulang pesan Kakak? 👂"})

    try:
        # 2. Generate
        full_prompt = f"{MODI_PROMPT}\n\nUser: {user_msg}\nModi:"
        response = model.generate_content(full_prompt)
        reply = response.text
        
        if not reply:
            reply = "Waduh, sinyal Modi putus-putus nih. Coba tanya lagi ya Kak? 😅"
            
        return jsonify({"response": reply})
    except Exception as e:
        print(f"AI Error: {e}")
        return jsonify({"response": "Maaf Kak, server Modi lagi penuh banget. Coba beberapa detik lagi ya! 🙏"})

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
                news_list.append(parts[0])
            else:
                news_list.append(title)
        return jsonify(news_list)
    except: return jsonify([])

@app.route("/cctv")
def cctv_page(): return render_template("cctv.html")

# --- ROUTE SHOLAT DENGAN EMAIL REMINDER ---
@app.route("/jadwal-sholat")
def jadwal_sholat_page():
    # Kirim Email Pengingat (Hanya jika login & belum dikirim sesi ini)
    if 'user' in session and not session.get('sholat_reminder_sent'):
        user_id = session['user']
        user_data = ref.child(f'users/{user_id}').get() if ref else None
        
        if user_data and user_data.get('email'):
            try:
                nama = user_data.get('nama', 'Sobat')
                email_dest = user_data.get('email')
                
                msg = Message("🕋 Pengingat Ibadah & Pesan Moral - KTVDI", recipients=[email_dest])
                msg.body = f"""Assalamualaikum Wr. Wb. / Salam Sejahtera {nama},

Terima kasih telah mengakses fitur Jadwal Sholat KTVDI.

🕌 **PESAN KHUSUS (Disclaimer: Untuk yang Beragama Islam):**
"Jadikanlah sabar dan sholat sebagai penolongmu."
Saudaraku, mari kita jaga sholat 5 waktu tepat pada waktunya. 
Hindari perbuatan maksiat, jauhi dunia gemerlap (dugem) yang merugikan, serta tanamkan sifat JUJUR dan ANTI-KORUPSI dalam setiap pekerjaan kita. 
Integritas adalah kunci keberkahan hidup.

🤝 **PESAN UNTUK SEMUA (Lintas Agama):**
Bagi saudara-saudaraku yang beragama lain, mari kita senantiasa menebar kebaikan, menjaga toleransi, dan menjadi pribadi yang bermanfaat bagi bangsa dan negara.

Semoga Tuhan Yang Maha Esa selalu melindungi kita semua.

Salam Persaudaraan,
**Komunitas TV Digital Indonesia**
"""
                mail.send(msg)
                session['sholat_reminder_sent'] = True # Tandai sudah kirim agar tidak spam
            except Exception as e:
                print(f"Gagal kirim email sholat: {e}")

    daftar_kota = ["Jakarta", "Surabaya", "Bandung", "Semarang", "Yogyakarta", "Medan", "Makassar", "Denpasar", "Palembang", "Pekalongan"]
    return render_template("jadwal-sholat.html", daftar_kota=sorted(daftar_kota))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user, pw = request.form.get('username'), hash_password(request.form.get('password'))
        u = ref.child(f'users/{user}').get() if ref else None
        if u and u.get('password') == pw:
            session['user'], session['nama'] = user, u.get('nama')
            session.pop('sholat_reminder_sent', None) # Reset status email sholat saat login baru
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
            msg = Message("Verifikasi Pendaftaran KTVDI", recipients=[e])
            msg.body = f"""Yth. {n},

Selamat datang di keluarga besar Komunitas TV Digital Indonesia (KTVDI).
Kami senang Anda bergabung bersama kami.

Berikut adalah KODE OTP Anda:
== {otp} ==

⚠️ PENTING:
1. Kode ini hanya berlaku selama 1 MENIT.
2. JANGAN BERIKAN kode ini kepada siapapun (termasuk admin).
3. Jagalah kerahasiaan akun Anda.

Silakan masukkan kode tersebut di halaman verifikasi.

Hormat kami,
Tim Admin KTVDI
"""
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
            
            # Email Sambutan
            try:
                msg = Message("Selamat Datang Resmi di KTVDI!", recipients=[p['email']])
                msg.body = f"""Halo {p['nama']},

Selamat! Akun KTVDI Anda telah aktif.
Terima kasih telah menjadi bagian dari revolusi penyiaran digital Indonesia.

Anda kini dapat mengakses seluruh fitur komunitas. Mari berkontribusi untuk penyiaran yang lebih baik.

Salam,
Ketua KTVDI
"""
                mail.send(msg)
            except: pass

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
                    target_name = data.get('nama', 'User')
                    break
        if not target_user:
            flash("Email tidak ditemukan.", "error")
            return render_template("forgot-password.html")
        
        otp = str(random.randint(100000, 999999))
        session['reset_user'] = target_user
        session['reset_email'] = email_input
        session['reset_otp'] = otp
        
        try:
            msg = Message("Permintaan Reset Password - KTVDI", recipients=[email_input])
            msg.body = f"""Yth. {target_name},

Kami menerima permintaan untuk mereset kata sandi akun KTVDI Anda.

KODE OTP: {otp}

⚠️ PERHATIAN:
- Kode ini hanya berlaku 1 MENIT.
- Jika Anda tidak merasa melakukan permintaan ini, mohon abaikan email ini dan amankan akun Anda segera.
- KTVDI tidak pernah meminta OTP Anda.

Salam aman,
Tim Keamanan IT KTVDI
"""
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
            email = session.get('reset_email')
            ref.child(f'users/{uid}').update({"password": hash_password(new_pass)})
            
            # Email Peringatan Sukses
            try:
                msg = Message("Password Berhasil Diubah - Penting!", recipients=[email])
                msg.body = f"""Halo,

Password akun KTVDI Anda baru saja diubah.

PENTING:
Mohon ingat password baru Anda dan email yang terdaftar.
Jika Anda lupa email atau kehilangan akses ke email ini, maka STATUS KEANGGOTAAN KTVDI ANDA AKAN HILANG PERMANEN dan tidak dapat dipulihkan.

Mohon jaga kredensial Anda dengan baik.

Salam,
Admin KTVDI
"""
                mail.send(msg)
            except: pass

            session.clear()
            flash("Password berhasil diubah.", "success")
            return redirect(url_for('login'))
        flash("Password tidak sama.", "error")
    return render_template("reset_password.html")

@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    return render_template("dashboard.html", name=session.get('nama'), provinsi_list=list((ref.child('provinsi').get() or {}).values()))

@app.route("/daftar-siaran")
def daftar_siaran(): return render_template("daftar-siaran.html", provinsi_list=list((ref.child('provinsi').get() or {}).values()))

# --- CRUD (Add, Edit, Delete) ---
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
