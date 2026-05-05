# Ottobiz

## What we are

Ottobiz is an AI-native operations layer for businesses that run on WhatsApp. We don't sell a chatbot and we don't sell software — we sell the service of running a small business's commerce operation: customer sales, supplier coordination, payment reconciliation, and delivery dispatch, performed autonomously by agents that talk on the business's behalf.

For the customer of an Ottobiz-powered business, nothing changes. They message the business on WhatsApp the way they always have. The difference is that the reply comes in seconds, the stock answer is correct, the payment receipt gets verified, the supplier gets pinged about a restock, and the dispatch rider gets booked — all without the owner touching the thread.

## What we do

Most small businesses in our target markets sell over WhatsApp. The owner is the bottleneck: they are simultaneously the salesperson replying to customers, the procurement clerk chasing suppliers, the accountant reconciling bank alerts, and the dispatcher coordinating riders. They lose sales because they can't reply fast enough. They forget to follow up with suppliers. They miss restocks. They lose receipts.

Ottobiz replaces that bottleneck with a system of coordinated agents:

- A **customer-facing agent** holds every customer conversation, answers product questions, negotiates, takes orders, and confirms payments.
- An **outbound agent** holds persistent conversations with the business's suppliers, riders, and partners — pinging them when stock runs low, when a delivery is needed, when a price needs confirming — and threading their replies back into the original customer conversation.
- A **back-office coordinator** turns those vendor replies into actions: updating inventory, re-pricing products, escalating to the owner when a human decision is needed.

These agents share a common ledger and conversation memory, so a vendor confirming "yes we have 3 left" forty minutes later gets stitched correctly back into the customer thread that has been waiting on it. This is the hard part of running a real business in chat, and it is what makes Ottobiz a transactional system rather than a chatbot.

## Who our customers are

Our buyer is the owner of a 1–20 person business that sells over WhatsApp — fashion boutiques, FMCG resellers, pharmacies, electronics shops, food vendors, beauty supply stores. They are drowning in chat threads. They are losing revenue every day to slow replies and forgotten follow-ups. They have already tried hiring an assistant; the assistant cost more than they made and still missed the supplier follow-ups.

Their customers — who never see Ottobiz directly — get a faster, more competent business to buy from.

## How we make money

We price as a service, not as software. Owners pay either a percentage of orders Ottobiz transacts or a flat monthly fee scaled to volume. We are not a per-seat SaaS, because what we replace isn't software — it's the labor of running a sales desk and a procurement desk.

## Why now

Two things changed at the same time. AI models are now competent enough to hold a real commercial conversation across multiple parties without supervision. And in our target markets, WhatsApp has become the system of record for commerce — there is no Shopify, no Square, no CRM, no ERP underneath. The chat *is* the business. That makes WhatsApp-first markets uniquely well-suited to an AI-native operations layer, because we are not displacing entrenched software; we are formalizing what was already happening in chat.

## What we have built

A production system, in active use, with:

- A unified inbox abstraction that folds customer and vendor conversations into a single coherent state
- A persistent outbound agent that maintains long-running threads with each of a business's suppliers and partners
- A task ledger in Postgres that tracks every promise, commitment, and pending resolution across parties
- A products API and inventory pipeline with real-time side-effects
- Channel abstraction (WhatsApp today, web and others wired in) so the same brain runs across surfaces
- A coordinator that turns vendor replies into back-office actions automatically
- An observability stack (Logfire) over every agent run, tool call, and resolution

The architecture is deliberate: agents are composed as tools, not chained, so we avoid the routing-and-context-loss problem that breaks most multi-agent systems. State lives in a ledger, not in agent memory, so vendor replies arriving hours later still resolve correctly. Channels are abstracted, so adding Instagram DM, SMS, or a web widget is a configuration change, not a rewrite.

## Where we are going

The next phase turns Ottobiz from "the agent that runs your sales desk" into "the brain that runs your business" — a layer that makes a small business legible to AI by ingesting everything the owner currently keeps in their head, their phone, and their paper books, and exposing it as a system the owner can query and that our agents can act on. On top of that brain, we will progressively replace the patchwork of tools (or absence of tools) that SMEs use today: bookkeeping, procurement, CRM, point-of-sale, payments and credit tracking, and marketing.

The brain is the moat. The modules are the revenue. Each module we ship makes the brain richer; each brain improvement makes every module work better. That is the compounding loop we are building toward.
