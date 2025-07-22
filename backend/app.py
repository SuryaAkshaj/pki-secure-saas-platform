from flask import Flask, jsonify, request
import os

app = Flask(__name__)

# Simulate multi-tenant data
TENANTS = {
    "tenant1": {"data": "Welcome Tenant 1"},
    "tenant2": {"data": "Welcome Tenant 2"}
}

@app.route("/api/<tenant>")
def get_tenant_data(tenant):
    if tenant in TENANTS:
        return jsonify({"status": "success", "tenant": tenant, "data": TENANTS[tenant]["data"]})
    return jsonify({"status": "error", "message": "Tenant not found"}), 404

@app.route("/")
def index():
    return jsonify({"message": "Secure SaaS Platform - PKI Auth Enabled"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
