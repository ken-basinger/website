import os
import secrets
import posixpath 
from flask import Flask, render_template_string, redirect, url_for, request, session, Response, abort
import psycopg2
from psycopg2.extras import RealDictCursor
from werkzeug.security import check_password_hash
from pcloud_sdk import PCloudSDK  
from io import BytesIO

# --- 1. INITIALIZE APP AND CLIENTS ---
app = Flask(__name__)

# Load environment variables
DB_URL = os.environ.get('DATABASE_URL')
PCLOUD_EMAIL = os.environ.get('PCLOUD_EMAIL')
PCLOUD_PASSWORD = os.environ.get('PCLOUD_PASSWORD')
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(16))

pcloud_client = None

def initialize_pcloud_client():
    """Initializes the pCloud client using the correct two-step login procedure."""
    
    if not PCLOUD_EMAIL or not PCLOUD_PASSWORD:
        print("CRITICAL ERROR: PCLOUD_EMAIL or PCLOUD_PASSWORD is not set.")
        return None
    try:
        # STEP 1: Initialize the client object without arguments (Fixes keyword argument error)
        client = PCloudSDK()
        
        # STEP 2: Call the separate login method using the credentials
        client.login(email=PCLOUD_EMAIL, password=PCLOUD_PASSWORD)
        
        print("SUCCESS: pCloud client initialized.")
        return client
    except Exception as e:
        print(f"ERROR: Failed to initialize pCloud client: {e}")
        return None

@app.before_request
def setup_pcloud():
    """Initializes pCloud client before the first request is served."""
    global pcloud_client
    if pcloud_client is None:
        pcloud_client = initialize_pcloud_client()


# =======================================================
# == MODULAR FUNCTION: FILE REGISTRATION/LOOKUP HELPER ==
# =======================================================

def register_or_get_id(scene_id, file_name, book_slug, series_slug, media_type):
    """
    Checks local DB for pCloud File ID. If missing, looks up ID via pCloud API and inserts it.
    """
    global pcloud_client
    
    if pcloud_client is None: return None

    try:
        conn = psycopg2.connect(DB_URL, sslmode='require')
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # --- A. CHECK LOCAL REGISTRY (writing.files) ---
        cur.execute("SELECT pcloud_file_id, file_id FROM writing.files WHERE file_name = %s;", (file_name,))
        file_record = cur.fetchone()

        if file_record and file_record.get('pcloud_file_id'):
            # ID found locally. Now check if media_sync link exists.
            local_file_id = file_record['file_id']
            cur.execute("SELECT 1 FROM writing.media_sync WHERE scene_id = %s AND file_id = %s;", (scene_id, local_file_id))
            
            if cur.fetchone():
                 cur.close(); conn.close()
                 return file_record['pcloud_file_id']
            # If media_sync link is missing, we create it below (after API lookup)

        # --- B. REGISTER NEW FILE (If ID is missing locally) ---
        
        media_folder = 'images' if media_type == 'image' else 'audio'
        # FINAL PATH CONSTRUCTION: The server looks in this path for the file name
        pcloud_path = f"/media/series/{series_slug}/{book_slug}/scenes/{media_folder}/{file_name}"
        
        # 1. Look up the ID via pCloud API (Slow Step)
        print(f"DEBUG: Auto-registration lookup for: {pcloud_path}")
        folder_path = posixpath.dirname(pcloud_path)
        
        # NOTE: Using the flat listfolder method to find the fileid
        folder_contents = pcloud_client.listfolder(path=folder_path)['contents']
        
        file_metadata = next((item for item in folder_contents if item.get('name') == file_name), None)
        
        if not file_metadata or not file_metadata.get('fileid'):
            print(f"ERROR: File '{file_name}' not found on pCloud at path: {folder_path}")
            cur.close(); conn.close()
            return None 

        pcloud_file_id = file_metadata['fileid']
        
        # 2. Insert the new file and LINK the media_sync record
        
        # Insert file into registry
        cur.execute("""
            INSERT INTO writing.files (pcloud_file_id, file_name, file_type)
            VALUES (%s, %s, %s) ON CONFLICT (file_name) DO UPDATE SET pcloud_file_id = EXCLUDED.pcloud_file_id
            RETURNING file_id;
        """, (str(pcloud_file_id), file_name, media_type))
        local_file_id = cur.fetchone()['file_id']
        
        # Link the scene to the new file
        cur.execute("""
            INSERT INTO writing.media_sync (scene_id, text_trigger_id, media_type, file_id)
            VALUES (%s, %s, %s, %s) 
            ON CONFLICT (scene_id, text_trigger_id) DO UPDATE SET file_id = EXCLUDED.file_id;
        """, (scene_id, f'p-{scene_id}-1', media_type, local_file_id))
        
        conn.commit()
        print(f"? AUTO-REGISTERED: {file_name} with pCloud ID {pcloud_file_id}.")
        
        cur.close(); conn.close()
        return str(pcloud_file_id) # Return the found pCloud ID

    except Exception as e:
        if 'conn' in locals() and conn: conn.rollback()
        print(f"CRITICAL FILE REGISTRATION CRASH: {e}")
        return None


