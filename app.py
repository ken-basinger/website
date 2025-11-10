import os
from flask import Flask, render_template_string, Response, abort
from psycopg2.extras import RealDictCursor
import psycopg2 # Make sure you have this import
from pcloud import PyCloud

# --- 1. INITIALIZE APP (NO pCloud HERE YET) ---
app = Flask(__name__)

# Global variable to store the initialized client
pcloud_client = None

def initialize_pcloud_client():
    """Initializes the pCloud client by reading env variables."""
    global pcloud_client
    
    # Load secret credentials securely inside this function
    PCLOUD_EMAIL = os.environ.get('PCLOUD_EMAIL')
    PCLOUD_PASSWORD = os.environ.get('PCLOUD_PASSWORD')
    
    if not PCLOUD_EMAIL or not PCLOUD_PASSWORD:
        print("CRITICAL ERROR: PCLOUD_EMAIL or PCLOUD_PASSWORD is not set.")
        return None # Return None if credentials are missing
        
    try:
        # We know the error is here, so we wrap it for safety
        client = PyCloud(PCLOUD_EMAIL, PCLOUD_PASSWORD)
        print("SUCCESS: pCloud client initialized.")
        return client
    except Exception as e:
        print(f"ERROR: Failed to initialize pCloud client: {e}")
        # The 'NoneType' error is likely happening inside the PyCloud() call
        return None

# Use a decorator to initialize the client right after the app starts
@app.before_request
def setup_pcloud():
    """Initializes pCloud client before the first request is served."""
    global pcloud_client
    if pcloud_client is None:
        pcloud_client = initialize_pcloud_client()


# --- 2. UPDATE THE SECURE MEDIA PROXY ROUTE ---
# Change your existing proxy route to rely on the global client variable

@app.route('/')
def test_connection():
    # --- STATUS VARIABLES (Defined first) ---
    DB_URL = os.environ.get('DATABASE_URL')
    db_status = "? DB Connection FAILED"
    pcloud_status = "? pCloud FAILED"
    user_count = "N/A"
    
    # Check pCloud status using the global client if initialized
    global pcloud_client
    if pcloud_client:
        pcloud_status = "? pCloud Client Initialized"
    
    # --- TEMPORARY HTML OUTPUT (Defined second - FIXES NameError) ---
    # This ensures 'html_content' always exists, even if the DB fails below.
    # It will be overwritten if the DB connection succeeds.
    html_content = "" 

    # --- 1. Test PostgreSQL Connection & Query ---
    try:
        conn = psycopg2.connect(DB_URL, sslmode='require')
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Test query: Count users in your schema
        # NOTE: If this fails, the table or schema name is wrong.
        cur.execute('SELECT COUNT(user_id) FROM writing.users;') 
        count_result = cur.fetchone()
        user_count = count_result['count']
        
        db_status = f"? SUCCESS (User Count: {user_count})"
        
        cur.close()
        conn.close()
        
    except Exception as e:
        # If the connection fails, capture the error message to display
        db_status = f"? FAILED (DB Error: {e})"
    
    # --- 2. FINAL DISPLAY RESULTS ---
    # We define the HTML here, using the latest status of the variables
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head><title>System Check</title></head>
    <body style="font-family: sans-serif; padding: 20px;">
        <h1>Application Server Status Check</h1>
        <hr>
        <p style="font-size: 1.2em;"><strong>PostgreSQL Connection & Query:</strong> {db_status}</p>
        <p style="font-size: 1.2em;"><strong>pCloud Client Status:</strong> {pcloud_status}</p>
        <p style="margin-top: 30px;">If the database count is 0, your table is correctly created but empty, which is normal.</p>
    </body>
    </html>
    """
    
    # --- 3. RETURN STATEMENT ---
    return render_template_string(html_content)