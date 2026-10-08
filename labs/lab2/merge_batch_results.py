#!/usr/bin/env python3
"""
Merge multiple batch result files into a single promptfoo results file.

This allows you to view all batch results in one unified dashboard with:
    npx promptfoo view reports/merged_results.json

Usage:
    python merge_batch_results.py
    python merge_batch_results.py --batch-dir reports/batches --output reports/merged_results.json
"""

import argparse
import json
import os
import glob
from pathlib import Path


def load_batch_result(file_path):
    """Load a single batch result JSON file."""
    with open(file_path, 'r') as f:
        return json.load(f)


def merge_results(batch_files, output_file="reports/merged_results.json"):
    """Merge multiple batch result files into one."""
    
    if not batch_files:
        print("❌ No batch result files found!")
        return False
    
    print(f"📦 Found {len(batch_files)} batch result files")
    
    # Load the first batch as the base
    merged = load_batch_result(batch_files[0])
    print(f"✅ Loaded base: {batch_files[0]}")
    
    # Track cumulative stats
    total_successes = merged['results']['stats']['successes']
    total_failures = merged['results']['stats']['failures']
    total_errors = merged['results']['stats']['errors']
    
    # Keep track of the last batch for metadata
    last_batch_data = merged
    
    # Merge additional batches
    for batch_file in batch_files[1:]:
        print(f"➕ Merging: {batch_file}")
        batch_data = load_batch_result(batch_file)
        last_batch_data = batch_data
        
        # Append results
        merged['results']['results'].extend(batch_data['results']['results'])
        
        # Update stats
        total_successes += batch_data['results']['stats']['successes']
        total_failures += batch_data['results']['stats']['failures']
        total_errors += batch_data['results']['stats']['errors']
        
        # Merge token usage
        for key in ['prompt', 'completion', 'cached', 'total']:
            if key in batch_data['results']['stats']['tokenUsage']:
                merged['results']['stats']['tokenUsage'][key] = \
                    merged['results']['stats']['tokenUsage'].get(key, 0) + \
                    batch_data['results']['stats']['tokenUsage'][key]
    
    # Update final stats
    merged['results']['stats']['successes'] = total_successes
    merged['results']['stats']['failures'] = total_failures
    merged['results']['stats']['errors'] = total_errors
    
    # Update prompt metrics (aggregate across all results)
    prompt_metrics = {}
    for result in merged['results']['results']:
        prompt_id = result.get('promptId')
        if not prompt_id:
            continue
        
        if prompt_id not in prompt_metrics:
            prompt_metrics[prompt_id] = {
                'score': 0,
                'testPassCount': 0,
                'testFailCount': 0,
                'testErrorCount': 0,
                'assertPassCount': 0,
                'assertFailCount': 0,
                'totalLatencyMs': 0,
                'namedScores': {},
                'namedScoresCount': {}
            }
        
        metrics = prompt_metrics[prompt_id]
        metrics['score'] += result.get('score', 0)
        metrics['testPassCount'] += 1 if result.get('success') else 0
        metrics['testFailCount'] += 1 if not result.get('success') and not result.get('error') else 0
        metrics['testErrorCount'] += 1 if result.get('error') else 0
        metrics['totalLatencyMs'] += result.get('latencyMs', 0)
        
        # Aggregate named scores
        for score_name, score_value in result.get('namedScores', {}).items():
            metrics['namedScores'][score_name] = metrics['namedScores'].get(score_name, 0) + score_value
            metrics['namedScoresCount'][score_name] = metrics['namedScoresCount'].get(score_name, 0) + 1
    
    # Update prompts array with aggregated metrics
    for prompt in merged['results']['prompts']:
        prompt_id = prompt.get('id')
        if prompt_id in prompt_metrics:
            prompt['metrics'] = prompt_metrics[prompt_id]
    
    # Update metadata (use last batch's timestamp)
    merged['metadata']['exportedAt'] = last_batch_data['metadata']['exportedAt']
    merged['evalId'] = f"merged-{merged['evalId']}"
    
    # Save merged results
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(merged, f, indent=2)
    
    print(f"\n{'='*70}")
    print(f"📊 MERGE SUMMARY")
    print(f"{'='*70}")
    print(f"Total test results: {len(merged['results']['results'])}")
    print(f"✅ Successes: {total_successes}")
    print(f"❌ Failures: {total_failures}")
    print(f"💥 Errors: {total_errors}")
    print(f"\n📁 Merged results saved to: {output_file}")
    print(f"{'='*70}\n")
    
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Merge batch result files into a single promptfoo results file"
    )
    parser.add_argument(
        "--batch-dir",
        type=str,
        default="reports/batches",
        help="Directory containing batch result files (default: reports/batches)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="reports/merged_results.json",
        help="Output file path (default: reports/merged_results.json)"
    )
    parser.add_argument(
        "--pattern",
        type=str,
        default="batch_*_results.json",
        help="File pattern to match (default: batch_*_results.json)"
    )
    
    args = parser.parse_args()
    
    # Find all batch result files
    pattern = os.path.join(args.batch_dir, args.pattern)
    batch_files = sorted(glob.glob(pattern))
    
    if not batch_files:
        print(f"❌ No batch files found matching: {pattern}")
        print(f"   Make sure you've run the batch script first!")
        return 1
    
    # Merge results
    success = merge_results(batch_files, args.output)
    
    if success:
        print("✅ Success! Now run:")
        print(f"   npx promptfoo view {args.output}")
        print()
        return 0
    else:
        return 1


if __name__ == "__main__":
    exit(main())
