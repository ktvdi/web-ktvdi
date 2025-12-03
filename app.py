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

# ==============================================================================
# 1. KONFIGURASI
# ==============================================================================
load_dotenv()

app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("SECRET_KEY", "kunci-rahasia-default-123")

# Status Koneksi
firebase_connected = False

# --- Inisialisasi Firebase ---
try:
    if os.environ.get("FIREBASE_PROJECT_ID"):
        # Handle newline di private key
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
        print("⚠️ Warning: Variabel Environment Firebase tidak lengkap.")

except Exception as e:
    print(f"❌ Gagal inisialisasi Firebase: {str(e)}")

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

# ==============================================================================
# 2. HELPER FUNCTIONS (PENTING: Mencegah Error 500)
# ==============================================================================

def safe_items(data):
    """
    Fungsi ini mencegah error saat looping data dari Firebase.
    Menangani jika data berupa Dictionary, List, atau None.
    """
    if not data:
        return []
    if isinstance(data, dict):
        return data.items()
    if isinstance(data, list):
        # Jika list, kita return index sebagai key, dan value sebagai value
        # Filter item yang None (karena Firebase list bisa punya bolong)
        return [(k, v) for k, v in enumerate(data) if v is not None]
    return []

def safe_values(data):
    """Sama seperti di atas, tapi hanya mengambil values."""
    if not data:
        return []
    if isinstance(data, dict):
        return list(data.values())
    if isinstance(data, list):
        return [x for x in data if x is not None]
    return []

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def time_since_published(published_time):
    now = datetime.now()
    try:
        publish_time = datetime(*published_time[:6])
        delta = now - publish_time
        if delta.days >= 1: return f"{delta.days} hari lalu"
        if delta.seconds >= 3600: return f"{delta.seconds // 3600} jam lalu"
        return "Baru saja"
    except:
        return "-"

# ==============================================================================
# 3. ROUTES APLIKASI
# ==============================================================================

@app.route("/")
def home():
    # Inisialisasi variabel default agar tidak error jika DB kosong
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

                # Gunakan safe_items agar tidak crash jika data berupa List
                for provinsi, prov_data in safe_items(siaran_data):
                    # Hitung Wilayah (Level 2)
                    # Jika prov_data string/bukan dict/list, skip
                    if not isinstance(prov_data, (dict, list)): continue
                    
                    # Hitung jumlah wilayah sebenarnya
                    wilayah_items = list(safe_items(prov_data))
                    jumlah_wilayah += len(wilayah_items)

                    for wilayah, wil_data in wilayah_items:
                        if not isinstance(wil_data, (dict, list)): continue
                        
                        # Hitung MUX (Level 3)
                        mux_items = list(safe_items(wil_data))
                        jumlah_mux += len(mux_items)

                        for mux, mux_details in mux_items:
                            if not isinstance(mux_details, dict): continue
                            
                            # Hitung Siaran
                            siaran_list = mux_details.get('siaran', [])
                            if siaran_list:
                                jumlah_siaran += len(siaran_list)
                                for s in siaran_list:
                                    siaran_counts[s.lower()] += 1
                            
                            # Cek Tanggal Update
                            updated_str = mux_details.get('last_updated_date')
                            if updated_str:
                                try:
                                    curr_time = datetime.strptime(updated_str, '%d-%m-%Y')
                                    if last_updated_time is None or curr_time > last_updated_time:
                                        last_updated_time = curr_time
                                except: pass

                # Cari Siaran Terbanyak
                if siaran_counts:
                    top = siaran_counts.most_common(1)[0]
                    top_siaran_name = top[0].upper()
                    top_siaran_count = top[1]

                if last_updated_time:
                    last_update_str = last_updated_time.strftime('%d-%m-%Y')

        except Exception as e:
            print(f"Error reading Home Data: {e}") 
            # Tidak return error, biarkan halaman load dengan data 0 (agar user tidak melihat error 500)

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
        return jsonify({"response": "Maaf, fitur AI belum dikonfigurasi."})

    try:
        response = model.generate_content(prompt)
        return jsonify({"response": response.text})
    except Exception as e:
        return jsonify({"error": "Maaf, sedang gangguan."})

