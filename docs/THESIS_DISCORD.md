# Reading a Discord thesis

*Korean edition: [ko/THESIS_DISCORD.md](ko/THESIS_DISCORD.md)*

`/thesis ticker:<TICKER>` starts an exploratory local analysis. It does not place
orders or add a scored observation to the pilot ledger.

The thread contains a single progress board, updated in place, and a final result.
A completed stage means that the stage returned a validated output; it does not
prove that the evidence is accurate or that the model has an investment edge.
“근거 없음” means that the stage lacked evidence; “미확인” means that the bot did
not observe a terminal event. Neither is silently counted as complete.

The result separates execution health from the model rating. Buy / Overweight /
Hold / Underweight / Sell are model labels, not order instructions or portfolio
weights. Hold can mean neutral **or insufficient evidence**. REVIEW means that no
valid verdict was established. A successful execution with missing stages still
requires review. The result card is never green merely because a rating exists.

## Open the saved evidence

Copy the command from the final card and run it in the repository on the machine
that performed the analysis. The default remote interactive path executes on the
development machine, rather than the production pilot model host.

```bash
uv run python -m nuri.agents.discord.thesis_report --ticker DEMO --run aaaaaaaaaaaaaaaa --open
```

Replace the example ticker and run ID with the card's values. This reads the exact
saved JSON archive under the configured `archive_dir/runs` directory and writes a
private HTML sibling. It does not refresh prices, call a model, change the JSON
archive, or write to the ledger. Without `--open`, it prints the generated file
path. A missing archive or mismatched full hash fails with exit code 2.

The local view shows the saved rationale, supporting and opposing claims,
stage gaps, detailed reports, and recorded input cutoffs and observation times.
Missing information is displayed explicitly; the viewer does not reconstruct it
from newer data. The page uses escaped text and no external resources or scripts.

Raw reports can contain private context. They stay on the execution machine and
are not attached to Discord. Do not upload the HTML to public channels. The
Discord card deliberately carries only allowlisted status, rating and run ID.
