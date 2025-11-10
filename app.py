import os
from flask import Flask, render_template_string, Response, abort
import psycopg2
from pcloud import PyCloud
from io import BytesIO

# --- 1. INITIALIZE APP AND CLIENTS ---
app = Flask(__name__)

# Load secret credentials securely from Render's Environment Variables
# Render automatically injects the DATABASE_URL
DB_URL = os.environ.get('DATABASE_URL')
PCLOUD_EMAIL = os.environ.get('PCLOUD_EMAIL')
PCLOUD_PASSWORD = os.environ.get('PCLOUD_PASSWORD')

# Initialize pCloud Client (This connects your server to your private media)
try:
    pcloud_client = PyCloud(PCLOUD_EMAIL, PCLOUD_PASSWORD)
    print("SUCCESS: pCloud client initialized.")
except Exception as e:
    print(f"ERROR: Failed to initialize pCloud client: {e}")
    pcloud_client = None

# --- 2. THE TEST ROUTE: Verifies Connectivity ---
@app.route('/')
def test_connection():
    db_status = "? FAILED"
    pcloud_status = "? FAILED"

    # A. Test PostgreSQL Connection
    try:
        conn = psycopg2.connect(DB_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute('SELECT 1;')
        db_status = "? SUCCESS (DB is reachable)"
        cur.close()
        conn.close()
    except Exception as e:
        db_status = f"? FAILED (DB Error: {e})"

    # B. Test pCloud Connection (List a folder as a simple test)
    if pcloud_client:
        try:
            pcloud_client.listfolder(folderid=0) # Tries to list the root folder
            pcloud_status = "? SUCCESS (pCloud API is reachable)"
        except Exception as e:
            pcloud_status = f"? FAILED (pCloud Error: {e})"
    
    # C. Display Results in a simple page
    # In a real app, this is where you'd render your story template.
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head><title>System Check</title></head>
    <body>
        <h1>Application Server Status</h1>
        <p><strong>PostgreSQL Status:</strong> {db_status}</p>
        <p><strong>pCloud Status:</strong> {pcloud_status}</p>
        <p>If both are SUCCESS, your application is correctly configured to connect to your data and media!</p>
    </body>
    </html>
    """
    return render_template_string(html_content)

# --- 3. THE SECURE MEDIA PROXY ROUTE (Core Functionality) ---
@app.route('/media/<path:filename>')
def secure_media_proxy(filename):
    # NOTE: In the final app, you must add a user authentication check here!
    # e.g., if not is_user_logged_in(): return abort(401)
    
    if not pcloud_client:
        return abort(503) # Service unavailable

    # The actual path on your pCloud drive where the files are stored
    # You MUST adjust this to match your actual folder structure
    pcloud_path = f"/My Private Stories/Images/{filename}"
    
    try:
        # Securely fetch the file content using the pCloud SDK
        file_data = pcloud_client.getfile(path=pcloud_path).read()
        
        # Determine the content type (MIME type)
        content_type = 'image/jpeg' if filename.lower().endswith(('.jpg', '.jpeg')) else 'image/png'
        
        # Stream the file content back to the user's browser
        return Response(file_data, mimetype=content_type)

    except Exception as e:
        print(f"Error serving file {filename}: {e}")
        return abort(404) # File not found


if __name__ == '__main__':
    # This runs only locally, not on the Render server
    app.run(debug=True)