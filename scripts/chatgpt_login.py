"""One-time sign-in with ChatGPT for the novel-edge judge (no API key needed).

    python3 scripts/chatgpt_login.py

Opens your browser; you sign in and approve. Credentials are saved to ~/.pot-judge/chatgpt-auth.json (mode 0600).
Then run the portal with:   JUDGING_ENABLED=1 JUDGE_PROVIDER=chatgpt
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from judging import chatgpt_auth

if __name__ == "__main__":
    try:
        info = chatgpt_auth.login()
    except chatgpt_auth.AuthError as e:
        sys.exit(f"sign-in failed: {e}")
    print(f"signed in as {info['email'] or info['subject']} (scopes: {' '.join(info['scopes'])})")
