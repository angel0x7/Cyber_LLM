#!/usr/bin/env python3
"""
Lab 2 Results Analyzer - Comprehensive Observability Tool
=========================================================
Analyzes batch results from promptfoo evaluations to provide:
- Overall success/failure statistics
- Error type breakdown (429, 503, JSON errors, accuracy failures)
- Detailed failure analysis with root causes
- Raw output inspection for debugging

Usage:
    python tools/analyze_results.py
    python tools/analyze_results.py --batch 10        # Analyze specific batch
    python tools/analyze_results.py --failures-only   # Show only failed tests
    python tools/analyze_results.py --raw 10          # Show raw output for batch 10
"""

import argparse
import json
import glob
import os
import sys
from pathlib import Path


def load_batch_results(batch_num: int) -> dict:
    """Load results from a specific batch file."""
    filepath = f"reports/batches/batch_{batch_num:02d}_results.json"
    if not os.path.exists(filepath):
        return None
    with open(filepath, 'r') as f:
        return json.load(f)


def get_all_batch_files() -> list:
    """Get all batch result files sorted by number."""
    files = glob.glob("reports/batches/batch_*_results.json")
    return sorted(files)


def analyze_errors(results: list) -> dict:
    """Categorize errors from test results."""
    stats = {
        "total": len(results),
        "success": 0,
        "failures": 0,
        "429_rate_limit": 0,
        "503_overloaded": 0,
        "json_error": 0,
        "accuracy_error": 0,
        "other_error": 0
    }
    
    for r in results:
        if r.get('success', False):
            stats["success"] += 1
        else:
            stats["failures"] += 1
            error = str(r.get('response', {}).get('error', ''))
            
            if '429' in error or 'Rate limit' in error.lower():
                stats["429_rate_limit"] += 1
            elif '503' in error or 'overloaded' in error.lower():
                stats["503_overloaded"] += 1
            elif 'JSON' in error or 'json' in error or 'is-json' in str(r.get('gradingResult', {})):
                stats["json_error"] += 1
            elif r.get('response', {}).get('output'):
                # Got output but failed assertion = accuracy error
                stats["accuracy_error"] += 1
            else:
                stats["other_error"] += 1
    
    return stats


