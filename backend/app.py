from flask import Flask, jsonify, request, render_template_string, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
from flask_admin.form import SecureForm
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flasgger import Swagger, swag_from
import os
import logging
import jwt
import datetime
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import json

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///saas_platform.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SWAGGER'] = {
    'title': 'Secure SaaS Platform API',
    'uiversion': 3,
    'openapi': '3.0.2'
}

# Initialize extensions
db = SQLAlchemy(app)
CORS(app)
swagger = Swagger(app)
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)
limiter.init_app(app)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database Models
class Tenant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    domain = db.Column(db.String(120), unique=True)
    plan = db.Column(db.String(20), default='basic')  # basic, premium, enterprise
    status = db.Column(db.String(20), default='active')  # active, suspended, inactive
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    api_key = db.Column(db.String(64), unique=True)
    users = db.relationship('User', backref='tenant', lazy=True)
    certificates = db.relationship('Certificate', backref='tenant', lazy=True)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    role = db.Column(db.String(20), default='user')  # admin, user, viewer
    status = db.Column(db.String(20), default='active')
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenant.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    last_login = db.Column(db.DateTime)
    certificates = db.relationship('Certificate', backref='user', lazy=True)

class Certificate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    serial_number = db.Column(db.String(64), unique=True, nullable=False)
    common_name = db.Column(db.String(120), nullable=False)
    status = db.Column(db.String(20), default='active')  # active, revoked, expired
    issued_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    revoked_at = db.Column(db.DateTime)
    revocation_reason = db.Column(db.String(200))
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenant.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    cert_file_path = db.Column(db.String(200))
    key_file_path = db.Column(db.String(200))

class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    action = db.Column(db.String(100), nullable=False)
    resource = db.Column(db.String(100))
    details = db.Column(db.Text)
    ip_address = db.Column(db.String(45))

# Admin Views
class TenantAdmin(ModelView):
    column_list = ('name', 'domain', 'plan', 'status', 'created_at', 'user_count')
    column_searchable_list = ('name', 'domain')
    column_filters = ('plan', 'status', 'created_at')
    form_excluded_columns = ('users', 'certificates')
    
    def user_count(self, context, model, name):
        return len(model.users)

class UserAdmin(ModelView):
    column_list = ('username', 'email', 'role', 'status', 'tenant_id', 'created_at')
    column_searchable_list = ('username', 'email')
    column_filters = ('role', 'status', 'tenant_id')
    form_excluded_columns = ('certificates', 'last_login')
    
    def _format_tenant(self, context, model, name):
        if model.tenant:
            return model.tenant.name
        return 'N/A'
    
    column_formatters = {
        'tenant_id': _format_tenant
    }

class CertificateAdmin(ModelView):
    column_list = ('serial_number', 'common_name', 'status', 'tenant_id', 'user_id', 'issued_at', 'expires_at')
    column_searchable_list = ('common_name', 'serial_number')
    column_filters = ('status', 'tenant_id', 'user_id')
    form_excluded_columns = ('cert_file_path', 'key_file_path')
    
    def _format_tenant(self, context, model, name):
        if model.tenant:
            return model.tenant.name
        return 'N/A'
    
    def _format_user(self, context, model, name):
        if model.user:
            return model.user.username
        return 'N/A'
    
    column_formatters = {
        'tenant_id': _format_tenant,
        'user_id': _format_user
    }

# Initialize Admin
admin = Admin(app, name='Secure SaaS Admin', template_mode='bootstrap4')
admin.add_view(TenantAdmin(Tenant, db.session))
admin.add_view(UserAdmin(User, db.session))
admin.add_view(CertificateAdmin(Certificate, db.session))

# Utility Functions
def generate_api_key():
    import secrets
    return secrets.token_hex(32)

def log_audit(user_id, action, resource, details, ip_address):
    log = AuditLog(
        user_id=user_id,
        action=action,
        resource=resource,
        details=details,
        ip_address=ip_address
    )
    db.session.add(log)
    db.session.commit()

def generate_certificate(common_name, days=365):
    """Generate a new certificate for a user"""
    # Generate private key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    
    # Generate certificate
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Secure SaaS Platform"),
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
    ])
    
    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        private_key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.utcnow()
    ).not_valid_after(
        datetime.datetime.utcnow() + datetime.timedelta(days=days)
    ).add_extension(
        x509.BasicConstraints(ca=False, path_length=None), critical=True,
    ).add_extension(
        x509.KeyUsage(
            digital_signature=True,
            key_encipherment=True,
            key_agreement=False,
            key_cert_sign=False,
            crl_sign=False,
            content_commitment=False,
            data_encipherment=False,
            encipher_only=False,
            decipher_only=False
        ), critical=True,
    ).add_extension(
        x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False,
    ).sign(private_key, hashes.SHA256())
    
    return cert, private_key

# Routes
@app.route("/")
@limiter.limit("10 per minute")
def index():
    """Main dashboard for authenticated users"""
    client_cert = request.environ.get('SSL_CLIENT_CERT', None)
    
    if not client_cert:
        return redirect(url_for('admin.index'))
    
    # Extract user info from certificate
    try:
        cert = x509.load_pem_x509_certificate(client_cert.encode())
        cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        
        # Find user by certificate
        user = User.query.filter_by(username=cn).first()
        if not user:
            return jsonify({"error": "User not found"}), 404
            
        tenant = user.tenant
        
        return render_template_string(MAIN_DASHBOARD_TEMPLATE, 
                                   user=user, tenant=tenant)
    except Exception as e:
        logger.error(f"Certificate parsing error: {e}")
        return jsonify({"error": "Invalid certificate"}), 400

@app.route("/register")
def register():
    """User registration page"""
    return render_template_string(REGISTRATION_TEMPLATE)

@app.route("/certificates")
def certificates():
    """Certificate management page"""
    return render_template_string(CERTIFICATES_TEMPLATE)

@app.route("/admin-dashboard")
def admin_dashboard():
    """Admin dashboard page"""
    return render_template_string(ADMIN_DASHBOARD_TEMPLATE)

@app.route("/api/tenants")
@swag_from({
    'tags': ['Tenants'],
    'summary': 'Get all tenants',
    'responses': {
        200: {'description': 'List of tenants'},
        401: {'description': 'Unauthorized'}
    }
})
@limiter.limit("100 per hour")
def get_tenants():
    """Get all tenants (admin only)"""
    tenants = Tenant.query.all()
    return jsonify([{
        'id': t.id,
        'name': t.name,
        'domain': t.domain,
        'plan': t.plan,
        'status': t.status,
        'user_count': len(t.users),
        'created_at': t.created_at.isoformat()
    } for t in tenants])

