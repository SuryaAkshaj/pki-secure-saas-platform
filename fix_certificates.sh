#!/bin/bash
set -e

echo "🔧 Fixing Certificate Format for Windows Compatibility..."
echo "=================================================="

CERT_DIR="nginx/certs"
cd $CERT_DIR

# Remove existing certificates
rm -f *.crt *.key *.csr *.srl

echo "📝 Generating new certificates with proper format..."

# Generate CA with proper extensions
openssl genrsa -out ca.key 2048
openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 -out ca.crt \
    -subj "/C=US/ST=State/L=City/O=Organization/CN=MyCA" \
    -extensions v3_ca -config <(
cat << EOF
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_ca
[req_distinguished_name]
[v3_ca]
basicConstraints = CA:TRUE
keyUsage = keyCertSign, cRLSign
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer:always
EOF
)

# Generate server certificate
openssl genrsa -out server.key 2048
openssl req -new -key server.key -out server.csr \
    -subj "/C=US/ST=State/L=City/O=Organization/CN=localhost" \
    -config <(
cat << EOF
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
[req_distinguished_name]
[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names
[alt_names]
DNS.1 = localhost
DNS.2 = *.localhost
IP.1 = 127.0.0.1
EOF
)

openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
    -out server.crt -days 365 -sha256 \
    -extensions v3_req -extfile <(
cat << EOF
[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names
[alt_names]
DNS.1 = localhost
DNS.2 = *.localhost
IP.1 = 127.0.0.1
EOF
)

# Generate client certificate
openssl genrsa -out client.key 2048
openssl req -new -key client.key -out client.csr \
    -subj "/C=US/ST=State/L=City/O=Organization/CN=client" \
    -config <(
cat << EOF
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
[req_distinguished_name]
[v3_req]
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = clientAuth
EOF
)

openssl x509 -req -in client.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
    -out client.crt -days 365 -sha256 \
    -extensions v3_req -extfile <(
cat << EOF
[v3_req]
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = clientAuth
EOF
)

# Create PEM bundle for easier use
cat client.crt client.key > client.pem
chmod 600 client.pem

echo "✅ Certificates generated successfully!"
echo "📁 Files created in $CERT_DIR:"
ls -la *.crt *.key *.pem

echo ""
echo "🔐 To test with curl (Windows):"
echo "curl -k --cert client.crt --key client.key https://localhost/api/tenant1"
echo ""
echo "🔐 To test with OpenSSL:"
echo "openssl s_client -connect localhost:443 -cert client.crt -key client.key -CAfile ca.crt" 