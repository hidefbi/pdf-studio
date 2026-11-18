#!/bin/bash
# Stops only PDF Studio servers on the ports it can use. Other programs are left alone.
for p in $(seq 8000 8009); do
  if nc -z 127.0.0.1 "$p" 2>/dev/null && curl -s -m 2 "http://127.0.0.1:$p/api/identity" 2>/dev/null | grep -q '"pdf-studio"'; then
    curl -s -m 3 -o /dev/null -X POST -H "X-PDF-Studio: 1" "http://127.0.0.1:$p/api/shutdown"
    sleep 1
    PIDS=$(lsof -ti "tcp:$p" -sTCP:LISTEN 2>/dev/null)
    [ -n "$PIDS" ] && kill $PIDS 2>/dev/null
  fi
done
exit 0