@app.route("/api/tenants/<int:tenant_id>")
@swag_from({
    'tags': ['Tenants'],
    'summary': 'Get tenant details',
    'parameters': [
        {'name': 'tenant_id', 'in': 'path', 'type': 'integer', 'required': True}
    ],
    'responses': {
        200: {'description': 'Tenant details'},
        404: {'description': 'Tenant not found'}
    }
})
def get_tenant(tenant_id):
    """Get specific tenant details"""
    tenant = Tenant.query.get_or_404(tenant_id)
    return jsonify({
        'id': tenant.id,
        'name': tenant.name,
        'domain': tenant.domain,
        'plan': tenant.plan,
        'status': tenant.status,
        'users': [{'id': u.id, 'username': u.username, 'email': u.email, 'role': u.role} for u in tenant.users],
        'created_at': tenant.created_at.isoformat()
    })

@app.route("/api/users", methods=['POST'])
@swag_from({
    'tags': ['Users'],
    'summary': 'Create new user',
    'parameters': [
        {'name': 'username', 'in': 'body', 'type': 'string', 'required': True},
        {'name': 'email', 'in': 'body', 'type': 'string', 'required': True},
        {'name': 'tenant_id', 'in': 'body', 'type': 'integer', 'required': True},
        {'name': 'role', 'in': 'body', 'type': 'string', 'required': False}
    ],
    'responses': {
        201: {'description': 'User created'},
        400: {'description': 'Bad request'}
    }
})
@limiter.limit("10 per hour")
def create_user():
    """Create a new user"""
    data = request.get_json()
    
    if not all(k in data for k in ['username', 'email', 'tenant_id']):
        return jsonify({"error": "Missing required fields"}), 400
    
    # Check if user already exists
    if User.query.filter_by(username=data['username']).first():
        return jsonify({"error": "Username already exists"}), 400
    
    if User.query.filter_by(email=data['email']).first():
        return jsonify({"error": "Email already exists"}), 400
    
    # Create user
    user = User(
        username=data['username'],
        email=data['email'],
        tenant_id=data['tenant_id'],
        role=data.get('role', 'user')
    )
    
    db.session.add(user)
    db.session.commit()
    
    # Generate certificate for user
    cert, private_key = generate_certificate(data['username'])
    
    # Save certificate files
    cert_dir = f"certs/{user.id}"
    os.makedirs(cert_dir, exist_ok=True)
    
    cert_path = f"{cert_dir}/client.crt"
    key_path = f"{cert_dir}/client.key"
    
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    
    with open(key_path, "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ))
    
    # Create certificate record
    cert_record = Certificate(
        serial_number=str(cert.serial_number),
        common_name=data['username'],
        expires_at=cert.not_valid_after,
        tenant_id=data['tenant_id'],
        user_id=user.id,
        cert_file_path=cert_path,
        key_file_path=key_path
    )
    
    db.session.add(cert_record)
    db.session.commit()
    
    log_audit(user.id, 'user_created', 'user', f'User {data["username"]} created', request.remote_addr)
    
    return jsonify({
        "message": "User created successfully",
        "user_id": user.id,
        "certificate_files": {
            "cert": cert_path,
            "key": key_path
        }
    }), 201

@app.route("/api/certificates")
@swag_from({
    'tags': ['Certificates'],
    'summary': 'Get all certificates for current user',
    'responses': {
        200: {'description': 'List of certificates'},
        401: {'description': 'Unauthorized'}
    }
})
@limiter.limit("100 per hour")
def get_certificates():
    """Get all certificates for the authenticated user"""
    client_cert = request.environ.get('SSL_CLIENT_CERT', None)
    
    if not client_cert:
        return jsonify({"error": "No certificate provided"}), 401
    
    try:
        cert = x509.load_pem_x509_certificate(client_cert.encode())
        cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        
        user = User.query.filter_by(username=cn).first()
        if not user:
            return jsonify({"error": "User not found"}), 404
        
        # Get user's certificates
        user_certs = Certificate.query.filter_by(user_id=user.id).all()
        
        return jsonify([{
            'id': cert.id,
            'serial_number': cert.serial_number,
            'common_name': cert.common_name,
            'status': cert.status,
            'issued_at': cert.issued_at.isoformat(),
            'expires_at': cert.expires_at.isoformat(),
            'revoked_at': cert.revoked_at.isoformat() if cert.revoked_at else None,
            'revocation_reason': cert.revocation_reason,
            'tenant_id': cert.tenant_id,
            'user_id': cert.user_id
        } for cert in user_certs])
        
    except Exception as e:
        logger.error(f"Certificate parsing error: {e}")
        return jsonify({"error": "Invalid certificate"}), 400

@app.route("/api/certificates", methods=['POST'])
@swag_from({
    'tags': ['Certificates'],
    'summary': 'Generate new certificate for user',
    'parameters': [
        {'name': 'common_name', 'in': 'body', 'type': 'string', 'required': True},
        {'name': 'days', 'in': 'body', 'type': 'integer', 'required': False},
        {'name': 'purpose', 'in': 'body', 'type': 'string', 'required': False}
    ],
    'responses': {
        201: {'description': 'Certificate generated'},
        400: {'description': 'Bad request'},
        401: {'description': 'Unauthorized'}
    }
})
@limiter.limit("10 per hour")
def generate_new_certificate():
    """Generate a new certificate for the authenticated user"""
    client_cert = request.environ.get('SSL_CLIENT_CERT', None)
    
    if not client_cert:
        return jsonify({"error": "No certificate provided"}), 401
    
    try:
        cert = x509.load_pem_x509_certificate(client_cert.encode())
        cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        
        user = User.query.filter_by(username=cn).first()
        if not user:
            return jsonify({"error": "User not found"}), 404
        
        data = request.get_json()
        common_name = data.get('common_name')
        days = data.get('days', 365)
        purpose = data.get('purpose', 'general')
        
        if not common_name:
            return jsonify({"error": "Common name is required"}), 400
        
        # Generate new certificate
        new_cert, private_key = generate_certificate(common_name, days)
        
        # Save certificate files
        cert_dir = f"certs/{user.id}"
        os.makedirs(cert_dir, exist_ok=True)
        
        cert_path = f"{cert_dir}/{common_name}.crt"
        key_path = f"{cert_dir}/{common_name}.key"
        
        with open(cert_path, "wb") as f:
            f.write(new_cert.public_bytes(serialization.Encoding.PEM))
        
        with open(key_path, "wb") as f:
            f.write(private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            ))
        
        # Create certificate record
        cert_record = Certificate(
            serial_number=str(new_cert.serial_number),
            common_name=common_name,
            expires_at=new_cert.not_valid_after,
            tenant_id=user.tenant_id,
            user_id=user.id,
            cert_file_path=cert_path,
            key_file_path=key_path
        )
        
        db.session.add(cert_record)
        db.session.commit()
        
        log_audit(user.id, 'certificate_generated', 'certificate', 
                  f'Certificate {common_name} generated', request.remote_addr)
        
        return jsonify({
            "message": "Certificate generated successfully",
            "certificate": {
                "id": cert_record.id,
                "common_name": common_name,
                "serial_number": str(new_cert.serial_number),
                "expires_at": new_cert.not_valid_after.isoformat(),
                "files": {
                    "cert": cert_path,
                    "key": key_path
                }
            }
        }), 201
        
    except Exception as e:
        logger.error(f"Certificate generation error: {e}")
        return jsonify({"error": "Failed to generate certificate"}), 500

