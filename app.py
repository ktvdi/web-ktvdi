import os
import hashlib
import firebase_admin
import random
import re
from firebase_admin import credentials, db
from flask import Flask, request, render_template, redirect, url_for, session, flash, jsonify
from dotenv import load_dotenv
from flask_mail import Mail, Message
from datetime import datetime

# Muat variabel lingkungan
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")

# Inisialisasi Firebase
try:
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

    firebase_admin.initialize_app(cred, {
        'databaseURL': os.environ.get('DATABASE_URL')
    })

    ref = db.reference('/')
    print("✅ Firebase berhasil terhubung!")

except Exception as e:
    print("❌ Error initializing Firebase:", str(e))
    ref = None

# Inisialisasi Email
app.config['MAIL_SERVER'] = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
app.config['MAIL_PORT'] = int(os.environ.get("MAIL_PORT", 587))
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD")
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")

mail = Mail(app)

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("identifier")

        users_ref = db.reference("users")
        users = users_ref.get() or {}

        found_uid, found_user = None, None
        for uid, user in users.items():
            if "email" in user and user["email"].lower() == email.lower():
                found_uid, found_user = uid, user
                break

        if found_uid:
            otp = str(random.randint(100000, 999999))
            db.reference(f"otp/{found_uid}").set({
                "email": email,
                "otp": otp
            })

            try:
                # username = uid, nama = field di dalam
                username = found_uid
                nama = found_user.get("nama", "")

                msg = Message("Kode OTP Reset Password", recipients=[email])
                msg.body = f"""
Halo {nama} ({username}),

Anda meminta reset password.
Kode OTP Anda adalah: {otp}

Jika Anda tidak meminta reset, abaikan email ini.
"""
                mail.send(msg)

                flash(
                    f"Kode OTP telah dikirim ke email Anda. Username: {username}, Nama: {nama}",
                    "success"
                )
                session["reset_uid"] = found_uid
                return redirect(url_for("verify_otp"))

            except Exception as e:
                flash(f"Gagal mengirim email: {str(e)}", "error")

        else:
            flash("Email tidak ditemukan di database!", "error")

    return render_template("forgot-password.html")

# --- Halaman verifikasi OTP ---
@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    uid = session.get("reset_uid")
    if not uid:
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        otp_input = request.form.get("otp")

        # ambil OTP dari Firebase
        otp_data = db.reference(f"otp/{uid}").get()
        if otp_data and otp_data["otp"] == otp_input:
            flash("OTP benar, silakan ganti password Anda.", "success")
            return redirect(url_for("reset_password"))
        else:
            flash("OTP salah atau kadaluarsa.", "error")

    return render_template("verify-otp.html")

