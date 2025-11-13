import os
import secrets
import boto3
from botocore.exceptions import ClientError
from flask import Flask, render_template_string, redirect, url_for, request, session, abort
import psycopg2
from psycopg2.extras import RealDictCursor
from werkzeug.security import check_password_hash

# --- 1. CONFIGURATION AND INITIALIZATION ---
app = Flask(__name__)

# Load secrets securely from Render Environment Variables
DB_URL = os.environ.get('DATABASE_URL')
AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
AWS_REGION_NAME = os.environ.get('AWS_REGION_NAME', 'us-east-1')
S3_BUCKET_NAME = os.environ.get('S3_BUCKET_NAME', 'your-default-bucket-name')
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(16))

S3_CLIENT = None

def get_s3_client():
    """Initializes and returns the S3 client safely."""
    global S3_CLIENT
    if S3_CLIENT is None:
        try:
            if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY:
                 raise ValueError("AWS credentials are not set.")

            S3_CLIENT = boto3.client(
                's3',
                aws_access_key_id=AWS_ACCESS_KEY_ID,
                aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                region_name=AWS_REGION_NAME
            )
        except Exception as e:
            print(f"CRITICAL S3 ERROR: {e}")
            S3_CLIENT = None
    return S3_CLIENT

def get_db_connection():
    """Returns a new psycopg2 connection using the secure DB_URL."""
    return psycopg2.connect(DB_URL, sslmode='require')

def generate_signed_s3_url(series_slug, book_slug, filename, media_type):
    """Generates a secure, time-limited URL for a private S3 object."""
    client = get_s3_client()
    if client is None: return None
    
    media_folder = 'images' if media_type == 'image' else 'audio'
    # Final, corrected S3 key path construction
    s3_key = (f"media/series/{series_slug}/{book_slug}/scenes/{media_folder}/{filename}")

    try:
        url = client.generate_presigned_url(
            ClientMethod='get_object',
            Params={'Bucket': S3_BUCKET_NAME, 'Key': s3_key},
            ExpiresIn=300
        )
        return url
    except ClientError as e:
        print(f"AWS S3 Signing Error for key {s3_key}: {e}")
        return None

# --- 2. AUTHENTICATION ROUTES ---

@app.route('/login', methods=['GET'])
def login_page():
    if session.get('user_id'): return redirect(url_for('story_library'))
    
    error_message = request.args.get('error')
    
    html_content = f"""
    <!DOCTYPE html><html><head>
        <title>Private Library Login</title>
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Tinos:wght@400;700&family=Cormorant+Garamond:wght@300;700&display=swap">
        <style>
            /* --- High-End Login CSS --- */
            body {{ background-color: #F8F6F0; color: #262626; font-family: 'Tinos', serif; margin: 0; padding: 0; }}
            .login-container {{ max-width: 400px; margin: 15vh auto; padding: 3rem; background-color: #FFFFFF; border-radius: 12px; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08); }}
            .login-title {{ font-family: 'Cormorant Garamond', serif; font-weight: 700; font-size: 2.5rem; color: #8B7D6C; margin-bottom: 0.5rem; }}
            .error-message {{ color: #CC0000; font-weight: bold; margin-top: 1rem; }}
        </style>
    </head><body>
        <div class="login-container">
            <h1 class="login-title">Welcome</h1>
            {f'<p class="error-message">Incorrect username or password.</p>' if error_message else ''}
            
            <form method="POST" action="{url_for('login_submit')}"> 
                <div class="form-group"><label for="username">Username or Email</label><input type="text" id="username" name="username" required></div>
                <div class="form-group"><label for="password">Password</label><input type="password" id="password" name="password" required></div>
                <button type="submit" class="login-button">Access Stories</button>
            </form>
        </div>
    </body></html>
    """
    return render_template_string(html_content)

@app.route('/login', methods=['POST'])
def login_submit():
    username_or_email = request.form.get('username')
    password_input = request.form.get('password')
    user = None

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # 1. Retrieve user hash and credentials
        cur.execute("""
            SELECT user_id, username, password_hash 
            FROM website.users 
            WHERE username = %s OR email = %s;
        """, (username_or_email, username_or_email))
        
        user = cur.fetchone()
        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"CRITICAL AUTHENTICATION DB ERROR: {e}")
        return redirect(url_for('login_page', error='db_fail'))

    # 2. SECURE HASH CHECK (Simulated success for now)
    
    if user and password_input == 'testpass': # TEMPORARY: Placeholder for working hash check
        session['user_id'] = user['user_id']
        session['username'] = user['username']
        return redirect(url_for('story_library'))
    else:
        return redirect(url_for('login_page', error='invalid'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))

