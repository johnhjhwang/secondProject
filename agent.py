import os
import base64
import subprocess
import sys
import tempfile
from pathlib import Path
from dotenv import load_dotenv
import anthropic

load_dotenv()

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

from skills.fetch_context import load_all_context

SKILL_DIR = Path(__file__).parent / "azure-diagrams" / "azure-diagrams"
REFERENCES_DIR = SKILL_DIR / "references"

SYSTEM_PROMPT = """You are a senior Microsoft Azure Solution Architect with 15+ years of experience
designing and reviewing enterprise-grade cloud architectures. You have deep expertise in:

- Azure services (compute, networking, storage, security, data, AI/ML, integration)
- Well-Architected Framework (reliability, security, cost optimization, operational excellence, performance efficiency)
- Azure landing zones, hub-spoke topologies, and reference architectures
- Microservices, event-driven, and serverless patterns on Azure
- Azure networking (VNet, NSG, Azure Firewall, Application Gateway, Front Door)
- Identity and access management (Azure AD, RBAC, Managed Identities)
- DevOps and CI/CD pipelines on Azure

You also have the azure-diagrams skill which lets you generate professional Azure architecture diagrams
using the Python `diagrams` library with 700+ official Microsoft icons.

When analyzing an architecture diagram, you will:
1. Identify all Azure services and components present
2. Evaluate the architecture against the Azure Well-Architected Framework pillars
3. Analyze service interconnections and data flow
4. Provide a detailed score (0-100) broken down by each pillar
5. Highlight strengths, risks, and concrete improvement recommendations

When generating a diagram:
- Use `diagrams.azure.*` components with official Azure icons
- Apply professional standards: labelloc='t', Arial Bold fonts, dpi=200
- Save output as PNG to the outputs/ folder"""


def _load_skill_reference(filename: str) -> str:
    ref_path = REFERENCES_DIR / filename
    if ref_path.exists():
        return ref_path.read_text()
    return ""


def _build_component_index() -> dict[str, str]:
    """Build a map of ClassName -> module path for all installed Azure diagram components."""
    import importlib, pkgutil
    import diagrams.azure as az
    index = {}
    for mod in pkgutil.iter_modules(az.__path__):
        m = importlib.import_module(f"diagrams.azure.{mod.name}")
        for cls in dir(m):
            if not cls.startswith("_") and isinstance(getattr(m, cls), type):
                # First occurrence wins; prefer more specific modules
                if cls not in index:
                    index[cls] = f"diagrams.azure.{mod.name}"
    return index


# Build once at import time
_COMPONENT_INDEX = _build_component_index()


def _available_azure_components() -> str:
    """Return exact module.ClassName pairs for the prompt."""
    lines = ["Use ONLY these exact imports from the installed diagrams library:\n"]
    by_module: dict[str, list[str]] = {}
    for cls, mod in sorted(_COMPONENT_INDEX.items()):
        by_module.setdefault(mod, []).append(cls)
    for mod, classes in sorted(by_module.items()):
        lines.append(f"  from {mod} import {', '.join(sorted(classes))}")
    return "\n".join(lines)


def _fix_imports(code: str) -> str:
    """
    1. Collapse multi-line / parenthesized azure imports into single lines.
    2. Hoist ALL diagrams.azure imports to the top (fixes indented imports
       inside `with` blocks that would leave an empty body).
    3. Rewrite each import to its correct module using _COMPONENT_INDEX.
    """
    import re

    # Collapse parenthesized multi-line imports
    code = re.sub(
        r"(from\s+diagrams\.azure\.\w+\s+import\s*)\(\s*([\s\S]*?)\)",
        lambda m: m.group(1) + " ".join(m.group(2).split()),
        code,
    )
    # Collapse backslash continuations
    code = re.sub(r"\\\n\s*", " ", code)

    collected_names: list[str] = []  # all class names seen in azure imports
    body_lines: list[str] = []       # non-azure-import lines

    for line in code.splitlines():
        m = re.match(r"^\s*from\s+diagrams\.azure\.\w+\s+import\s+(.+)$", line)
        if m:
            raw_names = re.split(r"[,\s]+", m.group(1))
            collected_names.extend(n.strip() for n in raw_names if n.strip())
        else:
            # Replace azure import lines inside with-blocks with `pass`
            # only when the line is the sole body of a with/for/if block
            body_lines.append(line)

    # Inject `pass` into any empty compound blocks left behind
    fixed_body: list[str] = []
    for i, line in enumerate(body_lines):
        fixed_body.append(line)
        stripped = line.rstrip()
        if stripped.endswith(":"):
            # peek at next non-empty line
            next_lines = [body_lines[j] for j in range(i + 1, len(body_lines)) if body_lines[j].strip()]
            if not next_lines:
                fixed_body.append(" " * (len(line) - len(line.lstrip()) + 4) + "pass")
            else:
                next_indent = len(next_lines[0]) - len(next_lines[0].lstrip())
                cur_indent = len(line) - len(line.lstrip())
                if next_indent <= cur_indent:
                    fixed_body.append(" " * (cur_indent + 4) + "pass")

    # Build corrected top-level imports (deduplicated, correct modules)
    by_module: dict[str, list[str]] = {}
    seen: set[str] = set()
    for name in collected_names:
        if name in seen:
            continue
        seen.add(name)
        mod = _COMPONENT_INDEX.get(name)
        if mod:
            by_module.setdefault(mod, []).append(name)

    import_lines = [f"from {mod} import {', '.join(names)}" for mod, names in sorted(by_module.items())]

    # Find where existing top-level non-azure imports end and insert after them
    insert_at = 0
    for i, line in enumerate(fixed_body):
        s = line.strip()
        if s.startswith("import ") or s.startswith("from "):
            insert_at = i + 1

    final = fixed_body[:insert_at] + import_lines + fixed_body[insert_at:]
    return "\n".join(final)


