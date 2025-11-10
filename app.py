import os
from flask import Flask, render_template_string, Response, abort
# ... other imports ...
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

@app.route('/media/<path:filename>')
def secure_media_proxy(filename):
    global pcloud_client

    if pcloud_client is None:
        # Attempt initialization one last time if it failed earlier
        pcloud_client = initialize_pcloud_client()
        if pcloud_client is None:
            return abort(503) # Service unavailable

    # ... The rest of your proxy logic (getfile, content_type, Response) remains the same ...
    # e.g., pcloud_path = f"/My Private Stories/Images/{filename}"
    # file_data = pcloud_client.getfile(path=pcloud_path).read() 
    # return Response(file_data, mimetype=content_type)
    # ...