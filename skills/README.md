# Skills

Agent skills for working with this stack. Each subdirectory holds a `SKILL.md`
with YAML frontmatter (`name`, `description`) followed by the instructions.

| Skill | What it covers |
|-------|----------------|
| [`dashboard-author`](dashboard-author/SKILL.md) | Turning a request into a dashboard: a validated YAML spec in `dashboards/` (members from the Cube catalog, roles checked against the row-level security rules), a screenshot from generated data, the rollup lint, and a PR. `evals.md` has three requests to score it on. |
| [`oss-da-bi-stack`](oss-da-bi-stack/SKILL.md) | Operating the ELT/CDC stack: regenerating the AdventureWorks OLTP sandbox, applying init scripts, running the simulators and DAGs, querying the databases, and extending the pipelines. |

To make a skill available to an OpenCode agent, point its skill directory at this
folder or copy the skill into your OpenCode config's skills directory.
