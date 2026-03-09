import os
import yaml
import fnmatch
from loguru import logger

def resolve_plan_scenarios(project_root, domain, scenario_patterns):
    """
    Given a list of scenario strings (e.g., 'core/stt_*', 'core/stt_polish_std'),
    resolves them into a dictionary of scenario definitions.
    
    'domain' should be 'backend' or 'client'.
    """
    resolved_scenarios = {}
    
    # 1. Pre-cache for file contents to avoid redundant reads
    file_cache = {}
    
    for pattern in scenario_patterns:
        if "/" not in pattern:
            logger.warning(f"Invalid scenario pattern '{pattern}': Missing source separator (e.g. 'core/scenario_id')")
            continue
            
        source_name, scen_pattern = pattern.split("/", 1)
        source_file = f"{source_name}.yaml"
        source_path = os.path.join(project_root, "tests", domain, "scenarios", source_file)
        
        if source_path not in file_cache:
            if os.path.exists(source_path):
                try:
                    with open(source_path, "r", encoding="utf-8") as f:
                        file_cache[source_path] = yaml.safe_load(f) or {}
                except Exception as e:
                    logger.error(f"Failed to load scenario source '{source_path}': {e}")
                    file_cache[source_path] = {}
            else:
                logger.warning(f"Scenario source '{source_name}' not found at {source_path}")
                file_cache[source_path] = {}
                
        source_data = file_cache[source_path]
        
        # 2. Match patterns
        matches_found = False
        for scen_id, scen_def in source_data.items():
            if fnmatch.fnmatch(scen_id, scen_pattern):
                # We use 'source/id' as the key to ensure uniqueness
                resolved_id = f"{source_name}/{scen_id}"
                resolved_scenarios[resolved_id] = scen_def
                matches_found = True
        
        if not matches_found:
            logger.warning(f"No scenarios matching '{scen_pattern}' found in '{source_name}'")
            
    return resolved_scenarios

# Legacy support - keeping the name for transitional period if needed
def load_scenarios_from_sources(project_root, domain, sources):
    """
    DEPRECATED: Use resolve_plan_scenarios instead.
    Standard utility to load and merge scenario definitions from a list of YAML sources.
    'domain' should be either 'backend' or 'client'.
    """
    scenarios = {}
    if not sources:
        return scenarios

    for source_file in sources:
        path = os.path.join(project_root, "tests", domain, "scenarios", source_file)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data:
                    scenarios.update(data)
        else:
            logger.warning(f"Scenario source '{source_file}' not found for domain '{domain}' at {path}")

    return scenarios
