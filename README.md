# Secure Containerized Multi-Tenant SaaS Platform with PKI-based IAM and Integrated Docker Honeypot

This project demonstrates a **secure SaaS platform** with:
- **Multi-tenant backend (Flask)**
- **PKI-based authentication (mutual TLS) using Nginx reverse proxy**
- **Containerized Honeypot** to detect and log unauthorized access attempts.

---

## **Architecture**

```
+-------------------+
|   Client (PKI)    |
|  - client.crt     |
|  - client.key     |
+---------+---------+
          |
          v
   +------+-------+      +-------------------+
   |   Nginx      | ----> |   SaaS Backend   |
   | (PKI Auth)   |      | (Flask, Tenants) |
   +------+-------+      +-------------------+
          |
   Invalid Cert
          |
          v
+-------------------+
|  Honeypot Service |
| (Logs attackers)  |
+-------------------+
```

---

## **Features**

- **Multi-tenant SaaS backend** running as a Docker container.
- **PKI-based IAM** (only valid client certificates can access the backend).
- **Honeypot for detection** of unauthorized/malicious traffic.
- **Containerized architecture with Docker Compose.**
- **Logging & monitoring** for unauthorized requests.

---

## **Project Structure**

```
secure-saas-platform/
│
├── docker-compose.yml         # Compose file for all services
│
├── nginx/
│   ├── nginx.conf             # Nginx reverse proxy with PKI auth
│   ├── certs/                 # PKI certificates (generated later)
│
├── backend/
│   ├── Dockerfile
│   ├── app.py                 # Multi-tenant SaaS backend
│   ├── requirements.txt
│
├── honeypot/
│   ├── Dockerfile
│   ├── honeypot.py            # Honeypot Flask app
│   ├── requirements.txt
│
└── scripts/
    ├── generate_certs.sh      # PKI certificate generation script
```

---

## **Setup & Run**

### **1. Clone the Repository**
```bash
git clone https://github.com/<SuryaAkshaj>/secure-saas-pki-honeypot.git
cd secure-saas-platform
```

### **2. Generate PKI Certificates**
```bash
cd scripts
chmod +x generate_certs.sh
./generate_certs.sh
cd ..
```

### **3. Build and Start Containers**
```bash
docker-compose up --build
```

---

## **Testing the Platform**

### **A. Access with Client Certificate**
Use curl with the generated client certificate:
```bash
curl -k --cert nginx/certs/client.crt --key nginx/certs/client.key https://localhost/api/tenant1
```

### **B. Access without Certificate**
This triggers the honeypot:
```bash
curl -k https://localhost/
```

Check honeypot logs:
```bash
docker exec -it honeypot-service cat honeypot.log
```

---

## **PKI Certificates**
The script `scripts/generate_certs.sh` creates:
- `ca.crt` and `ca.key` – Certificate Authority.
- `server.crt` and `server.key` – Nginx server cert.
- `client.crt` and `client.key` – Client cert for testing.

---

## **Technologies Used**
- Docker & Docker Compose – Containerization.
- Flask (Python) – SaaS backend & honeypot service.
- Nginx – Reverse proxy with mutual TLS.
- OpenSSL – PKI certificate generation.

---

## **Future Improvements**
- Add rate limiting and IP banning.
- Deploy to Kubernetes with secrets management.
- Add real analytics and dashboards for honeypot logs.

## **🚀 Enhanced Features (NEW!)**

This platform now includes comprehensive **User Experience & Management** features:

- **🎯 Multi-Step User Registration** with tenant selection and role assignment
- **🔐 Advanced Certificate Management** with lifecycle tracking and expiry warnings
- **📊 Admin Dashboard** with real-time analytics and quick actions
- **👥 Role-Based Access Control** (Admin, User, Viewer)
- **📈 Audit Logging** for compliance and security monitoring
- **🎨 Modern, Responsive UI** built with Bootstrap 5

**📖 See [README_ENHANCED.md](README_ENHANCED.md) for complete documentation of new features!**
