# Ottobiz Frontend

Next.js frontend for the Ottobiz platform.

## Setup

1. Install dependencies:
```bash
npm install
```

2. Create `.env.local`:
```env
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
```

3. Run development server:
```bash
npm run dev
```

4. Build for production:
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
