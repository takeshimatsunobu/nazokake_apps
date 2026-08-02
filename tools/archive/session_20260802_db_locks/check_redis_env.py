import socket
import subprocess
import sys

def check_redis_package():
    try:
        import redis
        print("[OK] 'redis' package is installed.")
        return True
    except ImportError:
        print("[WARN] 'redis' package is NOT installed.")
        return False

def check_redis_server():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1)
    try:
        s.connect(('localhost', 6379))
        print("[OK] Redis server is running on localhost:6379.")
        s.close()
        return True
    except (ConnectionRefusedError, socket.timeout, OSError):
        print("[GARN] Redis server is NOT running on localhost:6379.")
        return False

def main():
    print("=== Redis Environment Check ===")
    pkg_ok = check_redis_package()
    srv_ok = check_redis_server()
    
    if not pkg_ok:
        print("\nTo install redis package, run: uv add redis")
    if not srv_ok:
        print("Please ensure Redis is installed and running (e.g., via Docker or WSL).")

if __name__ == "__main__":
    main()