@app.route("/api/certificates/<int:cert_id>/revoke", methods=['POST'])
@swag_from({
    'tags': ['Certificates'],
    'summary': 'Revoke certificate',
    'parameters': [
        {'name': 'cert_id', 'in': 'path', 'type': 'integer', 'required': True},
        {'name': 'reason', 'in': 'body', 'type': 'string', 'required': False}
    ],
    'responses': {
        200: {'description': 'Certificate revoked'},
        404: {'description': 'Certificate not found'}
    }
})
def revoke_certificate(cert_id):
    """Revoke a certificate"""
    cert = Certificate.query.get_or_404(cert_id)
    
    if cert.status == 'revoked':
        return jsonify({"error": "Certificate already revoked"}), 400
    
    cert.status = 'revoked'
    cert.revoked_at = datetime.datetime.utcnow()
    cert.revocation_reason = request.json.get('reason', 'Admin revocation')
    
    db.session.commit()
    
    log_audit(cert.user_id, 'certificate_revoked', 'certificate', 
              f'Certificate {cert.serial_number} revoked', request.remote_addr)
    
    return jsonify({"message": "Certificate revoked successfully"})

@app.route("/health")
def health_check():
    return jsonify({"status": "healthy", "service": "saas-backend"})

# HTML Templates
REGISTRATION_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>User Registration - Secure SaaS Platform</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        body {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }
        .registration-container {
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            overflow: hidden;
            margin: 50px auto;
            max-width: 500px;
        }
        .header {
            background: linear-gradient(135deg, #2c3e50 0%, #34495e 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }
        .form-container {
            padding: 40px;
        }
        .form-control {
            border-radius: 10px;
            border: 2px solid #e9ecef;
            padding: 12px 15px;
            transition: all 0.3s ease;
        }
        .form-control:focus {
            border-color: #667eea;
            box-shadow: 0 0 0 0.2rem rgba(102, 126, 234, 0.25);
        }
        .btn-register {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border: none;
            border-radius: 10px;
            padding: 12px 30px;
            font-weight: 600;
            transition: all 0.3s ease;
        }
        .btn-register:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 20px rgba(102, 126, 234, 0.3);
        }
        .tenant-select {
            background: #f8f9fa;
            border: 2px solid #e9ecef;
            border-radius: 10px;
            padding: 15px;
            margin-bottom: 20px;
        }
        .step-indicator {
            display: flex;
            justify-content: center;
            margin-bottom: 30px;
        }
        .step {
            width: 40px;
            height: 40px;
            border-radius: 50%;
            background: #e9ecef;
            color: #6c757d;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 10px;
            font-weight: bold;
            transition: all 0.3s ease;
        }
        .step.active {
            background: #667eea;
            color: white;
        }
        .step.completed {
            background: #28a745;
            color: white;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="registration-container">
            <div class="header">
                <h2><i class="fas fa-user-plus"></i> User Registration</h2>
                <p class="mb-0">Join the Secure SaaS Platform</p>
            </div>
            
            <div class="form-container">
                <!-- Step Indicator -->
                <div class="step-indicator">
                    <div class="step active" id="step1">1</div>
                    <div class="step" id="step2">2</div>
                    <div class="step" id="step3">3</div>
                </div>

                <!-- Step 1: Basic Information -->
                <div id="step1-content">
                    <h4 class="mb-4">Basic Information</h4>
                    <div class="mb-3">
                        <label for="username" class="form-label">Username *</label>
                        <input type="text" class="form-control" id="username" placeholder="Enter username" required>
                        <div class="form-text">Username must be unique and contain only letters, numbers, and underscores.</div>
                    </div>
                    <div class="mb-3">
                        <label for="email" class="form-label">Email Address *</label>
                        <input type="email" class="form-control" id="email" placeholder="Enter email address" required>
                    </div>
                    <div class="mb-3">
                        <label for="firstName" class="form-label">First Name</label>
                        <input type="text" class="form-control" id="firstName" placeholder="Enter first name">
                    </div>
                    <div class="mb-3">
                        <label for="lastName" class="form-label">Last Name</label>
                        <input type="text" class="form-control" id="lastName" placeholder="Enter last name">
                    </div>
                    <button type="button" class="btn btn-register btn-lg w-100" onclick="nextStep()">
                        Next <i class="fas fa-arrow-right"></i>
                    </button>
                </div>

                <!-- Step 2: Tenant Selection -->
                <div id="step2-content" style="display: none;">
                    <h4 class="mb-4">Select Your Organization</h4>
                    <div class="tenant-select">
                        <h6><i class="fas fa-building"></i> Available Organizations</h6>
                        <div id="tenant-list">
                            <!-- Tenants will be loaded here -->
                        </div>
                    </div>
                    <div class="mb-3">
                        <label for="role" class="form-label">Role *</label>
                        <select class="form-control" id="role" required>
                            <option value="">Select a role</option>
                            <option value="user">User</option>
                            <option value="viewer">Viewer</option>
                            <option value="admin">Administrator</option>
                        </select>
                    </div>
                    <div class="d-flex gap-2">
                        <button type="button" class="btn btn-outline-secondary btn-lg flex-fill" onclick="prevStep()">
                            <i class="fas fa-arrow-left"></i> Previous
                        </button>
                        <button type="button" class="btn btn-register btn-lg flex-fill" onclick="nextStep()">
                            Next <i class="fas fa-arrow-right"></i>
                        </button>
                    </div>
                </div>

                <!-- Step 3: Review & Submit -->
                <div id="step3-content" style="display: none;">
                    <h4 class="mb-4">Review & Submit</h4>
                    <div class="card mb-4">
                        <div class="card-body">
                            <h6>Registration Summary</h6>
                            <div id="registration-summary">
                                <!-- Summary will be populated here -->
                            </div>
                        </div>
                    </div>
                    <div class="mb-3">
                        <div class="form-check">
                            <input class="form-check-input" type="checkbox" id="terms" required>
                            <label class="form-check-label" for="terms">
                                I agree to the <a href="#" onclick="showTerms()">Terms of Service</a> and <a href="#" onclick="showPrivacy()">Privacy Policy</a>
                            </label>
                        </div>
                    </div>
                    <div class="d-flex gap-2">
                        <button type="button" class="btn btn-outline-secondary btn-lg flex-fill" onclick="prevStep()">
                            <i class="fas fa-arrow-left"></i> Previous
                        </button>
                        <button type="button" class="btn btn-register btn-lg flex-fill" onclick="submitRegistration()" id="submit-btn">
                            <i class="fas fa-check"></i> Complete Registration
                        </button>
                    </div>
                </div>

                <!-- Loading State -->
                <div id="loading-state" style="display: none; text-align: center;">
                    <div class="spinner-border text-primary mb-3" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                    <p>Processing your registration...</p>
                </div>

                <!-- Success State -->
                <div id="success-state" style="display: none; text-align: center;">
                    <div class="text-success mb-3">
                        <i class="fas fa-check-circle fa-3x"></i>
                    </div>
                    <h4>Registration Successful!</h4>
                    <p>Your account has been created successfully. You will receive an email with your certificate files.</p>
                    <div class="alert alert-info">
                        <strong>Next Steps:</strong>
                        <ul class="mb-0 mt-2">
                            <li>Download your client certificate and private key</li>
                            <li>Import the certificate into your browser or application</li>
                            <li>Access the platform using your new credentials</li>
                        </ul>
                    </div>
                    <a href="/" class="btn btn-primary">Go to Dashboard</a>
                </div>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        let currentStep = 1;
        let registrationData = {};

        // Load tenants on page load
        document.addEventListener('DOMContentLoaded', function() {
            loadTenants();
        });

        function loadTenants() {
            fetch('/api/tenants')
                .then(response => response.json())
                .then(tenants => {
                    const tenantList = document.getElementById('tenant-list');
                    tenantList.innerHTML = '';
                    
                    tenants.forEach(tenant => {
                        const tenantDiv = document.createElement('div');
                        tenantDiv.className = 'form-check mb-2';
                        tenantDiv.innerHTML = `
                            <input class="form-check-input" type="radio" name="tenant" id="tenant${tenant.id}" value="${tenant.id}" required>
                            <label class="form-check-label" for="tenant${tenant.id}">
                                <strong>${tenant.name}</strong> (${tenant.plan} plan)
                            </label>
                        `;
                        tenantList.appendChild(tenantDiv);
                    });
                })
                .catch(error => {
                    console.error('Error loading tenants:', error);
                    document.getElementById('tenant-list').innerHTML = '<p class="text-danger">Error loading organizations</p>';
                });
        }

        function nextStep() {
            if (currentStep === 1) {
                if (!validateStep1()) return;
                saveStep1Data();
            } else if (currentStep === 2) {
                if (!validateStep2()) return;
                saveStep2Data();
            }
            
            if (currentStep < 3) {
                currentStep++;
                showStep(currentStep);
                updateStepIndicator();
            }
        }

        function prevStep() {
            if (currentStep > 1) {
                currentStep--;
                showStep(currentStep);
                updateStepIndicator();
            }
        }

        function showStep(step) {
            document.getElementById('step1-content').style.display = 'none';
            document.getElementById('step2-content').style.display = 'none';
            document.getElementById('step3-content').style.display = 'none';
            
            document.getElementById(`step${step}-content`).style.display = 'block';
            
            if (step === 3) {
                populateSummary();
            }
        }

        function updateStepIndicator() {
            for (let i = 1; i <= 3; i++) {
                const stepElement = document.getElementById(`step${i}`);
                if (i < currentStep) {
                    stepElement.className = 'step completed';
                    stepElement.innerHTML = '<i class="fas fa-check"></i>';
                } else if (i === currentStep) {
                    stepElement.className = 'step active';
                    stepElement.innerHTML = i;
                } else {
                    stepElement.className = 'step';
                    stepElement.innerHTML = i;
                }
            }
        }

        function validateStep1() {
            const username = document.getElementById('username').value.trim();
            const email = document.getElementById('email').value.trim();
            
            if (!username || !email) {
                alert('Please fill in all required fields.');
                return false;
            }
            
            if (username.length < 3) {
                alert('Username must be at least 3 characters long.');
                return false;
            }
            
            const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            if (!emailRegex.test(email)) {
                alert('Please enter a valid email address.');
                return false;
            }
            
            return true;
        }

        function validateStep2() {
            const selectedTenant = document.querySelector('input[name="tenant"]:checked');
            const role = document.getElementById('role').value;
            
            if (!selectedTenant) {
                alert('Please select an organization.');
                return false;
            }
            
            if (!role) {
                alert('Please select a role.');
                return false;
            }
            
            return true;
        }

        function saveStep1Data() {
            registrationData.username = document.getElementById('username').value.trim();
            registrationData.email = document.getElementById('email').value.trim();
            registrationData.firstName = document.getElementById('firstName').value.trim();
            registrationData.lastName = document.getElementById('lastName').value.trim();
        }

        function saveStep2Data() {
            const selectedTenant = document.querySelector('input[name="tenant"]:checked');
            registrationData.tenant_id = parseInt(selectedTenant.value);
            registrationData.role = document.getElementById('role').value;
        }

        function populateSummary() {
            const summary = document.getElementById('registration-summary');
            summary.innerHTML = `
                <p><strong>Username:</strong> ${registrationData.username}</p>
                <p><strong>Email:</strong> ${registrationData.email}</p>
                <p><strong>Name:</strong> ${registrationData.firstName} ${registrationData.lastName}</p>
                <p><strong>Role:</strong> ${registrationData.role}</p>
                <p><strong>Organization ID:</strong> ${registrationData.tenant_id}</p>
            `;
        }

        function submitRegistration() {
            if (!document.getElementById('terms').checked) {
                alert('Please agree to the Terms of Service and Privacy Policy.');
                return false;
            }
            
            // Show loading state
            document.getElementById('step3-content').style.display = 'none';
            document.getElementById('loading-state').style.display = 'block';
            
            // Submit registration
            fetch('/api/users', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    username: registrationData.username,
                    email: registrationData.email,
                    tenant_id: registrationData.tenant_id,
                    role: registrationData.role
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.message) {
                    // Show success state
                    document.getElementById('loading-state').style.display = 'none';
                    document.getElementById('success-state').style.display = 'block';
                } else {
                    throw new Error(data.error || 'Registration failed');
                }
            })
            .catch(error => {
                alert('Registration failed: ' + error.message);
                document.getElementById('loading-state').style.display = 'none';
                document.getElementById('step3-content').style.display = 'block';
            });
        }

        function showTerms() {
            alert('Terms of Service would be displayed here.');
        }

        function showPrivacy() {
            alert('Privacy Policy would be displayed here.');
        }
    </script>
