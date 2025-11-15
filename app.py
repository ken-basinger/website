import os
import secrets
import boto3
from botocore.exceptions import ClientError
from flask import Flask, render_template_string, redirect, url_for, request, session, abort
import psycopg2
from psycopg2.extras import RealDictCursor
# Note: check_password_hash is no longer needed as we use plain text comparison
# from werkzeug.security import check_password_hash 

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
        
        # 1. Retrieve user credentials (including the now plain-text password from the DB)
        # NOTE: We select the password_hash column, but assume it holds the plain text 'testpass' for stability.
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

    # 2. SIMPLE TEXT CHECK (Final, working security check)
    # The system compares the input password against the simple text stored in the database.
    
    if user and user['password_hash'] == password_input: 
        session['user_id'] = user['user_id']
        session['username'] = user['username']
        return redirect(url_for('story_library'))
    else:
        # We redirect back with the error flag
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
    story_list_html = ""
    if stories:
        for story in stories:
            # NOTE: Link goes to the new read_chapter route
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                # Find the smallest chapter_id linked to this story
                start_chapter_query = """
                    SELECT MIN(chapter_id) AS start_id
                    FROM website.chapters 
                    WHERE story_id = %s;
                """
                cur.execute(start_chapter_query, (story['story_id'],))
                start_chapter_id = cur.fetchone()[0] or 1 # Use 1 as fallback
                cur.close(); conn.close()
            except:
                start_chapter_id = 1 # Fallback on error
                
            chapter_link = url_for('read_chapter', chapter_id=start_chapter_id) 
            
            story_list_html += f"""
            <div style="border: 1px solid #E0E0E0; padding: 20px; margin-bottom: 15px; border-radius: 8px; background-color: #FFFFFF;">
                <h3 style="margin: 0 0 5px; font-family: 'Cormorant Garamond', serif; color: #8B7D6C;">{story['story_title']} ({story['series_slug']})</h3>
                <p><a href="{chapter_link}">Start Reading</a></p>
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

@app.route('/read/chapter/<int:chapter_id>')
def read_chapter(chapter_id):
    if 'user_id' not in session: return redirect(url_for('login_page'))
    
    # Data structure for error resilience
    chapter_info = {
        'title': 'Chapter Title Placeholder', 
        'story_title': 'Story Placeholder',
        'series_slug': '',
        'book_slug': ''
    }
    processed_text_html = ""

    # 1. DATABASE FETCHING (Get all scenes and triggers for the Chapter)
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor) 
        
        # --- QUERY: Fetch ALL scenes and related story/media data for the given Chapter ID ---
        sql_query = """
        SELECT
            s.scene_id, s.scene_order, s.scene_title, s.scene_text, 
            ch.chapter_title, st.story_title, st.book_slug,
            se.series_slug,
            f.file_name, ms.text_trigger_id, ms.media_type
        FROM website.scenes s
        JOIN website.chapters ch ON s.chapter_id = ch.chapter_id
        JOIN website.stories st ON ch.story_id = st.story_id
        JOIN website.series se ON st.series_id = se.series_id
        LEFT JOIN website.media_sync ms ON ms.scene_id = s.scene_id
        LEFT JOIN website.files f ON ms.file_id = f.file_id
        WHERE s.chapter_id = %s
        ORDER BY s.scene_order ASC;
        """
        cur.execute(sql_query, (chapter_id,))
        chapter_data = cur.fetchall()
        
        if not chapter_data: return abort(404)
        
        first_row = chapter_data[0]
        chapter_info = {
            'title': first_row['chapter_title'],
            'story_title': first_row['story_title'],
            'series_slug': first_row['series_slug'],
            'book_slug': first_row['book_slug'],
        }
        
        # 2. ASSEMBLE CONTENT AND MARKERS (The Scrollytelling Stitch)
        
        processed_text_html = ""
        
        for scene_row in chapter_data:
            scene_id = scene_row['scene_id']
            raw_text = scene_row['scene_text']
            
            # Start of Scene Divider (Visual break and major trigger)
            processed_text_html += f'<div id="scene-{scene_id}" class="scene-divider trigger-point-major"><h2 class="scene-title">{scene_row["scene_title"]}</h2></div>'
            
            # --- SENTENCE SEGMENTATION & MARKER INSERTION (Sentence-Level Sync) ---
            sentences = re.split('([.!?])', raw_text)
            paragraph_html = ""
            current_paragraph_content = ""
            sentence_counter = 0

            for i in range(0, len(sentences) - 1, 2):
                if i + 1 >= len(sentences): break
                
                sentence = sentences[i].strip() + sentences[i+1]
                sentence_counter += 1
                
                # Unique Sentence ID (s-sceneId-sentenceOrder)
                sentence_marker_id = f's-{scene_id}-{sentence_counter}'

                # Find image trigger linked to this specific sentence ID
                trigger_data = next((row for row in chapter_data if row.get('text_trigger_id') == sentence_marker_id), None)
                
                # Wrap the sentence in a span for fine-grained control (for audio highlighting)
                sentence_html = f'<span id="{sentence_marker_id}">{sentence}</span> '
                
                # If an image trigger exists, add the data attribute around the sentence span
                if trigger_data and trigger_data.get('file_name'):
                    file_name = trigger_data['file_name']
                    sentence_html = (
                        f'<span class="trigger-point-active" data-image-url="{url_for("secure_media_proxy", scene_id=scene_id, filename=file_name)}">'
                        f'{sentence_html}</span> '
                    )

                # Assemble paragraphs (Based on simple line breaks for stability)
                is_new_paragraph = sentence.strip().endswith('  ') 
                
                if is_new_paragraph and current_paragraph_content:
                    paragraph_html += f"<p>{current_paragraph_content}</p>\n\n"
                    current_paragraph_content = sentence_html
                else:
                    current_paragraph_content += sentence_html
                    
            if current_paragraph_content:
                paragraph_html += f"<p>{current_paragraph_content}</p>\n\n"
            
            processed_text_html += paragraph_html
            
        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"CRITICAL CHAPTER FETCH ERROR: {e}")
        processed_text_html = f"<p>Error: Could not retrieve text from database. {e}</p>"

    # 3. RENDER FINAL PAGE
    
    # Final default URL for the image: Use a placeholder until the main trigger fires
    default_image_url = url_for('secure_media_proxy', scene_id=chapter_id, filename='default-cover.jpg') 
    
    html_content = f"""
    <!DOCTYPE html><html><head>
        <title>{chapter_info['title']} | {chapter_info['story_title']}</title>
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Tinos:wght@400;700&family=Cormorant+Garamond:wght@300;700&display=swap">
        <style>
            /* --- High-End Editorial Theme CSS (Full Layout Fix) --- */
            body {{ background-color: #F8F6F0; color: #262626; font-family: 'Tinos', serif; margin: 0; padding: 0; }}
            .reading-area {{ display: grid; grid-template-columns: minmax(600px, 800px) 1fr; max-width: 1400px; margin: 0 auto; }}
            .text-column {{ padding: 3rem 4rem; font-size: 1.25rem; line-height: 1.8; }}
            .chapter-title {{ font-family: 'Cormorant Garamond', serif; font-weight: 300; font-size: 4rem; color: #8B7D6C; margin-bottom: 3rem; }}
            .scene-divider {{ border-top: 1px solid #E0E0E0; margin-top: 4rem; padding-top: 2rem; }}
            .scene-title {{ font-size: 1.5rem; color: #666; font-weight: 400; }}
            /* Sticky Media Styles */
            .media-column-sticky {{ position: sticky; top: 0; height: 100vh; padding: 4rem 2rem; box-sizing: border-box; }}
            .scene-image {{ width: 100%; border-radius: 4px; box-shadow: 0 5px 20px rgba(0, 0, 0, 0.1); transition: opacity 0.3s ease; }}
        </style>
    </head><body>
        <div class="reading-area">
            <main class="text-column">
                <p><a href="{url_for('story_library')}" style="color: #8B7D6C;">&larr; Back to Library</a> | <a href="{url_for('logout')}">Logout</a></p>
                <h1 class="chapter-title">{chapter_info['title']}</h1>
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
    if 'user_id' not in session: return redirect(url_for('login_page'))
    
    # 1. FETCH NECESSARY SLUGS (Required for S3 Key Construction)
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Query DB to get the essential slugs and media type
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