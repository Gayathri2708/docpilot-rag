# Northwind Ledger: Product FAQ

This FAQ answers the questions customers ask most often about Northwind Ledger: plans and pricing, billing, the API, uptime and support, and how customer data is handled. It is maintained by the Northwind Labs customer success team.

Northwind Labs and Northwind Ledger are fictional and used as sample data for DocPilot.

## About the product

### What is Northwind Ledger?

Northwind Ledger is Northwind Labs' invoicing and accounts-receivable platform for small and mid-sized businesses. It creates and sends invoices, chases late payments with automatic reminders, matches incoming payments to open invoices and reports on cash flow.

### Who is it for?

Ledger is built for businesses that send between a few dozen and a few thousand invoices a month and do not want to run a full accounting suite just to get paid on time. Finance teams usually connect Ledger to their existing accounting software and use it as the front end for receivables.

## Plans and pricing

### What plans are available?

Northwind Ledger has three plans: Starter at USD 12 per user per month, Growth at USD 29 per user per month, and Enterprise with custom pricing agreed with our sales team. Annual billing gives a 15% discount on Starter and Growth.

### What are the limits on the Starter plan?

The Starter plan supports up to 10 users and 500 invoices per month. Growth and Enterprise have no invoice limit. If a Starter workspace reaches its invoice limit, existing invoices keep working and reminders keep going out, but new invoices can only be created after upgrading or when the next month begins.

### Is there a free trial?

Yes. Every new workspace starts with a 14-day free trial of the Growth plan, and no payment card is needed to start. At the end of the trial, the workspace moves to a paid plan or becomes read-only until a plan is chosen.

## Billing, cancellation and refunds

### When am I billed?

Monthly plans are billed in advance on the 1st of each month. Adding users mid-month is charged pro rata on the next bill. Removing users takes effect from the next billing month.

### Can I cancel?

Monthly plans can be cancelled at any time and stay active until the end of the billing month. There is no cancellation fee.

### Do you offer refunds?

Annual plans can be refunded pro rata if cancelled within 30 days of the start or renewal date. After those 30 days, annual plans are not refundable, but they stay active until the end of the paid year. Monthly plans are not refunded for partial months.

## API and integrations

### Is there an API?

Yes. The REST API is available on all plans and covers everything the web app can do. Rate limits are 60 requests per minute on Starter, 600 on Growth and 3,000 on Enterprise. Requests over the limit receive HTTP status 429 with a Retry-After header that says how many seconds to wait.

### How do webhooks work?

Webhooks notify your systems when an invoice is created, sent, viewed or paid. A webhook delivery that fails is retried up to 8 times over 24 hours, with exponential backoff between attempts. Deliveries that still fail are listed in the webhook log for 7 days.

### Which integrations are built in?

Ledger connects natively to Slack, Microsoft Teams and Zapier on every plan. Enterprise adds SAML single sign-on and SCIM user provisioning, so users can be created and removed from the customer's own identity provider.

## Uptime and support

### What uptime do you guarantee?

Growth comes with a 99.9% monthly uptime SLA and Enterprise with 99.95%. If uptime falls below the SLA in a month, the customer receives a service credit of 10% of that month's fee for each 0.1 percentage point below the SLA, up to a maximum of 50% of the monthly fee. Credits are applied automatically to the next invoice.

### How do I get support?

Support depends on the plan. Starter customers get email support with a response within 2 business days. Growth customers get chat and email support with a response within 8 business hours. Enterprise customers have a named account manager and get a first response to Priority 1 tickets within 1 hour, 24 hours a day, 7 days a week.

A Priority 1 ticket means Ledger is unavailable or invoices cannot be sent for the whole workspace.

## Data, security and privacy

### Where is my data stored?

Customer data is stored in the region chosen when the workspace is created: India (Mumbai) or the European Union (Frankfurt). Data cannot be moved between regions after the workspace has been created, so choose the region that matches your data residency needs.

### How is my data backed up?

Backups are taken every 6 hours and kept for 35 days. Backups are stored in the same region as the workspace.

### What happens when I delete my workspace?

When a workspace is deleted, its data is kept for 30 days so it can be restored if the deletion was a mistake. After that, the data is permanently purged, including from backups once they expire.

### Do you keep audit logs?

Audit logs record sign-ins, permission changes, exports and invoice edits. They are kept for 90 days on Growth and for 1 year on Enterprise. Audit logs are not available on Starter.

### Which certifications do you have?

Northwind Ledger is ISO 27001 certified. SOC 2 Type II reports are available to Enterprise customers under a non-disclosure agreement.

### Can I require two-factor authentication for my team?

Yes. Workspace admins on every plan can require two-factor authentication for all users in their workspace from Settings, Security.

## Features

### Which currencies are supported?

Invoices can be created in 42 currencies. Exchange rates are updated daily at 06:00 UTC and the rate used is saved on each invoice.

### How large can attachments be?

Each file attached to an invoice can be up to 25 MB. PDF, PNG, JPG and XLSX attachments are supported.

### Can invoices repeat automatically?

Yes. Recurring invoices can run weekly, monthly, quarterly or yearly, and each run can be sent automatically or held as a draft for review.

### When are payment reminders sent?

By default, reminders are sent 3 days before the due date, on the due date and 7 days after it. Each workspace can change the schedule or turn reminders off for individual customers.

### Can I export my data?

Yes. Invoices, payments and customers can be exported as CSV, XLSX or PDF at any time, on every plan.

### Is there a mobile app?

Yes. The Ledger apps for iOS and Android can create and send invoices, and can create invoices offline. Offline changes are synced when the device is back online.

### How do I transfer ownership of a workspace?

The current owner can transfer ownership to another admin from Settings, Members. Each workspace has exactly one owner at a time.
