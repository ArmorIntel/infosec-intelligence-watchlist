# Infosec Intelligence Watchlist

This repository contains a curated list of RSS feeds related to Cyber Threat Intelligence, Threat Hunting, and Information Security.
It consolidates high-signal RSS sources used for security monitoring, threat intelligence production, and **ongoing situational awareness**.
The list is curated for practitioners who need rapid access to advisories, research, vendor updates, and wider technology context without too much noise.

The goal is to help professionals, researchers, and enthusiasts stay up to date with the latest news, research, and discoveries in the cybersecurity landscape.

## Repository contents

<!-- BEGIN generated:categories -->
- `infosec-intelligence-watchlist.xml` &mdash; is an OPML (Outline Processor Markup Language) file of 309 feeds, grouped by categories:
  - **Threat Intelligence**
    - Security News
    - Research & Labs
    - AI Security
    - Vendor & Industry Updates
    - Government & CERT Bulletins
    - Alerts & Monitoring
    - Investigations & Breach Reporting
    - Communities & Experts
    - Knowledge Sharing & Podcasts
    - Intelligence Newsletters
    - OSINT & Tooling
  - **Technology Intelligence**
    - Industry & Innovation
    - AI & Data Science
    - Privacy, Compliance & Governance
    - Cryptocurrency & Blockchain
    - Apple Ecosystem
    - Hardware & IoT
    - Software & Open Source
    - Enterprise Platforms
    - Science & Academia
<!-- END generated:categories -->

