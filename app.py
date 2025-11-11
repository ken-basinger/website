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

@app.route('/') # <-- This is the main landing page after login
def story_library():
    # --- SECURITY GATE ---
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    # --- END SECURITY GATE ---
    
    DB_URL = os.environ.get('DATABASE_URL')
    stories = []
    
    # 1. Database Query Logic (fetches story list)
    try:
        # ... SQL to JOIN writing.stories and writing.series ...
        stories = cur.fetchall()
    except Exception as e:
        print(f"ERROR: Failed to fetch story list: {e}")

    # 2. HTML Generation Logic (loops through stories)
    story_list_html = ""
    # ... logic to create the HTML links using the fetched data ...

    # 3. Final Return Statement
    return render_template_string(f"""
    <body ...>
        <h2>Your Private Library</h2>
        {story_list_html}
    </body>


# --- 4. THE SECURE MEDIA PROXY ROUTE (Protected) ---
# NOTE: We use scene_id in the path to look up dynamic details from the DB/View
@app.route('/media/<int:scene_id>/<path:filename>')
def secure_media_proxy(scene_id, filename):
    # --- SECURITY GATE ---
    if 'user_id' not in session:
        return abort(401) # Unauthorized if not logged in
    # --- END SECURITY GATE ---

    global pcloud_client
    DB_URL = os.environ.get('DATABASE_URL')
    
    if pcloud_client is None:
        return abort(503) # Service unavailable if pCloud client failed

    # 1. QUERY DATABASE VIEW to get the full, constructed pCloud path
    try:
        conn = psycopg2.connect(DB_URL, sslmode='require')
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Query the View for the path associated with the requested scene and filename
        sql_query = """
        SELECT full_pcloud_media_path, media_type
        FROM writing.scene_media_details 
        WHERE scene_id = %s AND media_file_path = %s 
        LIMIT 1;
        """
        # NOTE: Assumes media_file_path in DB is just the filename (e.g., 'ch03-sc02.png')
        cur.execute(sql_query, (scene_id, filename)) 
        
        db_result = cur.fetchone()
        cur.close()
        conn.close()

        if not db_result:
            # File not found in the database view
            print(f"Proxy Error: File {filename} for scene {scene_id} not mapped in database.")
            return abort(404)
            
        pcloud_path = db_result['full_pcloud_media_path']
        media_type = db_result['media_type']
        
    except Exception as e:
        print(f"Database Query Error in Proxy: {e}")
        return abort(500) # Internal Server Error

    # 2. SECURELY FETCH THE FILE FROM PCLOUD
    try:
        file_data = pcloud_client.getfile(path=pcloud_path).read()
        
        # 3. DETERMINE CONTENT TYPE
        if media_type == 'image':
            content_type = 'image/jpeg' if filename.lower().endswith(('.jpg', '.jpeg')) else 'image/png'
        elif media_type == 'audio':
            content_type = 'audio/mpeg' 
        else:
            content_type = 'application/octet-stream'

        # 4. STREAM RESPONSE
        response = Response(file_data, mimetype=content_type)
        response.headers['Content-Disposition'] = f'inline; filename="{filename}"'
        return response

    except Exception as e:
        print(f"pCloud Access Error: Failed to retrieve {pcloud_path}. {e}")
        return abort(404)
# --- NEW ROUTE: THE STORY LIBRARY PAGE (Protected) ---

@app.route('/library')
def story_library():
    # --- SECURITY GATE ---
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    # --- END SECURITY GATE ---
    
    DB_URL = os.environ.get('DATABASE_URL')
    stories = []
    
    try:
        conn = psycopg2.connect(DB_URL, sslmode='require')
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Fetch all necessary story data
        sql_query = """
        SELECT 
            s.story_id,
            s.story_title,
            s.book_slug,
            se.series_slug
        FROM writing.stories s
        JOIN writing.series se ON s.series_id = se.series_id;
        """
        cur.execute(sql_query)
        stories = cur.fetchall()
        cur.close()
        conn.close()

    except Exception as e:
        # If the DB fails here, log it and display an empty list
        print(f"ERROR: Failed to fetch story list: {e}")

    # --- RENDER THE LIBRARY HTML ---
    
    # We will use simple, clean HTML to list the stories
    story_list_html = ""
    if stories:
        for story in stories:
            # Construct the link to the first scene (assuming scene_id 1 is the start)
            # This link will take the reader to the actual immersive view
            scene_link = url_for('read_scene', scene_id=1) 
            
            story_list_html += f"""
            <div style="border: 1px solid #ccc; padding: 15px; margin-bottom: 10px; border-radius: 8px;">
                <h3 style="margin: 0; color: #8B7D6C;">{story['story_title']} ({story['series_slug']})</h3>
                <p>Status: Available</p>
                <p><a href="{scene_link}">Start Reading (Test Link)</a></p>
            </div>
            """
    else:
        story_list_html = "<p>No stories found in the library. Please add content to the database.</p>"

    html_content = f"""
    <body style="font-family: sans-serif; padding: 40px; background-color: #F8F6F0;">
        <h1>Welcome, {session.get('username', 'Reader')}!</h1>
        <p><a href="{url_for('logout')}">Logout</a></p>
        <hr>
        <h2>Your Private Library</h2>
        {story_list_html}
    </body>
    """
    return render_template_string(html_content)
# --- END OF APP.PY ---