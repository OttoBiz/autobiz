#!/bin/bash
set -e

# Update pg_hba.conf to allow all connections
echo "host all all 0.0.0.0/0 md5" >> /var/lib/postgresql/data/pg_hba.conf

# Update postgresql.conf to listen on all IP addresses
echo "listen_addresses='*'" >> /var/lib/postgresql/data/postgresql.conf
