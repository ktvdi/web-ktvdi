import os
import hashlib
import random
import re
import pytz
import feedparser
import google.generativeai as genai
from datetime import datetime
from collections import Counter

# Flask & Firebase Imports
import firebase_admin
from firebase_admin import credentials, db
from flask import Flask, request, render_template, redirect, url_for, session, flash, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
from flask_mail import Mail, Message

# 1. KONFIGURASI AWAL
# ==============================================================================
load_dotenv() # Wajib ada file .env

app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-123")

# Variabel Global untuk status Firebase
firebase_connected = False

# --- Inisialisasi Firebase ---
try:
    # Cek apakah variabel env ada
    if os.environ.get("FIREBASE_PROJECT_ID"):
        private_key = os.environ.get("FIREBASE_PRIVATE_KEY")
        if private_key:
            private_key = private_key.replace('\\n', '\n')

        cred = credentials.Certificate({
            "type": "service_account",
            "project_id": os.environ.get("FIREBASE_PROJECT_ID"),
            "private_key_id": os.environ.get("FIREBASE_PRIVATE_KEY_ID"),
            "private_key": private_key,
            "client_email": os.environ.get("FIREBASE_CLIENT_EMAIL"),
            "client_id": os.environ.get("FIREBASE_CLIENT_ID"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": os.environ.get("FIREBASE_CLIENT_X509_CERT_URL"),
            "universe_domain": "googleapis.com"
        })

        firebase_admin.initialize_app(cred, {
            'databaseURL': os.environ.get('DATABASE_URL')
        })
        
        firebase_connected = True
        print("✅ Firebase berhasil terhubung!")
    else:
        print("⚠️ Warning: FIREBASE_PROJECT_ID tidak ditemukan di .env. Aplikasi berjalan dalam mode offline/terbatas.")

except Exception as e:
    print(f"❌ Gagal inisialisasi Firebase: {str(e)}")
    firebase_connected = False

# --- Inisialisasi Email ---
app.config['MAIL_SERVER'] = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
app.config['MAIL_PORT'] = int(os.environ.get("MAIL_PORT", 587))
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD")
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")

mail = Mail(app)

# --- Konfigurasi Gemini AI ---
gemini_key = os.environ.get("GEMINI_APP_KEY")
if gemini_key:
    genai.configure(api_key=gemini_key)
    model = genai.GenerativeModel(
        "gemini-2.5-flash", 
        system_instruction="Anda adalah Chatbot AI KTVDI..." 
    )
else:
    model = None
    print("⚠️ Warning: GEMINI_APP_KEY tidak ditemukan.")

# 2. FUNGSI BANTUAN (HELPER)
# ==============================================================================
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def time_since_published(published_time):
    now = datetime.now()
    try:
        publish_time = datetime(*published_time[:6])
        delta = now - publish_time
        
        if delta.days >= 1:
            return "1 hari yang lalu" if delta.days == 1 else f"{delta.days} hari yang lalu"
        if delta.seconds >= 3600:
            return f"{delta.seconds // 3600} jam yang lalu"
        if delta.seconds >= 60:
            return f"{delta.seconds // 60} menit yang lalu"
        return "Baru saja"
    except:
        return "-"

# 3. ROUTES UTAMA
# ==============================================================================

@app.route("/")
def home():
    # Default values (Agar tidak error 500 jika data kosong)
    jumlah_wilayah = 0
    jumlah_siaran = 0
    jumlah_mux = 0
    top_siaran_name = "-"
    top_siaran_count = 0
    last_update_str = "-"

    if firebase_connected:
        try:
            ref = db.reference('siaran')
            siaran_data = ref.get()
            
            if siaran_data:
                siaran_counts = Counter()
                last_updated_time = None

                if isinstance(siaran_data, dict):
                    for provinsi, prov_data in siaran_data.items():
                        if isinstance(prov_data, dict):
                            jumlah_wilayah += len(prov_data)
                            for wilayah, wil_data in prov_data.items():
                                if isinstance(wil_data, dict):
                                    jumlah_mux += len(wil_data)
                                    for mux, mux_details in wil_data.items():
                                        # Hitung siaran
                                        siaran_list = mux_details.get('siaran', [])
                                        if siaran_list:
                                            jumlah_siaran += len(siaran_list)
                                            for s in siaran_list:
                                                siaran_counts[s.lower()] += 1
                                        
                                        # Cek last update
                                        updated_str = mux_details.get('last_updated_date')
                                        if updated_str:
                                            try:
                                                curr_time = datetime.strptime(updated_str, '%d-%m-%Y')
                                                if last_updated_time is None or curr_time > last_updated_time:
                                                    last_updated_time = curr_time
                                            except: pass

                # Statistik top siaran
                if siaran_counts:
                    top = siaran_counts.most_common(1)[0]
                    top_siaran_name = top[0].upper()
                    top_siaran_count = top[1]

                if last_updated_time:
                    last_update_str = last_updated_time.strftime('%d-%m-%Y')

        except Exception as e:
            print(f"Error reading Firebase in Home: {e}")

    return render_template('home.html', 
        most_common_siaran_name=top_siaran_name,
        most_common_siaran_count=top_siaran_count,
        jumlah_wilayah_layanan=jumlah_wilayah,
        jumlah_siaran=jumlah_siaran, 
        jumlah_penyelenggara_mux=jumlah_mux, 
        last_updated_time=last_update_str
    )

@app.route('/', methods=['POST'])
def chatbot():
    data = request.get_json()
    prompt = data.get("prompt")
    
    if not model:
        return jsonify({"response": "Maaf, fitur AI sedang tidak tersedia (API Key missing)."})

    try:
        response = model.generate_content(prompt)
        return jsonify({"response": response.text})
    except Exception as e:
        return jsonify({"error": "Maaf, saya sedang sibuk. Coba lagi nanti."})

@app.route("/daftar-siaran")
def daftar_siaran():
    provinsi_list = []
    if firebase_connected:
        try:
            ref = db.reference("provinsi")
            data = ref.get()
            if data:
                if isinstance(data, list):
                    provinsi_list = [p for p in data if p]
                elif isinstance(data, dict):
                    provinsi_list = list(data.values())
            provinsi_list.sort()
        except:
            pass
    
    return render_template("daftar-siaran.html", provinsi_list=provinsi_list)

@app.route('/berita')
def berita():
    try:
        rss_url = 'https://news.google.com/rss/search?q=tv+digital&hl=id&gl=ID&ceid=ID:id'
        feed = feedparser.parse(rss_url)
        articles = feed.entries
    except:
        articles = []
    
    per_page = 6
    page = request.args.get('page', 1, type=int)
    total = len(articles)
    
    # Mencegah error pagination jika articles kosong
    if total == 0:
        return render_template('berita.html', articles=[], page=1, total_pages=1)

    start = (page - 1) * per_page
    end = start + per_page
    current_articles = articles[start:end]
    total_pages = (total + per_page - 1) // per_page

    for art in current_articles:
        if 'published_parsed' in art:
            art.time_since_published = time_since_published(art.published_parsed)
    
    return render_template('berita.html', articles=current_articles, page=page, total_pages=total_pages)

# 4. AUTH & CRUD (Safe Mode)
# ==============================================================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if not firebase_connected:
        return render_template('login.html', error="Database tidak terhubung.")

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        hashed_pw = hash_password(password)

        try:
            ref = db.reference(f'users/{username}')
            user_data = ref.get()

            if user_data and user_data.get('password') == hashed_pw:
                session['user'] = username
                session['nama'] = user_data.get("nama", "Pengguna")
                return redirect(url_for('dashboard'))
            else:
                return render_template('login.html', error="Username atau Password salah.")
        except:
            return render_template('login.html', error="Gagal menghubungi server.")

    return render_template('login.html')

@app.route("/register", methods=["GET", "POST"])
def register():
    if not firebase_connected:
        flash("Database error.", "error")
        return render_template("register.html")

    if request.method == "POST":
        nama = request.form.get("nama")
        email = request.form.get("email")
        username = request.form.get("username")
        password = request.form.get("password")

        if len(password) < 8:
            flash("Password minimal 8 karakter.", "error")
            return render_template("register.html")

        # Cek Existing User
        try:
            users_ref = db.reference("users")
            users = users_ref.get() or {}
            if username in users:
                flash("Username sudah dipakai.", "error")
                return render_template("register.html")
        except:
            flash("Gagal cek database.", "error")
            return render_template("register.html")

        otp = str(random.randint(100000, 999999))
        hashed_pw = hash_password(password)
        
        try:
            db.reference(f"pending_users/{username}").set({
                "nama": nama, "email": email, "password": hashed_pw, "otp": otp
            })
            
            # Send Email (Try Block)
            msg = Message("Kode OTP KTVDI", recipients=[email])
            msg.body = f"Kode OTP: {otp}"
            mail.send(msg)
            
            session["pending_username"] = username
            return redirect(url_for("verify_register"))
        except Exception as e:
            flash(f"Error pendaftaran: {e}", "error")

    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    username = session.get("pending_username")
    if not username: return redirect(url_for("register"))

    if request.method == "POST":
        otp_input = request.form.get("otp")
        try:
            pending_ref = db.reference(f"pending_users/{username}")
            data = pending_ref.get()
            
            if data and str(data.get("otp")) == str(otp_input):
                db.reference(f"users/{username}").set({
                    "nama": data["nama"],
                    "email": data["email"],
                    "password": data["password"],
                    "points": 0
                })
                pending_ref.delete()
                session.pop("pending_username", None)
                flash("Berhasil! Silakan login.", "success")
                return redirect(url_for("login"))
            else:
                flash("Kode OTP salah.", "error")
        except:
            flash("Error verifikasi.", "error")

    return render_template("verify-register.html", username=username)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    
    provinsi_list = []
    if firebase_connected:
        try:
            ref = db.reference("provinsi")
            data = ref.get()
            if isinstance(data, list): provinsi_list = [p for p in data if p]
            elif isinstance(data, dict): provinsi_list = list(data.values())
            provinsi_list.sort()
        except: pass

    return render_template("dashboard.html", name=session.get('nama'), provinsi_list=provinsi_list)

@app.route("/add_data", methods=["GET", "POST"])
def add_data():
    if 'user' not in session: return redirect(url_for('login'))
    
    provinsi_list = []
    if firebase_connected:
        try:
            ref = db.reference("provinsi")
            data = ref.get()
            if isinstance(data, list): provinsi_list = [p for p in data if p]
            elif isinstance(data, dict): provinsi_list = list(data.values())
            provinsi_list.sort()
        except: pass

    if request.method == 'POST':
        try:
            provinsi = request.form['provinsi']
            wilayah = request.form['wilayah'].strip()
            mux = request.form['mux'].strip()
            siaran_raw = request.form['siaran']
            
            siaran_list = sorted([s.strip() for s in siaran_raw.split(',') if s.strip()])
            tz = pytz.timezone('Asia/Jakarta')
            now = datetime.now(tz)

            data_to_save = {
                "siaran": siaran_list,
                "last_updated_by_username": session.get('user'),
                "last_updated_by_name": session.get('nama'),
                "last_updated_date": now.strftime("%d-%m-%Y"),
                "last_updated_time": now.strftime("%H:%M:%S WIB")
            }

            db.reference(f"siaran/{provinsi}/{wilayah}/{mux}").set(data_to_save)
            return redirect(url_for('dashboard'))
        except Exception as e:
            return render_template('add_data_form.html', error_message=f"Gagal: {e}", provinsi_list=provinsi_list)

    return render_template('add_data_form.html', provinsi_list=provinsi_list)

@app.route("/edit_data/<provinsi>/<wilayah>/<mux>", methods=["GET", "POST"])
def edit_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    
    # Decode URL
    provinsi = provinsi.replace('%20', ' ')
    wilayah = wilayah.replace('%20', ' ')
    mux = mux.replace('%20', ' ')

    current_siaran = ""
    if firebase_connected:
        try:
            data = db.reference(f"siaran/{provinsi}/{wilayah}/{mux}").get()
            if data and 'siaran' in data:
                current_siaran = ", ".join(data['siaran'])
        except: pass

    if request.method == 'POST':
        try:
            siaran_raw = request.form['siaran']
            siaran_list = sorted([s.strip() for s in siaran_raw.split(',') if s.strip()])
            
            tz = pytz.timezone('Asia/Jakarta')
            now = datetime.now(tz)

            update_data = {
                "siaran": siaran_list,
                "last_updated_by_username": session.get('user'),
                "last_updated_by_name": session.get('nama'),
                "last_updated_date": now.strftime("%d-%m-%Y"),
                "last_updated_time": now.strftime("%H:%M:%S WIB")
            }
            
            db.reference(f"siaran/{provinsi}/{wilayah}/{mux}").update(update_data)
            return redirect(url_for('dashboard'))
        except Exception as e:
            return render_template('edit_data_form.html', error_message=f"Error: {e}", provinsi=provinsi, wilayah=wilayah, mux=mux, siaran=current_siaran)

    return render_template('edit_data_form.html', provinsi=provinsi, wilayah=wilayah, mux=mux, siaran=current_siaran)

@app.route("/delete_data/<provinsi>/<wilayah>/<mux>", methods=["POST"])
def delete_data(provinsi, wilayah, mux):
    if 'user' not in session: return jsonify({"status": "error"}), 401
    try:
        db.reference(f"siaran/{provinsi}/{wilayah}/{mux}").delete()
        return jsonify({"status": "success"})
    except:
        return jsonify({"status": "error"}), 500

# 5. API AJAX HELPER (Safe Mode)
# ==============================================================================
@app.route("/get_wilayah")
def get_wilayah():
    try:
        p = request.args.get("provinsi")
        data = db.reference(f"siaran/{p}").get() or {}
        return jsonify({"wilayah": list(data.keys())})
    except:
        return jsonify({"wilayah": []})

@app.route("/get_mux")
def get_mux():
    try:
        p = request.args.get("provinsi")
        w = request.args.get("wilayah")
        data = db.reference(f"siaran/{p}/{w}").get() or {}
        return jsonify({"mux": list(data.keys())})
    except:
        return jsonify({"mux": []})

@app.route("/get_siaran")
def get_siaran():
    try:
        p = request.args.get("provinsi")
        w = request.args.get("wilayah")
        m = request.args.get("mux")
        data = db.reference(f"siaran/{p}/{w}/{m}").get() or {}
        return jsonify({
            "siaran": data.get("siaran", []),
            "last_updated_date": data.get("last_updated_date", "-"),
            "last_updated_time": data.get("last_updated_time", ""),
            "last_updated_by_name": data.get("last_updated_by_name", "-"),
            "last_updated_by_username": data.get("last_updated_by_username", "-")
        })
    except:
        return jsonify({"siaran": []})

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    # ... (Kode logic forgot password sama, hanya perlu dibungkus try-except jika perlu)
    return render_template("forgot-password.html")

@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp_reset():
    # ... (Logic verify reset password)
    return render_template("verify-otp.html")

@app.route("/reset-password", methods=["GET", "POST"])
def perform_reset():
    # ... (Logic reset password)
    return render_template("reset-password.html")

if __name__ == "__main__":
    app.run(debug=True)
