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

# =========================
# 2) UTIL
# =========================
MUX_REGEX = re.compile(r"^UHF\s\d{2}\s-\s.+$")

def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def check_password(input_password: str, stored_value: str) -> bool:
    """
    Prioritas: bandingkan SHA-256 hex. Jika tidak cocok, coba bandingkan plain text
    (untuk berjaga-jaga bila DB menyimpan password apa adanya).
    """
    if not isinstance(stored_value, str):
        return False
    return sha256_hex(input_password) == stored_value or input_password == stored_value

def wib_now():
    tz = pytz.timezone("Asia/Jakarta")
    now = datetime.now(tz)
    return now.strftime("%d-%m-%Y"), now.strftime("%H:%M:%S WIB")

def require_login(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

# =========================
# 3) AUTH (USERNAME/PASSWORD)
# =========================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        if not username or not password:
            flash("Isi username dan password.")
            return render_template("dashboard.html", view="login")

        # Ambil data user di node users/{username}
        user_node = db.child("users").child(username).get().val()
        if not user_node:
            flash("Username tidak ditemukan.")
            return render_template("dashboard.html", view="login")

        stored_pwd = user_node.get("password", "")
        if not check_password(password, stored_pwd):
            flash("Password salah.")
            return render_template("dashboard.html", view="login")

        # Sukses login -> simpan ke session
        session["user"] = {
            "username": username,
            "name": user_node.get("nama") or username,
            "email": user_node.get("email") or "",
        }
        return redirect(url_for("dashboard"))

    return render_template("dashboard.html", view="login")

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))

# =========================
# 4) DASHBOARD
# =========================
@app.route("/")
@require_login
def root():
    return redirect(url_for("dashboard"))

@app.route("/dashboard", methods=["GET"])
@require_login
def dashboard():
    user = session["user"]

    # Ambil daftar provinsi (map kunci->nama), lalu kita pakai nilainya (nama provinsi)
    provinsi_map = db.child("provinsi").get().val() or {}
    provinsi_list = sorted(list(provinsi_map.values()))

    selected_prov = request.args.get("provinsi") or (provinsi_list[0] if provinsi_list else "")

    # Ambil data siaran untuk provinsi terpilih
    siaran_prov = db.child("siaran").child(selected_prov).get().val() or {}

    return render_template(
        "dashboard.html",
        view="dashboard",
        user=user,
        provinsi_list=provinsi_list,
        selected_prov=selected_prov,
        siaran_prov=siaran_prov
    )

@app.route("/save", methods=["POST"])
@require_login
def save():
    user = session["user"]
    provinsi = (request.form.get("provinsi") or "").strip()
    wilayah = (request.form.get("wilayah") or "").strip()
    mux = (request.form.get("mux") or "").strip()
    daftar = (request.form.get("daftar") or "").strip()

    if not provinsi:
        flash("Provinsi wajib dipilih.")
        return redirect(url_for("dashboard", provinsi=provinsi))

    expected_wil = f"{provinsi}-1"
    if wilayah != expected_wil:
        flash(f"Wilayah Layanan harus '{expected_wil}'.")
        return redirect(url_for("dashboard", provinsi=provinsi))

    if not MUX_REGEX.match(mux):
        flash("Format MUX harus 'UHF XX - Nama MUX'. Contoh: UHF 35 - Indosiar.")
        return redirect(url_for("dashboard", provinsi=provinsi))

    if not daftar:
        flash("Daftar siaran tidak boleh kosong.")
        return redirect(url_for("dashboard", provinsi=provinsi))

    channels = [s.strip() for s in daftar.split(",") if s.strip()]
    siaran_obj = {str(i + 1): ch for i, ch in enumerate(channels)}

    tgl, jam = wib_now()
    payload = {
        "last_updated_by_name": user.get("name"),
        "last_updated_by_username": user.get("username"),
        "last_updated_date": tgl,
        "last_updated_time": jam,
        "siaran": siaran_obj
    }

    db.child("siaran").child(provinsi).child(wilayah).child(mux).set(payload)
    flash("Data siaran berhasil disimpan.")
    return redirect(url_for("dashboard", provinsi=provinsi))

@app.route("/delete", methods=["POST"])
@require_login
def delete():
    provinsi = (request.form.get("provinsi") or "").strip()
    wilayah = (request.form.get("wilayah") or "").strip()
    mux = (request.form.get("mux") or "").strip()

    if not provinsi or not wilayah or not mux:
        flash("Parameter penghapusan tidak lengkap.")
        return redirect(url_for("dashboard", provinsi=provinsi))

    db.child("siaran").child(provinsi).child(wilayah).child(mux).remove()
    flash("Data siaran dihapus.")
    return redirect(url_for("dashboard", provinsi=provinsi))

@app.route("/edit", methods=["GET"])
@require_login
def edit():
    user = session["user"]
    provinsi = (request.args.get("provinsi") or "").strip()
    wilayah = (request.args.get("wilayah") or "").strip()
    mux = (request.args.get("mux") or "").strip()

    provinsi_map = db.child("provinsi").get().val() or {}
    provinsi_list = sorted(list(provinsi_map.values()))
    siaran_prov = db.child("siaran").child(provinsi).get().val() or {}

    data = db.child("siaran").child(provinsi).child(wilayah).child(mux).get().val() or {}
    siaran_obj = data.get("siaran", {})
    ordered = [siaran_obj[k] for k in sorted(siaran_obj.keys(), key=lambda x: int(x))] if siaran_obj else []
    daftar_prefill = ", ".join(ordered)

    return render_template(
        "dashboard.html",
        view="dashboard",
        user=user,
        provinsi_list=provinsi_list,
        selected_prov=provinsi,
        siaran_prov=siaran_prov,
        edit_mode=True,
        edit_data={"provinsi": provinsi, "wilayah": wilayah, "mux": mux, "daftar": daftar_prefill}
    )

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
