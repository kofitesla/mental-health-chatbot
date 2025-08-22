import os
from flask import Flask, request, jsonify, render_template, redirect, url_for, session, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import google.generativeai as genai
from datetime import datetime
import json
from functools import wraps

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "supersecretkey")

# Configure Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Configure Gemini API
genai.configure(api_key=os.getenv("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-2.5-pro")

# Simple file-based user storage (use database in production)
USERS_FILE = 'users.json'
USER_DATA_DIR = 'user_data'

# Create user data directory if it doesn't exist
os.makedirs(USER_DATA_DIR, exist_ok=True)

# Initialize users file if it doesn't exist
if not os.path.exists(USERS_FILE):
    with open(USERS_FILE, 'w') as f:
        json.dump({}, f)

class User(UserMixin):
    def __init__(self, username):
        self.id = username
        self.username = username

@login_manager.user_loader
def load_user(username):
    users = load_users()
    if username in users:
        return User(username)
    return None

def load_users():
    with open(USERS_FILE, 'r') as f:
        return json.load(f)

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f)

def get_user_data_file(username, data_type):
    return os.path.join(USER_DATA_DIR, f"{username}_{data_type}.json")

def load_user_data(username, data_type):
    file_path = get_user_data_file(username, data_type)
    if os.path.exists(file_path):
        with open(file_path, 'r') as f:
            return json.load(f)
    return []

def save_user_data(username, data_type, data):
    file_path = get_user_data_file(username, data_type)
    with open(file_path, 'w') as f:
        json.dump(data, f)

# Mental health system prompt (same as before)
SYSTEM_PROMPT = """You are a compassionate mental health support chatbot. Your role is to:

1. Provide empathetic, non-judgmental emotional support
2. Use active listening techniques and validate feelings
3. Suggest healthy coping strategies and self-care practices
4. Recognize signs of crisis and provide appropriate resources
5. NEVER diagnose mental health conditions or provide medical advice
6. Encourage professional help when appropriate
7. Maintain appropriate boundaries as a support tool, not a replacement for therapy

Crisis Resources:
- National Suicide Prevention Lifeline: 988 (US)
- Crisis Text Line: Text HOME to 741741
- International Association for Suicide Prevention: https://www.iasp.info/resources/Crisis_Centres/

Always prioritize user safety and well-being. If someone expresses suicidal thoughts or immediate danger, provide crisis resources immediately."""

