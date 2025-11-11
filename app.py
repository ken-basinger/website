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

# Load environment variables (Render automatically injects these)
DB_URL = os.environ.get('DATABASE_URL')
PCLOUD_EMAIL = os.environ.get('PCLOUD_EMAIL')
PCLOUD_PASSWORD = os.environ.get('PCLOUD_PASSWORD')
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(16))

# Global client initialization (as perfected earlier)
pcloud_client = None

def initialize_pcloud_client():
    # ... (Initialization logic remains here) ...
    if not PCLOUD_EMAIL or not PCLOUD_PASSWORD:
        print("CRITICAL ERROR: PCLOUD_EMAIL or PCLOUD_PASSWORD is not set.")
        return None
    try:
        client = PyCloud(PCLOUD_EMAIL, PCLOUD_PASSWORD)
        print("SUCCESS: pCloud client initialized.")
        return client
    except Exception as e:
        print(f"ERROR: Failed to initialize pCloud client: {e}")
        return None

@app.before_request
def setup_pcloud():
    global pcloud_client
    if pcloud_client is None and PCLOUD_EMAIL and PCLOUD_PASSWORD:
        pcloud_client = initialize_pcloud_client()

# --- 2. THE LOGIN / LOGOUT ROUTES (Security Gate) ---

@app.route('/login', methods=['GET'])
def login_page():
    if session.get('user_id'):
        return redirect(url_for('story_library')) # Redirect to the final, single library route
    
    error_message = session.pop('login_error', '')

    html_content = f"""
    <!DOCTYPE html><html><head><title>Private Library Login</title>
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Tinos:wght@400;700&family=Cormorant+Garamond:wght@300;700&display=swap">
        <style> /* ... (Styles remain the same) ... */ </style>
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
    
    # ... (Authentication database check logic remains here) ...
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
        return redirect(url_for('story_library')) # Redirect to the correct, single library function
    else:
        session['login_error'] = "Incorrect username or password."
        return redirect(url_for('login_page'))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))


# --- 3. THE STORY LIBRARY PAGE (The Functional Root) ---

@app.route('/') # <-- THIS IS THE ONLY ROUTE FOR THE LIBRARY
def story_library():
    # --- SECURITY GATE ---
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    # --- END SECURITY GATE ---
    
    stories = []
    
    try:
        conn = psycopg2.connect(DB_URL, sslmode='require')
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # SQL to fetch ALL stories and their slugs for linking
        sql_query = """
        SELECT 
            st.story_id, st.story_title, st.book_slug, se.series_slug
        FROM writing.stories st
        JOIN writing.series se ON st.series_id = se.series_id;
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
                <p>Status: Available - Book Slug: {story['book_slug']}</p>
                <p><a href="{scene_link}">Start Reading (Test Link)</a></p>
            </div>
            """
    else:
        story_list_html = "<p>No stories found. Please add content to your database tables.</p>"

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


# --- 4. THE SECURE MEDIA PROXY ROUTE (Protected) ---
@app.route('/media/<int:scene_id>/<path:filename>')
def secure_media_proxy(scene_id, filename):
    # ... (This logic remains the same as before, waiting for final database integration) ...
    if 'user_id' not in session: return abort(401)
    if pcloud_client is None: return abort(503)

    # TEMPORARY TEST SUCCESS MESSAGE (Remove when fetching real files)
    if filename == 'ch03-sc02.png':
        return Response(f"Proxy SUCCESS: Authenticated access granted for {filename}.", mimetype='text/plain')
    return abort(404)
    

# =======================================================
# == MODULAR FUNCTION 1: DATABASE RETRIEVAL =============
# =======================================================

def get_scene_db_data(scene_id):
    """Fetches and consolidates all scene, story, and trigger data."""
    
    # --- Inside @app.route('/read/<int:scene_id>') def read_scene(scene_id): ---

   # Initializations
    DB_URL = os.environ.get('DATABASE_URL')
    
    # We define the variables the template relies on for safe rendering in case of error
    scene_data = {'title': "Error Loading Scene", 'raw_text': "Error: Data retrieval failed.", 
                  'story_title': "N/A", 'series_slug': "N/A"}
    raw_triggers = []

    try:
        conn = psycopg2.connect(DB_URL, sslmode='require')
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # --- 1. THE UNIFIED, ROBUST QUERY ---
        # This query performs ALL necessary JOINs (Scenes -> Chapters -> Stories -> Series)
        # and LEFT JOINs the media triggers in one efficient operation.
        sql_final_details = """
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
        cur.execute(sql_final_details, (scene_id,))
        results = cur.fetchall()
        
        cur.close()
        conn.close()

        if not results:
            # This handles cases where the scene doesn't exist or is missing a parent link
            return abort(404)

        # --- 2. ASSEMBLE FINAL DATA ---
        # Data is taken from the first row of the results (as story info is identical for all rows)
        first_row = results[0] 
        
        scene_data = {
            'title': first_row['scene_title'],
            'raw_text': first_row['scene_text'],
            'story_title': first_row['story_title'],
            'series_slug': first_row['series_slug'],
        }
        
        # Filter raw triggers (rows where media_sync data exists)
        raw_triggers = [row for row in results if row.get('text_trigger_id') is not None]

    except Exception as e:
        print(f"CRITICAL DATABASE LINKAGE ERROR: {e}")
        return abort(500)
    
