#!/usr/bin/env python3
"""
Test script for video upload functionality
"""

import os
import requests
from pathlib import Path

# Use script directory as base so tests work regardless of cwd
BASE_DIR = os.path.dirname(__file__)

def test_upload_system():
    """Test the upload system"""
    print("Testing Video Upload System")
    print("=" * 40)
    
    # Check if Flask is running (use 127.0.0.1 to avoid localhost IPv6 issues)
    try:
        response = requests.get("http://127.0.0.1:5000/")
        print(f"✓ Flask server is running (Status: {response.status_code})")
    except requests.exceptions.ConnectionError:
        print("✗ Flask server is not running")
        print("Please start the server with: python app.py (from the `cctv` directory)")
        return False
    
    # Check upload folder
    upload_folder = os.path.join(BASE_DIR, "static", "uploads")
    print(f"\nUpload folder: {upload_folder}")
    print(f"Exists: {os.path.exists(upload_folder)}")
    print(f"Writable: {os.access(upload_folder, os.W_OK) if os.path.exists(upload_folder) else 'N/A'}")
    
    # Check if there are any existing videos
    if os.path.exists(upload_folder):
        videos = [f for f in os.listdir(upload_folder) if f.lower().endswith(('.mp4', '.avi', '.mov', '.mkv'))]
        print(f"Existing videos: {videos}")
    
    # Test login page
    try:
        response = requests.get("http://127.0.0.1:5000/login")
        print(f"\n✓ Login page accessible (Status: {response.status_code})")
    except Exception as e:
        print(f"✗ Login page error: {e}")
    
    print("\n" + "=" * 40)
    print("Manual Testing Steps:")
    print("1. Open http://localhost:5000 in browser")
    print("2. Login as faculty: PSBCSE / faculty@123")
    print("3. Try uploading a video file")
    print("4. Check terminal output for debug messages")
    
    return True

if __name__ == "__main__":
    test_upload_system()
