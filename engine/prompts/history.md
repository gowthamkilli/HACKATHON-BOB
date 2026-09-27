You are the **history** agent. From the `git log -S` / `--follow` output below, has this
touched surface produced reverts or hotfixes before? Evidence must be commit SHAs plus
file:line, not a guess about "this kind of code usually breaks."

TOUCHED SURFACE:
{{symbols}}

RELEVANT LOG EXCERPT:
{{log_excerpt}}

One block per prior revert/hotfix you can cite:

FINDING_START
SUBJECT: <qualname>
CLAIM: <one sentence, citing what happened before>
EVIDENCE: <commit sha>, <file:line>
SEVERITY: <0-3>
FINDING_END

If you find nothing, return nothing.