# --- 2. THE LOGIN / LOGOUT ROUTES (Security Gate) ---

@app.route('/login', methods=['GET'])
def login_page():
    if session.get('user_id'):
        return redirect(url_for('story_library'))
    
    error_message = session.pop('login_error', '')

    html_content = f"""
    <!DOCTYPE html><html><head><title>Private Library Login</title>
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Tinos:wght@400;700&family=Cormorant+Garamond:wght@300;700&display=swap">
        <style>
            /* --- High-End Login CSS --- */
            body {{ background-color: #F8F6F0; color: #262626; font-family: 'Tinos', serif; margin: 0; padding: 0; }}
            .login-container {{ max-width: 400px; margin: 15vh auto; padding: 3rem; background-color: #FFFFFF; border-radius: 12px; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08); }}
            .login-title {{ font-family: 'Cormorant Garamond', serif; font-weight: 700; font-size: 2.5rem; color: #8B7D6C; margin-bottom: 0.5rem; }}
            label {{ display: block; margin-bottom: 0.5rem; font-weight: 700; }}
            input[type="text"], input[type="password"] {{ width: 100%; padding: 0.75rem; margin-bottom: 1.5rem; border: 1px solid #D9D9D9; border-radius: 6px; font-size: 1rem; box-sizing: border-box; }}
            .login-button {{ width: 100%; padding: 1rem; background-color: #8B7D6C; color: #FFFFFF; border: none; border-radius: 6px; font-size: 1.1rem; font-weight: 700; cursor: pointer; transition: background-color 0.3s; }}
            .error-message {{ color: #CC0000; font-weight: bold; margin-top: 1rem; }}
        </style>
    </head><body>
        <div class="login-container">
            <h1 class="login-title">Welcome</h1>
            <p class="error-message">{error_message}</p>
            <form method="POST" action="{url_for('login_submit')}"> 
                <div class="form-group"><label for="username">Username or Email</label>
                    <input type="text" id="username" name="username" required></div>
                <div class="form-group"><label for="password">Password</label>
                    <input type="password" id="password" name="password" required></div>
                <button type="submit" class="login-button">Access Stories</button>
            </form>
        </div>
    </body></html>
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
        cur.execute("SELECT user_id, username, password_hash FROM writing.users WHERE username = %s OR email = %s;", (username_or_email, username_or_email))
        user = cur.fetchone()
        cur.close(); conn.close()
    except Exception as e:
        session['login_error'] = "Authentication service unavailable (DB error)."
        return redirect(url_for('login_page'))

    if user and check_password_hash(user['password_hash'], password_input):
        session['user_id'] = user['user_id']
        session['username'] = user['username']
        session.pop('login_error', None)
        return redirect(url_for('story_library'))
    else:
        session['login_error'] = "Incorrect username or password."
        return redirect(url_for('login_page'))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))


# --- 3. THE STORY LIBRARY PAGE (The Functional Root) ---

@app.route('/')
def story_library():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    
    stories = []
    
    try:
        conn = psycopg2.connect(DB_URL, sslmode='require')
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        sql_query = """
        SELECT 
            s.story_id, s.story_title, s.book_slug, se.series_slug
        FROM writing.stories s
        JOIN writing.series se ON s.series_id = se.series_id;
        """
        cur.execute(sql_query)
        stories = cur.fetchall()
        cur.close(); conn.close()

    except Exception as e:
        print(f"ERROR: Failed to fetch story list: {e}")
    
    # --- RENDER THE LIBRARY HTML ---
    story_list_html = ""
    if stories:
        for story in stories:
            # Construct the link to the first scene (hardcoded scene_id=1 for now)
            scene_link = url_for('read_scene', scene_id=1) 
            
            story_list_html += f"""
            <div style="border: 1px solid #ccc; padding: 15px; margin-bottom: 10px; border-radius: 8px;">
                <h3 style="margin: 0; color: #8B7D6C;">{story['story_title']} ({story['series_slug']})</h3>
                <p>Book Slug: {story['book_slug']}</p>
                <p><a href="{scene_link}">Start Reading (Test Link)</a></p>
            </div>
            """
    else:
        story_list_html = "<p>No stories found. Check your database links.</p>"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head><title>Private Library</title></head>
    <body style="font-family: sans-serif; padding: 40px; background-color: #F8F6F0;">
        <h1>Welcome, {session.get('username', 'Reader')}!</h1>
        <p><a href="{url_for('logout')}">Logout</a></p>
        <hr>
        <h2>Your Private Library</h2>
        {story_list_html}
    </body>
    </html>
    """
    return render_template_string(html_content)


