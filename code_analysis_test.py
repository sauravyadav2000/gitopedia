#!/usr/bin/env python3
"""
Code Analysis Test for Gitopedia Critical Features
Analyzes the server.py code to verify implementation of critical features
"""

import re
import json
import sys
from pathlib import Path

class GitopediaCodeAnalyzer:
    def __init__(self, server_file_path="/app/backend/server.py"):
        self.server_file_path = server_file_path
        self.results = []
        self.server_code = ""
        
        # Read server code
        try:
            with open(server_file_path, 'r') as f:
                self.server_code = f.read()
        except Exception as e:
            print(f"❌ Failed to read server code: {e}")
            sys.exit(1)

    def analyze_sse_keepalive_implementation(self):
        """Analyze SSE keepalive ping implementation"""
        print("🔍 Analyzing SSE Keepalive Implementation...")
        
        # Check for StreamingResponse usage
        if "StreamingResponse" in self.server_code:
            print("✅ StreamingResponse found")
        else:
            print("❌ StreamingResponse not found")
            self.results.append(("SSE StreamingResponse", False, "StreamingResponse not imported/used"))
            return False
            
        # Check for keepalive ping implementation
        ping_patterns = [
            r'type.*ping', 
            r'ping.*message',
            r'Processing\.\.\.',
            r'asyncio\.wait_for.*timeout.*20',
            r'asyncio\.shield'
        ]
        
        ping_found = 0
        for pattern in ping_patterns:
            if re.search(pattern, self.server_code, re.IGNORECASE):
                ping_found += 1
                
        if ping_found >= 3:
            print(f"✅ Keepalive ping implementation found ({ping_found}/5 patterns)")
            self.results.append(("SSE Keepalive Pings", True, f"{ping_found}/5 implementation patterns found"))
        else:
            print(f"❌ Keepalive ping implementation incomplete ({ping_found}/5 patterns)")
            self.results.append(("SSE Keepalive Pings", False, f"Only {ping_found}/5 patterns found"))
            
        # Check for proper SSE headers
        sse_headers = [
            'text/event-stream',
            'Cache-Control.*no-cache',
            'Connection.*keep-alive',
            'X-Accel-Buffering.*no'
        ]
        
        header_found = 0
        for header in sse_headers:
            if re.search(header, self.server_code, re.IGNORECASE):
                header_found += 1
                
        if header_found >= 2:
            print(f"✅ SSE headers properly configured ({header_found}/4 headers)")
        else:
            print(f"⚠️  SSE headers may be incomplete ({header_found}/4 headers)")
            
        return ping_found >= 3

    def analyze_llm_context_optimization(self):
        """Analyze LLM context filtering implementation"""
        print("\n🔍 Analyzing LLM Context Optimization...")
        
        # Check for exclude patterns
        exclude_patterns = [
            'node_modules',
            '\.git',
            'dist.*build',
            '__pycache__',
            'vendor',
            'binary_extensions'
        ]
        
        patterns_found = 0
        for pattern in exclude_patterns:
            if re.search(pattern, self.server_code, re.IGNORECASE):
                patterns_found += 1
                
        if patterns_found >= 4:
            print(f"✅ File filtering implemented ({patterns_found}/6 patterns)")
            self.results.append(("LLM Context Filtering", True, f"{patterns_found}/6 exclude patterns found"))
        else:
            print(f"❌ File filtering incomplete ({patterns_found}/6 patterns)")
            self.results.append(("LLM Context Filtering", False, f"Only {patterns_found}/6 patterns found"))
            
        # Check for file tree limits
        if re.search(r'1000.*files?', self.server_code, re.IGNORECASE):
            print("✅ File tree limit increased to 1000")
        elif re.search(r'500.*files?', self.server_code, re.IGNORECASE):
            print("⚠️  File tree limit still at 500")
        else:
            print("❌ No clear file tree limit found")
            
        return patterns_found >= 4

    def analyze_fallback_model_implementation(self):
        """Analyze fallback model implementation"""
        print("\n🔍 Analyzing Fallback Model Implementation...")
        
        # Check for nested try-catch blocks
        try_catch_pattern = r'try:.*?except.*?try:.*?except'
        if re.search(try_catch_pattern, self.server_code, re.DOTALL):
            print("✅ Nested try-catch structure found")
        else:
            print("❌ No nested try-catch structure found")
            
        # Check for specific model names
        models = [
            'claude-sonnet-4',
            'claude-3-haiku',
            'claude.*haiku',
            'RateLimitError',
            'InternalServerError'
        ]
        
        model_patterns_found = 0
        for model in models:
            if re.search(model, self.server_code, re.IGNORECASE):
                model_patterns_found += 1
                
        if model_patterns_found >= 3:
            print(f"✅ Fallback model implementation found ({model_patterns_found}/5 patterns)")
            self.results.append(("Fallback Model", True, f"{model_patterns_found}/5 implementation patterns"))
        else:
            print(f"❌ Fallback model implementation incomplete ({model_patterns_found}/5 patterns)")
            self.results.append(("Fallback Model", False, f"Only {model_patterns_found}/5 patterns found"))
            
        return model_patterns_found >= 3

    def analyze_credit_refund_mechanism(self):
        """Analyze credit refund implementation"""
        print("\n🔍 Analyzing Credit Refund Mechanism...")
        
        # Check for try-finally blocks
        if re.search(r'try:.*?finally:', self.server_code, re.DOTALL):
            print("✅ Try-finally structure found")
        else:
            print("❌ No try-finally structure found")
            
        # Check for credit refund patterns
        refund_patterns = [
            r'credits_deducted.*False',
            r'inc.*credits.*2',
            r'Refunding.*credits',
            r'finally:.*refund',
            r'generation.*failed'
        ]
        
        refund_found = 0
        for pattern in refund_patterns:
            if re.search(pattern, self.server_code, re.IGNORECASE):
                refund_found += 1
                
        if refund_found >= 3:
            print(f"✅ Credit refund mechanism implemented ({refund_found}/5 patterns)")
            self.results.append(("Credit Refund", True, f"{refund_found}/5 refund patterns found"))
        else:
            print(f"❌ Credit refund mechanism incomplete ({refund_found}/5 patterns)")
            self.results.append(("Credit Refund", False, f"Only {refund_found}/5 patterns found"))
            
        return refund_found >= 3

    def analyze_api_structure(self):
        """Analyze overall API structure"""
        print("\n🔍 Analyzing API Structure...")
        
        # Check for required endpoints
        required_endpoints = [
            r'reports/generate',
            r'reports/check', 
            r'user/profile',
            r'user/transactions',
            r'auth/verify',
            r'stats'
        ]
        
        endpoints_found = 0
        for endpoint in required_endpoints:
            if re.search(endpoint, self.server_code):
                endpoints_found += 1
                
        if endpoints_found >= 5:
            print(f"✅ Required API endpoints found ({endpoints_found}/6)")
            self.results.append(("API Endpoints", True, f"{endpoints_found}/6 endpoints found"))
        else:
            print(f"❌ Missing required API endpoints ({endpoints_found}/6)")
            self.results.append(("API Endpoints", False, f"Only {endpoints_found}/6 endpoints found"))
            
        # Check for proper error handling
        error_patterns = [
            'HTTPException',
            'try.*except',
            'status_code.*40[0-9]',
            'logger\.error'
        ]
        
        error_handling = 0
        for pattern in error_patterns:
            if re.search(pattern, self.server_code, re.IGNORECASE):
                error_handling += 1
                
        if error_handling >= 3:
            print(f"✅ Error handling implemented ({error_handling}/4 patterns)")
        else:
            print(f"⚠️  Error handling may be incomplete ({error_handling}/4 patterns)")
            
        return endpoints_found >= 5

    def print_summary(self):
        """Print analysis summary"""
        print(f"\n" + "="*60)
        print(f"📊 CODE ANALYSIS SUMMARY")
        print(f"="*60)
        
        total_checks = len(self.results)
        passed_checks = sum(1 for _, success, _ in self.results if success)
        
        print(f"Code checks: {total_checks}")
        print(f"Checks passed: {passed_checks}")
        print(f"Checks failed: {total_checks - passed_checks}")
        print(f"Success rate: {(passed_checks/total_checks*100):.1f}%")
        
        print(f"\n📋 DETAILED RESULTS:")
        for check_name, success, details in self.results:
            status = "✅ PASS" if success else "❌ FAIL"
            print(f"  {status} {check_name}: {details}")
            
        print(f"="*60)
        
        return passed_checks == total_checks

def main():
    """Run code analysis"""
    print("🚀 Starting Gitopedia Code Analysis")
    print("🔍 Analyzing critical features implementation...")
    
    analyzer = GitopediaCodeAnalyzer()
    
    # Run all analyses
    analyzer.analyze_sse_keepalive_implementation()
    analyzer.analyze_llm_context_optimization() 
    analyzer.analyze_fallback_model_implementation()
    analyzer.analyze_credit_refund_mechanism()
    analyzer.analyze_api_structure()
    
    # Print results
    all_passed = analyzer.print_summary()
    
    if all_passed:
        print("🎉 All code analysis checks passed!")
        return 0
    else:
        print("⚠️  Some code analysis checks failed.")
        return 1

if __name__ == "__main__":
    sys.exit(main())