import sys
try:
    import opentelemetry
    print("[+] opentelemetry is installed.")
except ImportError:
    print("[-] opentelemetry is NOT installed.")
