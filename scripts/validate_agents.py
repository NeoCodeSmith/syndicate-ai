#!/usr/bin/env python3
"""
Validate all agent YAML contracts against AgentDefinition schema.
Run in CI to catch broken contracts before deployment.
"""
import sys
from pathlib import Path
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from syndicate.core.models import AgentDefinition

errors = []
agents_dir = Path(__file__).parent.parent / "agents"

for yaml_file in sorted(agents_dir.rglob("*.yaml")):
    try:
        raw = yaml.safe_load(yaml_file.read_text())
        AgentDefinition.model_validate(raw)
        print(f"  ✓  {yaml_file.relative_to(agents_dir.parent)}")
    except Exception as e:
        errors.append((str(yaml_file), str(e)))
        print(f"  ✗  {yaml_file.relative_to(agents_dir.parent)}: {e}")

print(f"\n{'─'*60}")
print(f"  {len(list(agents_dir.rglob('*.yaml'))) - len(errors)} valid  |  {len(errors)} invalid")

if errors:
    sys.exit(1)