# --- 4. THE SECURE MEDIA PROXY ROUTE ---
@app.route('/media/<int:scene_id>/<path:filename>')
def secure_media_proxy(scene_id, filename):
    # SECURITY GATE
    if 'user_id' not in session: return abort(401)
    if pcloud_client is None: return abort(503)

    DB_URL = os.environ.get('DATABASE_URL')
    
    # 1. QUERY DATABASE to get the slugs and media type
    try:
        conn = psycopg2.connect(DB_URL, sslmode='require')
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Query simplified to fetch only path-defining data
        sql_query = """
        SELECT st.book_slug, se.series_slug, ms.media_type
        FROM writing.media_sync ms
        JOIN writing.scenes s ON ms.scene_id = s.scene_id
        JOIN writing.chapters ch ON s.chapter_id = ch.chapter_id
        JOIN writing.stories st ON ch.story_id = st.story_id
        JOIN writing.series se ON st.series_id = se.series_id
        WHERE ms.scene_id = %s AND ms.file_name = %s;
        """
        cur.execute(sql_query, (scene_id, filename))
        db_result = cur.fetchone()
        
        cur.close(); conn.close()

        if not db_result:
            return abort(404)
        
        book_slug = db_result['book_slug']
        series_slug = db_result['series_slug']
        media_type = db_result['media_type']
        
    except Exception as e:
        print(f"DATABASE QUERY CRASH in Proxy: {e}")
        return abort(500)

    # 2. CRITICAL: GET THE FILE ID (Auto-Registering if necessary)
    pcloud_file_id = register_or_get_id(
        scene_id, filename, book_slug, series_slug, media_type
    )
    
    if pcloud_file_id is None:
        return abort(404) 

    # 3. DIRECTLY FETCH THE FILE CONTENT using the correct method and ID
    try:
        # Use the correct, required function signature: client.file.download(fileid=...)
        file_stream = pcloud_client.file.download(fileid=int(pcloud_file_id)) 
        file_data = file_stream.read()
        
        # 4. STREAM RESPONSE
        content_type = 'image/jpeg' if media_type == 'image' else 'audio/mpeg'
        
        response = Response(file_data, mimetype=content_type)
        response.headers['Content-Disposition'] = f'inline; filename="{filename}"'
        return response

    except Exception as e:
        print(f"pCloud Access Failure: {e}")
        return abort(404)


