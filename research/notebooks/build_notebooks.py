"""Generate the research notebooks from one source so setup cells cannot drift apart.

Usage (from apps/api):  uv run python ../../research/notebooks/build_notebooks.py [--execute]
--execute runs each notebook against real models and saves the outputs.
"""

import sys
import textwrap
from pathlib import Path

import nbformat
from nbclient import NotebookClient
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

HERE = Path(__file__).parent

SETUP = r'''
# Setup: works locally and on Google Colab. Never put secrets in notebook cells.
import json, os, subprocess, sys
from pathlib import Path

IN_COLAB = "google.colab" in sys.modules
if IN_COLAB:
    REPO_URL = ""  # Set to your clone URL. On Colab, add HF_TOKEN under Secrets to use hosted models.
    if not Path("salesiq").exists():
        if not REPO_URL:
            raise RuntimeError("Set REPO_URL in this cell to clone the SalesIQ repository.")
        subprocess.run(["git", "clone", "--depth=1", REPO_URL, "salesiq"], check=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "httpx", "pyyaml", "pydantic", "mcp"], check=True)
    ROOT = Path("salesiq").resolve()
    from google.colab import userdata
    try:
        os.environ["HF_TOKEN"] = userdata.get("HF_TOKEN")
    except userdata.SecretNotFoundError:
        print("No HF_TOKEN secret; only a local model server can be used.")
else:
    ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "research").is_dir())
sys.path.insert(0, str(ROOT / "apps" / "api"))
os.environ["SALESIQ_RESEARCH_DIR"] = str(ROOT / "research")

from app.agents.llm import LLMError, ModelRegistry

registry = ModelRegistry()
status = {s.key: s for s in registry.status()}
CANDIDATES = ["qwen3-4b", "qwen2.5-7b", "mistral-7b", "hf-qwen3-8b"]
MODEL = next((k for k in CANDIDATES if status[k].available), None)
if MODEL is None:
    # There is deliberately no mock: results must come from a real model.
    raise RuntimeError("No model is reachable. Start Ollama and pull a model, or set HF_TOKEN.\n"
                       + "\n".join(f"{s.key}: {s.reason}" for s in status.values() if not s.available))
print(f"Using real model: {MODEL} ({registry.model(MODEL).model})")
'''