</body>
</html>
"""

ADMIN_DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin Dashboard - Secure SaaS Platform</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        body { background: #f8f9fa; font-family: 'Segoe UI', sans-serif; }
        .sidebar { min-height: 100vh; background: #2c3e50; }
        .sidebar .nav-link { color: #ecf0f1; }
        .sidebar .nav-link:hover { background: #34495e; color: #fff; }
        .sidebar .nav-link.active { background: #3498db; }
        .main-content { padding: 20px; }
        .stat-card { text-align: center; padding: 20px; border-radius: 15px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); }
        .stat-number { font-size: 2.5rem; font-weight: bold; }
        .chart-container { background: white; border-radius: 15px; padding: 20px; margin: 20px 0; box-shadow: 0 4px 15px rgba(0,0,0,0.1); }
    </style>
</head>
<body>
    <div class="container-fluid">
        <div class="row">
            <!-- Sidebar -->
            <nav class="col-md-3 col-lg-2 d-md-block sidebar collapse">
                <div class="position-sticky pt-3">
                    <div class="text-center mb-4">
                        <h4 class="text-white">🔒 Admin Panel</h4>
                    </div>
                    <ul class="nav flex-column">
                        <li class="nav-item">
                            <a class="nav-link active" href="#dashboard">
                                <i class="fas fa-tachometer-alt"></i> Dashboard
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="#tenants">
                                <i class="fas fa-building"></i> Tenants
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="#users">
                                <i class="fas fa-users"></i> Users
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="#certificates">
                                <i class="fas fa-certificate"></i> Certificates
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="#audit">
                                <i class="fas fa-shield-alt"></i> Audit Logs
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="/">
                                <i class="fas fa-home"></i> Back to App
                            </a>
                        </li>
                    </ul>
                </div>
            </nav>

            <!-- Main content -->
            <main class="col-md-9 ms-sm-auto col-lg-10 px-md-4 main-content">
                <div class="d-flex justify-content-between flex-wrap flex-md-nowrap align-items-center pt-3 pb-2 mb-3 border-bottom">
                    <h1 class="h2">Admin Dashboard</h1>
                    <div class="btn-toolbar mb-2 mb-md-0">
                        <div class="btn-group me-2">
                            <button type="button" class="btn btn-sm btn-outline-secondary" onclick="refreshData()">
                                <i class="fas fa-sync-alt"></i> Refresh
                            </button>
                        </div>
                    </div>
                </div>

                <!-- Stats Cards -->
                <div class="row mb-4">
                    <div class="col-md-3">
                        <div class="card stat-card bg-primary text-white">
                            <div class="stat-number" id="total-tenants">0</div>
                            <div>Total Tenants</div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="card stat-card bg-success text-white">
                            <div class="stat-number" id="total-users">0</div>
                            <div>Total Users</div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="card stat-card bg-warning text-white">
                            <div class="stat-number" id="active-certs">0</div>
                            <div>Active Certs</div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="card stat-card bg-info text-white">
                            <div class="stat-number" id="today-logins">0</div>
                            <div>Today's Logins</div>
                        </div>
                    </div>
                </div>

                <!-- Quick Actions -->
                <div class="row mb-4">
                    <div class="col-12">
                        <div class="chart-container">
                            <h5><i class="fas fa-bolt"></i> Quick Actions</h5>
                            <div class="row">
                                <div class="col-md-3">
                                    <button class="btn btn-primary w-100 mb-2" onclick="showCreateTenant()">
                                        <i class="fas fa-plus"></i> New Tenant
                                    </button>
                                </div>
                                <div class="col-md-3">
                                    <button class="btn btn-success w-100 mb-2" onclick="showCreateUser()">
                                        <i class="fas fa-user-plus"></i> New User
                                    </button>
                                </div>
                                <div class="col-md-3">
                                    <button class="btn btn-warning w-100 mb-2" onclick="showGenerateCert()">
                                        <i class="fas fa-certificate"></i> Generate Cert
                                    </button>
                                </div>
                                <div class="col-md-3">
                                    <button class="btn btn-info w-100 mb-2" onclick="exportData()">
                                        <i class="fas fa-download"></i> Export Data
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Recent Activity -->
                <div class="row">
                    <div class="col-md-6">
                        <div class="chart-container">
                            <h5><i class="fas fa-clock"></i> Recent Activity</h5>
                            <div id="recent-activity">
                                <p class="text-muted">Loading recent activity...</p>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-6">
                        <div class="chart-container">
                            <h5><i class="fas fa-chart-pie"></i> System Status</h5>
                            <div id="system-status">
                                <div class="alert alert-success">
                                    <i class="fas fa-check-circle"></i> All systems operational
                                </div>
                                <div class="alert alert-info">
                                    <i class="fas fa-info-circle"></i> Database: Connected
                                </div>
                                <div class="alert alert-info">
                                    <i class="fas fa-info-circle"></i> Honeypot: Active
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </main>
        </div>
    </div>

    <!-- Create Tenant Modal -->
    <div class="modal fade" id="createTenantModal" tabindex="-1">
        <div class="modal-dialog">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title">Create New Tenant</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body">
                    <form id="tenantForm">
                        <div class="mb-3">
                            <label class="form-label">Tenant Name</label>
                            <input type="text" class="form-control" id="tenantName" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Domain</label>
                            <input type="text" class="form-control" id="tenantDomain">
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Plan</label>
                            <select class="form-control" id="tenantPlan">
                                <option value="basic">Basic</option>
                                <option value="premium">Premium</option>
                                <option value="enterprise">Enterprise</option>
                            </select>
                        </div>
                    </form>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                    <button type="button" class="btn btn-primary" onclick="createTenant()">Create</button>
                </div>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        // Load dashboard data
        document.addEventListener('DOMContentLoaded', function() {
            loadDashboardData();
        });

        function loadDashboardData() {
            // Load statistics
            fetch('/api/tenants')
                .then(response => response.json())
                .then(tenants => {
                    document.getElementById('total-tenants').textContent = tenants.length;
                });

            // Load recent activity
            loadRecentActivity();
        }

        function loadRecentActivity() {
            const activity = [
                { action: 'User registered', user: 'john.doe', time: '2 minutes ago' },
                { action: 'Certificate generated', user: 'admin', time: '5 minutes ago' },
                { action: 'Tenant created', user: 'admin', time: '1 hour ago' },
                { action: 'Certificate revoked', user: 'admin', time: '2 hours ago' }
            ];

            const container = document.getElementById('recent-activity');
            container.innerHTML = activity.map(item => `
                <div class="d-flex justify-content-between align-items-center mb-2">
                    <div>
                        <strong>${item.action}</strong><br>
                        <small class="text-muted">${item.user}</small>
                    </div>
                    <small class="text-muted">${item.time}</small>
                </div>
            `).join('');
        }

        function showCreateTenant() {
            const modal = new bootstrap.Modal(document.getElementById('createTenantModal'));
            modal.show();
        }

        function createTenant() {
            const name = document.getElementById('tenantName').value;
            const domain = document.getElementById('tenantDomain').value;
            const plan = document.getElementById('tenantPlan').value;

            if (!name) {
                alert('Please enter a tenant name');
                return;
            }

            // Create tenant logic here
            alert(`Tenant "${name}" created successfully!`);
            
            const modal = bootstrap.Modal.getInstance(document.getElementById('createTenantModal'));
            modal.hide();
            
            // Refresh data
            loadDashboardData();
        }

        function showCreateUser() {
            alert('Create User functionality will be implemented here');
        }

        function showGenerateCert() {
            alert('Generate Certificate functionality will be implemented here');
        }

        function exportData() {
            alert('Export functionality will be implemented here');
        }

        function refreshData() {
            loadDashboardData();
        }
    </script>
</body>
</html>
"""

