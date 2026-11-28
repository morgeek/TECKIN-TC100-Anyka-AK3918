#!/bin/sh
# httpscert.cgi: download the camera's persistent public ECDSA P-256 HTTPS certificate (/mnt/config/https-cert.pem).
# Never exposes the private key file.

CERT_PATH="${HTTPS_CERT_FILE:-/mnt/config/https-cert.pem}"

if [ ! -r "$CERT_PATH" ] || [ ! -s "$CERT_PATH" ]; then
  printf 'Status: 404 Not Found\r\n'
  printf 'Content-Type: text/plain\r\n'
  printf 'Cache-Control: no-store\r\n\r\n'
  printf 'HTTPS certificate not generated yet (HTTPS is off by default: switch it on in Services, or HTTPS=1 in boot.conf).\n'
  exit 0
fi

printf 'Content-Type: application/x-pem-file\r\n'
printf 'Cache-Control: no-store\r\n'
printf 'Content-Disposition: attachment; filename="tc100-https-cert.pem"\r\n\r\n'
cat "$CERT_PATH"
exit 0
