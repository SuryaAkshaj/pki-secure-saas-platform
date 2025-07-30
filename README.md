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
├── docker-compose.yaml         # Compose file for all services
│
├── nginx/
│   ├── nginx.conf             # Nginx reverse proxy with PKI auth
│   ├── certs/                 # PKI certificates (generated here)
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
├── scripts/
│   └── generate_certs.sh      # (Legacy) PKI certificate generation script
│
├── fix_certificates.sh        # Recommended cross-platform certificate script
└── README.md
```

---

## **Setup & Run**

### **1. Generate PKI Certificates**

> **Recommended:** Use the provided `fix_certificates.sh` for best compatibility (especially on Windows).

```bash
chmod +x fix_certificates.sh
./fix_certificates.sh
```

This will generate all necessary certificates in `nginx/certs/`.

---

### **2. Build and Start Containers**

```bash
docker-compose up --build -d
```

---

### **3. Check Container Status**

```bash
docker ps
```
You should see `nginx-proxy`, `saas-backend`, and `honeypot-service` running and healthy.

---

## **Testing the Platform**

### **A. Access with Client Certificate**
Use curl with the generated client certificate:
```bash
curl -k --cert nginx/certs/client.crt --key nginx/certs/client.key https://localhost/api/tenant1
```

### **B. Access without Certificate (Triggers Honeypot)**
```bash
curl -k https://localhost/
```

### **C. Check Honeypot Logs**
To see the latest honeypot activity:
```bash
docker exec honeypot-service tail -20 honeypot.log
```
To watch logs live:
```bash
docker exec -it honeypot-service tail -f honeypot.log
```

---

## **PKI Certificates**
- `fix_certificates.sh` creates:
  - `ca.crt` and `ca.key` – Certificate Authority
  - `server.crt` and `server.key` – Nginx server cert
  - `client.crt` and `client.key` – Client cert for testing

---

## **Technologies Used**
- Docker & Docker Compose – Containerization
- Flask (Python) – SaaS backend & honeypot service
- Nginx – Reverse proxy with mutual TLS
- OpenSSL – PKI certificate generation

---

## **Future Improvements**
- Add rate limiting and IP banning
- Deploy to Kubernetes with secrets management
- Add real analytics and dashboards for honeypot logs

---

## **Troubleshooting**
- If you see errors running `fix_certificates.sh` on Windows, try using WSL (Windows Subsystem for Linux) or run the script on a Linux machine for best compatibility.
- For any issues with Docker networking or permissions, ensure Docker Desktop is running and you have the necessary privileges.