CERTIFICATES_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Certificate Management - Secure SaaS Platform</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        body {
            background: #f8f9fa;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }
        .cert-card {
            background: white;
            border-radius: 15px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
            transition: all 0.3s ease;
            border-left: 5px solid #28a745;
        }
        .cert-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 8px 25px rgba(0,0,0,0.15);
        }
        .cert-card.revoked {
            border-left-color: #dc3545;
            opacity: 0.7;
        }
        .cert-card.expired {
            border-left-color: #ffc107;
            opacity: 0.8;
        }
        .status-badge {
            font-size: 0.8rem;
            padding: 0.4rem 0.8rem;
        }
        .cert-details {
            background: #f8f9fa;
            border-radius: 10px;
            padding: 15px;
            margin-top: 15px;
        }
        .action-buttons {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        .btn-sm {
            padding: 0.25rem 0.5rem;
            font-size: 0.875rem;
        }
        .expiry-warning {
            background: #fff3cd;
            border: 1px solid #ffeaa7;
            color: #856404;
            padding: 10px;
            border-radius: 5px;
            margin-top: 10px;
        }
        .cert-icon {
            font-size: 2rem;
            color: #28a745;
            margin-bottom: 15px;
        }
        .cert-icon.revoked { color: #dc3545; }
        .cert-icon.expired { color: #ffc107; }
    </style>
</head>
<body>
    <div class="container-fluid">
        <div class="row">
            <!-- Sidebar -->
            <nav class="col-md-3 col-lg-2 d-md-block bg-dark sidebar collapse" style="min-height: 100vh;">
                <div class="position-sticky pt-3">
                    <div class="text-center mb-4">
                        <h4 class="text-white">🔒 Secure SaaS</h4>
                    </div>
                    <ul class="nav flex-column">
                        <li class="nav-item">
                            <a class="nav-link text-white-50" href="/">
                                <i class="fas fa-tachometer-alt"></i> Dashboard
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link text-white-50" href="/admin">
                                <i class="fas fa-cog"></i> Admin Panel
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link active text-white" href="/certificates">
                                <i class="fas fa-certificate"></i> Certificates
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link text-white-50" href="/register">
                                <i class="fas fa-user-plus"></i> Register User
                            </a>
                        </li>
                    </ul>
                </div>
            </nav>

            <!-- Main content -->
            <main class="col-md-9 ms-sm-auto col-lg-10 px-md-4">
                <div class="d-flex justify-content-between flex-wrap flex-md-nowrap align-items-center pt-3 pb-2 mb-3 border-bottom">
                    <h1 class="h2">
                        <i class="fas fa-certificate text-primary"></i> Certificate Management
                    </h1>
                    <div class="btn-toolbar mb-2 mb-md-0">
                        <div class="btn-group me-2">
                            <button type="button" class="btn btn-sm btn-outline-primary" onclick="refreshCertificates()">
                                <i class="fas fa-sync-alt"></i> Refresh
                            </button>
                            <button type="button" class="btn btn-sm btn-outline-success" onclick="showNewCertModal()">
                                <i class="fas fa-plus"></i> New Certificate
                            </button>
                        </div>
                    </div>
                </div>

                <!-- Certificate Statistics -->
                <div class="row mb-4">
                    <div class="col-md-3">
                        <div class="card text-center">
                            <div class="card-body">
                                <h5 class="card-title text-success">Active</h5>
                                <h3 class="text-success" id="active-count">0</h3>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="card text-center">
                            <div class="card-body">
                                <h5 class="card-title text-warning">Expiring Soon</h5>
                                <h3 class="text-warning" id="expiring-count">0</h3>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="card text-center">
                            <div class="card-body">
                                <h5 class="card-title text-danger">Expired</h5>
                                <h3 class="text-danger" id="expired-count">0</h3>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="card text-center">
                            <div class="card-body">
                                <h5 class="card-title text-secondary">Revoked</h5>
                                <h3 class="text-secondary" id="revoked-count">0</h3>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Certificate List -->
                <div id="certificates-container">
                    <!-- Certificates will be loaded here -->
                </div>

                <!-- Loading State -->
                <div id="loading-state" class="text-center py-5" style="display: none;">
                    <div class="spinner-border text-primary" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                    <p class="mt-3">Loading certificates...</p>
                </div>

                <!-- Empty State -->
                <div id="empty-state" class="text-center py-5" style="display: none;">
                    <i class="fas fa-certificate fa-3x text-muted mb-3"></i>
                    <h4>No Certificates Found</h4>
                    <p class="text-muted">You don't have any certificates yet. Create your first one to get started.</p>
                    <button class="btn btn-primary" onclick="showNewCertModal()">
                        <i class="fas fa-plus"></i> Create Certificate
                    </button>
                </div>
            </main>
        </div>
    </div>

    <!-- New Certificate Modal -->
    <div class="modal fade" id="newCertModal" tabindex="-1">
        <div class="modal-dialog">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title">
                        <i class="fas fa-plus-circle text-primary"></i> Generate New Certificate
                    </h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body">
                    <form id="newCertForm">
                        <div class="mb-3">
                            <label for="certName" class="form-label">Certificate Name *</label>
                            <input type="text" class="form-control" id="certName" required 
                                   placeholder="e.g., My Laptop, Mobile Device">
                            <div class="form-text">A descriptive name for this certificate</div>
                        </div>
                        <div class="mb-3">
                            <label for="certDays" class="form-label">Validity Period *</label>
                            <select class="form-control" id="certDays" required>
                                <option value="30">30 days</option>
                                <option value="90">90 days</option>
                                <option value="180">180 days</option>
                                <option value="365" selected>1 year</option>
                                <option value="730">2 years</option>
                            </select>
                        </div>
                        <div class="mb-3">
                            <label for="certPurpose" class="form-label">Purpose</label>
                            <select class="form-control" id="certPurpose">
                                <option value="general">General Access</option>
                                <option value="development">Development</option>
                                <option value="testing">Testing</option>
                                <option value="production">Production</option>
                            </select>
                        </div>
                    </form>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                    <button type="button" class="btn btn-primary" onclick="generateCertificate()">
                        <i class="fas fa-magic"></i> Generate Certificate
                    </button>
                </div>
            </div>
        </div>
    </div>

    <!-- Certificate Details Modal -->
    <div class="modal fade" id="certDetailsModal" tabindex="-1">
        <div class="modal-dialog modal-lg">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title">
                        <i class="fas fa-info-circle text-info"></i> Certificate Details
                    </h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body" id="certDetailsContent">
                    <!-- Certificate details will be populated here -->
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                    <button type="button" class="btn btn-danger" id="revokeBtn" onclick="revokeCertificate()" style="display: none;">
                        <i class="fas fa-ban"></i> Revoke Certificate
                    </button>
                </div>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        let certificates = [];
        let currentCertId = null;

        // Load certificates on page load
        document.addEventListener('DOMContentLoaded', function() {
            loadCertificates();
        });

        function loadCertificates() {
            showLoading(true);
            
            // Simulate API call - replace with actual endpoint
            fetch('/api/certificates')
                .then(response => response.json())
                .then(data => {
                    certificates = data;
                    displayCertificates();
                    updateStatistics();
                    showLoading(false);
                })
                .catch(error => {
                    console.error('Error loading certificates:', error);
                    showLoading(false);
                    showEmptyState();
                });
        }

        function displayCertificates() {
            const container = document.getElementById('certificates-container');
            
            if (certificates.length === 0) {
                showEmptyState();
                return;
            }
            
            container.innerHTML = '';
            
            certificates.forEach(cert => {
                const certCard = createCertificateCard(cert);
                container.appendChild(certCard);
            });
        }

        function createCertificateCard(cert) {
            const card = document.createElement('div');
            card.className = `card cert-card mb-3 ${cert.status}`;
            
            const statusClass = getStatusClass(cert.status);
            const statusIcon = getStatusIcon(cert.status);
            
            card.innerHTML = `
                <div class="card-body">
                    <div class="row align-items-center">
                        <div class="col-md-2 text-center">
                            <div class="cert-icon ${cert.status}">${statusIcon}</div>
                        </div>
                        <div class="col-md-7">
                            <h5 class="card-title">${cert.common_name}</h5>
                            <p class="card-text text-muted">
                                <strong>Serial:</strong> ${cert.serial_number}<br>
                                <strong>Issued:</strong> ${formatDate(cert.issued_at)}<br>
                                <strong>Expires:</strong> ${formatDate(cert.expires_at)}
                            </p>
                            <span class="badge ${statusClass} status-badge">${cert.status.toUpperCase()}</span>
                        </div>
                        <div class="col-md-3">
                            <div class="action-buttons">
                                <button class="btn btn-outline-info btn-sm" onclick="viewCertificate(${cert.id})">
                                    <i class="fas fa-eye"></i> View
                                </button>
                                <button class="btn btn-outline-success btn-sm" onclick="downloadCertificate(${cert.id})">
                                    <i class="fas fa-download"></i> Download
                                </button>
                                ${cert.status === 'active' ? `
                                    <button class="btn btn-outline-danger btn-sm" onclick="revokeCertificate(${cert.id})">
                                        <i class="fas fa-ban"></i> Revoke
                                    </button>
                                ` : ''}
                            </div>
                        </div>
                    </div>
                    
                    ${cert.status === 'active' && isExpiringSoon(cert.expires_at) ? `
                        <div class="expiry-warning">
                            <i class="fas fa-exclamation-triangle"></i>
                            <strong>Warning:</strong> This certificate expires in ${getDaysUntilExpiry(cert.expires_at)} days.
                        </div>
                    ` : ''}
                </div>
            `;
            
            return card;
        }

        function getStatusClass(status) {
            switch(status) {
                case 'active': return 'bg-success';
                case 'expired': return 'bg-warning';
                case 'revoked': return 'bg-danger';
                default: return 'bg-secondary';
            }
        }

        function getStatusIcon(status) {
            switch(status) {
                case 'active': return '🔒';
                case 'expired': return '⏰';
                case 'revoked': return '🚫';
                default: return '❓';
            }
        }

        function formatDate(dateString) {
            return new Date(dateString).toLocaleDateString();
        }

        function isExpiringSoon(expiryDate) {
            const daysUntilExpiry = getDaysUntilExpiry(expiryDate);
            return daysUntilExpiry <= 30 && daysUntilExpiry > 0;
        }

        function getDaysUntilExpiry(expiryDate) {
            const expiry = new Date(expiryDate);
            const now = new Date();
            const diffTime = expiry - now;
            return Math.ceil(diffTime / (1000 * 60 * 60 * 24));
        }

        function updateStatistics() {
            const active = certificates.filter(c => c.status === 'active').length;
            const expiring = certificates.filter(c => c.status === 'active' && isExpiringSoon(c.expires_at)).length;
            const expired = certificates.filter(c => c.status === 'expired').length;
            const revoked = certificates.filter(c => c.status === 'revoked').length;
            
            document.getElementById('active-count').textContent = active;
            document.getElementById('expiring-count').textContent = expiring;
            document.getElementById('expired-count').textContent = expired;
            document.getElementById('revoked-count').textContent = revoked;
        }

        function showLoading(show) {
            document.getElementById('loading-state').style.display = show ? 'block' : 'none';
            document.getElementById('certificates-container').style.display = show ? 'none' : 'block';
            document.getElementById('empty-state').style.display = 'none';
        }

        function showEmptyState() {
            document.getElementById('loading-state').style.display = 'none';
            document.getElementById('certificates-container').style.display = 'none';
            document.getElementById('empty-state').style.display = 'block';
        }

        function refreshCertificates() {
            loadCertificates();
        }

        function showNewCertModal() {
            const modal = new bootstrap.Modal(document.getElementById('newCertModal'));
            modal.show();
        }

        function generateCertificate() {
            const name = document.getElementById('certName').value;
            const days = document.getElementById('certDays').value;
            const purpose = document.getElementById('certPurpose').value;
            
            if (!name) {
                alert('Please enter a certificate name');
                return;
            }
            
            // Simulate certificate generation
            alert(`Certificate "${name}" will be generated for ${days} days with purpose: ${purpose}`);
            
            // Close modal and refresh
            const modal = bootstrap.Modal.getInstance(document.getElementById('newCertModal'));
            modal.hide();
            
            // In real implementation, call API to generate certificate
            setTimeout(() => {
                loadCertificates();
            }, 1000);
        }

        function viewCertificate(certId) {
            currentCertId = certId;
            const cert = certificates.find(c => c.id === certId);
            
            if (!cert) return;
            
            const content = document.getElementById('certDetailsContent');
            content.innerHTML = `
                <div class="row">
                    <div class="col-md-6">
                        <h6>Basic Information</hh6>
                        <table class="table table-sm">
                            <tr><td><strong>Common Name:</strong></td><td>${cert.common_name}</td></tr>
                            <tr><td><strong>Serial Number:</strong></td><td>${cert.serial_number}</td></tr>
                            <tr><td><strong>Status:</strong></td><td><span class="badge ${getStatusClass(cert.status)}">${cert.status.toUpperCase()}</span></td></tr>
                            <tr><td><td><strong>Issued:</strong></td><td>${formatDate(cert.issued_at)}</td></tr>
                            <tr><td><strong>Expires:</strong></td><td>${formatDate(cert.expires_at)}</td></tr>
                        </table>
                    </div>
                    <div class="col-md-6">
                        <h6>Certificate Details</h6>
                        <div class="cert-details">
                            <p><strong>Subject:</strong> CN=${cert.common_name}</p>
                            <p><strong>Issuer:</strong> CN=Secure SaaS CA</p>
                            <p><strong>Key Usage:</strong> Digital Signature, Key Encipherment</p>
                            <p><strong>Extended Key Usage:</strong> Client Authentication</p>
                        </div>
                    </div>
                </div>
                
                ${cert.status === 'revoked' ? `
                    <div class="alert alert-warning mt-3">
                        <strong>Revocation Details:</strong><br>
                        <strong>Revoked:</strong> ${formatDate(cert.revoked_at)}<br>
                        <strong>Reason:</strong> ${cert.revocation_reason || 'Not specified'}
                    </div>
                ` : ''}
            `;
            
            // Show/hide revoke button
            const revokeBtn = document.getElementById('revokeBtn');
            revokeBtn.style.display = cert.status === 'active' ? 'inline-block' : 'none';
            
            const modal = new bootstrap.Modal(document.getElementById('certDetailsModal'));
            modal.show();
        }

        function downloadCertificate(certId) {
            const cert = certificates.find(c => c.id === certId);
            if (!cert) return;
            
            // Simulate download - in real implementation, this would download the actual files
            alert(`Downloading certificate for ${cert.common_name}...`);
        }

        function revokeCertificate(certId) {
            if (!confirm('Are you sure you want to revoke this certificate? This action cannot be undone.')) {
                return;
            }
            
            const reason = prompt('Please provide a reason for revocation:');
            if (reason === null) return; // User cancelled
            
            // Simulate API call
            fetch(`/api/certificates/${certId}/revoke`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ reason: reason })
            })
            .then(response => response.json())
            .then(data => {
                alert('Certificate revoked successfully');
                loadCertificates(); // Refresh the list
                
                // Close modal if open
                const modal = bootstrap.Modal.getInstance(document.getElementById('certDetailsModal'));
                if (modal) modal.hide();
            })
            .catch(error => {
                alert('Failed to revoke certificate: ' + error.message);
            });
        }
    </script>
