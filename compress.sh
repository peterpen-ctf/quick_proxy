#!/bin/sh

SESSIONS_DIR=/srv/sessions
COMPRESSED_DIR=/srv/sessions/compressed


mkdir -p $COMPRESSED_DIR
cd $SESSIONS_DIR
for port_dir in port*/; do tar cfz "$COMPRESSED_DIR/${port_dir%/}.tar.gz" "$port_dir"; done
