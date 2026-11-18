# Marketing skill sources

These are selected, unmodified `SKILL.md` documents from three public projects.
Their folder names keep overlapping skill names separate. They are reference
material for Shopivell's marketing prompts; no third-party shell scripts or
account connectors are executed by the backend.

| Source | Upstream revision | Copied here | Distinct use |
| --- | --- | --- | --- |
| [Corey Haines, Marketing Skills](https://github.com/coreyhaines31/marketingskills) | `73573e94a06a39965978b3fa1f9c1eace8cebc7c` | 12 skill files | Positioning, creative, copy, analytics, CRO and SEO foundations |
| [Ryze AI, Marketing Skills](https://github.com/irinabuht12-oss/marketing-skills) | `b3bdcd618a61034509f66e48ac0bb588f8defceb` | 8 skill files | Account audits, fatigue, spend, landing page and tracking analysis |
| [Meta Ads Kit](https://github.com/TheMattBerman/meta-ads-kit) | `dffa0daf6ed1e278481e9408af3be6aaf9709b28` | 6 skill files | Meta reporting, creative monitoring, budget, copy, upload and Pixel/CAPI guidance |

Corey's and Meta Ads Kit's MIT licenses are copied alongside their skills.
Ryze's README says the skills are MIT licensed, but the repository has no
separate LICENSE file at the revision above. The original README is the source
for that statement.

Some source documents link to reference files or use Ryze MCP and Meta Ads CLI
commands that are not copied here. Shopivell uses only bounded guidance from
the cited source files in `modules/openclaw/marketing_skill_library.py`.
Shopivell's live Meta actions remain with Zernio and are never inferred from
these instructions. Metrics, approvals and account data must come from the
connected account, not from a website or model guess.

## Current runtime use

- `ad_copy`: Corey ad creative and copywriting plus Meta Ads Kit copy patterns
  are loaded into the existing OpenAI ad-copy request.
- `brand_url_audit`: Corey positioning and CRO plus Ryze landing-page audit
  guide the read-only `scripts/marketing_skills_probe.py` URL trial.

The source repositories have not been forked to the owner's GitHub account.
The connected GitHub tool has no fork operation, and this sandbox currently
blocks GitHub API network access for `gh repo fork`.
