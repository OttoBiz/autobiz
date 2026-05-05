# Ottobiz

## In one line

Ottobiz runs the WhatsApp sales desk for small businesses — replying to customers, chasing suppliers, confirming payments, and booking deliveries — all at once, all on its own.

## The problem

In our launch markets, commerce happens in WhatsApp. The shop owner is the bottleneck. They are the salesperson, the procurement clerk, the accountant, and the dispatcher — at the same time.

They lose sales because they can't reply fast enough. They forget to follow up with the supplier about a restock. They miss bank alerts and ship the wrong order. They lose receipts. They've already tried hiring an assistant; the assistant cost more than they made and still missed the supplier follow-ups.

The result is a business that can never grow past the owner's attention span.

## What Ottobiz does

Ottobiz is the operations team this business never had. From the moment a customer sends "hi, do you have size 8?" to the moment that customer's order is paid, packed, restocked, and out for delivery, Ottobiz handles it.

- It **answers customers** in seconds, in their language, with the right product and the right price.
- It **negotiates and takes orders** the way the owner would.
- It **chases the supplier** when stock is low, holds that conversation across hours and days, and brings the answer back into the customer's thread without losing context.
- It **verifies payments** by reading bank alerts and matching them to the right order.
- It **books the rider** and updates the customer when the delivery is on its way.

To the customer, nothing changes. They message the business on WhatsApp the way they always have. The business just answers faster, gets it right, and never drops them.

## Who we serve

Owners of 1–20 person businesses that sell over WhatsApp:

- Fashion boutiques and resellers
- FMCG and household goods shops
- Pharmacies and beauty supply stores
- Electronics and accessory vendors
- Food and grocery vendors

These are businesses that have never been served by Shopify, Square, or any conventional commerce stack — because the chat *is* the storefront, the receipt book, and the CRM all at once. Ottobiz is built for the way they actually operate, not the way Western SaaS assumes they should.

## How we make money

Ottobiz prices like airtime, not like software. We charge for the work the agent does — not for the money the shop receives. This is deliberate: in our market, payment rails are open and shops can collect bank transfers directly. We never depend on seeing the shop's money. We only depend on doing the shop's work, and that work is observable from our own side.

**Monthly floor.** Each shop pays a monthly floor anchored to a fraction of what a junior sales assistant would cost. The floor covers access to the agent and a starter pack of credits.

**Credits for usage.** Beyond the starter pack, owners top up credits whenever they want — the same way every Nigerian SME already buys airtime. Each credit covers one unit of work the agent does: a customer reply, a supplier follow-up, an order processed end-to-end. There is no card-on-file, no surprise bill, no separate usage invoice — just one balance the owner watches and tops up.

**Referral cut on the cross-vendor network.** When Ottobiz introduces a customer from one shop to another — shoes to go with a dress, a clinic next to a pharmacy — the receiving shop pays the source shop a commission, and Ottobiz takes a cut on top. This line is structurally enforceable in a way primary commerce is not, because the introduction itself happens inside our system. It is also where the network effect lives: every new shop in a neighborhood makes the recommendation graph richer for every shop already on it.

The floor and credits scale linearly with shops on the platform. The referral cut scales with shops × density × complementarity — the layer that compounds. As model and infrastructure costs continue their decline, our cost per credit shrinks while the price the owner pays stays steady; gross margins expand automatically over time.

## The competitive picture

The category looks crowded from the outside. Up close, almost every player is doing one half of the job — the customer-facing half.

- **Global WhatsApp commerce platforms** — Wati, Yalo, AiSensy, Interakt, Gallabox, Gupshup, SleekFlow. Inbound chatbots, shared inboxes, and customer re-engagement. SleekFlow's *AgentFlow* ships role-specialized agents (sales, support, analyst); their forthcoming "outbound agent" re-engages *customers* for lead recovery, not suppliers for restocks.
- **Direct-commerce platforms** — Flowcart (Kenya) is the closest-named overlap on paper; in practice it is conversational commerce focused on click-to-WhatsApp ads, cart recovery, and Shopify/WooCommerce checkout. Customer-facing only.
- **Africa-specific** — Vendy (YC W22, Lagos) is agentic payments infrastructure and a Meta-approved BSP — a payments rail we coexist with rather than compete against. Bumpa builds storefront tools for small WhatsApp/Instagram sellers. Kayko (Rwanda) does small-business automation at fast-growing scale.
- **The structural threat** — Meta is shipping native AI agents inside WhatsApp Business itself, which will commoditize inbound conversational AI.

## How we stand out

Every competitor we have examined operates on the **customer side only**: answer questions, take orders, recover carts, re-engage. That is the easier half of running a real business in chat.

Ottobiz operates on **both sides**. Behind every customer reply, a real business has another conversation it has to run — with a supplier to confirm stock, with a rider to book a pickup, with a bank alert to verify a payment, with a partner to chase an exception. Those conversations are asynchronous, multi-party, and stateful. They are also where most lost sales actually happen.

We hold those conversations in parallel with the customer's, and we stitch the outcomes back together automatically. The supplier who answers forty minutes later lands in the right thread, with the right context, and triggers the right follow-up to the right customer — without the owner touching anything.

That is the difference between a chatbot and an operations team. As Meta commoditizes the inbound side, the value migrates to the side we built first.

## The network underneath

Because every Ottobiz-powered shop is already wired into the same coordination layer, those shops naturally form a network. We are building a cross-sell layer on top of it.

When a customer buys a dress, their Ottobiz can suggest shoes from the boutique next door, a tailor for adjustments, or a stylist who already serves the same neighborhood. When a customer fills a prescription, their pharmacy's Ottobiz can suggest the nearby clinic, the lab that ran their last test, or a delivery rider who already knows the address. Recommendations are restricted to **complements**, never substitutes — a shop is never offered up against its competitors.

Cross-sell is **opt-in per shop**. Owners choose whether to participate, on which catalog, and on what commission split. Shops that opt in earn a referral fee on every sale they send to a neighbor. Ottobiz takes a cut.

Two things make this layer hard for any of our competitors to copy quickly. First, every other player on the field runs as a siloed install per merchant — their architecture has no way to see across vendors. Second, recommendations only matter if they convert; ours fire inside the conversation that is already happening, at the moment of intent, on a channel the customer already trusts. Click-through ad-style recommendations don't work in chat. Ours do, because they're delivered by the agent the customer is already talking to.

## Why now

Two things changed at once. AI models are now competent enough to hold a real commercial conversation across multiple parties without supervision. And in our launch markets, WhatsApp has already become the system of record for commerce — there is no underlying ERP, CRM, or POS to displace. The chat *is* the business. We don't have to fight entrenched software; we get to formalize what is already happening in chat, with AI doing the work the owner currently does by hand.

## What we have

A production system, in active use, with the customer agent, the persistent supplier-side agent, the back-office coordinator, the products and inventory pipeline, multi-channel reach, and full observability — running today, for real businesses, on real orders.
