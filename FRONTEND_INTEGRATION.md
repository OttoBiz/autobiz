# Frontend-Backend Integration Guide

## Integration Status

### ✅ Fully Integrated Endpoints

1. **Customer Chat** (`/api/v1/customer/chat`)
   - ✅ Frontend sends FormData with files support
   - ✅ Backend handles both JSON and Form data
   - ✅ File uploads supported (images, PDFs, audio)

2. **Business Chat** (`/api/v1/business/chat`)
   - ✅ Frontend sends JSON
   - ✅ Backend accepts JSON
   - ✅ Endpoint path fixed to match frontend

3. **Logistics Chat** (`/api/v1/logistics/chat`)
   - ✅ Frontend sends JSON
   - ✅ Backend accepts JSON

4. **Business Analytics** (`/api/v1/analytics/business`)
   - ✅ Frontend sends JSON
   - ✅ Backend returns analytics data

5. **User Analytics** (`/api/v1/analytics/user`)
   - ✅ Frontend sends JSON
   - ✅ Backend returns user analytics

6. **Inventory Management** (`/api/v1/inventory/`)
   - ✅ Frontend sends JSON
   - ✅ Backend returns inventory data

7. **Supply Chain** (`/api/v1/supply-chain/`)
   - ✅ Frontend sends JSON
   - ✅ Backend returns supply chain data

## How the Frontend Works During Simulation/Demo

### Overview
The frontend provides a **3-way simulation interface** where you can test conversations between customers, businesses, and logistics companies simultaneously. It's designed to simulate the full Ottobiz platform workflow.

### Simulation Flow

#### 1. **Persona Selection** (Top Section)
   - **User Persona**: Select a customer (6 predefined users)
   - **Business Persona**: Select a vendor/business (5 predefined businesses)
   - **Logistics Persona**: Select a logistics company (3 predefined logistics)

#### 2. **Three-Way Chat Windows** (Main Section)
   Three side-by-side chat windows simulate different perspectives:

   **A. Customer Chat Window (Left)**
   - **Purpose**: Simulates customer interactions
   - **Features**:
     - Text input for customer messages
     - File upload button (📎) for receipts/images
     - Disabled until user + business selected
   - **Backend Flow**:
     1. Message sent to `/api/v1/customer/chat`
     2. Routing agent determines conversation stage
     3. Routes to appropriate agent (product, payment verification, logistics, etc.)
     4. Response displayed in chat window
   - **Use Cases**:
     - Product inquiries: "Do you have iPhone 15?"
     - Purchase intent: "I want to buy this product"
     - Payment verification: Upload receipt image
     - Delivery questions: "Where is my order?"

   **B. Business Chat Window (Middle)**
   - **Purpose**: Simulates business owner/vendor interactions
   - **Features**:
     - Text input for business messages
     - Disabled until business selected
   - **Backend Flow**:
     1. Message sent to `/api/v1/business/chat`
     2. Business chat agent processes request
     - Can access analytics tools
     - Can manage inventory
     - Can respond to central agent coordination requests
   - **Use Cases**:
     - "Show me my sales analytics"
     - "What products are low in stock?"
     - "Update product X stock to 50"
     - Responding to payment verification requests

   **C. Logistics Chat Window (Right)**
   - **Purpose**: Simulates logistics company interactions
   - **Features**:
     - Text input for logistics messages
     - Disabled until logistics selected
   - **Backend Flow**:
     1. Message sent to `/api/v1/logistics/chat`
     2. Central agent coordinates delivery logistics
   - **Use Cases**:
     - "Order #123 is ready for pickup"
     - "Delivery scheduled for tomorrow"
     - "Order delivered successfully"

#### 3. **Analytics Sections** (Bottom Section)
   Four analytics panels for testing business insights:

   **A. Business Analytics**
   - Click "Get Analytics" button
   - Shows: Sales, orders, revenue, top products
   - Updates based on selected business

   **B. User Analytics**
   - Click "Get Analytics" button
   - Shows: Spending habits, purchase history, recommendations
   - Updates based on selected user

   **C. Inventory Management**
   - Click "Get Inventory" button
   - Shows: Stock levels, low stock alerts
   - Updates based on selected business

   **D. Supply Chain**
   - Click "Get Supply Chain" button
   - Shows: Supplier orders, delivery status
   - Updates based on selected business