# --- The rest of the function (HTML generation, etc.) follows here ---
# --- (The rest of the file relies on scene_data and raw_triggers being defined.) ---

# =======================================================
# == MODULAR FUNCTION 2: HTML/MARKER GENERATION =========
# =======================================================

def generate_scene_html(scene_id, data):
    """Segments raw text and inserts the unique HTML markers."""
    
    # Process triggers into a cleaner list for the frontend
    media_triggers = []

    # Only process image triggers for now
    for row in data['raw_triggers']:
        if row['media_type'] == 'image' and row.get('media_file_path'): 
            # We must use the full file path from the view for the proxy lookup!
            full_path = row['full_pcloud_media_path'] 
            
            # The proxy route needs the Scene ID AND the final filename
            filename = full_path.split('/')[-1] 

            media_triggers.append({
                'trigger_id': row['text_trigger_id'],
                # We send the final filename for the proxy to use as the route slug
                'media_path': url_for('secure_media_proxy', scene_id=scene_id, filename=filename),
            })
            
    paragraphs = data['scene']['scene_text'].split('\n\n')
    processed_text_html = ""
    
    # Loop through each paragraph to insert unique IDs
    for i, p in enumerate(paragraphs):
        # Create the globally unique trigger ID: p-[scene ID]-[paragraph order]
        unique_trigger_id = f'p-{scene_id}-{i + 1}'
        
        # Find a matching trigger in the processed list
        trigger_data = next((t for t in media_triggers if t['trigger_id'] == unique_trigger_id), None)
        
        if trigger_data:
            # If trigger exists, mark the paragraph for the Intersection Observer
            processed_text_html += (
                f'<p id="{unique_trigger_id}" '
                f'data-image-url="{trigger_data["media_path"]}" '
                f'class="trigger-point-active">{p}</p>\n\n'
            )
        else:
            # Render the paragraph normally
            processed_text_html += f'<p>{p}</p>\n\n'
            
    # The image source is the first media trigger found
    default_image = media_triggers[0]['media_path'] if media_triggers else ''
    
    # --- RENDER FINAL PAGE with JS Logic ---
    html_template = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <title>{data['scene']['scene_title']} | {data['story']['story_title']}</title>
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Tinos:wght@400;700&family=Cormorant+Garamond:wght@300;700&display=swap">
        <style>
            /* BASE AESTHETICS */
            body { background-color: #F8F6F0; color: #262626; font-family: 'Tinos', serif; margin: 0; padding: 0; }
            
            /* --- LAYOUT FIX: THE GRID --- */
            .reading-area { 
                display: grid;
                grid-template-columns: minmax(600px, 800px) 1fr; /* Text is wide, image is fixed sidebar */
                max-width: 1400px; 
                margin: 0 auto; 
            }
            
            /* TYPOGRAPHY FIXES */
            .text-column { 
                padding: 3rem 4rem; 
                font-size: 1.25rem; /* Now readable size */
                line-height: 1.8; /* Good spacing */ 
            }
            .chapter-title { 
                font-family: 'Cormorant Garamond', serif; 
                font-size: 4rem; 
                color: #8B7D6C; 
            }

            /* STICKY IMAGE FIX */
            .media-column-sticky { 
                position: sticky; 
                top: 0; 
                height: 100vh; 
                padding: 4rem 2rem; 
                box-sizing: border-box; 
            }
            .scene-image { 
                width: 100%; 
                border-radius: 4px; 
                box-shadow: 0 5px 20px rgba(0, 0, 0, 0.1); 
            }
        </style>
    </head>
    <body>
        <div class="reading-area">
            <main class="text-column">
                <p><a href="{url_for('story_library')}" style="color: #8B7D6C;">&larr; Back</a> | <a href="{url_for('logout')}" style="color: #8B7D6C;">Logout</a></p>
                <h1 class="chapter-title">{data['scene']['scene_title']}</h1>
                {processed_text_html}
            </main>
            
            <aside class="media-column-sticky">
                <img id="dynamic-scene-image" class="scene-image" src="{default_image}" alt="Scene Illustration">
            </aside>
        </div>
        <script> /* ... (Your JS Intersection Observer logic remains here) ... */ </script>
    </body>
    </html>
    """
    return html_template
    
# --- 5. THE IMMERSIVE READER ROUTE (The Coordinator) ---
@app.route('/read/<int:scene_id>')
def read_scene(scene_id):
    # --- SECURITY GATE ---
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    
    # 1. FETCH DATA (Call the modular DB function)
    data = get_scene_db_data(scene_id)
    
    # 2. HANDLE ERRORS
    if data is None:
        # Returns 404 if data not found or database crashed
        return abort(404) 

    # 3. GENERATE & RETURN HTML (Call the modular HTML function)
    html_template = generate_scene_html(scene_id, data)
    
    return render_template_string(html_template)

if __name__ == '__main__':
    app.run(debug=True)