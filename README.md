# 🤖 WhatsApp AI Assistant

A modular, agent-based WhatsApp assistant that automates business operations through intelligent conversation flows.

## 🎯 Overview

This AI assistant handles:
- **Product Inquiries** - Answer questions about products and services
- **Order Processing** - Manage cart, checkout, and order tracking  
- **Payment Integration** - Secure payment processing via multiple providers
- **Delivery Management** - Schedule and track deliveries
- **Business Communication** - Escalate complex issues to business owners

## 🏗️ Architecture

**Agent-Based Design:**
- `OrchestratorAgent` - Central FSM controller and routing logic
- `ProductInfoAgent` - Product queries and recommendations
- `PaymentAgent` - Payment processing flows
- `InventoryAgent` - Stock management and updates
- `DeliveryAgent` - Delivery scheduling and tracking
- `BusinessCommAgent` - Owner escalation and communication
- `CustomerChatAgent` - Message formatting and customer experience

**Clean Separation:**
- **Agents** handle business logic only
- **Services** manage external integrations (WhatsApp, payments, logistics)
- **API Layer** orchestrates message flow and state management

## 🛠️ Tech Stack

- **FastAPI** - Web framework and API routing
- **SQLModel** - Database ORM and data modeling
- **Pydantic** - Data validation and settings management
- **Redis** - Session state and memory management
- **PostgreSQL** - Persistent business data storage

## 📁 Project Structure

```
whatsapp-ai-assistant/
├── app.py              # FastAPI application factory
├── main.py             # Uvicorn entrypoint
├── config.py           # Environment configuration
├── models.py           # SQLModel database schemas
├── fsm.py              # Order state machine logic
├── routes.py           # API endpoints and routing
├── agents/             # Business logic agents
├── services/           # External service integrations
└── utils.py            # Common utilities
```

## 🚀 Getting Started

### Prerequisites
- Python 3.13+
- PostgreSQL
- Redis
- uv package manager

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd whatsapp-ai-assistant
   ```

2. **Install dependencies**
   ```bash
   uv sync
   ```

3. **Set up environment**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

4. **Run the application**
   ```bash
   uv run uvicorn main:app --reload
   ```

## 📡 API Endpoints

- `POST /chat` - Handle incoming WhatsApp messages
- `POST /webhook` - Process payment and logistics webhooks  
- `GET /health` - Health check endpoint

## 🔧 Configuration

Key environment variables:
- `WHATSAPP_API_KEY` - WhatsApp API credentials
- `PAYMENT_PROVIDER_KEY` - Payment processor API key
- `DATABASE_URL` - PostgreSQL connection string
- `REDIS_URL` - Redis connection string

## 🧪 Testing

```bash
uv run pytest
```

## 📄 License

[Add your license here]

## 🤝 Contributing

[Add contribution guidelines here]