def print_comprehensive_analysis():
    """Print full analysis of all batches."""
    print("\n" + "=" * 70)
    print("🔍 COMPREHENSIVE RUN ANALYSIS")
    print("=" * 70 + "\n")
    
    batch_files = get_all_batch_files()
    if not batch_files:
        print("❌ No batch result files found in reports/batches/")
        print("   From labs/lab2, run the offline fixture evaluation first:\n")
        print("   export COURSE_PYTHON=\"$(command -v python3)\"")
        print("   export LLM_OFFLINE=1")
        print("   python run_batches_simple.py --config promptfooconfig_offline.yaml --batch-size 4\n")
        return
    
    total_stats = {
        "total": 0, "success": 0, "failures": 0,
        "429_rate_limit": 0, "503_overloaded": 0,
        "json_error": 0, "accuracy_error": 0, "other_error": 0
    }
    
    batches_with_issues = {
        "429": [], "503": [], "json": [], "accuracy": []
    }
    
    print(f"{'Batch':<10} {'Status':<12} {'Pass':<8} {'Fail':<8} {'Details':<30}")
    print("-" * 70)
    
    for batch_file in batch_files:
        batch_num = int(batch_file.split('batch_')[1].split('_')[0])
        
        try:
            with open(batch_file, 'r') as f:
                data = json.load(f)
                results = data.get('results', {}).get('results', [])
        except Exception as e:
            print(f"Batch {batch_num:2d}   ❌ ERROR      -        -        Could not read: {e}")
            continue
        
        stats = analyze_errors(results)
        
        # Aggregate totals
        for key in total_stats:
            total_stats[key] += stats[key]
        
        # Track problematic batches
        if stats["429_rate_limit"] > 0:
            batches_with_issues["429"].append(batch_num)
        if stats["503_overloaded"] > 0:
            batches_with_issues["503"].append(batch_num)
        if stats["json_error"] > 0:
            batches_with_issues["json"].append(batch_num)
        if stats["accuracy_error"] > 0:
            batches_with_issues["accuracy"].append(batch_num)
        
        # Status emoji
        if stats["failures"] == 0:
            status = "✅ PASS"
        elif stats["429_rate_limit"] > 0:
            status = "🚨 RATE LIM"
        elif stats["503_overloaded"] > 0:
            status = "⚠️  OVERLOAD"
        elif stats["json_error"] > 0:
            status = "📋 JSON ERR"
        else:
            status = "❌ FAIL"
        
        # Details
        details = []
        if stats["429_rate_limit"]:
            details.append(f"429:{stats['429_rate_limit']}")
        if stats["503_overloaded"]:
            details.append(f"503:{stats['503_overloaded']}")
        if stats["json_error"]:
            details.append(f"JSON:{stats['json_error']}")
        if stats["accuracy_error"]:
            details.append(f"Accuracy:{stats['accuracy_error']}")
        
        print(f"Batch {batch_num:2d}   {status:<12} {stats['success']:<8} {stats['failures']:<8} {', '.join(details) or 'OK'}")
    
    # Summary
    print("\n" + "=" * 70)
    print("📊 OVERALL RESULTS")
    print("=" * 70)
    print(f"\n   Total tests:     {total_stats['total']}")
    print(f"   ✅ Successes:    {total_stats['success']}")
    print(f"   ❌ Failures:     {total_stats['failures']}")
    if total_stats['total'] > 0:
        print(f"   📈 Pass rate:    {total_stats['success']/total_stats['total']*100:.1f}%")
    
    print(f"\n🔍 ERROR BREAKDOWN:")
    print(f"   🚨 429 Rate Limits:    {total_stats['429_rate_limit']}")
    print(f"   ⚠️  503 Server Errors:  {total_stats['503_overloaded']}")
    print(f"   📋 JSON Parse Errors:  {total_stats['json_error']}")
    print(f"   🎯 Accuracy Errors:    {total_stats['accuracy_error']}")
    print(f"   ❓ Other Errors:       {total_stats['other_error']}")
    
    print(f"\n📁 BATCHES WITH ISSUES:")
    print(f"   429 Rate Limits: {batches_with_issues['429'] or 'None'}")
    print(f"   503 Overloaded:  {batches_with_issues['503'] or 'None'}")
    print(f"   JSON Errors:     {batches_with_issues['json'] or 'None'}")
    print(f"   Accuracy Issues: {batches_with_issues['accuracy'] or 'None'}")
    
    # Recommendations
    print(f"\n💡 RECOMMENDATIONS:")
    if total_stats['429_rate_limit'] > 0:
        print("   • 429 errors: Increase --delay to 240 or wait 1 hour")
    if total_stats['503_overloaded'] > 0:
        print("   • 503 errors: The batch runner stopped without changing the configured model.")
        print("     Check provider status/limits, then rerun with the same explicit MODEL_ID.")
    if total_stats['json_error'] > 0:
        print("   • JSON errors: Model returned malformed JSON. Check raw output with:")
        print(f"     python tools/analyze_results.py --raw {batches_with_issues['json'][0] if batches_with_issues['json'] else 'N'}")
    if total_stats['accuracy_error'] > 0:
        print("   • Accuracy errors: Model misclassified vulnerabilities.")
        print("     Review with: python tools/analyze_results.py --failures-only")
        print("     Consider improving the prompt or providing examples")
    
    if total_stats['failures'] == 0:
        print("   No batch errors were recorded. Check case coverage and metrics before interpreting results.")
    
    print("\n" + "=" * 70 + "\n")


