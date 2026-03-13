# Ottobiz Frontend

Next.js frontend for the Ottobiz platform.

## Local Development Setup

### Prerequisites
- Node.js 18+ installed
- Backend running on `http://localhost:8000` (or update `.env.local`)

### Quick Start

1. **Install dependencies:**
```bash
cd frontend
npm install
```

2. **Environment variables are already configured** (`.env.local` exists)
   - Default backend URL: `http://localhost:8000`
   - To change: Edit `frontend/.env.local`

3. **Start development server:**
```bash
npm run dev
```

4. **Open browser:**
   - Frontend: http://localhost:3000
   - Make sure backend is running on http://localhost:8000

### Testing Locally

1. **Start Backend First:**
```bash
# In a separate terminal
cd app
uvicorn main:app --reload
```

2. **Start Frontend:**
```bash
# In frontend directory
npm run dev
```

3. **Test the Application:**
   - Open http://localhost:3000
   - Select a user and business persona
   - Start chatting in the customer window
   - Test business chat, logistics chat
   - Click analytics buttons to test endpoints

### Build for Production

```bash
npm run build
npm start
```

## Features

- **Customer Chat**: Interact as a customer with businesses
- **Business Chat**: Interact as a business owner
- **Logistics Chat**: Interact as a logistics company
- **Analytics**: View business and user analytics
- **Inventory Management**: Manage inventory
- **Supply Chain**: Track supply chain

## Deployment (Vercel)

1. Connect GitHub repository
2. Set environment variable `NEXT_PUBLIC_BACKEND_URL`
3. Deploy automatically

## Structure

- `app/page.tsx` - Main page with all chat interfaces
- `components/` - Reusable components
- `lib/` - Utility functions
