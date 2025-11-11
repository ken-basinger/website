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
    

# --- 5. THE IMMERSIVE READER ROUTE ---
@app.route('/read/<int:scene_id>')
def read_scene(scene_id):
    # --- SECURITY GATE ---
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    # --- END SECURITY GATE ---

    DB_URL = os.environ.get('DATABASE_URL')
    scene_data = None
    media_triggers = []
    
    # 1. FETCH DATA AND TRIGGERS FROM DB VIEW
    try:
        conn = psycopg2.connect(DB_URL, sslmode='require')
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        sql_sync_query = "SELECT * FROM writing.scene_media_details WHERE scene_id = %s;"
        cur.execute(sql_sync_query, (scene_id,))
        results = cur.fetchall()
        cur.close()
        conn.close()

        if not results:
            return render_template_string("<h1>404</h1><p>Scene not found or no media triggers defined.</p>", 404)
        
        scene_data = {
            'title': results[0]['scene_title'],
            'raw_text': results[0]['scene_text'],
            'story_title': results[0]['story_title'],
            'series_slug': results[0]['series_slug'],
        }
        
        # Separate the multimedia triggers for the frontend
        for row in results:
            if row['media_type'] == 'image' and row['full_pcloud_media_path']:
                # The media_path uses the secure proxy route
                filename = os.path.basename(row['full_pcloud_media_path'])
                media_triggers.append({
                    'trigger_id': row['text_trigger_id'],
                    'media_path': url_for('secure_media_proxy', scene_id=scene_id, filename=filename),
                })
        
    except Exception as e:
        print(f"DATABASE ERROR during scene retrieval: {e}")
        return abort(500)

    # --- 2. GENERATE HTML (Text Segmentation and Trigger Insertion) ---
    
    # Split the raw text into a list of paragraphs
    paragraphs = scene_data['raw_text'].split('\n\n')
    processed_text_html = ""
    
    # Loop through each paragraph to insert unique IDs
    for i, p in enumerate(paragraphs):
        # Create the globally unique trigger ID: p-[scene ID]-[paragraph order]
        unique_trigger_id = f'p-{scene_id}-{i + 1}' 
        
        # Use this unique ID to find a matching event in the database results
        trigger_data = next((t for t in media_triggers if t['trigger_id'] == unique_trigger_id), None)
        
        if trigger_data:
            # If trigger exists, mark the paragraph with the unique ID and URL for the JS Intersection Observer
            processed_text_html += (
                f'<p id="{unique_trigger_id}" '
                f'data-image-url="{trigger_data["media_path"]}" '
                f'class="trigger-point-active">{p}</p>\n\n'
            )
        else:
            # Otherwise, just render the normal paragraph
            processed_text_html += f'<p>{p}</p>\n\n'

    # --- 3. RENDER FINAL PAGE with JS Logic ---
    
    default_image = media_triggers[0]['media_path'] if media_triggers else ''
    
    html_template = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <title>{scene_data['title']} | {scene_data['story_title']}</title>
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Tinos:wght@400;700&family=Cormorant+Garamond:wght@300;700&display=swap">
        
        <style> /* ... (Your elegant CSS remains here) ... */ </style>
    </head>
    <body>
        <div class="reading-area">
            <main class="text-column">
                <h1 class="chapter-title">{scene_data['title']}</h1>
                {processed_text_html}
                <div style="height: 50vh;">- End of Scene -</div>
            </main>
            
            <aside class="media-column-sticky">
                <img id="dynamic-scene-image" class="scene-image" src="{default_image}" alt="Scene Illustration">
            </aside>
        </div>

        <script>
            // ... (Your JavaScript Intersection Observer logic remains here) ...
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