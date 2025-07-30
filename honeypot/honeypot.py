from flask import Flask, request, render_template_string
import logging
import json
from datetime import datetime

app = Flask(__name__)

# Logging setup
logging.basicConfig(filename='honeypot.log', level=logging.INFO,
                    format='%(asctime)s - %(message)s')

# Honeypot HTML template
HONEYPOT_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Access Denied</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; background: #f8f9fa; }
        .container { max-width: 600px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); text-align: center; }
        .warning { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; padding: 20px; border-radius: 5px; margin: 20px 0; }
        .info { background: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; padding: 15px; border-radius: 5px; margin: 15px 0; }
        .icon { font-size: 48px; margin: 20px 0; }
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">🚨</div>
        <h1>Access Denied</h1>
        
        <div class="warning">
            <h3>⚠️ Security Alert</h3>
            <p><strong>Invalid Certificate Detected</strong></p>
            <p>Your access attempt has been logged and monitored.</p>
        </div>
        
        <div class="info">
            <h4>🔍 What Happened?</h4>
            <p>This is a <strong>honeypot system</strong> designed to detect unauthorized access attempts.</p>
            <p>Your request was intercepted because:</p>
            <ul style="text-align: left;">
                <li>No valid client certificate provided</li>
                <li>Invalid or expired certificate</li>
                <li>Unauthorized access attempt</li>
            </ul>
        </div>
        
        <div class="info">
            <h4>📊 Security Information</h4>
            <p><strong>Your IP:</strong> {{ client_ip }}</p>
            <p><strong>Timestamp:</strong> {{ timestamp }}</p>
            <p><strong>User Agent:</strong> {{ user_agent }}</p>
        </div>
        
        <p style="color: #6c757d; font-size: 14px; margin-top: 30px;">
            This incident has been logged for security analysis.
        </p>
    </div>
</body>
</html>
"""

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE"])
def catch_all(path):
    # Enhanced logging with more details
    attack_data = {
        "timestamp": datetime.now().isoformat(),
        "ip": request.remote_addr,
        "path": path,
        "method": request.method,
        "user_agent": request.headers.get('User-Agent', 'Unknown'),
        "headers": dict(request.headers),
        "query_params": dict(request.args),
        "client_cert": request.environ.get('SSL_CLIENT_CERT', 'None')
    }
    
    log_msg = f"🚨 HONEYPOT TRIGGERED - IP: {request.remote_addr}, Path: {path}, Method: {request.method}"
    logging.info(log_msg)
    logging.info(f"Attack details: {json.dumps(attack_data, indent=2)}")
    
    # Return HTML response for web browsers
    if request.headers.get('Accept', '').find('text/html') != -1:
        return render_template_string(HONEYPOT_TEMPLATE, 
                                   client_ip=request.remote_addr,
                                   timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                   user_agent=request.headers.get('User-Agent', 'Unknown')), 403
    
    # Return JSON for API requests
    return {"status": "error", "message": "Access Denied - Invalid Certificate"}, 403

@app.route("/health")
def health_check():
    return {"status": "healthy", "service": "honeypot"}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6000, debug=False)
