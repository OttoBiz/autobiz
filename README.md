# Ottobiz - Automated Business Platform

Ottobiz (derived from autobiz) is a comprehensive automated business platform designed for small and medium-sized businesses and enterprises. It handles the complete business cycle from initial customer messaging (from online ads) to sales conversion, logistics delivery, upselling, product recommendations, cold messaging, customer complaints, inventory management, and supply chain operations.

## 🎯 Project Overview

Ottobiz automates business operations through AI-powered agents that handle:
- **Customer Interactions**: Product inquiries, purchases, payment verification
- **Logistics Coordination**: Delivery planning and tracking between customers, vendors, and logistics companies
- **Upselling & Cross-selling**: Intelligent product recommendations
- **Customer Service**: Complaint handling with human agent escalation
- **Inventory Management**: Stock tracking and forecasting
- **Business Analytics**: Performance insights and recommendations
- **Supply Chain**: Supplier coordination and tracking

## 🏗️ Architecture

### Backend
- **Framework**: FastAPI (Python)
- **AI Library**: Pydantic AI (converted from LangChain)
- **Database**: PostgreSQL/Supabase
- **Cache**: Redis
- **Deployment**: Docker Compose, Render.com

### Frontend
- **Framework**: Next.js (React)
- **Styling**: Tailwind CSS
- **Deployment**: Vercel

### AI Agents
All agents inherit from a base agent class and use Pydantic AI:

1. **Base Agent**: Common functionality for all agents
2. **Product Agent**: Handles product inquiries and purchases
3. **Central Agent**: Coordinates 3-way communication (customer, vendor, logistics)
4. **Upselling Agent**: Recommends complementary products
5. **Customer Service Agent**: Handles complaints and escalations
6. **Payment Verification Agent**: Verifies customer payments
7. **Logistics Agent**: Coordinates deliveries
8. **Routing Agent**: Determines which agent to use
9. **User Analytics Agent**: Analyzes user behavior
10. **Business Analytics Agent**: Provides business insights
11. **Inventory Manager Agent**: Manages inventory (tool for business analytics)
12. **Supply Chain Agent**: Tracks supplies
13. **Audio Processing Agent**: Handles speech-to-text and text-to-speech
14. **Media Processing Agent**: Processes documents and images
15. **Evaluator Agent**: Evaluates responses before sending
16. **Cold Messaging Agent**: Sends follow-up messages

## 📋 Business Tiers

- **Free**: Basic features only (no logistics, upselling, inventory, analytics)
- **Gold**: Upselling, logistics, business analytics (no inventory, user analytics)
- **Platinum**: All features enabled

Tier restrictions can be disabled in development by setting `DEBUG=True` in config.

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+
- Docker & Docker Compose
- PostgreSQL (or Supabase)
- Redis

### Backend Setup

1. Clone the repository
2. Navigate to the backend directory:
```bash
cd app
```

3. Create a `.env` file:
```env
MODEL_NAME=gemini-2.0-flash
MODEL_API_KEY=your-api-key
DATABASE_URL=postgresql://user:password@host:5432/dbname
REDIS_URL=redis://:password@host:6379/0
DEBUG=False
```

4. Install dependencies:
```bash
pip install -r requirements.txt
```

5. Run with Docker Compose:
```bash
docker-compose up
```

Or run directly:
```bash
uvicorn main:app --reload
```

### Frontend Setup

1. Navigate to the frontend directory:
```bash
cd frontend
```

2. Install dependencies:
```bash
npm install
```

3. Create a `.env.local` file:
```env
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
```

4. Run the development server:
```bash
npm run dev
```

## 📁 Project Structure

```
ottobiz/
├── app/                          # Backend
│   ├── backend/
│   │   ├── api/                  # API endpoints
│   │   │   └── routers/
│   │   │       ├── customer.py
│   │   │       ├── business.py
│   │   │       ├── logistics.py
│   │   │       ├── analytics.py
│   │   │       ├── inventory.py
│   │   │       └── supply_chain.py
│   │   ├── chatbot/
│   │   │   └── agents/           # AI agents
│   │   │       ├── base_agent.py
│   │   │       ├── product_agent.py
│   │   │       ├── central_agent.py
│   │   │       ├── upselling_agent.py
│   │   │       └── ...
│   │   ├── db/                   # Database models and utilities
│   │   │   ├── models.py
│   │   │   ├── database.py
│   │   │   └── ...
│   │   ├── config.py             # Configuration
│   │   └── struct.py             # Pydantic schemas
│   ├── main.py                   # FastAPI app
│   ├── requirements.txt
│   ├── dockerfile
│   └── docker-compose.yml
├── frontend/                     # Frontend
│   ├── app/
│   │   └── page.tsx              # Main page
│   ├── package.json
│   └── ...
└── README.md
```

## 🔌 API Endpoints

### Customer
- `POST /api/v1/customer/chat` - Customer chat messages

### Business
- `POST /api/v1/business/chat` - Business owner messages

### Logistics
- `POST /api/v1/logistics/chat` - Logistics company messages
- `GET /api/v1/logistics/orders/{order_id}/tracking` - Order tracking

### Analytics
- `POST /api/v1/analytics/business` - Business analytics
- `POST /api/v1/analytics/user` - User analytics

### Inventory
- `POST /api/v1/inventory/` - Get inventory
- `POST /api/v1/inventory/update` - Update inventory

### Supply Chain
- `POST /api/v1/supply-chain/` - Get supply chain info

## 🧪 Testing

Test cases are located in `app/backend/tests/test_eval/`. Run tests with:
```bash
pytest app/backend/tests/
```

## 📊 Database Schema

Key tables:
- `users` - Customer information
- `businesses` - Business information (vendors, logistics, service providers)
- `products` - Product catalog
- `services` - Service offerings
- `orders` - Order management
- `transactions` - Payment transactions
- `inventory_items` - Inventory tracking
- `supply_chain` - Supply chain tracking
- `chat_history` - Conversation history
- `tickets` - Support tickets
- `invoices` - Generated invoices

## 🚢 Deployment

### Backend (Render.com)
1. Connect your GitHub repository
2. Set environment variables
3. Use build command: `pip install -r requirements.txt`
4. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`

### Frontend (Vercel)
1. Connect your GitHub repository
2. Set `NEXT_PUBLIC_BACKEND_URL` environment variable
3. Deploy automatically on push

## 📝 Environment Variables

### Backend
- `MODEL_NAME` - AI model name (default: gemini-2.0-flash)
- `MODEL_API_KEY` - AI model API key
- `DATABASE_URL` - PostgreSQL connection string
- `REDIS_URL` - Redis connection string
- `DEBUG` - Enable debug mode (disables tier restrictions)
- `SUPABASE_URL` - Supabase project URL
- `SUPABASE_KEY` - Supabase API key
- `PAYSTACK_PUBLIC_KEY` - Paystack public key (optional)
- `PAYSTACK_SECRET_KEY` - Paystack secret key (optional)

### Frontend
- `NEXT_PUBLIC_BACKEND_URL` - Backend API URL

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## 📄 License

[Your License Here]

## 🆘 Support

For issues and questions, please open an issue on GitHub.

## 🗺️ Roadmap

- [ ] Multimodal product retrieval
- [ ] Advanced forecasting
- [ ] Paystack integration
- [ ] Invoice generation
- [ ] Order tracking
- [ ] WhatsApp integration
- [ ] Mobile app

