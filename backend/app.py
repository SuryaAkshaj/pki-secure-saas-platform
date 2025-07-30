from flask import Flask, jsonify, request, render_template_string
import os
import logging

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Simulate multi-tenant data
TENANTS = {
    "tenant1": {"data": "Welcome Tenant 1", "plan": "premium"},
    "tenant2": {"data": "Welcome Tenant 2", "plan": "basic"}
}

# Simple HTML template for web interface
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Secure SaaS Platform</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }
        .container { max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .header { text-align: center; color: #2c3e50; margin-bottom: 30px; }
        .status { padding: 15px; border-radius: 5px; margin: 10px 0; }
        .success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .info { background: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }
        .tenant-card { background: #f8f9fa; padding: 20px; margin: 10px 0; border-radius: 5px; border-left: 4px solid #007bff; }
        .cert-info { background: #fff3cd; color: #856404; border: 1px solid #ffeaa7; padding: 10px; border-radius: 5px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔒 Secure SaaS Platform</h1>
            <p>PKI-based Authentication & Multi-Tenant Architecture</p>
        </div>
        
        <div class="status success">
            <h3>✅ Authentication Successful</h3>
            <p>You have accessed this platform with a valid client certificate.</p>
        </div>
        
        <div class="cert-info">
            <h4>🔐 Certificate Information</h4>
            <p><strong>Client Certificate:</strong> Valid</p>
            <p><strong>Authentication Method:</strong> Mutual TLS (mTLS)</p>
            <p><strong>Security Level:</strong> High</p>
        </div>
        
        <h3>🏢 Available Tenants</h3>
        <div class="tenant-card">
            <h4>Tenant 1 (Premium)</h4>
            <p><strong>Data:</strong> Welcome Tenant 1</p>
            <p><strong>Plan:</strong> Premium</p>
            <a href="/api/tenant1" style="color: #007bff;">View Details</a>
        </div>
        
        <div class="tenant-card">
            <h4>Tenant 2 (Basic)</h4>
            <p><strong>Data:</strong> Welcome Tenant 2</p>
            <p><strong>Plan:</strong> Basic</p>
            <a href="/api/tenant2" style="color: #007bff;">View Details</a>
        </div>
        
        <div class="status info">
            <h4>🔍 Security Features</h4>
            <ul>
                <li>PKI-based authentication (no passwords)</li>
                <li>Multi-tenant data isolation</li>
                <li>Honeypot threat detection</li>
                <li>Containerized architecture</li>
            </ul>
        </div>
    </div>
</body>
</html>
"""

@app.route("/api/<tenant>")
def get_tenant_data(tenant):
    # Log successful access
    client_cert = request.environ.get('SSL_CLIENT_CERT', 'No certificate')
    logger.info(f"Authorized access for tenant {tenant} with cert: {client_cert[:50]}...")
    
    if tenant in TENANTS:
        return jsonify({
            "status": "success", 
            "tenant": tenant, 
            "data": TENANTS[tenant]["data"],
            "plan": TENANTS[tenant]["plan"]
        })
    return jsonify({"status": "error", "message": "Tenant not found"}), 404

@app.route("/health")
def health_check():
    return jsonify({"status": "healthy", "service": "saas-backend"})

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
