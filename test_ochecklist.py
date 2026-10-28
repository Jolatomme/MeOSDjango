#!/usr/bin/env python3
"""
Test script for O'checklist integration
This script demonstrates how to test the O'checklist endpoint

To send the file start_report.yaml for test :
curl -X POST -H "Content-Type: application/yaml" --data-binary @start_report.yaml http://localhost:8000/ochecklist/update/
"""

import hashlib
import base64
import gzip
import yaml
import requests
import json
import sys
import os

def create_test_yaml():
    """Create a simple test YAML similar to start_report.yaml"""
    test_data = {
        'Version': '1.5',
        'Creator': 'O Checklist Test',
        'Created': '2024-10-12T12:45:04+02:00',
        'Event': 'Test Event',
        'Data': [
            {
                'Runner': {
                    'StartStatus': 'Started OK',
                    'Id': 'TEST001',
                    'Name': 'Test Runner One',
                    'Org': 'Test Club',
                    'Card': '111111',
                    'StartTime': '2024-10-12T12:31:00+02:00',
                    'ClassName': 'TEST'
                },
                'ChangeLog': None
            },
            {
                'Runner': {
                    'StartStatus': 'DNS',
                    'Id': 'TEST002',
                    'Name': 'Test Runner Two',
                    'Org': 'Test Club',
                    'Card': '222222',
                    'StartTime': '2024-10-12T12:33:00+02:00',
                    'ClassName': 'TEST'
                },
                'ChangeLog': {
                    'DNS': '2024-10-12T12:34:56+02:00'
                }
            }
        ]
    }
    
    # Add EndOfData as in the original format
    test_data['EndOfData'] = {'Runners': 2, 'Lines': 0}
    yaml_output = yaml.dump(test_data, default_flow_style=False, allow_unicode=True)
    return yaml_output

def compute_digest(data, algorithm='sha-256', encoding='base64'):
    """Compute digest of data"""
    if algorithm == 'sha-256':
        hash_obj = hashlib.sha256(data)
    elif algorithm == 'sha-512':
        hash_obj = hashlib.sha512(data)
    elif algorithm == 'md5':
        hash_obj = hashlib.md5(data)
    else:
        raise ValueError(f"Unsupported algorithm: {algorithm}")
    
    digest_bytes = hash_obj.digest()
    
    if encoding == 'base64':
        return base64.b64encode(digest_bytes).decode('ascii')
    elif encoding == 'hex':
        return digest_bytes.hex()
    else:
        raise ValueError(f"Unsupported encoding: {encoding}")

def test_endpoint(base_url="http://localhost:8000"):
    """Test the O'checklist endpoint"""
    print("Testing O'checklist endpoint...")
    
    # Create test data
    yaml_data = create_test_yaml()
    print(f"Created YAML data ({len(yaml_data)} bytes)")
    
    # Test 1: Basic POST without compression or digest
    print("\n=== Test 1: Basic POST ===")
    try:
        response = requests.post(
            f"{base_url}/ochecklist/update/",
            data=yaml_data.encode('utf-8'),
            headers={'Content-Type': 'application/yaml'},
            timeout=10
        )
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")
        if response.status_code == 200:
            print("✓ Basic POST test passed")
        else:
            print("✗ Basic POST test failed")
    except Exception as e:
        print(f"✗ Basic POST test failed with exception: {e}")
    
    # Test 2: With Content-Digest (SHA-256, Base64)
    print("\n=== Test 2: With SHA-256 Base64 Digest ===")
    try:
        digest = compute_digest(yaml_data.encode('utf-8'), 'sha-256', 'base64')
        headers = {
            'Content-Type': 'application/yaml',
            'Content-Digest': f'sha-256={digest}'
        }
        response = requests.post(
            f"{base_url}/ochecklist/update/",
            data=yaml_data.encode('utf-8'),
            headers=headers,
            timeout=10
        )
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")
        if response.status_code == 200:
            print("✓ Digest test passed")
        else:
            print("✗ Digest test failed")
    except Exception as e:
        print(f"✗ Digest test failed with exception: {e}")
    
    # Test 3: With gzip compression
    print("\n=== Test 3: With Gzip Compression ===")
    try:
        compressed_data = gzip.compress(yaml_data.encode('utf-8'))
        digest = compute_digest(compressed_data, 'sha-256', 'base64')
        headers = {
            'Content-Type': 'application/yaml',
            'Content-Encoding': 'gzip',
            'Content-Digest': f'sha-256={digest}'
        }
        response = requests.post(
            f"{base_url}/ochecklist/update/",
            data=compressed_data,
            headers=headers,
            timeout=10
        )
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")
        if response.status_code == 200:
            print("✓ Gzip test passed")
        else:
            print("✗ Gzip test failed")
    except Exception as e:
        print(f"✗ Gzip test failed with exception: {e}")
    
    # Test 4: Invalid digest (should fail)
    print("\n=== Test 4: Invalid Digest (should fail) ===")
    try:
        headers = {
            'Content-Type': 'application/yaml',
            'Content-Digest': 'sha-256=invalidbase64digest!!!'
        }
        response = requests.post(
            f"{base_url}/ochecklist/update/",
            data=yaml_data.encode('utf-8'),
            headers=headers,
            timeout=10
        )
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")
        if response.status_code == 400:
            print("✓ Invalid digest correctly rejected")
        else:
            print("✗ Invalid digest should have been rejected")
    except Exception as e:
        print(f"✗ Invalid digest test failed with exception: {e}")

def check_admin_data(base_url="http://localhost:8000"):
    """Check if data was stored by querying the admin or list view"""
    print("\n=== Checking stored data ===")
    try:
        response = requests.get(f"{base_url}/ochecklist/", timeout=10)
        print(f"Reports list status: {response.status_code}")
        if response.status_code == 200:
            # Check if we see our test data in the response
            if 'Test Event' in response.text and 'Test Runner' in response.text:
                print("✓ Test data found in reports list")
            else:
                print("? Test data not clearly visible in reports list (may need admin check)")
        else:
            print("✗ Could not access reports list")
    except Exception as e:
        print(f"✗ Failed to check reports list: {e}")

def main():
    """Main test function"""
    print("O'checklist Integration Test")
    print("=" * 40)
    
    # Allow custom base URL from command line
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    print(f"Testing against: {base_url}")
    
    # Run tests
    test_endpoint(base_url)
    check_admin_data(base_url)
    
    print("\n" + "=" * 40)
    print("Test completed!")
    print("\nTo manually test:")
    print("1. Start the Django server: python manage.py runserver")
    print("2. Visit http://localhost:8000/ochecklist/ to see reports")
    print("3. Visit http://localhost:8000/admin/ to see detailed data")
    print("4. For Android app testing, you'll need HTTPS in production")

if __name__ == "__main__":
    main()
