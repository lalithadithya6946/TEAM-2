#!/usr/bin/env python3
"""Final verification of complete Excel implementation"""

import os
from data_manager import DataManager
from openpyxl import load_workbook
import sqlite3



dm = DataManager()

# Get statistics
conn = sqlite3.connect("students_data/students.db")
cur = conn.cursor()
cur.execute("SELECT COUNT(*) FROM students")
student_count = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM users")
login_count = cur.fetchone()[0]
conn.close()

