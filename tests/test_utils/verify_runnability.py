import os
import sys

# Add project root to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(script_dir))
sys.path.insert(0, project_root)

from utils.engine import PipelineResolver
from utils import load_config

def main():
    resolver = PipelineResolver(project_root)
    cfg = load_config()
    
    print("\n🔍 TESTING RUNNABILITY ENGINE")
    print("="*40)
    
    # Test 1: Resolve with explicit strategy
    pipeline = "voice_to_voice"
    strategy = "fast_interaction"
    
    print(f"Target: {pipeline} + {strategy}")
    report = resolver.check_runnability(pipeline, strategy)
    
    print(f"Runnable: {'✅ YES' if report['runnable'] else '❌ NO'}")
    
    if not report['runnable']:
        print("\nMissing Dependencies:")
        for err in report['errors']:
            print(f"  - {err}")
            
    print("\nFulfillment Map:")
    print(f"{'Node ID':<20} | {'Status':<10} | {'Model/Role'}")
    print("-" * 60)
    for nid, info in report['map'].items():
        status = info.get('status', '???')
        model = info.get('model') or info.get('role', 'LOCAL')
        print(f"{nid:<20} | {status:<10} | {model}")
    print("="*40 + "\n")

if __name__ == "__main__":
    main()