@app.route("/daftar-siaran")
def daftar_siaran():
    provinsi_list = []
    if firebase_connected:
        try:
            ref = db.reference("provinsi")
            data = ref.get()
            # Gunakan safe_values agar aman
            provinsi_list = safe_values(data)
            provinsi_list.sort()
        except: pass
    
    return render_template("daftar-siaran.html", provinsi_list=provinsi_list)

@app.route('/berita')
def berita():
    articles = []
    try:
        rss_url = 'https://news.google.com/rss/search?q=tv+digital&hl=id&gl=ID&ceid=ID:id'
        feed = feedparser.parse(rss_url)
        articles = feed.entries
    except: pass
    
    # Pagination
    per_page = 6
    page = request.args.get('page', 1, type=int)
    total = len(articles)
    
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

# ==============================================================================
# 4. AUTHENTICATION (Login, Register, OTP)
# ==============================================================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if not firebase_connected:
        return render_template('login.html', error="Database error.")

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
            return render_template('login.html', error="Gagal koneksi database.")

    return render_template('login.html')

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        nama = request.form.get("nama")
        email = request.form.get("email")
        username = request.form.get("username")
        password = request.form.get("password")

        # Validasi
        if len(password) < 8:
            flash("Password minimal 8 karakter.", "error"); return render_template("register.html")
        if not re.match(r"^[a-z0-9]+$", username):
            flash("Username harus huruf kecil & angka.", "error"); return render_template("register.html")

        # Cek Database
        try:
            users = db.reference("users").get() or {}
            # Handle jika users berupa List (sangat jarang tapi mungkin)
            if isinstance(users, list): 
                # Convert list to dict logic for checking logic, or check manually
                pass 
            elif username in users:
                flash("Username sudah dipakai.", "error"); return render_template("register.html")
            
            # Cek Email Loop
            for k, v in safe_items(users):
                if isinstance(v, dict) and v.get('email') == email:
                    flash("Email sudah terdaftar.", "error"); return render_template("register.html")
        except: pass

        otp = str(random.randint(100000, 999999))
        hashed_pw = hash_password(password)
        
        try:
            db.reference(f"pending_users/{username}").set({
                "nama": nama, "email": email, "password": hashed_pw, "otp": otp
            })
            msg = Message("Kode OTP KTVDI", recipients=[email])
            msg.body = f"Kode OTP Anda: {otp}"
            mail.send(msg)
            
            session["pending_username"] = username
            return redirect(url_for("verify_register"))
        except Exception as e:
            flash(f"Gagal: {e}", "error")

    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    username = session.get("pending_username")
    if not username: return redirect(url_for("register"))

    if request.method == "POST":
        otp_input = request.form.get("otp")
        data = db.reference(f"pending_users/{username}").get()
        
        if data and str(data.get("otp")) == str(otp_input):
            db.reference(f"users/{username}").set({
                "nama": data["nama"], "email": data["email"], "password": data["password"], "points": 0
            })
            db.reference(f"pending_users/{username}").delete()
            session.pop("pending_username", None)
            flash("Sukses! Silakan login.", "success")
            return redirect(url_for("login"))
        else:
            flash("Kode OTP salah.", "error")

    return render_template("verify-register.html", username=username)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("identifier")
        users = db.reference("users").get() or {}
        
        found_uid = None
        for uid, u in safe_items(users):
            if isinstance(u, dict) and u.get("email") == email:
                found_uid = uid
                break
        
        if found_uid:
            otp = str(random.randint(100000, 999999))
            db.reference(f"otp/{found_uid}").set({"email": email, "otp": otp})
            try:
                msg = Message("Reset Password KTVDI", recipients=[email])
                msg.body = f"Kode OTP Reset: {otp}"
                mail.send(msg)
                session["reset_uid"] = found_uid
                return redirect(url_for("verify_otp"))
            except: flash("Gagal kirim email.", "error")
        else:
            flash("Email tidak ditemukan.", "error")
            
    return render_template("forgot-password.html")

@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    uid = session.get("reset_uid")
    if not uid: return redirect(url_for("forgot_password"))
    
    if request.method == "POST":
        otp_input = request.form.get("otp")
        data = db.reference(f"otp/{uid}").get()
        if data and str(data.get("otp")) == str(otp_input):
            return redirect(url_for("reset_password"))
        flash("OTP Salah.", "error")
        
    return render_template("verify-otp.html")

