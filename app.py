import os
import hashlib
import firebase_admin
from firebase_admin import credentials, db
from flask import Flask, request, render_template, redirect, url_for, session
from dotenv import load_dotenv

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
