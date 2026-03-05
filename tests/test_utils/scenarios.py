import os
import yaml
from loguru import logger

def load_scenarios_from_sources(project_root, domain, sources):
    """
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