@app.route("/")
def index():
    if not current_user.is_authenticated:
        return redirect(url_for('login'))
    
    # Load user-specific chat log
    chat_log = load_user_data(current_user.username, 'chat_log')
    
    # Initialize with welcome message if empty
    if not chat_log:
        welcome_msg = {
            "sender": "assistant", 
            "text": f"Hello {current_user.username}! I'm here to provide compassionate mental health support. I'm not a replacement for professional therapy, but I'm here to listen and help you through difficult moments. How are you feeling today?",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
        }
        chat_log.append(welcome_msg)
        save_user_data(current_user.username, 'chat_log', chat_log)
    
    return render_template("index.html", log=chat_log, username=current_user.username)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        
        if not username or not password:
            flash("Username and password are required", "error")
            return redirect(url_for('register'))
        
        users = load_users()
        
        if username in users:
            flash("Username already exists", "error")
            return redirect(url_for('register'))
        
        # Create new user
        users[username] = {
            "password_hash": generate_password_hash(password),
            "created_at": datetime.now().isoformat()
        }
        save_users(users)
        
        flash("Registration successful! Please log in.", "success")
        return redirect(url_for('login'))
    
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        
        users = load_users()
        
        if username in users and check_password_hash(users[username]["password_hash"], password):
            user = User(username)
            login_user(user)
            return redirect(url_for('index'))
        
        flash("Invalid username or password", "error")
    
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route("/chat", methods=["POST"])
@login_required
def chat():
    user_input = request.json.get("message")
    if not user_input:
        return jsonify({"error": "No message provided"}), 400

    # Load user's chat log
    chat_log = load_user_data(current_user.username, 'chat_log')

    # Check for crisis keywords
    crisis_keywords = ["suicide", "kill myself", "end it all", "not worth living", "hurt myself"]
    is_crisis = any(keyword in user_input.lower() for keyword in crisis_keywords)

    # Add user message to chat log
    user_msg = {
        "sender": "user", 
        "text": user_input,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    chat_log.append(user_msg)

    # Prepare conversation for Gemini API
    gemini_conversation_history = [
        {"role": "user", "parts": [{"text": SYSTEM_PROMPT}]},
        {"role": "model", "parts": [{"text": "I understand my role as a compassionate mental health support chatbot. I'm here to listen, provide emotional support, and help you navigate difficult feelings while prioritizing your safety and well-being. How can I support you today?"}]}
    ]

    # Add recent chat history for context (last 10 messages)
    recent_messages = chat_log[-11:-1] if len(chat_log) > 1 else []
    for msg in recent_messages:
        role = "user" if msg["sender"] == "user" else "model"
        gemini_conversation_history.append({
            "role": role, 
            "parts": [{"text": msg["text"]}]
        })

    # Add current user input
    gemini_conversation_history.append({
        "role": "user", 
        "parts": [{"text": user_input}]
    })

    # Generate response using Gemini
    try:
        response = model.generate_content(gemini_conversation_history)
        bot_reply = response.text

        # If crisis detected, prepend crisis resources
        if is_crisis:
            crisis_response = """🆘 **I'm concerned about you and want to help immediately.** 

**CRISIS RESOURCES:**
• **Call 988** - National Suicide Prevention Lifeline (US)
• **Text HOME to 741741** - Crisis Text Line
• **Call 911** if in immediate danger

You are not alone, and your life has value. Please reach out to one of these resources right away.

"""
            bot_reply = crisis_response + bot_reply

    except Exception as e:
        print(f"Error generating content from Gemini: {e}")
        bot_reply = "I'm experiencing technical difficulties right now. If you're in crisis, please call 988 (Suicide Prevention Lifeline) or 911 for immediate help. I'll be back to support you soon."

    # Add bot reply to chat log
    bot_msg = {
        "sender": "assistant", 
        "text": bot_reply,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    chat_log.append(bot_msg)
    
    # Save updated chat log
    save_user_data(current_user.username, 'chat_log', chat_log)
    
    return jsonify({"response": bot_reply})

@app.route("/mood", methods=["GET", "POST"])
@login_required
def mood():
    # Load user's journal entries
    journal_entries = load_user_data(current_user.username, 'journal_entries')
    
    if request.method == "POST":
        mood = request.form.get("mood")
        thoughts = request.form.get("thoughts")
        
        if mood and thoughts:
            entry = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "mood": mood,
                "thoughts": thoughts,
                "mood_score": get_mood_score(mood)
            }
            journal_entries.append(entry)
            save_user_data(current_user.username, 'journal_entries', journal_entries)
        
        return redirect(url_for("mood"))
    
    return render_template("mood.html", entries=journal_entries, username=current_user.username)

def get_mood_score(mood):
    """Convert mood to numerical score for tracking trends"""
    mood_scores = {
        "terrible": 1,
        "bad": 2,
        "okay": 3,
        "good": 4,
        "great": 5
    }
    return mood_scores.get(mood.lower(), 3)

@app.route("/resources")
@login_required
def resources():
    """Mental health resources page"""
    return render_template("resources.html", username=current_user.username)

@app.route("/api/mood-trends")
@login_required
def mood_trends():
    """API endpoint for mood trend data"""
    journal_entries = load_user_data(current_user.username, 'journal_entries')
    
    if not journal_entries:
        return jsonify([])
    
    trends = []
    for entry in journal_entries[-30:]:  # Last 30 entries
        trends.append({
            "date": entry["timestamp"].split()[0],
            "score": entry["mood_score"]
        })
    
    return jsonify(trends)

@app.route("/clear-chat", methods=["POST"])
@login_required
def clear_chat():
    """Clear chat history"""
    save_user_data(current_user.username, 'chat_log', [])
    return jsonify({"status": "cleared"})

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return render_template("404.html"), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template("500.html"), 500

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)