"""TCP liveness probe for the panel: exit 0 when :PORT answers."""
import socket
import sys

port = int(sys.argv[1] if len(sys.argv) > 1 else 8081)
sock = socket.socket()
sock.settimeout(2)
try:
    ok = sock.connect_ex(("127.0.0.1", port)) == 0
finally:
    sock.close()
sys.exit(0 if ok else 1)
