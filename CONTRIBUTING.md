# Contributing

Start with [development setup](docs/development.md), the
[architecture](docs/architecture.md), and [profile provenance](docs/profiles.md).
Discuss changes to physical models or evidence contracts in an issue before a
large implementation. Small fixes can go directly to a pull request.

1. Describe the problem, units, expected behavior, and affected default or opt-in path.
2. Keep the change focused. Use `tv_sim` imports and place Python source under
   `src/tv_sim/`; keep research and decisions under `docs/`.
3. Preserve existing default output, temporal histories, profile/data bytes, and
   artifact schemas unless the change explicitly calls for a model revision.
   Never refresh golden fixtures just to make a failing test pass. Explain every
   intentional numerical change and obtain PM review.
4. Add meaningful checks for changed behavior. Label long running tests `slow`.
   Keep measured (`M`), derived (`D`), placeholder (`P`), and unavailable (`NR`)
   evidence distinct; unknown does not mean zero.
5. Run `make lint typecheck test docs-check`. Use `make format` before review and
   `pre-commit run --all-files` when hooks are installed. Verify affected CLI or
   browser workflows and include the exact results in the pull request.
6. Update relevant usage, research, provenance records, and `CHANGELOG.md`.
   Keep large generated arrays out of version control and document regeneration.

Public functions should have type hints and a docstring that states the units,
shapes, state effects, and important constraints. Prefer small domain helpers to
parallel implementations of transfer functions, load limits, or timing rules.

The project uses a [PM review workflow](docs/decisions/0005-pm-workflow.md).
Implementation evidence and a reviewable working tree are the handoff; the PM
chooses the final commit split and integration. Do not push or publish changes
without authorization. Preserve copyright notices for vendored code and sources.