# --- 3. APPLICATION CORE HANDLERS ---

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
    story_list_html = ""
    if stories:
        for story in stories:
            # FIX: Get the actual start scene ID for the link
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                # Find the smallest scene_id linked to this story
                start_scene_query = """
                    SELECT MIN(sc.scene_id)
                    FROM website.chapters ch
                    JOIN website.scenes sc ON sc.chapter_id = ch.chapter_id
                    WHERE ch.story_id = %s;
                """
                cur.execute(start_scene_query, (story['story_id'],))
                start_scene_id = cur.fetchone()[0] or 1 # Use 1 as fallback
                cur.close(); conn.close()
            except:
                start_scene_id = 1 # Fallback on error
                
            scene_link = url_for('read_scene', scene_id=start_scene_id) 
            
            story_list_html += f"""
            <div style="border: 1px solid #E0E0E0; padding: 20px; margin-bottom: 15px; border-radius: 8px; background-color: #FFFFFF;">
                <h3 style="margin: 0 0 5px; font-family: 'Cormorant Garamond', serif; color: #8B7D6C;">{story['story_title']} ({story['series_slug']})</h3>
                <p><a href="{scene_link}">Start Reading</a></p>
            </div>
            """
    else:
        story_list_html = "<p>No stories found. Check your database links.</p>"
        
    html_content = f"""
    <!DOCTYPE html><html><head><title>Private Library</title></head>
    <body style="font-family: 'Tinos', serif; padding: 40px; background-color: #F8F6F0;">
        <h1>Welcome, {session.get('username', 'Reader')}!</h1><p><a href="{url_for('logout')}">Logout</a></p><hr>
        <h2>Your Private Library</h2>
        {story_list_html}
    </body></html>
    """
    return render_template_string(html_content)

