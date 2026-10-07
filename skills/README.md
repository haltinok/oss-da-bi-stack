# Skills

Agent skills for working with this stack. Each subdirectory holds a `SKILL.md`
with YAML frontmatter (`name`, `description`) followed by the instructions.

| Skill | What it covers |
|-------|----------------|
| [`oss-da-bi-stack`](oss-da-bi-stack/SKILL.md) | Operating the ELT/CDC stack: regenerating the AdventureWorks OLTP sandbox, applying init scripts, running the simulators and DAGs, querying the databases, and extending the pipelines. |

To make a skill available to an OpenCode agent, point its skill directory at this
folder or copy the skill into your OpenCode config's skills directory.
