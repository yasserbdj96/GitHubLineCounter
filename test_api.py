#!/usr/bin/env python
# coding:utf-8
"""
Quick test script to verify the Flask app is working correctly
"""

import requests
import json

BASE_URL = "http://localhost:5000"

def test_api():
    print("="*60)
    print("Testing Code Statistics API")
    print("="*60)
    
    # Test 1: Get all statistics
    print("\n1. Testing /api/stats (all data)...")
    try:
        response = requests.get(f"{BASE_URL}/api/stats")
        if response.status_code == 200:
            data = response.json()
            print(f"   ✓ Success! Found {len(data)} languages")
            for lang, stats in list(data.items())[:3]:  # Show first 3
                print(f"     - {lang}: {stats['total_lines']:,} lines in {stats['files']} files")
        else:
            print(f"   ✗ Failed: Status {response.status_code}")
    except Exception as e:
        print(f"   ✗ Error: {e}")
    
    # Test 2: Get Python statistics
    print("\n2. Testing /api/stats?language=python...")
    try:
        response = requests.get(f"{BASE_URL}/api/stats?language=python")
        if response.status_code == 200:
            data = response.json()
            if 'PYTHON' in data:
                stats = data['PYTHON']
                print(f"   ✓ Success!")
                print(f"     - Files: {stats['files']}")
                print(f"     - Total Lines: {stats['total_lines']:,}")
                print(f"     - Code Lines: {stats['code_lines']:,}")
                print(f"     - Comment Lines: {stats['comment_lines']:,}")
            else:
                print(f"   ⚠ No Python data found")
        else:
            print(f"   ✗ Failed: Status {response.status_code}")
    except Exception as e:
        print(f"   ✗ Error: {e}")
    
    # Test 3: Get badge
    print("\n3. Testing /api/badge/total_lines...")
    try:
        response = requests.get(f"{BASE_URL}/api/badge/total_lines")
        if response.status_code == 200 and 'svg' in response.headers.get('Content-Type', ''):
            print(f"   ✓ Success! Badge SVG generated ({len(response.content)} bytes)")
            print(f"   📝 Markdown: ![Badge]({BASE_URL}/api/badge/total_lines)")
        else:
            print(f"   ✗ Failed: Status {response.status_code}")
    except Exception as e:
        print(f"   ✗ Error: {e}")
    
    # Test 4: Get Python badge
    print("\n4. Testing /api/badge/code_lines?language=python...")
    try:
        response = requests.get(f"{BASE_URL}/api/badge/code_lines?language=python")
        if response.status_code == 200:
            print(f"   ✓ Success! Python badge generated")
            print(f"   📝 Markdown: ![Python Code]({BASE_URL}/api/badge/code_lines?language=python)")
        else:
            print(f"   ✗ Failed: Status {response.status_code}")
    except Exception as e:
        print(f"   ✗ Error: {e}")
    
    # Test 5: Get weekly statistics
    print("\n5. Testing /api/stats?period=week...")
    try:
        response = requests.get(f"{BASE_URL}/api/stats?period=week")
        if response.status_code == 200:
            data = response.json()
            total_lines = sum(stats['total_lines'] for stats in data.values())
            print(f"   ✓ Success! Week total: {total_lines:,} lines across {len(data)} languages")
        else:
            print(f"   ✗ Failed: Status {response.status_code}")
    except Exception as e:
        print(f"   ✗ Error: {e}")
    
    print("\n" + "="*60)
    print("Test completed!")
    print("="*60)
    
    # Generate sample README badges
    print("\n📋 Sample README.md badges:\n")
    print(f"![Total Lines]({BASE_URL}/api/badge/total_lines)")
    print(f"![Code Lines]({BASE_URL}/api/badge/code_lines)")
    print(f"![Python Lines]({BASE_URL}/api/badge/total_lines?language=python)")
    print(f"![JavaScript Files]({BASE_URL}/api/badge/files?language=javascript)")
    print(f"![Total Files]({BASE_URL}/api/badge/files?color=%23ff6b6b)")
    print()

def show_all_languages():
    """Show all languages and their statistics"""
    print("\n" + "="*60)
    print("All Language Statistics")
    print("="*60)
    
    try:
        response = requests.get(f"{BASE_URL}/api/stats")
        if response.status_code == 200:
            data = response.json()
            
            # Sort by total lines
            sorted_langs = sorted(data.items(), key=lambda x: x[1]['total_lines'], reverse=True)
            
            print(f"\n{'Language':<15} {'Files':>8} {'Total Lines':>15} {'Code Lines':>15}")
            print("-"*60)
            
            for lang, stats in sorted_langs:
                print(f"{lang:<15} {stats['files']:>8} {stats['total_lines']:>15,} {stats['code_lines']:>15,}")
            
            # Totals
            total_files = sum(s['files'] for s in data.values())
            total_lines = sum(s['total_lines'] for s in data.values())
            total_code = sum(s['code_lines'] for s in data.values())
            
            print("-"*60)
            print(f"{'TOTAL':<15} {total_files:>8} {total_lines:>15,} {total_code:>15,}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == '--all':
        show_all_languages()
    else:
        test_api()
        
        print("\n💡 Tip: Run with --all to see all language statistics")
        print("   python test_api.py --all")