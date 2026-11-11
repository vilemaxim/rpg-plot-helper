# Mods and After-Action Reports are written in the user's own LLM

Mod Writers and Mod Runners do not fill in forms, and the web app's first version makes no LLM calls. Instead the system generates a prompt for each Mod, containing the Mod's text and its Features, which the person runs in whatever LLM they already use. That LLM interviews them and produces a file in the shared format, which they submit. The system checks the file and returns any errors as text they can paste back into their LLM.

We chose this because it works identically in both versions (see ADR-0001), costs nothing to host, needs no API keys or usage limits, and lets a tired Mod Runner answer questions instead of learning a format. The Flag check needs no LLM, since it works from each Mod's listed Features.

## Considered Options

- **A structured form.** Rejected because Mod Runners are often volunteers reporting from a phone in a field, and a form that captures seven kinds of Canon Change is too heavy for them.
- **A built-in interview chat from the start.** Deferred, not rejected: it is the intended next step for the web app once the model is proven.

## Consequences

- Submitted files come from LLMs the system does not control, so every submission is validated and nothing reaches Canon without the Plot Master's approval.
- The generated prompt contains the full Mod, including GM-only facts, so it is only given to people entitled to see that Mod.
