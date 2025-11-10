import os
from flask import Flask, render_template_string, Response, abort
# ... other imports ...
from pcloud import PyCloud 
from psycopg2.extras import RealDictCursor

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
    db_status = "? FAILED"
    pcloud_status = "? FAILED"
    user_count = "N/A"
    
    # --- A. Test PostgreSQL Connection & Query ---
    try:
        # Connect using the secure DATABASE_URL variable
        # sslmode='require' is essential for Render connections
        conn = psycopg2.connect(DB_URL, sslmode='require')
        
        # Use RealDictCursor to fetch results as dictionary rows
        cur = conn.cursor(cursor_factory=RealDictCursor) 
        
        # Test query: Count the number of users in your new table
        cur.execute('SELECT COUNT(user_id) FROM writing.users;')
        count_result = cur.fetchone()
        user_count = count_result['count']
        
        db_status = f"? SUCCESS (User Count: {user_count})"
        
        cur.close()
        conn.close()        # ... checks for user count from writing.users table ...
    
    except Exception as e:
        db_status = f"? FAILED (DB Error: {e})"
    
    # --- B. Test pCloud Connection ---
    # ... logic remains the same ...
    
    # --- C. Display Results ---
    # ... HTML code to show the results ...
    return render_template_string(html_content)