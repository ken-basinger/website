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
    db_status = "? FAILED (No connection attempt made)"
    pcloud_status = "? FAILED (Client not initialized)"
    user_count = "N/A"
    
    # --- A. DEFINE DEFAULT HTML_CONTENT HERE (Fixes the NameError) ---
    # This provides a default value in case the entire try/except block fails.
    html_content = "<h1>Server Error: Could not render status page.</h1>" 
    
    # --- B. Test PostgreSQL Connection & Query ---
    try:
        # ... (Your connection and query logic remains here) ...
        
        db_status = f"? SUCCESS (User Count: {user_count})"
        
        # ... (Closing database connection) ...
        
    except Exception as e:
        db_status = f"? FAILED (DB Error: {e})"    
    # --- B. Test pCloud Connection ---
    # ... logic remains the same ...
    
    # --- C. Display Results ---
    # ... HTML code to show the results ...
    return render_template_string(html_content)