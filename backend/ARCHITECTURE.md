# Backend Architecture

## Overview
Backend hiện tại là một **Thin API Gateway** chỉ phục vụ frontend và proxy requests đến AgentCore Runtime.

## Architecture Flow  
```
Frontend → Backend (API Gateway - port 8010)
              ↓ /chat/stream
         AgentCore Runtime (Agent - port 8080)
              ↓ MCP Gateway
    MCP Finance Server (AWS App Runner)
```

## Backend Routes

### 🤖 Core - AgentCore Integration
- **POST /chat/stream** - Streaming chat proxy to AgentCore Runtime
  - Handles SSE streaming from AgentCore
  - Auto-repairs mojibake encoding issues
  - Forwards user authentication token

### 👤 User Data Management
- **GET/POST /goals** - User financial goals CRUD
- **GET/POST /risk-profile** - User risk profile management
- **GET /notifications** - User notifications
- **GET /audit** - Audit logs

## Services

### Authentication
- **auth.py** - JWT token verification using Cognito
  - `verify_jwt()` - Validates bearer tokens
  - `current_user()` - FastAPI dependency for protected routes

### Data Storage
- **store.py** - In-memory data store (development)
  - goals, risk_profiles, notifications
  
- **supabase_rest.py** - Supabase client for production
  - Transaction storage
  - User profile data

## Key Changes (Cleanup v0.2.0)

### Removed ❌
- `app/services/finance/` - All financial logic → moved to MCP server
- `app/services/financial_tools.py` - MCP tool implementations
- `app/services/external_cashflow_provider.py`
- `app/routes/mcp.py` - MCP REST wrapper
- `app/routes/transactions.py` - Transaction processing
- `app/routes/forecast.py` - Cashflow forecasting
- `app/routes/decision.py` - Financial decisions  
- `app/routes/aggregates.py` - Spending analytics
- Heavy dependencies: numpy, pandas, statsmodels, darts, river, pyod

### Kept ✅
- Chat streaming (proxy to AgentCore)
- User data management (goals, risk profile, notifications)
- Authentication & authorization
- Database connections

## Dependencies
```
fastapi==0.112.2
uvicorn==0.30.6
python-jose==3.3.0       # JWT verification
requests==2.32.3         # HTTP client for AgentCore
pydantic==2.8.2
python-dotenv==1.0.1
```

## Environment Variables
```bash
# Cognito
COGNITO_USER_POOL_ID=us-east-1_xxxxxxx
COGNITO_CLIENT_ID=xxxxxx
COGNITO_REGION=us-east-1

# AgentCore Runtime
AGENTCORE_RUNTIME_ARN=arn:aws:bedrock-agentcore:...
AWS_REGION=us-east-1

# Database (optional - for production)
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=xxx
```

## Running Backend
```bash
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8010 --reload
```

## Testing
```bash
# Health check
curl http://localhost:8010/health

# Chat stream (with valid token)
curl -X POST http://localhost:8010/chat/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Analyze my spending"}'
```

## Design Principles

1. **Thin Gateway**: Backend không chứa business logic phức tạp
2. **Separation of Concerns**: Financial logic ở MCP server, backend chỉ route
3. **Stateless**: Không cache data, forward requests đến AgentCore
4. **Authentication Only**: Verify tokens, không authorize business rules
5. **Minimal Dependencies**: Chỉ giữ essentials cho API gateway

## Future Enhancements
- [ ] Add Redis cache for user sessions
- [ ] Add rate limiting per user
- [ ] Add observability (OpenTelemetry)
- [ ] Add request/response logging to CloudWatch
- [ ] Add health checks for downstream services
