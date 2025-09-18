import os
import hashlib
import firebase_admin
from firebase_admin import credentials, db
from flask import Flask, request, render_template, redirect, url_for, session
from dotenv import load_dotenv
from flask_mail import Mail

# Muat variabel lingkungan
load_dotenv()

print("FIREBASE_PROJECT_ID:", os.environ.get("FIREBASE_PROJECT_ID"))
print("DATABASE_URL:", os.environ.get("DATABASE_URL"))
print("FIREBASE_CLIENT_EMAIL:", os.environ.get("FIREBASE_CLIENT_EMAIL"))
print("PRIVATE_KEY length:", len(os.environ.get("FIREBASE_PRIVATE_KEY", "")))

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY')

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

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("identifier")

        # cek email di Firebase
        users_ref = db.reference("users")  # asumsinya data user ada di node "users"
        users = users_ref.get()

        found = None
        for uid, user in users.items():
            if "email" in user and user["email"] == email:
                found = uid
                break

        if found:
            # generate OTP 6 digit
            otp = str(random.randint(100000, 999999))

            # simpan OTP ke Firebase
            db.reference(f"otp/{found}").set({
                "email": email,
                "otp": otp
            })

            # kirim OTP via email
            try:
                msg = Message("Kode OTP Reset Password", recipients=[email])
                msg.body = f"Kode OTP Anda adalah: {otp}. Gunakan kode ini untuk reset password."
                mail.send(msg)

                flash("Kode OTP telah dikirim ke email Anda", "success")
                session["reset_uid"] = found  # simpan user id ke session
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
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        new_password = request.form.get("password")

        # update password di Firebase
        db.reference(f"users/{uid}/password").set(new_password)

        # hapus OTP
        db.reference(f"otp/{uid}").delete()
        session.pop("reset_uid", None)

        flash("Password berhasil direset, silakan login kembali.", "success")
        return redirect(url_for("login"))

    return render_template("reset-password.html")

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