def print_failure_details():
    """Print detailed information about failed tests."""
    print("\n" + "=" * 70)
    print("🔍 CHECKING WHAT ERRORS OCCURRED IN FAILED BATCHES")
    print("=" * 70 + "\n")
    
    batch_files = get_all_batch_files()
    failure_count = 0
    
    for batch_file in batch_files:
        batch_num = int(batch_file.split('batch_')[1].split('_')[0])
        
        try:
            with open(batch_file, 'r') as f:
                data = json.load(f)
                results = data.get('results', {}).get('results', [])
        except Exception:
            continue
        
        has_failures = False
        for i, r in enumerate(results):
            if not r.get('success', False):
                if not has_failures:
                    print(f"\n{'='*50}")
                    print(f"=== BATCH {batch_num} ===")
                    print(f"{'='*50}")
                    has_failures = True
                
                failure_count += 1
                
                # Get test details
                vars_data = r.get('vars', {})
                snippet = vars_data.get('code', vars_data.get('snippet', 'unknown'))[:60]
                expected = vars_data.get('label', 'unknown')
                
                print(f"\n❌ Test {i+1}:")
                print(f"   Snippet: {snippet}...")
                print(f"   Expected: {expected}")
                
                # Get output
                output = r.get('response', {}).get('output', '')
                if output:
                    print(f"   Output: {output[:200]}...")
                
                # Get error
                error = r.get('response', {}).get('error', '')
                if error:
                    print(f"   Error: {error[:150]}")
                
                # Get assertion failures
                assertions = r.get('gradingResult', {}).get('componentResults', [])
                for assertion in assertions:
                    if not assertion.get('pass', False):
                        print(f"   ❌ Failed: {assertion.get('assertion', {}).get('type', 'unknown')}")
                        reason = assertion.get('reason', 'N/A')
                        # Truncate long reasons
                        if len(reason) > 200:
                            reason = reason[:200] + "..."
                        print(f"      Reason: {reason}")
                
                # Root cause analysis
                print(f"\n   🔍 ROOT CAUSE:")
                if '429' in str(error):
                    print("      → Rate limit exceeded. Wait or increase delay.")
                elif '503' in str(error) or 'overloaded' in str(error).lower():
                    print("      → Provider service is overloaded. The runner does not change models automatically.")
                elif 'JSON' in str(assertions) or 'json' in str(error).lower():
                    print("      → Model returned invalid JSON. Check raw output.")
                elif output and expected:
                    try:
                        obj = json.loads(output) if isinstance(output, str) else output
                        actual = obj.get('is_vuln', obj.get('is_vulnerable', 'unknown'))
                        print(f"      → Model said '{actual}' but expected '{expected}'")
                        print(f"      → Model rationale: {obj.get('rationale', 'N/A')[:100]}...")
                        print("      → This is a MODEL ACCURACY issue - prompt may need improvement")
                    except:
                        print("      → Could not parse output for analysis")
                else:
                    print("      → Unknown error - check raw output")
    
    if failure_count == 0:
        print("✅ No failures found! All tests passed.")
    else:
        print(f"\n{'='*70}")
        print(f"Total failures: {failure_count}")
        print(f"{'='*70}\n")


def print_raw_output(batch_num: int):
    """Print raw output from a specific batch for debugging."""
    print(f"\n{'='*70}")
    print(f"📋 RAW OUTPUT - BATCH {batch_num}")
    print(f"{'='*70}\n")
    
    data = load_batch_results(batch_num)
    if not data:
        print(f"❌ Could not find batch {batch_num} results")
        return
    
    results = data.get('results', {}).get('results', [])
    
    for i, r in enumerate(results):
        success = "✅" if r.get('success', False) else "❌"
        print(f"\n--- Test {i+1} {success} ---")
        
        # Print vars
        vars_data = r.get('vars', {})
        print(f"Expected: {vars_data.get('label', 'N/A')}")
        print(f"Snippet: {vars_data.get('code', vars_data.get('snippet', 'N/A'))[:100]}...")
        
        # Print raw output
        output = r.get('response', {}).get('output', 'N/A')
        print(f"\nRAW OUTPUT:\n{output}")
        
        # Print error if any
        error = r.get('response', {}).get('error', '')
        if error:
            print(f"\nERROR:\n{error}")
        
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Analyze promptfoo batch evaluation results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tools/analyze_results.py                    # Full analysis
  python tools/analyze_results.py --failures-only   # Show only failures
  python tools/analyze_results.py --raw 10          # Raw output for batch 10
  python tools/analyze_results.py --batch 5         # Analyze specific batch
        """
    )
    parser.add_argument("--batch", "-b", type=int, help="Analyze specific batch number")
    parser.add_argument("--failures-only", "-f", action="store_true", help="Show only failed tests with details")
    parser.add_argument("--raw", "-r", type=int, help="Show raw output for specific batch")
    
    args = parser.parse_args()
    
    # Change to project root if needed
    if os.path.exists("tools/analyze_results.py"):
        pass  # Already in project root
    elif os.path.exists("analyze_results.py"):
        os.chdir("..")  # In tools/, go up
    
    if args.raw:
        print_raw_output(args.raw)
    elif args.failures_only:
        print_failure_details()
    elif args.batch:
        print_raw_output(args.batch)
    else:
        print_comprehensive_analysis()
        print("\nFor more details:")
        print("  python tools/analyze_results.py --failures-only   # Detailed failure analysis")
        print("  python tools/analyze_results.py --raw <batch>     # Raw output inspection")


if __name__ == "__main__":
    main()
