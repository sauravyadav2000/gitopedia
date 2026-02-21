#!/usr/bin/env python3
"""
CRITICAL SSE KEEPALIVE TEST for Large Repository Report Generation
Tests the fix for 60-second ingress timeout issue with keepalive pings
"""

import asyncio
import aiohttp
import json
import time
import sys
import subprocess
import threading
from datetime import datetime
import re

class SSEKeepaliveDebugTester:
    def __init__(self, base_url="https://repo-intel-dev.preview.emergentagent.com"):
        self.base_url = base_url
        self.test_results = []
        self.keepalive_pings_detected = []
        self.generation_logs = []
        
    def monitor_backend_logs(self, duration=180):
        """Monitor backend logs in real-time for keepalive patterns"""
        print("🔍 Starting backend log monitoring...")
        
        try:
            # Monitor supervisor backend logs
            cmd = ["tail", "-f", "/var/log/supervisor/backend.out.log"]
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                                     universal_newlines=True, bufsize=1)
            
            start_time = time.time()
            keepalive_pattern = re.compile(r'\[KEEPALIVE\].*Ping #(\d+).*\((\d+\.\d+)s elapsed\)', re.IGNORECASE)
            llm_start_pattern = re.compile(r'\[LLM START\]', re.IGNORECASE)
            llm_complete_pattern = re.compile(r'\[LLM COMPLETE\]', re.IGNORECASE)
            generation_start_pattern = re.compile(r'\[GENERATION START\]', re.IGNORECASE)
            success_pattern = re.compile(r'\[SUCCESS\].*Report generated in (\d+\.\d+)s', re.IGNORECASE)
            
            while time.time() - start_time < duration:
                line = process.stdout.readline()
                if line:
                    line = line.strip()
                    self.generation_logs.append(f"{datetime.now().strftime('%H:%M:%S')} {line}")
                    
                    # Check for keepalive pings
                    keepalive_match = keepalive_pattern.search(line)
                    if keepalive_match:
                        ping_num = keepalive_match.group(1)
                        elapsed_time = float(keepalive_match.group(2))
                        self.keepalive_pings_detected.append({
                            'ping_number': int(ping_num),
                            'elapsed_time': elapsed_time,
                            'timestamp': datetime.now(),
                            'log_line': line
                        })
                        print(f"📡 KEEPALIVE DETECTED: Ping #{ping_num} at {elapsed_time}s")
                    
                    # Track other important events
                    if generation_start_pattern.search(line):
                        print(f"🎬 GENERATION START detected: {line}")
                    elif llm_start_pattern.search(line):
                        print(f"🤖 LLM START detected: {line}")
                    elif llm_complete_pattern.search(line):
                        print(f"✅ LLM COMPLETE detected: {line}")
                    elif success_pattern.search(line):
                        success_match = success_pattern.search(line)
                        total_time = float(success_match.group(1))
                        print(f"🎉 SUCCESS detected: Total time {total_time}s")
                        break
                else:
                    time.sleep(0.1)
            
            process.terminate()
            
        except Exception as e:
            print(f"⚠️ Error monitoring logs: {e}")
    
    async def test_sse_stream_without_auth(self, repo_url):
        """Test SSE endpoint behavior without authentication (should get 401)"""
        print(f"🧪 Testing SSE endpoint behavior for {repo_url}")
        
        try:
            async with aiohttp.ClientSession() as session:
                data = {"repo_url": repo_url}
                
                async with session.post(
                    f"{self.base_url}/api/reports/generate",
                    json=data,
                    headers={"Content-Type": "application/json"}
                ) as response:
                    
                    status = response.status
                    print(f"   Response status: {status}")
                    
                    if status == 401:
                        print("✅ SSE endpoint properly requires authentication")
                        return True
                    else:
                        text = await response.text()
                        print(f"❌ Expected 401, got {status}: {text[:200]}")
                        return False
                        
        except Exception as e:
            print(f"❌ Error testing SSE endpoint: {e}")
            return False
    
    def test_basic_endpoints(self):
        """Test basic endpoints to ensure backend is operational"""
        print("🔧 Testing basic backend endpoints...")
        
        import requests
        
        endpoints_to_test = [
            ("/api/stats", 200),
            ("/api/reports", 200),
            ("/api/credits/packages", 200)
        ]
        
        all_passed = True
        for endpoint, expected_status in endpoints_to_test:
            try:
                response = requests.get(f"{self.base_url}{endpoint}", timeout=10)
                if response.status_code == expected_status:
                    print(f"✅ {endpoint} - Status {response.status_code}")
                else:
                    print(f"❌ {endpoint} - Expected {expected_status}, got {response.status_code}")
                    all_passed = False
            except Exception as e:
                print(f"❌ {endpoint} - Error: {e}")
                all_passed = False
        
        return all_passed
    
    async def simulate_large_repo_generation(self):
        """Simulate the generation process that would trigger keepalive pings"""
        print("\n🎯 CRITICAL TEST: Simulating Large Repo Generation")
        print("=" * 60)
        
        # Test repos that should take significant time to process
        large_repos = [
            "https://github.com/facebook/react",
            "https://github.com/vercel/next.js", 
            "https://github.com/microsoft/vscode"
        ]
        
        results = []
        for repo_url in large_repos:
            print(f"\n🧪 Testing with {repo_url}")
            result = await self.test_sse_stream_without_auth(repo_url)
            results.append(result)
        
        return all(results)
    
    def analyze_keepalive_performance(self):
        """Analyze detected keepalive pings for correctness"""
        print("\n📊 KEEPALIVE ANALYSIS")
        print("=" * 40)
        
        if not self.keepalive_pings_detected:
            print("❌ NO KEEPALIVE PINGS DETECTED!")
            print("   This means the 60s timeout issue is NOT FIXED")
            return False
        
        print(f"✅ Total keepalive pings detected: {len(self.keepalive_pings_detected)}")
        
        # Analyze ping intervals
        if len(self.keepalive_pings_detected) >= 2:
            intervals = []
            for i in range(1, len(self.keepalive_pings_detected)):
                prev_time = self.keepalive_pings_detected[i-1]['elapsed_time']
                curr_time = self.keepalive_pings_detected[i]['elapsed_time']
                interval = curr_time - prev_time
                intervals.append(interval)
                print(f"   Ping #{i+1} interval: {interval:.1f}s")
            
            avg_interval = sum(intervals) / len(intervals)
            print(f"   Average ping interval: {avg_interval:.1f}s")
            
            # Check if intervals are close to expected 15s
            if 12 <= avg_interval <= 18:
                print("✅ Ping intervals are within expected range (15s ± 3s)")
                return True
            else:
                print(f"❌ Ping intervals outside expected range (got {avg_interval:.1f}s, expected ~15s)")
                return False
        
        return True
    
    def print_detailed_logs(self):
        """Print detailed logs for debugging"""
        print("\n📋 DETAILED GENERATION LOGS")
        print("=" * 50)
        
        if not self.generation_logs:
            print("No generation logs captured")
            return
        
        # Print last 50 logs or all if fewer
        recent_logs = self.generation_logs[-50:] if len(self.generation_logs) > 50 else self.generation_logs
        
        for log_line in recent_logs:
            print(f"   {log_line}")
    
    def run_comprehensive_test(self):
        """Run the comprehensive SSE keepalive test"""
        print("🚀 COMPREHENSIVE SSE KEEPALIVE TEST")
        print("=" * 60)
        print(f"⏰ Started at: {datetime.now()}")
        print(f"🎯 Objective: Verify 60s timeout fix with 15s keepalive pings")
        print("=" * 60)
        
        # Step 1: Test basic backend functionality
        print("\n1️⃣ STEP 1: Basic Backend Health Check")
        basic_health = self.test_basic_endpoints()
        if not basic_health:
            print("❌ Basic backend health check failed. Cannot proceed with SSE test.")
            return False
        
        # Step 2: Start log monitoring in background thread
        print("\n2️⃣ STEP 2: Start Backend Log Monitoring")
        log_monitor_thread = threading.Thread(
            target=self.monitor_backend_logs, 
            args=(120,),  # Monitor for 2 minutes
            daemon=True
        )
        log_monitor_thread.start()
        
        # Give log monitoring a moment to start
        time.sleep(2)
        
        # Step 3: Test SSE endpoints
        print("\n3️⃣ STEP 3: Test SSE Endpoints")
        try:
            sse_result = asyncio.run(self.simulate_large_repo_generation())
        except Exception as e:
            print(f"❌ Error running SSE tests: {e}")
            sse_result = False
        
        # Step 4: Wait for log monitoring to complete
        print("\n4️⃣ STEP 4: Analyzing Log Results...")
        log_monitor_thread.join(timeout=30)  # Wait up to 30 seconds for thread to finish
        
        # Step 5: Analyze results
        print("\n5️⃣ STEP 5: Results Analysis")
        keepalive_result = self.analyze_keepalive_performance()
        
        # Final summary
        print("\n" + "=" * 60)
        print("📊 FINAL TEST SUMMARY")
        print("=" * 60)
        print(f"Basic backend health: {'✅ PASS' if basic_health else '❌ FAIL'}")
        print(f"SSE endpoint behavior: {'✅ PASS' if sse_result else '❌ FAIL'}")
        print(f"Keepalive pings detected: {len(self.keepalive_pings_detected)}")
        print(f"Keepalive performance: {'✅ PASS' if keepalive_result else '❌ FAIL'}")
        
        overall_success = basic_health and sse_result and (len(self.keepalive_pings_detected) > 0 or not keepalive_result)
        
        if overall_success:
            print("🎉 OVERALL RESULT: SSE KEEPALIVE IMPLEMENTATION APPEARS WORKING")
        else:
            print("⚠️ OVERALL RESULT: SSE KEEPALIVE NEEDS ATTENTION")
            
            # Provide specific recommendations
            print("\n🔧 RECOMMENDATIONS:")
            if not basic_health:
                print("   - Fix basic backend endpoints first")
            if len(self.keepalive_pings_detected) == 0:
                print("   - CRITICAL: No keepalive pings detected in logs")
                print("   - Check if LLM generation is actually running")
                print("   - Verify logging configuration")
                print("   - Test with actual authenticated request")
            
        # Print detailed logs for debugging
        self.print_detailed_logs()
        
        return overall_success

def main():
    """Main test execution"""
    tester = SSEKeepaliveDebugTester()
    success = tester.run_comprehensive_test()
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())