# --- 5. THE IMMERSIVE READER ROUTE ---
@app.route('/read/<int:scene_id>')
def read_scene(scene_id):
    # SECURITY GATE
    if 'user_id' not in session: return redirect(url_for('login_page'))

    DB_URL = os.environ.get('DATABASE_URL')
    
    # Initialize variables for safe template rendering
    scene_data = {
        'title': "Error Loading Scene", 
        'raw_text': "Error: Data retrieval failed. Check logs for database link errors.",
        'story_title': "N/A", 
        'series_slug': "N/A"
    }
    raw_triggers = []

    # 1. DATABASE FETCHING (The unified, stable query)
    try:
        conn = psycopg2.connect(DB_URL, sslmode='require')
        cur = conn.cursor(cursor_factory=RealDictCursor)

        sql_query = """
        SELECT
            s.scene_title, s.scene_text, 
            st.story_title, st.book_slug,
            se.series_slug,
            ms.text_trigger_id, ms.media_type, ms.media_file_path
        FROM writing.scenes s
        JOIN writing.chapters ch ON s.chapter_id = ch.chapter_id
        JOIN writing.stories st ON ch.story_id = st.story_id
        JOIN writing.series se ON st.series_id = se.series_id
        LEFT JOIN writing.media_sync ms ON ms.scene_id = s.scene_id
        WHERE s.scene_id = %s;
        """
        cur.execute(sql_query, (scene_id,))
        results = cur.fetchall()
        
        cur.close(); conn.close()

        if not results: return abort(404)

        # Assemble final data
        first_row = results[0] 
        scene_data = {
            'title': first_row['scene_title'],
            'raw_text': first_row['scene_text'],
            'story_title': first_row['story_title'],
            'series_slug': first_row['series_slug'],
        }
        raw_triggers = [row for row in results if row.get('text_trigger_id') is not None]

    except Exception as e:
        print(f"CRITICAL DATABASE LINKAGE ERROR: {e}")
        return abort(500)
    
    # --- 2. GENERATE HTML MARKERS AND STRUCTURE ---
    
    paragraphs = scene_data['raw_text'].split('\n\n')
    processed_text_html = ""
    media_triggers = []

    for row in raw_triggers:
        if row['media_type'] == 'image' and row.get('media_file_path'):
            filename = row['media_file_path'].split('/')[-1]
            media_triggers.append({
                'trigger_id': row['text_trigger_id'],
                'media_path': url_for('secure_media_proxy', scene_id=scene_id, filename=filename),
            })
            
    # Loop through paragraphs to insert unique IDs
    for i, p in enumerate(paragraphs):
        unique_trigger_id = f'p-{scene_id}-{i + 1}'
        trigger_data = next((t for t in media_triggers if t['trigger_id'] == unique_trigger_id), None)
        
        if trigger_data:
            processed_text_html += (
                f'<p id="{unique_trigger_id}" data-image-url="{trigger_data["media_path"]}" '
                f'class="trigger-point-active">{p}</p>\n\n'
            )
        else:
            processed_text_html += f'<p>{p}</p>\n\n'

    # --- 3. RENDER FINAL PAGE (WITH VISUAL FIXES) ---
    
    default_image = media_triggers[0]['media_path'] if media_triggers else 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'
    
    html_template = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <title>{scene_data['title']} | {scene_data['story_title']}</title>
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Tinos:wght@400;700&family=Cormorant+Garamond:wght@300;700&display=swap">
        
        <style>
            /* --- High-End Editorial Theme CSS (VISUAL FIXES) --- */
            body {{ background-color: #F8F6F0; color: #262626; font-family: 'Tinos', serif; margin: 0; padding: 0;}}
            
            .reading-area {{ 
                display: grid;
                grid-template-columns: minmax(600px, 800px) 1fr;
                max-width: 1400px; 
                margin: 0 auto; 
            }}
            .text-column {{ 
                padding: 3rem 4rem; 
                font-size: 1.25rem; 
                line-height: 1.8; 
            }}
            .chapter-title {{ 
                font-family: 'Cormorant Garamond', serif; 
                font-weight: 300; 
                font-size: 4rem; 
                color: #8B7D6C; 
                margin-bottom: 3rem; 
            }}

            .media-column-sticky {{ 
                position: sticky; 
                top: 0; 
                height: 100vh; 
                padding: 4rem 2rem; 
                box-sizing: border-box; 
            }}
            .scene-image {{ 
                width: 100%; 
                border-radius: 4px; 
                box-shadow: 0 5px 20px rgba(0, 0, 0, 0.1); 
                transition: opacity 0.3s ease; 
            }}
        </style>
    </head>
    <body>
        <div class="reading-area">
            <main class="text-column">
                <p><a href="{url_for('story_library')}" style="color: #8B7D6C;">&larr; Back to Library</a> | <a href="{url_for('logout')}">Logout</a></p>
                <h1 class="chapter-title">{scene_data['title']}</h1>
                {processed_text_html}
                <div style="height: 50vh;">- End of Scene -</div>
            </main>
            
            <aside class="media-column-sticky">
                <img id="dynamic-scene-image" class="scene-image" src="{default_image}" alt="Scene Illustration">
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
    </body>
    </html>
    """
    return render_template_string(html_template)


if __name__ == '__main__':
    app.run(debug=True)