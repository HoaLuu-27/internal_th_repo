# Zegal CRM / Sales / Documents -> Project (Phase 1)

## Pain points addressed

| Pain point | Delivery in this module | Owner action |
| --- | --- | --- |
| Leads are mixed between commercial, project, warranty and change requests | Lead type, requirement type, site, required completion and intake scope on CRM opportunity | Configure pipeline stages and lead sources |
| Quotations have different pricing bases and lose their version history | Sale type, quotation type and revision counter | Configure products, UoM, pricelists and quotation templates |
| PM receives an incomplete handover after deal closure | Required handover checklist, approved scope, committed timeline and payment notes | Define the final checklist and project-manager assignment rule |
| A confirmed project sale does not create a traceable project | Controlled **Create Project** action; it preserves the sales order and opportunity links | Configure service products / project templates if Odoo's automatic task creation is also used |
| Files are scattered between sales and delivery | One project dossier folder created in Odoo Documents | Configure folder permissions and document tags |

## What must be configured (no custom code)

1. Master data before UAT: UoM categories (m2, hour, block, day), products/services, cost categories, customer/lead sources and sales teams.
2. CRM stages: New request -> Survey -> Technical take-off -> Quotation -> Negotiation -> Won / Lost. Keep `Handover to project` as a visible milestone.
3. Sales: quotation templates by pricing basis; service products configured to create tasks/projects only where the native Odoo automation is wanted; payment terms and milestones.
4. Project: project templates/WBS, task stages, roles, planned hours and analytic account/cost centre design.
5. Documents: permissioned root folders, tags (`Technical`, `Quote`, `Contract`, `Appendix`, `Acceptance`, `Invoice`) and retention rules.
6. Access: sales may edit intake/quotation; PM confirms the checklist; only designated roles create the dossier/project.

## Custom scope implemented

The module deliberately keeps the Phase 1 custom layer narrow:

- CRM intake classification and scope fields.
- Sale classification, quotation revision number and project handover data.
- A handover checklist that blocks project creation when required entries are incomplete.
- Explicit sales order -> project -> opportunity mapping.
- A one-click Documents folder for the project dossier.

## Gaps intentionally not built in this module

These require a separate design because they affect finance/procurement controls: internal BoQ/costing import, margin and quotation approvals, contract/amendments, project budget/committed/actual cost, change-request approval, purchase/stock approval and allocation, milestone invoicing reconciliation, and project P&L. The PDF classifies several of these as moderate/deep custom work; they should not be hidden inside the CRM-to-project flow.

## Acceptance test

1. Create a Project opportunity; record the intake and attach customer files using chatter/Documents.
2. Create a project quotation, set a pricing type and revision; confirm it.
3. Enter approved scope, customer timeline, payment notes and complete all required checklist rows.
4. Click **Create Project**; verify source sales order/opportunity and handover fields on the resulting project.
5. Click **Create Project Dossier Folder** and upload/tag the project documents in that folder.
