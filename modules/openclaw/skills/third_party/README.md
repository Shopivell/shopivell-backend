# Marketing skill sources

These are selected, unmodified `SKILL.md` documents from three public projects.
Their folder names keep overlapping skill names separate. They are reference
material for Shopivell's marketing prompts; no third-party shell scripts or
account connectors are executed by the backend.

| Source | Upstream revision | Copied here | Distinct use |
| --- | --- | --- | --- |
| [Corey Haines, Marketing Skills](https://github.com/coreyhaines31/marketingskills) | `73573e94a06a39965978b3fa1f9c1eace8cebc7c` | 13 skill files | Positioning, creative, imagery, copy, analytics, CRO and SEO foundations |
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

The previous `ad-creator`, `market-research` and `zernio-ads` skill definitions
are disabled (`SKILL.md.disabled`); their TypeScript implementations are
commented out. The former Python creative and agent prompt blocks are also
commented out. Active angle, campaign-copy, research, planner, goal, evaluator,
calibration and image prompts now use `marketing_skill_library.py`. Existing
executor action IDs remain API routing names so stored plans still resolve.
They do not load the disabled skill instructions.

- `ad_copy`: Corey ad creative and copywriting plus Meta Ads Kit copy patterns
  are loaded into the existing OpenAI ad-copy request.
- `brand_url_audit`: Corey positioning and CRO plus Ryze landing-page audit
  guide the read-only `scripts/marketing_skills_probe.py` URL trial.
- `scripts/meta_brand_draft_probe.py` uses the backend's existing OpenAI key to
  generate three Meta ad angles, nine copy variants and three image concepts.
  It saves a local HTML preview and does not publish a campaign.

The source repositories have not been forked to the owner's GitHub account.
The connected GitHub tool has no fork operation, and this sandbox currently
blocks GitHub API network access for `gh repo fork`.
