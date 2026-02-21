#!/usr/bin/env python3

import requests
import sys
import json
import time
import asyncio
import aiohttp
from datetime import datetime
import re

class GitopediaAPITester:
    def __init__(self, base_url="https://report-gen-staging-1.preview.emergentagent.com"):
        self.base_url = base_url
        self.token = None
        self.tests_run = 0
        self.tests_passed = 0
        self.failed_tests = []

    def run_test(self, name, method, endpoint, expected_status, data=None, headers=None):
        """Run a single API test"""
        url = f"{self.base_url}{endpoint}"
        test_headers = {'Content-Type': 'application/json'}
        if headers:
            test_headers.update(headers)

        self.tests_run += 1
        print(f"\n🔍 Testing {name}...")
        print(f"   URL: {method} {url}")
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=test_headers, timeout=10)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=test_headers, timeout=10)
            elif method == 'PUT':
                response = requests.put(url, json=data, headers=test_headers, timeout=10)

            success = response.status_code == expected_status
            if success:
                self.tests_passed += 1
                print(f"✅ PASSED - Status: {response.status_code}")
                try:
                    response_data = response.json()
                    print(f"   Response: {json.dumps(response_data, indent=2)[:200]}...")
                except:
                    print(f"   Response: {response.text[:100]}...")
            else:
                print(f"❌ FAILED - Expected {expected_status}, got {response.status_code}")
                print(f"   Response: {response.text[:200]}...")
                self.failed_tests.append({
                    "test": name,
                    "expected": expected_status,
                    "actual": response.status_code,
                    "response": response.text[:200]
                })

            return success, response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text

        except requests.exceptions.RequestException as e:
            print(f"❌ FAILED - Network error: {str(e)}")
            self.failed_tests.append({
                "test": name,
                "error": str(e)
            })
            return False, {}
        except Exception as e:
            print(f"❌ FAILED - Error: {str(e)}")
            self.failed_tests.append({
                "test": name,
                "error": str(e)
            })
            return False, {}

    def test_stats_endpoint(self):
        """Test /api/stats endpoint returns correct structure"""
        success, response = self.run_test(
            "Stats Endpoint Structure",
            "GET", 
            "/api/stats",
            200
        )
        
        if success:
            # Verify response structure
            required_fields = ['total_reports', 'total_users']
            missing_fields = [field for field in required_fields if field not in response]
            if missing_fields:
                print(f"❌ Missing required fields: {missing_fields}")
                return False
            
            # Verify field types
            if not isinstance(response.get('total_reports'), int) or not isinstance(response.get('total_users'), int):
                print(f"❌ Invalid field types in stats response")
                return False
                
            print(f"✅ Stats structure valid: {response}")
            
        return success

    def test_reports_list_empty(self):
        """Test /api/reports returns empty list for fresh DB"""
        success, response = self.run_test(
            "Reports List (Fresh DB)",
            "GET",
            "/api/reports",
            200
        )
        
        if success:
            # Verify response structure for empty DB
            if not isinstance(response, dict) or 'reports' not in response:
                print(f"❌ Invalid reports response structure")
                return False
            
            # For fresh DB, reports should be empty array
            reports = response.get('reports', [])
            print(f"✅ Reports list returned: {len(reports)} reports")
            
        return success

    def test_reports_check_validation(self):
        """Test /api/reports/check validates GitHub URL format"""
        test_cases = [
            # Valid URLs should return 200
            {
                "url": "https://github.com/facebook/react",
                "expected_status": 200,
                "description": "Valid GitHub URL"
            },
            # Invalid URLs should return 400
            {
                "url": "invalid-url",
                "expected_status": 400,
                "description": "Invalid URL format"
            },
            {
                "url": "https://gitlab.com/user/repo",
                "expected_status": 400,
                "description": "Non-GitHub URL"
            }
        ]

        all_passed = True
        for case in test_cases:
            success, response = self.run_test(
                f"Reports Check - {case['description']}",
                "POST",
                "/api/reports/check",
                case['expected_status'],
                {"repo_url": case['url']}
            )
            
            if not success:
                all_passed = False
            elif case['expected_status'] == 200:
                # For valid URLs, should return exists field
                if 'exists' not in response:
                    print(f"❌ Missing 'exists' field in response")
                    all_passed = False
                    
        return all_passed

    def test_auth_verify_endpoint(self):
        """Test /api/auth/verify endpoint exists and rejects invalid tokens"""
        
        # Test with no token
        success, response = self.run_test(
            "Auth Verify - No Token",
            "POST",
            "/api/auth/verify",
            400,
            {}
        )
        
        # Test with invalid token
        success2, response2 = self.run_test(
            "Auth Verify - Invalid Token", 
            "POST",
            "/api/auth/verify",
            401,
            {"token": "invalid-token-123"}
        )
        
        return success and success2

    def test_user_profile_unauthorized(self):
        """Test /api/user/profile requires authentication"""
        success, response = self.run_test(
            "User Profile - Unauthorized",
            "GET",
            "/api/user/profile", 
            401
        )
        return success

    def test_reports_generate_unauthorized(self):
        """Test /api/reports/generate requires authentication"""
        success, response = self.run_test(
            "Reports Generate - Unauthorized",
            "POST",
            "/api/reports/generate",
            401,
            {"repo_url": "https://github.com/facebook/react"}
        )
        return success
    
    def test_user_transactions_unauthorized(self):
        """Test /api/user/transactions requires authentication"""
        success, response = self.run_test(
            "User Transactions - Unauthorized",
            "GET",
            "/api/user/transactions",
            401
        )
        return success

    def print_summary(self):
        """Print test results summary"""
        print(f"\n" + "="*60)
        print(f"📊 BACKEND TEST SUMMARY")
        print(f"="*60)
        print(f"Tests run: {self.tests_run}")
        print(f"Tests passed: {self.tests_passed}")
        print(f"Tests failed: {self.tests_run - self.tests_passed}")
        print(f"Success rate: {(self.tests_passed/self.tests_run*100):.1f}%")
        
        if self.failed_tests:
            print(f"\n❌ FAILED TESTS:")
            for i, failure in enumerate(self.failed_tests, 1):
                print(f"  {i}. {failure['test']}")
                if 'expected' in failure:
                    print(f"     Expected: {failure['expected']}, Got: {failure['actual']}")
                if 'error' in failure:
                    print(f"     Error: {failure['error']}")
                    
        print(f"="*60)

def main():
    """Run all backend API tests"""
    print("🚀 Starting Gitopedia Backend API Tests")
    print(f"⏰ Test started at: {datetime.now()}")
    
    tester = GitopediaAPITester()
    
    # Run all tests
    print("\n📋 Running Core API Tests...")
    tester.test_stats_endpoint()
    tester.test_reports_list_empty() 
    tester.test_reports_check_validation()
    tester.test_auth_verify_endpoint()
    
    print("\n🔒 Running Authentication Tests...")
    tester.test_user_profile_unauthorized()
    tester.test_reports_generate_unauthorized()
    tester.test_user_transactions_unauthorized()
    
    # Print results
    tester.print_summary()
    
    # Return appropriate exit code
    if tester.tests_passed == tester.tests_run:
        print("🎉 All tests passed!")
        return 0
    else:
        print("⚠️  Some tests failed. Check the summary above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())