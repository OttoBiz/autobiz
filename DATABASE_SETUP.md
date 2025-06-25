# 🗄️ Database Setup Guide

This guide will help you set up PostgreSQL and Redis for the WhatsApp AI Assistant project.

## 🎯 Overview

The project uses:
- **PostgreSQL** - Main database for business data (orders, products, customers, etc.)
- **Redis** - Session storage for conversation state and memory

## 🚀 Quick Start (Recommended)

### Option 1: Docker Setup (Easiest)

1. **Install Docker and Docker Compose**
   - [Docker Desktop](https://www.docker.com/products/docker-desktop/) (includes Docker Compose)

2. **Start the databases**
   ```bash
   # Start PostgreSQL and Redis
   docker-compose up -d postgres redis
   
   # Optional: Start Adminer (database web interface)
   docker-compose up -d adminer
   ```

3. **Create environment file**
   ```bash
   cp sample.env .env
   # Edit .env if needed (default values work for Docker setup)
   ```

4. **Create database tables and sample data**
   ```bash
   uv run python db_setup.py
   ```

5. **Verify setup**
   - Database: http://localhost:8080 (Adminer)
     - Server: `postgres`
     - Username: `postgres`
     - Password: `postgres`
     - Database: `whatsapp_ai`
   - Redis: `redis-cli ping` (if you have Redis CLI installed)

### Option 2: Manual Installation

#### PostgreSQL Setup

1. **Install PostgreSQL**
   ```bash
   # macOS
   brew install postgresql
   brew services start postgresql
   
   # Ubuntu/Debian
   sudo apt update
   sudo apt install postgresql postgresql-contrib
   sudo systemctl start postgresql
   
   # Windows
   # Download from https://www.postgresql.org/download/
   ```

2. **Create database and user**
   ```bash
   sudo -u postgres psql
   ```
   ```sql
   CREATE DATABASE whatsapp_ai;
   CREATE USER whatsapp_user WITH PASSWORD 'your_password';
   GRANT ALL PRIVILEGES ON DATABASE whatsapp_ai TO whatsapp_user;
   \q
   ```

3. **Update connection string in .env**
   ```env
   DATABASE_URL=postgresql://whatsapp_user:your_password@localhost:5432/whatsapp_ai
   ```

#### Redis Setup

1. **Install Redis**
   ```bash
   # macOS
   brew install redis
   brew services start redis
   
   # Ubuntu/Debian
   sudo apt install redis-server
   sudo systemctl start redis-server
   
   # Windows
   # Download from https://redis.io/download
   ```

2. **Verify Redis is running**
   ```bash
   redis-cli ping
   # Should return: PONG
   ```

## 🔧 Configuration

### Environment Variables

Create a `.env` file with your database configuration:

```env
# Database Configuration
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/whatsapp_ai
REDIS_URL=redis://localhost:6379/0

# Other settings...
```

### Database Tables

The project uses SQLModel to define database schema. Tables include:

- `business` - Business information
- `customer` - Customer data
- `product` - Product catalog
- `order` - Customer orders
- `orderitem` - Order line items
- `payment` - Payment transactions
- `delivery` - Delivery information

## 🛠️ Setup Script

The `db_setup.py` script handles:

1. **Connection testing** - Verifies database connectivity
2. **Table creation** - Creates all required tables
3. **Sample data** - Adds demo business and products

### Running the Setup Script

```bash
# Run the complete setup
uv run python db_setup.py

# Or run specific parts
uv run python -c "from db_setup import test_connection; test_connection()"
uv run python -c "from db_setup import create_tables; create_tables()"
```

## 📊 Database Management

### Viewing Data

**Using Adminer (Docker setup):**
1. Go to http://localhost:8080
2. Login with:
   - Server: `postgres`
   - Username: `postgres`
   - Password: `postgres`
   - Database: `whatsapp_ai`

**Using psql:**
```bash
# Connect to database
psql postgresql://postgres:postgres@localhost:5432/whatsapp_ai

# List tables
\dt

# View sample data
SELECT * FROM business;
SELECT * FROM product;
```

### Resetting Database

```bash
# Stop containers
docker-compose down

# Remove data volumes (WARNING: This deletes all data!)
docker-compose down -v

# Start fresh
docker-compose up -d postgres redis
uv run python db_setup.py
```

## 🔍 Troubleshooting

### Common Issues

1. **Connection refused**
   ```
   Error: connection to server at "localhost" (::1), port 5432 failed
   ```
   - **Solution**: Make sure PostgreSQL is running
   - **Docker**: `docker-compose up -d postgres`
   - **Manual**: Check PostgreSQL service status

2. **Database does not exist**
   ```
   Error: database "whatsapp_ai" does not exist
   ```
   - **Solution**: Create the database first
   - **Docker**: Database is auto-created
   - **Manual**: Run `CREATE DATABASE whatsapp_ai;` in psql

3. **Authentication failed**
   ```
   Error: password authentication failed for user "postgres"
   ```
   - **Solution**: Check credentials in `.env` file
   - **Docker**: Use `postgres:postgres` (default)
   - **Manual**: Use your created username/password

4. **Redis connection failed**
   ```
   Error: Redis connection failed
   ```
   - **Solution**: Make sure Redis is running
   - **Docker**: `docker-compose up -d redis`
   - **Manual**: `redis-server` or check service status

5. **Port already in use**
   ```
   Error: bind: address already in use
   ```
   - **Solution**: Change ports in `docker-compose.yml` or stop conflicting services

### Checking Status

```bash
# Check Docker containers
docker-compose ps

# Check container logs
docker-compose logs postgres
docker-compose logs redis

# Test connections
uv run python -c "from db_setup import test_connection; test_connection()"
```

## 📈 Production Setup

For production deployment:

1. **Use managed databases** (AWS RDS, Google Cloud SQL, etc.)
2. **Set strong passwords** and use environment variables
3. **Enable SSL/TLS** for database connections
4. **Set up backups** and monitoring
5. **Use connection pooling** for high traffic

Example production DATABASE_URL:
```env
DATABASE_URL=postgresql://username:password@your-db-host:5432/whatsapp_ai?sslmode=require
```

## 🧪 Testing

Verify everything works:

```bash
# Test database models
uv run python -c "from models import Business, Product; print('Models imported successfully')"

# Test database connection
uv run python -c "from db_setup import test_connection; test_connection()"

# Start the application
uv run uvicorn main:app --reload
```

## 📝 Notes

- The Docker setup is recommended for development
- Sample data includes a demo business and products
- Redis is used for session storage, not persistent data
- All timestamps use UTC timezone
- Database migrations can be added later using Alembic

## 🆘 Need Help?

1. Check the logs: `docker-compose logs`
2. Verify your `.env` configuration
3. Make sure all required services are running
4. Test connections individually
5. Check firewall/network settings

For additional help, refer to the main project documentation or create an issue.