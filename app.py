import os
import secrets
import boto3
from botocore.exceptions import ClientError
from flask import Flask, render_template_string, redirect, url_for, request, session, abort, Response
import psycopg2
from psycopg2.extras import RealDictCursor

# --- 1. CONFIGURATION AND INITIALIZATION ---
app = Flask(__name__)

# Load secrets securely from Render Environment Variables
DB_URL = os.environ.get('DATABASE_URL')
AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
AWS_REGION_NAME = os.environ.get('AWS_REGION_NAME', 'us-east-1')
S3_BUCKET_NAME = os.environ.get('S3_BUCKET_NAME', 'your-default-bucket-name')
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(16))

# Initialize S3 Client once globally
try:
    S3_CLIENT = boto3.client(
        's3',
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_REGION_NAME
    )
    print("SUCCESS: AWS S3 client initialized.")
except Exception as e:
    print(f"CRITICAL S3 ERROR: {e}")
    S3_CLIENT = None

# --- 2. HELPER FUNCTIONS ---

def get_db_connection():
    """Returns a new psycopg2 connection using the secure DB_URL."""
    return psycopg2.connect(DB_URL, sslmode='require')

def generate_signed_s3_url(series_slug, book_slug, filename, media_type):
    """Generates a secure, time-limited URL for a private S3 object."""
    if S3_CLIENT is None: return None
    
    media_folder = 'images' if media_type == 'image' else 'audio'
    # NOTE: Path must exactly match how files are uploaded to S3 via Cyberduck!
    s3_key = (
        f"media/series/{series_slug}/{book_slug}/scenes/{media_folder}/{filename}"
    )

    try:
        # Generate the URL, valid for 300 seconds (5 minutes)
        url = S3_CLIENT.generate_presigned_url(
            ClientMethod='get_object',
            Params={'Bucket': S3_BUCKET_NAME, 'Key': s3_key},
            ExpiresIn=300
        )
        return url
    except ClientError as e:
        print(f"AWS S3 Signing Error for key {s3_key}: {e}")
        return None

# --- 3. AUTHENTICATION ROUTES ---

@app.route('/login', methods=['GET'])
def login_page():
    if session.get('user_id'): return redirect(url_for('story_library'))
    # --- Login page HTML omitted for brevity but includes the high-end CSS ---
    html_content = "..." 
    return render_template_string(html_content)

@app.route('/login', methods=['POST'])
def login_submit():
    # Final production logic would be here, but we use the simulated success for structural testing
    if request.form.get('username') == 'testreader' and request.form.get('password') == 'testpass':
        session['user_id'] = 1
        return redirect(url_for('story_library'))
    return redirect(url_for('login_page', error='invalid'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))

# --- 4. APPLICATION CORE HANDLERS ---

@app.route('/')
def story_library():
    if 'user_id' not in session: return redirect(url_for('login_page'))
    
    stories = []
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        sql_query = """
        SELECT s.story_id, s.story_title, s.book_slug, se.series_slug
        FROM website.stories s JOIN website.series se ON s.series_id = se.series_id;
        """
        cur.execute(sql_query)
        stories = cur.fetchall()
        cur.close(); conn.close()
    except Exception as e:
        print(f"ERROR fetching library: {e}")
    
    # --- Library HTML Generation ---
    # ... (HTML generation using stories array) ...
    html_content = "..." 
    return render_template_string(html_content)

@app.route('/read/<int:scene_id>')
def read_scene(scene_id):
    if 'user_id' not in session: return redirect(url_for('login_page'))

    # ... (Code to fetch scene text, slugs, and triggers) ...
    # ... (Code to generate the HTML and CSS for the Immersive Reader) ...
    html_content = "..." 
    return render_template_string(html_content)


@app.route('/media/<int:scene_id>/<path:filename>')
def secure_media_proxy(scene_id, filename):
    if 'user_id' not in session: return abort(401)
    if S3_CLIENT is None: return abort(503)

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        # Query DB to get slugs and media type
        sql_query = """
        SELECT st.book_slug, se.series_slug, ms.media_type
        FROM website.media_sync ms
        JOIN website.scenes s ON ms.scene_id = s.scene_id
        JOIN website.chapters ch ON s.chapter_id = ch.chapter_id
        JOIN website.stories st ON ch.story_id = st.story_id
        JOIN website.series se ON st.series_id = se.series_id
        WHERE ms.scene_id = %s AND ms.media_file_path = %s;
        """
        cur.execute(sql_query, (scene_id, filename))
        db_result = cur.fetchone()
        cur.close(); conn.close()

        if not db_result: return abort(404)
        
        # GENERATE SECURE URL AND REDIRECT
        signed_url = generate_signed_s3_url(
            db_result['series_slug'], db_result['book_slug'], filename, db_result['media_type']
        )
        
        if signed_url:
            return redirect(signed_url, code=302)
        else:
            return abort(404)

    except Exception as e:
        print(f"CRITICAL PROXY ERROR: {e}")
        return abort(500)