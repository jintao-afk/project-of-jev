# Jev project instructions

- Keep project code, models, environments, caches, logs, reports and backups on D:. Do not download existing models again or copy the project to C:.
- Current operation is entirely offline. The local decision implementation is independent AnyJev + Qwen, not commercial Jev weights or evidence of commercial Jev performance.
- Preserve historical evaluations, annotations, release manifests and backups. Keep routing, execution, partial validation and independently reviewed quality separate. Do not tune a frozen version on its holdout or overwrite the freeze.
- After completing a verifiable stage, report changes, checks and remaining failures, and prepare a Git handoff. The user will personally commit and push using their own Git account. Do not run git add, commit, tag, push, or account/remote configuration unless the user explicitly changes this instruction. The user prefers Git commits over duplicate full local project backups; create a full backup only when explicitly requested.
- Git stores source, configuration, tests, documents and lightweight manifests. Exclude model weights, virtual environments, caches, logs, old repair backups, credentials and generated ZIP archives. Preserve exact file bytes without Git EOL conversion.
- For Git handoff, prepare ignore rules, explain the intended file scope and provide a suggested commit message plus verification commands. Preserve existing repair backups and historical records. Do not add global Git trust exceptions merely to bypass sandbox ownership checks.
- A project .venv may depend on D:\Anaconda. Record external runtime dependencies and distinguish a project backup from a self-contained machine/environment image.
