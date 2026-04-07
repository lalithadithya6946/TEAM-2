#!/usr/bin/env python3
"""
Test script for UVPAS CCTV System
This script tests all major components of the system
"""

import os
import sys
from pathlib import Path

# Use script directory as base so tests work regardless of cwd
BASE_DIR = os.path.dirname(__file__)

def test_imports():
    """Test if all required modules can be imported"""
    print("Testing module imports...")
    
    try:
        import flask
        print("✓ Flask imported successfully")
    except ImportError as e:
        print(f"✗ Flask import failed: {e}")
        return False
    
    try:
        import cv2
        print("✓ OpenCV imported successfully")
    except ImportError as e:
        print(f"✗ OpenCV import failed: {e}")
        return False
    
    try:
        import numpy
        print("✓ NumPy imported successfully")
    except ImportError as e:
        print(f"✗ NumPy import failed: {e}")
        return False
    
    try:
        import face_recognition
        print("✓ Face Recognition imported successfully")
    except ImportError as e:
        print(f"✗ Face Recognition import failed: {e}")
        return False
    
    return True

def test_app_creation():
    """Test if the Flask app can be created"""
    print("\nTesting Flask app creation...")
    
    try:
        # Ensure import uses module from this folder
        sys.path.insert(0, BASE_DIR)
        from app import app
        print("✓ Flask app created successfully")
        print(f"✓ App name: {app.name}")
        print(f"✓ App secret key: {'Set' if app.secret_key else 'Not set'}")
        return True
    except Exception as e:
        print(f"✗ Flask app creation failed: {e}")
        return False

def test_database_connection():
    """Test database connections"""
    print("\nTesting database connections...")
    
    try:
        from data_manager import DataManager
        dm = DataManager()
        print("✓ DataManager created successfully")
        
        # Test getting a student
        student = dm.get_student("99220041142")
        if student:
            print(f"✓ Demo student found: {student['name']}")
        else:
            print("⚠ Demo student not found (this is normal for fresh install)")
        
        return True
    except Exception as e:
        print(f"✗ Database connection failed: {e}")
        return False

def test_file_structure():
    """Test if all required files and directories exist"""
    print("\nTesting file structure...")
    
    required_files = [
        os.path.join(BASE_DIR, "app.py"),
        os.path.join(BASE_DIR, "auth.py"),
        os.path.join(BASE_DIR, "data_manager.py"),
        os.path.join(BASE_DIR, "recognition.py"),
        os.path.join(BASE_DIR, "requirements.txt")
    ]
    
    required_dirs = [
        os.path.join(BASE_DIR, "templates"),
        os.path.join(BASE_DIR, "static"),
        os.path.join(BASE_DIR, "student_photos"),
        os.path.join(BASE_DIR, "students_data")
    ]
    
    all_good = True
    
    for file in required_files:
        if os.path.exists(file):
            print(f"✓ {file} exists")
        else:
            print(f"✗ {file} missing")
            all_good = False
    
    for dir_name in required_dirs:
        if os.path.exists(dir_name):
            print(f"✓ {dir_name}/ directory exists")
        else:
            print(f"✗ {dir_name}/ directory missing")
            all_good = False
    
    return all_good

def test_templates():
    """Test if all required templates exist"""
    print("\nTesting template files...")
    
    required_templates = [
        "login.html",
        "faculty_dashboard.html",
        "student_dashboard.html",
        "view_video.html",
        "student_profile.html"
    ]
    
    all_good = True
    
    for template in required_templates:
        template_path = os.path.join(BASE_DIR, "templates", template)
        if os.path.exists(template_path):
            print(f"✓ {template} exists")
        else:
            print(f"✗ {template} missing")
            all_good = False
    
    return all_good

def test_routes():
    """Test if all required routes are defined"""
    print("\nTesting route definitions...")
    
    try:
        from app import app
        
        required_routes = [
            "/",
            "/login",
            "/logout", 
            "/faculty_dashboard",
            "/student_dashboard",
            "/upload_photo",
            "/upload_video",
            "/view_video/<filename>",
            "/student/<regno>"
        ]
        
        all_good = True
        
        for route in required_routes:
            # Check if route exists in app.url_map
            route_exists = False
            for rule in app.url_map.iter_rules():
                if rule.rule == route or rule.rule.startswith(route.split('<')[0]):
                    route_exists = True
                    break
            
            if route_exists:
                print(f"✓ Route {route} exists")
            else:
                print(f"✗ Route {route} missing")
                all_good = False
        
        return all_good
        
    except Exception as e:
        print(f"✗ Route testing failed: {e}")
        return False

def main():
    """Run all tests"""
    print("=" * 50)
    print("UVPAS CCTV System - System Test")
    print("=" * 50)
    
    tests = [
        ("Module Imports", test_imports),
        ("Flask App Creation", test_app_creation),
        ("Database Connection", test_database_connection),
        ("File Structure", test_file_structure),
        ("Template Files", test_templates),
        ("Route Definitions", test_routes)
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"✗ {test_name} failed with exception: {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "=" * 50)
    print("TEST SUMMARY")
    print("=" * 50)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"{test_name}: {status}")
    
    print(f"\nOverall: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! System is ready to run.")
        print("\nTo start the system:")
        print("1. python app.py")
        print("2. Open http://localhost:5000 in your browser")
        print("3. Use demo credentials to login")
    else:
        print("⚠ Some tests failed. Please check the issues above.")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
