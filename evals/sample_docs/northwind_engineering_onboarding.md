# Northwind Labs Engineering Onboarding Guide

Welcome to Northwind Labs engineering. This guide walks new engineers through their first 90 days: what happens before you join, how to set up your development environment, how code gets to production and when you take on responsibilities such as on-call. It is maintained by the Developer Experience team. Company-wide rules on leave, benefits and expenses are in the Employee Handbook; this guide only adds what is specific to engineering.

Northwind Labs is a fictional software company used as sample data for DocPilot.

## 1. Before your first day

Your laptop is shipped to your home address 5 working days before your start date. Please do not set it up on your own. It enrols in FleetGuard, our device management service, during the guided setup session on Day 1, and a laptop set up without that session has to be wiped and started again.

About 2 days before you start, you receive an email inviting you to activate your NorthID account. NorthID is the single sign-on service for every company tool, from email to GitHub. Activate it from your personal phone so you can sign in on Day 1.

Your manager sends you a short welcome note with the name of your team, your onboarding buddy and the first tickets on your onboarding board.

## 2. Your first week

Engineers spend their whole first week in the Bengaluru office, Monday to Friday, regardless of the team's usual hybrid schedule. Meeting the team in person in the first week makes the rest of onboarding much faster, and the setup sessions are run in person.

A typical first week looks like this:

- **Day 1:** IT setup session at 10:00 (laptop, FleetGuard, NorthID and your hardware security key), meeting your team, and an introduction to the company from the People team.
- **Day 2:** Development environment setup with the Developer Experience team, ending with a working local build of the services your team owns.
- **Day 3:** Architecture overview: how Northwind Ledger is built, how services talk to each other, and where data lives.
- **Days 4 and 5:** Pair with your buddy on your starter task and open your first pull request.

Your onboarding buddy is an engineer from a different team who helps you find your way around: who to ask, which documents to trust, and how things really work. Your buddy is assigned for your first 8 weeks, and you should meet at least once a week, even if only for fifteen minutes.

## 3. Development environment

All backend services live in the Atlas monorepo. Clone it and run `nwdev bootstrap`, the setup command of our internal developer CLI. It installs the pinned toolchain (Python 3.12, Node 20 and Go 1.22) and starts local Postgres and Redis containers. A full bootstrap takes about 40 minutes on a new laptop, most of it downloading container images.

If anything fails, run `nwdev doctor` and post its output in the #eng-help channel. Please do not install toolchains by hand: version drift between laptops is the most common cause of "works on my machine" bugs.

The staging environment is rebuilt from production snapshots every night at 02:00 IST, with all customer data anonymised during the copy. Anything you change in staging during the day is therefore gone the next morning. Long-running experiments belong in a personal preview environment, which you can create with `nwdev preview`.

## 4. Your first pull request

Pick a ticket labelled `good-first-task` from the onboarding board. Your first pull request should be under 100 changed lines, and most engineers merge it within their first 5 working days. Small first changes teach the review process, the CI pipeline and the release train without the stress of a big feature.

The general rules for approvals are in the Employee Handbook. In addition, reviewers are expected to respond to review requests within 1 working day, even if the response is only to say when they will review. If a review is blocking you for longer, ask in your team channel.

New code must keep test coverage at or above 80% for the files it touches. CI blocks merges that drop coverage below that line. Tests should run in under a minute locally for the module you changed; slow tests are tagged `slow` and run only in CI.

## 5. Releases and deployments

Production releases go out on release trains that leave every Monday and Wednesday at 14:00 IST. A change must be merged to main by 12:00 IST on the day of the train to be included. Urgent fixes outside the train need approval from the on-call engineering manager and are deployed through the same release pipeline.

Every user-facing change ships behind a feature flag in Beacon, the feature flag service. A flag lets you turn a change on for internal users first, then for a percentage of customers, and turn it off instantly if something goes wrong. Flags must be removed within 30 days of full rollout so that old code paths do not pile up.

There is a deployment freeze from 20 December to 2 January every year. Only P1 fixes are deployed during the freeze, and each one needs approval from the head of engineering.

## 6. Access to production

New engineers get read-only access to production dashboards and logs after 30 days. Write access to production through Jumpgate requires completing the Production Readiness course and at least 60 days at Northwind Labs. The Production Readiness course takes about half a day and covers the release pipeline, rollbacks, database migrations and incident handling.

Production access is always granted just in time and expires automatically. The exact rules are in the Information Security Policy.

## 7. Joining on-call

Engineers join their team's on-call rotation after 3 months. Before your first solo week, you shadow 2 full on-call shifts and run one incident drill with your team. During shadow shifts you are paged together with the primary on-call engineer, and you take the lead on at least one alert with them watching.

The on-call allowance and the response times for P1 incidents are described in the Employee Handbook. Runbooks for every alert are linked from the alert itself; if an alert has no runbook, writing one is a great early contribution.

## 8. Leave and time off in your first months

Sick leave is available from your first day; you do not need to have worked for any minimum period. Paid leave accrues from your joining date. During your first 3 months you can take up to 2 days of paid leave in advance with your manager's approval, before you have accrued it.

Please avoid planned leave during your first two weeks, because most onboarding sessions happen then and are not repeated until the next joining batch.

## 9. Check-ins and goals

Your manager runs check-ins with you at 30, 60 and 90 days. The 30-day check-in is about settling in, the 60-day check-in about your first real project, and at the 90-day check-in you and your manager agree on goals for your first performance review.

The Developer Experience team sends a short onboarding survey on day 45. It is anonymous, and it is how this guide gets better, so please fill it in.

## 10. Getting help

- **#eng-help:** tooling, builds, CI and the development environment.
- **#security-help:** anything security-related, including a lost device.
- **#people-help:** leave, payroll and other People team questions.
- **#devex:** feedback on this guide and on developer tooling.

When in doubt, ask your buddy or your manager. Nobody expects you to know how things work here yet, and asking early is always better than being stuck quietly.
