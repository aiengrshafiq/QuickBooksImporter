import http.server
import socketserver
import webbrowser
import os
from urllib.parse import urlparse, parse_qs
# CORRECT
from intuitlib.client import AuthClient
from intuitlib.enums import Scopes

from config import QB_CLIENT_ID, QB_CLIENT_SECRET, QB_REDIRECT_URI, QB_ENVIRONMENT, auth_keys_present

# This script runs a temporary web server to catch the OAuth redirect
# It's the easiest way to get the initial code and realmId

PORT = 8000
auth_code = None
realm_id = None

class OAuthCallbackHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        global auth_code, realm_id
        query_components = parse_qs(urlparse(self.path).query)
        
        if 'code' in query_components and 'realmId' in query_components:
            auth_code = query_components["code"][0]
            realm_id = query_components["realmId"][0]
            
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><head><title>Success!</title></head>")
            self.wfile.write(b"<body style='font-family: sans-serif; text-align: center; padding-top: 50px;'>")
            self.wfile.write(b"<h1>Authentication Successful!</h1>")
            self.wfile.write(b"<p>You can close this window and return to your terminal.</p>")
            self.wfile.write(b"</body></html>")
        else:
            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body><h1>Error</h1><p>Could not parse auth code and realmId from redirect.</p></body></html>")

def get_tokens():
    if not auth_keys_present():
        print("Error: QB_CLIENT_ID, QB_CLIENT_SECRET, or QB_REDIRECT_URI not found in .env file.")
        print("Please follow Step 1 in README.md first.")
        return

    auth_client = AuthClient(
        client_id=QB_CLIENT_ID,
        client_secret=QB_CLIENT_SECRET,
        redirect_uri=QB_REDIRECT_URI,
        environment=QB_ENVIRONMENT,
    )
    
    auth_url = auth_client.get_authorization_url([ Scopes.ACCOUNTING ])
    
    print("--- QuickBooks Initial Authentication ---")
    print("\nStarting a temporary web server at http://localhost:8000 ...")
    
    # Open the auth URL in the user's browser
    webbrowser.open(auth_url)
    print(f"\nYour browser should open. If not, please visit this URL:\n{auth_url}\n")
    print("Please log in to QuickBooks and authorize the app.")
    print("Waiting for you to authorize...")

    # Start the server and wait for the one request
    httpd = None
    try:
        with socketserver.TCPServer(("", PORT), OAuthCallbackHandler) as httpd:
            # Handle one request, which will set the global vars
            httpd.handle_request()
    except OSError as e:
        print(f"\nError: Could not start web server on port {PORT}.")
        print("Another service might be using it, or you may have a permissions issue.")
        print("Please stop the other service and try again.")
        print(f"Details: {e}")
        return
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return
    finally:
        if httpd:
            httpd.server_close()
            
    print("Authorization received! Shutting down web server.")

    if auth_code and realm_id:
        print("Exchanging authorization code for tokens...")
        try:
            auth_client.get_bearer_token(auth_code, realm_id=realm_id)
            
            print("\n--- SUCCESS! ---")
            print("Your tokens are ready. Copy these values into your .env file:\n")
            print("--------------------------------------------------")
            print(f"QB_ACCESS_TOKEN={auth_client.access_token}")
            print(f"QB_REFRESH_TOKEN={auth_client.refresh_token}")
            print(f"QB_REALM_ID={auth_client.realm_id}")
            print("--------------------------------------------------")
            
        except Exception as e:
            print(f"\nError getting tokens: {e}")
            print("Please try running the script again.")
    else:
        print("\nError: Could not get authorization code or realmId. Please try again.")

if __name__ == "__main__":
    get_tokens()