### Complete Demo Scenario

#### Scenario 1: Product Purchase Flow
1. **Select Personas**:
   - User: "John Doe"
   - Business: "Donrey Fashion"
   - Logistics: "Fast Delivery Co"

2. **Customer Window**:
   - Customer: "Do you have Nike sneakers?"
   - AI: "Yes, we have Nike sneakers available. Price: $120..."
   - Customer: "I want to buy them"
   - AI: "Here are our bank details for payment..."
   - Customer: [Uploads receipt image]
   - AI: "Payment verified! Processing your order..."

3. **Business Window** (automatically):
   - AI: "Payment verification request: Customer claims payment for Nike sneakers, Amount: $120. Please confirm."
   - Business: "Yes, payment received"
   - AI: "Order confirmed. Coordinating delivery..."

4. **Logistics Window** (automatically):
   - AI: "New delivery request: Order #123, Address: [customer address]"
   - Logistics: "Order picked up. Estimated delivery: 2 days"
   - AI: "Tracking number: TRK123456"

5. **Customer Window** (final):
   - AI: "Your order is on the way! Tracking: TRK123456"

#### Scenario 2: Business Analytics
1. Select Business: "Donrey Fashion"
2. Click "Business Analytics" button
3. View sales metrics, top products, revenue
4. Business can ask: "What products are selling best?"
5. AI responds with analytics insights

#### Scenario 3: Inventory Management
1. Select Business: "Donrey Fashion"
2. Click "Inventory" button
3. View current stock levels
4. Business can ask: "Update Nike sneakers stock to 50"
5. AI updates inventory via tool

### Key Features

1. **Real-time Multi-party Communication**
   - All three chat windows update independently
   - Central agent coordinates between parties
   - Messages flow automatically when needed

2. **File Upload Support**
   - Customer can upload receipt images/PDFs
   - Files processed by file_processor → media_processing_agent
   - Extracted data passed to payment verification agent

3. **State Management**
   - Each persona maintains separate chat history
   - User state persisted in Redis
   - Conversation context preserved across messages

4. **Analytics Integration**
   - Real-time analytics from database
   - Business insights displayed in JSON format
   - Can be queried via chat or buttons

### Testing Checklist

- [ ] Customer can inquire about products
- [ ] Customer can purchase products
- [ ] Customer can upload receipt for payment verification
- [ ] Business receives payment verification requests
- [ ] Business can view analytics
- [ ] Business can manage inventory
- [ ] Logistics receives delivery requests
- [ ] Central agent coordinates 3-way communication
- [ ] Analytics endpoints return data
- [ ] File uploads work correctly

### Environment Setup

**Frontend**:
```bash
cd frontend
npm install
# Set NEXT_PUBLIC_BACKEND_URL in .env.local
npm run dev
```

**Backend**:
```bash
cd app
pip install -r requirements.txt
# Set environment variables in .env
uvicorn main:app --reload
```

### API Endpoints Summary

| Endpoint | Method | Frontend | Backend | Status |
|----------|--------|----------|---------|--------|
| `/api/v1/customer/chat` | POST | ✅ FormData | ✅ FormData/JSON | ✅ |
| `/api/v1/business/chat` | POST | ✅ JSON | ✅ JSON | ✅ |
| `/api/v1/logistics/chat` | POST | ✅ JSON | ✅ JSON | ✅ |
| `/api/v1/analytics/business` | POST | ✅ JSON | ✅ JSON | ✅ |
| `/api/v1/analytics/user` | POST | ✅ JSON | ✅ JSON | ✅ |
| `/api/v1/inventory/` | POST | ✅ JSON | ✅ JSON | ✅ |
| `/api/v1/supply-chain/` | POST | ✅ JSON | ✅ JSON | ✅ |

All endpoints are fully integrated and ready for testing!