</body>
</html>
"""

MAIN_DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Secure SaaS Platform - Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        .sidebar { min-height: 100vh; background: #2c3e50; }
        .sidebar .nav-link { color: #ecf0f1; }
        .sidebar .nav-link:hover { background: #34495e; color: #fff; }
        .sidebar .nav-link.active { background: #3498db; }
        .main-content { padding: 20px; }
        .card { margin-bottom: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .stat-card { text-align: center; padding: 20px; }
        .stat-number { font-size: 2.5rem; font-weight: bold; color: #3498db; }
    </style>
</head>
<body>
    <div class="container-fluid">
        <div class="row">
            <!-- Sidebar -->
            <nav class="col-md-3 col-lg-2 d-md-block sidebar collapse">
                <div class="position-sticky pt-3">
                    <div class="text-center mb-4">
                        <h4 class="text-white">🔒 Secure SaaS</h4>
                    </div>
                    <ul class="nav flex-column">
                        <li class="nav-item">
                            <a class="nav-link active" href="#dashboard">
                                <i class="fas fa-tachometer-alt"></i> Dashboard
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="#tenants">
                                <i class="fas fa-building"></i> Tenants
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="#users">
                                <i class="fas fa-users"></i> Users
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="#certificates">
                                <i class="fas fa-certificate"></i> Certificates
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="/admin">
                                <i class="fas fa-cog"></i> Admin Panel
                            </a>
                        </li>
                    </ul>
                </div>
            </nav>

            <!-- Main content -->
            <main class="col-md-9 ms-sm-auto col-lg-10 px-md-4 main-content">
                <div class="d-flex justify-content-between flex-wrap flex-md-nowrap align-items-center pt-3 pb-2 mb-3 border-bottom">
                    <h1 class="h2">Welcome, {{ user.username }}!</h1>
                    <div class="btn-toolbar mb-2 mb-md-0">
                        <div class="btn-group me-2">
                            <button type="button" class="btn btn-sm btn-outline-secondary">Export</button>
                            <button type="button" class="btn btn-sm btn-outline-secondary">Share</button>
                        </div>
                    </div>
                </div>

                <!-- Stats Cards -->
                <div class="row">
                    <div class="col-md-3">
                        <div class="card stat-card">
                            <div class="stat-number">{{ tenant.plan|title }}</div>
                            <div class="text-muted">Plan</div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="card stat-card">
                            <div class="stat-number">{{ user.role|title }}</div>
                            <div class="text-muted">Role</div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="card stat-card">
                            <div class="stat-number">{{ user.certificates|length }}</div>
                            <div class="text-muted">Certificates</div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="card stat-card">
                            <div class="stat-number">{{ tenant.users|length }}</div>
                            <div class="text-muted">Team Members</div>
                        </div>
                    </div>
                </div>

                <!-- Tenant Info -->
                <div class="row">
                    <div class="col-md-6">
                        <div class="card">
                            <div class="card-header">
                                <h5><i class="fas fa-building"></i> Tenant Information</h5>
                            </div>
                            <div class="card-body">
                                <p><strong>Name:</strong> {{ tenant.name }}</p>
                                <p><strong>Domain:</strong> {{ tenant.domain or 'Not set' }}</p>
                                <p><strong>Status:</strong> 
                                    <span class="badge bg-{{ 'success' if tenant.status == 'active' else 'warning' }}">
                                        {{ tenant.status|title }}
                                    </span>
                                </p>
                                <p><strong>Created:</strong> {{ tenant.created_at.strftime('%Y-%m-%d') }}</p>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-6">
                        <div class="card">
                            <div class="card-header">
                                <h5><i class="fas fa-user"></i> User Profile</h5>
                            </div>
                            <div class="card-body">
                                <p><strong>Username:</strong> {{ user.username }}</p>
                                <p><strong>Email:</strong> {{ user.email }}</p>
                                <p><strong>Role:</strong> {{ user.role|title }}</p>
                                <p><strong>Last Login:</strong> {{ user.last_login.strftime('%Y-%m-%d %H:%M') if user.last_login else 'Never' }}</p>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Quick Actions -->
                <div class="card">
                    <div class="card-header">
                        <h5><i class="fas fa-bolt"></i> Quick Actions</h5>
                    </div>
                    <div class="card-body">
                        <div class="row">
                            <div class="col-md-3">
                                <a href="/admin" class="btn btn-primary btn-lg w-100 mb-2">
                                    <i class="fas fa-cog"></i><br>Admin Panel
                                </a>
                            </div>
                            <div class="col-md-3">
                                <a href="/api/tenants" class="btn btn-info btn-lg w-100 mb-2">
                                    <i class="fas fa-list"></i><br>View Tenants
                                </a>
                            </div>
                            <div class="col-md-3">
                                <a href="/swagger" class="btn btn-success btn-lg w-100 mb-2">
                                    <i class="fas fa-book"></i><br>API Docs
                                </a>
                            </div>
                            <div class="col-md-3">
                                <button class="btn btn-warning btn-lg w-100 mb-2" onclick="downloadCert()">
                                    <i class="fas fa-download"></i><br>Download Cert
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </main>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        function downloadCert() {
            alert('Certificate download functionality will be implemented here');
        }
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        
        # Create default admin tenant and user if they don't exist
        if not Tenant.query.first():
            admin_tenant = Tenant(
                name='Admin Organization',
                domain='admin.local',
                plan='enterprise',
                api_key=generate_api_key()
            )
            db.session.add(admin_tenant)
            db.session.commit()
            
            admin_user = User(
                username='admin',
                email='admin@admin.local',
                role='admin',
                tenant_id=admin_tenant.id
            )
            db.session.add(admin_user)
            db.session.commit()
            
            logger.info("Default admin tenant and user created")
    
    app.run(host="0.0.0.0", port=5000, debug=False)
