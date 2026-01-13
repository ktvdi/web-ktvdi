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
        
    # Cek apakah app sudah inisialisasi untuk mencegah double init di Vercel
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

genai.configure(api_key=os.environ.get("GEMINI_APP_KEY"))
model = genai.GenerativeModel("gemini-2.5-flash")

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

# --- FUNGSI BANTUAN DATA ---
def get_bmkg_weather():
    try:
        url = "https://data.bmkg.go.id/DataMKG/MEWS/DigitalForecast/DigitalForecast-DKIJakarta.xml"
        response = requests.get(url)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            weather_desc = []
            for area in root.findall(".//area[@description='Jakarta Pusat']"):
                for parameter in area.findall("parameter[@id='weather']"):
                    timerange = parameter.find("timerange")
                    value = timerange.find("value").text
                    weather_codes = {
                        "0": "Cerah", "1": "Cerah Berawan", "2": "Cerah Berawan", "3": "Berawan", 
                        "4": "Berawan Tebal", "5": "Udara Kabur", "10": "Asap", "45": "Kabut", 
                        "60": "Hujan Ringan", "61": "Hujan Sedang", "63": "Hujan Lebat", 
                        "80": "Hujan Petir", "95": "Hujan Petir", "97": "Hujan Petir"
                    }
                    cuaca = weather_codes.get(value, "Berawan")
                    weather_desc.append(f"Jakarta Pusat: {cuaca}")
                    break 
            return " | ".join(weather_desc) if weather_desc else "Cerah Berawan"
        return "Data Cuaca Tidak Tersedia"
    except: return "Gagal mengambil data BMKG"

def get_daily_news_summary():
    try:
        feed = feedparser.parse('https://news.google.com/rss?hl=id&gl=ID&ceid=ID:id')
        summary = ""
        for i, entry in enumerate(feed.entries[:5], 1):
            summary += f"{i}. {entry.title}\n   ({entry.link})\n\n"
        return summary
    except: return "Gagal memuat berita harian."

