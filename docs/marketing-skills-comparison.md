# Marketing skill comparison and Shopivell selection

Source revisions and copied file counts are recorded in
[`modules/openclaw/skills/third_party/README.md`](../modules/openclaw/skills/third_party/README.md).

| Job | Corey Marketing Skills | Ryze AI Marketing Skills | Meta Ads Kit | Shopivell choice |
| --- | --- | --- | --- | --- |
| Positioning, customer language, copy | Detailed foundation and creative frameworks | Some ICP and ad-copy helpers | Brand-aware Meta copy | Corey foundation with Meta Ads Kit's visual/copy alignment |
| Website and landing-page review | CRO and copywriting diagnosis | Ad-to-page message match audit | Limited | Corey CRO plus Ryze landing-page checks |
| Live paid-account diagnosis | Cross-platform strategy and evidence rules | Granular Meta/Google diagnostics, often expecting Ryze MCP | Daily Meta reports and fatigue | Keep Shopivell's Zernio account data; use guidance only when metrics exist |
| Campaign actions | Planning guidance | Ryze connector can propose account actions | Meta CLI scripts can modify ads | Shopivell's existing Zernio action path remains authoritative |
| SEO and AI visibility | SEO audits and content strategy | Dedicated AI visibility and SEO playbooks | Limited | Copy selected analysis guides; run only when requested and data is available |

The three sources overlap on ads and copy. Their instructions are written for
different agent environments. Shopivell loads bounded excerpts from selected
documents into its existing ad-copy request, rather than installing Ryze MCP or
running Meta Ads Kit shell scripts. The URL probe uses a separate, read-only
analysis prompt. Neither route can infer spend, conversions, CPA, ROAS or
creative fatigue from a website alone.

## Reliable Tech URL trial, 2026-11-18

Test URL: [reliabletech.co.zw](https://www.reliabletech.co.zw/).
The site did not respond to this sandbox's direct HTTPS request. The test input
in `tests/fixtures/reliabletech-page.txt` was assembled from the indexed
[homepage](https://www.reliabletech.co.zw/) and
[product page](https://www.reliabletech.co.zw/products). It is a snapshot, so
prices and fulfilment claims need rechecking before publication.

**Observed in the supplied page text:** Reliable Modern Technologies sells IT
products in Zimbabwe, including laptops, printers, cameras and networking
equipment. It advertises same-day delivery in Harare, nationwide shipping,
manufacturer warranties and EcoCash/bank-transfer payment. Its indexed product
list showed a Canon PIXMA MG2541S 3-in-1 Printer at `$50.00`.

**Model review of the skill prompt, using the evidence above:**

1. A useful provisional angle is the printer's three listed functions with an
   enquiry CTA. Confirm the exact model functions and current price before an ad
   is published.
2. A second angle can focus on Harare delivery for a listed product. The page
   claims same-day delivery, but cut-off times, stock and eligible areas are
   unknown, so the copy should not promise delivery for a specific order.
3. The homepage's broad category range suggests separate laptop and printer
   landing pages could be tested. Without an actual ad and page pairing, the
   Ryze message-match check has no score to calculate.

**Missing evidence:** current ad copy, spend, impressions, CTR, CPA, ROAS,
conversion events, customer reviews, target audience, visual assets, stock and
current fulfilment terms. The skills should report these as missing instead of
inventing numbers or naming a winning creative.

The prompt builder and Python files passed local syntax checks. A live OpenAI
API run was attempted with the URL snapshot, but it stopped before sending a
request because this environment has no `OPENAI_API_KEY`. This review was made
in the OpenAI assistant session; it is not a Shopivell API result or a live
campaign performance measurement. When a network-enabled environment has the
key, run:

```powershell
python scripts/marketing_skills_probe.py https://www.reliabletech.co.zw/ --output reliabletech-audit.json
```