- `opml/` &mdash; one OPML file per subcategory, generated from the global file, to subscribe only to the topics you need (see [Subscribe to a single category](#subscribe-to-a-single-category))
- `scripts/` &mdash; maintenance scripts used by the GitHub Actions (see [Automation](#automation)):
  - `build_category_opml.py` &mdash; regenerates the `opml/` files and the generated parts of this README
  - `check_feeds.py` &mdash; checks the health of every feed (dead, inactive, to check manually)
  - `feed-exceptions.txt` &mdash; low-frequency high-value sources and known quirks the health check should not flag
  - `validate_opml.py` &mdash; validates the OPML structure (two folder levels, no duplicate, sorted feeds)
  - `changelog.py` &mdash; lists the feeds added, removed and moved between two versions

Last review: **October 2026**.

## How to use the watchlist

1. Download the OPML file from this repository
2. Import the file into your RSS reader (tested with Inoreader, should be compatible with most RSS readers)
3. Review the folders, adjust notification rules, and fine-tune for your needs with filters, rules or tags in your RSS reader

### Inoreader example

#### Import feeds

There are two options, either you import all feeds and manage them, or you subscribe to the OPML file and get updates whenere it's updated.

One shot import :
![Importing feeds into Inoreader](./inoreader_screens/import_feeds.png)

Beware, if you use the free plan of Inoreader, you might be limited on the number of feeds you can import.
![Error feed limit](./inoreader_screens/feed_limit.png)

Subscribing to the OPML file :
You will need to use the raw file url from the xml file of this repository.
`https://raw.githubusercontent.com/ArmorIntel/infosec-intelligence-watchlist/refs/heads/main/infosec-intelligence-watchlist.xml`
![Subscribing to OPML file](./inoreader_screens/subscribe_opml.png)

### Subscribe to a single category

If you don't want the whole watchlist (or if your RSS reader plan limits the number of feeds), import or subscribe to one or several category files instead. Each file contains one subcategory of the global watchlist and is updated along with it.

<!-- BEGIN generated:category-table -->
| Category | Subcategory | Feeds | Raw OPML URL |
|---|---|---:|---|
| Threat Intelligence | [Security News](./opml/threat-intelligence/security-news.opml) | 21 | `https://raw.githubusercontent.com/ArmorIntel/infosec-intelligence-watchlist/refs/heads/main/opml/threat-intelligence/security-news.opml` |
| Threat Intelligence | [Research & Labs](./opml/threat-intelligence/research-and-labs.opml) | 36 | `https://raw.githubusercontent.com/ArmorIntel/infosec-intelligence-watchlist/refs/heads/main/opml/threat-intelligence/research-and-labs.opml` |
| Threat Intelligence | [AI Security](./opml/threat-intelligence/ai-security.opml) | 10 | `https://raw.githubusercontent.com/ArmorIntel/infosec-intelligence-watchlist/refs/heads/main/opml/threat-intelligence/ai-security.opml` |
| Threat Intelligence | [Vendor & Industry Updates](./opml/threat-intelligence/vendor-and-industry-updates.opml) | 32 | `https://raw.githubusercontent.com/ArmorIntel/infosec-intelligence-watchlist/refs/heads/main/opml/threat-intelligence/vendor-and-industry-updates.opml` |
| Threat Intelligence | [Government & CERT Bulletins](./opml/threat-intelligence/government-and-cert-bulletins.opml) | 22 | `https://raw.githubusercontent.com/ArmorIntel/infosec-intelligence-watchlist/refs/heads/main/opml/threat-intelligence/government-and-cert-bulletins.opml` |
| Threat Intelligence | [Alerts & Monitoring](./opml/threat-intelligence/alerts-and-monitoring.opml) | 11 | `https://raw.githubusercontent.com/ArmorIntel/infosec-intelligence-watchlist/refs/heads/main/opml/threat-intelligence/alerts-and-monitoring.opml` |
| Threat Intelligence | [Investigations & Breach Reporting](./opml/threat-intelligence/investigations-and-breach-reporting.opml) | 10 | `https://raw.githubusercontent.com/ArmorIntel/infosec-intelligence-watchlist/refs/heads/main/opml/threat-intelligence/investigations-and-breach-reporting.opml` |
| Threat Intelligence | [Communities & Experts](./opml/threat-intelligence/communities-and-experts.opml) | 26 | `https://raw.githubusercontent.com/ArmorIntel/infosec-intelligence-watchlist/refs/heads/main/opml/threat-intelligence/communities-and-experts.opml` |
| Threat Intelligence | [Knowledge Sharing & Podcasts](./opml/threat-intelligence/knowledge-sharing-and-podcasts.opml) | 3 | `https://raw.githubusercontent.com/ArmorIntel/infosec-intelligence-watchlist/refs/heads/main/opml/threat-intelligence/knowledge-sharing-and-podcasts.opml` |
| Threat Intelligence | [Intelligence Newsletters](./opml/threat-intelligence/intelligence-newsletters.opml) | 11 | `https://raw.githubusercontent.com/ArmorIntel/infosec-intelligence-watchlist/refs/heads/main/opml/threat-intelligence/intelligence-newsletters.opml` |
| Threat Intelligence | [OSINT & Tooling](./opml/threat-intelligence/osint-and-tooling.opml) | 8 | `https://raw.githubusercontent.com/ArmorIntel/infosec-intelligence-watchlist/refs/heads/main/opml/threat-intelligence/osint-and-tooling.opml` |
| Technology Intelligence | [Industry & Innovation](./opml/technology-intelligence/industry-and-innovation.opml) | 44 | `https://raw.githubusercontent.com/ArmorIntel/infosec-intelligence-watchlist/refs/heads/main/opml/technology-intelligence/industry-and-innovation.opml` |
| Technology Intelligence | [AI & Data Science](./opml/technology-intelligence/ai-and-data-science.opml) | 11 | `https://raw.githubusercontent.com/ArmorIntel/infosec-intelligence-watchlist/refs/heads/main/opml/technology-intelligence/ai-and-data-science.opml` |
| Technology Intelligence | [Privacy, Compliance & Governance](./opml/technology-intelligence/privacy-compliance-and-governance.opml) | 11 | `https://raw.githubusercontent.com/ArmorIntel/infosec-intelligence-watchlist/refs/heads/main/opml/technology-intelligence/privacy-compliance-and-governance.opml` |
| Technology Intelligence | [Cryptocurrency & Blockchain](./opml/technology-intelligence/cryptocurrency-and-blockchain.opml) | 15 | `https://raw.githubusercontent.com/ArmorIntel/infosec-intelligence-watchlist/refs/heads/main/opml/technology-intelligence/cryptocurrency-and-blockchain.opml` |
| Technology Intelligence | [Apple Ecosystem](./opml/technology-intelligence/apple-ecosystem.opml) | 11 | `https://raw.githubusercontent.com/ArmorIntel/infosec-intelligence-watchlist/refs/heads/main/opml/technology-intelligence/apple-ecosystem.opml` |
| Technology Intelligence | [Hardware & IoT](./opml/technology-intelligence/hardware-and-iot.opml) | 5 | `https://raw.githubusercontent.com/ArmorIntel/infosec-intelligence-watchlist/refs/heads/main/opml/technology-intelligence/hardware-and-iot.opml` |
| Technology Intelligence | [Software & Open Source](./opml/technology-intelligence/software-and-open-source.opml) | 10 | `https://raw.githubusercontent.com/ArmorIntel/infosec-intelligence-watchlist/refs/heads/main/opml/technology-intelligence/software-and-open-source.opml` |
| Technology Intelligence | [Enterprise Platforms](./opml/technology-intelligence/enterprise-platforms.opml) | 6 | `https://raw.githubusercontent.com/ArmorIntel/infosec-intelligence-watchlist/refs/heads/main/opml/technology-intelligence/enterprise-platforms.opml` |
| Technology Intelligence | [Science & Academia](./opml/technology-intelligence/science-and-academia.opml) | 6 | `https://raw.githubusercontent.com/ArmorIntel/infosec-intelligence-watchlist/refs/heads/main/opml/technology-intelligence/science-and-academia.opml` |
<!-- END generated:category-table -->

#### Explore feeds
![Feeds view](./inoreader_screens/feeds_view.png)

#### Manage feeds
![Content view](./inoreader_screens/content_view.png)

#### Create custom dashboards
![Dashboard view](./inoreader_screens/dashboard_view.png)

Pro tips : you can subscribe to Telegram channels, use tags, filter feeds and create automated rules (some features are in the paid plan). There is even an n8n node available, API key, etc. if you want to go further.

## Maintenance

- Check the list periodically to remove inactive feeds and add new relevant sources
- Contribute to the project, so everybody can use your new relevant sources
- When introducing new feeds, ensure they are **unique** and placed in the most relevant subcategory to preserve low noise

Review criteria used to keep the list clean:
- **Dead feed**: fails twice in a row (DNS error, HTTP 404/410/5xx, timeout, invalid certificate, or not a valid RSS/Atom document). When the source has moved, the feed URL is updated instead of being removed
- **Inactive feed**: nothing published for more than 6 months
- **Exceptions**: low-frequency but high-value sources (CERTs and government agencies, research labs, recognised researchers, primary sources) are kept as long as they published within the last 24 months
- Feeds blocked by anti-bot protections (HTTP 403/429 to scripts) but working in RSS readers are kept
- Entries specific to a personal RSS reader account (keyword alerts, newsletter addresses) are not part of the shared list

## Automation

The repository is maintained with GitHub Actions:

| Workflow | Trigger | What it does |
|---|---|---|
| [Monthly feed health check](.github/workflows/feed-health.yml) | 1st of each month, or manually | Checks every feed and keeps a single [`feed-health`](../../issues?q=label%3Afeed-health) issue up to date with the dead, inactive and suspicious feeds to review |
| [Validate watchlist](.github/workflows/validate-pr.yml) | Pull requests and pushes changing the watchlist | Validates the OPML structure, rejects duplicates, and checks that every added feed answers, is valid RSS/Atom and published within the last 6 months |
| [Sync generated files](.github/workflows/sync-generated.yml) | Pushes to `main` changing the watchlist | Regenerates the per-category OPML files and the generated parts of this README (category list, feed count, subscription table) and commits them |
| [Release a reviewed watchlist](.github/workflows/release.yml) | Manually, after a review | Creates a dated release (e.g. `2026.10`) with the list of feeds added, removed and moved since the previous one, and the OPML files attached |

To run the checks locally (Python 3.10+ and curl, no dependency):

```bash
python3 scripts/validate_opml.py
python3 scripts/check_feeds.py --markdown report.md
```

## Contributing

Contributions are welcome!
If you want to add new feeds or suggest improvements:
- Fork this repository
- Update the xml file (`infosec-intelligence-watchlist.xml` is the only file to edit): keep two folder levels and feeds sorted alphabetically
- Don't edit the `opml/` files or the generated parts of this README: they are regenerated automatically once your change is merged
- Submit a pull request with a description

Maintained by [ArmorIntel](https://github.com/ArmorIntel/).
You can reach out for collaboration or CTI discussions.