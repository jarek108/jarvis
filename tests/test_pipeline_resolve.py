import os
import sys
import json

# Add project root to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.append(project_root)

from utils.pipeline import PipelineResolver

def test_resolve():
    resolver = PipelineResolver(project_root)
    
    print("\n--- TEST 1: STRATEGY RESOLUTION ---")
    try:
        bound_graph = resolver.resolve("voice_to_voice", "high_quality")
        for nid, node in bound_graph.items():
            if 'binding' in node: print(f"Node: {nid:<10} -> {node['binding']['id']}")
    except Exception as e: print(f"❌ Failed: {e}")

    print("\n--- TEST 2: FRICTIONLESS AUTO-RESOLUTION ---")
    try:
        bound_graph = resolver.resolve("voice_to_voice")
        for nid, node in bound_graph.items():
            if 'binding' in node: print(f"Node: {nid:<10} -> {node['binding']['id']}")
    except Exception as e: print(f"❌ Failed: {e}")

if __name__ == "__main__":
    test_resolve()
