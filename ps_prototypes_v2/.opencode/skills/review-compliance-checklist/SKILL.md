# Skill: review-compliance-checklist

The AGENTS.md compliance checklist. Evaluate every item and mark ✅ or ❌.
For every ❌, there must be a corresponding finding in the Findings section.

## Checklist

```markdown
## AGENTS.md Compliance Checklist

### Code Style
- [ ] `from __future__ import annotations` present in every module
- [ ] Import order: stdlib → third-party → local (blank line between each group)
- [ ] No wildcard imports (`import *`)
- [ ] Type hints on all public function signatures (parameters + return value)
- [ ] Built-in generics used for 3.8 compat (`list[x]` → `List[x]` from `typing`)
- [ ] No bare `print` statements — `logging` used throughout
- [ ] Naming: `snake_case` functions/variables, `PascalCase` classes, `UPPER_CASE` constants, `_single_underscore` private

### Documentation
- [ ] NumPy-style docstrings on all public functions, classes, and modules
- [ ] Docstrings cover: Parameters, Returns, Raises, and algorithmic notes where relevant
- [ ] Loss weight defaults are justified in docstrings or inline comments
- [ ] Comments explain *why*, not *what*

### Reproducibility
- [ ] `torch.manual_seed` and `numpy.random.seed` set and documented in configs
- [ ] Model checkpoints stored co-located with their config files

### Pipeline
- [ ] Online/incremental inference supported — 2D coords emitted per batch, no full-epoch wait
- [ ] No training loop that blocks output until epoch completion
- [ ] Each pipeline stage is independently benchmarkable

### Loss Functions
- [ ] Each loss component is an independent, importable module
- [ ] Every loss module exposes a `weight` parameter with a documented default
- [ ] All loss components are logged individually per step (not just the combined total)

### Scale
- [ ] No unbounded state accumulation over batches
- [ ] No O(n²) operations over the full dataset
```
