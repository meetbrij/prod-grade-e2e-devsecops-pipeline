# Documentation index

| Document | Read it when |
|---|---|
| [Main README](../README.md) | You want the project overview, architecture diagrams, pipelines and how to run it locally |
| [terraform/README.md](../terraform/README.md) | You are building the infrastructure, or need to know what each stack creates |
| [runbook.md](runbook.md) | You are releasing, promoting, rolling back, pausing, rotating a secret or destroying |
| [troubleshooting.md](troubleshooting.md) | Something failed and you have an error message |
| [security-gates.md](security-gates.md) | A scanner blocked a merge, or you want to turn the gates on or off |
| [decisions.md](decisions.md) | You want to know why something was built this way and what it costs |
| [eks-explained.md](eks-explained.md) | You want the Kubernetes and EKS concepts, and a picture of what runs where |
| [app/eval/README.md](../app/eval/README.md) | You want to run or read the accuracy evaluation |
| [CLAUDE.md](../CLAUDE.md) | You are an AI coding assistant working in this repository (rules, decisions, the app contract) |

**Not written yet:** a data-residency note (region choice and what changes for a UAE bank), which waits for the evaluation results, and an API reference with request and response examples. The endpoints are listed in the main README and the service serves interactive documentation at `/docs`.

Keep this index current when a document is added or removed.