# --- ROUTE CRON JOB (Daily Blast) ---
@app.route("/api/cron/daily-blast", methods=['GET'])
def trigger_daily_blast():
    try:
        print(f"⏰ Memulai Blast Email Harian... {datetime.now()}")
        if not ref: return jsonify({"error": "Database not connected"}), 500
        
        users_data = ref.child('users').get()
        if not users_data: return jsonify({"status": "No users found"}), 200

        cuaca = get_bmkg_weather()
        berita = get_daily_news_summary()
        tanggal = datetime.now().strftime("%d %B %Y")
        
        count = 0
        for uid, user in users_data.items():
            email_dest = user.get('email')
            nama_user = user.get('nama', 'Sobat KTVDI')
            
            if email_dest:
                try:
                    msg = Message(f"📰 Informasi Harian KTVDI - {tanggal}", recipients=[email_dest])
                    msg.body = f"""Halo {nama_user},

Selamat malam! Berikut adalah rangkuman informasi harian khusus untuk anggota komunitas KTVDI.

🌤️ PRAKIRAAN CUACA HARI INI (BMKG):
{cuaca}

📰 BERITA PILIHAN HARI INI:
{berita}

Terus pantau siaran TV digital di daerahmu dan laporkan jika ada kendala sinyal di dashboard komunitas.

Salam Hangat,
Tim Komunitas TV Digital Indonesia
"""
                    mail.send(msg)
                    count += 1
                except Exception as e:
                    print(f"Gagal kirim ke {email_dest}: {e}")
        
        return jsonify({"status": "Success", "sent_count": count}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- ROUTES REGULER ---

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
    except: 
        return jsonify([])

@app.route('/', methods=['POST'])
def chatbot():
    data = request.get_json()
    try:
        res = model.generate_content(data.get("prompt"))
        return jsonify({"response": res.text})
    except: return jsonify({"error": "AI Busy"})

@app.route("/cctv")
def cctv_page(): return render_template("cctv.html")

@app.route("/jadwal-sholat")
def jadwal_sholat_page():
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

# --- REGISTER (EMAIL PROFESIONAL) ---
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
        
        ref.child(f'pending_users/{u}').set({
            "nama": n, "email": e, "password": hash_password(p), "otp": otp
        })
        
        try:
            msg = Message("Kode OTP Pendaftaran KTVDI", recipients=[e])
            # ISI EMAIL REGISTRASI PROFESIONAL
            msg.body = f"""Halo {n},

Perkenalkan, kami dari tim Komunitas TV Digital Indonesia (KTVDI).
Terima kasih telah bergabung bersama kami untuk mewujudkan penyiaran digital yang merata.

Berikut adalah kode OTP untuk menyelesaikan pendaftaran akun Anda:
{otp}

Mohon hati-hati, JANGAN berikan kode ini kepada siapapun (termasuk admin).
Kode OTP ini berlaku selama 1 menit.

Salam hangat,
Tim Admin KTVDI
"""
            mail.send(msg)
            session['pending_username'] = u
            return redirect(url_for("verify_register"))
        except Exception as error:
            print(f"EMAIL ERROR: {error}")
            flash(f"Gagal kirim email: {error}", "error")
            
    return render_template("register.html")

# --- VERIFIKASI (FIX ERROR 500) ---
@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    u = session.get('pending_username')
    if not u: return redirect(url_for('register'))
    
    if request.method == "POST":
        try:
            p = ref.child(f'pending_users/{u}').get()
            if not p:
                flash("Sesi habis, silakan daftar ulang.", "error")
                return redirect(url_for('register'))

            if str(p['otp']) == request.form.get("otp"):
                # 1. Simpan User Resmi (CRITICAL STEP)
                ref.child(f'users/{u}').set({
                    "nama":p['nama'], 
                    "email":p['email'], 
                    "password":p['password'], 
                    "points":0
                })
                # 2. Hapus data pending
                ref.child(f'pending_users/{u}').delete()
                session.pop('pending_username', None)
                
                # 3. KIRIM EMAIL SAMBUTAN (DALAM TRY-EXCEPT AGAR TIDAK BIKIN ERROR 500)
                try:
                    msg = Message("Selamat Datang! Anda Resmi Menjadi Anggota KTVDI", recipients=[p['email']])
                    msg.body = f"""Halo {p['nama']},

Selamat! Akun Anda telah berhasil diverifikasi.
Sekarang Anda sudah TERDAFTAR RESMI sebagai anggota keluarga besar Komunitas TV Digital Indonesia (KTVDI).

Dengan akun ini, Anda dapat:
- Mengakses Dashboard Kontributor
- Melaporkan status sinyal MUX
- Berdiskusi di forum komunitas

Jangan lupa untuk selalu menjaga kerahasiaan akun Anda.

Salam hangat,
Tim Admin KTVDI
"""
                    mail.send(msg)
                except Exception as e:
                    # Log error tapi JANGAN return error page, karena user sudah sukses register
                    print(f"⚠️ Gagal kirim email sambutan (User tetap terdaftar): {e}")

                flash("Registrasi Berhasil! Silakan Login.", "success")
                return redirect(url_for('login'))
            
            else:
                flash("Kode OTP Salah!", "error")
        
        except Exception as e:
            print(f"❌ Error Verifikasi: {e}")
            flash("Terjadi kesalahan sistem saat verifikasi.", "error")
        
    return render_template("verify-register.html", username=u)

# --- LUPA PASSWORD (EMAIL PROFESIONAL & REMINDER) ---
@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email_input = request.form.get("email")
        
        target_user = None
        target_name = "Sobat KTVDI"
        all_users = ref.child('users').get()
        
        if all_users:
            for uid, data in all_users.items():
                if data.get('email') == email_input:
                    target_user = uid
                    target_name = data.get('nama', 'Sobat KTVDI')
                    break
        
        if not target_user:
            flash("Email tidak ditemukan.", "error")
            return render_template("forgot-password.html")
            
        otp = str(random.randint(100000, 999999))
        session['reset_user'] = target_user
        session['reset_name'] = target_name
        session['reset_email'] = email_input
        session['reset_otp'] = otp
        
        try:
            msg = Message("Reset Password Akun KTVDI", recipients=[email_input])
            # ISI EMAIL LUPA PASSWORD
            msg.body = f"""Halo {target_name},

Perkenalkan, kami dari tim Komunitas TV Digital Indonesia (KTVDI).
Kami menerima permintaan untuk mereset kata sandi akun Anda.

Berikut adalah kode OTP untuk melanjutkan proses reset password:
{otp}

Mohon hati-hati, JANGAN berikan kode ini kepada siapapun.
Kode OTP ini berlaku selama 1 menit.

Jika Anda tidak merasa melakukan permintaan ini, silakan abaikan email ini.

Salam hangat,
Tim Admin KTVDI
"""
            mail.send(msg)
            return redirect(url_for('verify_reset'))
        except Exception as e:
            print(f"EMAIL ERROR: {e}")
            flash("Gagal mengirim email.", "error")
            
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
        conf_pass = request.form.get("confirm_password")
        
        if new_pass == conf_pass:
            uid = session['reset_user']
            nama = session.get('reset_name', 'Sobat KTVDI')
            email = session.get('reset_email')
            
            ref.child(f'users/{uid}').update({"password": hash_password(new_pass)})
            
            # EMAIL PENGINGAT AKUN (SAFE MODE)
            if email:
                try:
                    msg = Message("Password Berhasil Diubah - Ingat Akun Anda!", recipients=[email])
                    msg.body = f"""Halo {nama},

Password akun KTVDI Anda telah berhasil diperbarui.

MOHON DIINGAT:
Username Anda: {uid}

Pastikan Anda mencatat atau mengingat kredensial ini agar tidak kehilangan akses ke komunitas di masa mendatang.
Jika Anda tidak melakukan perubahan ini, segera hubungi admin.

Salam aman,
Tim Security KTVDI
"""
                    mail.send(msg)
                except Exception as e:
                    print(f"Gagal kirim reminder: {e}")

            session.pop('reset_user', None)
            session.pop('reset_otp', None)
            session.pop('reset_verified', None)
            session.pop('reset_name', None)
            session.pop('reset_email', None)
            
            flash("Password berhasil diubah. Silakan login.", "success")
            return redirect(url_for('login'))
        flash("Password tidak sama.", "error")
        
    return render_template("reset_password.html")

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
