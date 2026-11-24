# Shopivell Website Builder

The Website Builder extends Shopivell's existing authenticated store experience. It uses Shopivell authentication, store/product/FAQ data, its existing AI website generation service, and PostgreSQL models. It is not a separate SiteForge deployment.

## Project flow

1. The frontend loads the published template catalog from `GET /v1/api/website-builder/templates`.
2. `POST /websites` creates a store-owned project and deep-copies each selected template page into `website_project_pages`. Editing the copy never writes into the source template.
3. `POST /websites/{id}/generate` uses store profile, products, FAQs, brand colors, typography, and selected template structure as AI context. Generated pages update only the project's GrapesJS JSON and preview.
4. The GrapesJS editor stores complete project JSON per page, autosaves after edits and every 15 seconds, and supports pages, media uploads, undo/redo, devices, named versions, and restore.
5. Publishing snapshots the project. The published API URL renders the saved page and provides the website chat widget.
6. Website visitor messages are answered using the store's existing knowledge-grounded assistant, saved to the Website Messages inbox, and emailed to the store email (falling back to the owner email).

## Important API paths

- `GET /v1/api/website-builder/templates` and `/templates/{id}`
- `POST /v1/api/website-builder/websites` (optional `template_id`)
- `/websites/{id}/pages` (list, create, update, delete, reorder)
- `/websites/{id}/versions`, `/websites/{id}/restore/{version_id}`
- `/websites/{id}/media` (authenticated image upload/list/delete)
- `/websites/{id}/inbox` (authenticated owner inbox)
- `POST /v1/api/website-builder/websites/{id}/deploy`
- `GET /v1/api/website-builder/public/sites/{id}?page=/`
- `POST /v1/api/website-builder/public/sites/{id}/messages`

Administrators can manage templates in the builder's **Manage templates** screen or through POST/PUT/DELETE `/templates` and POST/PUT `/templates/{id}/pages`. The UI accepts imported GrapesJS project JSON, previews pages, and controls draft/published visibility.

## Configuration and persistence

- `PUBLIC_API_URL` controls published site and media URLs; defaults to `https://api.shopivell.com`.
- `WEBSITE_UPLOAD_DIR` controls local website media storage; defaults to `uploads/website-builder`.
- Visitor email notifications use the existing `EMAIL_USERNAME`, `EMAIL_PASSWORD`, `SMTP_SERVER`, and `SMTP_PORT` settings.
- The backend startup `database.init_db()` imports these models and creates missing tables. Existing installations use the project's current schema startup process.
- Domain registration is intentionally not enabled. A registrar provider API and key are required before domain search, purchase, or DNS setup can be offered.

## Local checks

From the frontend repository:

```sh
npm run build
node node_modules/typescript/bin/tsc --noEmit
```

From the backend repository:

```sh
python -m compileall -q modules/website_builder
```

The backend publishes its OpenAPI documentation at `/docs` in the normal Shopivell FastAPI deployment.