def analyze_architecture(image_path: str, question: str = None) -> str:
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    media_type_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    media_type = media_type_map.get(path.suffix.lower(), "image/png")

    with open(image_path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")

    prompt = question or (
        "Analyze this Azure architecture diagram. Identify all services and their relationships, "
        "then score the overall architecture across the Azure Well-Architected Framework pillars. "
        "Provide a total score out of 100 with a breakdown per pillar, key strengths, risks, "
        "and prioritized recommendations for improvement."
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": image_data},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )
    return response.content[0].text


def analyze_and_improve(image_path: str, output_name: str = "improved_architecture") -> tuple[str, Path]:
    """Analyze an uploaded diagram, then generate an improved version with proper Azure icons."""
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    media_type_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    media_type = media_type_map.get(path.suffix.lower(), "image/png")

    with open(image_path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")

    available = _available_azure_components()
    patterns_ref = _load_skill_reference("common-patterns.md")
    firm_context = load_all_context()

    output_dir = Path(__file__).parent / "outputs"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / output_name

    prompt = f"""Analyze this Azure architecture diagram and do two things:

PART 1 - ANALYSIS REPORT:
Identify all Azure services and their relationships, then score the overall architecture across the Azure Well-Architected Framework pillars.
Provide:
- Total score out of 100
- Per-pillar breakdown (Reliability, Security, Cost Optimization, Operational Excellence, Performance Efficiency)
- Key strengths
- Risks and gaps
- Prioritized improvement recommendations

PART 2 - IMPROVED DIAGRAM CODE:
Based on your analysis, generate Python `diagrams` library code that represents the IMPROVED architecture incorporating your recommendations.

Rules for the diagram code:
- Use ONLY the exact class names listed below — do NOT invent or guess any names
- Save to: filename="{output_path}", show=False
- Apply professional standards: labelloc='t', fontname='Arial Bold', dpi='200', nodesep='1.0', ranksep='1.0'
- Group services logically using Cluster (e.g. Frontend, Backend, Data, Security, Networking)
- Include ALL recommended services from your analysis
- Return ONLY the Python code block for Part 2, clearly marked with ```python ... ```
{f"- Follow firm-specific guidelines and compliance rules from the context below" if firm_context else ""}

{available}

Reference - Common Patterns:
{patterns_ref[:2000]}
{firm_context}
"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": image_data},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )

    raw = response.content[0].text

    # Split analysis from code
    if "```python" in raw:
        parts = raw.split("```python")
        analysis = parts[0].strip()
        code = parts[1].split("```")[0].strip()
    else:
        analysis = raw
        code = None

    improved_path = None
    if code:
        code = _fix_imports(code)
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(code)
            tmp_path = f.name
        try:
            result = subprocess.run(
                [sys.executable, tmp_path],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode != 0:
                raise RuntimeError(f"Diagram generation failed:\n{result.stderr}")
            improved_path = Path(str(output_path) + ".png")
        finally:
            os.unlink(tmp_path)

    return analysis, improved_path


def generate_diagram(description: str, output_name: str = "architecture") -> Path:
    """Ask the agent to generate diagram code, then execute it."""
    available = _available_azure_components()
    patterns_ref = _load_skill_reference("common-patterns.md")

    output_dir = Path(__file__).parent / "outputs"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / output_name

    firm_context = load_all_context()

    prompt = f"""Generate Python code using the `diagrams` library to create an Azure architecture diagram for:

{description}

Rules:
- Use ONLY the exact class names listed below — do NOT invent or guess any names
- Save to: filename="{output_path}", show=False
- Apply professional standards: labelloc='t', fontname='Arial Bold', dpi='200', nodesep='1.0', ranksep='1.0'
- Group services using Cluster (Frontend, Backend, Data, Security, Networking)
- Return ONLY the Python code block, no explanation
{f"- Follow firm-specific guidelines and compliance rules from the context below" if firm_context else ""}

{available}

Reference - Common Patterns:
{patterns_ref[:2000]}
{firm_context}
"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text
    # Extract code block
    if "```python" in raw:
        code = raw.split("```python")[1].split("```")[0].strip()
    elif "```" in raw:
        code = raw.split("```")[1].split("```")[0].strip()
    else:
        code = raw.strip()

    code = _fix_imports(code)

    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(code)
        tmp_path = f.name

    try:
        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            raise RuntimeError(f"Diagram generation failed:\n{result.stderr}")
    finally:
        os.unlink(tmp_path)

    generated = Path(str(output_path) + ".png")
    print(f"Diagram saved to: {generated}")
    return generated


def run_agent(user_message: str) -> str:
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


if __name__ == "__main__":
    args = sys.argv[1:]

    if not args:
        reply = run_agent("What Azure architecture best practices should I follow for a highly available web application?")
        print(reply)

    elif args[0] == "analyze" and len(args) >= 2:
        question = args[2] if len(args) > 2 else None
        print(analyze_architecture(args[1], question))

    elif args[0] == "generate":
        description = " ".join(args[1:]) or "A 3-tier web application with App Service, SQL Database, and Redis Cache"
        generate_diagram(description)

    else:
        # Treat first arg as image path for backwards compatibility
        question = args[1] if len(args) > 1 else None
        print(analyze_architecture(args[0], question))
