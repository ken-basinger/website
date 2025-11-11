import os
import secrets
from flask import Flask, render_template_string, redirect, url_for, request, session, Response, abort
import psycopg2
from psycopg2.extras import RealDictCursor
from werkzeug.security import check_password_hash
from pcloud import PyCloud
from io import BytesIO

# --- 1. INITIALIZE APP AND CLIENTS ---
app = Flask(__name__)

# SECURITY CRITICAL: Flask uses this key to secure session cookies (user logins). 
# We load the secret key from the environment variable (SECRET_KEY) for production safety.
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(16)) 

# Load environment variables (Render automatically injects these)
DB_URL = os.environ.get('DATABASE_URL')
PCLOUD_EMAIL = os.environ.get('PCLOUD_EMAIL')
PCLOUD_PASSWORD = os.environ.get('PCLOUD_PASSWORD')

# Global variable to hold the securely initialized pCloud client
pcloud_client = None


def initialize_pcloud_client():
    """Initializes the pCloud client once credentials are confirmed to exist."""
    global pcloud_client
    
    if not PCLOUD_EMAIL or not PCLOUD_PASSWORD:
        # This error should be logged, but the server shouldn't crash
        print("CRITICAL ERROR: PCLOUD_EMAIL or PCLOUD_PASSWORD is not set. Media access is disabled.")
        return None
        
    try:
        # Use direct authentication (email/password) as planned
        client = PyCloud(PCLOUD_EMAIL, PCLOUD_PASSWORD)
        print("SUCCESS: pCloud client initialized.")
        return client
    except Exception as e:
        print(f"ERROR: Failed to initialize pCloud client: {e}")
        return None

# Attempt to initialize the pCloud client before any routes are hit
@app.before_request
def setup_pcloud():
    global pcloud_client
    if pcloud_client is None and PCLOUD_EMAIL and PCLOUD_PASSWORD:
        pcloud_client = initialize_pcloud_client()

# --- 2. THE LOGIN / LOGOUT ROUTES (The Security Gate) ---

