You are extracting documented guarantees from a codebase's own written record — ADRs,
docstrings, inline comments, and test names. You are given only the harvested snippets below,
never whole files.

Normalize each candidate guarantee into the exact block format below. Do not invent a
guarantee that isn't backed by one of the snippets. Do not paraphrase the statement so much
that it stops matching what the snippet actually says.

HARVESTED SNIPPETS:
{{harvest_text}}

For each distinct guarantee, return:

GUARANTEE_START
ID: <as given in the snippet, e.g. G3>
STATEMENT: <one sentence, the claim itself>
WHY: <one sentence, the reason it exists, from the snippet if present>
GUARANTEE_END

Return only GUARANTEE_START/GUARANTEE_END blocks, nothing else.
