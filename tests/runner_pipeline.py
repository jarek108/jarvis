import os
import sys
import yaml
import time
import argparse
from loguru import logger

# Add project root to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.append(project_root)

from utils.pipeline import PipelineResolver, PipelineExecutor
from utils.console import GREEN, RED, YELLOW, CYAN, RESET, BOLD, LINE_LEN

class PipelineTestRunner:
    def __init__(self, plan_path):
        with open(plan_path, "r") as f:
            self.plan = yaml.safe_load(f)
        self.project_root = project_root
        self.resolver = PipelineResolver(project_root)
        self.executor = PipelineExecutor(project_root)

    def run_scenario(self, scenario):
        sid = scenario['id']
        pid = scenario['pipeline']
        mid = scenario.get('mapping')
        loadout = scenario.get('loadout')
        
        print("\n" + "="*LINE_LEN)
        print(f"{BOLD}{CYAN}SCENARIO: {sid}{RESET}")
        print(f"Pipeline: {pid} | Mapping: {mid or 'AUTO'} | Loadout: {loadout}")
        print("="*LINE_LEN)

        if loadout:
            logger.info(f"Applying loadout: {loadout}")
            from manage_loadout import apply_loadout
            apply_loadout(loadout, soft=False)

        try:
            bound_graph = self.resolver.resolve(pid, mid)
        except Exception as e:
            print(f"{RED}❌ Resolution Failed: {e}{RESET}")
            return False

        print(f"\n{BOLD}Running Graph...{RESET}")
        success = self.executor.run(bound_graph, scenario.get('inputs', {}))
        
        if success:
            print(f"\n{GREEN}✅ SCENARIO SUCCESS{RESET}")
            for nid, timing in self.executor.timings.items():
                print(f"  - {nid:<15}: {timing['duration']:.3f}s")
        else:
            print(f"\n{RED}❌ SCENARIO FAILED{RESET}")
        
        return success

    def run_all(self):
        total = len(self.plan['scenarios'])
        passed = 0
        for s in self.plan['scenarios']:
            if self.run_scenario(s): passed += 1
        
        print("\n" + "="*LINE_LEN)
        print(f"PIPELINE TEST COMPLETE: {passed}/{total} Passed")
        print("="*LINE_LEN)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", type=str)
    args = parser.parse_args()
    
    runner = PipelineTestRunner(args.plan)
    runner.run_all()
