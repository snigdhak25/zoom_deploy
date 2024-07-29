import requests
import json
import base64
import os
from datetime import datetime
import pytz
from flask import Flask, request, redirect, render_template_string, url_for
import logging
import urllib.parse

app = Flask(__name__)

# Zoom OAuth credentials
CLIENT_ID = '9B1ViQTeTPCS6FIiCQ8n0Q'
CLIENT_SECRET = 'jCHbcOvyUtWpcrNN3KCtK21jhAPietNT'
REDIRECT_URI = 'https://zoom-deploy-hcmv.onrender.com/zoom/callback'

TOKEN_FILE = 'zoom_tokens.json'
IST = pytz.timezone('Asia/Kolkata')  # IST Timezone

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Helper function to load tokens from a file
def load_tokens():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'r') as f:
            return json.load(f)
    return {}

# Helper function to save tokens to a file
def save_tokens(tokens):
    with open(TOKEN_FILE, 'w') as f:
        json.dump(tokens, f)

# Step 1: Get Authorization URL
@app.route('/')
def home():
    form_html = '''
    <style>
        body {
            font-family: Arial, sans-serif;
            background-color: #f4f4f9;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
        }
        form {
            background: #fff;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 0 10px rgba(0, 0, 0, 0.1);
            width: 100%;
            max-width: 400px;
        }
        label {
            display: block;
            margin: 10px 0 5px;
            font-weight: bold;
        }
        input, button {
            width: 100%;
            padding: 10px;
            margin: 5px 0;
            border: 1px solid #ccc;
            border-radius: 4px;
        }
        button {
            background: #007bff;
            color: #fff;
            border: none;
            cursor: pointer;
            margin-top: 10px;
        }
        button:hover {
            background: #0056b3;
        }
    </style>
    <form action="/schedule" method="post">
        <label for="topic">Meeting Topic:</label>
        <input type="text" id="topic" name="topic" required>
        <label for="date">Date (YYYY-MM-DD):</label>
        <input type="date" id="date" name="date" required>
        <label for="time">Time (HH:MM):</label>
        <input type="time" id="time" name="time" required>
        <button type="submit">Schedule Meeting</button>
    </form>
    '''
    return render_template_string(form_html)

@app.route('/schedule', methods=['POST'])
def schedule():
    try:
        topic = request.form['topic']
        date = request.form['date']
        time = request.form['time']
        start_time = f"{date}T{time}:00"
        start_time_ist = IST.localize(datetime.strptime(start_time, '%Y-%m-%dT%H:%M:%S'))
        start_time_utc = start_time_ist.astimezone(pytz.utc).isoformat()
        
        # Validate start_time_utc and topic before using them
        if not start_time_utc or not topic:
            raise ValueError("Start time or topic is missing")
        
        state_param = f"{start_time_utc}#{topic}"
        encoded_state = urllib.parse.quote(state_param)
        logger.info(f"Encoded state parameter for auth URL: {encoded_state}")
        
        # First attempt without prompt
        auth_url = (
            f"https://zoom.us/oauth/authorize?response_type=code&client_id={CLIENT_ID}&scope=meeting:write:meeting"
            f"&redirect_uri={REDIRECT_URI}&state={encoded_state}&prompt=none"
        )
        return redirect(auth_url)
    except Exception as e:
        logger.error(f"Error scheduling meeting: {e}")
        return f"Failed to schedule meeting: {e}"

@app.route('/zoom/callback')
def callback():
    try:
        code = request.args.get('code')
        encoded_state = request.args.get('state')
        error = request.args.get('error')
        
        if error:
            # If there's an error (likely because prompt=none failed), ask for login
            auth_url = (
                f"https://zoom.us/oauth/authorize?response_type=code&client_id={CLIENT_ID}&scope=meeting:write:meeting"
                f"&redirect_uri={REDIRECT_URI}&state={encoded_state}"
            )
            return redirect(auth_url)
        
        # Decode state parameter
        state = urllib.parse.unquote(encoded_state)
        logger.info(f"Decoded state parameter: {state}")
        
        # Split state to get start_time and topic
        if state and '#' in state:
            start_time, topic = state.split('#', 1)
        else:
            raise ValueError("State parameter is not properly formatted")

        token_url = "https://zoom.us/oauth/token"
        headers = {
            "Authorization": f"Basic {base64.b64encode((CLIENT_ID + ':' + CLIENT_SECRET).encode()).decode()}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI
        }
        response = requests.post(token_url, headers=headers, data=payload)
        response_data = response.json()

        if 'access_token' in response_data:
            save_tokens(response_data)
            access_token = response_data.get("access_token")
            join_url = schedule_meeting(access_token, start_time, topic)
            if join_url:
                return redirect(join_url)
            else:
                return "Failed to schedule meeting."
        else:
            return f"Failed to obtain access token: {response_data}"
    except Exception as e:
        return f"Failed to process callback: {e}"

# Step 3: Refresh Access Token
def refresh_access_token(refresh_token):
    try:
        token_url = "https://zoom.us/oauth/token"
        headers = {
            "Authorization": f"Basic {base64.b64encode((CLIENT_ID + ':' + CLIENT_SECRET).encode()).decode()}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token
        }
        response = requests.post(token_url, headers=headers, data=payload)
        response_data = response.json()
        if 'access_token' in response_data:
            save_tokens(response_data)
        return response_data.get("access_token")
    except Exception as e:
        return None

# Step 4: Schedule a Meeting and Get Join URL
def schedule_meeting(access_token, start_time, topic):
    try:
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        
        meeting_details = {
            "topic": topic,
            "type": 2,
            "start_time": start_time,
            "duration": 60,
            "timezone": "UTC",
            "agenda": "This is an automated meeting",
            "settings": {
                "host_video": True,
                "participant_video": True,
                "join_before_host": False,
                "mute_upon_entry": True,
                "watermark": True,
                "use_pmi": False,
                "approval_type": 0,
                "registration_type": 1,
                "audio": "both",
                "auto_recording": "cloud"
            }
        }
        
        user_id = 'me'
        response = requests.post(f'https://api.zoom.us/v2/users/{user_id}/meetings', headers=headers, json=meeting_details)
        
        if response.status_code == 201:
            meeting = response.json()
            join_url = meeting.get('join_url')
            return join_url
        else:
            return None
    except Exception as e:
        return None

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