@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    uid = session.get("reset_uid")
    if not uid: return redirect(url_for("forgot_password"))
    
    if request.method == "POST":
        new_pw = request.form.get("password")
        if len(new_pw) < 8:
            flash("Password min 8 karakter", "error")
        else:
            db.reference(f"users/{uid}").update({"password": hash_password(new_pw)})
            db.reference(f"otp/{uid}").delete()
            session.pop("reset_uid", None)
            flash("Password berhasil direset.", "success")
            return redirect(url_for("login"))
            
    return render_template("reset-password.html")

# ==============================================================================
# 5. DASHBOARD & CRUD (DATA)
# ==============================================================================

@app.route("/dashboard")
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    
    prov_list = []
    if firebase_connected:
        try:
            data = db.reference("provinsi").get()
            prov_list = safe_values(data)
            prov_list.sort()
        except: pass
        
    return render_template("dashboard.html", name=session.get('nama'), provinsi_list=prov_list)

@app.route("/add_data", methods=["GET", "POST"])
def add_data():
    if 'user' not in session: return redirect(url_for('login'))
    
    prov_list = []
    try:
        data = db.reference("provinsi").get()
        prov_list = safe_values(data)
        prov_list.sort()
    except: pass

    if request.method == 'POST':
        try:
            provinsi = request.form['provinsi']
            wilayah = request.form['wilayah'].strip()
            mux = request.form['mux'].strip()
            siaran = sorted([s.strip() for s in request.form['siaran'].split(',') if s.strip()])
            
            # Save Data
            now = datetime.now(pytz.timezone('Asia/Jakarta'))
            data = {
                "siaran": siaran,
                "last_updated_by_username": session.get('user'),
                "last_updated_by_name": session.get('nama'),
                "last_updated_date": now.strftime("%d-%m-%Y"),
                "last_updated_time": now.strftime("%H:%M:%S WIB")
            }
            db.reference(f"siaran/{provinsi}/{wilayah}/{mux}").set(data)
            return redirect(url_for('dashboard'))
        except Exception as e:
            return render_template('add_data_form.html', error_message=f"Gagal: {e}", provinsi_list=prov_list)

    return render_template('add_data_form.html', provinsi_list=prov_list)

@app.route("/edit_data/<provinsi>/<wilayah>/<mux>", methods=["GET", "POST"])
def edit_data(provinsi, wilayah, mux):
    if 'user' not in session: return redirect(url_for('login'))
    
    # URL Decode
    provinsi = provinsi.replace('%20', ' ')
    wilayah = wilayah.replace('%20', ' ')
    mux = mux.replace('%20', ' ')

    old_siaran = ""
    try:
        data = db.reference(f"siaran/{provinsi}/{wilayah}/{mux}").get()
        if data and 'siaran' in data:
            old_siaran = ", ".join(data['siaran'])
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
            return render_template('edit_data_form.html', error_message=str(e), provinsi=provinsi, wilayah=wilayah, mux=mux, siaran=old_siaran)

    return render_template('edit_data_form.html', provinsi=provinsi, wilayah=wilayah, mux=mux, siaran=old_siaran)

@app.route("/delete_data/<provinsi>/<wilayah>/<mux>", methods=["POST"])
def delete_data(provinsi, wilayah, mux):
    if 'user' not in session: return jsonify({"status":"error"}), 401
    try:
        db.reference(f"siaran/{provinsi}/{wilayah}/{mux}").delete()
        return jsonify({"status":"success"})
    except: return jsonify({"status":"error"}), 500

# ==============================================================================
# 6. AJAX API (Safe Mode)
# ==============================================================================
@app.route("/get_wilayah")
def get_wilayah():
    try:
        p = request.args.get("provinsi")
        data = db.reference(f"siaran/{p}").get()
        # Ambil keys, tapi handle jika data adalah List
        keys = [k for k,v in safe_items(data)]
        return jsonify({"wilayah": keys})
    except: return jsonify({"wilayah": []})

@app.route("/get_mux")
def get_mux():
    try:
        p = request.args.get("provinsi")
        w = request.args.get("wilayah")
        data = db.reference(f"siaran/{p}/{w}").get()
        keys = [k for k,v in safe_items(data)]
        return jsonify({"mux": keys})
    except: return jsonify({"mux": []})

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
    except: return jsonify({"siaran": []})

# Lain-lain
@app.route('/sitemap.xml')
def sitemap_xml():
    return send_from_directory('static', 'sitemap.xml')

if __name__ == "__main__":
    app.run(debug=True)