@app.route('/login', methods=['GET'])
def login_page():
    # If already logged in, redirect to the story library
    if session.get('user_id'):
        return redirect(url_for('test_connection'))
        
    # Inject the login error message if one exists in the session
    error_message = session.pop('login_error', '')

    # --- HIGH-END LOGIN PAGE HTML ---
    # Uses the elegant color scheme and fonts we selected
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Private Library Login</title>
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Tinos:wght@400;700&family=Cormorant+Garamond:wght@300;700&display=swap">
        <style>
            body {{ background-color: #F8F6F0; color: #262626; font-family: 'Tinos', serif; margin: 0; padding: 0; }}
            .login-container {{ max-width: 400px; margin: 15vh auto; padding: 3rem; background-color: #FFFFFF; border-radius: 12px; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08); }}
            .login-title {{ font-family: 'Cormorant Garamond', serif; font-weight: 700; font-size: 2.5rem; color: #8B7D6C; margin-bottom: 0.5rem; }}
            label {{ display: block; margin-bottom: 0.5rem; font-weight: 700; }}
            input[type="text"], input[type="password"] {{ width: 100%; padding: 0.75rem; margin-bottom: 1.5rem; border: 1px solid #D9D9D9; border-radius: 6px; font-size: 1rem; box-sizing: border-box; }}
            .login-button {{ width: 100%; padding: 1rem; background-color: #8B7D6C; color: #FFFFFF; border: none; border-radius: 6px; font-size: 1.1rem; font-weight: 700; cursor: pointer; transition: background-color 0.3s; }}
            .error-message {{ color: #CC0000; font-weight: bold; margin-top: 1rem; }}
        </style>
    </head>
    <body>
        <div class="login-container">
            <h1 class="login-title">Welcome</h1>
            <p class="error-message">{error_message}</p>
            
            <form method="POST" action="{url_for('login_submit')}"> 
                <div class="form-group">
                    <label for="username">Username or Email</label>
                    <input type="text" id="username" name="username" required>
                </div>
                
                <div class="form-group">
                    <label for="password">Password</label>
                    <input type="password" id="password" name="password" required>
                </div>
                
                <button type="submit" class="login-button">Access Stories</button>
            </form>
        </div>
    </body>
    </html>
    """
    return render_template_string(html_content)


@app.route('/login', methods=['POST'])
def login_submit():
    username_or_email = request.form['username']
    password_input = request.form['password']
    user = None

    try:
        conn = psycopg2.connect(DB_URL, sslmode='require')
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("""
            SELECT user_id, username, password_hash 
            FROM writing.users 
            WHERE username = %s OR email = %s;
        """, (username_or_email, username_or_email))
        
        user = cur.fetchone()
        cur.close()
        conn.close()
        
    except Exception as e:
        session['login_error'] = "Authentication service unavailable (DB error)."
        return redirect(url_for('login_page'))

    # === TEMPORARY OVERRIDE: CHECK FOR USER EXISTENCE ONLY ===
    # This bypasses the password check to see if the query is the problem.
    if user:
        # SUCCESS: User record was found in the database.
        session['user_id'] = user['user_id']
        session['username'] = user['username']
        session.pop('login_error', None)
        return redirect(url_for('test_connection'))
    else:
        # FAILURE: Database did NOT find the user record.
        session['login_error'] = "Authentication failed (User not found)."
        return redirect(url_for('login_page'))
    # === END OVERRIDE ===


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))


# --- 3. MAIN TEST / LIBRARY ROUTE (Protected) ---

@app.route('/')
def test_connection():
    # --- SECURITY GATE ---
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    # --- END SECURITY GATE ---
    
    # --- VARIABLES ---
    db_status = "? DB Connection FAILED"
    pcloud_status = "? pCloud FAILED"
    user_count = "N/A"
    
    # Check pCloud status using the global client
    if pcloud_client:
        pcloud_status = "? pCloud Client Initialized"
    
    # Check if the user is in session
    welcome_message = f"Welcome, {session.get('username', 'Guest')}!"
    
    # --- Test PostgreSQL Connection & Query (Already working) ---
    try:
        conn = psycopg2.connect(DB_URL, sslmode='require')
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute('SELECT COUNT(user_id) FROM writing.users;') 
        count_result = cur.fetchone()
        user_count = count_result['count']
        
        db_status = f"? SUCCESS (User Count: {user_count})"
        
        cur.close()
        conn.close()
        
    except Exception as e:
        db_status = f"? FAILED (DB Error: {e})"
    
    
    # --- FINAL DISPLAY RESULTS ---
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head><title>Private Library - Home</title></head>
    <body style="font-family: sans-serif; padding: 20px;">
        <h1>{welcome_message}</h1>
        <p><a href="{url_for('logout')}">Logout</a></p>
        <hr>
        <h2>System Status Check</h2>
        <p style="font-size: 1.2em;"><strong>PostgreSQL Connection & Query:</strong> {db_status}</p>
        <p style="font-size: 1.2em;"><strong>pCloud Client Status:</strong> {pcloud_status}</p>
        
        <h3 style="margin-top: 2rem;">Library Placeholder</h3>
        <p>Your stories will be listed here after you implement the retrieval logic.</p>

        <h3 style="margin-top: 2rem;">Secure Media Test:</h3>
        <p>Accessing a test image via the secure proxy: <a href="{url_for('secure_media_proxy', filename='ch03-sc02.png', scene_id=101)}">Test Image Link</a></p>
    </body>
    </html>
    """
    return render_template_string(html_content)


# --- 4. THE SECURE MEDIA PROXY ROUTE (Protected) ---
# NOTE: We use scene_id in the path to look up dynamic details from the DB/View
@app.route('/media/<int:scene_id>/<path:filename>')
def secure_media_proxy(scene_id, filename):
    # --- SECURITY GATE ---
    if 'user_id' not in session:
        return abort(401) # Unauthorized if not logged in
    # --- END SECURITY GATE ---

    global pcloud_client
    if pcloud_client is None:
        return abort(503)

    # ... (The rest of the final proxy logic will go here: 
    # Querying the View to construct the pcloud_path, fetching the file, and streaming the Response) ...

    # --- FOR NOW, LET'S JUST SHOW A SUCCESS MESSAGE ---
    if filename == 'ch03-sc02.png':
        return Response("Proxy SUCCESS: Authentication Passed. File data would stream here.", mimetype='text/plain')
    else:
        return abort(404)

# --- END OF APP.PY ---