@app.route('/read/<int:scene_id>')
def read_scene(scene_id):
    if 'user_id' not in session: return redirect(url_for('login_page'))
    
    scene_data = {
        'title': 'Scene Title Placeholder', 
        'story_title': 'Story Placeholder',
        'raw_text': "Error: Could not retrieve text from database.",
    }
    processed_text_html = ""
    raw_triggers = []

    # 1. DATABASE FETCHING (Get real text/data)
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor) 
        
        # Get scene details and story/series slugs
        sql_query = """
        SELECT
            s.scene_title, s.scene_text, 
            st.story_title, st.book_slug,
            se.series_slug,
            f.file_name, ms.text_trigger_id, ms.media_type
        FROM website.scenes s
        JOIN website.chapters ch ON s.chapter_id = ch.chapter_id
        JOIN website.stories st ON ch.story_id = st.story_id
        JOIN website.series se ON st.series_id = se.series_id
        LEFT JOIN website.media_sync ms ON ms.scene_id = s.scene_id
        LEFT JOIN website.files f ON ms.file_id = f.file_id
        WHERE s.scene_id = %s;
        """
        cur.execute(sql_query, (scene_id,))
        scene_result = cur.fetchall()
        
        if scene_result:
            first_row = scene_result[0]
            scene_data['title'] = first_row['scene_title']
            scene_data['raw_text'] = first_row['scene_text']
            scene_data['story_title'] = first_row['story_title']
            scene_data['series_slug'] = first_row['series_slug']
            scene_data['book_slug'] = first_row['book_slug']
            
            # --- PROCESS TEXT SEGMENTATION & MARKERS ---
            paragraphs = scene_data['raw_text'].split('\n\n')
            
            media_triggers = []
            for row in scene_result:
                 if row.get('media_type') == 'image' and row.get('file_name'):
                    media_triggers.append({
                        'trigger_id': row['text_trigger_id'],
                        'media_path': url_for('secure_media_proxy', scene_id=scene_id, filename=row['file_name']),
                    })

            # --- SEGMENTATION AND MARKER INSERTION ---
            processed_text_html = ""
            for i, p in enumerate(paragraphs):
                unique_trigger_id = f'p-{scene_id}-{i + 1}'
                trigger_data = next((t for t in media_triggers if t['trigger_id'] == unique_trigger_id), None)
                
                if trigger_data:
                    processed_text_html += (
                        f'<p id="{unique_trigger_id}" data-image-url="{trigger_data["media_path"]}" class="trigger-point-active">{p}</p>\n\n'
                    )
                else:
                    processed_text_html += f"<p>{p}</p>\n\n"
            
        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"CRITICAL SCENE FETCH ERROR: {e}")
        pass 
    
    # Final default URL for the image
    # Fallback to the first available image URL, or a blank placeholder
    default_image_url = media_triggers[0]['media_path'] if media_triggers else url_for('secure_media_proxy', scene_id=scene_id, filename='test-image.jpg') 
    
    # --- 2. RENDER FINAL PAGE (WITH VISUAL POLISH) ---
    
    html_content = f"""
    <!DOCTYPE html><html><head>
        <title>{scene_data['title']} | {scene_data['story_title']}</title>
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Tinos:wght@400;700&family=Cormorant+Garamond:wght@300;700&display=swap">
        <style>
            /* --- High-End Editorial Theme CSS (Full Layout Fix) --- */
            body {{ background-color: #F8F6F0; color: #262626; font-family: 'Tinos', serif; margin: 0; padding: 0; }}
            .reading-area {{ display: grid; grid-template-columns: minmax(600px, 800px) 1fr; max-width: 1400px; margin: 0 auto; }}
            .text-column {{ padding: 3rem 4rem; font-size: 1.25rem; line-height: 1.8; }}
            .chapter-title {{ font-family: 'Cormorant Garamond', serif; font-weight: 300; font-size: 4rem; color: #8B7D6C; margin-bottom: 3rem; }}
            .media-column-sticky {{ position: sticky; top: 0; height: 100vh; padding: 4rem 2rem; box-sizing: border-box; }}
            .scene-image {{ width: 100%; border-radius: 4px; box-shadow: 0 5px 20px rgba(0, 0, 0, 0.1); }}
        </style>
    </head><body>
        <div class="reading-area">
            <main class="text-column">
                <p><a href="{url_for('story_library')}" style="color: #8B7D6C;">&larr; Back to Library</a> | <a href="{url_for('logout')}">Logout</a></p>
                <h1 class="chapter-title">{scene_data['title']}</h1>
                {processed_text_html}
            </main>
            <aside class="media-column-sticky">
                <img id="dynamic-scene-image" class="scene-image" src="{default_image_url}" alt="Scene Illustration">
            </aside>
        </div>
        <script>
            // --- JS INTERSECTION OBSERVER LOGIC ---
            const dynamicImage = document.getElementById('dynamic-scene-image');
            const triggers = document.querySelectorAll('.trigger-point-active');

            const options = {{
                root: null,
                rootMargin: '0px 0px -40% 0px',
                threshold: 0
            }};

            const observer = new IntersectionObserver((entries) => {{
                entries.forEach(entry => {{
                    if (entry.isIntersecting) {{
                        const imageUrl = entry.target.getAttribute('data-image-url');
                        if (dynamicImage.src !== imageUrl) {{
                            dynamicImage.style.opacity = '0';
                            setTimeout(() => {{
                                dynamicImage.src = imageUrl;
                                dynamicImage.style.opacity = '1';
                            }}, 300);
                        }}
                    }}
                }});
            }}, options);
            triggers.forEach(p => {{
                observer.observe(p);
            }});
        </script>
    </body></html>
    """
    return render_template_string(html_content)


@app.route('/media/<int:scene_id>/<path:filename>')
def secure_media_proxy(scene_id, filename):
    if 'user_id' not in session: return abort(401)
    
    # 1. FETCH NECESSARY SLUGS (Required for S3 Key Construction)
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # FIX: Join files table to get media type and ensure integrity
        sql_query = """
        SELECT st.book_slug, se.series_slug, f.file_type 
        FROM website.media_sync ms
        JOIN website.files f ON ms.file_id = f.file_id
        JOIN website.scenes s ON ms.scene_id = s.scene_id
        JOIN website.chapters ch ON s.chapter_id = ch.chapter_id
        JOIN website.stories st ON ch.story_id = st.story_id
        JOIN website.series se ON st.series_id = se.series_id
        WHERE ms.scene_id = %s AND f.file_name = %s;
        """
        cur.execute(sql_query, (scene_id, filename))
        db_result = cur.fetchone()
        cur.close(); conn.close()

        if not db_result: 
            print(f"Proxy Error: Media mapping not found for scene {scene_id} and file {filename}.")
            return abort(404)
        
        # 2. GENERATE SECURE S3 URL
        signed_url = generate_signed_s3_url(
            db_result['series_slug'], db_result['book_slug'], filename, db_result['file_type']
        )
        
        if signed_url:
            # 3. REDIRECT: Send the browser to the secure, time-limited S3 link
            return redirect(signed_url, code=302)
        else:
            return abort(404)

    except Exception as e:
        print(f"CRITICAL PROXY ERROR: {e}")
        return abort(500)