# --- Halaman reset password ---
@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    uid = session.get("reset_uid")
    if not uid:
        flash("Sesi reset password tidak ditemukan!", "error")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        new_password = request.form.get("password")

        if len(new_password) < 8:
            flash("Password harus minimal 8 karakter.", "error")
            return render_template("reset-password.html")

        # hash password (pakai sha256 agar sama kayak login-mu sebelumnya)
        hashed_pw = hashlib.sha256(new_password.encode()).hexdigest()

        user_ref = db.reference(f"users/{uid}")
        user_ref.update({"password": hashed_pw})

        # hapus OTP setelah reset
        db.reference(f"otp/{uid}").delete()
        session.pop("reset_uid", None)

        flash("Password berhasil direset, silakan login kembali.", "success")
        return redirect(url_for("login"))

    return render_template("reset-password.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        nama = request.form.get("nama")
        email = request.form.get("email")
        username = request.form.get("username")
        password = request.form.get("password")

        # --- Validasi ---
        if len(password) < 8:
            flash("Password harus minimal 8 karakter.", "error")
            return render_template("register.html")

        if not re.match(r"^[a-z0-9]+$", username):
            flash("Username hanya boleh huruf kecil dan angka.", "error")
            return render_template("register.html")

        users_ref = db.reference("users")
        users = users_ref.get() or {}

        # cek email sudah terdaftar
        for uid, user in users.items():
            if user.get("email", "").lower() == email.lower():
                flash("Email sudah terdaftar!", "error")
                return render_template("register.html")

        # cek username sudah dipakai
        if username in users:
            flash("Username sudah dipakai!", "error")
            return render_template("register.html")

        # hash password
        hashed_pw = hashlib.sha256(password.encode()).hexdigest()

        # generate OTP
        otp = str(random.randint(100000, 999999))

        # simpan ke pending_users di Firebase
        db.reference(f"pending_users/{username}").set({
            "nama": nama,
            "email": email,
            "password": hashed_pw,
            "otp": otp
        })

        # kirim OTP ke email
        try:
            msg = Message("Kode OTP Verifikasi Akun", recipients=[email])
            msg.body = f"""
Halo {nama},

Terima kasih sudah mendaftar.
Kode OTP Anda: {otp}

Gunakan kode ini untuk mengaktifkan akun Anda.
"""
            mail.send(msg)

            session["pending_username"] = username
            flash("Kode OTP telah dikirim ke email Anda. Silakan verifikasi.", "success")
            return redirect(url_for("verify_register"))

        except Exception as e:
            flash(f"Gagal mengirim email OTP: {str(e)}", "error")

    return render_template("register.html")

@app.route("/verify-register", methods=["GET", "POST"])
def verify_register():
    username = session.get("pending_username")
    if not username:
        flash("Sesi pendaftaran tidak ditemukan.", "error")
        return redirect(url_for("register"))

    pending_ref = db.reference(f"pending_users/{username}")
    pending_data = pending_ref.get()

    if not pending_data:
        flash("Data pendaftaran tidak ditemukan.", "error")
        return redirect(url_for("register"))

    if request.method == "POST":
        otp_input = request.form.get("otp")

        if pending_data.get("otp") == otp_input:
            # pindahkan ke users
            db.reference(f"users/{username}").set({
                "nama": pending_data["nama"],
                "email": pending_data["email"],
                "password": pending_data["password"],
                "points": 0
            })

            # hapus dari pending
            pending_ref.delete()
            session.pop("pending_username", None)

            flash("Akun berhasil diverifikasi! Silakan login.", "success")
        else:
            flash("Kode OTP salah!", "error")

    return render_template("verify-register.html", username=username)

@app.route("/daftar-siaran")
def daftar_siaran():
    # Ambil daftar provinsi dari Firebase
    ref = db.reference("provinsi")
    data = ref.get() or {}
    provinsi_list = list(data.values())  # misalnya: {"bengkulu": "Bengkulu"} → ambil value
    return render_template("daftar-siaran.html", provinsi_list=provinsi_list)

# 🔹 API ambil daftar wilayah
@app.route("/get_wilayah")
def get_wilayah():
    provinsi = request.args.get("provinsi")
    ref = db.reference(f"siaran/{provinsi}")
    data = ref.get() or {}
    wilayah_list = list(data.keys())
    return jsonify({"wilayah": wilayah_list})

# 🔹 API ambil daftar MUX
@app.route("/get_mux")
def get_mux():
    provinsi = request.args.get("provinsi")
    wilayah = request.args.get("wilayah")
    ref = db.reference(f"siaran/{provinsi}/{wilayah}")
    data = ref.get() or {}
    mux_list = list(data.keys())
    return jsonify({"mux": mux_list})

# 🔹 API ambil detail siaran
@app.route("/get_siaran")
def get_siaran():
    provinsi = request.args.get("provinsi")
    wilayah = request.args.get("wilayah")
    mux = request.args.get("mux")
    ref = db.reference(f"siaran/{provinsi}/{wilayah}/{mux}")
    data = ref.get() or {}

    return jsonify({
        "last_updated_by_name": data.get("last_updated_by_name", "-"),
        "last_updated_by_username": data.get("last_updated_by_username", "-"),
        "last_updated_date": data.get("last_updated_date", "-"),
        "last_updated_time": data.get("last_updated_time", "-"),
        "siaran": data.get("siaran", [])
    })

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")  # key di Firebase
        password = request.form.get("password")

        if ref is None:
            return "Firebase tidak terhubung", 500

        users_ref = ref.child('users')
        user_data = users_ref.child(username).get()

        if not user_data:
            error = "Username tidak ditemukan."
            return render_template('login.html', error=error)

        # Hash input password sebelum dibandingkan
        input_hash = hashlib.sha256(password.encode()).hexdigest()
        if user_data.get("password") == input_hash:
            # simpan username & nama lengkap ke session
            session['username'] = username
            session['nama'] = user_data.get("nama", "Pengguna")
            return redirect(url_for('dashboard'))
        else:
            error = "Password salah."
            return render_template('login.html', error=error)

    return render_template('login.html')

@app.route("/dashboard")
def dashboard():
    if 'username' in session:
        return render_template("dashboard.html", nama=session['nama'])
    return redirect(url_for('login'))

@app.route("/logout")
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))

@app.route("/test-firebase")
def test_firebase():
    try:
        if ref is None:
            return "❌ Firebase belum terhubung"

        # Ambil semua data root
        data = ref.get()

        if not data:
            return "✅ Firebase terhubung, tapi data kosong."
        return f"✅ Firebase terhubung! Data root:<br><pre>{data}</pre>"
    except Exception as e:
        return f"❌ Error akses Firebase: {e}"

if __name__ == "__main__":
    app.run(debug=True)
