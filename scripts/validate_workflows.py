#!/usr/bin/env python3
"""
Validate all workflow YAML DAGs.
Checks: schema, step references, no undefined on_success/on_failure targets.
"""
import sys
from pathlib import Path
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from syndicate.core.models import WorkflowDefinition

errors = []
workflows_dir = Path(__file__).parent.parent / "workflows"

for yaml_file in sorted(workflows_dir.rglob("*.yaml")):
    try:
        raw = yaml.safe_load(yaml_file.read_text())
        WorkflowDefinition.model_validate(raw)
        print(f"  ✓  {yaml_file.relative_to(workflows_dir.parent)}")
    except Exception as e:
        errors.append((str(yaml_file), str(e)))
        print(f"  ✗  {yaml_file.relative_to(workflows_dir.parent)}: {e}")

print(f"\n{'─'*60}")
print(f"  {len(list(workflows_dir.rglob('*.yaml'))) - len(errors)} valid  |  {len(errors)} invalid")

if errors:
    sys.exit(1)
