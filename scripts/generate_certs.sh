 #!/bin/bash
set -e

CERT_DIR="../nginx/certs"
mkdir -p $CERT_DIR
cd $CERT_DIR

# Generate CA key & cert
openssl genrsa -out ca.key 2048
openssl req -x509 -new -nodes -key ca.key -subj "/CN=MyCA" -days 365 -out ca.crt

# Generate server key & CSR
openssl genrsa -out server.key 2048
openssl req -new -key server.key -subj "/CN=nginx" -out server.csr
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days 365

# Generate client key & cert
openssl genrsa -out client.key 2048
openssl req -new -key client.key -subj "/CN=client" -out client.csr
openssl x509 -req -in client.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out client.crt -days 365

echo "Certificates generated in $CERT_DIR"
