# Ottobiz Expansion Roadmap

This document describes how Ottobiz expands from "the agent that runs your WhatsApp sales desk" into two reinforcing positions: a **Company Brain** for small businesses, and a **SaaS Challenger** that progressively replaces the legacy tools (or absence of tools) those businesses rely on today.

The two positions are not separate products. The brain is the substrate. The SaaS modules are what monetize it. Every module we ship feeds the brain; every brain improvement makes every module smarter. That is the compounding loop, and it is the reason we should build them together rather than picking one.

---

## The thesis

A small business has a brain. Today it lives in the owner's head, their phone, a notebook, a few WhatsApp groups, and some bank SMS messages. Nothing is structured. Nothing is queryable. No software has access to it. Every tool the owner could buy — Shopify, QuickBooks, Hubspot, Square — assumes a level of digital structure that doesn't exist in our market, which is why those tools have failed to penetrate it.

Ottobiz already extracts and structures part of that brain through chat. The expansion is to ingest the rest of it, expose it to the owner as a queryable system, and then build the modules that act on it — replacing one legacy tool at a time, each one going deep rather than wide.

---

## The three layers

### Layer 1 — Brain ingestion

The foundation. None of these are user-visible features on their own. They are what turns the brain from "knows what happened in customer chat" into "knows the actual business." Without them, every module above ships half-blind.

| Capability | What it does |
|---|---|
| **Voice note ingestion** | Owner sends a voice note ("got 50 cartons of milk from Musa today, 18k each") → agent updates inventory and supplier ledger |
| **Receipt / invoice / waybill OCR** | Photo of a supplier invoice or bank teller slip → parsed and matched to the right record |
| **Bank SMS / transaction parsing** | Forwarded bank alerts → automatic reconciliation against pending orders. Eliminates the single biggest manual task in our market |
| **Supplier / staff WhatsApp group participation** | Agent joins the owner's existing groups and listens — extracting price changes, restock confirmations, dispatch updates as they happen |
| **Historical chat backfill** | On onboarding, ingest the last 3–6 months of WhatsApp history. Bootstrap product catalog, customer list, supplier relationships, and pricing patterns automatically |

The unlock here is **passive ingestion**. Owners shouldn't have to enter data. The brain learns from what they already do.

### Layer 2 — Brain queryability

This is where Company Brain becomes a sellable product on top of automation. The brain stops being plumbing and starts being something the owner directly uses.

| Capability | What it does |
|---|---|
| **Owner Q&A** | Natural language: "who owes me money?", "what did Musa say about the rice restock?", "which customers haven't ordered in a month?", "what's my best-selling SKU this week?" |
| **Daily briefing** | Morning push: overnight orders, pending vendor confirmations, low-stock alerts, debts due, anomalies. Replaces opening WhatsApp to 200 unread threads |
| **Anomaly + opportunity alerts** | "Aisha usually orders weekly, hasn't in 3 weeks." "Sugar wholesale price dropped 8% — restock now?" The brain acting on patterns, not just answering |

### Layer 3 — SaaS Challenger modules

Each module is a "we replace X" pitch. Each one is sellable on its own, and each one feeds structured data back into the brain.

| Module | Replaces | Reuse from current system |
|---|---|---|
| **Bookkeeping / P&L** | QuickBooks, manual ledgers, accountant fees | Orders + outbound ledger + bank SMS already feed this |
| **Procurement / supplier management** | Spreadsheets, supplier WhatsApp chaos | Outbound agent already does the hard part |
| **CRM** | Hubspot-lite, owner's memory | Chat history is already a CRM, just not exposed |
| **POS for walk-in sales** | Square, paper books | "Sold 2 bags rice to Aisha cash" via voice note |
| **Logistics / dispatch desk** | Manual rider coordination | Logistics agent stub already exists |
| **Payments + credit/debt tracking** | Manual ledgers, ad-hoc IOUs | Payment agent + ledger primitive |
| **Multi-channel storefront** | Shopify, Instagram shop | Channel abstraction already in place |
| **Marketing / re-engagement** | Mailchimp, Klaviyo | Brain knows who's lapsed and what they buy |

---

## Phasing

The temptation will be to ship a thin version of every module at once. That produces a wide, shallow product no one loves. We sequence by **brain-leverage**: build the foundation that makes everything downstream better, then expose it, then go deep on the two modules with the highest pain.

### Phase 1 — Ingestion completeness (months 1–2)

**Goal**: turn the brain from "knows chat" into "knows the business."

- Voice note ingestion
- Bank SMS / transaction parsing
- Historical chat backfill on onboarding

These three together change what every later phase can do. Voice notes capture what the owner already says out loud. Bank SMS kills the most-hated manual task in our market. Historical backfill changes onboarding from "set up your products" to "we already know your business — confirm what we found," which is the single largest activation lever we have.

Receipt OCR and supplier-group participation are stretch items in this phase if capacity allows.

### Phase 2 — Brain exposed (months 3–4)

**Goal**: make the brain a product, not just plumbing.

- Owner Q&A surface (in WhatsApp itself, addressed to the bot directly)
- Daily briefing
- Anomaly + opportunity alerts

After this phase, "Company Brain" is a thing we can sell on its own — even to a business that doesn't yet trust us to handle their customer chat. It also proves to ourselves that the ingestion work in Phase 1 produced something actually valuable.

### Phase 3 — First two SaaS challengers (months 5–7)

**Goal**: replace two specific tools, completely, for our existing customers.

- **Bookkeeping / P&L** — highest "I'd pay to replace this" urgency for SME owners; generates the most structured data back into the brain; closest to what the bank-SMS ingestion already produces.
- **Procurement / supplier management** — already half-built (the outbound agent is the hard part); turns the outbound ledger into a supplier scorecard, price tracker, and auto-RFQ surface.

Two modules. Go deep. Do not ship a third in this phase, even if it looks easy.

### Phase 4 — Data-driven third module (months 8+)

By the end of Phase 3, usage and conversation data will tell us what owners want next: CRM, payments/credit tracking, POS, logistics, or storefront. We do not pre-decide. We pick the module our customers are already asking for, and we go deep on it the way we did the first two.

The remaining modules ship in subsequent phases on the same principle: one at a time, deep, driven by demand signals from the prior phase.

---

## What this means for narrative

The Company Brain pitch and the SaaS Challenger pitch can fight each other if we lead with both equally. "We're the brain of your business" is a platform story — slow, sticky, infrastructural. "We replace your bookkeeping software" is a point-solution story — fast, transactional, easy to explain.

We lead with **Company Brain** as the narrative — *we make small businesses legible to AI* — and we use the **SaaS Challenger modules as proof points** — *and on top of that brain, we have already replaced their bookkeeping, their procurement, and their customer service desk*. The brain is the moat. The modules are the revenue. Both stories stay coherent, and neither cannibalizes the other.

---

## What this does *not* change

- The agent architecture (central / outbound / coordinator) is the right substrate for all of the above. No re-architecture is required to begin Phase 1.
- The unified inbox primitive and the outbound ledger are exactly the foundations the brain needs.
- The channel abstraction means new modules and new ingestion sources do not require touching agent code.

The expansion is additive. Nothing in the current system is being thrown away. Each phase strengthens the moat that the prior phase started.