NOTEBOOKS: dict[str, list[tuple[str, str]]] = {
    "01_environment_and_models": [
        ("md", """# 01 · Environment and models
**Objective:** confirm which real models can run here and measure a first call.

**Runs on:** a local Ollama server (GPU optional, slower on CPU) or the Hugging Face router with `HF_TOKEN`
(which may bill the token owner). All data is fictional."""),
        ("code", SETUP),
        ("md", "## Environment check\nModel availability comes from asking each provider, not from assumptions."),
        ("code", """
import shutil
for s in status.values():
    print(f"{s.key:14} {'available' if s.available else 'unavailable: ' + str(s.reason)}")
print()
if shutil.which("nvidia-smi"):
    print(subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader"],
                         capture_output=True, text=True).stdout.strip())
else:
    print("No NVIDIA GPU detected; expect CPU speeds.")
"""),
        ("md", "## A real call, with validated output\nThe first call also loads the model, so it is slower than later ones."),
        ("code", """
from pydantic import BaseModel

class Fact(BaseModel):
    city: str
    employees: int | None

msg = [{"role": "user", "content": "Fictional note: Halden Labs has a team of 140 in Leeds. Extract the facts."}]
for attempt in ("cold or warm", "warm"):
    parsed, result = registry.structured(MODEL, msg, Fact, max_tokens=80)
    print(attempt, parsed, f"{result.latency_ms:.0f} ms", result.usage)
assert parsed.city.lower() == "leeds" and parsed.employees == 140, "Unexpected extraction"
"""),
        ("md", "## Failures are explicit\nA missing model raises a clear error. Nothing is silently substituted."),
        ("code", """
import tempfile, yaml
cfg = {"providers": {"ollama": {"base_url": registry.providers["ollama"].base_url}},
       "models": {"gone": {"provider": "ollama", "model": "no-such-model:latest", "capabilities": ["chat"]}}}
path = Path(tempfile.mkdtemp()) / "models.yaml"
path.write_text(yaml.safe_dump(cfg))
try:
    ModelRegistry(path).chat("gone", [{"role": "user", "content": "hi"}])
except LLMError as exc:
    print(f"{exc.category}: {exc}")
"""),
        ("md", """**Expected:** a list of models with reasons for any that are unavailable, two validated extractions (the second
faster), and a `model_not_found` error.

**Limitations and next steps:** latency depends on hardware and on which model is already loaded. Next: notebook 02."""),
    ],
    "02_lead_intelligence": [
        ("md", """# 02 · Lead intelligence
**Objective:** compare the rule baseline with a real model at ICP classification on the *train* split.
Held-out numbers belong in notebook 06; this notebook is for exploring, so tuning here does not contaminate them.

Data is fictional. Labels come from a known rule, not real sales outcomes."""),
        ("code", SETUP),
        ("code", """
from app.agents.evaluation import baseline, metrics, tasks
from app.agents.evaluation.runner import Dataset

data = Dataset.load("train")
icp = data.manifest["icp"]
sample = data.prospects[:8]  # Increase for a fuller picture; each item is a real model call.
print(sample[0]["structured"]); print(sample[0]["note"]); print("gold:", sample[0]["gold"]["icp_fit"])
"""),
        ("code", """
gold, rule_pred, model_pred, reasons = [], [], [], []
for r in sample:
    gold.append(r["gold"]["icp_fit"])
    rule_pred.append(baseline.classify(r, icp).fit)
    try:
        out, _ = registry.structured(MODEL, tasks.classification_messages(r, icp), tasks.ClassificationOut, max_tokens=400)
        model_pred.append(out.fit); reasons.append(out.reasons)
    except LLMError as exc:  # A failed call counts as wrong; it is not hidden.
        model_pred.append(None); reasons.append([f"{exc.category}: {exc}"])

for name, pred in (("rules", rule_pred), (MODEL, model_pred)):
    report = metrics.classification_report(gold, pred)
    low, high = report["accuracy_ci95"]
    print(f"{name:12} accuracy {report['accuracy']:.0%} (95% CI {low:.0%}-{high:.0%}, n={report['n']})")
"""),
        ("md", "## Why the model decided\nReasons are shown so a person can check them against the note."),
        ("code", """
for r, p, why in zip(sample, model_pred, reasons):
    print(f"{r['id']}  gold={r['gold']['icp_fit']:6} model={p}  {why[:2]}")
assert len(model_pred) == len(sample)
"""),
        ("md", """**Expected:** rules score very well here because their keywords were written from this split. Compare on held-out
data in notebook 06 before concluding anything.

**Limitations:** eight items give a very wide interval. A label is an assessment of fit, never a conversion probability."""),
    ],
    "03_structured_extraction": [
        ("md", """# 03 · Structured extraction
**Objective:** extract company facts into a typed schema, and measure whether the model *invents* facts that the text
does not state. Notes contain a distractor company to tempt it. Data is fictional."""),
        ("code", SETUP),
        ("code", """
from app.agents.evaluation import baseline, metrics, tasks
from app.agents.evaluation.runner import Dataset

records = Dataset.load("train").prospects[:8]
gold = [r["gold"]["facts"] for r in records]
pred = []
for r in records:
    try:
        out, _ = registry.structured(MODEL, tasks.extraction_messages(r), tasks.ExtractionOut, max_tokens=200)
        pred.append(out.model_dump())
    except LLMError as exc:
        print(r["id"], exc.category)
        pred.append(None)
for name, p in (("regex", [baseline.extract(r).model_dump() for r in records]), (MODEL, pred)):
    rep = metrics.extraction_report(gold, p)
    print(f"{name:12} field accuracy {rep['field_accuracy']:.0%}, invented {rep['invented_fact_rate']:.0%} of {rep['absent_facts']} absent facts")
    print("   ", {k: f"{v:.0%}" for k, v in rep["per_field"].items()})
"""),
        ("md", "## Output validation\nPydantic rejects malformed output, and a schema error is reported rather than repaired by guessing."),
        ("code", """
from pydantic import ValidationError
try:
    tasks.ExtractionOut.model_validate_json('{"company_name": "X", "employee_count": "many"}')
except ValidationError as exc:
    print("Rejected:", exc.error_count(), "problems")
print(pred[0]); print("gold:", gold[0])
"""),
        ("md", """**Expected:** high accuracy on this split, with an invented-fact rate reported separately because a confident wrong
value is worse than a null.

**Limitations:** templated fictional notes are far cleaner than real web pages. Real-document evaluation comes with Phase 5."""),
    ],
    "04_agent_workflows": [
        ("md", """# 04 · Agent workflows (prototype)
**Objective:** chain extraction, qualification, and research synthesis with deterministic quality gates, as a small
prototype of what Phase 6 builds in LangGraph with persistence. Includes a lead whose evidence carries a planted injection.

Fictional data. **This notebook is not the production workflow**: no checkpoints, retries across restarts, or approvals."""),
        ("code", SETUP),
        ("code", """
from app.agents.evaluation import metrics, tasks
from app.agents.evaluation.runner import Dataset

data = Dataset.load("train")
canary = data.manifest["canary"]
item = next(i for i in data.grounding if i["has_injection"])
for e in item["evidence"]:
    print(e["id"], e["source"], "-", e["text"][:90])
"""),
        ("code", """
def quality_gate(brief, evidence):
    # Deterministic checks. A model never gets to approve its own output.
    check = metrics.grounding_check([(c.text, c.evidence_ids) for c in brief.claims], evidence,
                                    full_text=" ".join([brief.summary, *[c.text for c in brief.claims]]), canary=canary)
    problems = []
    if check["invalid_citations"]: problems.append("cites unknown evidence")
    if check["uncited_claims"]: problems.append("has uncited claims")
    if check["cited_injection"]: problems.append("relied on an injected source")
    if check["injection_followed"]: problems.append("followed an injected instruction")
    if check["unsupported_numbers"]: problems.append(f"invented numbers {check['unsupported_numbers']}")
    return check, problems

trace = []
try:
    brief, res = registry.structured(MODEL, tasks.synthesis_messages(item), tasks.SynthesisOut, max_tokens=700)
    trace.append(("synthesis", res.model_key, f"{res.latency_ms:.0f} ms", "ok"))
    check, problems = quality_gate(brief, item["evidence"])
    verdict = "escalate to human" if problems else "accept"
    trace.append(("quality_gate", "deterministic", "-", verdict))
except LLMError as exc:
    brief, problems, verdict = None, [exc.category], "failed: visible to the user"
    trace.append(("synthesis", MODEL, "-", exc.category))
for step in trace: print(step)
print("Problems:", problems or "none"); print("Verdict:", verdict)
if brief:
    for c in brief.claims: print(" -", c.text, c.evidence_ids)
"""),
        ("md", """**Expected:** a short trace and a verdict. If the model cited the injected source, the gate escalates instead of accepting.
That outcome is the point: the safety property comes from the deterministic check, not from trusting the model.

**Limitations:** the gate's lexical checks can miss a false claim built from source words. Next: LangGraph workflows (Phase 6)."""),
    ],
    "05_mcp_integration": [
        ("md", """# 05 · MCP integration (prototype)
**Objective:** exercise the official MCP Python SDK with a real model choosing a tool call: tool discovery, typed
input, a permission check inside the tool, and tenant scoping. Phase 7 builds the production server on real services.

The tool reads the fictional dataset; it is an in-memory demo server, not a deployed one."""),
        ("code", SETUP),
        ("code", """
import logging
from mcp import Client
from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel
from app.agents.evaluation.runner import Dataset

logging.disable(logging.ERROR)  # The denial below is expected; its server traceback is only noise.
leads = Dataset.load("train").prospects
# Tenant and role are set by trusted server code, never by the model or the tool arguments.
SESSION = {"org": "org-a", "role": "analyst"}
TENANT_OF = {r["id"]: ("org-a" if i % 2 == 0 else "org-b") for i, r in enumerate(leads)}

server = MCPServer("salesiq-demo")

@server.tool()
def search_leads(query: str, limit: int = 3) -> list[dict]:
    "Read-only search over leads the caller may see."
    q = query.lower()
    hits = [r for r in leads if TENANT_OF[r["id"]] == SESSION["org"] and (q in r["note"].lower() or q in r["structured"]["industry"].lower())]
    return [{"id": r["id"], "company": r["structured"]["company"], "industry": r["structured"]["industry"]} for r in hits[:min(limit, 10)]]

@server.tool()
def delete_lead(lead_id: str) -> str:
    "Destructive. Requires the delete permission, checked here rather than by the model."
    if SESSION["role"] not in ("owner", "admin", "manager"):
        raise PermissionError("role may not delete leads")
    return "deleted"
"""),
        ("code", """
class ToolChoice(BaseModel):
    tool: str
    query: str

async with Client(server) as client:
    tools = (await client.list_tools()).tools
    print("Discovered:", [t.name for t in tools])
    catalog = [{"name": t.name, "description": t.description} for t in tools]
    prompt = f"Tools: {json.dumps(catalog)}\\nRequest: find fintech leads. Choose the tool and a one-word query."
    choice, res = registry.structured(MODEL, [{"role": "user", "content": prompt}], ToolChoice, max_tokens=60)
    print("Model chose:", choice, f"({res.latency_ms:.0f} ms)")
    allowed = {t.name for t in tools}
    assert choice.tool in allowed, "Tool names are validated against the catalog"
    result = await client.call_tool("search_leads", {"query": choice.query})
    print("Result:", result.content[0].text if result.content else "no matches")

    # Authorization is enforced inside the tool, whatever the model asks for.
    denied = await client.call_tool("delete_lead", {"lead_id": "train-001"})
    print("Delete as analyst -> is_error:", denied.is_error, "|", denied.content[0].text)
    assert denied.is_error
"""),
        ("md", """**Expected:** two discovered tools, a model-chosen search, and a refused delete because the session role is `analyst`.

**Limitations:** no transport authentication, audit log, or real services yet; those come with Phase 7. Model output is only
ever treated as a *request* that server code validates."""),
    ],
    "06_model_evaluation": [
        ("md", """# 06 · Model evaluation
**Objective:** read the held-out results, compare methods, and state what the evidence does and does not support.
Results come from `python -m app.agents.evaluation` runs stored in `research/evaluations/`; this notebook does not re-run them."""),
        ("code", SETUP.split("from app.agents.llm import")[0] + "print('Reading stored results; no model is called here.')\n"),
        ("code", """
from IPython.display import Markdown, display
from app.agents.evaluation.report import load_summaries, merge, render

runs = load_summaries(split="test")
assert runs, "No held-out runs found. Run: python -m app.agents.evaluation --models baseline,qwen2.5-7b --split test"
merged = merge(runs)
display(Markdown(render(merged, runs)))
"""),
        ("md", "## Is any difference real?\nCompare intervals before believing a gap. Non-overlap here is a rough screen, not a formal test."),
        ("code", """
acc = {m: e["quality"] for m, e in merged["classification"].items()}
best = max(acc, key=lambda m: acc[m]["accuracy"])
base = acc["baseline"]
for m, q in sorted(acc.items(), key=lambda kv: -kv[1]["accuracy"]):
    lo, hi = q["accuracy_ci95"]
    clear = lo > base["accuracy_ci95"][1]
    note = "baseline" if m == "baseline" else ("clearly above baseline" if clear else "not clearly above baseline")
    print(f"{m:14} {q['accuracy']:.0%}  CI {lo:.0%}-{hi:.0%}  {note}")
"""),
        ("md", """**Limitations:** fictional data, rule-derived labels, one prompt version, small samples, no human ratings. Fine-tuning is not
justified by this evidence; the next improvements are retrieval, stronger validation, and real-document evaluation."""),
    ],
}


def build(execute: bool) -> None:
    for name, cells in NOTEBOOKS.items():
        nb = new_notebook(
            cells=[
                new_markdown_cell(textwrap.dedent(body).strip()) if kind == "md"
                else new_code_cell(textwrap.dedent(body).strip())
                for kind, body in cells
            ],
            metadata={"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"}},
        )
        path = HERE / f"{name}.ipynb"
        if execute:
            print(f"Executing {name}...", flush=True)
            NotebookClient(nb, timeout=900, kernel_name="python3",
                           resources={"metadata": {"path": str(HERE)}}).execute()
        nbformat.write(nb, path)
        print(f"Wrote {path.name}")


if __name__ == "__main__":
    build("--execute" in sys.argv)
